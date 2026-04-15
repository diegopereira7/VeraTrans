"""Parser auto-generado para AGROSANALFONSO + GLAMOUR (mismo template 'I'-separado).

GLAMOUR es marca comercial de AGROSANALFONSO S.A. — comparten layout exacto:

    TOTAL | PIECES | TOTAL | ST | CODE | DESCRIPTION | UNIT | VOLUMEN | REAL | TOTAL
    PIECES  TYPE    UNITS    BN                        PRICE  WEIGHT    WEIGHT USD
    1 I AHBN I 50I ST I R11-BCPI I EXPLORER 50 CM 25 I $0.300000I 13.00I 10.56 I $15.00
    I AHBN I 75I ST I R11-BCPI I MONDIAL. 50 CM 25 I $0.300000I I I $22.50     ← continuación
"""
from __future__ import annotations

import re
from src.models import InvoiceHeader, InvoiceLine


# Split por "I" pero con espacios opcionales. Celdas vacías permitidas.
# Formato de celda description: "<VARIETY> <SIZE> CM <SPB>"
_DESC_RE = re.compile(
    r'^(?P<variety>[A-Z][A-Z0-9\s\-\'/\.]+?)\s+'
    r'(?P<size>\d{2,3})\s*CM\s+'
    r'(?P<spb>\d+)\s*$',
    re.IGNORECASE,
)

_INVOICE_RE = re.compile(r'COMERCIALINVOICE\s+(\d+)', re.I)
_DATE_RE    = re.compile(r'DATE:\s*(\d{1,2}/\d{1,2}/\d{4})', re.I)
_AWB_RE     = re.compile(r'MAWB#?:\s*([\d\s]+?)HAWB', re.I)
_HAWB_RE    = re.compile(r'HAWB#?:\s*(\S+)', re.I)


def _num_usd(s: str) -> float:
    """Acepta '$0.300000' o '$58.00' o '$0,30'."""
    s = s.strip().replace('$', '').replace(' ', '')
    if not s:
        return 0.0
    if ',' in s and '.' not in s:
        return float(s.replace(',', '.'))
    return float(s)


class AutoParser:
    fmt_key = 'auto_agrosanalfonso'

    def parse(self, text: str, provider_data: dict) -> tuple[InvoiceHeader, list[InvoiceLine]]:
        header = InvoiceHeader(
            provider_id=provider_data.get('id', 0),
            provider_name=provider_data.get('name', ''),
            provider_key=provider_data.get('key', ''),
        )
        m = _INVOICE_RE.search(text)
        if m:
            header.invoice_number = m.group(1)
        m = _DATE_RE.search(text)
        if m:
            header.date = m.group(1)
        m = _AWB_RE.search(text)
        if m:
            header.awb = re.sub(r'\s+', '', m.group(1))
        m = _HAWB_RE.search(text)
        if m:
            header.hawb = m.group(1)

        lines: list[InvoiceLine] = []
        for raw in text.split('\n'):
            s = raw.strip()
            if not s or 'I' not in s:
                continue
            if 'TOTAL' in s[:10].upper() or 'PIECES' in s[:10].upper():
                continue
            # Split por 'I' pero sin romper tokens con I interna (BCPI, HBSJM).
            # Regla: la 'I' es separador si NO está precedida por letra mayúscula.
            # Cubre '75I ST', '$0.300000I 13.00' (I tras dígito o $) y
            # ' I ' (espacios a ambos lados) a la vez.
            stripped = re.sub(r'^I\s+|\s+I$', '', s)
            cells = [c.strip() for c in re.split(r'(?<![A-Z])I\s+', stripped)]
            # Estructura esperada ≥8 celdas tras split:
            # [box_num | type_code | stems | 'ST' | farm_code | description | price | volumen | weight | total]
            if len(cells) < 8:
                continue
            # Buscar la celda description (contiene "<VAR> <SIZE> CM <SPB>")
            desc_idx = None
            for i, c in enumerate(cells):
                if re.search(r'\d+\s*CM\s+\d+', c, re.I):
                    desc_idx = i
                    break
            if desc_idx is None:
                continue
            m = _DESC_RE.match(cells[desc_idx])
            if not m:
                continue
            # Celdas a la izquierda del description:
            # cells[desc_idx - 1] = farm_code (R11-BCPI)
            # cells[desc_idx - 2] = 'ST' o similar (unit type)
            # cells[desc_idx - 3] = stems
            # cells[desc_idx - 4] = type_code (AHBN / AQBN)
            # cells[desc_idx - 5] = box_num (vacío en continuación)
            try:
                stems_cell = cells[desc_idx - 3]
                stems = int(re.sub(r'\D+', '', stems_cell)) if stems_cell else 0
                type_code = cells[desc_idx - 4]
                farm_code = cells[desc_idx - 1]
            except (IndexError, ValueError):
                continue
            # Derivar box_type de type_code: AHBN → HB, AQBN → QB, etc.
            box_type = 'HB'
            if 'QB' in type_code.upper():
                box_type = 'QB'
            elif 'TB' in type_code.upper():
                box_type = 'TB'
            elif 'FB' in type_code.upper():
                box_type = 'FB'
            # Cell to the right of description: price; last cell: total
            try:
                price_cell = cells[desc_idx + 1]
                price = _num_usd(price_cell)
            except (IndexError, ValueError):
                price = 0.0
            # Total: última celda no vacía que empiece con $
            total = 0.0
            for c in reversed(cells):
                if c.startswith('$'):
                    total = _num_usd(c)
                    break
            variety = m.group('variety').strip().upper().rstrip('.').strip()
            spb = int(m.group('spb'))
            size = int(m.group('size'))
            bunches = stems // spb if spb else 0

            lines.append(InvoiceLine(
                raw_description=s[:120],
                species='ROSES',
                variety=variety,
                origin='EC',
                size=size,
                stems_per_bunch=spb,
                bunches=bunches,
                stems=stems,
                price_per_stem=price,
                line_total=total,
                box_type=box_type,
                label=farm_code,
                provider_key=provider_data.get('key', ''),
            ))

        if not header.total and lines:
            header.total = round(sum(l.line_total for l in lines), 2)
        return header, lines
