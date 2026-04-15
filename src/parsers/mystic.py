from __future__ import annotations

import re

from src.models import InvoiceHeader, InvoiceLine


# Block/farm names que aparecen entre box_code y variety en MYSTIC
# (R19 SORIALES BRIGHTON, R19 IGLESIAS EXPLORER, etc.)
_BLOCK_NAMES = {'SORIALES', 'IGLESIAS', 'NAVARRETE'}

# Línea con los 6 campos finales fijos: peso cantidad length stems price total.
# Soporta box_code con dígitos (R14, R19, VNG, FR), variedad mixed-case y
# bloque opcional antes de variety.
_LINE_RE = re.compile(
    r'^(?:\s*\d+\s+)?(?P<btype>[HQ])\s+'
    r'(?P<code>[A-Z][A-Z0-9]{0,14})\s+'
    r'(?P<variety>.+?)\s+'
    r'(?P<peso>\d+)\s+(?P<cantidad>\d+)\s+(?P<length>\d+)\s+(?P<stems>\d+)\s+'
    r'(?P<price>[\d,.]+)\s+(?P<total>[\d,.]+)\s*$'
)

# Fallback sin box_code (ej. STAMPSYBOX: "1 H NECTARINE 4 25 50 100 0,300 30,000")
_LINE_RE_NOCODE = re.compile(
    r'^(?:\s*\d+\s+)?(?P<btype>[HQ])\s+'
    r'(?P<variety>[A-Z][A-Z0-9\s\-\.\'/&]+?)\s+'
    r'(?P<peso>\d+)\s+(?P<cantidad>\d+)\s+(?P<length>\d+)\s+(?P<stems>\d+)\s+'
    r'(?P<price>[\d,.]+)\s+(?P<total>[\d,.]+)\s*$'
)


def _num(s: str) -> float:
    s = s.replace('.', '').replace(',', '.') if ',' in s else s
    try:
        return float(s)
    except ValueError:
        return 0.0


def _species_from_variety(variety: str) -> str:
    v = variety.upper()
    if 'GYP' in v or 'GYPS' in v:
        return 'GYPSOPHILA'
    if 'HYDRANGEA' in v:
        return 'HYDRANGEAS'
    if 'ALSTROEMERIA' in v:
        return 'ALSTROEMERIA'
    return 'ROSES'


def _clean_variety(v: str) -> str:
    tokens = v.strip().split()
    # Quitar bloque inicial (SORIALES, IGLESIAS, etc.)
    while tokens and tokens[0].upper() in _BLOCK_NAMES:
        tokens = tokens[1:]
    # Quitar sufijo "N/A"
    while tokens and tokens[-1].upper() in ('N/A', 'NA'):
        tokens = tokens[:-1]
    return ' '.join(tokens).strip().upper()


class MysticParser:
    """MYSTIC FLOWERS y variantes (Fiorentina, Stampsy) — layout:
        [BOX_N°] TB [BOX_CODE] [BLOCK?] VARIETY PESO CANTIDAD LENGT STEMS PRICE TOTAL
    Box_code puede contener dígitos (R14, R19). Block opcional (SORIALES, IGLESIAS).
    Variedad mixed-case y puede incluir sufijo N/A.
    """

    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']
        h.provider_id = pdata['id']
        h.provider_name = pdata['name']
        m = re.search(r'INVOICE\s+#\s*(\S+)', text, re.I)
        h.invoice_number = m.group(1) if m else ''
        m = re.search(r'Date\s*:\s*([\d/]+)', text, re.I)
        h.date = m.group(1) if m else ''
        m = re.search(r'A\.W\.B\.?\s*N[o\xba\s]*[:\s]*([\d\-]+)', text, re.I)
        h.awb = re.sub(r'\s+', '', m.group(1)) if m else ''
        try:
            m = re.search(r'Total Invoice USD\s*\$?\s*([\d,.]+)', text, re.I)
            h.total = float(m.group(1).replace(',', '')) if m else 0.0
        except Exception:
            h.total = 0.0

        lines: list[InvoiceLine] = []
        for raw in text.split('\n'):
            ln = raw.strip()
            if not ln or 'TOTAL' in ln[:10] or 'BOX' in ln[:5] and 'VARIETY' in ln:
                continue
            pm = _LINE_RE.match(ln) or _LINE_RE_NOCODE.match(ln)
            if not pm:
                continue
            try:
                cantidad = int(pm.group('cantidad'))  # CANTIDAD/CANTID = tallos por ramo (SPB)
                peso = int(pm.group('peso'))          # PESO = n ramos
                size = int(pm.group('length'))
                stems = int(pm.group('stems'))
                price = _num(pm.group('price'))
                total = _num(pm.group('total'))
            except (ValueError, TypeError):
                continue
            variety = _clean_variety(pm.group('variety'))
            if not variety:
                continue
            species = _species_from_variety(variety)
            spb = cantidad if cantidad > 0 else (25 if species == 'ROSES' else 1)
            bunches = peso if peso > 0 else (stems // spb if spb else 0)
            lines.append(InvoiceLine(
                raw_description=raw,
                species=species,
                variety=variety,
                origin='EC',
                size=size,
                stems_per_bunch=spb,
                bunches=bunches,
                stems=stems,
                price_per_stem=price,
                line_total=total,
                box_type=pm.group('btype'),
                provider_key=pdata.get('key', ''),
            ))

        if not h.total and lines:
            h.total = round(sum(l.line_total for l in lines), 2)
        return h, lines
