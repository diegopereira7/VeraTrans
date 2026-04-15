"""Parser auto-generado para SAN JORGE ROSES.

Layout:
    No. BOX CODE VARIETY LONG STEMS BUNCH TOTAL TOTAL PRICE TOTAL
                          BOX   BUNCH STEMS PRICE
                          BOX   TYPE  BOX
    1 HB ROSAS CHERRY OH 50 25 12 12 300 0,3500 T 105,00      ← parent con box_num/type
    1 QB ROSAS PINK FLOYD 50 25 1 1 25 0,3500 T 8,75
    ROSAS PINK FLOYD 60 25 3 3 75 0,4000 T 30,00              ← continuación

Campos (tras box_num/type opcional): code=ROSAS, variety, size, spb,
bunch/box, total_bunch, stems, price, marcador T, total.
Decimal con coma.
"""
from __future__ import annotations

import re
from src.models import InvoiceHeader, InvoiceLine


_LINE_RE = re.compile(
    r'^(?:(?P<box_num>\d+)\s+(?P<box_type>HB|QB|TB|FB)\s+)?'
    r'(?P<species>ROSAS?|CARNATION|CLAVELES?)\s+'
    r'(?P<variety>[A-Z][A-Z0-9\s\-\'/]+?)\s+'
    r'(?P<size>\d{2,3})\s+'
    r'(?P<spb>\d+)\s+'
    r'(?P<bunch_box>\d+)\s+'
    r'(?P<total_bunch>\d+)\s+'
    r'(?P<stems>\d+)\s+'
    r'(?P<price>\d+[.,]\d+)\s+'
    r'[A-Z]\s+'                              # marcador 'T'
    r'(?P<total>[\d.,]+)\s*$',
    re.IGNORECASE,
)

_INVOICE_RE = re.compile(r'INVOICE\s+No\s*:\s*(\S+)', re.I)
_DATE_RE    = re.compile(r'DATE:\s*(\d{1,2}/\d{1,2}/\d{2,4})', re.I)
_AWB_RE     = re.compile(r'AWB\s*#?:\s*([\d\s\-]+)HAWB', re.I)
_HAWB_RE    = re.compile(r'HAWB\s*#?:\s*(\S+)', re.I)
_SPECIES_MAP = {
    'ROSA': 'ROSES', 'ROSAS': 'ROSES',
    'CARNATION': 'CARNATIONS', 'CLAVEL': 'CARNATIONS', 'CLAVELES': 'CARNATIONS',
}


def _num(s: str) -> float:
    return float(s.replace('.', '').replace(',', '.')) if s else 0.0


class AutoParser:
    fmt_key = 'auto_sanjorge'

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
        last_box_type = ''
        for raw in text.split('\n'):
            s = raw.strip()
            if not s or len(s) < 15:
                continue
            m = _LINE_RE.match(s)
            if not m:
                continue
            if m.group('box_type'):
                last_box_type = m.group('box_type').upper()
            species = _SPECIES_MAP.get(m.group('species').upper(), 'ROSES')
            lines.append(InvoiceLine(
                raw_description=s[:120],
                species=species,
                variety=m.group('variety').strip().upper(),
                origin='EC',
                size=int(m.group('size')),
                stems_per_bunch=int(m.group('spb')),
                bunches=int(m.group('total_bunch')),
                stems=int(m.group('stems')),
                price_per_stem=_num(m.group('price')),
                line_total=_num(m.group('total')),
                box_type=last_box_type or 'HB',
                provider_key=provider_data.get('key', ''),
            ))

        if not header.total and lines:
            header.total = round(sum(l.line_total for l in lines), 2)
        return header, lines
