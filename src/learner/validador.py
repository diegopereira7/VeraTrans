"""Fase 4: Validación de reglas inferidas y cálculo de score de confianza."""
from __future__ import annotations

import re

from .modelos import PDFFingerprint, ExtractionRule
from .cluster import confianza_cluster


def validar_reglas(
    reglas: list[ExtractionRule],
    cluster_fps: list[PDFFingerprint],
) -> tuple[float, dict]:
    """Valida las reglas inferidas y calcula el score final.

    Returns:
        (score_final, detalles_dict) donde score_final es 0.0-1.0.
    """
    detalles = {}

    # CHECK 1: Completitud (25%)
    check1 = _check_completitud(reglas)
    detalles['completitud'] = check1

    # CHECK 2: Coherencia numérica (25%)
    check2 = _check_coherencia_numerica(reglas, cluster_fps)
    detalles['coherencia_numerica'] = check2

    # CHECK 3: Consistencia entre PDFs del cluster (25%)
    check3 = _check_consistencia(reglas, cluster_fps)
    detalles['consistencia_cluster'] = check3

    # CHECK 4: Confianza promedio de reglas (25%)
    check4 = _check_confianza_reglas(reglas)
    detalles['confianza_reglas'] = check4

    # Score base
    score_base = (check1 * 0.25 + check2 * 0.25 + check3 * 0.25 + check4 * 0.25)

    # Penalizar por tamaño del cluster
    conf_cluster = confianza_cluster(len(cluster_fps))
    detalles['confianza_cluster'] = conf_cluster

    # Penalizar por confianza de detección
    avg_deteccion = sum(fp.confianza_deteccion for fp in cluster_fps) / len(cluster_fps)
    detalles['confianza_deteccion'] = avg_deteccion

    score_final = score_base * conf_cluster * avg_deteccion
    detalles['score_base'] = round(score_base, 3)
    detalles['score_final'] = round(score_final, 3)

    return score_final, detalles


def _check_completitud(reglas: list[ExtractionRule]) -> float:
    """Check 1: ¿Se extraen los campos mínimos obligatorios?"""
    campos = {r.campo_destino for r in reglas}

    tiene_variety = 'variety' in campos
    tiene_stems = 'stems' in campos or 'bunches' in campos
    tiene_precio = 'price_per_stem' in campos or 'line_total' in campos
    tiene_header = any(c in campos for c in ('invoice_number', 'date'))
    tiene_species = 'species' in campos

    if not tiene_variety:
        return 0.0

    score = 0.3 if tiene_variety else 0.0
    score += 0.25 if tiene_stems else 0.0
    score += 0.25 if tiene_precio else 0.0
    score += 0.10 if tiene_header else 0.0
    score += 0.10 if tiene_species else 0.0

    return min(score, 1.0)


def _check_coherencia_numerica(
    reglas: list[ExtractionRule],
    cluster_fps: list[PDFFingerprint],
) -> float:
    """Check 2: ¿Los datos numéricos extraídos tienen sentido?"""
    scores = []

    for rule in reglas:
        if rule.campo_destino in ('stems', 'bunches', 'stems_per_bunch', 'price_per_stem', 'line_total'):
            if rule.evidencia:
                valid_count = 0
                for ev in rule.evidencia:
                    try:
                        val = float(ev.replace(',', '').replace('$', ''))
                        if _is_plausible(rule.campo_destino, val):
                            valid_count += 1
                    except (ValueError, AttributeError):
                        pass
                if rule.evidencia:
                    scores.append(valid_count / len(rule.evidencia))

    return sum(scores) / len(scores) if scores else 0.5


def _is_plausible(campo: str, val: float) -> bool:
    """Verifica si un valor numérico es plausible para su campo."""
    ranges = {
        'stems': (1, 50000),
        'bunches': (1, 5000),
        'stems_per_bunch': (1, 100),
        'price_per_stem': (0.01, 50.0),
        'line_total': (0.01, 100000.0),
        'size': (10, 200),
    }
    lo, hi = ranges.get(campo, (0, 999999))
    return lo <= val <= hi


def _check_consistencia(
    reglas: list[ExtractionRule],
    cluster_fps: list[PDFFingerprint],
) -> float:
    """Check 3: ¿Las reglas funcionan consistentemente en todos los PDFs?"""
    if len(cluster_fps) < 2:
        return 0.5

    # Verificar que el regex de línea matchea en todos los PDFs
    line_regex_rule = None
    for rule in reglas:
        if rule.campo_destino == 'line_pattern' and rule.patron_regex:
            line_regex_rule = rule
            break

    if line_regex_rule:
        pat = re.compile(line_regex_rule.patron_regex, re.IGNORECASE)
        pdfs_con_match = 0
        for fp in cluster_fps:
            if any(pat.search(l) for l in fp.lineas_datos):
                pdfs_con_match += 1
        return pdfs_con_match / len(cluster_fps)

    # Sin regex de línea, verificar consistencia de campos numéricos
    fields_per_pdf = []
    for fp in cluster_fps:
        fields_per_pdf.append(len(fp.lineas_datos))

    if not fields_per_pdf:
        return 0.3

    # Si todos tienen líneas de datos, es buena señal
    non_empty = sum(1 for n in fields_per_pdf if n > 0)
    return non_empty / len(fields_per_pdf) if fields_per_pdf else 0.3


def _check_confianza_reglas(reglas: list[ExtractionRule]) -> float:
    """Check 4: Promedio ponderado de confianza de las reglas."""
    if not reglas:
        return 0.0

    # Ponderar más los campos críticos
    weights = {
        'variety': 3.0,
        'stems': 2.0,
        'price_per_stem': 2.0,
        'line_total': 2.0,
        'line_pattern': 2.5,
        'invoice_number': 1.0,
        'date': 1.0,
        'species': 1.5,
    }

    total_weight = 0
    weighted_sum = 0

    for rule in reglas:
        w = weights.get(rule.campo_destino, 1.0)
        total_weight += w
        weighted_sum += rule.confianza * w

    return weighted_sum / total_weight if total_weight else 0.0
