"""Aplica las correcciones del golden set como entrenamiento de sinónimos.

Para cada línea revisada en una anotación gold:
  - Si el articulo_id gold coincide con lo que el sistema asigna → mark_confirmed
    (promueve el sinónimo a aprendido_confirmado)
  - Si difiere → add con origin='revisado' (degrada el sinónimo viejo,
    crea el nuevo como manual_confirmado)

Esto cierra el ciclo: revisión manual → entrenamiento del sistema.

Uso:
    python tools/golden_apply.py                          # todas las reviewed
    python tools/golden_apply.py golden/mystic_xxx.json   # una específica
    python tools/golden_apply.py --dry-run                # solo mostrar, no aplicar
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import SQL_FILE, SYNS_FILE
from src.pdf import detect_provider, get_last_extraction
from src.parsers import FORMAT_PARSERS
from src.matcher import Matcher, split_mixed_boxes, reclassify_assorted
from src.articulos import ArticulosLoader
from src.sinonimos import SynonymStore
from src.models import InvoiceLine

GOLDEN_DIR = Path(__file__).resolve().parent.parent / 'golden'
BASE = Path(r"C:\Users\diego.pereira\Desktop\DOC VERA\FACTURAS IMPORTACION\PROVEEDORES")


def _find_pdf(annotation: dict) -> Path | None:
    pdf_name = annotation.get('pdf', '')
    if not pdf_name:
        return None
    for folder in BASE.iterdir():
        if not folder.is_dir():
            continue
        candidate = folder / pdf_name
        if candidate.exists():
            return candidate
    return None


def _process_pdf(pdf_path: Path, matcher: Matcher) -> list[InvoiceLine]:
    """Procesa un PDF y devuelve las InvoiceLine con match del sistema."""
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
    ext_conf = extraction.confidence if extraction else 1.0
    ext_src = extraction.source if extraction else 'native'
    for l in lines:
        l.extraction_confidence = ext_conf
        if l.extraction_source == 'native':
            l.extraction_source = ext_src
    matched = matcher.match_all(pdata.get('id', 0), lines)
    return reclassify_assorted(matched)


def _match_gold_to_system(gold_lines: list[dict],
                          sys_lines: list[InvoiceLine]) -> list[tuple]:
    """Alinea líneas gold con las del sistema por variety+size."""
    sys_pool = list(sys_lines)
    pairs = []
    for gl in gold_lines:
        gv = gl.get('variety', '').strip().upper()
        gs = gl.get('size', 0)
        best_idx = None
        best_score = -1
        for i, sl in enumerate(sys_pool):
            sv = sl.variety.strip().upper()
            score = 0
            if gv == sv:
                score += 10
            elif gv and sv and (gv in sv or sv in gv):
                score += 5
            if gs == sl.size:
                score += 3
            if gl.get('stems') == sl.stems:
                score += 2
            if score > best_score:
                best_score = score
                best_idx = i
        if best_idx is not None and best_score >= 5:
            pairs.append((gl, sys_pool.pop(best_idx)))
        else:
            pairs.append((gl, None))
    return pairs


def apply_annotation(annotation: dict, syn: SynonymStore,
                     matcher: Matcher, dry_run: bool = False) -> dict:
    """Aplica correcciones de una anotación gold al SynonymStore."""
    pdf_path = _find_pdf(annotation)
    if not pdf_path:
        return {'error': f'PDF not found: {annotation.get("pdf")}'}

    provider_id = annotation.get('provider_id', 0)
    gold_lines = [l for l in annotation.get('lines', [])
                  if l.get('match_status') != 'rescue']
    sys_lines = _process_pdf(pdf_path, matcher)
    pairs = _match_gold_to_system(gold_lines, sys_lines)

    confirmed = 0
    corrected = 0
    skipped = 0

    for gl, sl in pairs:
        if gl is None or sl is None:
            skipped += 1
            continue

        gold_art_id = gl.get('articulo_id', 0)
        sys_art_id = sl.articulo_id or 0

        if not gold_art_id:
            skipped += 1
            continue

        if gold_art_id == sys_art_id:
            # Sistema acertó → confirmar sinónimo
            if dry_run:
                print(f'  [CONFIRM] {sl.variety} {sl.size}cm → {sl.articulo_name} (id={gold_art_id})')
            else:
                syn.mark_confirmed(provider_id, sl, gold_art_id)
            confirmed += 1
        else:
            # Sistema falló → corregir sinónimo
            gold_art_name = gl.get('articulo_name', '')
            if dry_run:
                print(f'  [CORRECT] {sl.variety} {sl.size}cm: '
                      f'sys={sys_art_id} ({sl.articulo_name}) → '
                      f'gold={gold_art_id} ({gold_art_name})')
            else:
                # add() con origin='revisado' degrada el viejo y crea el nuevo
                # como manual_confirmado
                syn.add(provider_id, sl, gold_art_id, gold_art_name,
                        origin='revisado')
            corrected += 1

    return {
        'provider_key': annotation.get('provider_key', ''),
        'invoice': annotation.get('invoice_number', ''),
        'confirmed': confirmed,
        'corrected': corrected,
        'skipped': skipped,
        'total': len(pairs),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('files', nargs='*', type=Path,
                    help='Archivos golden JSON (default: todos los reviewed en golden/)')
    ap.add_argument('--dry-run', action='store_true',
                    help='Solo mostrar qué haría, sin modificar sinónimos')
    args = ap.parse_args()

    # Determinar archivos
    if args.files:
        files = args.files
    else:
        files = sorted(GOLDEN_DIR.glob('*.json'))

    # Filtrar reviewed
    annotations = []
    for f in files:
        if f.name == 'golden_eval_results.json':
            continue
        data = json.loads(f.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            continue
        if data.get('_status') != 'reviewed':
            print(f'  Skip {f.name} (status={data.get("_status", "?")})', file=sys.stderr)
            continue
        annotations.append((f, data))

    if not annotations:
        print('No hay anotaciones reviewed. Revisa primero con golden_review.py.',
              file=sys.stderr)
        sys.exit(0)

    # Cargar recursos
    print('Cargando artículos y sinónimos...', file=sys.stderr, flush=True)
    art = ArticulosLoader()
    art.load_from_sql(str(SQL_FILE))
    syn = SynonymStore(str(SYNS_FILE))
    matcher = Matcher(art, syn)

    if args.dry_run:
        print('\n=== DRY RUN — no se modifican sinónimos ===\n')

    total_confirmed = 0
    total_corrected = 0

    for f, ann in annotations:
        pkey = ann.get('provider_key', '')
        inv = ann.get('invoice_number', '')
        print(f'Procesando {pkey}/{inv} ({f.name})...')

        result = apply_annotation(ann, syn, matcher, dry_run=args.dry_run)

        if 'error' in result:
            print(f'  ERROR: {result["error"]}')
            continue

        c = result['confirmed']
        x = result['corrected']
        s = result['skipped']
        total_confirmed += c
        total_corrected += x
        print(f'  ✓ {c} confirmados, ✗ {x} corregidos, — {s} skipped')

    print(f'\n{"=" * 50}')
    print(f'TOTAL: {total_confirmed} confirmados, {total_corrected} corregidos')
    if not args.dry_run and (total_confirmed or total_corrected):
        print(f'Sinónimos actualizados en {SYNS_FILE}')
    elif args.dry_run:
        print('(dry-run — nada modificado)')


if __name__ == '__main__':
    main()
