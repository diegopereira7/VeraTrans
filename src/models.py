"""Modelos de datos: InvoiceHeader, InvoiceLine y excepciones custom."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.config import (
    translate_carnation_color,
    DEFAULT_SIZE_CARNATIONS,
    DEFAULT_SIZE_HYDRANGEAS,
    DEFAULT_SPB_HYDRANGEAS,
)


# --- Excepciones ---

class TraductorError(Exception):
    """Error base del traductor."""

class ParseError(TraductorError):
    """Error al parsear un PDF o el dump SQL."""

class MatchError(TraductorError):
    """Error en el proceso de matching."""

class ExportError(TraductorError):
    """Error al exportar datos."""


# --- Modelos ---

@dataclass
class InvoiceHeader:
    """Cabecera de una factura de proveedor."""
    invoice_number: str = ''
    date: str = ''
    awb: str = ''
    hawb: str = ''
    provider_key: str = ''
    provider_id: int = 0
    provider_name: str = ''
    total: float = 0.0
    airline: str = ''
    incoterm: str = ''


@dataclass
class InvoiceLine:
    """Línea individual de una factura (un producto)."""
    # Datos de factura
    raw_description: str = ''
    species: str = 'ROSES'
    variety: str = ''
    grade: str = ''
    origin: str = 'EC'
    size: int = 0
    stems_per_bunch: int = 0
    bunches: int = 0
    stems: int = 0
    price_per_stem: float = 0.0
    price_per_bunch: float = 0.0
    line_total: float = 0.0
    label: str = ''
    farm: str = ''
    box_type: str = ''
    provider_key: str = ''
    # Resultado del match
    articulo_id: Optional[int] = None
    articulo_name: str = ''
    match_status: str = 'pendiente'
    match_method: str = ''

    def expected_name(self) -> str:
        """Construye el nombre esperado en VeraBuy según especie y origen.

        Returns:
            Nombre normalizado tal como debería existir en la BD de artículos.
        """
        v = self.variety.upper()
        s = self.size
        u = self.stems_per_bunch
        g = self.grade.upper()

        if self.species == 'ROSES':
            orig = 'EC' if self.origin == 'EC' else 'COL'
            if orig == 'EC':
                return f"ROSA EC {v} {s}CM {u}U" if s and u else f"ROSA EC {v}"
            return f"ROSA COL {v} {s}CM {u}U" if s and u else f"ROSA COL {v}"

        if self.species == 'CARNATIONS':
            color = translate_carnation_color(v)
            sz = s if s else DEFAULT_SIZE_CARNATIONS
            if self.provider_key == 'golden':
                prefix = 'MINI CLAVEL' if u == 10 else 'CLAVEL'
                return f"{prefix} FANCY {color} {sz}CM {u}U GOLDEN"
            if 'SPRAY' in v.upper():
                base = f"CLAVEL SPRAY {g} {color} {sz}CM {u}U" if g else f"CLAVEL SPRAY {color} {sz}CM {u}U"
                return base.replace('  ', ' ')
            base = f"CLAVEL COL {g} {color} {sz}CM {u}U" if g else f"CLAVEL COL {color} {sz}CM {u}U"
            return base.replace('  ', ' ')

        if self.species == 'HYDRANGEAS':
            if self.provider_key == 'latin':
                return f"HYDRANGEA {v} {DEFAULT_SIZE_HYDRANGEAS}CM {DEFAULT_SPB_HYDRANGEAS}U LATIN"
            return f"HYDRANGEA {v} {s}CM {u}U" if s and u else f"HYDRANGEA {v}"

        if self.species == 'ALSTROEMERIA':
            orig = 'COL' if self.origin == 'COL' else 'EC'
            if s:
                return f"ALSTROMERIA {orig} {g} {v} {s}CM {u}U".replace('  ', ' ')
            return f"ALSTROMERIA {orig} {v}"

        if self.species == 'GYPSOPHILA':
            return f"PANICULATA {v}"

        if self.species == 'CHRYSANTHEMUM':
            if self.provider_key == 'sayonara':
                return f"CRISANTEMO {v} {s}CM {u}U SAYONARA"
            return f"CRISANTEMO {v} {s}CM {u}U" if s else f"CRISANTEMO {v}"

        return v

    def match_key(self) -> str:
        """Clave única para buscar/guardar sinónimos."""
        return f"{self.species}|{self.variety.upper()}|{self.size}|{self.stems_per_bunch}|{self.grade.upper()}"
