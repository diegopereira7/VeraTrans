"""Parser auto-generado para NATIVE BLOOMS (CALINAMA CAPITAL).

Layout ROSES (mayoría de facturas):
    BOX Farm Box Variety Qty Lengt Stems Price/ TOTAL Label
    1 RDC HB COUNTRY HOME 12 50 300 $0,270 $81,000
    9 RDC HB TOPAZ 8 60 200 $0,250 $50,000
    VENDELA 4 60 100 $0,250 $25,000               ← continuación de mixed box

Layout TROPICAL (raro, sample boxes):
    Heliconia Heliconia sp 0603199090 Flower 13 13 $0,0001 $0,00

Prioriza roses; para tropical extrae lo que pueda.
"""
from __future__ import annotations

import re
from src.models import InvoiceHeader, InvoiceLine


# Línea parent: <box_num> <farm_code> <type> <variety...> <qty> <size> <stems> $<price> $<total>
_LINE_PARENT_RE = re.compile(
    r'^(?P<box_num>\d+)\s+'
    r'(?P<farm>[A-Z]{2,5})\s+'
    r'(?P<box_type>HB|QB|TB|FB)\s+'
    r'(?P<variety>[A-Z][A-Z0-9\s\-\'/]+?)\s+'
    r'(?P<qty>\d+)\s+'
    r'(?P<size>\d{2,3})\s+'
    r'(?P<stems>\d+)\s+'
    r'\$(?P<price>[\d,.]+)\s+'
    r'\$(?P<total>[\d,.]+)\s*$'
)

# Continuación sin prefix: <variety> <qty> <size> <stems> $<price> $<total>
_LINE_CONT_RE = re.compile(
    r'^(?P<variety>[A-Z][A-Z0-9\s\-\'/]+?)\s+'
    r'(?P<qty>\d+)\s+'
    r'(?P<size>\d{2,3})\s+'
    r'(?P<stems>\d+)\s+'
    r'\$(?P<price>[\d,.]+)\s+'
    r'\$(?P<total>[\d,.]+)\s*$'
)

# Layout tropical (sample boxes de NATIVEFARM S.A.):
#   Heliconia Heliconia sp 0603199090 Flower 13 13 $0,0001 $0,00
#   Areca palm Chrysalidocarpus lutescens 0604200000 Foliage 10 10 $0,0001 $0,00
_LINE_TROPICAL_RE = re.compile(
    r'^(?P<variety>[A-Z][a-zA-Z][\w\s]*?)\s+'
    r'(?P<sci>[A-Z][a-z]+(?:\s+[a-z\.]+)*)\s+'
    r'(?P<hts>06\d{8})\s+'
    r'(?P<ptype>Flower|Foliage)\s+'
    r'(?P<bunches>\d+)\s+'
    r'(?P<stems>\d+)\s+'
    r'\$(?P<price>[\d,.]+)\s+'
    r'\$(?P<total>[\d,.]+)\s*$'
)

_INVOICE_RE = re.compile(r'CUSTOMER\s+INVOICE\s+(\d+)', re.I)
_DATE_RE    = re.compile(r'Date\s*:\s*(\d{1,2}/\d{1,2}/\d{4})', re.I)
_AWB_RE     = re.compile(r'A\.W\.B\.\s*N[°º]?\s*:\s*(\S+)', re.I)
_HAWB_RE    = re.compile(r'H\.A\.W\.B\.\s*(\S+)', re.I)


def _num(s: str) -> float:
    """Convierte '0,270' o '81,000' o '1610,000' a float.

    NATIVE usa coma como separador en ambos (decimal y miles). Un truco:
    si el número tiene >=3 dígitos tras la última coma, tratarla como miles;
    si tiene 1-2 dígitos tras la última coma o 3 con valor <1, tratarla como decimal.
    Normalizamos: si solo hay UNA coma y <=3 dígitos después → decimal.
    """
    s = s.strip().replace('$', '')
    if not s:
        return 0.0
    # Una sola coma → decimal
    if s.count(',') == 1 and s.count('.') == 0:
        return float(s.replace(',', '.'))
    # Punto + coma → ya es formato 1.234,56 (europeo)
    if '.' in s and ',' in s:
        return float(s.replace('.', '').replace(',', '.'))
    return float(s.replace(',', ''))


class AutoParser:
    fmt_key = 'auto_native'

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

        lines: list[InvoiceLine] = []
        last_box_type = 'HB'
        last_farm = ''
        for raw in text.split('\n'):
            s = raw.strip()
            if not s or len(s) < 15:
                continue
            if s.upper().startswith(('TOTAL', 'BOX FARM', 'SUBTOTAL', 'NOTICE', 'PAYMENT',
                                     'CUSTOMER', 'PLEASE', 'INVOICE', 'DATE:', 'SHIPPER')):
                continue

            m = _LINE_PARENT_RE.match(s)
            if m:
                last_box_type = m.group('box_type')
                last_farm = m.group('farm')
                lines.append(self._build_line(s, m, last_box_type, last_farm, provider_data))
                continue

            m = _LINE_CONT_RE.match(s)
            if m:
                variety = m.group('variety').strip().upper()
                if variety in ('TOTAL', 'SUBTOTAL', 'CUSTOMER', 'INVOICE', 'INCOTERM'):
                    continue
                if len(variety) < 2 or len(variety) > 40:
                    continue
                lines.append(self._build_line(s, m, last_box_type, last_farm, provider_data))
                continue

            # Tropical / foliage (sample boxes)
            m = _LINE_TROPICAL_RE.match(s)
            if m:
                variety = m.group('variety').strip().upper()
                if len(variety) < 2 or variety in ('TOTAL', 'PROOF', 'COUNTRY'):
                    continue
                bunches = int(m.group('bunches'))
                stems = int(m.group('stems'))
                lines.append(InvoiceLine(
                    raw_description=s[:120],
                    species='OTHER',
                    variety=variety,
                    origin='EC',
                    size=0,
                    stems_per_bunch=stems // bunches if bunches else 1,
                    bunches=bunches,
                    stems=stems,
                    price_per_stem=_num(m.group('price')),
                    line_total=_num(m.group('total')),
                    box_type='QB',
                    provider_key=provider_data.get('key', ''),
                ))

        if not header.total and lines:
            header.total = round(sum(l.line_total for l in lines), 2)
        return header, lines

    def _build_line(self, raw, m, box_type, farm, provider_data) -> InvoiceLine:
        variety = m.group('variety').strip().upper()
        qty = int(m.group('qty'))
        size = int(m.group('size'))
        stems = int(m.group('stems'))
        # spb derivado: stems / bunches
        spb = stems // qty if qty > 0 else 25
        return InvoiceLine(
            raw_description=raw[:120],
            species='ROSES',
            variety=variety,
            origin='EC',
            size=size,
            stems_per_bunch=spb,
            bunches=qty,
            stems=stems,
            price_per_stem=_num(m.group('price')),
            line_total=_num(m.group('total')),
            box_type=box_type or 'HB',
            label=farm,
            provider_key=provider_data.get('key', ''),
        )
