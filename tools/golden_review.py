"""Herramienta interactiva para revisar anotaciones golden set.

Muestra cada línea con su match actual y las alternativas del catálogo.
El operador confirma (Enter), elige una alternativa (número), o busca
manualmente (escribiendo texto).

Uso:
    python tools/golden_review.py golden/mystic_0000281780.json
    python tools/golden_review.py golden/alegria_00046496.json --from-line 10

Atajos durante la revisión:
    Enter      → aceptar el articulo_id actual
    1-5        → elegir alternativa del catálogo
    33215      → asignar artículo por ID directamente (cualquier número > 5)
    r N        → re-revisar línea N (ej: r 3)
    s          → skip (dejar sin revisar)
    q          → guardar y salir (se puede retomar luego)

    Líneas iguales (misma variedad+size+origin) se auto-corrigen
    con la misma elección que hiciste la primera vez.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stdin.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import SQL_FILE, SYNS_FILE
from src.articulos import ArticulosLoader
from src.sinonimos import SynonymStore
from src.matcher import Matcher


def _color(text: str, code: int) -> str:
    """ANSI color wrapper."""
    return f'\033[{code}m{text}\033[0m'


def _green(t): return _color(t, 32)
def _yellow(t): return _color(t, 33)
def _red(t): return _color(t, 31)
def _cyan(t): return _color(t, 36)
def _bold(t): return _color(t, 1)


def _search_catalog(art: ArticulosLoader, query: str, limit: int = 10) -> list[dict]:
    """Busca artículos por texto en el nombre."""
    query_upper = query.upper().strip()
    words = query_upper.split()
    results = []
    for a in art.articulos.values():
        name = a.get('nombre', '').upper()
        if all(w in name for w in words):
            results.append(a)
            if len(results) >= limit:
                break
    return results


def _find_alternatives(art: ArticulosLoader, line: dict, limit: int = 5) -> list[dict]:
    """Busca artículos alternativos para una línea basándose en variedad+tamaño."""
    variety = line.get('variety', '').upper()
    size = line.get('size', 0)
    species = line.get('species', '').upper()
    origin = line.get('origin', '').upper()

    candidates = []
    for a in art.articulos.values():
        name = a.get('nombre', '').upper()
        score = 0
        # Variety match
        if variety and variety in name:
            score += 10
        elif variety:
            # Partial: any word of variety in name
            var_words = [w for w in variety.split() if len(w) >= 3]
            matches = sum(1 for w in var_words if w in name)
            if matches:
                score += matches * 3
        # Size match
        if size and f'{size}CM' in name:
            score += 5
        # Species match
        if species == 'ROSES' and 'ROSA' in name:
            score += 3
        elif species == 'CARNATIONS' and 'CLAVEL' in name:
            score += 3
        elif species == 'HYDRANGEAS' and 'HORTENSIA' in name:
            score += 3
        elif species == 'GYPSOPHILA' and 'GYPSOPHILA' in name:
            score += 3
        # Origin match
        if origin and origin in name:
            score += 2

        if score >= 5:
            candidates.append((score, a))

    candidates.sort(key=lambda x: x[0], reverse=True)
    return [a for _, a in candidates[:limit]]


def review_file(filepath: Path, art: ArticulosLoader, start_line: int = 0):
    """Revisión interactiva de un archivo golden."""
    data = json.loads(filepath.read_text(encoding='utf-8'))

    if data.get('_status') == 'reviewed':
        print(f'{_yellow("AVISO")}: este archivo ya está marcado como "reviewed".')
        resp = input('  ¿Quieres re-revisarlo? (s/N): ').strip().lower()
        if resp != 's':
            return

    lines = data.get('lines', [])
    total = len(lines)
    reviewed_count = sum(1 for l in lines if '_review' not in l)

    print()
    print(_bold(f'=== Golden Review: {filepath.name} ==='))
    print(f'  Proveedor: {data.get("provider_name", "")} ({data.get("provider_key", "")})')
    print(f'  Factura:   {data.get("invoice_number", "")}')
    print(f'  Líneas:    {total} ({reviewed_count} ya revisadas)')
    print()
    print(f'  Enter=aceptar  1-5=alternativa  ID=asignar por ID  s=skip  q=guardar+salir')
    print(f'  r N  =re-revisar línea N (ej: r 3)')
    print()
    # Correcciones ya hechas: (variety, size, origin) → (articulo_id, articulo_name)
    # Se aplican automáticamente a líneas idénticas
    corrections: dict[tuple, tuple] = {}

    modified = False
    # Cola de líneas a revisar: pendientes + las que el usuario pida re-revisar
    review_queue = [i for i, l in enumerate(lines) if '_review' in l and i >= start_line]
    qi = 0

    while qi < len(review_queue):
        i = review_queue[qi]
        qi += 1
        line = lines[i]

        var = line.get('variety', '')
        sz = line.get('size', 0)
        origin = line.get('origin', '')
        species = line.get('species', '')
        stems = line.get('stems', 0)
        total_val = line.get('line_total', 0)
        art_id = line.get('articulo_id', 0)
        art_name = line.get('articulo_name', '')
        status = line.get('match_status', '')
        link_conf = line.get('link_confidence', 0)

        # Auto-corrección: si ya corregimos una línea idéntica, aplicar
        key = (var.upper(), sz, origin.upper())
        if key in corrections:
            corr_id, corr_name = corrections[key]
            line['articulo_id'] = corr_id
            line['articulo_name'] = corr_name
            line.pop('_review', None)
            modified = True
            print(f'  {_green(f"✓ Auto:")} Línea {i+1} — {var} {sz}cm → {corr_name}')
            continue

        # Header
        print(_bold(f'── Línea {i+1}/{total} ──'))
        print(f'  Raw: {_cyan(line.get("raw_description", "")[:80])}')
        print(f'  Parsed: {_bold(var)} {sz}cm {origin} {species} | '
              f'stems={stems} total=${total_val:.2f}')

        # Current match
        if art_id:
            conf_color = _green if link_conf >= 0.80 else (_yellow if link_conf >= 0.50 else _red)
            print(f'  Match:  [{status}] {conf_color(f"conf={link_conf:.2f}")}')
            print(f'  → {_bold(f"[0] {art_name}")} (id={art_id})')
        else:
            print(f'  Match:  {_red("SIN MATCH")}')

        # Alternatives
        alts = _find_alternatives(art, line)
        # Filter out current match
        alts = [a for a in alts if a.get('id') != art_id][:5]
        if alts:
            print(f'  Alternativas:')
            for j, a in enumerate(alts, 1):
                print(f'    [{j}] {a.get("nombre", "")} (id={a.get("id", "")})')

        # Input
        while True:
            try:
                resp = input(f'  > ').strip()
            except (EOFError, KeyboardInterrupt):
                resp = 'q'

            if resp == '' or resp == '0':
                # Accept current
                line.pop('_review', None)
                modified = True
                corrections[key] = (line.get('articulo_id', 0), line.get('articulo_name', ''))
                print(f'  {_green("✓ Aceptado")}')
                break
            elif resp == 'q':
                # Save and quit
                if modified:
                    _save(filepath, data)
                    reviewed_now = sum(1 for l in lines if '_review' not in l)
                    print(f'\n{_green("Guardado")} — {reviewed_now}/{total} líneas revisadas')
                else:
                    print('\nSin cambios.')
                return
            elif resp == 's':
                print(f'  {_yellow("→ Skip")}')
                break
            elif resp.startswith('r ') or resp.startswith('r'):
                # Re-revisar línea N
                parts = resp.split()
                if len(parts) == 2 and parts[1].isdigit():
                    target = int(parts[1]) - 1  # 1-indexed → 0-indexed
                    if 0 <= target < total:
                        # Marcar esa línea como pendiente e insertarla justo después
                        lines[target]['_review'] = 'RE-REVIEW'
                        review_queue.insert(qi, target)
                        print(f'  {_yellow(f"Línea {target+1} será la siguiente")}')
                    else:
                        print(f'  Línea fuera de rango (1-{total})')
                else:
                    print(f'  Uso: r N (ej: r 3 para re-revisar la línea 3)')
                continue
            elif resp.isdigit():
                num = int(resp)
                if 1 <= num <= len(alts):
                    # Elegir alternativa
                    chosen = alts[num - 1]
                    new_id = chosen.get('id', 0)
                    new_name = chosen.get('nombre', '')
                else:
                    # ID de artículo directo
                    found = art.articulos.get(num)
                    if not found:
                        print(f'  {_red(f"ID {num} no existe en el catálogo")}')
                        continue
                    new_id = num
                    new_name = found.get('nombre', '')
                line['articulo_id'] = new_id
                line['articulo_name'] = new_name
                line.pop('_review', None)
                modified = True
                # Guardar corrección para auto-aplicar a líneas iguales
                corrections[key] = (new_id, new_name)
                print(f'  {_green("✓ Asignado:")} {new_name} (id={new_id})')
                break
            else:
                print(f'  Enter=aceptar, 1-5=alt, ID=artículo, r N=re-revisar, s=skip, q=salir')

        print()

    # Fin del archivo
    if modified:
        # Check if all reviewed
        pending = sum(1 for l in lines if '_review' in l)
        if pending == 0:
            data['_status'] = 'reviewed'
            print(f'{_green("¡Todas las líneas revisadas!")} Status → reviewed')
        else:
            print(f'{_yellow(f"{pending} líneas pendientes")} — puedes retomar luego')
        _save(filepath, data)
    else:
        pending = sum(1 for l in lines if '_review' in l)
        if pending == 0:
            print('Todas las líneas ya estaban revisadas.')
        else:
            print(f'{pending} líneas pendientes de revisión.')


def _save(filepath: Path, data: dict):
    """Guarda el archivo golden preservando formato."""
    filepath.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding='utf-8')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('file', type=Path, help='Archivo golden JSON a revisar')
    ap.add_argument('--from-line', type=int, default=0,
                    help='Empezar desde la línea N (0-indexed)')
    args = ap.parse_args()

    if not args.file.exists():
        print(f'ERROR: no existe {args.file}', file=sys.stderr)
        sys.exit(1)

    # Cargar catálogo
    print('Cargando catálogo...', file=sys.stderr, flush=True)
    art = ArticulosLoader()
    art.load_from_sql(str(SQL_FILE))
    print(f'  {len(art.articulos)} artículos cargados.', file=sys.stderr)

    review_file(args.file, art, start_line=args.from_line)


if __name__ == '__main__':
    main()
