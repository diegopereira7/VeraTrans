"""Gestión del diccionario de sinónimos (JSON + MySQL dual-write)."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from src.config import SYNS_FILE, FILE_ENCODING
from src.models import InvoiceLine

logger = logging.getLogger(__name__)

# MySQL opcional
try:
    from src.db import get_connection, MYSQL_AVAILABLE
except Exception:
    MYSQL_AVAILABLE = False


class SynonymStore:
    """Almacén persistente de sinónimos. Escribe a JSON + MySQL (si disponible)."""

    def __init__(self, fp: str | Path = SYNS_FILE):
        self.fp = Path(fp)
        self.syns: dict = {}
        if self.fp.exists():
            with open(self.fp, 'r', encoding=FILE_ENCODING) as f:
                self.syns = json.load(f)
            logger.debug("Sinónimos cargados: %d desde %s", len(self.syns), self.fp)

    def save(self) -> None:
        """Persiste los sinónimos a JSON."""
        with open(self.fp, 'w', encoding=FILE_ENCODING) as f:
            json.dump(self.syns, f, indent=2, ensure_ascii=False)

    def _sync_to_mysql(self, key: str, entry: dict) -> None:
        """Sincroniza una entrada a MySQL (best-effort, no falla si MySQL caído)."""
        if not MYSQL_AVAILABLE:
            return
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO sinonimos (clave, articulo_id, articulo_name, origen,
                    provider_id, species, variety, size, stems_per_bunch, grade, raw, invoice)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                    articulo_id=VALUES(articulo_id), articulo_name=VALUES(articulo_name),
                    origen=VALUES(origen), raw=VALUES(raw), invoice=VALUES(invoice)
            """, (key, entry.get('articulo_id', 0), entry.get('articulo_name', ''),
                  entry.get('origen', ''), entry.get('provider_id', 0),
                  entry.get('species', ''), entry.get('variety', ''),
                  entry.get('size', 0), entry.get('stems_per_bunch', 0),
                  entry.get('grade', ''), entry.get('raw', ''), entry.get('invoice', '')))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug("MySQL sync falló (no crítico): %s", e)

    def _key(self, provider_id: int, line: InvoiceLine) -> str:
        return f"{provider_id}|{line.match_key()}"

    def find(self, provider_id: int, line: InvoiceLine) -> dict | None:
        """Busca un sinónimo para la línea dada.

        Si no hay match exacto por stems_per_bunch, intenta con spb=0
        (sinónimo genérico que ignora SPB como discriminador).
        """
        exact = self.syns.get(self._key(provider_id, line))
        if exact:
            return exact
        # Fallback: intentar con stems_per_bunch=0
        if line.stems_per_bunch != 0:
            fallback_key = (f"{provider_id}|{line.species}|{line.variety.upper()}"
                            f"|{line.size}|0|{line.grade.upper()}")
            return self.syns.get(fallback_key)
        return None

    def add(self, provider_id: int, line: InvoiceLine,
            articulo_id: int, articulo_name: str, origin: str = 'manual',
            invoice: str = '') -> None:
        """Añade o actualiza un sinónimo."""
        k = self._key(provider_id, line)
        entry = {
            'articulo_id': articulo_id,
            'articulo_name': articulo_name,
            'origen': origin,
            'provider_id': provider_id,
            'species': line.species,
            'variety': line.variety.upper(),
            'size': line.size,
            'stems_per_bunch': line.stems_per_bunch,
            'grade': line.grade.upper(),
            'raw': getattr(line, 'raw_description', '')[:120],
            'invoice': invoice,
        }
        self.syns[k] = entry
        self.save()
        self._sync_to_mysql(k, entry)

    def count(self) -> int:
        """Número total de sinónimos."""
        return len(self.syns)

    def export_sql(self) -> str:
        """Genera INSERT SQL para la tabla sinonimos_producto de VeraBuy."""
        if not self.syns:
            return '-- No hay sinónimos'
        lines = [
            "-- Sinónimos Universales — verabuy_trainer.py",
            f"-- {datetime.now():%Y-%m-%d %H:%M} — {len(self.syns)} sinónimos", "",
            "INSERT INTO `sinonimos_producto`",
            "    (`id_proveedor`,`nombre_factura`,`especie`,`talla`,`stems_per_bunch`,",
            "     `id_articulo`,`nombre_articulo`,`confianza`,`origen`)",
            "VALUES",
        ]
        vals = []
        pend = []
        for syn in sorted(self.syns.values(), key=lambda s: (s['provider_id'], s['species'], s['variety'])):
            if syn['articulo_id'] == 0:
                pend.append(syn)
                continue
            en = syn['articulo_name'].replace("'", "\\'")
            sp = syn.get('species', 'ROSES')
            vals.append(
                f"    ({syn['provider_id']},'{syn['variety']}','{sp}',"
                f"{syn['size']},{syn['stems_per_bunch']},"
                f"{syn['articulo_id']},'{en}',100,'{syn['origen']}')"
            )
        if vals:
            lines.append(',\n'.join(vals) + ';')
        if pend:
            lines += ['', f'-- PENDIENTES DE ALTA ({len(pend)}):']
            for p in pend:
                lines.append(f"--   {p.get('species', '')} {p['variety']} {p['size']}CM {p['stems_per_bunch']}U")
        return '\n'.join(lines)
