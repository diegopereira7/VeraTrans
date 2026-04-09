from __future__ import annotations

import re

from src.models import InvoiceHeader, InvoiceLine


class MysticParser:
    """BOX TB [Box_code] VARIETY CAN/CANTID BUNCHES/BUNCHE LENGT STEMS PRICE/UNIT TOTAL
    - Box_code puede estar ausente (Fiorentina, Stampsy)
    - CAN = n ramos en la caja; BUNCHES = tallos por ramo (U); LENGT = tamano CM
    - Algunas lineas llevan la variedad en la linea anterior (carry-forward)
    """
    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'INVOICE\s+#\s*(\S+)',text,re.I); h.invoice_number=m.group(1) if m else ''
        m=re.search(r'Date\s*:\s*([\d/]+)',text,re.I); h.date=m.group(1) if m else ''
        m=re.search(r'A\.W\.B\.?\s*N[o\xba\s]*[:\s]*([\d\-]+)',text,re.I); h.awb=re.sub(r'\s+','',m.group(1)) if m else ''
        try:
            m=re.search(r'Total Invoice USD\s*\$?\s*([\d,.]+)',text,re.I)
            h.total=float(m.group(1).replace(',','')) if m else 0.0
        except: h.total=0.0
        lines=[]
        current_variety=''
        for ln in text.split('\n'):
            raw=ln; ln=ln.strip()
            # Patron A: con codigo de caja corto (Mystic: "H VNG VARIETY CAN BUNCHES LENGT STEMS PRICE")
            # [A-Z]{2,5} no captura -- solo casa con codigos tipo "VNG", no con palabras como "ORANGE"
            # FIX: [A-Za-z] para aceptar variedades mixed-case (Florifrut: "Frutteto", "Brighton")
            pm=re.search(r'\b(H|Q)\b\s+[A-Z]{2,5}\s+([A-Za-z][A-Za-z\s.\-/&]+?)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d,.]+)',ln)
            if not pm:
                # Patron B: sin codigo de caja (Fiorentina, Stampsy)
                pm=re.search(r'\b(H|Q)\b\s+([A-Za-z][A-Za-z\s.\-/&]+?)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d,.]+)',ln)
            if pm:
                btype=pm.group(1); current_variety=pm.group(2).strip()
                try:
                    bunches=int(pm.group(3))  # CAN/CANTID = n ramos
                    spb=int(pm.group(4))       # BUNCHES/BUNCHE = tallos por ramo (U)
                    sz=int(pm.group(5))        # LENGT = tamano CM
                    stems=int(pm.group(6))     # STEMS = total tallos
                    price=float(pm.group(7).replace(',','.'))
                except: continue
                total=price*stems
                il=InvoiceLine(raw_description=raw,species='ROSES',variety=current_variety,
                               size=sz,stems_per_bunch=spb,bunches=bunches,stems=stems,
                               price_per_stem=price,line_total=total,box_type=btype)
                lines.append(il); continue
            # Carry-forward: linea H/Q con numeros pero sin variedad (variedad en linea anterior)
            pm2=re.search(r'\b(H|Q)\b\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d,.]+)',ln)
            if pm2 and current_variety:
                btype=pm2.group(1)
                try:
                    bunches=int(pm2.group(2)); spb=int(pm2.group(3))
                    sz=int(pm2.group(4)); stems=int(pm2.group(5))
                    price=float(pm2.group(6).replace(',','.'))
                except: continue
                total=price*stems
                il=InvoiceLine(raw_description=raw,species='ROSES',variety=current_variety,
                               size=sz,stems_per_bunch=spb,bunches=bunches,stems=stems,
                               price_per_stem=price,line_total=total,box_type=btype)
                lines.append(il); continue
            # Linea solo con variedad (antes de la linea de numeros)
            # Requiere sangria inicial -- asi excluimos cabeceras tipo "BOX TB Box code..."
            vm=re.match(r'^\s{5,}([A-Z][A-Z .\-/]+[A-Z.])\s{5,}',raw)
            if vm: current_variety=vm.group(1).strip()
        return h, lines
