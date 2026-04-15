"""Validaciones cruzadas post-parseo.

Estas validaciones no "arreglan" nada por sí solas: anotan errores en
`InvoiceLine.validation_errors` y en un reporte a nivel factura. El objetivo
es detectar las "cascading failures" que el artículo de anyformat.ai describe
como el principal riesgo de extracción mal validada — una factura que cuadra
línea a línea puede estar completamente rota si el total no casa o si los
stems declarados no son coherentes con bunches*stems_per_bunch.

Reglas actuales:
    R1. stems == bunches * stems_per_bunch   (si ambos > 0)
    R2. line_total ≈ stems * price_per_stem  (tolerancia 2%)
    R3. sum(line_total) ≈ header.total       (tolerancia 1%, solo si header.total > 0)
    R4. line_total > 0 si la línea tiene match ok
"""
from __future__ import annotations

from typing import Iterable

from src.models import InvoiceHeader, InvoiceLine


# Tolerancias (en fracción: 0.02 = 2%)
_TOL_LINE = 0.02
_TOL_HEADER = 0.01


def _rel_diff(a: float, b: float) -> float:
    if b == 0:
        return abs(a)
    return abs(a - b) / abs(b)


def validate_line(line: InvoiceLine) -> list[str]:
    """Valida una línea individual. Devuelve lista de códigos de error."""
    errs: list[str] = []

    # R1: coherencia stems / bunches / stems_per_bunch
    if line.stems > 0 and line.bunches > 0 and line.stems_per_bunch > 0:
        expected = line.bunches * line.stems_per_bunch
        if expected != line.stems:
            errs.append(f'stems_mismatch (esperado {expected}, recibido {line.stems})')

    # R2: line_total coherente con stems * price_per_stem
    if line.stems > 0 and line.price_per_stem > 0 and line.line_total > 0:
        expected = line.stems * line.price_per_stem
        if _rel_diff(line.line_total, expected) > _TOL_LINE:
            errs.append(f'total_mismatch (esperado {expected:.2f}, recibido {line.line_total:.2f})')

    # R4: línea ok debería tener line_total > 0
    if line.match_status == 'ok' and line.line_total <= 0:
        errs.append('line_total_zero_en_match_ok')

    return errs


def validate_invoice(header: InvoiceHeader,
                     lines: Iterable[InvoiceLine]) -> dict:
    """Valida la factura completa y anota errores en cada línea.

    Muta las líneas añadiendo `validation_errors`; devuelve un resumen
    con los contadores y las diferencias globales (útil para el frontend).
    """
    lines = list(lines)
    per_line_err_count = 0

    for l in lines:
        errs = validate_line(l)
        if errs:
            l.validation_errors = errs
            per_line_err_count += 1
            # Una línea con errores de validación no puede ser de confianza
            # alta, da igual cómo haya matcheado.
            l.match_confidence = min(l.match_confidence, 0.70)

    # R3: sum(line_total) ≈ header.total
    sum_lines = round(sum(l.line_total for l in lines), 2)
    header_diff = None
    header_ok = True
    if header.total and header.total > 0:
        diff = _rel_diff(sum_lines, header.total)
        header_diff = round(sum_lines - header.total, 2)
        if diff > _TOL_HEADER:
            header_ok = False

    return {
        'sum_lines': sum_lines,
        'header_total': header.total,
        'header_diff': header_diff,
        'header_ok': header_ok,
        'lines_with_errors': per_line_err_count,
        'total_lines': len(lines),
    }
