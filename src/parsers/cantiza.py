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
            bm=re.search(r'HB\s+CAN[- ]?([\dX.]+)',ln)
            if bm: btype=f"HB CAN-{bm.group(1)}"
            if re.search(r'MIXED\s+BOX',ln):
                lm=re.search(r'\$[\d.]+\s+([A-Z][\w\s\-]*?)\s*$',ln)
                if lm:
                    raw2=lm.group(1).strip()
                    if raw2 and raw2!='TOTALS': label=re.split(r'\s{4,}',raw2)[0].strip()
                fm=re.search(r'(C\d+)\s+\d+\s+\$',ln)
                if fm: farm=fm.group(1)
                continue
            pm=re.search(r'([\w][\w\s.\']*?)\s+(\d+)CM\s+N\s+(\d+)ST\s+CZ',ln)
            if not pm: continue
            var=re.sub(r'^[\d*X.]+\s+','',pm.group(1).strip()).strip()
            var=re.sub(r'\([\d*X.]+\)','',var).strip()
            if not var: continue
            sz,spb=int(pm.group(2)),int(pm.group(3))
            fm2=re.search(r'(?:ROSES|CARNATION)\s+([A-Z][A-Z0-9]*(?:-\d+)?)',ln)
            if fm2: farm=fm2.group(1).upper()
            nm=re.search(r'(?:[A-Z][A-Z0-9]*(?:-\d+)?)\s+(\d+)\s+\$([\d.]+)\s+(\d+)\s+\$([\d.]+)\s+\$([\d.]+)',ln)
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
