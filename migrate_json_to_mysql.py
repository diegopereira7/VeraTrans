"""Migración one-shot de los ficheros JSON al schema real de MySQL.

Lee `sinonimos_universal.json` y `historial_universal.json` desde la raíz del
proyecto y los inserta en las tablas `sinonimos` e `historial` usando
INSERT...ON DUPLICATE KEY UPDATE, así que es idempotente: se puede correr
varias veces sin duplicar filas.

Uso:
    python migrate_json_to_mysql.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

from src.config import SYNS_FILE, HIST_FILE
from src.db import get_connection, MYSQL_AVAILABLE


# Mismo mapping que SynonymStore._ORIGEN_MAP — duplicado a propósito para
# que la migración no dependa de detalles internos del store.
ORIGEN_MAP = {
    'manual':       'manual',
    'manual-web':   'manual',
    'manual-batch': 'manual',
    'revisado':     'manual',
    'auto':         'auto',
    'auto-fuzzy':   'auto-fuzzy',
}


def migrate_sinonimos(conn) -> tuple[int, int]:
    """Vuelca sinonimos_universal.json a la tabla `sinonimos`."""
    if not Path(SYNS_FILE).exists():
        print(f'  ! No existe {SYNS_FILE}, salto.')
        return (0, 0)

    with open(SYNS_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    cur = conn.cursor()
    inserted = 0
    skipped = 0
    sql = """
        INSERT INTO sinonimos
            (clave, id_proveedor, nombre_factura, especie, talla,
             stems_per_bunch, grado, id_articulo, nombre_articulo, origen)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            id_articulo     = VALUES(id_articulo),
            nombre_articulo = VALUES(nombre_articulo),
            origen          = VALUES(origen)
    """

    for key, entry in data.items():
        try:
            origen = ORIGEN_MAP.get(entry.get('origen', ''), 'manual')
            cur.execute(sql, (
                key,
                int(entry.get('provider_id', 0) or 0),
                entry.get('variety', ''),
                entry.get('species', ''),
                int(entry.get('size', 0) or 0),
                int(entry.get('stems_per_bunch', 0) or 0),
                entry.get('grade', ''),
                int(entry.get('articulo_id', 0) or 0),
                entry.get('articulo_name', ''),
                origen,
            ))
            inserted += 1
        except Exception as e:
            print(f'  ! Skip {key}: {e}')
            skipped += 1

    conn.commit()
    cur.close()
    return (inserted, skipped)


def migrate_historial(conn) -> tuple[int, int]:
    """Vuelca historial_universal.json a la tabla `historial`."""
    if not Path(HIST_FILE).exists():
        print(f'  ! No existe {HIST_FILE}, salto.')
        return (0, 0)

    with open(HIST_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    cur = conn.cursor()
    inserted = 0
    skipped = 0
    sql = """
        INSERT INTO historial
            (numero_factura, pdf_nombre, proveedor, total_usd,
             lineas, ok_count, sin_match, fecha_proceso)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            pdf_nombre    = VALUES(pdf_nombre),
            proveedor     = VALUES(proveedor),
            total_usd     = VALUES(total_usd),
            lineas        = VALUES(lineas),
            ok_count      = VALUES(ok_count),
            sin_match     = VALUES(sin_match),
            fecha_proceso = VALUES(fecha_proceso)
    """

    for inv, entry in data.items():
        try:
            fecha = entry.get('fecha', '')
            # El JSON guarda 'YYYY-MM-DD HH:MM'; añadimos segundos si faltan.
            if fecha and len(fecha) == 16:
                fecha = fecha + ':00'
            cur.execute(sql, (
                inv,
                entry.get('pdf', ''),
                entry.get('provider', ''),
                float(entry.get('total_usd', 0) or 0),
                int(entry.get('lineas', 0) or 0),
                int(entry.get('ok', 0) or 0),
                int(entry.get('sin_match', 0) or 0),
                fecha or None,
            ))
            inserted += 1
        except Exception as e:
            print(f'  ! Skip {inv}: {e}')
            skipped += 1

    conn.commit()
    cur.close()
    return (inserted, skipped)


def main() -> int:
    if not MYSQL_AVAILABLE:
        print('ERROR: pymysql no disponible. pip install pymysql')
        return 1

    print('Conectando a MySQL...')
    conn = get_connection()
    try:
        print('\n→ Migrando sinónimos...')
        ins, skp = migrate_sinonimos(conn)
        print(f'  {ins} insertados/actualizados, {skp} saltados.')

        print('\n→ Migrando historial...')
        ins, skp = migrate_historial(conn)
        print(f'  {ins} insertados/actualizados, {skp} saltados.')

        # Conteos finales para verificar
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM sinonimos')
        n_syn = cur.fetchone()[0]
        cur.execute('SELECT COUNT(*) FROM historial')
        n_hist = cur.fetchone()[0]
        cur.close()
        print(f'\nEstado final: sinonimos={n_syn}, historial={n_hist}')
    finally:
        conn.close()

    return 0


if __name__ == '__main__':
    sys.exit(main())
