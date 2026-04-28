from __future__ import annotations

import re

from src.models import InvoiceHeader, InvoiceLine


# Línea con solo el box_type (HBS, HBXL, QB, HB, FB, EB, TB).
# En ECOFLOR el box_type vive en su propia línea y aplica al siguiente
# bloque de datos (puede haber sub-líneas en cajas mixtas heredando el
# mismo btype).
_BTYPE_RE = re.compile(r'^\s*(HBS|HBXL|QB|HB|FB|EB|TB)\s*$')

# Dimensiones físicas de la caja: "(110.0*30.0*30.0)" o "(105.0*27.0*16.0)".
# Aparecen tras cada línea de datos, hay que saltarlas.
_DIM_RE = re.compile(r'^\s*\([\d.]+\*[\d.]+\*[\d.]+\)\s*$')

# Resumen final: "TOTAL 78 1950 565,500".
_TOTAL_SUMMARY_RE = re.compile(r'^\s*TOTAL\s+\d+\s+\d+\s+[\d,.]+\s*$')

# Layout NUEVO 2026 (btype en línea propia):
#   "1 MONDIAL 50 12 25 300 0,290 87,000"
#   "VENDELA 60 1 25 25 0,290 7,250"   ← sub-línea sin box_n (caja mixta)
# Columnas: [BOX_N?] VARIETY LENGTH QTY STEMS_PER_BUNCH TOTAL_STEMS PRICE TOTAL
_LINE_RE_NEW = re.compile(
    r'^\s*(?:(?P<box_n>\d+)\s+)?'
    r"(?P<variety>[A-ZÑÁÉÍÓÚ�][A-ZÑÁÉÍÓÚ0-9 \-\.'/&�]*?)\s+"
    r'(?P<length>\d{2,3})\s+'
    r'(?P<qty>\d+)\s+'
    r'(?P<spb>\d+)\s+'
    r'(?P<total_stems>\d+)\s+'
    r'(?P<price>[\d,.]+)\s+'
    r'(?P<total>[\d,.]+)\s*$'
)

# Layout VIEJO (btype inline H/Q antes de variety, distinto orden columnar):
#   "1 H MONDIAL 12 25 50 300 0,290 87,000"
#   "Q CAFÉ DEL MAR 3 25 50 75 0,500 37,500"   ← sub-línea sin box_n
# Cabecera: BOX TB Box_codeVARIETY CAN BUNCHES LENGT STEMS PRICE/UNIT TOTAL
# Columnas: [BOX_N?] BTYPE VARIETY QTY SPB LENGTH TOTAL_STEMS PRICE TOTAL
_LINE_RE_OLD = re.compile(
    r'^\s*(?:(?P<box_n>\d+)\s+)?'
    r'(?P<btype>[HQ])\s+'
    r"(?P<variety>[A-ZÑÁÉÍÓÚ�][A-ZÑÁÉÍÓÚ0-9 \-\.'/&�]*?)\s+"
    r'(?P<qty>\d+)\s+'
    r'(?P<spb>\d+)\s+'
    r'(?P<length>\d{2,3})\s+'
    r'(?P<total_stems>\d+)\s+'
    r'(?P<price>[\d,.]+)\s+'
    r'(?P<total>[\d,.]+)\s*$',
    re.I
)


def _num(s: str) -> float:
    """ECOFLOR usa coma decimal: '0,290' → 0.29; '87,000' → 87.0.
    Si llega un valor con punto decimal lo respeta. Mixtos resuelve por
    último separador.
    """
    s = s.strip()
    if not s:
        return 0.0
    if ',' in s and '.' not in s:
        return float(s.replace(',', '.'))
    if '.' in s and ',' not in s:
        return float(s)
    if s.rfind(',') > s.rfind('.'):
        return float(s.replace('.', '').replace(',', '.'))
    return float(s.replace(',', ''))


def _species_from_variety(variety: str) -> str:
    v = variety.upper()
    if 'GYP' in v:
        return 'GYPSOPHILA'
    if 'HYDRANGEA' in v:
        return 'HYDRANGEAS'
    if 'ALSTROEMERIA' in v:
        return 'ALSTROEMERIA'
    return 'ROSES'


class EcoflorParser:
    """ECOFLOR GROUPCHILE — layout 2026 con box_type en línea propia.

    Estructura por caja (3 líneas):
        HBS
        1 MONDIAL 50 12 25 300 0,290 87,000
        (110.0*30.0*30.0)

    Sub-líneas de caja mixta omiten el box_n y heredan el btype del HBS
    previo:
        HBS
        VENDELA 60 1 25 25 0,290 7,250
        (110.0*30.0*30.0)

    Columnas tabulares: Box_N° | Box_Type | Box_code | VARIETY | Length |
    Qty | Stems | Total_Stems | Price/Stem | TOTAL.
    Box_code falta en este layout — el parser lo deja vacío.
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
        m = re.search(r'A\.W\.B\.?\s*N[º\xba\s�]*[:\s]*([\d\-]+)', text, re.I)
        h.awb = re.sub(r'\s+', '', m.group(1)) if m else ''
        try:
            m = re.search(r'Total Invoice USD\s*\$?\s*([\d,.]+)', text, re.I)
            h.total = _num(m.group(1)) if m else 0.0
        except Exception:
            h.total = 0.0

        lines: list[InvoiceLine] = []
        current_btype = ''

        for raw in text.split('\n'):
            ln = raw.strip()
            if not ln:
                continue
            if _DIM_RE.match(ln) or _TOTAL_SUMMARY_RE.match(ln):
                continue
            mb = _BTYPE_RE.match(ln)
            if mb:
                current_btype = mb.group(1)
                continue
            # Probar primero el layout viejo (btype inline) — es más restrictivo.
            # Si falla, layout nuevo.
            btype_for_line = current_btype
            pm = _LINE_RE_OLD.match(ln)
            if pm:
                btype_for_line = pm.group('btype').upper()
            else:
                pm = _LINE_RE_NEW.match(ln)
                if not pm:
                    continue
            try:
                size = int(pm.group('length'))
                qty = int(pm.group('qty'))
                spb = int(pm.group('spb'))
                stems = int(pm.group('total_stems'))
                price = _num(pm.group('price'))
                total = _num(pm.group('total'))
            except (ValueError, TypeError):
                continue
            # Coherencia: total_stems ≈ qty * spb (tolerancia 5% o ±2).
            # Filtra falsos positivos como cabeceras "Length Qty ...".
            if qty and spb and abs(qty * spb - stems) > max(2, stems * 0.05):
                continue
            variety = pm.group('variety').strip().upper()
            if not variety or len(variety) < 2:
                continue
            species = _species_from_variety(variety)
            lines.append(InvoiceLine(
                raw_description=raw,
                species=species,
                variety=variety,
                origin='EC',
                size=size,
                stems_per_bunch=spb,
                bunches=qty,
                stems=stems,
                price_per_stem=price,
                price_per_bunch=round(price * spb, 4) if spb else 0.0,
                line_total=total,
                box_type=btype_for_line,
                provider_key=pdata.get('key', ''),
            ))

        if not h.total and lines:
            h.total = round(sum(l.line_total for l in lines), 2)
        return h, lines
