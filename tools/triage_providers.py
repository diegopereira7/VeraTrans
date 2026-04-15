"""Triage automático de la carpeta PROVEEDORES.

Escanea cada subcarpeta, extrae texto del primer PDF y clasifica al proveedor
en uno de estos buckets:

  REGISTRADO_OK       — detectado por config.py Y tiene parser (fmt != 'unknown')
  REGISTRADO_STUB     — detectado pero fmt='unknown'
  NO_REGISTRADO_ML    — no detectado, pero el aprendido lo reconoce
  NO_REGISTRADO       — ni config ni aprendido lo reconocen → candidato a registrar
  LOGISTICA           — carrier/aduanas/freight, NO es factura de proveedor
  VACIO               — no hay PDFs o todos fallaron

Output: tabla compacta + listas por bucket para planificar el trabajo.
"""
from __future__ import annotations

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pdf import detect_provider, extract_text
from src.config import PROVIDERS


BASE = Path(r"C:\Users\diego.pereira\Desktop\DOC VERA\FACTURAS IMPORTACION\PROVEEDORES")

# Carpetas que NO son proveedores de flores (cargueros, aduanas, buyer).
LOGISTICS = {
    'ALLIANCE', 'DSV', 'SAFTEC', 'REAL CARGA', 'EXCELE CARGA',
    'LOGIZTIK', 'VERALEZA',
}

# Carga marca_prov.txt → {folder_name_upper: id}
def load_marca_map() -> dict[str, int]:
    out: dict[str, int] = {}
    path = BASE / 'marca_prov.txt'
    if not path.exists():
        return out
    for ln in path.read_text(encoding='utf-8').splitlines():
        ln = ln.strip()
        if not ln or ln.startswith('#'):
            continue
        if '|' not in ln:
            continue
        name, pid = ln.split('|', 1)
        pid = pid.strip()
        if pid and pid.isdigit():
            out[name.strip().upper()] = int(pid)
    return out


def classify_folder(folder: Path, marca_map: dict[str, int]) -> dict:
    """Devuelve {folder, bucket, detected_provider, suggested_id, sample_pdf, reason}."""
    name = folder.name
    name_up = name.upper()
    pdfs = sorted(folder.rglob('*.pdf'))
    if not pdfs:
        pdfs = sorted(folder.rglob('*.PDF'))

    if name_up in LOGISTICS:
        return {
            'folder': name, 'bucket': 'LOGISTICA',
            'pdfs': len(pdfs), 'detected': '', 'suggested_id': '',
            'reason': 'carguero/aduanas — no procesar',
        }
    if not pdfs:
        return {
            'folder': name, 'bucket': 'VACIO',
            'pdfs': 0, 'detected': '', 'suggested_id': '',
            'reason': 'sin PDFs',
        }

    sample = pdfs[0]
    try:
        pdata = detect_provider(str(sample))
    except Exception as e:
        pdata = None

    # ID sugerido: buscar en marca_map por varios alias
    suggested_id = ''
    for key in (name_up, name_up.replace(' ', ''), name_up.split()[0] if name_up.split() else ''):
        if key in marca_map:
            suggested_id = marca_map[key]
            break

    if pdata:
        fmt = pdata.get('fmt', '')
        bucket = 'REGISTRADO_STUB' if fmt == 'unknown' else 'REGISTRADO_OK'
        return {
            'folder': name, 'bucket': bucket,
            'pdfs': len(pdfs),
            'detected': f"{pdata.get('name')} (fmt={fmt})",
            'suggested_id': suggested_id or pdata.get('id', ''),
            'reason': '',
        }

    # Intentar parsers aprendidos
    try:
        from src.learner import intentar_auto_parse
        text = extract_text(str(sample))
        auto = intentar_auto_parse(str(sample), text)
        if auto.get('ok'):
            return {
                'folder': name, 'bucket': 'NO_REGISTRADO_ML',
                'pdfs': len(pdfs),
                'detected': auto.get('learned_provider', '?'),
                'suggested_id': suggested_id,
                'reason': 'detectado por parser aprendido',
            }
    except Exception:
        pass

    return {
        'folder': name, 'bucket': 'NO_REGISTRADO',
        'pdfs': len(pdfs),
        'detected': '',
        'suggested_id': suggested_id,
        'reason': 'ningún parser lo reconoce',
    }


def main():
    marca_map = load_marca_map()
    results: list[dict] = []
    folders = sorted([p for p in BASE.iterdir() if p.is_dir()])
    for i, f in enumerate(folders, 1):
        print(f'[{i}/{len(folders)}] {f.name}...', file=sys.stderr, flush=True)
        try:
            results.append(classify_folder(f, marca_map))
        except Exception as e:
            results.append({
                'folder': f.name, 'bucket': 'ERROR',
                'pdfs': 0, 'detected': '', 'suggested_id': '',
                'reason': f'excepción: {e}',
            })

    # Print report
    print('\n' + '=' * 100)
    print(f'{"FOLDER":<22} {"BUCKET":<18} {"PDFS":>4}  {"ID":>6}  DETECTED / REASON')
    print('=' * 100)
    for r in results:
        print(f'{r["folder"]:<22} {r["bucket"]:<18} {r["pdfs"]:>4}  '
              f'{str(r["suggested_id"]):>6}  {r["detected"] or r["reason"]}')

    print('\n' + '=' * 100)
    print('RESUMEN POR BUCKET')
    print('=' * 100)
    buckets: dict[str, list[str]] = {}
    for r in results:
        buckets.setdefault(r['bucket'], []).append(r['folder'])
    for b in ['REGISTRADO_OK', 'REGISTRADO_STUB', 'NO_REGISTRADO_ML',
              'NO_REGISTRADO', 'LOGISTICA', 'VACIO', 'ERROR']:
        if b in buckets:
            print(f'\n{b} ({len(buckets[b])}):')
            for folder in buckets[b]:
                print(f'  - {folder}')


if __name__ == '__main__':
    main()
