"""Parser auto-generado para ROSABELLA (TERESA VERDEZOTO, Guayllabamba).

Layout sencillo — una línea por caja:
    TYPE PIECES EQ.FB VARIETY HTS S/B BUNCH_COL TOT_BUNCH STEMS PRICE TOTAL
    HB 2 1 ABC 0603.11.00.60 25 24 24 600 0,22 132,00
    HB 1 0,5 EXPLORER 0603.11.00.60 25 14 14 350 0,32 112,00

Decimal con coma. ABC suele ser código 'ASSORTED'.
"""
from __future__ import annotations

import re
from src.models import InvoiceHeader, InvoiceLine


_LINE_RE = re.compile(
    r'^(?P<box_type>HB|QB|TB|FB)\s+'
    r'(?P<pieces>\d+)\s+'
    r'(?P<fulls>[\d.,]+)\s+'
    r'(?P<variety>[A-Z][A-Z0-9\s\-\'/]+?)\s+'
    r'(?P<hts>\d{4}\.\d{2}\.\d{2}\.\d{2})\s+'
    r'(?P<spb>\d+)\s+'
    r'(?P<bunch_col>\d+)\s+'
    r'(?P<total_bunch>\d+)\s+'
    r'(?P<stems>\d+)\s+'
    r'(?P<price>\d+[,.]\d+)\s+'
    r'(?P<total>[\d.,]+)\s*$',
    re.IGNORECASE,
)

_INVOICE_RE = re.compile(r'INVOICE\s+No\.\s*(\S+)', re.I)
_DATE_RE    = re.compile(r'Date:\s*\n?\s*(\d{1,2}/\d{1,2}/\d{4})', re.I)
_AWB_RE     = re.compile(r'MAWB\s+No\.?\s*\n?\s*([\d\s]+)', re.I)
_HAWB_RE    = re.compile(r'HAWB\s+No\.?\s*\n?\s*(\S+)', re.I)


def _num(s: str) -> float:
    return float(s.replace('.', '').replace(',', '.')) if ',' in s else float(s)


class AutoParser:
    fmt_key = 'auto_rosabella'

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
            if not s or len(s) < 25:
                continue
            m = _LINE_RE.match(s)
            if not m:
                continue
            variety = m.group('variety').strip().upper()
            # "ABC" → ASSORTED (abreviatura común en ROSABELLA)
            if variety == 'ABC':
                variety = 'ASSORTED'
            spb = int(m.group('spb'))
            stems = int(m.group('stems'))
            total_bunch = int(m.group('total_bunch'))
            lines.append(InvoiceLine(
                raw_description=s[:120],
                species='ROSES',
                variety=variety,
                origin='EC',
                size=0,       # ROSABELLA no expone CM en texto plano
                stems_per_bunch=spb,
                bunches=total_bunch,
                stems=stems,
                price_per_stem=_num(m.group('price')),
                line_total=_num(m.group('total')),
                box_type=m.group('box_type').upper(),
                provider_key=provider_data.get('key', ''),
            ))

        if not header.total and lines:
            header.total = round(sum(l.line_total for l in lines), 2)
        return header, lines
