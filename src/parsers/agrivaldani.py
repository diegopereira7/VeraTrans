from __future__ import annotations

import re

from src.models import InvoiceHeader, InvoiceLine


class AgrivaldaniParser:
    """
    Formato Agrivaldani/Luxus.
    QUARTER/HALF/FULL = tipo de caja (nunca variedad).
    La variedad puede estar en la misma linea que los numeros
    o en una linea propia justo antes (carry-forward).

    Casos:
      Luxus:       "1 HALF FREEDOM 40 25 12 300 0.22 22.00"
      Agrivaldani: variedad en sub-cabecera, datos en siguiente linea
      Agrivaldani1:"1-1 R15  1 QUARTER EXPLORER 50 25 1 25 0.30 7.50"
                   "MUNDIAL 50 25 1 25 0.38 9.50"
                   "CARROUSEL  1"  <- solo variedad + cantidad, hereda tamano
    """
    _NOISE = re.compile(r'^(TOTAL|FOB|USD|ORDER|BOX|TYPE|VARIETIES|STEMS|PRICE|BUNCH|CARPE\s+DIEM\s+STEMS)', re.I)
    _BTYPE = re.compile(r'\b(QUARTER|HALF|FULL)\b', re.I)
    # Admite acentos/ñ en variedades (ej: PIÑA COLADA CRAFTED)
    _V = r'[A-ZÀ-ÖØ-Ý\u00D1\u00F1]'  # mayúsculas + acentos + Ñ/ñ
    _VC = r'[A-ZÀ-ÖØ-Ý\u00D1\u00F1\s.\-/&]'
    _VARONLY = re.compile(r'^(' + _V + _VC + r'{2,25}?)\s+(\d+)\s*$')

    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'Invoice\s+#[:\s]+(\S+)',text,re.I); h.invoice_number=m.group(1) if m else ''
        m=re.search(r'Date[:\s]+([\d/\-]+)',text,re.I); h.date=m.group(1) if m else ''
        m=re.search(r'AWB[:\s]+([\d\-\s]+?)(?:\s{2,}|HAWB)',text,re.I); h.awb=re.sub(r'\s+','',m.group(1)) if m else ''
        m=re.search(r'HAWB[:\s]+(\S+)',text,re.I); h.hawb=m.group(1) if m else ''
        try:
            m=re.search(r'TOTAL:\s+[A-Z\s]+AND\s+[\d/]+\s+USD',text,re.I)
            # fallback: last number before USD
            m2=re.search(r'\$([\d,]+\.?\d*)\s*$',text,re.M)
            h.total=float(m2.group(1).replace(',','')) if m2 else 0.0
        except: h.total=0.0

        raw_lines=text.split('\n')
        lines=[]; current_variety=''; current_sz=50; current_spb=25; current_btype=''

        for ln in raw_lines:
            ln=ln.strip()
            if not ln: continue

            bt=self._BTYPE.search(ln)
            if bt: current_btype=bt.group(1).upper()

            # -- Limpiar prefijos de orden y tipo de caja --
            clean=re.sub(r'^\d+\s*[-\u2013]\s*\d+\s+\S+\s+','',ln)              # "1 - 1 R15 "
            clean=re.sub(r'^\d+\s+(?:QUARTER|HALF|FULL)\s+','',clean,flags=re.I)  # "1 QUARTER "
            # Quitar QUARTER/HALF/FULL residual — siempre es box type en este formato
            # (carry-forward a current_btype ya se hizo arriba)
            clean=re.sub(r'^(?:QUARTER|HALF|FULL)\s+','',clean,flags=re.I)

            # -- Patron A: variedad + CM + SPB + (bunches) + stems + price + total --
            # "FREEDOM 40 25 12 300 0.22 22.00"  /  "E. BLACK 50 25 1 25 0.30 15.00"
            # "HIGH & MAGIC 50 25 1 25 0.34 8.50"
            pm=re.search(
                r'^(' + self._V + self._VC + r'{1,28}?)\s+'  # variedad (admite acentos/ñ)
                r'(\d{2})\s+(\d{2})\s+'              # CM  SPB
                r'\d*\s*(\d+)\s+'                    # (bunches?)  stems
                r'([\d.]+)\s+([\d.]+)',               # price  total
                clean
            )
            if pm:
                candidate=pm.group(1).strip()
                sz=int(pm.group(2)); spb=int(pm.group(3))
                stems=int(pm.group(4))
                try: price=float(pm.group(5)); total=float(pm.group(6))
                except: price=0.0; total=0.0
                if not self._NOISE.match(candidate):
                    current_variety=candidate; current_sz=sz; current_spb=spb
                elif current_variety:
                    sz=current_sz; spb=current_spb
                else:
                    continue
                if not current_variety: continue
                il=InvoiceLine(raw_description=ln,species='ROSES',variety=current_variety,
                               size=sz,stems_per_bunch=spb,stems=stems,
                               price_per_stem=price,line_total=total,box_type=current_btype)
                lines.append(il); continue

            # -- Patron B: variedad + bunches + stems + price + total (sin CM/SPB) --
            # "M. DARK BLUE  1  25  0.90  22.50"  -- hereda CM/SPB del contexto
            pm2=re.search(
                r'^(' + self._V + self._VC + r'{1,28}?)\s+'  # variedad (admite acentos/ñ)
                r'(\d{1,3})\s+(\d{1,3})\s+'     # bunches  stems
                r'([\d.]+)\s+([\d.]+)',           # price  total
                clean
            )
            if pm2 and current_sz:
                candidate=pm2.group(1).strip()
                if not self._NOISE.match(candidate) and len(candidate)>2:
                    current_variety=candidate
                if not current_variety: continue
                try:
                    stems=int(pm2.group(3)); price=float(pm2.group(4)); total=float(pm2.group(5))
                except: continue
                il=InvoiceLine(raw_description=ln,species='ROSES',variety=current_variety,
                               size=current_sz,stems_per_bunch=current_spb,stems=stems,
                               price_per_stem=price,line_total=total,box_type=current_btype)
                lines.append(il); continue

            # -- Patron C: solo numeros -- hereda variedad y CM/SPB
            # "50  25  1  25  0.38  9.50"  o  "60  25  100  0.90  22.50"
            nm=re.search(r'^(\d{2})\s+(\d{2})\s+\d*\s*(\d+)\s+([\d.]+)\s+([\d.]+)',clean)
            if nm and current_variety:
                sz=int(nm.group(1)); spb=int(nm.group(2)); stems=int(nm.group(3))
                try: price=float(nm.group(4)); total=float(nm.group(5))
                except: price=0.0; total=0.0
                il=InvoiceLine(raw_description=ln,species='ROSES',variety=current_variety,
                               size=sz,stems_per_bunch=spb,stems=stems,
                               price_per_stem=price,line_total=total,box_type=current_btype)
                lines.append(il); continue

            # -- Variedad sola (actualiza current_variety para siguiente linea) --
            vo=self._VARONLY.match(clean)
            if vo:
                candidate=vo.group(1).strip()
                if not self._NOISE.match(candidate): current_variety=candidate

            # -- Sub-cabecera Agrivaldani: "TYPE  CARPE DIEM  STEMS  BOX..." --
            hm=re.search(r'TYPE\s+([A-Z][A-Z\s.\-/]{2,20}?)\s+STEMS',ln,re.I)
            if hm:
                candidate=hm.group(1).strip()
                if not self._NOISE.match(candidate): current_variety=candidate

        # Deduplicar: agrupa multiples cajas de misma variedad/talla/SPB
        seen={}
        for il in lines:
            k=f"{il.variety}|{il.size}|{il.stems_per_bunch}"
            if k not in seen: seen[k]=il
            else: seen[k].stems+=il.stems; seen[k].line_total+=il.line_total
        return h, list(seen.values())
