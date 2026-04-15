"""Extrae 40 líneas del primer PDF de cada proveedor indicado.

Uso: python tools/extract_samples.py FOLDER1 "FOLDER WITH SPACE" ...
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from src.pdf import extract_text

BASE = Path(r"C:\Users\diego.pereira\Desktop\DOC VERA\FACTURAS IMPORTACION\PROVEEDORES")


def show(folder_name: str):
    folder = BASE / folder_name
    if not folder.exists():
        print(f'\n### {folder_name} — NO EXISTE')
        return
    pdfs = sorted(folder.rglob('*.pdf')) or sorted(folder.rglob('*.PDF'))
    if not pdfs:
        print(f'\n### {folder_name} — SIN PDFs')
        return
    print(f'\n### {folder_name} — {pdfs[0].name}')
    try:
        text = extract_text(str(pdfs[0]))
    except Exception as e:
        print(f'  ERROR: {e}')
        return
    for i, ln in enumerate(text.split('\n')[:40]):
        s = ln.strip()
        if s:
            print(f'  {i:2}: {s[:140]}')


if __name__ == '__main__':
    for arg in sys.argv[1:]:
        show(arg)
