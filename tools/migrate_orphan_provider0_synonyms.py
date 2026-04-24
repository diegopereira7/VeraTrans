"""Migra sinónimos con key `0|...` al provider_id correcto.

Sesión 12a: diagnóstico de los 0 → real provider_id. El bug estaba en
la UI (batch mode: `STATE.provider_id` no se actualiza por factura →
`saveLineArticle` componía synKey con providerId=0). Las correcciones
del operador quedaban huérfanas — se guardaban como `0|...` y el
siguiente batch no las reutilizaba, por lo que Ángel corregía la
misma línea una y otra vez.

Política:
  - Para cada entry con key `0|{species}|{variety}|{size}|{spb}|{grade}`,
    mirar el `articulo_id` al que apunta.
  - Leer `id_proveedor` del artículo en MySQL.
  - Recomponer la key como `{id_proveedor}|...` y mover el sinónimo.
  - Si la nueva key ya existe: preservar el más fuerte (manual >
    aprendido > ambiguo) — ante empate, el nuevo sobrescribe porque
    es más reciente y explícito.
  - Dejar en el JSON solo la nueva key (eliminar la `0|`).

Uso: python tools/migrate_orphan_provider0_synonyms.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.articulos import ArticulosLoader

SYN_FILE = Path(__file__).resolve().parent.parent / 'sinonimos_universal.json'

STATUS_RANK = {
    'manual_confirmado':    4,
    'aprendido_confirmado': 3,
    'aprendido_en_prueba':  2,
    'ambiguo':              1,
    None:                   1,
    'rechazado':            0,
}


def _stronger(a: dict, b: dict) -> dict:
    """Devuelve el entry de sinónimo "más fuerte" (mayor status)."""
    ra = STATUS_RANK.get(a.get('status'), 1)
    rb = STATUS_RANK.get(b.get('status'), 1)
    return a if ra >= rb else b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true',
                    help='Aplicar migración. Sin este flag es dry-run.')
    args = ap.parse_args()

    loader = ArticulosLoader()
    loader.load_from_db()

    with SYN_FILE.open(encoding='utf-8') as f:
        data = json.load(f)

    orphans = {k: v for k, v in data.items() if k.startswith('0|')}
    print(f'Orphans con key 0|... : {len(orphans)}')
    if not orphans:
        return

    planned_moves: list[tuple[str, str, dict]] = []
    planned_drops: list[str] = []
    resolved = 0

    for old_key, entry in orphans.items():
        art_id = entry.get('articulo_id')
        art = loader.articulos.get(art_id) if art_id else None
        if not art:
            print(f'  [SKIP] {old_key!r}: art_id={art_id} no encontrado en catálogo — se elimina')
            planned_drops.append(old_key)
            continue
        pid = art.get('id_proveedor', 0) or 0
        if not pid:
            print(f'  [SKIP] {old_key!r}: art {art_id} sin id_proveedor — se elimina')
            planned_drops.append(old_key)
            continue
        parts = old_key.split('|', 1)
        if len(parts) != 2:
            print(f'  [SKIP] {old_key!r}: formato de key inesperado')
            continue
        new_key = f'{pid}|{parts[1]}'
        planned_moves.append((old_key, new_key, entry))
        resolved += 1
        existing = data.get(new_key)
        conflict = ' (CONFLICTO: merge)' if existing else ''
        print(f'  {old_key} -> {new_key}{conflict}')
        print(f'     art={art_id} name={(entry.get("articulo_name") or "")[:50]}')

    print()
    print(f'Movibles: {resolved} · A eliminar: {len(planned_drops)}')

    if not args.apply:
        print('\n(dry-run — usa --apply para persistir)')
        return

    # Backup
    backup = SYN_FILE.with_suffix(
        f'.json.backup_orphans_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
    shutil.copy2(SYN_FILE, backup)
    print(f'Backup: {backup}')

    # Apply
    for old_key, new_key, entry in planned_moves:
        existing = data.get(new_key)
        # Actualizar provider_id del entry antes de guardar
        parts = new_key.split('|')
        entry['provider_id'] = int(parts[0])
        if existing:
            merged = _stronger(existing, entry)
            # Preservar el que gana, pero incrementar times_confirmed
            merged['times_confirmed'] = (merged.get('times_confirmed') or 0) \
                + (existing.get('times_confirmed') or 0)
            data[new_key] = merged
        else:
            data[new_key] = entry
        del data[old_key]

    for k in planned_drops:
        del data[k]

    tmp = SYN_FILE.with_suffix('.json.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(SYN_FILE)
    print(f'Aplicado: {resolved} movidos + {len(planned_drops)} eliminados')


if __name__ == '__main__':
    main()
