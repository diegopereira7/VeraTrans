from __future__ import annotations

import re

from src.models import InvoiceHeader, InvoiceLine


class LatinParser:
    """
    Latin Flowers Farms SAS CI -- Hortensias (id_proveedor=6323).
    Articulos en BD: "HYDRANGEA {GRADO} {COLOR_ES} 60CM 1U LATIN"
    Siempre 1U en VeraBuy, independientemente del bunch en la factura.
    """
    _COLOR_MAP = {
        'DARK GREEN':'VERDE OSCURO','LIGHT PINK':'ROSA CLARO','DUSTY PINK':'ROSA VIEJO',
        'PINK BLUSH':'ROSA','LIGHT PEACH':'MELOCOTON','LIGHT MOCCA':'MOCCA',
        'LIGHT BLUE':'AZUL CLARO','BLUE BOGOTANA':'AZUL CRIOLLA','BLUE CRIOLLA':'AZUL CRIOLLA',
        'WHITE':'BLANCO','BLUE':'AZUL','RED':'ROJO','PINK':'ROSA','GREEN':'VERDE',
        'MIX':'MIXTO','PEACH':'MELOCOTON','SALMON':'SALMON','BURGUNDY':'GRANATE',
    }

    def _map_color(self, color_en:str) -> str:
        for en, es in sorted(self._COLOR_MAP.items(), key=lambda x:-len(x[0])):
            if color_en == en or color_en.startswith(en):
                return es
        return color_en

    def _translate_variety(self, desc:str) -> str:
        """Convierte descripcion raw en variedad VeraBuy (porcion tras 'HYDRANGEA ')."""
        d = desc.upper().strip()
        d = re.sub(r'^HYDRANGEA\s+', '', d)
        d = re.sub(r'\s*-\s*VERALEZA\b.*$', '', d)
        d = re.sub(r'\s+PREMIUM\s*$', '', d)
        if d.startswith('MIX'):
            return 'PREMIUM MIXTO'
        is_tinted = d.startswith('TINTED')
        if is_tinted: d = re.sub(r'^TINTED\s+', '', d)
        if d.startswith('EMERALD'):
            return 'EMERALD BICOLOR'
        if d.startswith('ANTIQUE'):
            d = re.sub(r'^ANTIQUE\s+', '', d).strip()
            return f"ANTIQUE {self._map_color(d)}"
        grado = 'PREMIUM TENIDA' if is_tinted else 'PREMIUM'
        return f"{grado} {self._map_color(d.strip())}"

    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'LF(\d+)',text,re.I);                      h.invoice_number='LF'+m.group(1) if m else ''
        m=re.search(r'Date\s+([\d\-]+)',text,re.I);             h.date=m.group(1) if m else ''
        m=re.search(r'AWB\s+No\.?\s*([\d]+)',text,re.I);        h.awb=re.sub(r'\s+','',m.group(1)) if m else ''
        m=re.search(r'HAWB[:\s]+(ECM\d+)',text,re.I);           h.hawb=m.group(1) if m else ''
        try:
            m=re.search(r'Total\s+USD\s*([\d,]+\.\d+)',text,re.I); h.total=float(m.group(1).replace(',','')) if m else 0.0
        except: h.total=0.0
        lines=[]
        for ln in text.split('\n'):
            ln=ln.strip()
            # Format A (old): "1 QB HYDRANGEA ..."
            pm=re.search(r'(\d+)\s+(QB|HB)\s+(HYDRANGEA\s+[A-Z][A-Z\s.\-]+?)\s+\w+\s+\d{4}\w*\s+(\d+)\s+(\d+)\s+([\d.]+)',ln,re.I)
            # Format B: "0.250 1.00QBx35 HYDRANGEA VARIETY 0603... DELEG STEMS stem STEMS PRICE TOTAL"
            # Algunos PDFs usan coma decimal ("0,250 1,00QBx35"); [\d.,]+ cubre ambos.
            if not pm:
                pm=re.search(
                    r'[\d.,]+\s*'                            # BXS (0.250 / 0,250)
                    r'[\d.,]+\s*'                            # PCS (1.00 / 1,00)
                    r'(QB|HB)x(\d+)\s+'                      # QBx35 → box_type + stems_per_box
                    r'(HYDRANGEA\s+[A-Z][A-Z\s.\-/]+?)\s+'   # HYDRANGEA + variety
                    r'(\d{10})\s+'                            # HTS tariff (10 digits)
                    r'(.+?)\s+'                               # DELEGACION (variable)
                    r'(\d+)\s+stem\s+'                        # first stems count
                    r'(\d+)\s+'                               # total stems
                    r'([\d.,]+)\s+'                           # price (0.58 / 0,58)
                    r'([\d.,]+)',                             # total (20.30 / 20,30)
                    ln, re.I)
                if pm:
                    btype = pm.group(1).upper()
                    desc = pm.group(3).strip().upper()
                    deleg = pm.group(5).strip()
                    stems = int(pm.group(7))
                    try:
                        pps = float(pm.group(8).replace(',', '.'))
                        total_val = float(pm.group(9).replace(',', '.'))
                    except: pps = 0.0; total_val = 0.0
                    label = re.sub(r'\s*-?\s*S\.?O\.?\s*$', '', deleg).strip()
                    label = re.sub(r'\s*-\s*$', '', label).strip()
                    variety = self._translate_variety(desc)
                    il = InvoiceLine(raw_description=ln, species='HYDRANGEAS', variety=variety, origin='COL',
                                     size=60, stems_per_bunch=1, stems=stems, price_per_stem=pps,
                                     line_total=total_val, box_type=btype, label=label, provider_key='latin')
                    lines.append(il)
                    continue
            # Format C: QBH lines — two column-order variants in the same PDF.
            # Both share: N QBH HYDRANGEA DESC ... 0603190125 ...
            # Strategy: capture description before tariff, then extract totals from the
            # numeric tokens scattered around ATPDEA and PO labels.
            if not pm:
                pm_c = re.search(
                    r'(\d+)\s+(QBH|QBM|HBH|QB)\s*'            # boxes + box_type (space optional for QBHHYDRANGEA)
                    r'(HYDRANGEA\s+.+?)\s+'                    # description
                    r'(?:ATPDEA\s+)?'                          # optional ATPDEA before tariff
                    r'(0603\d{6})',                             # HTS tariff
                    ln, re.I)
                if pm_c:
                    btype = 'QB'
                    desc = pm_c.group(3).strip().upper()
                    desc = re.sub(r'\s*(?:ATPDEA|PREMIUM[-\s]*VERALEZA|PREMIUM)\s*$', '', desc).strip()
                    desc = 'HYDRANGEA ' + re.sub(r'^HYDRANGEA\s+', '', desc)
                    # Extract all decimal numbers from the line after the tariff
                    after_tariff = ln[pm_c.end():]
                    nums = re.findall(r'\d+\.\d+|\d+', after_tariff)
                    # Find total: the largest number that looks like a dollar amount (>5.0)
                    # Find price: a number with 3 decimals like 0.550, 0.600
                    # Find stems: an integer (35, 70, 175...)
                    stems = 0; pps = 0.0; total_val = 0.0
                    for n in nums:
                        v = float(n)
                        if '.' in n and len(n.split('.')[1]) == 3 and 0.1 < v < 5.0:
                            pps = v  # price per stem (0.550, 0.600, etc.)
                    # Total = last large number; stems = first integer > 4
                    int_nums = [int(float(n)) for n in nums if float(n) == int(float(n)) and float(n) > 0]
                    float_nums = [float(n) for n in nums if float(n) > 5.0]
                    if float_nums:
                        total_val = float_nums[-1]  # last large float = total
                    if int_nums:
                        stems = int_nums[0]  # first integer = stems
                    if pps == 0.0 and stems > 0 and total_val > 0:
                        pps = total_val / stems
                    # Extract label from PO fields
                    label_parts = re.findall(r'([A-Z][A-Z\s]*?)-?\s*S\.?O\.?', after_tariff, re.I)
                    label = label_parts[0].strip().rstrip('-').strip() if label_parts else ''
                    variety = self._translate_variety(desc)
                    il = InvoiceLine(raw_description=ln, species='HYDRANGEAS', variety=variety, origin='COL',
                                     size=60, stems_per_bunch=1, stems=stems, price_per_stem=pps,
                                     line_total=total_val, box_type=btype, label=label, provider_key='latin')
                    lines.append(il)
                    continue
            if not pm: continue
            btype=pm.group(2).upper()
            desc=pm.group(3).strip().upper()
            stems=int(pm.group(5))
            try: pps=float(pm.group(6))
            except: pps=0.0
            total=round(pps*stems,2)
            before=ln[:pm.start()].strip()
            label=re.sub(r'\s*-?\s*S\.?O\.?\s*$','',before).strip() if before else ''
            variety=self._translate_variety(desc)
            il=InvoiceLine(raw_description=ln,species='HYDRANGEAS',variety=variety,origin='COL',
                           size=60,stems_per_bunch=1,stems=stems,price_per_stem=pps,
                           line_total=total,box_type=btype,label=label,provider_key='latin')
            lines.append(il)
        return h, lines
