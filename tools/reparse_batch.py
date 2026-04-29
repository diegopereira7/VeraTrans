"""Re-procesa un batch desde cero (parser + matcher) preservando
ediciones manuales del operador.

A diferencia de ``rematch_batch.py`` (que solo re-corre el matcher
sobre líneas ya parseadas), este script vuelve a extraer texto del
PDF y re-parsear con la pipeline actual. Útil cuando hay un fix de
parser y el operador ya hizo correcciones manuales que no quiere
perder.

Estrategia de preservación:
  - Las correcciones de artículo (✓/✗ en la UI) se persisten como
    sinónimos en ``sinonimos_universal.json``; el matcher las
    re-aplica automáticamente al re-procesar.
  - Las ediciones por línea sí se preservan explícitamente:
      * ``_deleted`` (línea borrada por el operador).
      * ``label`` (destino editado a mano).
      * ``articulo_id``/``articulo_name`` cuando el operador asignó
        un artículo específico que el matcher actual no propondría.
  - El matching old↔new se hace por ``raw_description`` (clave más
    estable). Si hay N líneas viejas con el mismo raw que ahora
    colapsan a 1 nueva (split→merge), se toma la nueva tal cual y se
    descartan las correcciones de las sublíneas — ese es justo el
    caso que motivó el reproceso.

Uso:
    python tools/reparse_batch.py <batch_id>
    python tools/reparse_batch.py batch_status/<batch_id>.json
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.articulos import ArticulosLoader  # noqa: E402
from src.config import PROVIDERS, SYNS_FILE  # noqa: E402
from src.matcher import (  # noqa: E402
    Matcher,
    rescue_unparsed_lines,
    split_mixed_boxes,
    reclassify_assorted,
)
from src.parsers import FORMAT_PARSERS  # noqa: E402
from src.pdf import detect_provider, get_last_extraction  # noqa: E402
from src.sinonimos import SynonymStore  # noqa: E402
from src.validate import validate_invoice  # noqa: E402


BATCH_STATUS_DIR = _ROOT / 'batch_status'
BATCH_UPLOADS_DIR = _ROOT / 'batch_uploads'


def _resolve_batch(arg: str) -> tuple[Path, Path]:
    """Devuelve (status_json_path, uploads_dir_path) para el batch."""
    p = Path(arg)
    if p.exists() and p.is_file():
        batch_id = p.stem
        status = p
    else:
        batch_id = arg
        status = BATCH_STATUS_DIR / f'{batch_id}.json'
        if not status.exists():
            raise FileNotFoundError(f'No se encontró {status}')
    uploads = BATCH_UPLOADS_DIR / batch_id
    if not uploads.is_dir():
        raise FileNotFoundError(f'No se encontró carpeta uploads {uploads}')
    return status, uploads


def _line_to_dict(il: Any) -> dict:
    """Serializa un InvoiceLine al formato que usa batch_status."""
    return {
        'raw_description': il.raw_description,
        'raw': il.raw_description,
        'species': il.species,
        'variety': il.variety,
        'grade': il.grade,
        'origin': il.origin,
        'size': il.size,
        'stems_per_bunch': il.stems_per_bunch,
        'bunches': il.bunches,
        'stems': il.stems,
        'price_per_stem': il.price_per_stem,
        'price_per_bunch': il.price_per_bunch,
        'line_total': il.line_total,
        'total_line': il.line_total,
        'label': il.label,
        'farm': il.farm,
        'box_type': il.box_type,
        'articulo_id': il.articulo_id,
        'articulo_name': il.articulo_name,
        'match_status': il.match_status,
        'match_method': il.match_method,
        'ocr_confidence': il.ocr_confidence,
        'extraction_confidence': il.extraction_confidence,
        'extraction_source': il.extraction_source,
        'match_confidence': il.match_confidence,
        'confidence': il.match_confidence,
        'link_confidence': il.link_confidence,
        'candidate_margin': il.candidate_margin,
        'candidate_count': il.candidate_count,
        'match_reasons': list(il.match_reasons),
        'match_penalties': list(il.match_penalties),
        'top_candidates': list(il.top_candidates),
        'validation_errors': list(il.validation_errors),
        'review_lane': il.review_lane,
    }


def _build_old_index(old_lines: list[dict]) -> dict[str, list[int]]:
    """Indexa líneas viejas por raw_description (lower+strip)."""
    idx: dict[str, list[int]] = defaultdict(list)
    for i, l in enumerate(old_lines):
        raw = (l.get('raw_description') or l.get('raw') or '').strip().lower()
        if raw:
            idx[raw].append(i)
    return idx


def _preserve_user_edits(new_line: dict, old_lines: list[dict]) -> dict:
    """Aplica overrides del operador desde una vieja línea sobre la nueva.

    Reglas:
      - Si CUALQUIER vieja tiene ``_deleted=True``, marcar la nueva como
        deleted (asume que el operador quería esa caja fuera).
      - ``label``: si vieja tiene label no vacío, usarlo (el parser
        actual también lo intenta extraer; si coinciden no pasa nada,
        si difieren preferimos el del operador).
      - ``articulo_id``: si la vieja tenía match ok con un articulo_id
        distinto al que propone el matcher ahora **y** la nueva quedó
        en sin_match/ambiguous, tomamos el de la vieja como ancla
        manual. Si el matcher actual ya propone uno con ok, gana el
        nuevo (probablemente vino del sinónimo aprendido).
    """
    if not old_lines:
        return new_line

    # _deleted: cualquiera basta para propagar
    if any(l.get('_deleted') for l in old_lines):
        new_line['_deleted'] = True

    # label: tomar el primer no-vacío de las viejas. El parser actual
    # rellena label si la línea lo trae; el operador puede haberlo
    # editado a mano. Preferimos su versión si la hay.
    old_labels = [str(l.get('label') or '').strip() for l in old_lines]
    old_labels = [s for s in old_labels if s]
    if old_labels:
        # Si todas las viejas comparten el mismo label, claramente
        # querido por el operador. Si difieren (muy raro porque
        # sublíneas hereden), escoger el primero.
        new_line['label'] = old_labels[0]

    # articulo_id manual: si la vieja tenía un matched concreto y
    # la nueva quedó sin/ambiguous, conservar la elección manual.
    new_status = new_line.get('match_status') or ''
    if new_status in ('sin_match', 'ambiguous_match'):
        for old in old_lines:
            if (old.get('articulo_id')
                    and old.get('match_status') == 'ok'
                    and (old.get('match_method') or '').lower()
                    in ('manual', 'sinónimo', 'sinonimo', 'synonym')):
                new_line['articulo_id'] = old['articulo_id']
                new_line['articulo_name'] = old.get('articulo_name', '')
                new_line['match_status'] = 'ok'
                new_line['match_method'] = old.get('match_method', 'manual')
                new_line['match_confidence'] = old.get(
                    'match_confidence', old.get('confidence', 0.95))
                new_line['confidence'] = new_line['match_confidence']
                new_line['link_confidence'] = old.get('link_confidence', 0.95)
                new_line['review_lane'] = 'auto'
                new_line['validation_errors'] = []
                break

    return new_line


def _recompute_invoice_stats(inv: dict) -> None:
    """Espejo de _recompute en api.php — para que la UI muestre bien."""
    flagged = {'ambiguous_match', 'sin_match', 'sin_parser',
               'mixed_box', 'llm_extraido', 'pendiente'}
    ok = sin = needs = 0
    lines = [l for l in (inv.get('lines') or []) if not l.get('_deleted')]
    for l in lines:
        st = l.get('match_status') or ''
        if st == 'ok':
            ok += 1
        elif st == 'sin_match':
            sin += 1
        conf = float(l.get('confidence') or l.get('match_confidence') or 0)
        errs = l.get('validation_errors') or []
        flag_status = st in flagged
        if (flag_status
                or (isinstance(errs, list) and len(errs) > 0)
                or conf < 0.84):
            needs += 1
    inv['ok_count'] = ok
    inv['sin_match'] = sin
    inv['needs_review'] = needs
    inv['lineas'] = len(lines)
    inv['total_usd'] = round(sum(
        float(l.get('line_total') or l.get('total_line') or 0)
        for l in lines), 2)


def _process_pdf(pdf_path: Path, matcher: Matcher) -> tuple[Any, list[Any], dict]:
    """Pipeline completa: extracción → parser → split → rescue → matcher.

    Réplica del orden de ``procesar_pdf._process_with_lines`` para que
    el output tenga las mismas garantías (incluye señal extraction y
    rescued separadamente).
    """
    pdata = detect_provider(str(pdf_path))
    if not pdata:
        return None, [], {}
    # AlegriaParser y otros parsers tabulares usan `pdata['pdf_path']`
    # para abrir el PDF con pdfplumber.extract_tables(). procesar_pdf
    # lo añade en su pipeline; aquí también.
    pdata['pdf_path'] = str(pdf_path)
    fmt = pdata.get('fmt')
    parser = FORMAT_PARSERS.get(fmt)
    if not parser:
        return None, [], {}
    text = pdata.get('text', '')
    try:
        header, lines = parser.parse(text, pdata)
    except Exception:  # noqa: BLE001
        return None, [], {}

    lines = split_mixed_boxes(lines)
    rescued = rescue_unparsed_lines(text, lines)

    ext = get_last_extraction()
    ext_conf = ext.confidence if ext else 1.0
    ext_source = ext.source if ext else 'native'
    # ocr_confidence histórico: 1.0 si nativo, ext_conf si OCR.
    ocr_conf = ext_conf if (ext and ext.is_ocr) else 1.0
    for l in lines:
        l.ocr_confidence = ocr_conf
        l.extraction_confidence = ext_conf
        if l.extraction_source == 'native':
            l.extraction_source = ext_source
    for l in rescued:
        l.ocr_confidence = ocr_conf
        l.extraction_confidence = round(
            min(l.extraction_confidence, ext_conf), 3)

    matched = matcher.match_all(pdata['id'], lines,
                                invoice=header.invoice_number or '')
    matched = reclassify_assorted(matched)
    matched.extend(rescued)

    validation = validate_invoice(header, matched)
    return header, matched, validation


def reparse_batch(status_path: Path, uploads_dir: Path) -> dict:
    """Re-procesa todos los PDFs del batch, escribiendo el status in-place."""
    with status_path.open('r', encoding='utf-8') as f:
        data = json.load(f)

    art = ArticulosLoader()
    art.load_from_db()
    syn = SynonymStore(str(SYNS_FILE))
    matcher = Matcher(art, syn)

    facturas = 0
    nuevos_parseados = 0
    preservados = 0
    fallos: list[str] = []

    with syn.batch():
        for inv in data.get('resultados') or []:
            pdf_name = inv.get('pdf') or ''
            if not pdf_name:
                continue
            pdf_path = uploads_dir / pdf_name
            if not pdf_path.exists():
                fallos.append(f'{pdf_name}: PDF no encontrado en uploads')
                continue
            facturas += 1

            old_lines = list(inv.get('lines') or [])
            old_idx = _build_old_index(old_lines)

            header, matched, validation = _process_pdf(pdf_path, matcher)
            if header is None:
                fallos.append(f'{pdf_name}: error en pipeline')
                continue

            new_lines: list[dict] = []
            for il in matched:
                d = _line_to_dict(il)
                raw_key = (d.get('raw_description') or '').strip().lower()
                old_matches = [old_lines[i] for i in old_idx.get(raw_key, [])]
                if old_matches:
                    _preserve_user_edits(d, old_matches)
                    preservados += 1
                new_lines.append(d)

            # Conservar líneas viejas marcadas _deleted aunque no
            # aparezcan en la nueva extracción (registro histórico).
            # Sólo si su raw_description no quedó cubierto por una
            # nueva línea (caso típico: el operador borró una línea
            # y queremos que siga reflejada como borrada).
            new_raws = {(d.get('raw_description') or '').strip().lower()
                        for d in new_lines}
            for old in old_lines:
                if not old.get('_deleted'):
                    continue
                raw = (old.get('raw_description')
                       or old.get('raw') or '').strip().lower()
                if raw and raw not in new_raws:
                    new_lines.append(old)

            inv['lines'] = new_lines
            nuevos_parseados += len(new_lines)

            # Si el parser ahora sí extrae líneas, marcar la factura
            # como ok y rellenar metadata de cabecera (antes podía
            # tener ok=False y error="Parser X no extrajo líneas").
            if new_lines:
                inv['ok'] = True
                inv['error'] = None
                if not inv.get('provider'):
                    inv['provider'] = header.provider_name or ''
                if not inv.get('provider_id'):
                    inv['provider_id'] = header.provider_id or 0
                if not inv.get('invoice'):
                    inv['invoice'] = header.invoice_number or ''
                if not inv.get('date'):
                    inv['date'] = header.date or ''

            # Recalcular validación cruzada (sum_lines vs header_total)
            # contra los nuevos totales: si una línea antes oculta ahora
            # parsea, el aviso "Parcial" debe disparar/desaparecer según
            # corresponda. Sin esto el JSON queda con sum_lines viejo.
            inv['validation'] = validation

            _recompute_invoice_stats(inv)

    # Recalcular counters globales del batch (la UI los lee del root)
    res_list = data.get('resultados') or []
    procesadas_ok = sum(1 for inv in res_list if inv.get('ok'))
    con_error = sum(1 for inv in res_list if not inv.get('ok'))
    total_lineas = sum(inv.get('lineas', 0) or 0 for inv in res_list)
    total_ok = sum(inv.get('ok_count', 0) or 0 for inv in res_list)
    total_sin = sum(inv.get('sin_match', 0) or 0 for inv in res_list)
    total_review = sum(inv.get('needs_review', 0) or 0 for inv in res_list)
    total_usd = round(sum(inv.get('total_usd', 0) or 0 for inv in res_list), 2)

    resumen = data.get('resumen') or {}
    resumen.update({
        'procesadas_ok': procesadas_ok,
        'con_error': con_error,
        'total_lineas': total_lineas,
        'total_ok': total_ok,
        'total_sin_match': total_sin,
        'total_needs_review': total_review,
        'total_usd': total_usd,
    })
    data['resumen'] = resumen
    data['procesados_ok'] = procesadas_ok
    data['con_error'] = con_error

    # Escritura atómica
    tmp = status_path.with_suffix(status_path.suffix + '.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    tmp.replace(status_path)

    return {
        'facturas': facturas,
        'lineas_nuevas': nuevos_parseados,
        'lineas_preservadas': preservados,
        'fallos': fallos,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print('Uso: python tools/reparse_batch.py <batch_id|ruta>',
              file=sys.stderr)
        return 2
    try:
        status_path, uploads_dir = _resolve_batch(argv[1])
    except FileNotFoundError as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 1

    summary = reparse_batch(status_path, uploads_dir)
    print(json.dumps({'ok': True, 'path': str(status_path), **summary},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
