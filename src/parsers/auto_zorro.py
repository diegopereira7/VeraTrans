"""Parser auto-generado para FLORES EL ZORRO (Cundinamarca, Colombia).

Layout — proformas de muestra (SAMPLE WITHOUT COMMERCIAL VALUE en muchas).
Única muestra disponible = riesgo de overfit. OCR ruidoso (lowercase l por 1,
ASSORTEO en vez de ASSORTED, etc.).

    Product Label HTS Boxes Bun x Box h Bunches xBox Stems Units Price Total
    CARNATION ASSORTED Select 0603127000 1 HB 15 20 300 0.010 $ 3.000
    MINI CARNATION ASSORTED Select 0603123000 1 HB 30 10 300 0.010 $ 3.000
"""
from __future__ import annotations

import re
from src.models import InvoiceHeader, InvoiceLine
from src.parsers._helpers import extract_printed_total


# Línea tolerante al OCR: 'l' o '1' para pcs; variety con posible duplicación.
_LINE_RE = re.compile(
    r'^(?P<species>CARNATION|MINI\s+CARNATION|ROSES?|ROSA|CLAVEL(?:ES)?|HYDRANGEAS?|ALSTROEMERIA|SPRAY\s+ROSES?)\s+'
    r'(?P<variety>[A-Z][A-Z0-9\s\-\'/]+?)\s+'
    r'(?P<grade>Select|Fancy|Premium|Standard|Assorted)\s+'
    r'(?P<hts>\d{10})\s+'
    r'[l1I]\s+'                               # pcs: OCR 'l' por '1'
    r'(?P<box_type>HB|QB|TB|FB)\s+'
    r'(?P<bunches>\d+)\s+'
    r'(?P<spb>\d+)\s+'
    r'(?P<stems>\d+)\s+'
    r'(?P<price>\d+\.\d+)\s+'
    r'\$\s*(?P<total>[\d.,]+)\s*$',
    re.IGNORECASE,
)

_INVOICE_RE = re.compile(r'PROFORMA\s+(\d+)', re.I)

_SPECIES_MAP = {
    'CARNATION': 'CARNATIONS',
    'MINI CARNATION': 'CARNATIONS',
    'CLAVEL': 'CARNATIONS', 'CLAVELES': 'CARNATIONS',
    'ROSE': 'ROSES', 'ROSES': 'ROSES', 'ROSA': 'ROSES',
    'SPRAY ROSE': 'ROSES', 'SPRAY ROSES': 'ROSES',
    'HYDRANGEA': 'HYDRANGEAS', 'HYDRANGEAS': 'HYDRANGEAS',
    'ALSTROEMERIA': 'ALSTROEMERIA',
}


def _num(s: str) -> float:
    return float(s.replace(',', '')) if s else 0.0


class AutoParser:
    fmt_key = 'auto_zorro'

    def parse(self, text: str, provider_data: dict) -> tuple[InvoiceHeader, list[InvoiceLine]]:
        header = InvoiceHeader(
            provider_id=provider_data.get('id', 0),
            provider_name=provider_data.get('name', ''),
            provider_key=provider_data.get('key', ''),
        )
        m = _INVOICE_RE.search(text)
        if m:
            header.invoice_number = m.group(1)
        m = re.search(r'AWB\s+(\S+)', text, re.I)
        if m:
            header.awb = m.group(1)

        lines: list[InvoiceLine] = []
        for raw in text.split('\n'):
            s = ' '.join(raw.strip().split())   # colapsar espacios múltiples
            if not s or len(s) < 30:
                continue
            m = _LINE_RE.match(s)
            if not m:
                continue
            species_raw = re.sub(r'\s+', ' ', m.group('species').upper())
            species = _SPECIES_MAP.get(species_raw, 'OTHER')
            variety_raw = m.group('variety').strip().upper()
            # Corrección de OCR típica: ASSORTEO → ASSORTED
            variety = variety_raw.replace('ASSORTEO', 'ASSORTED')
            # Deduplicar: 'ASSORTED ASSORTED' → 'ASSORTED'
            tokens = variety.split()
            if len(tokens) == 2 and tokens[0] == tokens[1]:
                variety = tokens[0]
            lines.append(InvoiceLine(
                raw_description=s[:120],
                species=species,
                variety=variety,
                grade=m.group('grade').upper(),
                origin='COL',
                size=0,
                stems_per_bunch=int(m.group('spb')),
                bunches=int(m.group('bunches')),
                stems=int(m.group('stems')),
                price_per_stem=float(m.group('price')),
                line_total=_num(m.group('total')),
                box_type=m.group('box_type').upper(),
                provider_key=provider_data.get('key', ''),
            ))

        # Sesión 12q: extraer total impreso preventivamente.
        if not header.total:
            header.total = extract_printed_total(text)
        if not header.total and lines:
            header.total = round(sum(l.line_total for l in lines), 2)
        return header, lines
