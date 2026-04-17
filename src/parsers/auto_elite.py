"""Parser auto-generado para THE ELITE FLOWER (FLORA CONCEPT LLC distribuye).

Layout complejo con parent + sub-líneas por variedad para cajas mixtas:

    ALSTROEMERIA ASSORTED INCREDIBLE 1HALF 240 240 24 0.2800 2.8000 67.2000 0.500   ← parent
    ALSTROEMERIA COTE D AZUR INCREDIBLE 40                                           ← sub (solo stems)
    ALSTROEMERIA PRIMADONNA INCREDIBLE 40
    ...

Rosas (layout similar pero con tamaño CM):
    GARDEN ROSES * 25 STEMS WHITE O'HARA 60 CM 1HALF 250 250 10 0.3600 9.0000 90.0000 0.500

Estrategia: si parent tiene variety ASSORTED/MIX, saltar y usar sub-líneas
(heredando price del parent). Si parent es una variedad concreta (WHITE O'HARA,
WINTERFELL), emitirlo directamente y saltar sub-líneas.
"""
from __future__ import annotations

import re
from src.models import InvoiceHeader, InvoiceLine


# Parent alstroemeria: species variety grade <type> <boxstems> <totalstems>
#                     <totalbunch> <pricestem> <pricebunch> <totalprice> <fullbox>
_PARENT_ALSTRO_RE = re.compile(
    r'^(?P<species>ALSTROEMERIA|ALSTRO|SPRAY\s+ROSES?|GARDEN\s+ROSES?|ROSES?|CARNATIONS?|HYDRANGEAS?)\s+'
    r'(?:\*\s*\d+\s*STEMS\s+)?'
    r'(?P<variety>[A-Z][A-Z0-9\s\-\'/]+?)\s+'
    r'(?P<grade>PREMIUM|INCREDIBLE|SELECT|FANCY|STANDARD)\s+'
    r'(?:(?P<size>\d{2,3})\s*CM\s+)?'
    r'(?P<type>\d+[HT]ALF|\d+FULL|\d+QUARTER|\dHALF|\dFULL)\s+'
    r'(?P<stems_box>\d+)\s+'
    r'(?P<total_stems>\d+)\s+'
    r'(?P<total_bunch>\d+)\s+'
    r'(?P<p_stem>[\d.]+)\s+'
    r'(?P<p_bunch>[\d.]+)\s+'
    r'(?P<total>[\d.]+)\s+'
    r'(?P<fullbox>[\d.]+)\s*$',
    re.IGNORECASE,
)

# Sub-línea: species variety grade <stems>
_SUBLINE_RE = re.compile(
    r'^(?P<species>ALSTROEMERIA|ALSTRO|SPRAY\s+ROSES?|GARDEN\s+ROSES?|ROSES?)\s+'
    r'(?:\*\s*\d+\s*STEMS\s+)?'
    r'(?P<variety>[A-Z][A-Z0-9\s\-\'/]+?)\s+'
    r'(?P<grade>PREMIUM|INCREDIBLE|SELECT|FANCY|STANDARD)\s+'
    r'(?:(?P<size>\d{2,3})\s*CM\s+)?'
    r'(?P<stems>\d+)\s*$',
    re.IGNORECASE,
)

_INVOICE_RE = re.compile(r'INVOICE\s+NUMBER\s*:\s*(\S+)', re.I)
_DATE_RE    = re.compile(r'SHIPMENT\s+DATE\s*:\s*(\d{4}/\d{2}/\d{2})', re.I)
_AWB_RE     = re.compile(r'AWB\s*:\s*(\S+)', re.I)
_HAWB_RE    = re.compile(r'AWBH\s*:\s*(\S+)', re.I)

_SPECIES_MAP = {
    'ALSTROEMERIA': 'ALSTROEMERIA', 'ALSTRO': 'ALSTROEMERIA',
    'ROSES': 'ROSES', 'ROSE': 'ROSES',
    'SPRAY ROSES': 'ROSES', 'SPRAY ROSE': 'ROSES',
    'GARDEN ROSES': 'ROSES', 'GARDEN ROSE': 'ROSES',
    'CARNATIONS': 'CARNATIONS', 'CARNATION': 'CARNATIONS',
    'HYDRANGEAS': 'HYDRANGEAS', 'HYDRANGEA': 'HYDRANGEAS',
}

_MIX_VARIETIES = {'ASSORTED', 'MIX', 'MIXED'}


def _box_type_from_elite(s: str) -> str:
    up = s.upper()
    if 'HALF' in up:
        return 'HB'
    if 'QUARTER' in up:
        return 'QB'
    if 'FULL' in up:
        return 'FB'
    return 'HB'


class AutoParser:
    fmt_key = 'auto_elite'

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
        # Estado del último parent (heredado por sub-líneas)
        last = {
            'is_mix': False,
            'species': 'ROSES',
            'size': 0,
            'p_stem': 0.0,
            'grade': '',
            'box_type': 'HB',
            'spb': 25,
        }
        for raw in text.split('\n'):
            s = raw.strip()
            if not s or len(s) < 20:
                continue

            m = _PARENT_ALSTRO_RE.match(s)
            if m:
                species_raw = re.sub(r'\s+', ' ', m.group('species').upper())
                species = _SPECIES_MAP.get(species_raw, 'OTHER')
                variety = m.group('variety').strip().upper()
                # Defaults por especie cuando el PDF no explicita CM:
                # ELITE siempre factura alstroemeria 70cm y claveles 60cm.
                default_size = {'ROSES': 60, 'ALSTROEMERIA': 70,
                                'CARNATIONS': 60, 'HYDRANGEAS': 60}.get(species, 0)
                size = int(m.group('size')) if m.group('size') else default_size
                total_stems = int(m.group('total_stems'))
                total_bunch = int(m.group('total_bunch'))
                spb = total_stems // total_bunch if total_bunch else 10
                p_stem = float(m.group('p_stem'))
                box_type = _box_type_from_elite(m.group('type'))
                grade = m.group('grade').upper()

                last.update(species=species, size=size, p_stem=p_stem,
                            grade=grade, box_type=box_type, spb=spb)
                last['is_mix'] = any(v in variety for v in _MIX_VARIETIES)

                if not last['is_mix']:
                    lines.append(InvoiceLine(
                        raw_description=s[:120], species=species, variety=variety,
                        grade=grade, origin='COL', size=size, stems_per_bunch=spb,
                        bunches=total_bunch, stems=total_stems,
                        price_per_stem=p_stem, line_total=float(m.group('total')),
                        box_type=box_type, provider_key=provider_data.get('key', ''),
                    ))
                continue

            m = _SUBLINE_RE.match(s)
            if m and last['is_mix']:
                # Solo procesar sub-líneas si el parent era mix
                variety = m.group('variety').strip().upper()
                if variety in _MIX_VARIETIES:
                    continue
                stems = int(m.group('stems'))
                species = _SPECIES_MAP.get(m.group('species').upper(), last['species'])
                size = int(m.group('size')) if m.group('size') else last['size']
                p_stem = last['p_stem']
                spb = last['spb']
                bunches = stems // spb if spb else 0
                lines.append(InvoiceLine(
                    raw_description=s[:120], species=species, variety=variety,
                    grade=m.group('grade').upper(), origin='COL', size=size,
                    stems_per_bunch=spb, bunches=bunches, stems=stems,
                    price_per_stem=p_stem, line_total=round(stems * p_stem, 2),
                    box_type=last['box_type'], provider_key=provider_data.get('key', ''),
                ))

        if not header.total and lines:
            header.total = round(sum(l.line_total for l in lines), 2)
        return header, lines
