"""Capa de acceso a datos MySQL para verabuy-traductor.

Cada función tiene fallback a ficheros JSON si MySQL no está disponible.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '',
    'database': 'traductor-verabuy',
    'charset': 'utf8mb4',
    'port': 3306,
}

try:
    import pymysql
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False


def get_connection():
    """Retorna conexión a MySQL. Lanza excepción si no conecta."""
    return pymysql.connect(**DB_CONFIG)


def mysql_available() -> bool:
    """Verifica si MySQL está disponible y responde."""
    if not MYSQL_AVAILABLE:
        return False
    try:
        conn = get_connection()
        conn.ping()
        conn.close()
        return True
    except Exception:
        return False
