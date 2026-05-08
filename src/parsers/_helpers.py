"""Helpers compartidos entre parsers (sesión 12q).

Centraliza la extracción del total impreso para los parsers `auto_*`
que actualmente derivan `h.total = sum(lines)` ciegamente. Sin total
impreso, la UI no puede alertar al operador de que faltan líneas — el
gap queda invisible. Estos parsers no tienen samples activos en el
batch del operador, así que el patrón es preventivo: probamos varios
regex comunes y el primero que matchee se asume correcto. Si ninguno
matchea, el parser sigue cayendo al sum como antes (comportamiento
heredado).
"""
from __future__ import annotations

import re


def _parse_amount(raw: str) -> float:
    """Normaliza un número con `$`, espacios, puntos/comas a float.

    Reglas:
      - Si tiene punto y coma juntos, el último separador es el decimal.
      - Si solo tiene coma con 3 dígitos después → miles (US).
      - Si solo tiene coma con 2 dígitos después → decimal (EU).
    """
    s = raw.strip().replace('$', '').replace(' ', '')
    if not s:
        return 0.0
    if ',' in s and '.' in s:
        if s.rfind('.') > s.rfind(','):
            return float(s.replace(',', ''))
        return float(s.replace('.', '').replace(',', '.'))
    if ',' in s:
        last = s.split(',')[-1]
        if len(last) == 3 and last.isdigit():
            return float(s.replace(',', ''))
        return float(s.replace(',', '.'))
    try:
        return float(s)
    except ValueError:
        return 0.0


# Patrones probados en orden — el primero que matchea gana. Más
# específicos (con keyword + $) van antes que los genéricos.
_TOTAL_PATTERNS = [
    # FOB / FCA
    r'TOTAL\s+FOB\s+\d+\s+[\d.,]+\s+([\d.,]+)',
    r'Vlr\.?\s*Total\s+FCA[^:]*:\s*([\d.,]+)',
    # Aposentos / multi-flora
    r'Total\s+Value\s*\$?\s*([\d.,]+)',
    r'TOTAL\s+DUE\s+USD?\s*\$?\s*([\d.,]+)',
    # Mystic / Fiorentina
    r'Total\s+Invoice\s+USD?\s*\$?\s*([\d.,]+)',
    # Malima / UMA
    r'Amount\s+Due\s*[:\s]*\$\s*([\d.,]+)',
    # Colibri / ColFarm
    r'INVOICE\s+TOTAL\s*\(?[^)]*\)?\s*([\d.,]+)',
    # Prestige
    r'TOTAL\s+A\s+PAGAR\s*\$?\s*([\d.,]+)',
    # Tessa
    r'Invoice\s+Amount\s*\$?\s*([\d.,]+)',
    # Rosely
    r'TOTALS?\s+\d+\s+\$\s*USD?\s+([\d.,]+)',
    # EQR / Brissas
    r'(?:Inv\.?\s+Subtotal|Sub\s*Total)\s*\$?\s*([\d.,]+)',
    # Domenica
    r'GRAND\s+TOTAL\s*[:\s]*\$?\s*([\d.,]+)',
    # Genérico USD al final
    r'Total\s+USD?\s*\$?\s*([\d.,]+)',
]
_TOTAL_REGEXES = [re.compile(p, re.I) for p in _TOTAL_PATTERNS]


def extract_printed_total(text: str) -> float:
    """Devuelve el total impreso en la factura, o `0.0` si no se encuentra.

    Aplica una jerarquía de patrones comunes en facturas de flores. Si
    múltiples matches existen, gana el primer patrón en `_TOTAL_PATTERNS`
    (más específico). Tolera varios formatos numéricos (US/EU).
    """
    for rx in _TOTAL_REGEXES:
        m = rx.search(text)
        if m:
            try:
                v = _parse_amount(m.group(1))
                if v > 0:
                    return v
            except (ValueError, IndexError):
                continue
    return 0.0
