"""Parser auto-generado para QUALISA, BELLAROSA (y familia SaaS).

Layout común (ejemplo):
    # BOX PRODUCT SPECIES LABEL    [cabecera]
    1 QB 1 LEMONADE    50CM P 25ST QUCT  ROSES 4  $8.0000 100 $0.3200 $32.00 7.44 0.00
    1 HB 1 TUTTI FRUTTI 50CM   20ST BECBE ROSES 10 $6.0000 200 $0.3000 $60.00

Tokens:
    box_num box_type pieces <variety...> <size>CM [P] <spb>ST <label> <species>
    <bunches> $<p_bunch> <stems> $<p_stem> $<total> [<vol_wt> <real_wt>]

Variedad puede ser multi-palabra (ej 'TUTTI FRUTTI'). Ancla: se captura lazy
hasta el `<num>CM` que marca la talla.
"""
from __future__ import annotations

import re
from src.models import InvoiceHeader, InvoiceLine


_SPECIES_MAP = {
    'ROSES':          'ROSES',
    'CARNATIONS':     'CARNATIONS',
    'CARNATION':      'CARNATIONS',
    'HYDRANGEAS':     'HYDRANGEAS',
    'HYDRANGEA':      'HYDRANGEAS',
    'ALSTROEMERIA':   'ALSTROEMERIA',
    'GYPSOPHILA':     'GYPSOPHILA',
    'CHRYSANTHEMUM':  'CHRYSANTHEMUM',
}

_LINE_RE = re.compile(
    r'^(?P<box_num>\d+)\s+'
    r'(?P<box_type>HB|QB|TB|FB)\s+'
    r'(?P<pieces>\d+)\s+'
    r'(?P<variety>[A-Z][A-Z0-9\s\-\'/]*?)\s+'
    r'(?P<size>\d+)\s*CM\s+'
    r'(?:P\s+)?'                              # packing opcional
    r'(?P<spb>\d+)\s*ST\s+'
    r'(?P<label>\S+)\s+'
    r'(?P<species>ROSES|CARNATIONS?|HYDRANGEAS?|ALSTROEMERIA|GYPSOPHILA|CHRYSANTHEMUM)\s+'
    r'(?P<bunches>\d+)\s+'
    r'\$?\s*(?P<p_bunch>[\d,]+\.\d+)\s+'
    r'(?P<stems>\d+)\s+'
    r'\$?\s*(?P<p_stem>[\d,]+\.\d+)\s+'
    r'\$?\s*(?P<total>[\d,]+\.\d+)'
    r'(?:\s+[\d,.]+\s+[\d,.]+)?\s*$',        # vol_wt real_wt opcionales
    re.IGNORECASE,
)

_INVOICE_RE = re.compile(r'(?:CUSTOMER\s+)?INVOICE\s+(?:Numbers?\s+)?(\d+)', re.I)
_DATE_RE    = re.compile(r'Invoice\s+Date\s+(\d{1,2}/\d{1,2}/\d{2,4})', re.I)
_MAWB_RE    = re.compile(r'MAWB\s+(\d{3}[-\s]\d{4}\s*\d{4})', re.I)
_HAWB_RE    = re.compile(r'HAWB\s+(\S+)', re.I)
_TOTAL_RE   = re.compile(r'Amount\s+Due\s+\$?\s*([\d,]+\.\d+)', re.I)


def _num(s: str) -> float:
    return float(s.replace(',', '')) if s else 0.0


class AutoParser:
    """Parser común QUALISA / BELLAROSA (template SaaS)."""

    fmt_key = 'auto_qualisa'

    def parse(self, text: str, provider_data: dict) -> tuple[InvoiceHeader, list[InvoiceLine]]:
        header = InvoiceHeader(
            provider_id=provider_data.get('id', 0),
            provider_name=provider_data.get('name', ''),
            provider_key=provider_data.get('key', ''),
        )
        m = _INVOICE_RE.search(text)
        if m:
            header.invoice_number = m.group(1).strip()
        m = _DATE_RE.search(text)
        if m:
            header.date = m.group(1).strip()
        m = _MAWB_RE.search(text)
        if m:
            header.awb = re.sub(r'\s+', '', m.group(1))
        m = _HAWB_RE.search(text)
        if m:
            header.hawb = m.group(1).strip()
        m = _TOTAL_RE.search(text)
        if m:
            header.total = _num(m.group(1))

        lines: list[InvoiceLine] = []
        for raw in text.split('\n'):
            s = raw.strip()
            if not s or len(s) < 20:
                continue
            m = _LINE_RE.match(s)
            if not m:
                continue
            species_raw = m.group('species').upper()
            species = _SPECIES_MAP.get(species_raw, 'OTHER')
            # Origen: QUALISA/BELLAROSA son Ecuador; podríamos afinar por RUC.
            origin = 'EC'
            # Carnation: traducir color a español si procede (variety contiene color)
            variety = m.group('variety').strip().upper()

            line = InvoiceLine(
                raw_description=s[:120],
                species=species,
                variety=variety,
                origin=origin,
                size=int(m.group('size')),
                stems_per_bunch=int(m.group('spb')),
                bunches=int(m.group('bunches')),
                stems=int(m.group('stems')),
                price_per_stem=_num(m.group('p_stem')),
                price_per_bunch=_num(m.group('p_bunch')),
                line_total=_num(m.group('total')),
                box_type=m.group('box_type').upper(),
                label=m.group('label').strip(),
                provider_key=provider_data.get('key', ''),
            )
            lines.append(line)

        # Si no hay total en cabecera, derivar de las líneas
        if not header.total and lines:
            header.total = round(sum(l.line_total for l in lines), 2)

        return header, lines
