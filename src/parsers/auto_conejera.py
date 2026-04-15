"""Parser auto-generado para FLORES LA CONEJERA SAS (factura electrónica COL).

Layout:
    BOX QTY BOX TYPE UNIT/BOX PRODUCT SM HTS PO # UNIT TYPE STEMS PRICE / STEM TOTAL PRICE
    1 QB 500 CARNATION ASSORTED SHORT PORRIÑO 0603.12.90.00 CAJICA Stems 500 USD$ 0.080 USD$ 40.00

Campos: box_num, box_type, unit/box, product (species+variety+grade),
        sm (customer code), hts, po (farm code), unit_type (Stems/Bunches),
        total_stems, price_per_stem, total_price.
"""
from __future__ import annotations

import re
from src.models import InvoiceHeader, InvoiceLine
from src.config import translate_carnation_color


_LINE_RE = re.compile(
    r'^(?P<box_num>\d+)\s+'
    r'(?P<box_type>HB|QB|TB|FB)\s+'
    r'(?P<unit_box>\d+)\s+'
    r'(?P<product>[A-Z][A-Z0-9\s\-\'/]+?)\s+'
    r'(?P<sm>\S+)\s+'
    r'(?P<hts>\d{4}\.\d{2}\.\d{2}\.\d{2})\s+'
    r'(?P<po>\S+)\s+'
    r'(?P<unit_type>Stems|Bunches|STEMS|BUNCHES)\s+'
    r'(?P<stems>\d+)\s+'
    r'USD\$?\s*(?P<price>[\d.]+)\s+'
    r'USD\$?\s*(?P<total>[\d.]+)\s*$',
    re.IGNORECASE,
)

_INVOICE_RE = re.compile(r'FE(\d+)', re.I)
_DATE_RE    = re.compile(r'DATE\s+ISSUED\s*\n?\s*(\d{4}-\d{2}-\d{2})', re.I)
_AWB_RE     = re.compile(r'MAWB\s*:\s*(\S+)', re.I)
_HAWB_RE    = re.compile(r'HAWB\s*:\s*(\S+)', re.I)
_TOTAL_RE   = re.compile(r'TOTAL\s+USD\$?\s*([\d.]+)', re.I)

_GRADES = {'SHORT', 'SELECT', 'FANCY', 'STANDARD', 'PREMIUM'}


def _split_product(product: str) -> tuple[str, str, str]:
    """Separa 'CARNATION ASSORTED SHORT' en (species_raw, variety, grade)."""
    tokens = product.upper().split()
    if not tokens:
        return '', '', ''
    # Species prefix (puede ser 1-2 palabras)
    species_raw = tokens[0]
    skip = 1
    if len(tokens) > 1 and tokens[0] == 'MINI' and tokens[1] in ('CARNATION', 'ROSE'):
        species_raw = 'MINI ' + tokens[1]
        skip = 2
    if len(tokens) > 1 and tokens[0] == 'SPRAY' and tokens[1] in ('CARNATION', 'ROSES', 'ROSE'):
        species_raw = 'SPRAY ' + tokens[1]
        skip = 2
    rest = tokens[skip:]
    # Grade = última palabra si matchea
    grade = ''
    if rest and rest[-1] in _GRADES:
        grade = rest[-1]
        rest = rest[:-1]
    variety = ' '.join(rest) or 'ASSORTED'
    return species_raw, variety, grade


_SPECIES_MAP = {
    'CARNATION': 'CARNATIONS',
    'MINI CARNATION': 'CARNATIONS',
    'SPRAY CARNATION': 'CARNATIONS',
    'ROSE': 'ROSES', 'ROSES': 'ROSES',
    'SPRAY ROSE': 'ROSES', 'SPRAY ROSES': 'ROSES',
    'HYDRANGEA': 'HYDRANGEAS', 'HYDRANGEAS': 'HYDRANGEAS',
    'ALSTROEMERIA': 'ALSTROEMERIA',
    'GYPSOPHILA': 'GYPSOPHILA',
    'CHRYSANTHEMUM': 'CHRYSANTHEMUM',
}


class AutoParser:
    fmt_key = 'auto_conejera'

    def parse(self, text: str, provider_data: dict) -> tuple[InvoiceHeader, list[InvoiceLine]]:
        header = InvoiceHeader(
            provider_id=provider_data.get('id', 0),
            provider_name=provider_data.get('name', ''),
            provider_key=provider_data.get('key', ''),
        )
        m = _INVOICE_RE.search(text)
        if m:
            header.invoice_number = 'FE' + m.group(1)
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
            header.total = float(m.group(1))

        lines: list[InvoiceLine] = []
        for raw in text.split('\n'):
            s = raw.strip()
            if not s or len(s) < 30:
                continue
            m = _LINE_RE.match(s)
            if not m:
                continue
            species_raw, variety, grade = _split_product(m.group('product'))
            species = _SPECIES_MAP.get(species_raw, 'OTHER')
            # Carnations: traducir color a español
            if species == 'CARNATIONS':
                variety = translate_carnation_color(variety)
            stems = int(m.group('stems'))
            # SPB por defecto: 20 claveles, 25 rosas, 10 mini
            if species == 'CARNATIONS':
                spb = 10 if 'MINI' in species_raw else 20
            elif species == 'HYDRANGEAS':
                spb = 1
            else:
                spb = 25
            bunches = stems // spb if spb else 0
            lines.append(InvoiceLine(
                raw_description=s[:120],
                species=species,
                variety=variety,
                grade=grade,
                origin='COL',
                size=0,     # no viene en factura
                stems_per_bunch=spb,
                bunches=bunches,
                stems=stems,
                price_per_stem=float(m.group('price')),
                line_total=float(m.group('total')),
                box_type=m.group('box_type').upper(),
                label=m.group('po'),
                provider_key=provider_data.get('key', ''),
            ))

        if not header.total and lines:
            header.total = round(sum(l.line_total for l in lines), 2)
        return header, lines
