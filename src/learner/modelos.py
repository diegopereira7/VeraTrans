"""Modelos de datos para el sistema de auto-aprendizaje."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass
class PDFFingerprint:
    """Huella estructural de un PDF de factura."""

    # Identificación
    pdf_path: str = ''
    proveedor_candidato: str = ''
    keywords_encontrados: list[str] = field(default_factory=list)

    # Estructura de páginas
    num_paginas: int = 0
    tiene_tablas: bool = False
    num_tablas_por_pagina: list[int] = field(default_factory=list)

    # Estructura de tablas
    num_columnas_tabla_principal: int = 0
    headers_tabla: list[str] = field(default_factory=list)
    headers_originales: list[str] = field(default_factory=list)

    # Estructura de texto
    separador_campos: str = ''
    num_campos_por_linea: int = 0
    lineas_datos: list[str] = field(default_factory=list)

    # Layout
    zona_header_lines: int = 0
    zona_footer_lines: int = 0
    texto_completo: str = ''

    # Hash y confianza
    hash_estructura: str = ''
    confianza_deteccion: float = 0.0

    def calcular_hash(self):
        """Calcula hash basado en estructura (no contenido)."""
        datos = '|'.join([
            str(self.tiene_tablas),
            str(self.num_columnas_tabla_principal),
            ','.join(sorted(self.headers_tabla)),
            self.separador_campos,
            str(self.num_campos_por_linea),
        ])
        self.hash_estructura = hashlib.md5(datos.encode()).hexdigest()[:12]


@dataclass
class ExtractionRule:
    """Regla de extracción inferida para un campo."""

    campo_destino: str = ''
    tipo: str = ''  # 'columna_tabla', 'regex_texto', 'posicion_fija', 'header_regex'

    # Para columna_tabla
    indice_columna: int | None = None
    header_columna: str | None = None

    # Para regex_texto
    patron_regex: str | None = None
    grupo_captura: int | None = None

    # Transformación
    transformacion: str | None = None  # 'strip', 'upper', 'float', 'int', 'split_color'

    # Confianza y evidencia
    confianza: float = 0.0
    evidencia: list[str] = field(default_factory=list)


@dataclass
class LearnedParser:
    """Parser auto-generado."""

    nombre: str = ''
    keywords: list[str] = field(default_factory=list)
    provider_id: int = 0
    species: str = ''
    origin: str = ''

    # Reglas de extracción
    header_rules: list[ExtractionRule] = field(default_factory=list)
    line_rules: list[ExtractionRule] = field(default_factory=list)
    line_regex: str = ''

    # Defaults
    default_spb: int = 0
    default_size: int = 0

    # Metadatos
    score: float = 0.0
    decision: str = ''  # VERDE, AMARILLO, ROJO
    fecha_generacion: str = ''
    num_pdfs_analizados: int = 0
    activo: bool = True

    def to_dict(self) -> dict:
        """Serializa a dict para JSON."""
        return {
            'nombre': self.nombre,
            'keywords': self.keywords,
            'provider_id': self.provider_id,
            'species': self.species,
            'origin': self.origin,
            'header_rules': [_rule_to_dict(r) for r in self.header_rules],
            'line_rules': [_rule_to_dict(r) for r in self.line_rules],
            'line_regex': self.line_regex,
            'default_spb': self.default_spb,
            'default_size': self.default_size,
            'score': self.score,
            'decision': self.decision,
            'fecha_generacion': self.fecha_generacion,
            'num_pdfs_analizados': self.num_pdfs_analizados,
            'activo': self.activo,
        }

    @classmethod
    def from_dict(cls, d: dict) -> LearnedParser:
        """Deserializa desde dict."""
        obj = cls(
            nombre=d.get('nombre', ''),
            keywords=d.get('keywords', []),
            provider_id=d.get('provider_id', 0),
            species=d.get('species', ''),
            origin=d.get('origin', ''),
            line_regex=d.get('line_regex', ''),
            default_spb=d.get('default_spb', 0),
            default_size=d.get('default_size', 0),
            score=d.get('score', 0),
            decision=d.get('decision', ''),
            fecha_generacion=d.get('fecha_generacion', ''),
            num_pdfs_analizados=d.get('num_pdfs_analizados', 0),
            activo=d.get('activo', True),
        )
        obj.header_rules = [_dict_to_rule(r) for r in d.get('header_rules', [])]
        obj.line_rules = [_dict_to_rule(r) for r in d.get('line_rules', [])]
        return obj


def _rule_to_dict(r: ExtractionRule) -> dict:
    return {
        'campo_destino': r.campo_destino,
        'tipo': r.tipo,
        'indice_columna': r.indice_columna,
        'header_columna': r.header_columna,
        'patron_regex': r.patron_regex,
        'grupo_captura': r.grupo_captura,
        'transformacion': r.transformacion,
        'confianza': r.confianza,
        'evidencia': r.evidencia[:5],
    }


def _dict_to_rule(d: dict) -> ExtractionRule:
    return ExtractionRule(
        campo_destino=d.get('campo_destino', ''),
        tipo=d.get('tipo', ''),
        indice_columna=d.get('indice_columna'),
        header_columna=d.get('header_columna'),
        patron_regex=d.get('patron_regex'),
        grupo_captura=d.get('grupo_captura'),
        transformacion=d.get('transformacion'),
        confianza=d.get('confianza', 0),
        evidencia=d.get('evidencia', []),
    )
