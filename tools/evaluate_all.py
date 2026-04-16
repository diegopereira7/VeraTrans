"""Evaluación masiva in-process de los parsers + matcher actuales.

Corre el pipeline completo (extracción → parser → rescue → matcher) sobre
las muestras de cada proveedor y emite métricas por proveedor y globales.
A diferencia de la versión antigua, NO llama a `auto_learn_parsers.py
evaluate` por subprocess — ejecuta todo en el mismo proceso para
cargar artículos y sinónimos una sola vez (antes se cargaban 82 veces)
y para tener acceso a las señales finas del matcher (`link_confidence`,
`candidate_margin`, `ambiguous_match`, `match_penalties`,
`extraction_source`).

Outputs:
  - auto_learn_report.json           — por proveedor, con muestras raw
  - auto_learn_report.csv            — una fila por proveedor, columnas
                                       comparables en el tiempo
  - auto_learn_penalties_top.json    — ranking global de match_penalties
                                       más frecuentes (input para Paso 3
                                       del roadmap — taxonomía E1..E10)

Uso:
    python tools/evaluate_all.py
    python tools/evaluate_all.py --max-samples 5
    python tools/evaluate_all.py --provider AGRINAG   # filtrar
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import traceback
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import SQL_FILE, SYNS_FILE
from src.pdf import detect_provider, get_last_extraction
from src.parsers import FORMAT_PARSERS
from src.matcher import Matcher, rescue_unparsed_lines, split_mixed_boxes, reclassify_assorted
from src.articulos import ArticulosLoader
from src.sinonimos import SynonymStore
from src.validate import validate_invoice


BASE = Path(r"C:\Users\diego.pereira\Desktop\DOC VERA\FACTURAS IMPORTACION\PROVEEDORES")
OUT_JSON = Path(__file__).resolve().parent.parent / 'auto_learn_report.json'
OUT_CSV  = Path(__file__).resolve().parent.parent / 'auto_learn_report.csv'
OUT_PEN  = Path(__file__).resolve().parent.parent / 'auto_learn_penalties_top.json'

# Carpetas logísticas — NO son proveedores reales
LOGISTICS = {
    'ALLIANCE', 'DSV', 'SAFTEC', 'REAL CARGA', 'EXCELE CARGA',
    'LOGIZTIK', 'VERALEZA', 'FESO',
}

# Umbral para contar una línea como "autoaprobable" en la métrica.
# Coincide con el umbral operativo del matcher (link ≥ 0.80 ya da un
# buen carril) pero también exigimos ausencia de validation_errors,
# extraction_source != 'rescue' y margen suficiente (>= 0.05).
_AUTOAPPROVE_LINK_MIN = 0.80
_AUTOAPPROVE_MARGIN_MIN = 0.05


def _eval_one_pdf(pdf: Path, matcher: Matcher, global_penalties: Counter) -> dict:
    """Ejecuta el pipeline completo sobre un PDF y devuelve métricas."""
    entry = {
        'file': pdf.name,
        'detected_as': '', 'fmt': '',
        'parsed_lines': 0, 'rescued_lines': 0,
        'ok_lines': 0, 'ambiguous_lines': 0, 'sin_match_lines': 0,
        'sin_parser_lines': 0,
        'header_total': 0.0, 'sum_line_total': 0.0,
        'header_ok': None, 'diff_pct': None,
        'extraction_source': '', 'extraction_engine': '',
        'extraction_confidence': 1.0, 'extraction_degraded': False,
        'avg_link_confidence': 0.0,
        'autoapprovable_lines': 0,
        'needs_review_lines': 0,
        'validation_errors_lines': 0,
        'penalties': {},
        'match_statuses': {},
        'invoice': '',
        'error': '',
    }

    try:
        pdata = detect_provider(str(pdf))
        extraction = get_last_extraction()
        if extraction:
            entry['extraction_source'] = extraction.source
            entry['extraction_engine'] = extraction.ocr_engine
            entry['extraction_confidence'] = round(extraction.confidence, 3)
            entry['extraction_degraded'] = bool(extraction.degraded)

        if not pdata:
            entry['error'] = 'no detectado'
            return entry

        entry['detected_as'] = pdata.get('name', '')
        entry['fmt'] = pdata.get('fmt', '')
        parser = FORMAT_PARSERS.get(pdata.get('fmt', ''))
        if not parser:
            entry['error'] = f"sin parser para fmt='{entry['fmt']}'"
            return entry

        pdata['pdf_path'] = str(pdf)
        header, lines = parser.parse(pdata['text'], pdata)
        lines = split_mixed_boxes(lines)
        rescued = rescue_unparsed_lines(pdata['text'], lines)
        valid = [l for l in lines if l.variety and (l.stems or l.line_total)]

        # Fallback central: derivar header.total de suma de líneas si el parser
        # no lo extrajo o extrajo un valor claramente incorrecto (>10x o <0.1x)
        if lines:
            _sum = round(sum(l.line_total for l in lines if l.line_total), 2)
            if not header.total:
                header.total = _sum
            elif _sum and header.total:
                _ratio = header.total / _sum if _sum else 999
                if _ratio > 10 or _ratio < 0.1:
                    header.total = _sum

        entry['invoice'] = header.invoice_number
        entry['header_total'] = header.total
        entry['parsed_lines'] = len(valid)
        entry['rescued_lines'] = len(rescued)
        sum_lines = round(sum(l.line_total for l in lines), 2)
        entry['sum_line_total'] = sum_lines
        if header.total:
            diff = abs(sum_lines - header.total) / header.total
            entry['header_ok'] = diff <= 0.01
            entry['diff_pct'] = round(diff * 100, 2)

        # Propagar extraction_confidence a las líneas antes de matchear.
        ext_conf = entry['extraction_confidence']
        ext_src = entry['extraction_source'] or 'native'
        for l in lines:
            l.extraction_confidence = ext_conf
            if l.extraction_source == 'native':
                l.extraction_source = ext_src

        matched = matcher.match_all(pdata.get('id', 0), lines)
        matched = reclassify_assorted(matched)
        validate_invoice(header, matched)

        link_scores = []
        sample_penalties: Counter = Counter()
        sample_statuses: Counter = Counter()
        for l in matched:
            sample_statuses[l.match_status or 'unknown'] += 1
            if l.match_status == 'ok':
                entry['ok_lines'] += 1
            elif l.match_status == 'ambiguous_match':
                entry['ambiguous_lines'] += 1
            elif l.match_status == 'sin_match':
                entry['sin_match_lines'] += 1
            elif l.match_status == 'sin_parser':
                entry['sin_parser_lines'] += 1
            if l.validation_errors:
                entry['validation_errors_lines'] += 1
            if l.link_confidence and l.link_confidence > 0:
                link_scores.append(l.link_confidence)
            # Autoaprobable: ok + link alto + margen + sin errors + no rescue
            if (l.match_status == 'ok'
                    and l.link_confidence >= _AUTOAPPROVE_LINK_MIN
                    and l.candidate_margin >= _AUTOAPPROVE_MARGIN_MIN
                    and not l.validation_errors
                    and l.extraction_source != 'rescue'):
                entry['autoapprovable_lines'] += 1
            # Needs review: ambiguous o ok con baja conf o con errors
            if (l.match_status in ('sin_match', 'sin_parser', 'llm_extraido',
                                   'ambiguous_match')
                    or (l.match_status == 'ok' and 0 < l.match_confidence < 0.80)
                    or (l.match_status == 'ok' and l.validation_errors)):
                entry['needs_review_lines'] += 1
            # Agregar penalties al ranking (global + por muestra)
            for p in (l.match_penalties or []):
                # Normalizar "foreign_brand(XXX)" → "foreign_brand" para ranking
                head = p.split('(', 1)[0].strip()
                global_penalties[head] += 1
                sample_penalties[head] += 1
        entry['penalties'] = dict(sample_penalties)
        entry['match_statuses'] = dict(sample_statuses)
        # Contar carriles de revisión
        lane_counts = Counter(l.review_lane or 'quick' for l in matched)
        entry['lane_auto'] = lane_counts.get('auto', 0)
        entry['lane_quick'] = lane_counts.get('quick', 0)
        entry['lane_full'] = lane_counts.get('full', 0)

        if link_scores:
            entry['avg_link_confidence'] = round(
                sum(link_scores) / len(link_scores), 3)

    except Exception as e:
        entry['error'] = f'{type(e).__name__}: {e}'
        entry['traceback'] = traceback.format_exc()
    return entry


def _aggregate(folder_name: str, sample_entries: list[dict]) -> dict:
    """Resumen por proveedor a partir de las muestras."""
    n = len(sample_entries)
    total_parsed = sum(s['parsed_lines'] for s in sample_entries)
    total_rescued = sum(s['rescued_lines'] for s in sample_entries)
    total_ok = sum(s['ok_lines'] for s in sample_entries)
    total_ambig = sum(s['ambiguous_lines'] for s in sample_entries)
    total_sinm = sum(s['sin_match_lines'] for s in sample_entries)
    total_sinp = sum(s.get('sin_parser_lines', 0) for s in sample_entries)
    total_auto = sum(s['autoapprovable_lines'] for s in sample_entries)
    total_review = sum(s['needs_review_lines'] for s in sample_entries)
    total_valerrs = sum(s['validation_errors_lines'] for s in sample_entries)

    linkable = sum(s['ok_lines'] + s['ambiguous_lines'] for s in sample_entries)
    autoapprove_rate = (total_auto / linkable) if linkable else 0.0

    # Fuente de extracción más frecuente entre muestras
    src_counter = Counter(s['extraction_source'] or 'native'
                          for s in sample_entries)
    engine_counter = Counter(s['extraction_engine'] or '-'
                             for s in sample_entries)

    # Penalties agregadas por proveedor (no solo global)
    prov_penalties: Counter = Counter()
    prov_statuses: Counter = Counter()
    for s in sample_entries:
        for pen, cnt in s.get('penalties', {}).items():
            prov_penalties[pen] += cnt
        for st, cnt in s.get('match_statuses', {}).items():
            prov_statuses[st] += cnt

    metrics = {
        'samples':              n,
        'detected':             sum(1 for s in sample_entries if s['detected_as']),
        'parsed_any':           sum(1 for s in sample_entries if s['parsed_lines']),
        'totals_ok':            sum(1 for s in sample_entries if s.get('header_ok')),
        'total_parsed':         total_parsed,
        'total_rescued':        total_rescued,
        'ok_lines':             total_ok,
        'ambiguous_lines':      total_ambig,
        'sin_match_lines':      total_sinm,
        'sin_parser_lines':     total_sinp,
        'autoapprovable_lines': total_auto,
        'autoapprove_rate':     round(autoapprove_rate, 3),
        'needs_review_lines':   total_review,
        'validation_errors_lines': total_valerrs,
        'extraction_source_mix': dict(src_counter),
        'extraction_engine_mix': dict(engine_counter),
        'penalties':            dict(prov_penalties.most_common()),
        'match_statuses':       dict(prov_statuses),
    }
    return metrics


def _verdict(metrics: dict) -> str:
    """Bucket por proveedor (mantenido para compat con el reporte previo)."""
    n = metrics.get('samples', 0)
    if n == 0:
        return 'SIN_MUESTRAS'
    det = metrics.get('detected', 0)
    par = metrics.get('parsed_any', 0)
    tok = metrics.get('totals_ok', 0)
    if det < n:
        return 'NO_DETECTADO'
    if par < n:
        return 'NO_PARSEA'
    if tok < n * 0.6 and n > 1:
        return 'TOTALES_MAL'
    if metrics.get('total_rescued', 0) > metrics.get('total_parsed', 0):
        return 'MUCHO_RESCATE'
    return 'OK'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--max-samples', type=int, default=5)
    ap.add_argument('--provider', default='',
                    help='Filtrar por nombre de carpeta (case-insensitive substring)')
    args = ap.parse_args()

    # Cargar una sola vez (antes se cargaba 82 veces vía subprocess).
    print('Cargando artículos y sinónimos...', file=sys.stderr, flush=True)
    art = ArticulosLoader()
    art.load_from_sql(str(SQL_FILE))
    syn = SynonymStore(str(SYNS_FILE))
    matcher = Matcher(art, syn)
    print(f'  {len(art.articulos)} artículos, {syn.count()} sinónimos.',
          file=sys.stderr)

    folders = sorted(p for p in BASE.iterdir()
                     if p.is_dir() and p.name.upper() not in LOGISTICS)
    if args.provider:
        flt = args.provider.upper()
        folders = [f for f in folders if flt in f.name.upper()]
        if not folders:
            print(f'ERROR: ningún proveedor con filtro "{args.provider}"',
                  file=sys.stderr)
            sys.exit(2)

    report = []
    global_penalties: Counter = Counter()

    for i, folder in enumerate(folders, 1):
        print(f'[{i}/{len(folders)}] {folder.name}...',
              file=sys.stderr, flush=True)
        pdfs = sorted(folder.rglob('*.pdf')) or sorted(folder.rglob('*.PDF'))
        pdfs = pdfs[:args.max_samples]
        samples = [_eval_one_pdf(pdf, matcher, global_penalties)
                   for pdf in pdfs]
        metrics = _aggregate(folder.name, samples)
        report.append({
            'folder':  folder.name,
            'verdict': _verdict(metrics),
            **metrics,
            'samples_raw': samples,
        })

    # JSON detallado
    OUT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding='utf-8')

    # CSV resumen
    csv_cols = [
        'folder', 'verdict', 'samples', 'detected', 'parsed_any',
        'totals_ok', 'total_parsed', 'total_rescued',
        'ok_lines', 'ambiguous_lines', 'sin_match_lines',
        'sin_parser_lines',
        'autoapprovable_lines', 'autoapprove_rate',
        'needs_review_lines', 'validation_errors_lines',
    ]
    with OUT_CSV.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=csv_cols)
        w.writeheader()
        for r in report:
            w.writerow({c: r.get(c, '') for c in csv_cols})

    # Ranking global de penalties (entrada para taxonomía Paso 3)
    OUT_PEN.write_text(
        json.dumps({
            'top': global_penalties.most_common(30),
            'total_penalties': sum(global_penalties.values()),
        }, ensure_ascii=False, indent=2),
        encoding='utf-8')

    # Resumen por bucket
    buckets: dict[str, list[dict]] = {}
    for r in report:
        buckets.setdefault(r['verdict'], []).append(r)

    print('\n' + '=' * 70)
    print(f'EVALUACIÓN MASIVA — {len(report)} proveedores')
    print('=' * 70)
    for v in ('OK', 'TOTALES_MAL', 'MUCHO_RESCATE', 'NO_PARSEA',
              'NO_DETECTADO', 'SIN_MUESTRAS', 'ERROR'):
        rows = buckets.get(v, [])
        if not rows:
            continue
        print(f'\n{v} ({len(rows)}):')
        for r in rows:
            print(f"  {r['folder']:<20} "
                  f"det={r['detected']}/{r['samples']} "
                  f"parsed={r['parsed_any']}/{r['samples']} "
                  f"tot_ok={r['totals_ok']}/{r['samples']} "
                  f"lines={r['total_parsed']} ok={r['ok_lines']} "
                  f"ambig={r['ambiguous_lines']} "
                  f"auto={r['autoapprovable_lines']} "
                  f"rescued={r['total_rescued']}")

    # Globales
    total_lines = sum(r['total_parsed'] for r in report)
    total_ok = sum(r['ok_lines'] for r in report)
    total_ambig = sum(r['ambiguous_lines'] for r in report)
    total_auto = sum(r['autoapprovable_lines'] for r in report)
    total_review = sum(r['needs_review_lines'] for r in report)
    linkable = total_ok + total_ambig
    auto_rate = (total_auto / linkable) if linkable else 0.0

    print('\n' + '─' * 70)
    print('GLOBALES')
    print('─' * 70)
    print(f'  líneas totales:        {total_lines}')
    print(f'  ok:                    {total_ok}')
    print(f'  ambiguous_match:       {total_ambig}')
    print(f'  autoapprovable:        {total_auto}')
    print(f'  needs_review:          {total_review}')
    print(f'  autoapprove_rate:      {auto_rate*100:.1f}% de las linkables')
    print('\nTop penalties globales (entrada Paso 3):')
    for name, cnt in global_penalties.most_common(10):
        print(f'  {cnt:4d}  {name}')
    print(f'\nArtefactos: {OUT_JSON.name} · {OUT_CSV.name} · {OUT_PEN.name}')


if __name__ == '__main__':
    main()
