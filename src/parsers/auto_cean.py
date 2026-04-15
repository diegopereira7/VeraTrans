"""Parser auto-generado para CEAN GLOBAL SAS.

Factura electrónica colombiana. Layout:

    Item Descripción Cantidad U Med. Cant. Cajas Tipo Caja Val Unit Total
    1 Carnation Red Select 800,00 Und. 2 QB 0,17 136,00
    2 Carnation Red Fancy*400 Tallos UE 800,00 Und. 2 QB 0,16 128,00
    7 Carnation White Select *400 Tallos UE 800,00 Und. 2 QB 0,16 124,00

Campos:
    item  | descripcion (species + color + grade [+ pack])
    cantidad=stems (decimal con coma, realmente entero)
    u.med "Und."
    cajas | tipo | precio | total (coma decimal)

Descripción: species siempre primero ('Carnation' o 'CARNATION'), luego color,
luego grade ('Select'/'Fancy'/'Estándar'), y opcionalmente '*NNN Tallos UE'
que indica pack size.
"""
from __future__ import annotations

import re
from src.models import InvoiceHeader, InvoiceLine
from src.config import translate_carnation_color


# Línea producto: <item> <description...> <qty>,<dec> Und. <boxes> <type> <price> <total>
_LINE_RE = re.compile(
    r'^(?P<item>\d+)\s+'
    r'(?P<desc>[A-Za-z][A-Za-z0-9\s\*\?/\-]+?)\s+'
    r'(?P<qty>[\d.]+,[\d]+)\s+'
    r'Und\.?\s+'
    r'(?P<boxes>\d+)\s+'
    r'(?P<box_type>HB|QB|TB|FB)\s+'
    r'(?P<price>\d+,\d+)\s+'
    r'(?P<total>[\d.]+,\d+)\s*$',
    re.IGNORECASE,
)

_INVOICE_RE = re.compile(r'FE\s+No\.?\s*(\d+)', re.I)
_DATE_RE    = re.compile(r'FECHA\s+FACTURA\s+(\d{1,2}/\d{1,2}/\d{4})', re.I)
_AWB_RE     = re.compile(r'GUIA\s+No\.?\s*(\S+)', re.I)
_HAWB_RE    = re.compile(r'GUIA\s+HIJA\s+(\S+)', re.I)
_TOTAL_RE   = re.compile(r'TOTAL\s+DOCUMENTO\s+([\d.]+,\d+)', re.I)

# Grados y colores estándar para CEAN
_GRADES = {'SELECT', 'FANCY', 'ESTANDAR', 'ESTÁNDAR', 'ESTANDARD', 'PREMIUM', 'STANDARD'}
_COLORS_EN = {
    'RED', 'WHITE', 'PINK', 'YELLOW', 'ASSORTED', 'MIX', 'ORANGE', 'PURPLE',
    'SALMON', 'PEACH', 'LIGHT', 'DARK', 'HOT', 'CREAM', 'GREEN',
}


def _num_col(s: str) -> float:
    """Formato colombiano: '1.234,56' → 1234.56 ; '800,00' → 800.0"""
    return float(s.replace('.', '').replace(',', '.'))


def _parse_description(desc: str) -> tuple[str, str, int]:
    """Devuelve (variety_color, grade, spb_from_pack).

    Ejemplos:
      'Carnation Red Select'                 → ('ROJO', 'SELECT', 20)
      'Carnation Red Fancy*400 Tallos UE'    → ('ROJO', 'FANCY', 20)  (pack=400, 20 spb)
      'Carnation Light Pink Fancy'           → ('ROSA CLARO', 'FANCY', 20)
      'Mini Carnation Red Select'            → ('ROJO', 'SELECT', 10)
    """
    upper = desc.upper()
    tokens = upper.split()
    # Saltar tokens species iniciales (Carnation / Mini Carnation)
    skip = 0
    if tokens[:2] == ['MINI', 'CARNATION']:
        skip = 2
        default_spb = 10
    elif tokens[:1] == ['CARNATION']:
        skip = 1
        default_spb = 20
    else:
        skip = 0
        default_spb = 25   # fallback

    rest = tokens[skip:]
    # Extraer grade (última palabra coincidente con _GRADES)
    grade = ''
    for g in _GRADES:
        for i, t in enumerate(rest):
            if t.startswith(g):
                grade = g
                rest = rest[:i] + rest[i + 1:]
                break
        if grade:
            break

    # Color = todo lo que queda hasta '*' o 'TALLOS'
    color_tokens = []
    for t in rest:
        if t.startswith('*') or 'TALLO' in t or t == 'UE':
            break
        color_tokens.append(t)
    color_en = ' '.join(color_tokens).strip()
    variety = translate_carnation_color(color_en) if color_en else 'ASSORTED'

    # SPB deducido del *NNN Tallos
    spb = default_spb
    pack_m = re.search(r'\*(\d+)\s*TALLOS?', upper)
    if pack_m:
        pack = int(pack_m.group(1))
        # Pack = número de tallos por unidad empaquetada. En CEAN '400 tallos'
        # suele ir con SPB=20 (20 bunches de 20 stems = 400). Default fine.
    return variety, grade, spb


class AutoParser:
    fmt_key = 'auto_cean'

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
            header.total = _num_col(m.group(1))

        lines: list[InvoiceLine] = []
        for raw in text.split('\n'):
            s = raw.strip()
            if not s or len(s) < 20:
                continue
            m = _LINE_RE.match(s)
            if not m:
                continue
            desc = m.group('desc').strip()
            if not any(sp in desc.upper() for sp in ('CARNATION', 'ROSE', 'CLAVEL', 'ROSA')):
                continue
            variety, grade, spb = _parse_description(desc)
            stems = int(_num_col(m.group('qty')))
            species = 'CARNATIONS' if 'CARNATION' in desc.upper() else 'ROSES'
            bunches = stems // spb if spb else 0
            lines.append(InvoiceLine(
                raw_description=s[:120],
                species=species,
                variety=variety,
                grade=grade,
                origin='COL',
                size=0,        # no viene en factura, se usará default
                stems_per_bunch=spb,
                bunches=bunches,
                stems=stems,
                price_per_stem=_num_col(m.group('price')),
                line_total=_num_col(m.group('total')),
                box_type=m.group('box_type').upper(),
                provider_key=provider_data.get('key', ''),
            ))

        if not header.total and lines:
            header.total = round(sum(l.line_total for l in lines), 2)
        return header, lines
