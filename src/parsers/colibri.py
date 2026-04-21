from __future__ import annotations

import re

from src.models import InvoiceHeader, InvoiceLine


class ColibriParser:
    """
    Claveles Colibri.
    Formato: [N] H/Q  Carnation [COLOR] [X SPB] [- GRADE]  [BOX_IDs]  [Total] ST  [PRICE]  [TOTAL]
    - No hay talla en CM.
    - El numero antes de ST ya es el total de tallos de esa linea.
    - X 20 indica tallos por ramo; si no aparece se asume 20.
    """
    GRADE_MAP={'FAN':'FANCY','SEL':'SELECT','STD':'STANDARD','PRE':'PREMIUM','FCY':'FANCY'}

    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'INVOICE\s+No\.\s*(\S+)',text,re.I); h.invoice_number=m.group(1) if m else ''
        m=re.search(r'Date Invoice[:\s]+([\d/]+)',text,re.I); h.date=m.group(1) if m else ''
        m=re.search(r'AWB[:\s]+([\d\-]+)',text,re.I); h.awb=re.sub(r'\s+','',m.group(1)) if m else ''
        lines=[]
        for ln in text.split('\n'):
            # Patron: [N] H/Q  Carnation DESCRIPCION ...  [N] ST  PRICE  TOTAL
            # La descripcion termina en 3+ espacios o en un numero de 6 digitos (box ID)
            pm=re.search(
                r'(\d+)\s*[HQ]\s+'                                    # N cajas
                r'(Mini)?[Cc]arnation\s+'                              # especie (+ Mini)
                r'((?:[A-Za-z][A-Za-z\s.\-/]*?))'                      # color/descripcion
                r'(?=\s{3,}|\s+\d{6}|\s+X\s+\d|\s*[-\u2013]\s*\w+\s{2,})',# fin descripcion
                ln, re.I
            )
            if not pm: continue
            is_mini=bool(pm.group(2))
            color=pm.group(3).strip().upper()

            # Extraer SPB del "X 20" -- solo 2-3 digitos, no IDs de caja
            spb_m=re.search(r'\bX\s+(\d{2,3})\b', ln)
            default_spb=10 if is_mini else 20
            spb=int(spb_m.group(1)) if spb_m else default_spb

            # Extraer grado (FAN / SEL / etc.) de la linea
            grade_m=re.search(r'\b(FAN|SEL|STD|PRE|FCY)\b', ln, re.I)
            grade_raw=grade_m.group(1).upper() if grade_m else 'FAN'
            grade=self.GRADE_MAP.get(grade_raw[:3], 'FANCY')

            # Box ID / destinatario: lo que va entre el grado y "CO-" (ej: R45, GARCIA)
            label_m=re.search(r'\d{6}\S*\s+(?:FAN|SEL|STD|PRE|FCY)\s+([A-Za-z\u00C0-\u024F][A-Za-z0-9\u00C0-\u024F]+)\s+CO-', ln, re.I)
            label=label_m.group(1).upper() if label_m else ''

            # Total de tallos: numero antes de literal "ST" (word boundary
            # para no capturar "STA" de grade STANDARD, ej. "581314 STA R17")
            st_m=re.search(r'(\d+)\s+ST\b', ln)
            stems=int(st_m.group(1)) if st_m else 0

            # Precio y total. Formato Colibri es US: coma=miles, punto=decimal
            # (ej. "2,565.000"). Hay que quitar la coma, no sustituirla por punto.
            prices=re.findall(r'([\d,]+\.[\d]{3})', ln)
            price=0.0; total=0.0
            if len(prices)>=2:
                try: price=float(prices[-2].replace(',','')); total=float(prices[-1].replace(',',''))
                except: pass
            elif len(prices)==1:
                try: total=float(prices[-1].replace(',',''))
                except: pass

            # Caja mixta: "CARN MIX RED/YELLOW" -> dos lineas, tallos y total / 2
            # BICOLOR es una variedad en si misma (flor bicolor), no se parte
            sp='CARNATIONS'  # Miniclaveles usan la misma especie; el SPB=10 los distingue
            mix_m=re.search(r'([A-Za-z]+)\s*/\s*([A-Za-z]+)', color)
            if mix_m:
                c1=mix_m.group(1).strip().upper()
                c2=mix_m.group(2).strip().upper()
                half=stems//2; half_t=round(total/2,3)
                for cv in (c1,c2):
                    lines.append(InvoiceLine(raw_description=ln,species=sp,variety=cv,
                                             grade=grade,origin='COL',size=0,
                                             stems_per_bunch=spb,stems=half,
                                             price_per_stem=price,line_total=half_t,
                                             label=label,box_type='MIX'))
            else:
                lines.append(InvoiceLine(raw_description=ln,species=sp,variety=color,
                                         grade=grade,origin='COL',size=0,
                                         stems_per_bunch=spb,stems=stems,
                                         price_per_stem=price,line_total=total,
                                         label=label))
        return h, lines
