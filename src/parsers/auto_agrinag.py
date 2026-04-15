"""Parser auto-generado para AGRINAG.

Layout — mismo template SaaS que QUALISA/BELLAROSA pero con estructura
parent/sub-línea para cajas mixtas:

    1 HB1 AGR MIXED BOX MIXED BOX 10 $8.5000 250 $0.3400 $85.00     ← parent MIXED
    (95*30*35)                                                      ← dimensiones caja
    HOT MERENGUE 50CM 25ST AGCT A ROSES 4 $7.7500 100 $0.3100 $31.0000
    HOT MERENGUE 60CM 25ST AGCT A ROSES 6 $9.0000 150 $0.3600 $54.0000
    1 HB1 AGR TUTTI FRUTTI 60CM 25ST AGCT A ROSES 10 $9.0000 250 $0.3600 $90.00

Estrategia: un solo regex que casa tanto parent-con-detalle como sub-línea.
Descartamos los `MIXED BOX` (no aportan variedad) y nos quedamos con el resto.
"""
from __future__ import annotations

import re
from src.models import InvoiceHeader, InvoiceLine


# Bloque común: variety size CM [packing] spb ST label [grade] species bunches pbunch stems pstem total
# - packing: letra suelta ('P', 'N', etc.) entre size y spb, opcional
# - species: una o dos palabras ('SPRAY ROSES', 'MINI CARNATIONS')
# - trailing suffix: ocasional palabra extra tras total (ej 'REY' como marca)
_BODY = (
    r'(?P<variety>[A-Z][A-Z0-9\s\-\'/]*?)\s+'
    r'(?P<size>\d+)\s*CM\s+'
    r'(?:[A-Z]\s+)?'                             # packing opcional (letra suelta)
    r'(?P<spb>\d+)\s*ST\s+'
    r'(?P<label>\S+)\s+'
    r'(?:(?P<grade>[A-Z]{1,2})\s+)?'             # grade opcional
    r'(?P<species>(?:SPRAY\s+|MINI\s+|GARDEN\s+)?'
    r'ROSES|CARNATIONS?|HYDRANGEAS?|ALSTROEMERIA|GYPSOPHILA|CHRYSANTHEMUM)\s+'
    r'(?P<bunches>\d+)\s+'
    r'\$?\s*(?P<p_bunch>[\d,]+\.\d+)\s+'
    r'(?P<stems>\d+)\s+'
    r'\$?\s*(?P<p_stem>[\d,]+\.\d+)\s+'
    r'\$?\s*(?P<total>[\d,]+\.\d+)'
    r'(?:\s+[\d,.]+\s+[\d,.]+)?'                 # volumen/peso opcional
    r'(?:\s+[A-Z]{2,5})?\s*$'                    # suffix opcional (REY, etc.)
)

# Con prefijo de caja. Pieces puede ir pegado al tipo ('HB1') o separado
# por espacio ('QB NATU'). Farm code opcional, 2-5 letras después del tipo.
_LINE_PARENT_RE = re.compile(
    r'^(?P<box_num>\d+)\s+'
    r'(?P<box_type>HB|QB|TB|FB)'
    r'(?P<pieces>\d*)\s+'                        # pieces puede estar vacío
    r'(?P<farm_code>[A-Z]{2,5})\s+'
    + _BODY,
    re.IGNORECASE,
)

# Sin prefijo (sub-línea de mixed box o continuación)
_LINE_CONT_RE = re.compile(r'^' + _BODY, re.IGNORECASE)

_INVOICE_RE = re.compile(r'INVOICE\s+(?:Numbers?\s+)?(\d+)', re.I)
_DATE_RE    = re.compile(r'Invoice\s+Date\s+(\d{1,2}/\d{1,2}/\d{2,4})', re.I)
_MAWB_RE    = re.compile(r'MAWB\s+(\d{3}[-\s]\d{4}\s*\d{4})', re.I)
_HAWB_RE    = re.compile(r'HAWB\s+(\S+)', re.I)
_TOTAL_RE   = re.compile(r'Amount\s+Due\s+\$?\s*([\d,]+\.\d+)', re.I)

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


def _num(s: str) -> float:
    return float(s.replace(',', '')) if s else 0.0


class AutoParser:
    fmt_key = 'auto_agrinag'

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
        last_box_type = ''
        for raw in text.split('\n'):
            s = raw.strip()
            if not s or len(s) < 20:
                continue
            # Ignorar líneas de dimensiones tipo (95*30*35)
            if re.match(r'^\(\d+\*\d+\*[\d.]+\)$', s):
                continue
            # Ignorar líneas de totales
            if re.match(r'^\d+\s+TOTALS?\s+', s, re.I):
                continue

            m = _LINE_PARENT_RE.match(s)
            box_type = ''
            if m:
                variety = m.group('variety').strip().upper()
                box_type = m.group('box_type').upper()
                last_box_type = box_type
                # MIXED BOX → saltar parent, las sub-líneas traerán detalle real
                if 'MIXED BOX' in variety:
                    continue
                species_raw = m.group('species').upper()
                line = InvoiceLine(
                    raw_description=s[:120],
                    species=_SPECIES_MAP.get(species_raw, 'OTHER'),
                    variety=variety,
                    origin='EC',
                    grade=(m.group('grade') or '').upper(),
                    size=int(m.group('size')),
                    stems_per_bunch=int(m.group('spb')),
                    bunches=int(m.group('bunches')),
                    stems=int(m.group('stems')),
                    price_per_stem=_num(m.group('p_stem')),
                    price_per_bunch=_num(m.group('p_bunch')),
                    line_total=_num(m.group('total')),
                    box_type=box_type,
                    label=m.group('label').strip(),
                    provider_key=provider_data.get('key', ''),
                )
                lines.append(line)
                continue

            m = _LINE_CONT_RE.match(s)
            if m:
                variety = m.group('variety').strip().upper()
                species_raw = m.group('species').upper()
                # Rechazar continuaciones que no encajen (ej. línea ruido larga)
                if len(variety) < 2 or len(variety) > 40:
                    continue
                line = InvoiceLine(
                    raw_description=s[:120],
                    species=_SPECIES_MAP.get(species_raw, 'OTHER'),
                    variety=variety,
                    origin='EC',
                    grade=(m.group('grade') or '').upper(),
                    size=int(m.group('size')),
                    stems_per_bunch=int(m.group('spb')),
                    bunches=int(m.group('bunches')),
                    stems=int(m.group('stems')),
                    price_per_stem=_num(m.group('p_stem')),
                    price_per_bunch=_num(m.group('p_bunch')),
                    line_total=_num(m.group('total')),
                    box_type=last_box_type or 'HB',
                    label=m.group('label').strip(),
                    provider_key=provider_data.get('key', ''),
                )
                lines.append(line)

        if not header.total and lines:
            header.total = round(sum(l.line_total for l in lines), 2)

        return header, lines
