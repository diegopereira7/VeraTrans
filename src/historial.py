"""Gestión del historial de facturas procesadas (JSON + MySQL dual-write)."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from src.config import HIST_FILE, FILE_ENCODING

logger = logging.getLogger(__name__)

try:
    from src.db import get_connection, MYSQL_AVAILABLE
except Exception:
    MYSQL_AVAILABLE = False


class History:
    """Registro persistente de facturas procesadas. Escribe a JSON + MySQL."""

    def __init__(self, fp: str | Path = HIST_FILE):
        self.fp = Path(fp)
        self.entries: dict = {}
        if self.fp.exists():
            with open(self.fp, 'r', encoding=FILE_ENCODING) as f:
                self.entries = json.load(f)
            logger.debug("Historial cargado: %d entradas desde %s", len(self.entries), self.fp)

    def save(self) -> None:
        """Persiste el historial a JSON."""
        with open(self.fp, 'w', encoding=FILE_ENCODING) as f:
            json.dump(self.entries, f, indent=2, ensure_ascii=False)

    def add(self, inv: str, pdf: str, provider: str, total: float,
            n: int, ok: int, fail: int, pdf_path: str = '') -> None:
        """Registra una factura procesada."""
        fecha = f"{datetime.now():%Y-%m-%d %H:%M}"
        entry = {
            'pdf': pdf, 'provider': provider, 'total_usd': total,
            'lineas': n, 'ok': ok, 'sin_match': fail,
            'fecha': fecha,
        }
        if pdf_path:
            entry['pdf_path'] = pdf_path
        elif inv in self.entries and self.entries[inv].get('pdf_path'):
            entry['pdf_path'] = self.entries[inv]['pdf_path']
        self.entries[inv] = entry
        self.save()
        # Sync a MySQL — el schema real usa nombres en español
        # (numero_factura, pdf_nombre, proveedor, ok_count, sin_match,
        #  fecha_proceso) y `numero_factura` es la clave única.
        if MYSQL_AVAILABLE:
            try:
                conn = get_connection()
                cur = conn.cursor()
                cur.execute("""
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
                """, (inv, pdf, provider, total, n, ok, fail, fecha + ':00'))
                conn.commit()
                conn.close()
            except Exception as e:
                logger.warning("MySQL historial sync falló: %s", e)

    def was_processed(self, inv: str) -> bool:
        """Comprueba si una factura ya fue procesada."""
        return inv in self.entries
