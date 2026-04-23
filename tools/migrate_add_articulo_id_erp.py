"""One-shot migration: popular `articulo_id_erp` en sinónimos y golden.

Contexto (sesión 10q): el `id` autoincrement de MySQL se renumera cuando
el operador re-importa el dump de la tabla `articulos` desde phpMyAdmin.
Los sinónimos (`sinonimos_universal.json`) y los anotaciones del golden
(`golden/*.json`) guardan `articulo_id` como clave → al cambiar los ids,
todos apuntan a artículos distintos y se corrompen.

Solución estructural (10q): guardar también `articulo_id_erp`, el
identificador del ERP externo (campo `id_erp` en catálogo), que NO
cambia. El matcher hace lookup por id_erp si el id local ya no coincide
con el artículo esperado (lazy remap — ver `SynonymStore.resolve_article_id`).

Esta migración recorre:
- `sinonimos_universal.json`: todas las entries.
- `golden/*.json`: todas las líneas con `articulo_id`.

Para cada `articulo_id` consulta la BD MySQL actual, extrae `id_erp`,
añade el campo `articulo_id_erp` al entry. Ids sin match (artículo ya
borrado o inconsistente) se reportan pero no se tocan.

Uso:
    python tools/migrate_add_articulo_id_erp.py           # dry-run
    python tools/migrate_add_articulo_id_erp.py --write   # aplica cambios
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from src.db import get_connection


def _norm_name(s: str) -> str:
    """Normaliza nombre para matching tolerante a tildes y espacios.

    Algunos nombres en el dump nuevo vienen sin tildes (TIMANÁ → TIMANA)
    y los JSON viejos las conservan. NFD + quitar marcas diacríticas
    permite matchear ambos.
    """
    s = (s or '').upper().strip()
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    # Colapsar múltiples espacios (el dump a veces tiene doble espacio)
    return ' '.join(s.split())

ROOT = Path(__file__).resolve().parent.parent
SYN_FILE = ROOT / 'sinonimos_universal.json'
GOLDEN_DIR = ROOT / 'golden'
SQL_DUMP = ROOT / 'articulos (5).sql'


def _parse_sql_dump(sql_path: Path) -> dict[str, tuple[str, int]]:
    """Parsea el dump SQL nuevo y devuelve mapping nombre → (id_erp, id_nuevo).

    La BD actual no trae la columna id_erp todavía; el dump de Diego
    (`articulos (5).sql`) sí, y además trae los ids nuevos tras la
    renumeración. Usamos el NOMBRE del artículo (estable entre ambas
    versiones) como puente para migrar sinónimos y golden sin depender
    de los ids locales.

    Si varios artículos tienen el mismo nombre, nos quedamos con el
    primero y reportamos colisiones (luego habrá que desambiguar).
    """
    import re
    import ast

    mapping: dict[str, tuple[str, int]] = {}
    collisions: dict[str, int] = {}

    txt = sql_path.read_text(encoding='utf-8')
    # Columnas del dump: (id, id_erp, id_grupo_articulo, id_proveedor,
    # color, tamano, marca, paquete, nombre, familia, referencia,
    # codigo_barras, referencia_anterior, nombre_proveedor, variedad,
    # calidad, avisos, iva, pvp, creado_at, modificado_at)
    for ln in txt.split('\n'):
        ln = ln.strip()
        if not ln.startswith('('):
            continue
        ln = ln.rstrip(',;')
        # Split tipo CSV respetando strings
        parts = _split_sql_row(ln)
        if len(parts) < 9:
            continue
        try:
            aid = int(parts[0].strip())
        except ValueError:
            continue
        id_erp = _clean_sql_str(parts[1])
        nombre = _clean_sql_str(parts[8])
        if not nombre:
            continue
        key = _norm_name(nombre)
        if key in mapping:
            collisions[key] = collisions.get(key, 1) + 1
            continue
        mapping[key] = (id_erp, aid)

    print(f'[dump] parsed {len(mapping)} nombres únicos desde {sql_path.name}')
    if collisions:
        print(f'[dump] {len(collisions)} nombres con colisión (ignoradas duplicadas):')
        for name, n in list(collisions.items())[:5]:
            print(f'    {n}x  {name[:60]}')
    return mapping


def _clean_sql_str(s: str) -> str:
    s = s.strip()
    if s == 'NULL':
        return ''
    if s.startswith("'") and s.endswith("'"):
        return s[1:-1].replace("\\'", "'").replace('\\"', '"')
    return s


def _split_sql_row(s: str) -> list[str]:
    parts = []
    cur = ''
    inq = False
    esc = False
    for ch in s[1:-1] if s.startswith('(') and s.endswith(')') else s:
        if esc:
            cur += ch
            esc = False
            continue
        if ch == '\\':
            cur += ch
            esc = True
            continue
        if ch == "'" and not inq:
            inq = True
            cur += ch
            continue
        if ch == "'" and inq:
            inq = False
            cur += ch
            continue
        if ch == ',' and not inq:
            parts.append(cur)
            cur = ''
            continue
        cur += ch
    if cur:
        parts.append(cur)
    return parts


def _migrate_synonyms(name_to_ref: dict[str, tuple[str, int]], apply: bool) -> dict:
    """Pobla articulo_id_erp y re-mapea articulo_id en sinonimos_universal.json.

    El puente entre BD vieja (ids pre-renumeración) y BD nueva (dump de
    Diego) es el NOMBRE del artículo guardado en la entry del sinónimo.
    """
    data = json.loads(SYN_FILE.read_text(encoding='utf-8'))
    populated = skipped = not_found = id_remapped = truncated = 0
    for k, e in data.items():
        old_art_id = int(e.get('articulo_id') or 0)
        if not old_art_id:
            skipped += 1
            continue
        if e.get('articulo_id_erp'):
            skipped += 1  # ya migrado
            continue
        name = _norm_name(e.get('articulo_name') or '')
        hit = name_to_ref.get(name)
        if not hit and len(name) > 3:
            # Fallback: export phpMyAdmin trunca la última letra cuando es
            # un carácter acentuado (TIMANÁ → TIMAN, TIMANA normalizado
            # tampoco matchea porque falta la A). Probar sin último char.
            hit = name_to_ref.get(name[:-1])
            if hit:
                truncated += 1
        if not hit:
            not_found += 1
            continue
        id_erp, new_id = hit
        e['articulo_id_erp'] = id_erp
        if new_id != old_art_id:
            e['articulo_id'] = new_id
            id_remapped += 1
        populated += 1

    print(f'[sinónimos] populated={populated}  id_remapped={id_remapped}  '
          f'truncated_fallback={truncated}  skipped={skipped}  '
          f'not_found={not_found}  total={len(data)}')

    if apply and populated > 0:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup = SYN_FILE.with_name(f'sinonimos_universal.json.backup_pre_id_erp_{ts}')
        shutil.copy(SYN_FILE, backup)
        SYN_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        print(f'[sinónimos] escrito {SYN_FILE.name} (backup: {backup.name})')
    return {'populated': populated, 'skipped': skipped,
            'not_found': not_found, 'id_remapped': id_remapped}


def _migrate_golden(name_to_ref: dict[str, tuple[str, int]], apply: bool) -> dict:
    """Pobla articulo_id_erp y re-mapea articulo_id en golden/*.json."""
    populated = skipped = not_found = id_remapped = 0
    touched_files: list[Path] = []
    for gf in sorted(GOLDEN_DIR.glob('*.json')):
        if gf.name == 'golden_eval_results.json':
            continue
        if 'backup' in gf.name:
            continue
        g = json.loads(gf.read_text(encoding='utf-8'))
        lines = g.get('lines') or []
        file_changed = False
        for l in lines:
            old_art_id = int(l.get('articulo_id') or 0)
            if not old_art_id:
                skipped += 1
                continue
            if l.get('articulo_id_erp'):
                skipped += 1
                continue
            name = _norm_name(l.get('articulo_name') or '')
            hit = name_to_ref.get(name)
            if not hit and len(name) > 3:
                hit = name_to_ref.get(name[:-1])
            if not hit:
                not_found += 1
                continue
            id_erp, new_id = hit
            l['articulo_id_erp'] = id_erp
            if new_id != old_art_id:
                l['articulo_id'] = new_id
                id_remapped += 1
            populated += 1
            file_changed = True
        if file_changed:
            touched_files.append(gf)
            if apply:
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                backup = gf.with_name(f'{gf.stem}.backup_pre_id_erp_{ts}.json')
                shutil.copy(gf, backup)
                gf.write_text(
                    json.dumps(g, ensure_ascii=False, indent=2),
                    encoding='utf-8'
                )

    print(f'[golden] populated={populated}  id_remapped={id_remapped}  '
          f'skipped={skipped}  not_found={not_found}  '
          f'touched_files={len(touched_files)}')
    if touched_files:
        for f in touched_files[:20]:
            print(f'    {f.name}')
    return {'populated': populated, 'skipped': skipped,
            'not_found': not_found, 'id_remapped': id_remapped,
            'touched_files': len(touched_files)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--write', action='store_true',
                    help='Aplica cambios. Sin este flag es dry-run.')
    args = ap.parse_args()

    print(f'Parseando dump SQL nuevo: {SQL_DUMP.name}')
    name_to_ref = _parse_sql_dump(SQL_DUMP)
    print()

    _migrate_synonyms(name_to_ref, args.write)
    print()
    _migrate_golden(name_to_ref, args.write)
    print()
    if not args.write:
        print('(dry-run — re-ejecuta con --write para aplicar)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
