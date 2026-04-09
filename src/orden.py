"""Generación de hoja de orden + líneas de orden a partir de factura procesada."""
from __future__ import annotations

import logging

from src.db import get_connection, MYSQL_AVAILABLE

logger = logging.getLogger(__name__)


def crear_hoja_orden(header: dict, lines: list[dict]) -> dict:
    """Crea una hoja de orden con sus líneas a partir del resultado de procesar_pdf.

    Args:
        header: dict con invoice_number, provider_id, provider_name, awb, date, total
        lines: lista de dicts con articulo_id, stems, stems_per_bunch, bunches,
               line_total, match_status, variety, size

    Returns:
        dict con ok, hoja_id, ordenes_count o error
    """
    if not MYSQL_AVAILABLE:
        return {'ok': False, 'error': 'MySQL no disponible'}

    # Solo crear órdenes para líneas con match OK
    lines_ok = [l for l in lines if l.get('match_status') == 'ok' and l.get('articulo_id')]

    if not lines_ok:
        return {'ok': False, 'error': 'No hay líneas con match para crear órdenes'}

    try:
        conn = get_connection()
        cur = conn.cursor()

        # Buscar id_proveedor en tabla proveedores
        provider_id = header.get('provider_id', 0)
        cur.execute("SELECT id FROM proveedores WHERE id = %s", (provider_id,))
        prov_row = cur.fetchone()
        db_provider_id = prov_row[0] if prov_row else None

        # Verificar si ya existe una hoja para esta factura
        invoice = header.get('invoice_number', '')
        cur.execute(
            "SELECT id FROM hoja_orden WHERE ref_albaran_proveedor = %s AND id_proveedor = %s",
            (invoice, db_provider_id)
        )
        existing = cur.fetchone()
        if existing:
            return {'ok': True, 'hoja_id': existing[0], 'ordenes_count': 0,
                    'message': 'Hoja de orden ya existe para esta factura'}

        # Crear hoja de orden
        cur.execute("""
            INSERT INTO hoja_orden
                (ref_albaran_proveedor, id_proveedor, vuelo, tipo_producto, serie, creador_id)
            VALUES (%s, %s, %s, 'Flor', 'CO', 1)
        """, (invoice, db_provider_id, header.get('awb', '')))
        hoja_id = cur.lastrowid

        # Crear líneas de orden
        ordenes_count = 0
        for line in lines_ok:
            stems = line.get('stems', 0)
            spb = line.get('stems_per_bunch', 0)
            bunches = line.get('bunches', 0)
            if bunches == 0 and spb > 0 and stems > 0:
                bunches = stems // spb

            cur.execute("""
                INSERT INTO ordenes
                    (id_hoja_orden, unidades, cantidad_cajas, cantidad_paquetes_caja,
                     precio_compra, lote, creador_id)
                VALUES (%s, %s, %s, %s, %s, %s, 1)
            """, (
                hoja_id,
                stems,
                bunches,
                spb,
                round(line.get('line_total', 0), 2),
                str(line.get('articulo_id', '')),
            ))
            ordenes_count += 1

        conn.commit()
        conn.close()

        logger.info("Hoja de orden %d creada: %d líneas (%s)", hoja_id, ordenes_count, invoice)
        return {'ok': True, 'hoja_id': hoja_id, 'ordenes_count': ordenes_count}

    except Exception as e:
        logger.error("Error creando hoja de orden: %s", e)
        return {'ok': False, 'error': str(e)}
