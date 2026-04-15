"""Conciliación a dos bandas: factura actual ↔ histórico de órdenes.

El artículo anyformat.ai/es/use-cases/invoice-processing describe la
conciliación como el paso que valida la extracción contra datos maestros
(órdenes de compra, contratos, históricos de proveedor).

VeraBuy no guarda órdenes de compra "esperadas" antes de recibir la
factura — las `hoja_orden` se crean A PARTIR de la factura. La
conciliación realista aquí es contra el HISTÓRICO: para cada línea,
comparar el precio con la media reciente del mismo artículo en el mismo
proveedor. Si la desviación supera un umbral, marcamos `price_delta` y
bajamos la confianza de la línea.

Esto detecta:
  - Errores de extracción (precios mal parseados, coma/punto decimal).
  - Cambios reales de precio que deben validarse manualmente.
  - Proveedores que "cuelan" subidas de precio entre facturas.
"""
from __future__ import annotations

import logging
from typing import Iterable

from src.db import get_connection, MYSQL_AVAILABLE
from src.models import InvoiceLine

logger = logging.getLogger(__name__)


# Desviación relativa de precio considerada anómala (15%).
_PRICE_TOLERANCE = 0.15
# Ventana de histórico a mirar (últimas N hojas del proveedor).
_HISTORY_WINDOW = 20


def _fetch_recent_prices(provider_id: int,
                         articulo_ids: list[int]) -> dict[int, float]:
    """Precio medio reciente por articulo_id para un proveedor.

    Consulta las últimas _HISTORY_WINDOW hojas de orden del proveedor y
    calcula la media de precio_unitario (precio_compra / unidades) por
    artículo. Devuelve {} si MySQL no responde — la reconciliación es
    best-effort, nunca bloqueante.
    """
    if not MYSQL_AVAILABLE or not articulo_ids:
        return {}
    try:
        conn = get_connection()
        cur = conn.cursor()
        placeholders = ','.join(['%s'] * len(articulo_ids))
        # Las líneas guardan articulo_id en `lote` (ver orden.py:81). La media
        # se pondera por unidades para que una hoja con 1 tallo no desvíe
        # la referencia frente a otra con 3000.
        cur.execute(f"""
            SELECT o.lote, AVG(o.precio_compra / NULLIF(o.unidades, 0))
              FROM ordenes o
              JOIN hoja_orden h ON h.id = o.id_hoja_orden
             WHERE h.id_proveedor = %s
               AND o.lote IN ({placeholders})
               AND o.unidades > 0
               AND h.id IN (
                    SELECT id FROM hoja_orden
                     WHERE id_proveedor = %s
                  ORDER BY id DESC LIMIT %s
               )
             GROUP BY o.lote
        """, (provider_id, *articulo_ids, provider_id, _HISTORY_WINDOW))
        rows = cur.fetchall()
        conn.close()
        out: dict[int, float] = {}
        for lote, avg_price in rows:
            try:
                out[int(lote)] = float(avg_price)
            except (TypeError, ValueError):
                continue
        return out
    except Exception as e:
        logger.debug("reconciliación: consulta histórico falló: %s", e)
        return {}


def reconcile(provider_id: int, lines: Iterable[InvoiceLine]) -> dict:
    """Compara cada línea con su precio histórico y anota desviaciones.

    Muta las líneas:
      - Añade 'price_delta_pct' a validation_errors si supera tolerancia.
      - Baja match_confidence a 0.60 en líneas con desviación severa.

    Devuelve resumen con contadores y lista de desviaciones para el frontend.
    """
    lines = list(lines)
    articulo_ids = sorted({l.articulo_id for l in lines
                           if l.articulo_id and l.match_status == 'ok'})
    refs = _fetch_recent_prices(provider_id, articulo_ids)

    deltas: list[dict] = []
    for l in lines:
        if not l.articulo_id or l.match_status != 'ok':
            continue
        if l.price_per_stem <= 0:
            continue
        ref = refs.get(l.articulo_id)
        if not ref or ref <= 0:
            continue
        delta = (l.price_per_stem - ref) / ref
        if abs(delta) > _PRICE_TOLERANCE:
            l.validation_errors = list(l.validation_errors) + [
                f'price_delta {delta*100:+.1f}% vs histórico {ref:.4f}'
            ]
            # Desviación severa (>2× tolerancia): bajamos confianza más.
            if abs(delta) > _PRICE_TOLERANCE * 2:
                l.match_confidence = min(l.match_confidence, 0.55)
            else:
                l.match_confidence = min(l.match_confidence, 0.70)
            deltas.append({
                'articulo_id':    l.articulo_id,
                'articulo_name':  l.articulo_name,
                'price_current':  round(l.price_per_stem, 4),
                'price_ref':      round(ref, 4),
                'delta_pct':      round(delta * 100, 1),
            })

    return {
        'checked_lines': sum(1 for l in lines
                             if l.articulo_id and l.match_status == 'ok'),
        'with_history':  len(refs),
        'anomalies':     len(deltas),
        'deltas':        deltas,
    }
