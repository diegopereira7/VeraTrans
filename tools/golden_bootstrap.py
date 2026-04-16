"""Genera una anotación draft para el golden set a partir de la salida del pipeline.

Procesa un PDF, ejecuta el pipeline completo, y genera un JSON de
anotación que el operador debe revisar y corregir manualmente antes
de ser usado como verdad-terreno.

Uso:
    python tools/golden_bootstrap.py path/to/invoice.pdf
    python tools/golden_bootstrap.py path/to/invoice.pdf --output golden/provider_inv123.json

El JSON generado tiene status "draft" hasta que el operador lo revise.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
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


def bootstrap(pdf_path: str) -> dict:
    """Procesa un PDF y devuelve una anotación golden draft."""
    pdata = detect_provider(pdf_path)
    if not pdata:
        return {'error': f'Proveedor no detectado en {pdf_path}'}

    extraction = get_last_extraction()
    parser = FORMAT_PARSERS.get(pdata.get('fmt', ''))
    if not parser:
        return {'error': f'Sin parser para fmt={pdata.get("fmt")}'}

    pdata['pdf_path'] = pdf_path
    header, lines = parser.parse(pdata['text'], pdata)
    lines = split_mixed_boxes(lines)
    rescued = rescue_unparsed_lines(pdata['text'], lines)

    # Propagar extraction info
    ext_conf = extraction.confidence if extraction else 1.0
    ext_src = extraction.source if extraction else 'native'
    for l in lines:
        l.extraction_confidence = ext_conf
        if l.extraction_source == 'native':
            l.extraction_source = ext_src

    # Cargar artículos y sinónimos (una sola vez por invocación)
    art = ArticulosLoader()
    art.load_from_sql(str(SQL_FILE))
    syn = SynonymStore(str(SYNS_FILE))
    matcher = Matcher(art, syn)

    matched = matcher.match_all(pdata.get('id', 0), lines)
    matched = reclassify_assorted(matched)
    validate_invoice(header, matched)

    # Construir anotación
    gold_lines = []
    for l in matched:
        gold_lines.append({
            'raw_description': l.raw_description,
            'species': l.species,
            'variety': l.variety,
            'origin': l.origin,
            'size': l.size,
            'stems_per_bunch': l.stems_per_bunch,
            'bunches': l.bunches,
            'stems': l.stems,
            'line_total': l.line_total,
            'articulo_id': l.articulo_id,
            'articulo_name': l.articulo_name,
            'match_status': l.match_status,
            'match_confidence': round(l.match_confidence, 3) if l.match_confidence else 0,
            'link_confidence': round(l.link_confidence, 3) if l.link_confidence else 0,
            '_review': 'CHECK — verify variety, size, origin, articulo_id',
        })

    # Rescued lines (separadas para visibilidad)
    for l in rescued:
        gold_lines.append({
            'raw_description': l.raw_description,
            'species': l.species,
            'variety': l.variety,
            'origin': l.origin,
            'size': l.size,
            'stems_per_bunch': l.stems_per_bunch,
            'bunches': l.bunches,
            'stems': l.stems,
            'line_total': l.line_total,
            'articulo_id': 0,
            'articulo_name': '',
            'match_status': 'rescue',
            'match_confidence': 0,
            'link_confidence': 0,
            '_review': 'RESCUED — parser missed this line, verify if real product',
        })

    annotation = {
        '_status': 'draft',
        '_note': 'DRAFT — Review and correct ALL fields before marking as reviewed. '
                 'Delete _review fields and change _status to "reviewed" when done.',
        '_created': datetime.now().isoformat(timespec='seconds'),
        '_created_by': 'golden_bootstrap.py',
        'pdf': Path(pdf_path).name,
        'provider_key': pdata['key'],
        'provider_name': pdata.get('name', ''),
        'provider_id': pdata.get('id', 0),
        'invoice_number': header.invoice_number,
        'header_total': header.total,
        'extraction_source': ext_src,
        'extraction_confidence': round(ext_conf, 3),
        'lines': gold_lines,
    }
    return annotation


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('pdf', help='Ruta al PDF de factura')
    ap.add_argument('--output', '-o', type=Path, default=None,
                    help='Ruta del JSON de salida (default: golden/<provider>_<invoice>.json)')
    args = ap.parse_args()

    if not Path(args.pdf).exists():
        print(f'ERROR: no existe {args.pdf}', file=sys.stderr)
        sys.exit(1)

    print('Procesando...', file=sys.stderr, flush=True)
    result = bootstrap(args.pdf)

    if 'error' in result:
        print(f'ERROR: {result["error"]}', file=sys.stderr)
        sys.exit(1)

    # Determinar ruta de salida
    out = args.output
    if not out:
        GOLDEN_DIR.mkdir(exist_ok=True)
        pkey = result['provider_key']
        inv = result['invoice_number'] or 'unknown'
        out = GOLDEN_DIR / f'{pkey}_{inv}.json'

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                   encoding='utf-8')
    n = len(result['lines'])
    print(f'Golden draft: {out} ({n} líneas)', file=sys.stderr)
    print(f'  Provider: {result["provider_name"]} ({result["provider_key"]})')
    print(f'  Invoice:  {result["invoice_number"]}')
    print(f'  Lines:    {n}')
    print(f'  Status:   DRAFT — needs manual review')
    print(f'\nNext: open {out}, verify each line, then change _status to "reviewed"')


if __name__ == '__main__':
    main()
