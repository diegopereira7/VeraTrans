"""Procesador no-interactivo de facturas PDF para VeraBuy Web.

Uso: python procesar_pdf.py <ruta_pdf>
Salida: JSON en stdout
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from src.pdf import detect_provider, get_last_ocr_confidence, get_last_extraction
from src.parsers import FORMAT_PARSERS
from src.articulos import ArticulosLoader
from src.sinonimos import SynonymStore
from src.matcher import Matcher, rescue_unparsed_lines, split_mixed_boxes, reclassify_assorted
from src.config import SQL_FILE, SYNS_FILE, HIST_FILE
from src.historial import History
from src.validate import validate_invoice
from src.reconciliation import reconcile
from src.llm_fallback import enrich_unparsed_lines


def run(pdf_path: str) -> dict:
    """Procesa un PDF y devuelve el resultado como dict JSON-serializable."""
    pdata = detect_provider(pdf_path)

    if not pdata:
        # Intentar con parsers aprendidos
        from src.learner import intentar_auto_parse
        from src.pdf import extract_text
        text = extract_text(pdf_path)
        auto_result = intentar_auto_parse(pdf_path, text)
        if auto_result['ok']:
            pdata = {
                'id': 0,
                'name': auto_result.get('learned_provider', 'Auto'),
                'fmt': 'auto_learned',
                'key': 'auto_learned',
                'text': text,
            }
            header = auto_result['header']
            lines = auto_result['lines']
            # Saltar al matching directamente
            return _process_with_lines(pdf_path, pdata, header, lines)

        # Sin parser aprendido para este PDF. Construimos un mensaje útil
        # que explique POR QUÉ y qué puede hacer el usuario, en vez de un
        # genérico "Proveedor no reconocido".
        info = auto_result.get('auto_learn_info') or {}
        candidato = info.get('proveedor_candidato')
        confianza = info.get('confianza_deteccion', 0)

        partes = ['Proveedor no reconocido en el PDF.']
        if candidato:
            partes.append(
                f'Detectado posible proveedor «{candidato}» '
                f'(confianza {int(confianza * 100)}%).'
            )
        partes.append(
            'El motor de auto-aprendizaje necesita al menos 2 facturas del '
            'mismo proveedor para inferir un parser nuevo. Sube varias '
            'juntas en «Importación Masiva» y, cuando termine el lote, el '
            'sistema generará el parser automáticamente.'
        )

        return {
            'ok': False,
            'error': ' '.join(partes),
            'auto_learn_info': info,
        }

    fmt = pdata.get('fmt', '')
    parser = FORMAT_PARSERS.get(fmt)
    if not parser:
        return {'ok': False, 'error': f'Sin parser para formato "{fmt}"'}

    # Nota: ya no comprobamos SQL_FILE.exists() — ArticulosLoader.load_from_sql
    # hace fallback automático a MySQL si el dump no está. La comprobación
    # bloqueaba todo el flujo aunque la BD estuviera disponible.

    # Inyectar ruta al PDF para parsers que necesiten acceso directo (ej: tablas)
    pdata['pdf_path'] = pdf_path

    header, lines = parser.parse(pdata['text'], pdata)

    # Fallback central: si el parser no extrajo header.total o extrajo un valor
    # claramente incorrecto, derivar de suma de líneas. Muchos parsers heredados
    # no tienen regex de total, o capturan un número equivocado del PDF.
    if lines:
        sum_lines = round(sum(l.line_total for l in lines if l.line_total), 2)
        if not header.total:
            header.total = sum_lines
        elif sum_lines and header.total:
            ratio = header.total / sum_lines if sum_lines else 999
            if ratio > 10 or ratio < 0.1:
                # Total extraído es >10x o <0.1x la suma — claramente incorrecto
                header.total = sum_lines

    return _process_with_lines(pdf_path, pdata, header, lines)


def _process_with_lines(pdf_path: str, pdata: dict, header, lines) -> dict:
    """Pipeline compartido: matching + serialización."""
    art = ArticulosLoader()
    art.load_from_sql(str(SQL_FILE))

    syn = SynonymStore(str(SYNS_FILE))
    matcher = Matcher(art, syn)

    lines = split_mixed_boxes(lines)
    rescued = rescue_unparsed_lines(pdata.get('text', ''), lines)
    pdf_name = Path(pdf_path).name if pdf_path else ''

    # Propaga la confianza del OCR y la señal de extracción a cada línea
    # ANTES de matchear — el matcher combina match_confidence con
    # ocr_confidence y extraction_confidence para bajar el score en
    # facturas escaneadas o con fuentes mixtas.
    ocr_conf = get_last_ocr_confidence()
    extraction = get_last_extraction()
    ext_conf = extraction.confidence if extraction else ocr_conf
    ext_source = extraction.source if extraction else 'native'
    ext_engine = extraction.ocr_engine if extraction else ''
    ext_degraded = bool(extraction and extraction.degraded)
    for l in lines:
        l.ocr_confidence = ocr_conf
        l.extraction_confidence = ext_conf
        # No pisar el 'rescue' que marca rescue_unparsed_lines.
        if l.extraction_source == 'native':
            l.extraction_source = ext_source
    for l in rescued:
        l.ocr_confidence = ocr_conf
        # rescued ya trae extraction_source='rescue' y confianza baja;
        # la multiplicamos por la confianza general para degradar más si
        # encima el PDF era OCR malo.
        l.extraction_confidence = round(min(l.extraction_confidence, ext_conf), 3)

    lines = matcher.match_all(pdata.get('id', 0), lines, invoice=pdf_name)
    lines = reclassify_assorted(lines)
    lines.extend(rescued)

    # LLM fallback — solo para sin_parser, y solo si la API key está disponible.
    # Si no, no-op. Nunca sustituye a los parsers deterministas.
    lines = enrich_unparsed_lines(lines)

    # Validación cruzada: anota errores en cada línea y devuelve resumen.
    header_validation = validate_invoice(header, lines)

    # Conciliación contra histórico de precios del proveedor (best-effort).
    provider_id = pdata.get('id', 0)
    reconciliation = reconcile(provider_id, lines) if provider_id else {
        'checked_lines': 0, 'with_history': 0, 'anomalies': 0, 'deltas': []}

    if len(lines) == 0:
        provider_name = pdata.get('name', 'desconocido')
        return {
            'ok': False,
            'error': f'El parser no extrajo líneas de producto ({provider_name})',
        }

    ok_count = sum(1 for l in lines if l.match_status == 'ok')
    no_parser = sum(1 for l in lines if l.match_status == 'sin_parser')
    mixed_box = sum(1 for l in lines if l.match_status == 'mixed_box')
    ambiguous = sum(1 for l in lines if l.match_status == 'ambiguous_match')

    # Registrar en historial
    try:
        hist = History(str(HIST_FILE))
        hist.add(
            header.invoice_number, pdf_name, header.provider_name,
            header.total, len(lines), ok_count,
            len(lines) - ok_count - no_parser - mixed_box,
            pdf_path=str(Path(pdf_path).resolve()) if pdf_path else '',
        )
    except Exception:
        pass  # no bloquear respuesta si falla historial

    raw_lines = _serialize_lines(lines)
    grouped_lines = _group_mixed_boxes(raw_lines)

    # "A Revisar" = todo lo que no está verde. `ambiguous_match` siempre
    # cuenta (por definición la línea está leída pero el artículo concreto
    # no está claro) además de las cubiertas en sesiones anteriores.
    needs_review = sum(
        1 for l in lines
        if l.match_status in ('sin_match', 'sin_parser', 'llm_extraido',
                              'ambiguous_match')
           or (l.match_status == 'ok' and 0 < l.match_confidence < 0.80)
           or (l.match_status == 'ok' and l.validation_errors)
    )

    return {
        'ok': True,
        'header': {
            'invoice_number': header.invoice_number,
            'date':           header.date,
            'awb':            header.awb,
            'hawb':           getattr(header, 'hawb', ''),
            'provider_name':  header.provider_name,
            'provider_id':    header.provider_id,
            'total':          header.total,
        },
        'stats': {
            'total_lineas': len(lines),
            'ok':           ok_count,
            'sin_match':    len(lines) - ok_count - no_parser - mixed_box - ambiguous,
            'sin_parser':   no_parser,
            'mixed_box':    mixed_box,
            'ambiguous':    ambiguous,
            'needs_review': needs_review,
            'ocr_confidence': ocr_conf,
            'extraction_confidence': ext_conf,
            'extraction_source': ext_source,
            'extraction_engine': ext_engine,
            'extraction_degraded': ext_degraded,
        },
        'validation':     header_validation,
        'reconciliation': reconciliation,
        'lines': grouped_lines,
    }


def _serialize_line(l) -> dict:
    """Convierte una InvoiceLine a dict JSON-serializable."""
    return {
        'raw':             l.raw_description[:120],
        'species':         l.species,
        'variety':         l.variety,
        'grade':           l.grade,
        'size':            l.size,
        'stems_per_bunch': l.stems_per_bunch,
        'stems':           l.stems,
        'price_per_stem':  round(l.price_per_stem, 5),
        'line_total':      round(l.line_total, 2),
        'label':           l.label,
        'box_type':        l.box_type,
        'articulo_id':     l.articulo_id,
        'articulo_name':   l.articulo_name or '',
        'match_status':    l.match_status,
        'match_method':    l.match_method,
        'ocr_confidence':   round(l.ocr_confidence, 3),
        'extraction_confidence': round(l.extraction_confidence, 3),
        'extraction_source': l.extraction_source,
        'match_confidence': round(l.match_confidence, 3),
        'link_confidence':  round(getattr(l, 'link_confidence', 0.0), 3),
        'candidate_margin': round(getattr(l, 'candidate_margin', 0.0), 3),
        'candidate_count':  getattr(l, 'candidate_count', 0),
        'match_reasons':    list(getattr(l, 'match_reasons', []) or []),
        'match_penalties':  list(getattr(l, 'match_penalties', []) or []),
        'top_candidates':   list(getattr(l, 'top_candidates', []) or []),
        'field_confidence': l.field_confidence,
        'validation_errors': list(l.validation_errors),
        'needs_review':     (l.match_status == 'ambiguous_match')
                            or (l.match_confidence > 0 and l.match_confidence < 0.80),
        'review_lane':      l.review_lane or 'quick',
    }


def _serialize_lines(lines) -> list[dict]:
    return [_serialize_line(l) for l in lines]


def _group_mixed_boxes(lines: list[dict]) -> list[dict]:
    """Agrupa líneas de cajas mixtas (box_type='MIX', mismo raw) bajo una fila padre.

    Las líneas normales pasan sin modificar con is_mixed=False.
    Las cajas mixtas generan una fila padre con totales + array de hijas.
    """
    from collections import OrderedDict

    groups: OrderedDict[str, list[int]] = OrderedDict()
    for i, l in enumerate(lines):
        if l.get('box_type') == 'MIX':
            key = l['raw']
            groups.setdefault(key, []).append(i)
        else:
            # Línea normal: clave única para que no se agrupe
            groups.setdefault(f'__single_{i}', []).append(i)

    result = []
    for key, indices in groups.items():
        if key.startswith('__single_'):
            line = lines[indices[0]]
            line['is_mixed'] = False
            result.append(line)
        elif len(indices) == 1:
            line = lines[indices[0]]
            line['is_mixed'] = False
            result.append(line)
        else:
            hijas = [lines[i] for i in indices]
            for h in hijas:
                h['is_mixed'] = True
            first = hijas[0]
            result.append({
                'row_type':    'mixed_parent',
                'raw':         first['raw'],
                'species':     first['species'],
                'grade':       first['grade'],
                'label':       first['label'],
                'stems':       sum(h['stems'] for h in hijas),
                'line_total':  round(sum(h['line_total'] for h in hijas), 2),
                'num_varieties': len(hijas),
                'children':    hijas,
                'is_mixed':    True,
            })
    return result


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    if len(sys.argv) < 2:
        print(json.dumps({'ok': False, 'error': 'Uso: procesar_pdf.py <ruta_pdf>'}))
        sys.exit(1)
    # Cualquier excepción se convierte en una respuesta JSON. El wrapper PHP
    # captura stdout+stderr (`2>&1`) así que si dejásemos propagar la excepción
    # el traceback se mezclaría con el JSON y el frontend sólo vería un error
    # genérico de parseo.
    try:
        result = run(sys.argv[1])
    except Exception as exc:
        import traceback
        result = {
            'ok': False,
            'error': f'Excepción procesando PDF: {exc}',
            'traceback': traceback.format_exc(),
        }
    print(json.dumps(result, ensure_ascii=False, default=str))
