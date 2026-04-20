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


def _ocr_normalize(raw: str) -> str:
    """Normaliza ruido OCR de facturas MILAGRO escaneadas muy mal.
    ``~OSES``→``ROSES``, ``FREE DOM``→``FREEDOM``, ``SO`` pegado a CM/size→``50``,
    ``25(``→``250`` / ``0.28(``→``0.280`` (paréntesis OCR de un cero),
    ``�`` (U+FFFD) → ``-`` cuando separa spb y size.
    """
    if not raw:
        return raw
    s = raw
    s = re.sub(r'~OSES\b', 'ROSES', s)
    s = re.sub(r'FREE\s+DOM\b', 'FREEDOM', s, flags=re.I)
    # Varios chars basura que el OCR usa como separador tipo `-`:
    # U+FFFD (replacement), U+2022 (bullet), U+00B0 (°), U+00B7 (·)
    s = re.sub(r'[\ufffd\u2022\u00b0\u00b7]', '-', s)
    # "SO"/"S0" en posición de size (entre `-` o `X` y resto): "25 - SO"
    s = re.sub(r'(?<=\s)-\s*S[O0](?=\s)', '- 50', s)
    s = re.sub(r'(?<=\s)S[O0]\s+(?=\d{5,6})', '50 ', s)  # "SO 000001" → "50 000001"
    # `0.28(` / `25(` : `(` basura final que OCR confundió con un `0`
    s = re.sub(r'(\d)\(\B', r'\g<1>0', s)
    return s


class AutoParser:
    fmt_key = 'auto_milagro'

    def parse(self, text: str, provider_data: dict) -> tuple[InvoiceHeader, list[InvoiceLine]]:
        header = InvoiceHeader(
            provider_id=provider_data.get('id', 0),
            provider_name=provider_data.get('name', ''),
            provider_key=provider_data.get('key', ''),
        )
        text = '\n'.join(_ocr_normalize(ln) for ln in text.split('\n'))
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
                    'match': mp,
                })

        # Estrategia por parent:
        # - is_mixto=True → emitir sub-líneas (detalle por variedad, cada una
        #   con su precio/cantidad dentro del box mixto).
        # - is_mixto=False → emitir el parent directamente; la sub-línea
        #   describe solo UN box (12 bunches/300 stems), mientras el parent
        #   agrega todos los boxes del item (24 bunches/600 stems/$132) que
        #   es lo que suma con el header.
        lines: list[InvoiceLine] = []
        current_box_idx = -1
        for raw in text.split('\n'):
            s = raw.strip()
            if not s:
                continue
            mp = _PARENT_RE.match(s)
            if mp:
                current_box_idx += 1
                # Emitir parent si no es mixto
                p = parents[current_box_idx] if 0 <= current_box_idx < len(parents) else None
                if p and not p['is_mixto']:
                    species = _SPECIES_MAP.get(mp.group('species').upper(), 'OTHER')
                    total_stems = int(mp.group('total_stems'))
                    total_bunch = int(mp.group('total_bunch'))
                    spb = int(mp.group('spb'))
                    price = _num(mp.group('price'))
                    lines.append(InvoiceLine(
                        raw_description=s[:120],
                        species=species,
                        variety=mp.group('variety').strip().upper(),
                        origin='COL',
                        size=int(mp.group('size')),
                        stems_per_bunch=spb,
                        bunches=total_bunch,
                        stems=total_stems,
                        price_per_stem=price,
                        line_total=_num(mp.group('total')),
                        box_type=f"{mp.group('box_type')}B",
                        provider_key=provider_data.get('key', ''),
                    ))
                continue

            # Sub-línea: solo se emite si el box actual es mixto.
            m = _SUBLINE_RE.match(s)
            if not m:
                continue
            parent = parents[current_box_idx] if 0 <= current_box_idx < len(parents) else None
            if parent and not parent['is_mixto']:
                # Ya emitimos el parent; evitar doble conteo.
                continue
            box_type = 'HB'
            if parent:
                box_type = f"{parent['box_type']}B"
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
