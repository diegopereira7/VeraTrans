"""Evaluación masiva: corre tools/auto_learn_parsers.py evaluate sobre cada
subcarpeta de PROVEEDORES y genera un informe consolidado.

Output:
- CSV con una fila por proveedor: samples, detected, parsed_any, totals_ok,
  total_rescued, total_parsed, veredicto.
- Lista ordenada de "peores" para priorizar arreglos.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import PROVIDERS

BASE = Path(r"C:\Users\diego.pereira\Desktop\DOC VERA\FACTURAS IMPORTACION\PROVEEDORES")
TOOL = Path(__file__).parent / 'auto_learn_parsers.py'
OUT  = Path(__file__).resolve().parent.parent / 'auto_learn_report.json'

# Carpetas logísticas — NO son proveedores reales
LOGISTICS = {
    'ALLIANCE', 'DSV', 'SAFTEC', 'REAL CARGA', 'EXCELE CARGA',
    'LOGIZTIK', 'VERALEZA', 'FESO',
}


def evaluate(folder: Path) -> dict:
    """Ejecuta evaluate y devuelve el JSON o error."""
    try:
        res = subprocess.run(
            [sys.executable, str(TOOL), 'evaluate', str(folder), '--max-samples', '5'],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=180,
        )
        data = json.loads(res.stdout)
        return data
    except subprocess.TimeoutExpired:
        return {'error': 'timeout'}
    except Exception as e:
        return {'error': f'{type(e).__name__}: {e}'}


def verdict(m: dict) -> str:
    """Clasifica en OK / CON_GAPS / ROTO basado en métricas."""
    n = m.get('samples', 0)
    if n == 0:
        return 'SIN_MUESTRAS'
    det = m.get('detected', 0)
    par = m.get('parsed_any', 0)
    tok = m.get('totals_ok', 0)
    if det < n:
        return 'NO_DETECTADO'
    if par < n:
        return 'NO_PARSEA'
    if tok < n * 0.6 and n > 1:
        return 'TOTALES_MAL'
    if m.get('total_rescued', 0) > m.get('total_parsed', 0):
        return 'MUCHO_RESCATE'
    return 'OK'


def main():
    folders = sorted(p for p in BASE.iterdir()
                     if p.is_dir() and p.name.upper() not in LOGISTICS)
    report = []
    for i, folder in enumerate(folders, 1):
        print(f'[{i}/{len(folders)}] {folder.name}...', file=sys.stderr, flush=True)
        r = evaluate(folder)
        if 'error' in r:
            report.append({'folder': folder.name, 'error': r['error'],
                           'verdict': 'ERROR'})
            continue
        metrics = r.get('metrics', {})
        report.append({
            'folder': folder.name,
            'verdict': verdict(metrics),
            **metrics,
            'samples_raw': r.get('samples', []),
        })

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding='utf-8')

    # Tabla resumida
    buckets = {}
    for r in report:
        buckets.setdefault(r['verdict'], []).append(r['folder'])
    print('\n' + '=' * 60)
    print(f'EVALUACIÓN MASIVA — {len(report)} proveedores')
    print('=' * 60)
    for v in ('OK', 'TOTALES_MAL', 'MUCHO_RESCATE', 'NO_PARSEA',
              'NO_DETECTADO', 'SIN_MUESTRAS', 'ERROR'):
        if v in buckets:
            print(f'\n{v} ({len(buckets[v])}):')
            for f in buckets[v]:
                r = next(x for x in report if x['folder'] == f)
                parsed = r.get('total_parsed', 0)
                rescued = r.get('total_rescued', 0)
                tok = r.get('totals_ok', 0)
                n = r.get('samples', 0)
                print(f'  {f:<20} samples={n} parsed_any={r.get("parsed_any", 0)}/{n} '
                      f'tot_ok={tok}/{n} lines={parsed} rescued={rescued}')


if __name__ == '__main__':
    main()
