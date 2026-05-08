"""Parser auto-generado para NATUFLOR.

Soporta DOS formatos de factura (la carpeta del usuario mezcla ambos):

Formato A — colombiano clásico (NIT 830501747, `FACTURA PROFORMA-FLOR...`):
    ROSE FREEDOM 40 Cm 10 350 3,500 .250 875.00
    ALSTRO (TSTEM ASSORTED SELECT 2 100 200 .180 36.00

Formato B — template SaaS (mismo que AGRINAG/QUALISA/BELLAROSA):
    1 HB NATU ESPERANCE 70CM N 25ST NACT ROSES 10 $11.2500 250 $0.4500 $112.50

Detecta cuál aplicar por la presencia de `FACTURA PROFORMA` vs `CUSTOMER INVOICE`.
"""
from __future__ import annotations

import re
from src.models import InvoiceHeader, InvoiceLine
from src.parsers._helpers import extract_printed_total

# Re-usa el parser SaaS (agrinag) para formato B
from src.parsers.auto_agrinag import AutoParser as _SaaSParser


_SPECIES_PREFIXES = {
    'ROSE':      'ROSES',
    'ROSES':     'ROSES',
    'ALSTRO':    'ALSTROEMERIA',
    'HYDRANGEA': 'HYDRANGEAS',
    'HYDRA':     'HYDRANGEAS',
    'CARNATION': 'CARNATIONS',
    'CARN':      'CARNATIONS',
    'GYPSO':     'GYPSOPHILA',
    'GYPS':      'GYPSOPHILA',
    'CHRYS':     'CHRYSANTHEMUM',
}

# Formato A: <species> [modificador] <variety...> <size> Cm <bunches> <spb> <stems> .<price> <total>
_LINE_A_ROSE_RE = re.compile(
    r'^(?P<species>ROSE|ROSES)\s+'
    r'(?P<variety>[A-Z][A-Z0-9\s\-/\']+?)\s+'
    r'(?P<size>\d{2,3})(?:\s*-\s*\d{2,3})?\s*(?:Cm|CM|cm)\s+'
    r'(?P<bunches>\d+)\s+'
    r'(?P<spb>\d+)\s+'
    r'(?P<stems>[\d,]+)\s+'
    r'\.?(?P<price>\d+)\s+'
    r'(?P<total>[\d,]+\.\d+)\s*$',
)

# ALSTRO / CARNATION sin size: species [modificador] variety bunches spb stems price total
_LINE_A_NOSIZE_RE = re.compile(
    r'^(?P<species>ALSTRO|CARNATION|GYPSO|HYDRA)\S*\s+'
    r'(?:\(\S+\s+)?'                            # modificador tipo (TSTEM
    r'(?P<variety>[A-Z][A-Z0-9\s\-/\']+?)\s+'
    r'(?P<bunches>\d+)\s+'
    r'(?P<spb>\d+)\s+'
    r'(?P<stems>[\d,]+)\s+'
    r'\.?(?P<price>\d+)\s+'
    r'(?P<total>[\d,]+\.\d+)\s*$',
)

_INVOICE_A_RE = re.compile(r'No\.\s*(\d{4,})', re.I)
_DATE_A_RE    = re.compile(r'DATE\(DD/MM/YY\):\s*(\d{1,2}/\d{1,2}/\d{2,4})', re.I)
_AWB_A_RE     = re.compile(r'AWB:(\S+)', re.I)


def _num(s: str) -> float:
    return float(s.replace(',', '')) if s else 0.0


def _int(s: str) -> int:
    return int(s.replace(',', '')) if s else 0


def _parse_format_a(text: str, provider_data: dict) -> tuple[InvoiceHeader, list[InvoiceLine]]:
    """Colombian layout. Origin=COL."""
    header = InvoiceHeader(
        provider_id=provider_data.get('id', 0),
        provider_name=provider_data.get('name', ''),
        provider_key=provider_data.get('key', ''),
    )
    m = _INVOICE_A_RE.search(text)
    if m:
        header.invoice_number = m.group(1)
    m = _DATE_A_RE.search(text)
    if m:
        header.date = m.group(1)
    m = _AWB_A_RE.search(text)
    if m:
        header.awb = m.group(1)

    lines: list[InvoiceLine] = []
    for raw in text.split('\n'):
        s = raw.strip()
        if not s or len(s) < 20:
            continue
        m = _LINE_A_ROSE_RE.match(s) or _LINE_A_NOSIZE_RE.match(s)
        if not m:
            continue
        gd = m.groupdict()
        sp_raw = gd['species'].upper()
        species = _SPECIES_PREFIXES.get(sp_raw, 'OTHER')
        # price en formato ".250" → 0.250
        p_str = gd['price']
        if '.' not in p_str:
            p_str = '0.' + p_str
        price = float(p_str)
        size = int(gd['size']) if 'size' in gd and gd.get('size') else 0
        line = InvoiceLine(
            raw_description=s[:120],
            species=species,
            variety=gd['variety'].strip().upper(),
            origin='COL',
            size=size,
            stems_per_bunch=_int(gd['spb']),
            bunches=_int(gd['bunches']),
            stems=_int(gd['stems']),
            price_per_stem=price,
            line_total=_num(gd['total']),
            provider_key=provider_data.get('key', ''),
        )
        lines.append(line)

    # Sesión 12q: extraer total impreso preventivamente.
    if not header.total:
        header.total = extract_printed_total(text)
    if not header.total and lines:
        header.total = round(sum(l.line_total for l in lines), 2)
    return header, lines


class AutoParser:
    fmt_key = 'auto_natuflor'

    def parse(self, text: str, provider_data: dict) -> tuple[InvoiceHeader, list[InvoiceLine]]:
        # Detectar formato
        if 'FACTURA PROFORMA' in text.upper() or 'NIT:830501747' in text:
            return _parse_format_a(text, provider_data)
        # Formato SaaS → delegar en AGRINAG parser
        return _SaaSParser().parse(text, provider_data)
