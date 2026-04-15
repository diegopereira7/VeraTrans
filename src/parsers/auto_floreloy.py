"""Parser auto-generado para FLORELOY.

Layout (cabecera de caja y datos en líneas separadas):
    GIJON 1 HB-CAR                                          ← parent (code, box#, type)
    250 25 10 EXPLORER 70 CMS $0.400 $100.00                ← datos
    GIJON 2 HB-CAR
    250 25 10 EXPLORER 70 CMS $0.400 $100.00

Data line: stems spb bunches variety length CMS $price $total
"""
from __future__ import annotations

import re
from src.models import InvoiceHeader, InvoiceLine


_BOX_HEADER_RE = re.compile(
    r'^(?P<code>[A-Z]+)\s+(?P<box_num>\d+)\s+(?P<box_type>HB|QB|TB|FB)(?:-[A-Z]+)?\s*$'
)

_LINE_DATA_RE = re.compile(
    r'^(?P<stems>\d+)\s+'
    r'(?P<spb>\d+)\s+'
    r'(?P<bunches>\d+)\s+'
    r'(?P<variety>[A-Z][A-Z0-9\s\-\'/]+?)\s+'
    r'(?P<length>\d+)\s*CMS?\s+'
    r'\$?\s*(?P<price>[\d,]+\.\d+)\s+'
    r'\$?\s*(?P<total>[\d,]+\.\d+)\s*$',
    re.IGNORECASE,
)

_INVOICE_RE = re.compile(r'INVOICE:\s*(\S+)', re.I)
_DATE_RE    = re.compile(r'DATE:\s*([\d\-a-z]+)', re.I)
_AWB_RE     = re.compile(r'AWB:\s*(\S+)', re.I)
_HAWB_RE    = re.compile(r'HAWB:\s*(\S+)', re.I)
_TOTAL_RE   = re.compile(r'TOTAL\s+FOB\s+VALUE[^\$]*\$?\s*([\d,]+\.\d+)', re.I)


def _num(s: str) -> float:
    return float(s.replace(',', '')) if s else 0.0


class AutoParser:
    fmt_key = 'auto_floreloy'

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
            header.awb = m.group(1)
        m = _HAWB_RE.search(text)
        if m:
            header.hawb = m.group(1)
        m = _TOTAL_RE.search(text)
        if m:
            header.total = _num(m.group(1))

        lines: list[InvoiceLine] = []
        current_box_type = ''
        current_code = ''
        for raw in text.split('\n'):
            s = raw.strip()
            if not s:
                continue
            mh = _BOX_HEADER_RE.match(s)
            if mh:
                current_box_type = mh.group('box_type').upper()
                current_code = mh.group('code')
                continue
            md = _LINE_DATA_RE.match(s)
            if not md:
                continue
            lines.append(InvoiceLine(
                raw_description=s[:120],
                species='ROSES',     # mayoría; refinable por sufijo box_type (CAR=carnation)
                variety=md.group('variety').strip().upper(),
                origin='EC',
                size=int(md.group('length')),
                stems_per_bunch=int(md.group('spb')),
                bunches=int(md.group('bunches')),
                stems=int(md.group('stems')),
                price_per_stem=_num(md.group('price')),
                line_total=_num(md.group('total')),
                box_type=current_box_type or 'HB',
                label=current_code,
                provider_key=provider_data.get('key', ''),
            ))

        if not header.total and lines:
            header.total = round(sum(l.line_total for l in lines), 2)
        return header, lines
