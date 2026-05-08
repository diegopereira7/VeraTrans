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

# Layout BOUQUET (NATIVEFARM facturas tropicales 2026):
#   "HB 1 0,5 Bqt. Sweet 8 6,65 53,20"   ← parent: 1 box × 8 ramos × 6,65 = 53,20 (por caja)
#   "HB 2 1 Bqt. Intense 8 6,65 53,20"   ← 2 cajas × 8 ramos × 6,65 = 106,40 (line_total = 2×53,20)
#   "Alpinia A 0603.19.9095 ... Flower 4 0,21 32 6 ,86"  ← componentes (skip)
# El "total per box" del parent (53,20) se multiplica por boxes para obtener line_total real.
_LINE_BQT_PARENT_RE = re.compile(
    r'^(?P<box_type>HB|QB|FB|TB)\s+'
    r'(?P<boxes>\d+)\s+'
    r'(?P<eq_full>[\d,.]+)\s+'
    r'Bqt\.\s+(?P<name>[A-Za-z][A-Za-z0-9\s\-\']*?)\s+'
    r'(?P<bunches_per_box>\d+)\s+'
    r'(?P<price>[\d,.]+)\s+'
    r'(?P<total_per_box>[\d,.]+)\s*$',
    re.I,
)

# Layout BOUQUET (NATIVE BLOOMS facturas 2024):
#   "HB 3 1,5 Bouquet Round Mix 12 4 ,65 5 5,80 167,40"
#   "QB 1 0,25 Amazon Box 60 0 ,50 3 0,00 30,00"
# Sesión 12r: caja con name de 1+ palabras tras "Bouquet|Amazon|Paradise|
# Mountain|Tropical". El total es el último `\d+,\d{2}`. Las componentes
# (Heliconia, Musa, etc.) NO traen `$` y NO matchean este regex.
_LINE_BQT_NATIVE_RE = re.compile(
    r'^(?P<box_type>HB|QB|FB|TB)\s+'
    r'(?P<boxes>\d+)\s+'
    r'(?P<eq_full>[\d,.]+)\s+'
    r'(?P<name>(?:Bouquet|Amazon|Paradise|Mountain|Tropical)[A-Za-z\s]*?)\s+'
    r'(?P<stems>\d+)\s+'
    r'(?P<rest>[\d,. ]+?)\s+'
    r'(?P<total>\d{1,4}[,.]\d{2})\s*$',
    re.I,
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
        # Total impreso: "Total <pcs_box> <full> <stems> <total>" al final
        # de la tabla. Ejemplo: "Total 5 2,5 1240 2 66,00" — OCR rompe el
        # decimal con espacios → "2 66,00" significa 266,00. Capturamos
        # todo el resto y eliminamos espacios internos antes de parsear.
        m = re.search(
            r'(?m)^Total\s+\d+\s+[\d.,]+\s+\d+\s+([\d.,\s]+)$', text)
        if m:
            try:
                raw = re.sub(r'\s+', '', m.group(1))
                if not raw:
                    pass
                elif ',' in raw and '.' in raw:
                    header.total = float(raw.replace('.', '').replace(',', '.'))
                elif ',' in raw:
                    header.total = float(raw.replace(',', '.'))
                else:
                    header.total = float(raw)
            except ValueError:
                pass

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

            # Bouquet parent NATIVE BLOOMS (sesión 12r): boxes con
            # nombres tipo "Bouquet Round Mix" / "Amazon Box" / etc.
            m = _LINE_BQT_NATIVE_RE.match(s)
            if m:
                name = m.group('name').strip().upper()
                if name and len(name) >= 4:
                    try:
                        boxes = int(m.group('boxes'))
                        stems_per_box = int(m.group('stems'))
                        total = _num(m.group('total')) * boxes
                    except ValueError:
                        continue
                    total_stems = boxes * stems_per_box
                    price = round(total / total_stems, 4) if total_stems else 0.0
                    lines.append(InvoiceLine(
                        raw_description=s[:120],
                        species='OTHER',
                        variety=name,
                        origin='EC',
                        size=0,
                        stems_per_bunch=stems_per_box,
                        bunches=boxes,
                        stems=total_stems,
                        price_per_stem=price,
                        line_total=round(total, 2),
                        box_type=m.group('box_type').upper(),
                        grade='BOUQUET',
                        provider_key=provider_data.get('key', ''),
                    ))
                    continue

            # Bouquet parent (NATIVEFARM tropical bouquets)
            m = _LINE_BQT_PARENT_RE.match(s)
            if m:
                name = m.group('name').strip().upper()
                if not name or len(name) < 2:
                    continue
                try:
                    boxes = int(m.group('boxes'))
                    bunches_per_box = int(m.group('bunches_per_box'))
                    price = _num(m.group('price'))
                    total_per_box = _num(m.group('total_per_box'))
                except ValueError:
                    continue
                total_bouquets = boxes * bunches_per_box
                line_total = round(boxes * total_per_box, 2)
                lines.append(InvoiceLine(
                    raw_description=s[:120],
                    species='OTHER',
                    variety=name,
                    origin='EC',
                    size=0,
                    stems_per_bunch=1,
                    bunches=total_bouquets,
                    stems=total_bouquets,
                    price_per_stem=price,
                    line_total=line_total,
                    box_type=m.group('box_type').upper(),
                    grade='BOUQUET',
                    provider_key=provider_data.get('key', ''),
                ))
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
