"""Parser auto-generado para SAN FRANCISCO GARDENS (CI SAN FRANCISCO SAS).

Proveedor colombiano especializado en hydrangeas. Layout:

    BXS PCS DESCRIPTION HTS CUST ORD P.O. S.P. UNITSTEMS PRICE TOTAL
    Hydrangea / Macrophylla                                       ← header de sección
    6.250 25.00QBx30 HYDRANGEA PREMIUM WHITE 0603190125 750 stem 750 0.6 450.00

Campos: <bxs> <pcs><type>x<pack> <species/variety> <hts> <stems> stem <total_stems> <price> <total>
"""
from __future__ import annotations

import re
from src.models import InvoiceHeader, InvoiceLine


_LINE_RE = re.compile(
    r'^(?P<bxs>[\d.]+)\s+'
    r'(?P<pcs>[\d.]+)'
    r'(?P<box_type>HB|QB|TB|FB)'
    r'x(?P<pack>\d+)\s+'
    r'HYDRANGEA\s+(?P<variety>[A-Z][A-Z\s]+?)\s+'
    r'(?P<hts>06\d{8})\s+'
    r'(?P<unit_stems>\d+)\s+stem\s+'
    r'(?P<total_stems>\d+)\s+'
    r'(?P<price>[\d.]+)\s+'
    r'(?P<total>[\d.]+)\s*$',
    re.IGNORECASE,
)

_INVOICE_RE = re.compile(r'INVOICE\s+(\d+)', re.I)
_DATE_RE    = re.compile(r'(\d{1,2}[A-Z]{3}\d{4})', re.I)
_AWB_RE     = re.compile(r'(\d{3}-\d{8})', re.I)


def _num(s: str) -> float:
    return float(s) if s else 0.0


class AutoParser:
    fmt_key = 'auto_sanfrancisco'

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

        lines: list[InvoiceLine] = []
        for raw in text.split('\n'):
            s = raw.strip()
            if not s or len(s) < 20:
                continue
            m = _LINE_RE.match(s)
            if not m:
                continue
            variety = m.group('variety').strip().upper()
            stems = int(m.group('total_stems'))
            # SPB = stems / pcs (bunches). Hydrangeas normalmente 1 stem per bunch.
            pack = int(m.group('pack'))
            price = _num(m.group('price'))
            lines.append(InvoiceLine(
                raw_description=s[:120],
                species='HYDRANGEAS',
                variety=variety,
                origin='COL',
                size=60,            # tamaño estándar hydrangea
                stems_per_bunch=1,   # hydrangeas: 1 stem/bunch en VeraBuy
                bunches=stems,        # para hydrangeas, bunches = stems
                stems=stems,
                price_per_stem=price,
                line_total=_num(m.group('total')),
                box_type=m.group('box_type').upper(),
                provider_key=provider_data.get('key', ''),
            ))

        if not header.total and lines:
            header.total = round(sum(l.line_total for l in lines), 2)
        return header, lines
