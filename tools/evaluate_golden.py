"""Evalúa el pipeline contra el golden set de verdad-terreno.

Lee cada anotación gold (status="reviewed") del directorio `golden/`,
procesa el PDF correspondiente, y compara línea a línea contra la
verdad-terreno.

Métricas:
  - Exactitud de parseo por campo (variety, size, origin, spb, stems, total)
  - Exactitud de artículo ERP (articulo_id match)
  - Aciertos completos por línea (todos los campos correctos)
  - Discrepancias principales (qué falla más)

Uso:
    python tools/evaluate_golden.py
    python tools/evaluate_golden.py --golden-dir golden/
    python tools/evaluate_golden.py --provider golden  # filtrar por provider_key
    python tools/evaluate_golden.py --verbose           # detalle por línea
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import SQL_FILE, SYNS_FILE
from src.pdf import detect_provider, get_last_extraction
from src.parsers import FORMAT_PARSERS
from src.matcher import Matcher, rescue_unparsed_lines, split_mixed_boxes, reclassify_assorted
from src.articulos import ArticulosLoader
from src.sinonimos import SynonymStore
from src.validate import validate_invoice

GOLDEN_DIR = Path(__file__).resolve().parent.parent / 'golden'
BASE = Path(r"C:\Users\diego.pereira\Desktop\DOC VERA\FACTURAS IMPORTACION\PROVEEDORES")

# Tolerancias para comparación numérica
_TOTAL_TOL = 0.02      # 2% para line_total
_STEMS_TOL = 0          # stems debe ser exacto


def _find_pdf(annotation: dict) -> Path | None:
    """Busca el PDF referenciado por la anotación."""
    pdf_name = annotation.get('pdf', '')
    if not pdf_name:
        return None

    # Buscar en la carpeta del proveedor
    pkey = annotation.get('provider_key', '')
    # Buscar en subdirectorios de BASE que contengan el nombre del proveedor
    for folder in BASE.iterdir():
        if not folder.is_dir():
            continue
        candidate = folder / pdf_name
        if candidate.exists():
            return candidate
    return None


def _process_pdf(pdf_path: Path, matcher: Matcher) -> list[dict]:
    """Procesa un PDF y devuelve las líneas como lista de dicts."""
    pdata = detect_provider(str(pdf_path))
    if not pdata:
        return []

    extraction = get_last_extraction()
    parser = FORMAT_PARSERS.get(pdata.get('fmt', ''))
    if not parser:
        return []

    pdata['pdf_path'] = str(pdf_path)
    header, lines = parser.parse(pdata['text'], pdata)
    lines = split_mixed_boxes(lines)
    rescued = rescue_unparsed_lines(pdata['text'], lines)

    ext_conf = extraction.confidence if extraction else 1.0
    ext_src = extraction.source if extraction else 'native'
    for l in lines:
        l.extraction_confidence = ext_conf
        if l.extraction_source == 'native':
            l.extraction_source = ext_src

    matched = matcher.match_all(pdata.get('id', 0), lines)
    matched = reclassify_assorted(matched)
    validate_invoice(header, matched)

    result = []
    for l in matched:
        result.append({
            'variety': l.variety,
            'species': l.species,
            'origin': l.origin,
            'size': l.size,
            'stems_per_bunch': l.stems_per_bunch,
            'bunches': l.bunches,
            'stems': l.stems,
            'line_total': l.line_total,
            'articulo_id': l.articulo_id,
            'articulo_name': l.articulo_name,
            'match_status': l.match_status,
            'link_confidence': l.link_confidence or 0,
        })
    return result


def _match_lines(gold_lines: list[dict], sys_lines: list[dict]) -> list[tuple]:
    """Alinea líneas gold con las del sistema por variety+size.

    Returns list of (gold_line, sys_line) tuples.
    gold_line or sys_line can be None if unmatched.
    """
    # Index system lines by (variety, size) for matching
    sys_pool = list(sys_lines)
    pairs = []

    for gl in gold_lines:
        gv = gl.get('variety', '').strip().upper()
        gs = gl.get('size', 0)
        best_idx = None
        best_score = -1

        for i, sl in enumerate(sys_pool):
            sv = sl.get('variety', '').strip().upper()
            ss = sl.get('size', 0)
            score = 0
            if gv == sv:
                score += 10
            elif gv and sv and (gv in sv or sv in gv):
                score += 5
            if gs == ss:
                score += 3
            elif gs and ss and abs(gs - ss) <= 10:
                score += 1
            # Prefer same stems count
            if gl.get('stems') == sl.get('stems'):
                score += 2
            if score > best_score:
                best_score = score
                best_idx = i

        if best_idx is not None and best_score >= 5:
            pairs.append((gl, sys_pool.pop(best_idx)))
        else:
            pairs.append((gl, None))

    # Remaining system lines (not matched to gold)
    for sl in sys_pool:
        pairs.append((None, sl))

    return pairs


def _compare_field(gold_val, sys_val, field: str) -> bool:
    """Compara un campo gold vs sistema con tolerancia."""
    if field == 'line_total':
        if gold_val == 0:
            return sys_val == 0
        return abs(gold_val - sys_val) / max(abs(gold_val), 0.01) <= _TOTAL_TOL
    if field == 'variety':
        return gold_val.strip().upper() == sys_val.strip().upper()
    if field == 'species':
        return gold_val.strip().upper() == sys_val.strip().upper()
    if field == 'origin':
        return gold_val.strip().upper() == sys_val.strip().upper()
    return gold_val == sys_val


# Campos de parseo que se evalúan
_PARSE_FIELDS = ['variety', 'species', 'origin', 'size', 'stems_per_bunch', 'stems', 'line_total']
# Campo de linking
_LINK_FIELD = 'articulo_id'


def evaluate_annotation(annotation: dict, matcher: Matcher,
                        verbose: bool = False) -> dict:
    """Evalúa una anotación gold contra la salida del sistema."""
    pdf_path = _find_pdf(annotation)
    if not pdf_path:
        return {'error': f'PDF not found: {annotation.get("pdf")}',
                'provider_key': annotation.get('provider_key', '')}

    gold_lines = [l for l in annotation.get('lines', [])
                  if l.get('match_status') != 'rescue']
    sys_lines = _process_pdf(pdf_path, matcher)

    pairs = _match_lines(gold_lines, sys_lines)

    # Contadores
    field_correct = Counter()
    field_total = Counter()
    link_correct = 0
    link_total = 0
    full_correct = 0
    full_total = 0
    discrepancies = []

    for gl, sl in pairs:
        if gl is None:
            # System produced a line not in gold (extra)
            discrepancies.append({
                'type': 'extra_system_line',
                'sys_variety': sl.get('variety', ''),
            })
            continue
        if sl is None:
            # Gold line not found in system output (missing)
            discrepancies.append({
                'type': 'missing_line',
                'gold_variety': gl.get('variety', ''),
                'gold_stems': gl.get('stems', 0),
            })
            full_total += 1
            for f in _PARSE_FIELDS:
                field_total[f] += 1
            if gl.get(_LINK_FIELD):
                link_total += 1
            continue

        full_total += 1
        all_ok = True

        # Evaluar campos de parseo
        for f in _PARSE_FIELDS:
            field_total[f] += 1
            gv = gl.get(f, 0 if f in ('size', 'stems_per_bunch', 'stems', 'line_total') else '')
            sv = sl.get(f, 0 if f in ('size', 'stems_per_bunch', 'stems', 'line_total') else '')
            if _compare_field(gv, sv, f):
                field_correct[f] += 1
            else:
                all_ok = False
                if verbose:
                    discrepancies.append({
                        'type': 'field_mismatch',
                        'field': f,
                        'gold': gv,
                        'system': sv,
                        'variety': gl.get('variety', ''),
                    })

        # Evaluar linking ERP
        gold_art = gl.get(_LINK_FIELD, 0)
        sys_art = sl.get(_LINK_FIELD, 0)
        if gold_art:
            link_total += 1
            if gold_art == sys_art:
                link_correct += 1
            else:
                all_ok = False
                discrepancies.append({
                    'type': 'link_mismatch',
                    'gold_variety': gl.get('variety', ''),
                    'gold_articulo': f"{gold_art} ({gl.get('articulo_name', '')})",
                    'sys_articulo': f"{sys_art} ({sl.get('articulo_name', '')})",
                })

        if all_ok:
            full_correct += 1

    return {
        'provider_key': annotation.get('provider_key', ''),
        'invoice': annotation.get('invoice_number', ''),
        'pdf': annotation.get('pdf', ''),
        'gold_lines': len(gold_lines),
        'sys_lines': len(sys_lines),
        'matched_pairs': sum(1 for g, s in pairs if g and s),
        'missing_lines': sum(1 for g, s in pairs if g and not s),
        'extra_lines': sum(1 for g, s in pairs if not g and s),
        'field_accuracy': {
            f: round(field_correct[f] / field_total[f], 3) if field_total[f] else None
            for f in _PARSE_FIELDS
        },
        'link_accuracy': round(link_correct / link_total, 3) if link_total else None,
        'link_correct': link_correct,
        'link_total': link_total,
        'full_line_accuracy': round(full_correct / full_total, 3) if full_total else None,
        'full_correct': full_correct,
        'full_total': full_total,
        'discrepancies': discrepancies[:30],  # cap para legibilidad
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--golden-dir', type=Path, default=GOLDEN_DIR)
    ap.add_argument('--provider', default='',
                    help='Filtrar por provider_key (substring)')
    ap.add_argument('--verbose', '-v', action='store_true',
                    help='Mostrar discrepancias por campo')
    args = ap.parse_args()

    gdir = args.golden_dir
    if not gdir.exists():
        print(f'ERROR: no existe {gdir}', file=sys.stderr)
        sys.exit(1)

    # Cargar anotaciones reviewed
    annotations = []
    for f in sorted(gdir.glob('*.json')):
        if f.name == 'golden_eval_results.json':
            continue
        data = json.loads(f.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('_status') != 'reviewed':
            continue
        if args.provider and args.provider.lower() not in data.get('provider_key', '').lower():
            continue
        annotations.append(data)

    if not annotations:
        print('No hay anotaciones con _status="reviewed" en el golden set.',
              file=sys.stderr)
        print(f'Directorio: {gdir}', file=sys.stderr)
        print('\nPara crear anotaciones draft:', file=sys.stderr)
        print('  python tools/golden_bootstrap.py path/to/invoice.pdf', file=sys.stderr)
        print('Luego revisa el JSON y cambia _status a "reviewed".', file=sys.stderr)
        sys.exit(0)

    # Cargar recursos una sola vez
    print('Cargando artículos y sinónimos...', file=sys.stderr, flush=True)
    art = ArticulosLoader()
    art.load_from_sql(str(SQL_FILE))
    syn = SynonymStore(str(SYNS_FILE))
    matcher = Matcher(art, syn)

    # Evaluar cada anotación
    results = []
    for ann in annotations:
        pkey = ann.get('provider_key', '')
        inv = ann.get('invoice_number', '')
        print(f'  Evaluando {pkey} / {inv}...', file=sys.stderr, flush=True)
        r = evaluate_annotation(ann, matcher, verbose=args.verbose)
        results.append(r)

    # Guardar JSON
    out_json = gdir / 'golden_eval_results.json'
    out_json.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str),
        encoding='utf-8')

    # Imprimir resumen
    print('\n' + '=' * 75)
    print('EVALUACIÓN GOLDEN SET')
    print('=' * 75)
    print(f'\nAnotaciones evaluadas: {len(results)}')

    # Agregar métricas
    all_field_correct = Counter()
    all_field_total = Counter()
    all_link_correct = 0
    all_link_total = 0
    all_full_correct = 0
    all_full_total = 0
    all_discrepancies = []

    for r in results:
        if 'error' in r:
            print(f'  ERROR {r["provider_key"]}: {r["error"]}')
            continue

        print(f'\n  {r["provider_key"]}/{r["invoice"]} ({r["pdf"]})')
        print(f'    Gold: {r["gold_lines"]} lines | System: {r["sys_lines"]} lines | '
              f'Matched: {r["matched_pairs"]} | Missing: {r["missing_lines"]} | '
              f'Extra: {r["extra_lines"]}')

        fa = r.get('field_accuracy', {})
        print(f'    Parse accuracy: ', end='')
        parts = []
        for f in _PARSE_FIELDS:
            v = fa.get(f)
            if v is not None:
                pct = v * 100
                mark = 'ok' if pct >= 95 else 'LOW' if pct < 80 else 'med'
                parts.append(f'{f}={pct:.0f}%')
        print(' | '.join(parts))

        la = r.get('link_accuracy')
        if la is not None:
            print(f'    Link accuracy:  {la*100:.0f}% ({r["link_correct"]}/{r["link_total"]})')
        fla = r.get('full_line_accuracy')
        if fla is not None:
            print(f'    Full accuracy:  {fla*100:.0f}% ({r["full_correct"]}/{r["full_total"]})')

        # Aggregate
        for f in _PARSE_FIELDS:
            if fa.get(f) is not None:
                all_field_total[f] += r.get('full_total', 0)
                all_field_correct[f] += int(fa[f] * r.get('full_total', 0))
        all_link_correct += r.get('link_correct', 0)
        all_link_total += r.get('link_total', 0)
        all_full_correct += r.get('full_correct', 0)
        all_full_total += r.get('full_total', 0)
        all_discrepancies.extend(r.get('discrepancies', []))

        # Top discrepancies
        if r.get('discrepancies') and args.verbose:
            print('    Discrepancies:')
            for d in r['discrepancies'][:10]:
                dtype = d.get('type', '')
                if dtype == 'link_mismatch':
                    print(f'      LINK: {d.get("gold_variety","")} — '
                          f'gold={d.get("gold_articulo","")} vs sys={d.get("sys_articulo","")}')
                elif dtype == 'field_mismatch':
                    print(f'      FIELD: {d.get("variety","")} — '
                          f'{d.get("field","")}={d.get("gold","")} vs {d.get("system","")}')
                elif dtype == 'missing_line':
                    print(f'      MISSING: {d.get("gold_variety","")} stems={d.get("gold_stems",0)}')

    # Global summary
    if all_full_total:
        print('\n' + '─' * 75)
        print('GLOBAL')
        print('─' * 75)
        print(f'  Total gold lines: {all_full_total}')
        for f in _PARSE_FIELDS:
            if all_field_total[f]:
                pct = all_field_correct[f] / all_field_total[f] * 100
                print(f'  {f:<20} {pct:>6.1f}%')
        if all_link_total:
            print(f'  {"articulo_id":<20} {all_link_correct/all_link_total*100:>6.1f}% '
                  f'({all_link_correct}/{all_link_total})')
        print(f'  {"full_line":<20} {all_full_correct/all_full_total*100:>6.1f}% '
              f'({all_full_correct}/{all_full_total})')

    # Top discrepancy types
    if all_discrepancies:
        dtype_counter = Counter(d['type'] for d in all_discrepancies)
        print(f'\n  Top discrepancy types:')
        for dtype, cnt in dtype_counter.most_common(5):
            print(f'    {cnt:>4}  {dtype}')

    print(f'\nArtefacto: {out_json.name}')


if __name__ == '__main__':
    main()
