from __future__ import annotations

import re

from src.models import InvoiceHeader, InvoiceLine


class CantizaParser:
    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        def f(p,d=''):
            m=re.search(p,text,re.I|re.DOTALL); return m.group(1).strip() if m else d
        h.invoice_number=f(r'(?:Invoice\s+Numbers?|CUSTOMER\s+INVOICE)\s+(\S+)')
        h.date=f(r'Invoice\s+Date\s+([\d/]+)')
        h.awb=re.sub(r'\s+','',f(r'MAWB\s+([\d\-\s]+?)(?:\s{2,}|HAWB)'))
        h.hawb=f(r'HAWB\s+(\S+)')
        try: h.total=float(f(r'Amount\s+Due\s+\$?([\d,]+\.?\d*)','0').replace(',',''))
        except: h.total=0.0
        lines=[]
        label=''; btype=''; farm=''
        for raw in text.split('\n'):
            ln=raw.strip()
            if not ln: continue
            # Normaliza OCR típico de esta factura: pipes, tamaños OCR (S0/SO → 50),
            # `N255T` pegado → `N 25ST`, `2351` (OCR de 25ST) → `25ST`.
            ln = ln.replace('|', ' ')
            ln = re.sub(r'\bS[O0](?=CM)', '50', ln)              # S0CM / SOCM → 50CM
            ln = re.sub(r'\bN(\d{1,2})5?T\b', r'N \g<1>5ST', ln) # N255T → N 25ST
            ln = re.sub(r'\bN\s*2351\b', 'N 25ST', ln, flags=re.I)
            ln = re.sub(r'\s{2,}', ' ', ln).strip()
            # Box type: "HB CAN-XXX" o "HB RN-XXX"
            bm=re.search(r'(HB|QB)\s+\w+[- ]?([\dX.]+)',ln)
            if bm: btype=f"{bm.group(1)} {bm.group(0).split()[1]}"
            if re.search(r'MIXED\s+BOX',ln):
                lm=re.search(r'\$[\d.]+\s+([A-Z][\w\s\-]*?)\s*$',ln)
                if lm:
                    raw2=lm.group(1).strip()
                    if raw2 and raw2!='TOTALS': label=re.split(r'\s{4,}',raw2)[0].strip()
                fm=re.search(r'([A-Z]\w*\s*\d*)\s+\d+\s+\$',ln)
                if fm: farm=fm.group(1).strip()
                continue
            # Sub-líneas: "VARIETY SIZECM N SPBST FARMCODE" — CZ (Cantiza), RN (Rosa Nova), etc.
            # `\s*` tras N para aceptar "N255T" pegado (ya normalizado arriba).
            pm=re.search(r'([\w][\w\s.\']*?)\s+(\d+)CM\s+N\s*(\d+)ST\s+[A-Z]{1,4}\b',ln)
            if not pm: continue
            var=re.sub(r'^[\d*X.]+\s+','',pm.group(1).strip()).strip()
            var=re.sub(r'\([\d*X.]+\)','',var).strip()
            if not var: continue
            sz,spb=int(pm.group(2)),int(pm.group(3))
            fm2=re.search(r'(?:ROSES|CARNATION)\s+([A-Z][\w\s]*?)(?:\s+\d+\s+\$)',ln)
            if fm2: farm=fm2.group(1).strip().upper()
            nm=re.search(r'(\d+)\s+\$([\d.]+)\s+(\d+)\s+\$([\d.]+)\s+\$([\d.]+)',ln)
            bunches=int(nm.group(1)) if nm else 0
            ppb=float(nm.group(2)) if nm else 0.0
            stems=int(nm.group(3)) if nm else 0
            pps=float(nm.group(4)) if nm else 0.0
            total=float(nm.group(5)) if nm else 0.0
            if stems==0 and bunches>0: stems=bunches*spb
            il=InvoiceLine(raw_description=f"{var} {sz}CM N {spb}ST CZ",species='ROSES',variety=var,
                           size=sz,stems_per_bunch=spb,bunches=bunches,stems=stems,
                           price_per_stem=pps,price_per_bunch=ppb,line_total=total,
                           label=label,farm=farm,box_type=btype)
            lines.append(il)
        return h,lines
