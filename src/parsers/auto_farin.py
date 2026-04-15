"""Parser auto-generado para Farin Roses.

Layout (ejemplo):
    Code Box No. Type Box Total Stems Total Varieties/Length Unit Total
                                  Stems Bunch Bunch Price Price
    VERALEZA SL 1 HB 300 25 12 VINTAGE 50 CMS $0.30 $90.00
                      50 25  2 VINTAGE 60 CMS $0.35 $17.50   ← continuación misma caja

Fields por línea: code | box_no | box_type | box_stems | spb | bunches | variety
                  | length_cm | unit_price | total
"""
from __future__ import annotations

import re
from src.models import InvoiceHeader, InvoiceLine


# Línea principal: incluye Code y Box No. al inicio.
_LINE_FULL_RE = re.compile(
    r'^\s*(?P<code>VERALEZA\s*S?\.?L?\.?)\s+'
    r'(?P<box_no>\d+)\s+'
    r'(?P<box_type>HB|QB|TB|FB)\s+'
    r'(?P<box_stems>\d+)\s+'
    r'(?P<spb>\d+)\s+'
    r'(?P<bunches>\d+)\s+'
    r'(?P<variety>[A-Z][A-Z0-9\s\-/\']*?)\s+'
    r'(?P<length>\d+)\s*CMS?\s+'
    r'\$?\s*(?P<unit>[\d,]+\.\d+)\s+'
    r'\$?\s*(?P<total>[\d,]+\.\d+)\s*$',
    re.IGNORECASE,
)

# Línea de continuación: sin Code ni BoxNo (misma caja, otra variedad o talla).
_LINE_CONT_RE = re.compile(
    r'^\s*(?P<box_stems>\d+)\s+'
    r'(?P<spb>\d+)\s+'
    r'(?P<bunches>\d+)\s+'
    r'(?P<variety>[A-Z][A-Z0-9\s\-/\']*?)\s+'
    r'(?P<length>\d+)\s*CMS?\s+'
    r'\$?\s*(?P<unit>[\d,]+\.\d+)\s+'
    r'\$?\s*(?P<total>[\d,]+\.\d+)\s*$',
)

_INVOICE_RE = re.compile(r'Invoice\s*:?\s*(\S+)', re.I)
_DATE_RE    = re.compile(r'Date\s*:?\s*([\d\-/a-z]+)', re.I)
_AWB_RE     = re.compile(r'AWB\s*:?\s*([\d\-]+)', re.I)
_HAWB_RE    = re.compile(r'HAWB\s*:?\s*(\S+)', re.I)
_TOTAL_RE   = re.compile(r'Total\s+FOB\s+Value\s*:?\s*\$?\s*([\d,]+\.\d+)', re.I)


def _num(s: str) -> float:
    return float(s.replace(',', '')) if s else 0.0


class AutoParser:
    """Parser para facturas Farin Roses."""

    fmt_key = 'auto_farin'

    def parse(self, text: str, provider_data: dict) -> tuple[InvoiceHeader, list[InvoiceLine]]:
        header = InvoiceHeader(
            provider_id=provider_data.get('id', 0),
            provider_name=provider_data.get('name', ''),
            provider_key=provider_data.get('key', ''),
        )
        # Cabecera
        m = _INVOICE_RE.search(text)
        if m:
            header.invoice_number = m.group(1).strip()
        m = _DATE_RE.search(text)
        if m:
            header.date = m.group(1).strip()
        m = _AWB_RE.search(text)
        if m:
            header.awb = m.group(1).strip()
        m = _HAWB_RE.search(text)
        if m:
            header.hawb = m.group(1).strip()
        m = _TOTAL_RE.search(text)
        if m:
            header.total = _num(m.group(1))

        lines: list[InvoiceLine] = []
        in_body = False
        for raw in text.split('\n'):
            s = raw.strip()
            if not s:
                continue
            if 'Code' in s and 'Box' in s and 'Varieties' in s:
                in_body = True
                continue
            if s.startswith(('Full Boxes', 'Sub Total', 'Total FOB', 'Freight', 'Discount')):
                in_body = False
                continue
            if not in_body:
                continue
            # Salta sub-header "Stems Bunch Bunch Price Price"
            if s.upper().replace(' ', '') in ('STEMSBUNCHBUNCHPRICEPRICE',):
                continue

            m = _LINE_FULL_RE.match(s)
            box_type = ''
            if m:
                box_type = m.group('box_type').upper()
                line = InvoiceLine(
                    raw_description=s[:120],
                    species='ROSES',
                    variety=m.group('variety').strip().upper(),
                    origin='EC',   # Farin es Ecuador (VICENTE ESTRELLA / Quito)
                    size=int(m.group('length')),
                    stems_per_bunch=int(m.group('spb')),
                    bunches=int(m.group('bunches')),
                    stems=int(m.group('box_stems')),
                    price_per_stem=_num(m.group('unit')),
                    line_total=_num(m.group('total')),
                    box_type=box_type,
                    provider_key=provider_data.get('key', ''),
                )
                lines.append(line)
                continue

            m = _LINE_CONT_RE.match(s)
            if m:
                line = InvoiceLine(
                    raw_description=s[:120],
                    species='ROSES',
                    variety=m.group('variety').strip().upper(),
                    origin='EC',
                    size=int(m.group('length')),
                    stems_per_bunch=int(m.group('spb')),
                    bunches=int(m.group('bunches')),
                    stems=int(m.group('box_stems')),
                    price_per_stem=_num(m.group('unit')),
                    line_total=_num(m.group('total')),
                    box_type=box_type,
                    provider_key=provider_data.get('key', ''),
                )
                lines.append(line)

        return header, lines
