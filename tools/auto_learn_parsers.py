"""Utilidades de apoyo al auto-aprendizaje de parsers.

Este módulo ya NO llama a ninguna API. Lo usa Claude Code (el agente) para:

  1. validate_parser_against_samples(provider_key, folder) → ejecuta el parser
     recién escrito contra las 5 muestras del proveedor y devuelve qué extrajo.
     Se invoca con `python tools/auto_learn_parsers.py validate AGRINAG ...`.

  2. register_learned_parser(provider_key, fmt_name) → añade el import al
     __init__.py y cambia fmt='unknown' por el nuevo en config.py.
     `python tools/auto_learn_parsers.py register AGRINAG auto_agrinag`.

Flujo típico:
  - Agente extrae muestras con tools/extract_samples.py
  - Agente escribe src/parsers/auto_NAME.py con Write
  - Agente llama `validate AGRINAG <carpeta>` para comprobar
  - Si OK → `register AGRINAG auto_agrinag`
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from src.pdf import extract_text, detect_provider
from src.config import PROVIDERS
from src.parsers import FORMAT_PARSERS

PARSERS_DIR   = Path(__file__).resolve().parent.parent / 'src' / 'parsers'
CONFIG_PATH   = Path(__file__).resolve().parent.parent / 'src' / 'config.py'
REGISTRY_PATH = PARSERS_DIR / '__init__.py'


def cmd_validate(args):
    """Ejecuta un parser contra las muestras de su carpeta y reporta qué extrajo.

    El parser ya debe estar escrito en src/parsers/<fmt_name>.py exportando
    `class AutoParser`. Devuelve JSON con conteos por muestra para inspección.
    """
    provider_key = args.provider_key
    provider = PROVIDERS.get(provider_key)
    if not provider:
        print(f'ERROR: {provider_key} no existe en PROVIDERS', file=sys.stderr)
        sys.exit(2)

    fmt_name = args.fmt_name or f'auto_{provider_key}'
    parser_path = PARSERS_DIR / f'{fmt_name}.py'
    if not parser_path.exists():
        print(f'ERROR: {parser_path} no existe', file=sys.stderr)
        sys.exit(2)

    # Cargar parser
    spec = importlib.util.spec_from_file_location(fmt_name, parser_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    parser_cls = getattr(mod, 'AutoParser', None)
    if not parser_cls:
        print(f'ERROR: {parser_path} no exporta AutoParser', file=sys.stderr)
        sys.exit(2)

    # Muestras
    folder = Path(args.folder)
    pdfs = sorted(folder.rglob('*.pdf')) or sorted(folder.rglob('*.PDF'))
    pdfs = pdfs[:args.max_samples]
    report = {'provider': provider_key, 'folder': str(folder), 'samples': []}

    for pdf in pdfs:
        entry = {'file': pdf.name, 'lines': 0, 'sample_lines': [], 'error': ''}
        try:
            text = extract_text(str(pdf))
            h, lines = parser_cls().parse(text, {**provider, 'key': 'auto'})
            valid = [l for l in lines if l.variety and (l.stems or l.line_total)]
            entry['lines'] = len(valid)
            entry['invoice'] = h.invoice_number
            entry['header_total'] = h.total
            entry['sample_lines'] = [
                {'variety': l.variety, 'size': l.size, 'stems': l.stems,
                 'price': l.price_per_stem, 'total': l.line_total}
                for l in valid[:3]
            ]
        except Exception as e:
            entry['error'] = f'{type(e).__name__}: {e}'
        report['samples'].append(entry)

    total_ok = sum(1 for s in report['samples'] if s['lines'] >= 1)
    report['pass_ratio'] = round(total_ok / max(len(report['samples']), 1), 2)
    report['min_lines'] = min((s['lines'] for s in report['samples']), default=0)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    sys.exit(0 if report['pass_ratio'] >= 0.7 else 1)


def cmd_register(args):
    """Registra un parser aprendido en __init__.py y cambia fmt en config.py."""
    provider_key = args.provider_key
    fmt_name = args.fmt_name

    if provider_key not in PROVIDERS:
        print(f'ERROR: {provider_key} no existe', file=sys.stderr)
        sys.exit(2)

    parser_path = PARSERS_DIR / f'{fmt_name}.py'
    if not parser_path.exists():
        print(f'ERROR: {parser_path} no existe', file=sys.stderr)
        sys.exit(2)

    # --- __init__.py: añadir import + entrada en FORMAT_PARSERS ---
    reg = REGISTRY_PATH.read_text(encoding='utf-8')
    import_line = f'from src.parsers.{fmt_name} import AutoParser as {fmt_name}_Parser'
    dict_line   = f"    '{fmt_name}': {fmt_name}_Parser(),\n"

    if import_line not in reg:
        # Inserta antes de 'FORMAT_PARSERS = {'
        reg = reg.replace('\nFORMAT_PARSERS = {',
                          f'\n{import_line}\n\nFORMAT_PARSERS = {{',
                          1)

    if f"'{fmt_name}':" not in reg:
        reg = reg.replace('FORMAT_PARSERS = {\n',
                          f'FORMAT_PARSERS = {{\n{dict_line}', 1)

    REGISTRY_PATH.write_text(reg, encoding='utf-8')

    # --- config.py: cambiar fmt='unknown' → fmt_name para este provider_key ---
    cfg = CONFIG_PATH.read_text(encoding='utf-8')
    # Regex tolerante: busca la línea entera que contiene 'provider_key': {...'fmt':'unknown'...}
    pattern = re.compile(
        rf"('{re.escape(provider_key)}'\s*:\s*\{{[^}}]*?'fmt'\s*:\s*)'unknown'"
    )
    new_cfg, n = pattern.subn(rf"\1'{fmt_name}'", cfg)
    if n == 0:
        print(f'AVISO: no se encontró fmt="unknown" en config.py para {provider_key}. '
              f'Comprueba que sigue siendo stub.', file=sys.stderr)
    else:
        CONFIG_PATH.write_text(new_cfg, encoding='utf-8')
    print(f'OK: {provider_key} registrado como fmt={fmt_name}')


def cmd_evaluate(args):
    """Mide calidad del parser ACTUAL (el registrado) contra muestras.

    Para parsers ya existentes: base line de qué extrae, qué líneas rescata el
    pipeline como sin_parser, qué totales cuadran. Se usa ANTES de tocar un
    parser para tener punto de comparación, y DESPUÉS para verificar mejora
    sin regresión.

    Flujo:
      - Corre detect_provider sobre cada PDF (para ver si el registro detecta).
      - Si detecta, ejecuta el parser registrado.
      - Aplica rescue_unparsed_lines para contar líneas huérfanas.
      - Valida totales cruzados.
    """
    from src.matcher import rescue_unparsed_lines

    folder = Path(args.folder)
    pdfs = sorted(folder.rglob('*.pdf')) or sorted(folder.rglob('*.PDF'))
    pdfs = pdfs[:args.max_samples]

    report = {'folder': str(folder), 'samples': []}
    for pdf in pdfs:
        entry = {'file': pdf.name, 'detected_as': '', 'fmt': '',
                 'parsed_lines': 0, 'rescued_lines': 0,
                 'header_total': 0, 'sum_line_total': 0,
                 'header_ok': None, 'error': ''}
        try:
            pdata = detect_provider(str(pdf))
            if not pdata:
                entry['error'] = 'no detectado por config.py'
                report['samples'].append(entry)
                continue
            entry['detected_as'] = pdata.get('name', '')
            entry['fmt'] = pdata.get('fmt', '')
            parser = FORMAT_PARSERS.get(pdata.get('fmt', ''))
            if not parser:
                entry['error'] = f"sin parser para fmt='{entry['fmt']}'"
                report['samples'].append(entry)
                continue
            pdata['pdf_path'] = str(pdf)
            h, lines = parser.parse(pdata['text'], pdata)
            valid = [l for l in lines if l.variety and (l.stems or l.line_total)]
            entry['parsed_lines'] = len(valid)
            entry['invoice'] = h.invoice_number
            entry['header_total'] = h.total
            sum_lines = round(sum(l.line_total for l in lines), 2)
            entry['sum_line_total'] = sum_lines
            if h.total:
                diff = abs(sum_lines - h.total) / h.total if h.total else 0
                entry['header_ok'] = diff <= 0.01
                entry['diff_pct'] = round(diff * 100, 2)
            rescued = rescue_unparsed_lines(pdata['text'], lines)
            entry['rescued_lines'] = len(rescued)
            entry['sample_parsed'] = [
                {'variety': l.variety, 'size': l.size, 'stems': l.stems,
                 'total': l.line_total, 'method': l.match_method or ''}
                for l in valid[:3]
            ]
            entry['sample_rescued'] = [l.raw_description[:100] for l in rescued[:3]]
        except Exception as e:
            entry['error'] = f'{type(e).__name__}: {e}'
        report['samples'].append(entry)

    # Métricas agregadas
    n = len(report['samples'])
    report['metrics'] = {
        'samples':         n,
        'detected':        sum(1 for s in report['samples'] if s['detected_as']),
        'parsed_any':      sum(1 for s in report['samples'] if s['parsed_lines']),
        'total_parsed':    sum(s['parsed_lines'] for s in report['samples']),
        'total_rescued':   sum(s['rescued_lines'] for s in report['samples']),
        'totals_ok':       sum(1 for s in report['samples'] if s.get('header_ok')),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    # Exit 0 solo si todas las muestras se detectan y parsean al menos 1 línea
    ok = (report['metrics']['detected'] == n and report['metrics']['parsed_any'] == n)
    sys.exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)

    p_val = sub.add_parser('validate', help='Ejecuta parser AUTO-NUEVO contra muestras')
    p_val.add_argument('provider_key')
    p_val.add_argument('folder')
    p_val.add_argument('--fmt-name', default='')
    p_val.add_argument('--max-samples', type=int, default=5)
    p_val.set_defaults(func=cmd_validate)

    p_reg = sub.add_parser('register', help='Registra parser en __init__.py + config.py')
    p_reg.add_argument('provider_key')
    p_reg.add_argument('fmt_name')
    p_reg.set_defaults(func=cmd_register)

    p_eval = sub.add_parser('evaluate', help='Mide calidad del parser ACTUAL contra muestras')
    p_eval.add_argument('folder', help='Carpeta con PDFs del proveedor')
    p_eval.add_argument('--max-samples', type=int, default=5)
    p_eval.set_defaults(func=cmd_evaluate)

    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
