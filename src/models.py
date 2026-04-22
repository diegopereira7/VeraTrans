"""Modelos de datos: InvoiceHeader, InvoiceLine y excepciones custom."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from src.config import (
    translate_carnation_color,
    DEFAULT_SIZE_CARNATIONS,
    DEFAULT_SIZE_HYDRANGEAS,
    DEFAULT_SPB_HYDRANGEAS,
)


_NON_ALNUM_RE = re.compile(r'[^A-Z0-9 ]+')


def normalize_variety_key(variety: str) -> str:
    """Canonicaliza la variedad para construir la synonym_key.

    Motivación: el parser a veces emite una variedad con puntuación
    (`MANDARIN. X-PRESSION`, `O'HARA`, `EXPLORER°`) y a veces sin, según
    cómo haya extraído pdfplumber la celda o según pase por OCR. Si dos
    variantes de la misma variedad producen claves distintas, el
    sinónimo guardado por el operador no se reutiliza y aparece como
    línea a corregir de nuevo. La clave canónica colapsa todos esos
    caracteres a espacios y compacta.
    """
    v = (variety or '').upper()
    v = _NON_ALNUM_RE.sub(' ', v)
    return ' '.join(v.split())


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
    # Confianza de extracción y matching (0.0-1.0).
    # ocr_confidence: 1.0 si el texto era nativo del PDF; <1.0 si vino de OCR.
    #   Se mantiene por compatibilidad con código que lo leía directamente.
    # extraction_confidence: señal agregada que también tiene en cuenta
    #   degradación (páginas sin extraer, texto corrupto, mezcla nativo+OCR).
    #   Puede ser menor que ocr_confidence aunque el OCR fuera bueno si el
    #   documento requiere revisión por otros motivos.
    # extraction_source: 'native' | 'mixed' | 'ocr' | 'empty' | 'rescue'.
    #   'rescue' indica que la línea entró por la red de seguridad (regex
    #   genérico sobre texto no parseado), no por el parser específico —
    #   la UI la pinta distinto para no disimular el fallo del parser.
    # match_confidence: se asigna según la etapa del pipeline que resolvió la línea.
    # field_confidence: confianza por campo extraído; permite enviar a revisión
    #                   humana solo los campos inciertos (ver validate.py).
    # validation_errors: lista de reglas cruzadas que fallaron (totales, stems…).
    ocr_confidence: float = 1.0
    extraction_confidence: float = 1.0
    extraction_source: str = 'native'
    match_confidence: float = 0.0
    # link_confidence: confianza de VINCULACIÓN (qué tan bien encaja el artículo
    #   ERP con la línea, según evidencia: especie, talla, origen, marca,
    #   histórico del proveedor, fiabilidad del sinónimo, margen frente al 2º).
    #   Es la señal que la UI debería usar para decidir "a revisar". A
    #   diferencia de match_confidence (que es producto de todas las confianzas)
    #   link_confidence aísla solo el vínculo, sin que la extracción degradada
    #   lo arrastre.
    # candidate_margin: diferencia de score entre el mejor candidato y el 2º.
    #   Margen < 0.10 indica empate práctico y la línea se marca ambigua.
    # candidate_count: número de candidatos considerados tras los vetos.
    # match_reasons / match_penalties: features que aportaron o restaron al
    #   score del candidato ganador. Trazabilidad para el operador humano.
    # top_candidates: lista resumen {id, nombre, score, reasons} con los ≤3
    #   mejores candidatos para que la UI pueda ofrecerlos alternativos.
    link_confidence: float = 0.0
    candidate_margin: float = 0.0
    candidate_count: int = 0
    match_reasons: list = field(default_factory=list)
    match_penalties: list = field(default_factory=list)
    top_candidates: list = field(default_factory=list)
    field_confidence: dict = field(default_factory=dict)
    validation_errors: list = field(default_factory=list)
    # review_lane: carril de revisión asignado post-matching.
    #   'auto'     — autoaprobable, no necesita revisión humana
    #   'quick'    — revisión rápida, razonablemente bueno pero no sólido
    #   'full'     — revisión completa, problema claro
    # Se asigna con classify_review_lane() después de validación.
    review_lane: str = ''

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
        """Clave única para buscar/guardar sinónimos.

        La variedad se canonicaliza con `normalize_variety_key` para que
        `MANDARIN. X-PRESSION`, `MANDARIN X-PRESSION` y `MANDARIN X PRESSION`
        produzcan la misma clave y no se creen sinónimos duplicados
        fantasmas al variar la puntuación entre extracciones.
        """
        return f"{self.species}|{normalize_variety_key(self.variety)}|{self.size}|{self.stems_per_bunch}|{self.grade.upper()}"
