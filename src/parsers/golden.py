from __future__ import annotations

import re

from src.models import InvoiceHeader, InvoiceLine


class GoldenParser:
    """
    Benchmark Growers SAS (Golden) -- Claveles y Miniclaveles.
    Formato: N H/Q Un/Box TotStems ItemDescription Grade/Color [BoxID] [ItemCode] Price Total
    - Grade/Color mezcla ruta (R45, PUERTO...) + color abreviado (WH, RD, MIX...)
    - Lineas con 2+ colores se dividen en sublineas (50/50)
    - Articulos en BD: "CLAVEL FANCY {COLOR} 70CM 20U GOLDEN"
    """
    _LABELS = {'PUERTO','ASTURIAS','BARRAL','PYTI','DANI','GIJON','CRISTIAN'}
    _COLOR_MAP = {
        'WH':'BLANCO','WHITE':'BLANCO','BLANCO':'BLANCO',
        'RD':'ROJO','RED':'ROJO','ROJO':'ROJO',
        'PK':'ROSA','PINK':'ROSA','ROSA':'ROSA',
        'YW':'AMARILLO','YELLOW':'AMARILLO','AMARILLO':'AMARILLO',
        'GR':'VERDE','GREEN':'VERDE','VERDE':'VERDE',
        'OR':'NARANJA','ORANGE':'NARANJA','NARANJA':'NARANJA',
        'PU':'MORADO','PURPLE':'MORADO','MORADO':'MORADO',
        'BIC':'BICOLOR','BICOL':'BICOLOR','BICOLORES':'BICOLOR','BICOLOR':'BICOLOR',
        'NOV':'NOVEDADES','NOVEDADES':'NOVEDADES',
    }
    _SKIP = {'FCY','FANCY','CARN','CARNATION','MINI','MCAT','AST','CB','MC','S2','AT','X',
             'BUNCH','CONSUMER','ASSORTED','MINICARNS'}

    def _parse_grade_color(self, field:str):
        """Retorna (label, [colores_en_espanol]) del campo Grade/Color de Benchmark."""
        field = re.sub(r'(?<!\w)R-(\d+)', r'R\1', field.upper())
        tokens = re.split(r'[\s/]+', field)
        label = ''; colors = []
        for tok in tokens:
            tok = tok.strip('+- ')
            if not tok: continue
            rm = re.match(r'^R(\d+)$', tok)
            if rm: label = 'R' + rm.group(1); continue
            if tok in self._LABELS: label = tok; continue
            if tok in ('MIX','MIXED'): continue   # indicador; los colores vienen despues
            if tok in self._SKIP: continue
            if tok in self._COLOR_MAP:
                c = self._COLOR_MAP[tok]
                if c not in colors: colors.append(c)
                continue
        if not colors: colors = ['MIXTO']
        return label, colors

    def _parse_invoice_line(self, ln:str):
        """Parsea una linea de factura anclando en el campo Item Description fijo.
        FIX: también captura SPIDER, MUM BALL, SUPER MUMS, CONSUMER BUNCH MUM.
        """
        desc_m = re.search(
            r'(CONSUMER\s+BUNCH\s+CARNATION\s+(?:FANCY|SELEC\w*)'
            r'|CONSUMER\s+BUNCH\s+MUM\s+BALL\s+\w+'   # CONSUMER BUNCH MUM BALL VERDILUGO
            r'|SUPER\s+MUMS\s+\w+'                     # SUPER MUMS WHITE
            r'|MUM\s+BALL\s+\w+'                        # MUM BALL GREEN
            r'|CREMON\s+\w+'                            # CREMON GREEN/CREAM/ASSORTED
            r'|MINICARNS\s+ASSORTED|SPIDER\s+\w+|ALSTRO\s+\w+\s+\w+)', ln, re.I)
        if not desc_m: return None
        item_desc = desc_m.group(1).upper()
        before = ln[:desc_m.start()].strip()
        after  = ln[desc_m.end():].strip()
        bm = re.match(r'(\d+)\s+(H|Q)\s+(\d+)\s+(\d+)', before)
        if not bm: return None
        btype = bm.group(2).upper()
        upb   = int(bm.group(3))
        stems = int(bm.group(4))
        price_m = re.search(r'([\d.]+)\s+([\d.]+)\s*$', after)
        if not price_m: return None
        try: price=float(price_m.group(1)); total=float(price_m.group(2))
        except: return None
        grade_color = after[:price_m.start()].strip()
        ic_m = re.search(r'\b(CB|MC)\s+\S+\s*$', grade_color, re.I)
        if ic_m: grade_color = grade_color[:ic_m.start()].strip()
        return {'btype':btype,'upb':upb,'stems':stems,
                'item_desc':item_desc,'grade_color':grade_color,
                'price_per_stem':price,'total':total}

    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'INVOICE\s+No\.?\s*(\d+)',text,re.I);       h.invoice_number=m.group(1) if m else ''
        m=re.search(r'INVOICE\s+DATE\s+([\d/]+)',text,re.I);     h.date=m.group(1) if m else ''
        m=re.search(r'MAWB\s+No\.?\s*([\d\-]+)',text,re.I);      h.awb=re.sub(r'\s+','',m.group(1)) if m else ''
        m=re.search(r'HAWB\s+No\.?\s*([\d\-]+)',text,re.I);      h.hawb=re.sub(r'\s+','',m.group(1)) if m else ''
        m=re.search(r'Ship\s+Date\s+([\d/]+)',text,re.I);        # ship date (no campo en header, ignorar)
        try:
            m=re.search(r'TOTAL\s+([\d,]+\.\d+)',text,re.I); h.total=float(m.group(1).replace(',','')) if m else 0.0
        except: h.total=0.0
        lines=[]
        for ln in text.split('\n'):
            ln=ln.strip()
            if not ln: continue
            parsed=self._parse_invoice_line(ln)
            if not parsed: continue
            is_mini='MINICARNS' in parsed['item_desc']
            is_spider='SPIDER' in parsed['item_desc']
            is_alstro='ALSTRO' in parsed['item_desc']
            is_mum=('MUM' in parsed['item_desc'] or 'CREMON' in parsed['item_desc']) and 'CARNATION' not in parsed['item_desc']
            is_selec='SELEC' in parsed['item_desc'] and 'FANCY' not in parsed['item_desc']
            stems_total=parsed['stems']; total=parsed['total']; price=parsed['price_per_stem']
            btype=parsed['btype']
            if is_alstro:
                sp='ALSTROEMERIA'
                spb=10
                label, colors = self._parse_grade_color(parsed['grade_color'])
                var_name = colors[0] if colors[0] != 'MIXTO' else 'MIXTO'
                il=InvoiceLine(raw_description=ln,species=sp,variety=var_name,grade='SELECT',origin='COL',
                               size=0,stems_per_bunch=spb,stems=stems_total,price_per_stem=price,
                               line_total=total,box_type=btype,label=label,provider_key='golden')
                lines.append(il)
                continue
            if is_mum:
                sp='CHRYSANTHEMUM'
                spb=10
                label, colors = self._parse_grade_color(parsed['grade_color'])
                # MUM/CREMON variety from item_desc
                mum_desc = parsed['item_desc']
                mum_desc = re.sub(r'^CONSUMER\s+BUNCH\s+', '', mum_desc)
                var_name = mum_desc
                il=InvoiceLine(raw_description=ln,species=sp,variety=var_name,grade='',origin='COL',
                               size=0,stems_per_bunch=spb,stems=stems_total,price_per_stem=price,
                               line_total=total,box_type=btype,label=label,provider_key='golden')
                lines.append(il)
                continue
            if is_spider:
                sp='CHRYSANTHEMUM'
                spb=10
            else:
                sp='CARNATIONS'
                spb=10 if is_mini else 20   # 10U miniclavel, 20U clavel fancy
            label, colors = self._parse_grade_color(parsed['grade_color'])

            # FIX: para SPIDER, usar tipo + color del grade_color como variedad
            if is_spider:
                spider_desc = parsed['item_desc'].replace('SPIDER','').strip()
                spider_color = colors[0] if colors[0] != 'MIXTO' else spider_desc.upper()
                var_name = f"SP SPIDER {spider_color}"
                il=InvoiceLine(raw_description=ln,species=sp,variety=var_name,grade='',origin='COL',
                               size=0,stems_per_bunch=spb,stems=stems_total,price_per_stem=price,
                               line_total=total,box_type=btype,label=label,provider_key='golden')
                lines.append(il)
                continue

            grade = 'SELECT' if is_selec else 'FANCY'
            n=len(colors)
            if n<=1:
                il=InvoiceLine(raw_description=ln,species=sp,variety=colors[0],grade=grade,origin='COL',
                               size=70,stems_per_bunch=spb,stems=stems_total,price_per_stem=price,
                               line_total=total,box_type=btype,label=label,provider_key='golden')
                lines.append(il)
            else:
                base=stems_total//n
                for i,color in enumerate(colors):
                    st=base if i<n-1 else stems_total-base*(n-1)
                    lt=round(st*price,2)
                    il=InvoiceLine(raw_description=ln,species=sp,variety=color,grade=grade,origin='COL',
                                   size=70,stems_per_bunch=spb,stems=st,price_per_stem=price,
                                   line_total=lt,box_type=btype,label=label,provider_key='golden')
                    lines.append(il)
        return h, lines
