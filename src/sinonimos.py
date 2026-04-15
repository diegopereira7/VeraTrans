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
    """Almacén persistente de sinónimos. Escribe a JSON + MySQL (si disponible).

    Desde la sesión 6 cada entrada puede llevar metadatos de fiabilidad:

        status: ``manual_confirmado`` | ``aprendido_confirmado`` |
                ``aprendido_en_prueba`` | ``ambiguo`` | ``rechazado``
        times_used: nº de veces que un matcher propuso el sinónimo.
        times_confirmed: nº de veces que un humano lo aceptó (origen manual).
        times_corrected: nº de veces que un humano lo cambió a otro artículo.
        last_confirmed_at: ISO timestamp de la última confirmación.
        first_seen_at: ISO timestamp de la primera vez que se creó.

    Los sinónimos antiguos que no traían estos campos los reciben con
    defaults conservadores (`aprendido_en_prueba`, contadores en 0) — no
    se asume que valen como "manual confirmado" hasta que el humano
    los toque. Así un sinónimo recién aprendido no puede saltarse
    contradicciones estructurales.
    """

    # Mapeo origen → status inicial si la entrada no trae status explícito.
    _STATUS_BY_ORIGIN = {
        'manual':         'manual_confirmado',
        'manual-web':     'manual_confirmado',
        'manual-batch':   'manual_confirmado',
        'revisado':       'manual_confirmado',
        'auto':           'aprendido_en_prueba',
        'auto-fuzzy':     'aprendido_en_prueba',
        'auto-matching':  'aprendido_en_prueba',
        'auto-marca':     'aprendido_en_prueba',
        'auto-delegacion':'aprendido_en_prueba',
        'auto-color-strip':'aprendido_en_prueba',
    }

    # Score de fiabilidad asignado por status. Se usa como feature en el
    # matcher — un sinónimo `manual_confirmado` pesa casi 1.0, uno
    # `aprendido_en_prueba` solo 0.55 (nunca máxima por defecto).
    _TRUST_BY_STATUS = {
        'manual_confirmado':     0.98,
        'aprendido_confirmado':  0.85,
        'aprendido_en_prueba':   0.55,
        'ambiguo':               0.30,
        'rechazado':             0.00,
    }

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

    @classmethod
    def trust_score(cls, entry: dict) -> float:
        """Score 0-1 de fiabilidad del sinónimo.

        Se deriva de `status` (default por origen si no existe) y se modula
        por ``times_confirmed`` / ``times_corrected``. Un sinónimo con
        muchas correcciones previas pierde peso aunque siga en estado
        ``aprendido_en_prueba``.
        """
        if not entry:
            return 0.0
        status = entry.get('status')
        if not status:
            status = cls._STATUS_BY_ORIGIN.get(entry.get('origen', ''),
                                               'aprendido_en_prueba')
        base = cls._TRUST_BY_STATUS.get(status, 0.40)
        tc = int(entry.get('times_confirmed', 0) or 0)
        tx = int(entry.get('times_corrected', 0) or 0)
        if tx > 0:
            # Cada corrección quita 15% del trust (con piso en 0.1).
            base = max(0.10, base - 0.15 * tx)
        elif tc > 1:
            # Confirmaciones repetidas suben, asintóticamente hasta el tope
            # del status (no superan `manual_confirmado`).
            base = min(cls._TRUST_BY_STATUS['manual_confirmado'],
                       base + 0.05 * min(tc - 1, 5))
        return round(base, 3)

    def mark_used(self, provider_id: int, line: InvoiceLine) -> None:
        """Incrementa times_used del sinónimo si existe. No persiste en caliente:
        los contadores se guardan al next save() normal. Silencioso si no existe.
        """
        k = self._key(provider_id, line)
        entry = self.syns.get(k)
        if not entry:
            return
        entry['times_used'] = int(entry.get('times_used', 0) or 0) + 1

    def mark_confirmed(self, provider_id: int, line: InvoiceLine,
                       articulo_id: int) -> None:
        """Marca el sinónimo como confirmado por el operador (ascenso de status)."""
        k = self._key(provider_id, line)
        entry = self.syns.get(k)
        if not entry or entry.get('articulo_id') != articulo_id:
            return
        entry['times_confirmed'] = int(entry.get('times_confirmed', 0) or 0) + 1
        entry['last_confirmed_at'] = datetime.now().isoformat(timespec='seconds')
        # Ascenso: aprendido_en_prueba → aprendido_confirmado tras 1ª confirmación.
        if entry.get('status') in (None, 'aprendido_en_prueba'):
            entry['status'] = 'aprendido_confirmado'
        self.save()

    def mark_corrected(self, provider_id: int, line: InvoiceLine,
                       old_articulo_id: int) -> None:
        """El operador corrigió el sinónimo a otro artículo. Lo degrada."""
        k = self._key(provider_id, line)
        entry = self.syns.get(k)
        if not entry or entry.get('articulo_id') != old_articulo_id:
            return
        entry['times_corrected'] = int(entry.get('times_corrected', 0) or 0) + 1
        # 2+ correcciones → rechazado (no se volverá a usar).
        if int(entry.get('times_corrected', 0)) >= 2:
            entry['status'] = 'rechazado'
        else:
            entry['status'] = 'ambiguo'
        self.save()

    # Mapeo de origenes lógicos del proyecto al enum real de la columna
    # `origen` en MySQL: ENUM('manual','auto','auto-fuzzy').
    _ORIGEN_MAP = {
        'manual':       'manual',
        'manual-web':   'manual',
        'manual-batch': 'manual',
        'revisado':     'manual',
        'auto':         'auto',
        'auto-fuzzy':   'auto-fuzzy',
    }

    def _sync_to_mysql(self, key: str, entry: dict) -> None:
        """Sincroniza una entrada a MySQL (best-effort, no falla si MySQL caído).

        El schema real de la tabla `sinonimos` usa nombres en español
        (id_articulo, nombre_articulo, id_proveedor, nombre_factura, especie,
        talla, grado) y `origen` es un ENUM restringido. Esta función mapea
        los campos del entry interno (estilo JSON) a esas columnas.
        """
        if not MYSQL_AVAILABLE:
            return
        try:
            conn = get_connection()
            cur = conn.cursor()
            origen = self._ORIGEN_MAP.get(entry.get('origen', ''), 'manual')
            cur.execute("""
                INSERT INTO sinonimos
                    (clave, id_proveedor, nombre_factura, especie, talla,
                     stems_per_bunch, grado, id_articulo, nombre_articulo, origen)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    id_articulo     = VALUES(id_articulo),
                    nombre_articulo = VALUES(nombre_articulo),
                    origen          = VALUES(origen)
            """, (
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
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("MySQL sync sinónimo falló: %s", e)

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
        """Añade o actualiza un sinónimo.

        Si el sinónimo ya existe y se está actualizando al MISMO artículo,
        se preservan contadores (times_used/confirmed/corrected). Si cambia
        el artículo, se asume que el operador lo corrigió → llama a
        mark_corrected antes de pisar y reinicia el nuevo con status
        adecuado por origin.
        """
        k = self._key(provider_id, line)
        prev = self.syns.get(k)
        now = datetime.now().isoformat(timespec='seconds')

        # Si cambia el artículo, marcar el viejo como corregido antes de pisarlo.
        if prev and prev.get('articulo_id') and prev['articulo_id'] != articulo_id:
            prev['times_corrected'] = int(prev.get('times_corrected', 0) or 0) + 1
            if int(prev['times_corrected']) >= 2:
                prev['status'] = 'rechazado'
            else:
                prev['status'] = 'ambiguo'

        # Conservar contadores si es el mismo artículo (refresh de metadatos).
        if prev and prev.get('articulo_id') == articulo_id:
            times_used = int(prev.get('times_used', 0) or 0)
            times_confirmed = int(prev.get('times_confirmed', 0) or 0)
            times_corrected = int(prev.get('times_corrected', 0) or 0)
            first_seen = prev.get('first_seen_at', now)
            last_confirmed = prev.get('last_confirmed_at', '')
            prev_status = prev.get('status')
        else:
            times_used = times_confirmed = times_corrected = 0
            first_seen = now
            last_confirmed = ''
            prev_status = None

        # Derivar status del origin si no viene o si es creación nueva.
        status = prev_status or self._STATUS_BY_ORIGIN.get(origin, 'aprendido_en_prueba')
        # Un alta manual siempre asciende (aunque ya existiera en prueba).
        if origin in ('manual', 'manual-web', 'manual-batch', 'revisado'):
            status = 'manual_confirmado'
            times_confirmed += 1
            last_confirmed = now

        entry = {
            'articulo_id': articulo_id,
            'articulo_name': articulo_name,
            'origen': origin,
            'status': status,
            'provider_id': provider_id,
            'species': line.species,
            'variety': line.variety.upper(),
            'size': line.size,
            'stems_per_bunch': line.stems_per_bunch,
            'grade': line.grade.upper(),
            'raw': getattr(line, 'raw_description', '')[:120],
            'invoice': invoice,
            'times_used': times_used,
            'times_confirmed': times_confirmed,
            'times_corrected': times_corrected,
            'first_seen_at': first_seen,
            'last_confirmed_at': last_confirmed,
        }
        self.syns[k] = entry
        self.save()
        self._sync_to_mysql(k, entry)

    def provider_article_usage(self, provider_id: int, articulo_id: int) -> int:
        """Cuenta cuántos sinónimos distintos del mismo proveedor apuntan a ese
        artículo. Señal simple de "este proveedor usa habitualmente este
        artículo"; si es ≥2 hay respaldo histórico razonable.
        """
        if not provider_id or not articulo_id:
            return 0
        n = 0
        for s in self.syns.values():
            if (s.get('provider_id') == provider_id
                    and s.get('articulo_id') == articulo_id
                    and s.get('status') != 'rechazado'):
                n += 1
        return n

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
