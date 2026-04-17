"""Parser auto-generado para EL MILAGRO DE LAS FLORES.

Layout con parent summary + sub-líneas por variedad (siempre se emiten
las sub-líneas, que traen el detalle real):

    1 H ROSES BARISTA X 25 - 40 (Mixto) 000001 10 10 250 250 0.550 137.50   ← parent
    ROSES BARISTA X 25 - 40 Milagro 6 150 0.600                             ← sub
    ROSES BARISTA X 25 - 50 Milagro 1 25 0.700
    ROSES CAFE DEL MAR X 25 - 40 Milagro 3 75 0.400
    2 H ROSES FREEDOM X 25 - 40 000002 12 24 300 600 0.220 132.00
    ROSES FREEDOM X 25 - 40 Milagro 12 300 0.220

Sub-line: species variety X spb - size Milagro bunches stems price
"""
from __future__ import annotations

import re
from src.models import InvoiceHeader, InvoiceLine


# Sub-línea: ROSES <variety> X <spb> - <size> Milagro <bunches> <stems> <price>
_SUBLINE_RE = re.compile(
    r'^(?P<species>ROSES|CARNATION|HYDRANGEAS?|ALSTROEMERIA)\s+'
    r'(?P<variety>[A-Z][A-Z0-9\s\-\'/]+?)\s+'
    r'X\s+(?P<spb>\d+)\s*-\s*'
    r'(?P<size>\d{2,3})\s+'
    r'(?P<farm>Milagro|MILAGRO)\s*(?:[A-Z\s]+)?\s*'
    r'(?P<bunches>\d+)\s+'
    r'(?P<stems>\d+)\s+'
    r'(?P<price>\d+[.,]\d+)\s*$',
    re.IGNORECASE,
)

# Parent con box_num: `1 H ROSES FREEDOM X 25 - 40 000002 12 24 300 600 0.220 132.00`
# La usamos para detectar boxes NO mixtos (sin sub-línea equivalente).
_PARENT_RE = re.compile(
    r'^(?P<box_num>\d+)\s+'
    r'(?P<box_type>[HFQT])\s+'
    r'(?P<species>ROSES|CARNATION|HYDRANGEAS?|ALSTROEMERIA)\s+'
    r'(?P<variety>[A-Z][A-Z0-9\s\-\'/]+?)\s+'
    r'X\s+(?P<spb>\d+)\s*-\s*'
    r'(?P<size>\d{2,3})\s+'
    r'(?P<mixto>\(Mixto\)\s+)?'
    r'(?P<box_id>\d+)\s+'
    r'(?P<bunches_box>\d+)\s+'
    r'(?P<total_bunch>\d+)\s+'
    r'(?P<stems_box>\d+)\s+'
    r'(?P<total_stems>\d+)\s+'
    r'(?P<price>\d+[.,]\d+)\s+'
    r'(?P<total>[\d.,]+)\s*$',
    re.IGNORECASE,
)

_INVOICE_RE = re.compile(r'INVOICE\s+No\.\s*(\S+)', re.I)
_DATE_RE    = re.compile(r'Date\s+Invoice:\s*(\d{4}-\d{2}-\d{2})', re.I)
_AWB_RE     = re.compile(r'AWB:\s*(\S+)', re.I)
_HAWB_RE    = re.compile(r'HAWB:\s*(\S+)', re.I)
_TOTAL_RE   = re.compile(r'TOTAL\s+INVOICE\s+\(Dollars\)\s+([\d,.]+)', re.I)
_SPECIES_MAP = {
    'ROSES': 'ROSES', 'ROSE': 'ROSES',
    'CARNATION': 'CARNATIONS', 'CARNATIONS': 'CARNATIONS',
    'HYDRANGEAS': 'HYDRANGEAS', 'HYDRANGEA': 'HYDRANGEAS',
    'ALSTROEMERIA': 'ALSTROEMERIA',
}


def _num(s: str) -> float:
    return float(s.replace(',', '')) if s else 0.0


class AutoParser:
    fmt_key = 'auto_milagro'

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

        # Primero identificar parents (mixto / simple) para saber qué sub-líneas
        # pertenecen a boxes mixtos y cuáles son "únicas".
        parents = []
        for raw in text.split('\n'):
            mp = _PARENT_RE.match(raw.strip())
            if mp:
                parents.append({
                    'box_type': mp.group('box_type'),
                    'is_mixto': bool(mp.group('mixto')),
                })

        # Emitir SIEMPRE las sub-líneas: traen variedad + precio reales por split.
        # La parent se ignora (sería doble conteo).
        lines: list[InvoiceLine] = []
        current_box_idx = -1
        for raw in text.split('\n'):
            s = raw.strip()
            if not s:
                continue
            # Si es un parent, avanzamos al siguiente box
            if _PARENT_RE.match(s):
                current_box_idx += 1
                continue
            m = _SUBLINE_RE.match(s)
            if not m:
                continue
            box_type = 'HB'
            if 0 <= current_box_idx < len(parents):
                t = parents[current_box_idx]['box_type']
                box_type = f'{t}B'
            species = _SPECIES_MAP.get(m.group('species').upper(), 'OTHER')
            stems = int(m.group('stems'))
            spb = int(m.group('spb'))
            bunches = int(m.group('bunches'))
            price = _num(m.group('price'))
            lines.append(InvoiceLine(
                raw_description=s[:120],
                species=species,
                variety=m.group('variety').strip().upper(),
                origin='COL',
                size=int(m.group('size')),
                stems_per_bunch=spb,
                bunches=bunches,
                stems=stems,
                price_per_stem=price,
                line_total=round(stems * price, 2),
                box_type=box_type,
                provider_key=provider_data.get('key', ''),
            ))

        if not header.total and lines:
            header.total = round(sum(l.line_total for l in lines), 2)
        return header, lines
