"""Fase 5: Generación de parsers funcionales a partir de reglas inferidas."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from src.config import BASE_DIR
from src.models import InvoiceHeader, InvoiceLine
from .modelos import PDFFingerprint, ExtractionRule, LearnedParser

LEARNED_RULES_FILE = BASE_DIR / 'learned_rules.json'


def generar_parser(
    nombre: str,
    reglas: list[ExtractionRule],
    cluster_fps: list[PDFFingerprint],
    score: float,
) -> LearnedParser:
    """Genera un LearnedParser funcional a partir de reglas validadas."""
    # Extraer keywords del cluster
    keywords = _extract_keywords(cluster_fps)

    # Determinar species y origin
    species = 'ROSES'
    origin = 'EC'
    for r in reglas:
        if r.campo_destino == 'species' and r.transformacion:
            species = r.transformacion

    # Determinar defaults según especie
    default_spb, default_size = _species_defaults(species)

    # Separar reglas de header y línea
    header_rules = [r for r in reglas if r.tipo == 'header_regex']
    line_rules = [r for r in reglas
                  if r.tipo in ('columna_tabla', 'posicion_fija', 'regex_texto')
                  and r.campo_destino != 'line_pattern' and r.campo_destino != 'species']

    # Buscar regex de línea
    line_regex = ''
    for r in reglas:
        if r.campo_destino == 'line_pattern' and r.patron_regex:
            line_regex = r.patron_regex
            break

    parser = LearnedParser(
        nombre=_sanitize_name(nombre),
        keywords=keywords,
        provider_id=0,
        species=species,
        origin=origin,
        header_rules=header_rules,
        line_rules=line_rules,
        line_regex=line_regex,
        default_spb=default_spb,
        default_size=default_size,
        score=score,
        decision='VERDE' if score >= 0.85 else 'AMARILLO',
        fecha_generacion=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        num_pdfs_analizados=len(cluster_fps),
    )

    return parser


def registrar_parser_aprendido(parser: LearnedParser):
    """Persiste el parser en learned_rules.json y lo registra para uso inmediato."""
    rules = _load_rules()
    rules[parser.nombre] = parser.to_dict()
    _save_rules(rules)

    # Registrar en el registry dinámico
    from src.learned_parsers import _reload_registry
    _reload_registry()


def desactivar_parser(nombre: str):
    """Desactiva un parser aprendido."""
    rules = _load_rules()
    if nombre in rules:
        rules[nombre]['activo'] = False
        _save_rules(rules)
        from src.learned_parsers import _reload_registry
        _reload_registry()


def activar_parser(nombre: str):
    """Activa un parser aprendido."""
    rules = _load_rules()
    if nombre in rules:
        rules[nombre]['activo'] = True
        _save_rules(rules)
        from src.learned_parsers import _reload_registry
        _reload_registry()


def _extract_keywords(fps: list[PDFFingerprint]) -> list[str]:
    """Extrae keywords comunes a todos los PDFs del cluster."""
    if not fps:
        return []

    # Keywords presentes en la mayoría de los PDFs
    all_kw = [set(fp.keywords_encontrados) for fp in fps]
    if not all_kw:
        return []

    common = all_kw[0]
    for kw_set in all_kw[1:]:
        common &= kw_set

    # Añadir el nombre del proveedor candidato como keyword
    provider_names = set()
    for fp in fps:
        if fp.proveedor_candidato:
            # Primera palabra significativa del nombre
            for word in fp.proveedor_candidato.split():
                if len(word) > 3 and word.upper() not in ('S.A.', 'S.A', 'LTDA', 'SLU', 'S.L.'):
                    provider_names.add(word.upper())
                    break

    return sorted(list(common | provider_names))[:10]


def _species_defaults(species: str) -> tuple[int, int]:
    """Retorna (default_spb, default_size) para una especie."""
    return {
        'ROSES': (25, 50),
        'CARNATIONS': (20, 70),
        'HYDRANGEAS': (1, 60),
        'ALSTROEMERIA': (10, 50),
        'GYPSOPHILA': (1, 80),
        'CHRYSANTHEMUM': (10, 70),
    }.get(species, (25, 50))


def _sanitize_name(name: str) -> str:
    """Sanitiza el nombre para usar como identificador."""
    name = name.lower().strip()
    name = re.sub(r'[^a-z0-9]', '_', name)
    name = re.sub(r'_+', '_', name).strip('_')
    return name[:30] or 'unknown'


def _load_rules() -> dict:
    if LEARNED_RULES_FILE.exists():
        return json.loads(LEARNED_RULES_FILE.read_text(encoding='utf-8'))
    return {}


def _save_rules(rules: dict):
    LEARNED_RULES_FILE.parent.mkdir(exist_ok=True)
    LEARNED_RULES_FILE.write_text(
        json.dumps(rules, indent=2, ensure_ascii=False, default=str),
        encoding='utf-8',
    )
