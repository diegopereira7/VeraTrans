"""One-shot migration: sinónimos Uma Flowers GYPSOPHILA con spb=0 → spb=25.

Contexto: el parser `UmaParser` extrae `stems_per_bunch` directo del PDF
(columna St.Bunch = 25 para GYPSOPHILA 750gr). Hay 12 sinónimos históricos
guardados con `spb=0` (posiblemente desde el formulario manual cuando
todavía no se rellenaba ese campo) que quedaron huérfanos: el matcher
busca por clave `440|GYPSOPHILA|<VAR>|80|25|` y no encuentra el sinónimo
viejo con `spb=0`, cae en scoring por evidencia débil (sin size_exact
ni brand_in_name porque no hay artículo PANICULATA...UMA en catálogo),
devuelve `ambiguous_match` con `low_evidence`. Shadow log (sesión 10n)
mostró el patrón: 13 líneas Uma pendientes, 12 con el mismo sinónimo
huérfano `GYPSOPHILA XL NATURAL WHITE 80`.

Migración:
  - 11 varieties con SOLO spb=0 → re-key a spb=25.
  - 2 varieties con spb=0 Y spb=25: prevalece el spb=25 (en los dos
    casos es igual o más confirmado). Borrar el spb=0.

No afecta otros proveedores (419 tiene 1 caso aislado distinto y su
impacto en shadow es nulo por ahora).
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

SYN_FILE = Path(__file__).resolve().parent.parent / 'sinonimos_universal.json'
BACKUP = SYN_FILE.with_name(
    f'sinonimos_universal.json.backup_uma_gypso_spb_'
    f'{datetime.now().strftime("%Y%m%d_%H%M%S")}'
)


def main():
    data = json.loads(SYN_FILE.read_text(encoding='utf-8'))
    print(f'Loaded {len(data)} synonyms from {SYN_FILE.name}')

    # Clasificar: solo Uma (440), GYPSOPHILA, spb=0
    targets = []
    for key, entry in data.items():
        if not key.startswith('440|'):
            continue
        if (entry.get('species') or '').upper() != 'GYPSOPHILA':
            continue
        if int(entry.get('stems_per_bunch') or 0) != 0:
            continue
        targets.append(key)

    print(f'Uma GYPSOPHILA spb=0 candidates: {len(targets)}')

    # Para cada candidato, construir nueva key con spb=25
    renamed = []
    dropped = []
    for old_key in targets:
        parts = old_key.split('|')
        parts[4] = '25'
        new_key = '|'.join(parts)
        if new_key in data:
            # Conflicto: ya existe entry con spb=25. Ver qué gana.
            old_entry = data[old_key]
            new_entry = data[new_key]
            old_conf = int(old_entry.get('times_confirmed') or 0)
            new_conf = int(new_entry.get('times_confirmed') or 0)
            old_status = old_entry.get('status') or ''
            new_status = new_entry.get('status') or ''
            STATUS_RANK = {
                'manual_confirmado': 4,
                'aprendido_confirmado': 3,
                'aprendido_en_prueba': 2,
                '': 1,
                None: 1,
                'ambiguo': 0,
                'rechazado': -1,
            }
            old_rank = (STATUS_RANK.get(old_status, 1), old_conf)
            new_rank = (STATUS_RANK.get(new_status, 1), new_conf)
            if new_rank >= old_rank:
                # spb=25 gana — descartar spb=0
                dropped.append((old_key, 'spb=25 existing is stronger',
                                old_entry.get('articulo_id'),
                                new_entry.get('articulo_id')))
                del data[old_key]
            else:
                # spb=0 gana — sobreescribir el spb=25 con los valores del viejo
                # pero con spb actualizado
                merged = dict(old_entry)
                merged['stems_per_bunch'] = 25
                data[new_key] = merged
                del data[old_key]
                renamed.append((old_key, new_key, 'overrode existing weaker'))
        else:
            # Sin conflicto: simple rename + update field
            entry = dict(data[old_key])
            entry['stems_per_bunch'] = 25
            data[new_key] = entry
            del data[old_key]
            renamed.append((old_key, new_key, 'no conflict'))

    print(f'Renamed: {len(renamed)}')
    for old, new, note in renamed:
        print(f'  {old}  ->  {new}   [{note}]')
    print(f'Dropped (conflict resolved in favor of existing spb=25): {len(dropped)}')
    for old, note, old_art, new_art in dropped:
        print(f'  {old}   [{note}]   old_art={old_art}  kept_art={new_art}')

    if not renamed and not dropped:
        print('Nada que migrar. No se hacen cambios.')
        return 0

    shutil.copy(SYN_FILE, BACKUP)
    print(f'Backup escrito: {BACKUP.name}')
    SYN_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
    print(f'Written {len(data)} synonyms to {SYN_FILE.name}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
