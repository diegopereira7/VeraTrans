from __future__ import annotations

import re

from src.models import InvoiceHeader, InvoiceLine


class BrissasParser:
    """Formato Brissas:
    ORDER | MARK | BX | BOX TYPE | VARIETIES | CM | STEMS | TOTAL STEMS | UNIT PRICE | TOTAL PRICE | ORDER TYPE | FARM

    Línea principal:
      "1 - 1 RICC ROSES 1 HB ROSE EXPLORER 50 325 325 0.280 91.000 Standing RICC ROSES"
    Línea de continuación (caja mixta, sin ORDER ni MARK):
      "ROSE FRUTTETO 60 200 200 0.320 64.000 Standing SANI ROSES"

    Variantes especiales:
      GARDEN ROSE <variety>, SPRAY ROSES SPR <color>, TINTED <color>
    """
    # Regex: línea principal con ORDER MARK BX BOXTYPE
    _MAIN_RE = re.compile(
        r'(\d+)\s*-\s*\d*\s+'           # ORDER range: "1 - 1", "3 - 4", or "12 - "
        r'(.+?)\s+'                       # MARK (farm name): "RICC ROSES"
        r'(\d+)\s+(HB|QB|TB)\s+'          # BX count + BOX TYPE
        r'((?:GARDEN\s+)?ROSE\s+'         # "ROSE " or "GARDEN ROSE "
        r'|SPRAY\s+ROSES?\s+(?:SPR\s+)?'  # "SPRAY ROSES SPR "
        r'|TINTED\s+'                     # "TINTED "
        r')'
        r'(.+?)\s+'                       # VARIETY
        r'(\d{2,3})\s+'                   # CM (talla)
        r'(\d+)\s+(\d+)\s+'              # STEMS per box, TOTAL STEMS
        r'([\d.]+)\s+([\d.]+)',           # UNIT PRICE, TOTAL PRICE
        re.I
    )
    # Regex: línea de continuación (sin ORDER/MARK, empieza con ROSE/GARDEN ROSE/etc.)
    _CONT_RE = re.compile(
        r'^((?:GARDEN\s+)?ROSE\s+'
        r'|SPRAY\s+ROSES?\s+(?:SPR\s+)?'
        r'|TINTED\s+'
        r')'
        r'(.+?)\s+'
        r'(\d{2,3})\s+'
        r'(\d+)\s+(\d+)\s+'
        r'([\d.]+)\s+([\d.]+)',
        re.I
    )

    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'Invoice\s+#[:\s]+(\S+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'Date[:\s]+([\d/\-]+)', text, re.I); h.date = m.group(1) if m else ''
        m = re.search(r'Air\s+waybill\s+No\.?[:\s]*([\d\-\s]+)', text, re.I)
        h.awb = re.sub(r'\s+', '', m.group(1).strip()) if m else ''
        # Total: "Sub Total XXXX.XXX" or just the last TOTAL line
        m = re.search(r'(?:Sub\s+)?Total\s+([\d,.]+)', text, re.I)
        h.total = float(m.group(1).replace(',', '')) if m else 0.0

        lines = []
        last_farm = ''
        last_box_type = 'HB'

        for ln in text.split('\n'):
            raw = ln.strip()
            if not raw:
                continue

            # Skip noise lines
            if re.match(r'(?:TOTAL|Forwarder|Box\s+Type|HB\s+\d|QB\s+\d|Thank|Payment|Sub\s+Total|Account|Bank|The\s+Swift)', raw, re.I):
                continue

            # Try main line
            pm = self._MAIN_RE.search(raw)
            if pm:
                last_farm = pm.group(2).strip()
                last_box_type = pm.group(4).upper()
                prefix = pm.group(5).strip().upper()
                var_raw = pm.group(6).strip().upper()
                sz = int(pm.group(7))
                stems_box = int(pm.group(8)); stems_total = int(pm.group(9))
                price = float(pm.group(10)); total = float(pm.group(11))

                var = self._clean_variety(prefix, var_raw)
                il = InvoiceLine(
                    raw_description=raw, species='ROSES', variety=var,
                    size=sz, stems_per_bunch=25, stems=stems_total,
                    price_per_stem=price, line_total=total,
                    box_type=last_box_type, farm=last_farm,
                )
                lines.append(il)
                continue

            # Try continuation line
            pm = self._CONT_RE.match(raw)
            if pm:
                prefix = pm.group(1).strip().upper()
                var_raw = pm.group(2).strip().upper()
                sz = int(pm.group(3))
                stems_box = int(pm.group(4)); stems_total = int(pm.group(5))
                price = float(pm.group(6)); total = float(pm.group(7))

                var = self._clean_variety(prefix, var_raw)
                il = InvoiceLine(
                    raw_description=raw, species='ROSES', variety=var,
                    size=sz, stems_per_bunch=25, stems=stems_total,
                    price_per_stem=price, line_total=total,
                    box_type=last_box_type, farm=last_farm,
                )
                lines.append(il)

        return h, lines

    @staticmethod
    def _clean_variety(prefix: str, var: str) -> str:
        """Clean variety name based on prefix and known patterns."""
        # Strip trailing noise: "Standing FARM_NAME", order type, farm repetition
        var = re.sub(r'\s+(?:Standing|VDAY|MDAY|Venta\s+diaria)\b.*$', '', var, flags=re.I).strip()

        # GARDEN ROSE prefix → keep as part of variety
        if 'GARDEN' in prefix:
            var = f"GARDEN ROSE {var}"
        # SPRAY ROSES SPR → normalize to SPRAY
        elif 'SPRAY' in prefix:
            var = f"SPRAY {var}"
        # TINTED prefix (captured explicitly)
        elif 'TINTED' in prefix:
            var = re.sub(r'^ROS\s+TINTED\b', '', var).strip()
            if not var:
                var = 'TINTED'
            else:
                var = f"TINTED {var}"
        else:
            # "ROSE TINTED ROS TINTED..." → the prefix is "ROSE " but var starts with TINTED
            if var.startswith('TINTED'):
                # "TINTED ROS TINTED" → just "TINTED"
                var = re.sub(r'^TINTED\s+ROS\s+TINTED\b', 'TINTED', var)
                if not var.startswith('TINTED '):
                    var = re.sub(r'^TINTED\b', 'TINTED', var)

        # Fix known truncations
        if var == 'HIGH AND':
            var = 'HIGH AND MAGIC'
        elif var == 'ULTRA FREEDOM':
            var = 'FREEDOM'

        return var


class TurflorParser:
    """Formato Turflor: BOXES H/Q (SPRAY) CARNATION VARIETY GRADE [DELEGATION] TARIFF STEMS T.STEMS Stems PRICE TOTAL
    Ejemplo: "10 H CARNATION ASSORTED FANCY 0603.12.00 500 5,000 Stems 0.130 $650.00"
             "1 H CARNATION SPECIAL MIX FANCY LUCAS 0603.12.00 500 500 Stems 0.130 $65.00"
             "1 Q SPRAY CARNATION RAINBOW SELECT GIJON 0603.12.00 250 250 Stems 0.140 $35.00"
    """
    # Known grades that mark the end of the variety
    _GRADES = {'FANCY', 'SELECT', 'STANDARD', 'STD'}

    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'INVOICE\s+Nro\.?\s*(\S+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'Date\s+Invoice\s+([\d/]+)', text, re.I); h.date = m.group(1) if m else ''
        m = re.search(r'AWB\s+([\d\-]+)', text, re.I); h.awb = re.sub(r'\s+', '', m.group(1)) if m else ''
        m = re.search(r'HAWB\s+([\w\-]+)', text, re.I); h.hawb = m.group(1) if m else ''
        m = re.search(r'INVOICE\s+TOTAL\s+US\$\s*([\d,.]+)', text, re.I)
        h.total = float(m.group(1).replace(',', '')) if m else 0.0

        lines = []
        for ln in text.split('\n'):
            raw = ln.strip()
            # Match: BOXES H/Q [SPRAY] CARNATION DESC ... TARIFF STEMS T.STEMS Stems PRICE $TOTAL
            pm = re.search(
                r'(\d+)\s+(H|Q)\s+'                                 # boxes + box_type
                r'((?:SPRAY\s+)?CARNATION\s+.+?)\s+'               # description (greedy until tariff)
                r'0603[\d.]+\s+'                                     # tariff code
                r'([\d,]+)\s+([\d,]+)\s+Stems\s+'                   # stems_box, total_stems
                r'([\d.]+)\s+\$([\d,.]+)',                           # price, total
                raw, re.I)
            # Format B (no tariff, HB/QB style): "1 HB CARNATION ASSORTED FANCY - ... 500 500 Stems $0.150 $75.00"
            # Captures everything between box_type and "N N Stems $P $T", then parses description
            if not pm:
                pm_b = re.search(
                    r'(\d+)\s+(HB|QB|H|Q)\s+'                       # boxes + box_type
                    r'(.*?)'                                         # description + dashes
                    r'(\d[\d,]*)\s+(\d[\d,]*)\s+Stems\s+'           # stems_box, total_stems
                    r'\$([\d.]+)\s+\$([\d,.]+)',                     # price, total
                    raw, re.I)
                if pm_b:
                    btype_raw = pm_b.group(2).upper()
                    btype = 'HB' if btype_raw in ('H', 'HB') else 'QB'
                    desc = re.sub(r'[\s-]+$', '', pm_b.group(3)).strip()
                    stems = int(pm_b.group(5).replace(',', ''))
                    try: price = float(pm_b.group(6)); total = float(pm_b.group(7).replace(',', ''))
                    except: price = 0.0; total = 0.0

                    # Parse description: may be "CARNATION VARIETY GRADE [- extras -] DELEG"
                    # or just a delegation name, or empty
                    d = desc.upper()
                    # Remove isolated dashes (separators between fields)
                    d = re.sub(r'\s+-\s+', ' ', d).strip()

                    is_spray = d.startswith('SPRAY ')
                    has_carnation = 'CARNATION' in d

                    if has_carnation:
                        d2 = re.sub(r'^SPRAY\s+CARNATION\s+', '', d) if is_spray else re.sub(r'^CARNATION\s+', '', d)
                        tokens = d2.split()
                        variety_parts = []
                        grade = ''
                        label = ''
                        for i, tok in enumerate(tokens):
                            if tok in self._GRADES:
                                grade = tok
                                label = ' '.join(tokens[i+1:])
                                break
                            variety_parts.append(tok)
                        variety = ' '.join(variety_parts) if variety_parts else 'ASSORTED'
                        if is_spray:
                            variety = f"SPRAY CARNATION {variety}"
                        else:
                            variety = f"CARNATION {variety}"
                    else:
                        # Delegation-only line or R12 label lines
                        variety = 'CARNATION ASSORTED'
                        grade = ''
                        label = d

                    il = InvoiceLine(raw_description=raw, species='CARNATIONS', variety=variety,
                                     origin='COL', size=0, stems_per_bunch=0, stems=stems, grade=grade,
                                     price_per_stem=price, line_total=total, box_type=btype,
                                     label=label, provider_key=pdata['key'])
                    lines.append(il)
                    continue
            if not pm:
                continue

            btype = 'HB' if pm.group(2).upper() == 'H' else 'QB'
            desc = pm.group(3).strip()
            stems = int(pm.group(5).replace(',', ''))
            try: price = float(pm.group(6)); total = float(pm.group(7).replace(',', ''))
            except: price = 0.0; total = 0.0

            # Parse description: [SPRAY] CARNATION VARIETY GRADE [DELEGATION]
            is_spray = desc.upper().startswith('SPRAY ')
            d = desc.upper()
            d = re.sub(r'^SPRAY\s+CARNATION\s+', '', d) if is_spray else re.sub(r'^CARNATION\s+', '', d)

            # Split into tokens, find grade, everything before is variety, after is delegation
            tokens = d.split()
            variety_parts = []
            grade = ''
            label = ''
            for i, tok in enumerate(tokens):
                if tok in self._GRADES:
                    grade = tok
                    label = ' '.join(tokens[i+1:])
                    break
                variety_parts.append(tok)
            variety = ' '.join(variety_parts) if variety_parts else 'MIXTO'
            if is_spray:
                variety = f"SPRAY CARNATION {variety}"
            else:
                variety = f"CARNATION {variety}"

            il = InvoiceLine(raw_description=raw, species='CARNATIONS', variety=variety, origin='COL',
                             size=0, stems_per_bunch=0, stems=stems, grade=grade,
                             price_per_stem=price, line_total=total, box_type=btype,
                             label=label, provider_key=pdata['key'])
            lines.append(il)
        return h, lines


class AlunaParser:
    """Formato: FULLBOXES PIECES STEMS VARIETY GRADE ... PRICE TOTAL"""
    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'INVOICE\s+(\S+)',text,re.I); h.invoice_number=m.group(1) if m else ''
        m=re.search(r'DATE[:\s]+([\d/]+)',text,re.I); h.date=m.group(1) if m else ''
        m=re.search(r'AWB\s+([\d\-]+)',text,re.I); h.awb=re.sub(r'\s+','',m.group(1)) if m else ''
        lines=[]
        for ln in text.split('\n'):
            ln=ln.strip()
            pm=re.search(r'([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([A-Z][A-Z\s.\-/]+?)\s+(\d{2})\s+\w+',ln)
            if not pm: continue
            var=pm.group(4).strip(); sz=int(pm.group(5))
            try: stems=int(pm.group(3).replace(',',''))
            except: stems=0
            nm=re.search(r'\$\s*([\d,.]+)\s+\$\s*([\d,.]+)',ln)
            price=0.0; total=0.0
            if nm:
                try: price=float(nm.group(1).replace(',','.')); total=float(nm.group(2).replace(',','.'))
                except: pass
            spb=25
            il=InvoiceLine(raw_description=ln,species='ROSES',variety=var,origin='COL',
                           size=sz,stems_per_bunch=spb,stems=stems,
                           price_per_stem=price,line_total=total)
            lines.append(il)
        return h, lines


class DaflorParser:
    """Formato: Boxes DESCRIPTION Box_ID Tariff No.Box P.O. Un.Box T.Un Unit Price TOTAL
    FIX: el PDF usa mixed-case (Alstroemeria, Roses), no solo MAYÚSCULAS.
    FIX: tamaño (50) aparece tras el guión de grado para rosas.
    FIX: a veces la descripción va en una línea y los números en la
    siguiente — mantener pending_desc/pending_sp entre iteraciones.
    """
    SPECIES_MAP={'alstroemeria':'ALSTROEMERIA','carnation':'CARNATIONS','rose':'ROSES',
                 'chrysanth':'CHRYSANTHEMUM','hydrangea':'HYDRANGEAS','gypsophila':'GYPSOPHILA'}

    def _detect_species(self, desc: str) -> str:
        for k, v in self.SPECIES_MAP.items():
            if k in desc.lower():
                return v
        return 'ALSTROEMERIA'

    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'INVOICE\s+Nro\.?\s*(\S+)',text,re.I); h.invoice_number=m.group(1) if m else ''
        m=re.search(r'Data Invoice\s+([\d/]+)',text,re.I); h.date=m.group(1) if m else ''
        m=re.search(r'AWB\s*/\s*VL\s+([\d\-]+)',text,re.I); h.awb=re.sub(r'\s+','',m.group(1)) if m else ''
        m=re.search(r'HAWB\s*/\s*VHL\s+([\w\-]+)',text,re.I); h.hawb=m.group(1).strip() if m else ''
        lines=[]
        # Descripción colgada de la línea previa. Ej:
        #   'Alstroemeria Assorted - CO-'
        #   '1 QB MARCA DECO - - 200 200 Stems $0.150 $30.00'
        pending_desc = ''
        pending_sp = ''
        for ln in text.split('\n'):
            ln=ln.strip()
            if not ln:
                continue

            # Formato cabecera-colgada: descripción en una línea sin números finales.
            hdr_m = re.match(
                r'^(Alstroemeria|Roses?|Carnations?|Hydrangeas?|Chrysanth\w*|Gypsophila)\s+'
                r'(.+?)\s*[-\u2013]\s*(?:MARCA\s+)?(?:CO-.*)?$',
                ln, re.I)
            if hdr_m and 'Stems' not in ln and '$' not in ln:
                pending_sp = self._detect_species(hdr_m.group(1))
                pending_desc = f"{hdr_m.group(1).strip()} {hdr_m.group(2).strip()}"
                continue

            # Normaliza pipes y OCR errors (€ vs $, o por 0 antes de .)
            # antes de buscar el patrón principal.
            ln_norm = ln.replace('|', ' ')
            ln_norm = re.sub(r'[\u20ac�]\s*o\.', '$0.', ln_norm)  # "� o.15" -> "$0.15"
            ln_norm = re.sub(r'\bo\.(\d)', r'0.\1', ln_norm)      # "o.15" -> "0.15"
            ln_norm = re.sub(r'\s{2,}', ' ', ln_norm).strip()
            # FIX: usar re.I para mixed-case: "1 QB Alstroemeria Assorted - Fancy"
            # Also allow digits in grade position (for roses where size appears as grade: "- 50").
            # Q alone (1 letra) soportado además de QB/HB.
            pm=re.search(r'(\d+)\s+(QB?|HB?)\s+([A-Za-z][A-Za-z\s.\-/\u00b4\u2019\']+?)\s*[-\u2013]\s*([A-Za-z0-9]+)',ln_norm,re.I)
            desc = ''
            btype = ''
            grade = ''
            used_pending = False
            if pm:
                btype=pm.group(2).upper(); desc=pm.group(3).strip(); grade=pm.group(4).strip()
                if len(btype) == 1:
                    btype = btype + 'B'   # "Q" → "QB", "H" → "HB"
            else:
                # Segunda línea del formato colgado: "1 QB ... 200 200 Stems $..."
                cont_m = re.search(
                    r'(\d+)\s+(QB?|HB?)\s+(?:(.+?)\s+)?\d+\s+\d+\s+Stems\s+\$?',
                    ln_norm, re.I)
                if cont_m and pending_desc:
                    btype = cont_m.group(2).upper()
                    if len(btype) == 1:
                        btype = btype + 'B'
                    # Etiqueta/marca entre QB y los números (opcional)
                    extra = (cont_m.group(3) or '').strip()
                    desc = pending_desc
                    grade = extra if extra and not re.match(r'^-+$', extra) else ''
                    used_pending = True
                else:
                    pm=re.search(r'(QB?|HB?)\s+([A-Za-z][A-Za-z\s.\-/\u00b4\u2019\']+?)\s*[-\u2013]\s*([A-Za-z0-9]+)',ln_norm,re.I)
                    if not pm:
                        continue
                    btype=pm.group(1).upper(); desc=pm.group(2).strip(); grade=pm.group(3).strip()
                    if len(btype) == 1:
                        btype = btype + 'B'

            # Detectar especie
            sp = pending_sp if used_pending and pending_sp else self._detect_species(desc)
            # Extraer tamaño para rosas: "Roses Pink O'hara - 50"
            sz=0
            sz_m=re.search(r'[-\u2013]\s*(\d{2})\s', ln_norm)
            if sz_m and sp == 'ROSES':
                sz = int(sz_m.group(1))
            # FIX: buscar "200 200 Stems $0.150 $30.00" con case-insensitive.
            # El primer $ puede faltar (Stems 0.15 $56.00) y los miles pueden
            # venir con coma (1,000 stems).
            nm=re.search(r'([\d,]+)\s+([\d,]+)\s+Stems\s+\$?([\d.]+)\s+\$?([\d.,]+)',ln_norm,re.I)
            upb=0; stems=0; price=0.0; total=0.0
            if nm:
                try:
                    upb=int(nm.group(1).replace(',','')); stems=int(nm.group(2).replace(',',''))
                    price=float(nm.group(3)); total=float(nm.group(4).replace(',',''))
                except: pass
            # Limpiar nombre de variedad: quitar prefijo de especie
            var_clean = re.sub(r'^(?:Alstroemeria|Roses?|Carnations?|Hydrangeas?)\s+', '', desc, flags=re.I).strip()
            il=InvoiceLine(raw_description=ln,species=sp,variety=var_clean.upper(),grade=grade.upper(),origin='COL',
                           size=sz,stems_per_bunch=upb,stems=stems,price_per_stem=price,line_total=total,box_type=btype)
            lines.append(il)
            # Reset pending tras consumirlo
            if used_pending:
                pending_desc = ''
                pending_sp = ''
        return h, lines


class EqrParser:
    """Formato: Description 'Roses Color Variety CM x Stems Stem'"""

    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'Invoice\s+#\s+(\d+)',text,re.I); h.invoice_number=m.group(1) if m else ''
        m=re.search(r'Invoice\s+Date\s+([\d/]+)',text,re.I); h.date=m.group(1) if m else ''
        m=re.search(r'Way\s+Bill[^:]*:\s*([\d\-]+)',text,re.I); h.awb=re.sub(r'\s+','',m.group(1)) if m else ''
        try:
            m=re.search(r'Amount\s+\$([\d,.]+)',text,re.I)
            h.total=float(m.group(1).replace(',','')) if m else 0.0
        except: h.total=0.0
        lines=[]
        for ln in text.split('\n'):
            # Strip "Bi - Color" / "Bi-Color" prefix before parsing
            had_bicolor = bool(re.search(r'Bi\s*-?\s*Color', ln, re.I))
            ln_clean = re.sub(r'(Roses?\s+)Bi\s*-?\s*Color\s+', r'\1', ln, flags=re.I)
            # Bi-Color lines: color IS the variety (Orange Iguana) → capture all
            # Non-Bi-Color lines: first word is color category (Orange Orange Crush) → skip it
            if had_bicolor:
                pm=re.search(r'Roses?\s+([A-Z][a-zA-Z\s.\-/]+?)\s+(\d{2})\s+Cm?\s+x\s+(\d+)\s+Stem',ln_clean,re.I)
            else:
                pm=re.search(r'Roses?\s+(?:\w+\s+)?([A-Z][a-zA-Z\s.\-/]+?)\s+(\d{2})\s+Cm?\s+x\s+(\d+)\s+Stem',ln_clean,re.I)
            # Garden Rose format: "Garden Rose Color Variety NN Cm N Bun. NN St/Bun at $PRICE"
            if not pm:
                pm_g=re.search(
                    r'Garden\s+Rose\s+\w+\s+'                      # "Garden Rose Peach"
                    r'([A-Z][a-zA-Z\s.\-/]+?)\s+'                  # variety (Country Home)
                    r'(\d{2})\s+Cm\s+'                              # size
                    r'(\d+)\s+Bun\.\s+(\d+)\s+St/Bun',             # bunches + stems_per_bunch
                    ln, re.I)
                if pm_g:
                    var=pm_g.group(1).strip(); sz=int(pm_g.group(2))
                    bunches=int(pm_g.group(3)); spb=int(pm_g.group(4))
                    stems=bunches*spb
                    nm=re.search(r'\$\s*([\d.]+)',ln); price=float(nm.group(1)) if nm else 0.0
                    total=round(price*stems,2)
                    il=InvoiceLine(raw_description=ln,species='ROSES',variety=var.upper(),
                                   size=sz,stems_per_bunch=spb,stems=stems,
                                   price_per_stem=price,line_total=total)
                    lines.append(il)
                    continue
            if not pm: continue
            var=pm.group(1).strip(); sz=int(pm.group(2)); stems=int(pm.group(3))
            spb=25
            nm=re.search(r'\$\s*([\d.]+)',ln); price=float(nm.group(1)) if nm else 0.0
            total_m=re.search(r'\$\s*[\d.]+\s*$',ln)
            try: total=float(total_m.group(0).strip().lstrip('$')) if total_m else 0.0
            except: total=0.0
            il=InvoiceLine(raw_description=ln,species='ROSES',variety=var.upper(),
                           size=sz,stems_per_bunch=spb,stems=stems,
                           price_per_stem=price,line_total=total)
            lines.append(il)
        return h, lines


class BosqueParser:
    """Formato: #BOX PRODUCT-VARIETY TARIFF LENGTH BUNCHS STEMS T.STEMS PRICE AMOUNT"""
    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'No\.:\s*(\S+)',text,re.I); h.invoice_number=m.group(1) if m else ''
        m=re.search(r'(?:MAWB|MAWB No)\s*[:\s]*([\d]+)',text,re.I); h.awb=re.sub(r'\s+','',m.group(1)) if m else ''
        lines=[]
        for ln in text.split('\n'):
            ln=ln.strip()
            # Format A (original): "1 HB ROSAS VARIETY 50 ..."
            pm=re.search(r'(?:\d+\s+)?(HB|QB|TB)\s+ROSAS?\s+([A-Z][A-Z\s.\-/]+?)\s+(\d{2})',ln)
            # Format B (OCR/PDF split): "1 HB R O SAS VARIETY 0603... 50 12 25 300 $ 0.2800 $84.00"
            if not pm:
                pm_b=re.search(
                    r'(?:\d+\s+)?(HB|QB|TB)\s+R\s*O\s*SAS?\s+'   # box + "R O SAS" (OCR-split ROSAS)
                    r'([A-Z][A-Z\s.\-/]+?)\s+'                    # variety
                    r'0603\d+\s+\d+\s+'                            # tariff codes
                    r'(\d{2})\s+',                                 # size (50, 60, 70...)
                    ln)
                if pm_b:
                    btype=pm_b.group(1); var=pm_b.group(2).strip(); sz=int(pm_b.group(3))
                    nm=re.search(r'(\d+)\s+(\d+)\s+\$\s*([\d.]+)\s+\$([\d.]+)',ln)
                    bun=0; stems=0; price=0.0; total=0.0
                    if nm:
                        try: bun=int(nm.group(1)); stems=int(nm.group(2)); price=float(nm.group(3)); total=float(nm.group(4))
                        except: pass
                    spb=25
                    il=InvoiceLine(raw_description=ln,species='ROSES',variety=var,
                                   size=sz,stems_per_bunch=spb,bunches=bun,stems=stems,
                                   price_per_stem=price,line_total=total,box_type=btype)
                    lines.append(il)
                    continue
            if not pm: continue
            btype=pm.group(1); var=pm.group(2).strip(); sz=int(pm.group(3))
            nm=re.search(r'(\d+)\s+(\d+)\s+\$\s*([\d.]+)\s+\$([\d.]+)',ln)
            bun=0; stems=0; price=0.0; total=0.0
            if nm:
                try: bun=int(nm.group(1)); stems=int(nm.group(2)); price=float(nm.group(3)); total=float(nm.group(4))
                except: pass
            spb=25
            il=InvoiceLine(raw_description=ln,species='ROSES',variety=var,
                           size=sz,stems_per_bunch=spb,bunches=bun,stems=stems,
                           price_per_stem=price,line_total=total,box_type=btype)
            lines.append(il)
        return h, lines


class MultifloraParser:
    """FIX: código con espacios (PF -A LS001), múltiples especies (ALSTRO, CHRY, DIANTHUS).
    FIX: formatos Box perfection, Quarter tall, Half tall.

    Soporta tres variantes del template Multiflora:
      A) Legacy con FBE al final y box_type de 2 palabras:
         "PF -A LS001 ALSTRO PERFECTION AST ASSORTED ALSTR 1 Box perfection 16 16 3.3000 52.8000 0.25"
      B) Box_type de 1 palabra con FBE al final:
         "40 -R OSJSS ROSE 40cm LPK Jessica 25 St(Stems) 2 Half 250 500 0.2600 130.0000 1.00"
      C) Factura antigua con FBE al inicio y $ en total:
         "0.50 1 Half Tall 500 CARN Standard YEL Yellow 20 St(Stems) 0.1000 $50.000"
    """
    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'INVOICE\s+#[:\s]*(\S+)',text,re.I); h.invoice_number=m.group(1) if m else ''
        m=re.search(r'SHIPPING\s+DATE[:\s]+([\d/]+)',text,re.I); h.date=m.group(1) if m else ''
        m=re.search(r'AWB[:\s]*([\d\-/]+)',text,re.I); h.awb=re.sub(r'[/\s]','',m.group(1))[:14] if m else ''
        m=re.search(r'TOTAL\s+DUE\s+USD\s+([\d,.]+)',text,re.I)
        h.total=float(m.group(1).replace(',','')) if m else 0.0
        lines=[]; text_lines=text.split('\n')
        for i, ln in enumerate(text_lines):
            ln=ln.strip()
            # upb_hint: derivar units-per-bunch desde patrón 'N St(Stems)' en la línea
            upb_hint = None
            spb_m = re.search(r'(\d+)\s*(?:St|Stems|Bunches)\s*\(', ln, re.I)
            if spb_m:
                upb_hint = int(spb_m.group(1))
            qty = upb = total_units = None
            ppb = total = 0.0
            # A) "... N Box/Quarter/Half WORD N N PRICE TOTAL FBE"
            pm=re.search(r'(\d+)\s+(?:Box|Quarter|Half)\s+\w+\s+(\d+)\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*$',ln)
            if pm:
                qty = int(pm.group(1)); upb = int(pm.group(2)); total_units = int(pm.group(3))
                ppb = float(pm.group(4)); total = float(pm.group(5))
            # B) "... N Box/Quarter/Half N N PRICE TOTAL FBE"  (Half Tall sin segunda palabra)
            if qty is None:
                pm = re.search(r'(\d+)\s+(?:Box|Quarter|Half)\s+(\d+)\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*$', ln)
                if pm:
                    qty = int(pm.group(1)); upb = int(pm.group(2)); total_units = int(pm.group(3))
                    ppb = float(pm.group(4)); total = float(pm.group(5))
            # C) "FBE PIECES Half Tall UNITS description UPB St(Stems) PRICE $TOTAL"
            if qty is None:
                pm_c = re.search(
                    r'^([\d.]+)\s+(\d+)\s+(?:Box|Half|Quarter)(?:\s+Tall)?\s+([\d,]+)\s+'
                    r'.+?(\d+)\s*(?:St|Stems|Bunches)\s*\([^)]+\)\s+'
                    r'([\d.]+)\s+\$?([\d,.]+)\s*$',
                    ln)
                if pm_c:
                    qty = int(pm_c.group(2))
                    total_units = int(pm_c.group(3).replace(',', ''))
                    upb = int(pm_c.group(4))
                    ppb = float(pm_c.group(5))
                    total = float(pm_c.group(6).replace(',', ''))
            if qty is None:
                continue
            if upb_hint:
                upb = upb_hint
            # Detectar especie y variedad del texto de la línea
            sp='ALSTROEMERIA'; var='ASSORTED'; grade='FANCY'; sz=0
            upper=ln.upper()
            if 'ALSTRO' in upper:
                sp='ALSTROEMERIA'
                if 'WHISTLER' in upper: var='WHISTLER'
                elif 'WHITE' in upper: var='WHITE'
                elif 'SPECIAL' in upper or 'SPE' in upper: var='SPECIAL PACK'
                else: var='ASSORTED'
                if 'SELECT' in upper or 'SPE ' in upper: grade='SELECT'
                elif 'AST' in upper: grade='FANCY'
                else: grade='FANCY'
            elif 'CHRY' in upper:
                sp='CHRYSANTHEMUM'
                var='SPECIAL PACK' if 'SPECIAL' in upper else 'ASSORTED'
                grade=''
            elif 'DIANTHUS' in upper:
                sp='OTHER'
                dm=re.search(r'DIANTHUS\s+\d+cm\s+\w+\s+([\w\s]+?)(?:\d|St)',ln,re.I)
                var=dm.group(1).strip().upper() if dm else 'GREEN BALL'
                sz_m=re.search(r'(\d{2})cm',ln,re.I)
                sz=int(sz_m.group(1)) if sz_m else 0
                grade=''
            elif re.search(r'\bCARN\b', upper):
                sp='CARNATIONS'
                gm=re.search(r'\bCARN\s+(\w+)\s+\w{3}\s+([A-Za-z]+)', ln)
                if gm:
                    grade = gm.group(1).upper()
                    var = gm.group(2).upper()
                if 'MINI' in upper:
                    sp = 'CARNATIONS'  # tag with variety prefix
                    var = 'MINI ' + var
            elif re.search(r'\bROSE\b', upper):
                sp='ROSES'
                sz_m = re.search(r'ROSE\s+(\d{2,3})\s*cm', ln, re.I)
                if sz_m:
                    sz = int(sz_m.group(1))
                gm = re.search(r'ROSE\s+\d{2,3}\s*cm\s+\w{3}\s+([A-Za-z][A-Za-z\s]+?)\s+\d+\s*(?:St|Stems|Bunches)', ln, re.I)
                if gm:
                    var = gm.group(1).strip().upper()
                grade=''
            # Label: buscar en la línea siguiente (ej: "NAVARRA", "R11")
            label=''
            if i+1 < len(text_lines):
                next_ln=text_lines[i+1].strip()
                # Labels suelen estar solos o después de "10ST(Bunches)"
                lm=re.search(r'(?:Bunches\)|Stems\))\s+(\w+)',next_ln) or re.search(r'^([A-Z][A-Z0-9]+)$',next_ln)
                if lm: label=lm.group(1)
            il=InvoiceLine(raw_description=ln,species=sp,variety=var,grade=grade,origin='COL',
                           size=sz,stems_per_bunch=upb,bunches=total_units,stems=total_units*10 if sp=='ALSTROEMERIA' else total_units,
                           price_per_bunch=ppb,line_total=total,label=label)
            lines.append(il)
        return h, lines


class FlorsaniParser:
    # Especies conocidas de Florsani (Gypsophila, Limonium, etc.)
    _SPECIES_MAP = {
        'gypsophila': 'GYPSOPHILA',
        'limonium': 'OTHER',
    }

    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'N[o\xba]\s*(\S+)',text,re.I); h.invoice_number=m.group(1) if m else ''
        m=re.search(r'DATE[:\s]+([\d/\-]+)',text,re.I); h.date=m.group(1) if m else ''
        m=re.search(r'AWB#[:\s]*([\d\-]+)',text,re.I); h.awb=re.sub(r'\s+','',m.group(1)) if m else ''
        lines=[]
        for ln in text.split('\n'):
            ln=ln.strip()
            # Gypsophila: "2 HE Gypsophila Natural 80 25 500 0.260 500 130.00"
            pm=re.search(r'(\d+)\s+(?:HE?|QB?)\s+(?:\w+\s+)?Gypsophila\s+(\w+)',ln,re.I)
            if pm:
                qty=int(pm.group(1)); variety=f"Gypsophila {pm.group(2)}".upper()
                nm=re.search(r'(\d{2})\s+(\d+)\s+(\d+)\s+([\d.]+)',ln)
                sz=int(nm.group(1)) if nm else 80; spb=int(nm.group(2)) if nm else 0
                stems=int(nm.group(3)) if nm else 0; price=float(nm.group(4)) if nm else 0.0
                total=price*(stems if stems else qty)
                il=InvoiceLine(raw_description=ln,species='GYPSOPHILA',variety=variety,
                               size=sz,stems_per_bunch=spb,stems=stems,
                               price_per_stem=price,line_total=total)
                lines.append(il); continue

            # Limonium: "2 HE Limonium Pinna Colada NINGUNO 750 70 16 25 0.260 800 208.00"
            pm2=re.search(r'(\d+)\s+(?:HE?|QB?)\s+(?:\w+\s+)?Limonium\s+(.+?)(?:\s+NINGUNO|\s+\d{3,})',ln,re.I)
            if pm2:
                qty=int(pm2.group(1)); variety=f"LIMONIUM {pm2.group(2).strip().upper()}"
                nm=re.search(r'(\d{2})\s+(\d+)\s+(\d+)\s+([\d.]+)\s+(\d+)\s+([\d.]+)',ln)
                if nm:
                    sz=int(nm.group(1)); spb=int(nm.group(2))
                    stems=int(nm.group(5)); total=float(nm.group(6))
                else:
                    nm2=re.search(r'(\d+)\s+([\d.]+)\s*$',ln)
                    stems=int(nm2.group(1)) if nm2 else 0; total=float(nm2.group(2)) if nm2 else 0.0
                    sz=70; spb=25
                il=InvoiceLine(raw_description=ln,species='OTHER',variety=variety,
                               size=sz,stems_per_bunch=spb,stems=stems,
                               price_per_stem=total/stems if stems else 0.0,
                               line_total=total)
                lines.append(il)
        return h, lines


class MaxiParser:
    """Maxiflores: tabular format with ROSE and ALSTRO lines.
    ROSE lines: "ROSE VARIETY NN Cm ... STEMS TOTAL"
    ALSTRO lines: "ALSTRO (TSTEM VARIETY GRADE ... N STEMS_BOX STEMS .PRICE TOTAL"
    ROSE GARDEN lines: "ROSE GARDEN MAYRA`S PEACH 40 Cm ... STEMS TOTAL"
    """
    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'No\.\s*(\d+)',text,re.I); h.invoice_number=m.group(1) if m else ''
        m=re.search(r'DATE.*?(\d{2}/\d{2}/\d{4})',text,re.I); h.date=m.group(1) if m else ''
        m=re.search(r'AWB[:\s]*([\d\-]+)',text,re.I); h.awb=re.sub(r'\s+','',m.group(1)) if m else ''
        try:
            m=re.search(r'PAY THIS AMOUNT US \$\s*([\d,.]+)',text,re.I)
            h.total=float(m.group(1).replace(',','')) if m else 0.0
        except: h.total=0.0
        lines=[]
        for ln in text.split('\n'):
            ln=ln.strip()
            # ROSE lines: "ROSE VARIETY NN Cm ... N STEMS_BOX STEMS .PRICE TOTAL"
            # Also handles talla ranges like "50-60CM" → uses higher talla
            # Capture variety+size, then extract stems/price/total from trailing numbers
            pm=re.search(r'ROSE\s+([A-Z][A-Z\s.\-/`\']+?)\s+(\d{2})(?:\s*-\s*(\d{2}))?\s*Cm\b',ln,re.I)
            if pm:
                # Extract all numbers after the size match
                after = ln[pm.end():]
                nums = re.findall(r'[\d,]+\.?\d*', after)
                if len(nums) < 3:
                    pm = None  # not enough data, skip
            if pm:
                var=pm.group(1).strip()
                sz=int(pm.group(3)) if pm.group(3) else int(pm.group(2))  # use higher talla if range
                # Last number = total, second-to-last = price, third-to-last = stems
                try: stems=int(nums[-3].replace(',','')); total=float(nums[-1].replace(',',''))
                except: stems=0; total=0.0
                # GARDEN roses: "ROSE GARDEN MAYRA'S PEACH" → variety = "GARDEN MAYRA'S PEACH"
                spb=25
                price=total/stems if stems else 0.0
                il=InvoiceLine(raw_description=ln,species='ROSES',variety=var,origin='COL',
                               size=sz,stems_per_bunch=spb,stems=stems,
                               price_per_stem=price,line_total=total)
                lines.append(il)
                continue
            # ALSTRO lines: "ALSTRO (TSTEM VARIETY GRADE ... N STEMS_BOX STEMS .PRICE TOTAL"
            pm_a=re.search(
                r'ALSTRO\s*\(?[A-Z]*\s*'          # "ALSTRO (TSTEM" or "ALSTRO"
                r'([A-Z][A-Z\s.\-/]+?)\s+'          # variety (ASSORTED, WHITE, etc.)
                r'(SELECT\w*|SUPERSELEC\w*|FANCY)\s*' # grade
                r'.*?'
                r'(\d+)\s+([\d,.]+)\s*$',             # stems total
                ln, re.I)
            if pm_a:
                var=pm_a.group(1).strip()
                grade=pm_a.group(2).strip().upper()
                if 'SUPERSELEC' in grade: grade='SUPERSELECT'
                if var.upper() in ('ASSORTED','MIX','MIXED','SURTIDO'): var='MIXTO'
                try: stems=int(pm_a.group(3)); total=float(pm_a.group(4).replace(',',''))
                except: continue
                price=total/stems if stems else 0.0
                il=InvoiceLine(raw_description=ln,species='ALSTROEMERIA',variety=var.upper(),
                               grade=grade,origin='COL',size=0,stems_per_bunch=10,stems=stems,
                               price_per_stem=price,line_total=total)
                lines.append(il)
        return h, lines


class PrestigeParser:
    """DESCRIPTION CODE HB/QB_UNIT HB/QB_QTY STEMS $ UNIT_VALUE TOTAL
    FIX: 3 columnas numéricas (UNIT, QTY, STEMS) en vez de 2.
    FIX: decimales con coma (0,33 no 0.33).
    """
    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'INVOICE\s+No\.?\s*(\d+)',text,re.I); h.invoice_number=m.group(1) if m else ''
        m=re.search(r'FECHA EXPEDICION\s*([\d\-]+)',text,re.I); h.date=m.group(1) if m else ''
        m=re.search(r'GU[I\xcdÌ]A\s+MASTER\s+([\d\-]+)',text,re.I); h.awb=re.sub(r'\s+','',m.group(1)) if m else ''
        m=re.search(r'GU[I\xcdÌ]A\s+HIJA\s+([\d\w\s\-\(\)]+)',text,re.I)
        h.hawb=re.sub(r'\s+','',m.group(1)).strip() if m else ''
        lines=[]
        for ln in text.split('\n'):
            ln=ln.strip()
            # "MOMENTUM ROSE 50 CM ROSA0682 1 250 250 $ 0,33 82,50"
            # groups: variety, size, code, unit, qty, stems, price, total
            pm=re.search(r'([A-Z][A-Z\s.\-/]+?)\s+ROSE\s+(\d{2})\s+CM\s+\w+\s+(\d+)\s+(\d+)\s+(\d+)\s+\$\s*([\d,]+)\s+([\d,.]+)',ln,re.I)
            if not pm:
                # Sin "ROSE": "ASSORTED 50 CM ROSA0091 1 250 250 ..."
                pm=re.search(r'([A-Z][A-Z\s.\-/]+?)\s+(\d{2})\s+CM\s+\w+\s+(\d+)\s+(\d+)\s+(\d+)\s+\$\s*([\d,]+)\s+([\d,.]+)',ln,re.I)
                if not pm: continue
            var=pm.group(1).strip(); sz=int(pm.group(2))
            try:
                stems=int(pm.group(5))
                price_str=pm.group(6).replace(',','.')
                total_str=pm.group(7).replace(',','.')
                # total puede ser "82,50" o "484,50"
                price=float(price_str)
                total=float(total_str)
            except: continue
            spb=25
            il=InvoiceLine(raw_description=ln,species='ROSES',variety=var,origin='COL',
                           size=sz,stems_per_bunch=spb,stems=stems,
                           price_per_stem=price,line_total=total)
            lines.append(il)
        return h, lines


class RoselyParser:
    """BOXES VARIETY *SPB LENGTH BUNCHS STEMS PRICE AMOUNT"""
    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'INVOICE\s+TO',text,re.I); h.invoice_number='ROSELY'  # no number visible
        m2=re.search(r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)[^\d]*([\d]+)[^\d]*([\w]+)[^\d]*([\d]+)',text,re.I)
        h.date='' if not m2 else f"{m2.group(2)}/{m2.group(3)}/{m2.group(4)}"
        m=re.search(r'MAWB[:\s]*([\d\-]+)',text,re.I); h.awb=re.sub(r'\s+','',m.group(1)) if m else ''
        lines=[]
        for ln in text.split('\n'):
            ln=ln.strip()
            pm=re.search(r'(\d+)\s+(TB|HB|QB)\s+([A-Z][A-Z\s.\-/]+?)\s+\*(\d+)\s+(\d{2})\s+\d+\s+(\d+)\s+\$\s*([\d.]+)\s+\$([\d.]+)',ln)
            if not pm: continue
            btype=pm.group(2); var=pm.group(3).strip(); spb=int(pm.group(4))
            sz=int(pm.group(5)); stems=int(pm.group(6))
            try: price=float(pm.group(7)); total=float(pm.group(8))
            except: price=0.0; total=0.0
            il=InvoiceLine(raw_description=ln,species='ROSES',variety=var,
                           size=sz,stems_per_bunch=spb,stems=stems,
                           price_per_stem=price,line_total=total,box_type=btype)
            lines.append(il)
        return h, lines


class CondorParser:
    """FIX: decimales con coma (0,48 no 0.48), tarifa de 12 dígitos, stems de 3 dígitos."""
    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'PROFORMA\s+(\d+)',text,re.I); h.invoice_number=m.group(1) if m else ''
        m=re.search(r'(\d{2}[A-Z]{3}\d{4})',text); h.date=m.group(1) if m else ''
        m=re.search(r'MAWB\s+No\.?\s*([\d\-]+)',text,re.I); h.awb=re.sub(r'\s+','',m.group(1)) if m else ''
        m=re.search(r'HAWB\s+No\.?\s*([\w\-]+)',text,re.I); h.hawb=m.group(1).strip() if m else ''
        m=re.search(r'TOTAL\s+USD\s+([\d.,]+)',text,re.I)
        h.total=float(m.group(1).replace(',','.')) if m else 0.0
        lines=[]
        for ln in text.split('\n'):
            ln=ln.strip()
            # Variante A: "15,00 QB HYD WHITE PREMIUM[00001] 350603199010 525 0,48 252,00"
            #   (HTS pegado al SPB: 350603199010)
            # Variante B: "20,00 QB HYD WHITE PREMIUM 35 0603199010 700 0,58 406,00"
            #   (SPB separado del HTS: 35 0603199010)
            pm=re.search(r'[\d,]+\s+(QB|HB)\s+(HYD\s+[A-Za-z][A-Za-z\s.\-/]+?)\s*(?:\[[\d]+\])?\s+\d{2,}\s*\d*\s+(\d+)\s+([\d,]+)\s+([\d,]+)',ln,re.I)
            if not pm: continue
            btype=pm.group(1).upper(); desc=pm.group(2).strip().upper()
            var=re.sub(r'^HYD\s+','',desc).strip()
            try:
                stems=int(pm.group(3))
                price=float(pm.group(4).replace(',','.'))
                total=float(pm.group(5).replace(',','.'))
            except: stems=0; price=0.0; total=0.0
            il=InvoiceLine(raw_description=ln,species='HYDRANGEAS',variety=var,origin='COL',
                           stems_per_bunch=1,bunches=stems,stems=stems,
                           price_per_stem=price,line_total=total,box_type=btype)
            lines.append(il)
        return h, lines


class MalimaParser:
    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'Invoice Numbers?\s+(\d+)',text,re.I); h.invoice_number=m.group(1) if m else ''
        m=re.search(r'Ship Date\s+([\d/]+)',text,re.I); h.date=m.group(1) if m else ''
        m=re.search(r'(?:MAWB|AWB)[:\s]*([\d\-]+)',text,re.I); h.awb=re.sub(r'\s+','',m.group(1)) if m else ''
        try:
            m=re.search(r'Amount Due\s+\$([\d,.]+)',text,re.I)
            h.total=float(m.group(1).replace(',','')) if m else 0.0
        except: h.total=0.0
        lines=[]
        current_btype = ''
        for ln in text.split('\n'):
            ln=ln.strip()
            # Variante A (inline): "1 HB MALIMA EUROPA 0.50 XLENCE... GYPSOPHILA N $X.XX N $X.XX $X.XX"
            pm=re.search(r'\d+\s+(HB|QB)\s+MALIMA\s+EUROPA\s+[\d.]+\s+(XLENCE[^$]+?)\s+(GYPSOPHILA)\s+(\d+)\s+\$([\d.]+)\s+(\d+)\s+\$([\d.]+)\s+\$([\d.]+)',ln,re.I)
            if pm:
                current_btype=pm.group(1)
                variety=pm.group(2).strip().upper()
                try:
                    bunches=int(pm.group(4)); ppb=float(pm.group(5))
                    stems=int(pm.group(6)); total=float(pm.group(8))
                except: bunches=0; ppb=0.0; stems=0; total=0.0
                spb=stems//bunches if bunches else 25
                il=InvoiceLine(raw_description=ln,species='GYPSOPHILA',variety=variety,
                               stems_per_bunch=spb,bunches=bunches,stems=stems,
                               price_per_bunch=ppb,line_total=total,box_type=current_btype)
                lines.append(il); continue

            # Parent mixed box: solo actualizar btype
            pm_parent=re.search(r'\d+\s+(HB|QB)\s+MALIMA\s+EUROPA\s+[\d.]+\s+MIXED\s+BOX',ln,re.I)
            if pm_parent:
                current_btype=pm_parent.group(1); continue

            # Variante B (sub-línea): "XLENCE 80CM 30GR 20ST R PTRI TINT GREEN GYPSOPHILA 1 $8.00 20 $0.40 $8.00"
            # o "MILLION STARS 80CM 750GR MIN 20ST R PTRI - MI GYPSOPHILA 1 $8.75 20 $0.44 $8.75"
            pm2=re.search(
                r'^(.+?)\s+GYPSOPHILA\s+(\d+)\s+\$([\d.]+)\s+(\d+)\s+\$([\d.]+)\s+\$([\d.]+)',
                ln, re.I)
            if pm2:
                raw_desc=pm2.group(1).strip().upper()
                # Limpiar: quitar dimensiones (80CM 30GR 20ST), etiquetas (R PTRI), guiones
                variety = re.sub(r'\d+CM\b', '', raw_desc)
                variety = re.sub(r'\d+GR\b', '', variety)
                variety = re.sub(r'\d+ST\b', '', variety)
                variety = re.sub(r'\bMIN\b', '', variety)
                variety = re.sub(r'\bR\s+PTRI\b', '', variety)
                variety = re.sub(r'\s*-\s*(XL|MI)\s*$', '', variety)
                variety = re.sub(r'\s+', ' ', variety).strip()
                if not variety: continue
                try:
                    bunches=int(pm2.group(2)); ppb=float(pm2.group(3))
                    stems=int(pm2.group(4)); total=float(pm2.group(6))
                except: continue
                spb=stems//bunches if bunches else 20
                il=InvoiceLine(raw_description=ln,species='GYPSOPHILA',variety=variety,
                               stems_per_bunch=spb,bunches=bunches,stems=stems,
                               price_per_bunch=ppb,line_total=total,
                               box_type=current_btype or 'HB')
                lines.append(il)
        return h, lines


class MonterosaParser:
    """Formato Monterosas: QB/HB {pcs} {order} {mark} {variety} {spb} {b} {tb} {stems} {price} {total}
    Ejemplo: "HB 1 3 COTTON XPRESSION 25 12 12 300 0.35 105.00"
             "QB 1 4 PEACH WAVE 25 4 4 100 0.40 40.00"
    El SPB (25) viene DESPUÉS de la variedad, no la talla.
    La talla no aparece explícita en este formato — se infiere del contexto.
    """
    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'INVOICE\s+(\d+)',text,re.I); h.invoice_number=m.group(1) if m else ''
        m=re.search(r'DATE[:\s]+([\d\-/]+)',text,re.I); h.date=m.group(1) if m else ''
        m=re.search(r'M\s*A\s*W\s*B[:\s]*([\d\-/]+)',text,re.I); h.awb=re.sub(r'\s+','',m.group(1)) if m else ''
        lines=[]
        for ln in text.split('\n'):
            ln=ln.strip()
            # Formato: "QB/HB {num} {num} {MARK?} VARIETY SPB BUNCH TBUNCH STEMS PRICE TOTAL"
            # Strip box type + numeric prefix: "HB 1 3 " → "COTTON XPRESSION 25 12 12 300 0.35 105.00"
            pm = re.search(
                r'(?:QB|HB)\s+\d+\s+\d+\s+'   # box_type + pieces + order
                r'(?:[A-Z]+\s+)?'               # optional MARK (single uppercase word like "PEACH" — but this is part of variety!)
                , ln)
            if not pm:
                continue
            # Better approach: strip "QB/HB N N " prefix, then parse variety from rest
            rest = re.sub(r'^(?:QB|HB)\s+\d+\s+\d+\s+', '', ln).strip()
            # Strip optional mark code like "R11" (letter+digits, 2-4 chars)
            rest = re.sub(r'^[A-Z]\d{1,3}\s+', '', rest).strip()
            # rest = "COTTON XPRESSION 25 12 12 300 0.35 105.00"
            # or     "PEACH WAVE 25 4 4 100 0.40 40.00"
            # Variety = all alpha/space/punct until we hit: SPB(2digit) BUNCH TBUNCH STEMS
            vm = re.match(
                r'([A-Z][A-Z\s.\-/&]+?)\s+'    # variety (lazy but requires alpha start)
                r'(\d{2})\s+'                   # SPB (always 2 digits: 10, 12, 25)
                r'(\d+)\s+(\d+)\s+(\d+)\s+'    # bunches, total_bunches, stems
                r'([\d.]+)\s+([\d.]+)',          # price, total
                rest)
            if not vm:
                continue
            var = vm.group(1).strip()
            spb = int(vm.group(2))
            bunches = int(vm.group(3))
            stems = int(vm.group(5))
            try: total = float(vm.group(7))
            except: continue
            price = total / stems if stems else 0.0
            # Talla no está explícita en Monterosas — default 50
            sz = 50
            bt_m = re.search(r'(QB|HB)', ln)
            btype = bt_m.group(1) if bt_m else ''
            il = InvoiceLine(raw_description=ln, species='ROSES', variety=var,
                             size=sz, stems_per_bunch=spb, bunches=bunches, stems=stems,
                             price_per_stem=price, line_total=total, box_type=btype)
            lines.append(il)
        return h, lines


class SecoreParser:
    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'Invoice\s+N[o\xba]\s+(\d+)',text,re.I); h.invoice_number=m.group(1) if m else ''
        m=re.search(r'(\d+[-]\w+[-]\d+)',text); h.date=m.group(1) if m else ''
        m=re.search(r'AWB\s+([\d\s]+)',text,re.I); h.awb=re.sub(r'\s+','',m.group(1))[:12] if m else ''
        lines=[]
        for ln in text.split('\n'):
            ln=ln.strip()
            pm=re.search(r'ROSE\s+([A-Z][A-Z\s.\-/]+?)\s+(\d{2})\s+CM',ln,re.I)
            if not pm: continue
            var=pm.group(1).strip(); sz=int(pm.group(2))
            nm=re.search(r'(\d+)\s+(HALF|QUARTER|FULL)\s+(\d+)\s+([\d.]+)\s+([\d.]+)',ln,re.I)
            if not nm: continue
            try: upb=int(nm.group(1)); stems=int(nm.group(3)); price=float(nm.group(4)); total=float(nm.group(5))
            except: continue
            il=InvoiceLine(raw_description=ln,species='ROSES',variety=var,
                           size=sz,stems_per_bunch=upb,stems=stems,
                           price_per_stem=price,line_total=total)
            lines.append(il)
        return h, lines


class TessaParser:
    """Boxes Order BoxT Loc. Description Len Bun/Box Stems Price Total Label
    FIX: Loc puede ser "XL 2" o solo un número, y Description puede estar
    en la misma línea o en la siguiente (PINK\\nMONDIAL).
    """
    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'Invoice\s+Number\s*(\d+)',text,re.I); h.invoice_number=m.group(1) if m else ''
        m=re.search(r'Invoice\s+Date\s+([\d/]+)',text,re.I); h.date=m.group(1) if m else ''
        m=re.search(r'AWB\s+([\d\-\s]+)',text,re.I); h.awb=re.sub(r'\s+','',m.group(1))[:14] if m else ''
        m=re.search(r'HAWB\s+([\w\-]+)',text,re.I); h.hawb=m.group(1).strip() if m else ''
        try:
            m=re.search(r'(?:Invoice Amount|TOTALS.*?)\$([\d,.]+)',text,re.I)
            h.total=float(m.group(1).replace(',','')) if m else 0.0
        except: h.total=0.0
        lines=[]; text_lines=text.split('\n')
        for i, ln in enumerate(text_lines):
            ln=ln.strip()
            # Patrón: ...HB/QB [loc] [num] VARIETY SIZE BUNCHES STEMS $PRICE $TOTAL LABEL
            # Ejemplo: "1 910573351 HB XL 2 MONDIAL 60 12 300 $0.45 $135.00 R17"
            pm=re.search(r'(HB|QB)\s+(?:\w+\s+)?(?:\d+\s+)?([A-Z][A-Z\s.\-/]+?)\s+(\d{2})\s+(\d+)\s+(\d+)\s+\$([\d.]+)\s+\$([\d.]+)',ln)
            if pm:
                btype=pm.group(1); var=pm.group(2).strip()
                try: sz=int(pm.group(3)); spb=int(pm.group(4)); stems=int(pm.group(5)); price=float(pm.group(6)); total=float(pm.group(7))
                except: continue
                label_m=re.search(r'\$[\d.]+\s+(\w+)\s*$',ln); label=label_m.group(1) if label_m else ''
                il=InvoiceLine(raw_description=ln,species='ROSES',variety=var,
                               size=sz,stems_per_bunch=spb,stems=stems,
                               price_per_stem=price,line_total=total,label=label,box_type=btype)
                lines.append(il)
                continue
            # FIX: línea sin variedad visible (variedad en la línea siguiente)
            # "1 910927987 QB 3 60 4 100 $0.45 $45.00 R18"
            # siguiente línea: "R2 PINK"  o "MONDIAL"
            pm2=re.search(r'(HB|QB)\s+(\d+)\s+(\d{2})\s+(\d+)\s+(\d+)\s+\$([\d.]+)\s+\$([\d.]+)',ln)
            if pm2:
                btype=pm2.group(1)
                try: sz=int(pm2.group(3)); spb=int(pm2.group(4)); stems=int(pm2.group(5)); price=float(pm2.group(6)); total=float(pm2.group(7))
                except: continue
                label_m=re.search(r'\$[\d.]+\s+(\w+)\s*$',ln); label=label_m.group(1) if label_m else ''
                # Buscar variedad en líneas siguientes
                var_parts=[]
                for j in range(i+1, min(i+3, len(text_lines))):
                    next_ln=text_lines[j].strip()
                    if not next_ln: continue
                    # Buscar palabras que son nombre de variedad (mayúsculas, no números)
                    vm=re.findall(r'[A-Z][A-Z]+', next_ln)
                    if vm:
                        for w in vm:
                            if w not in ('TESSA','TOTALS','AWB','HAWB','USD','FUE'):
                                var_parts.append(w)
                        break
                var=' '.join(var_parts) if var_parts else 'DESCONOCIDA'
                il=InvoiceLine(raw_description=ln,species='ROSES',variety=var,
                               size=sz,stems_per_bunch=spb,stems=stems,
                               price_per_stem=price,line_total=total,label=label,box_type=btype)
                lines.append(il)
        return h, lines


class UmaParser:
    """FIX: descripciones largas con cm/gr y farm.
    FIX: comas decimales y espacios en totales ($ 1 40,00 = $140.00).
    FIX: "Gyp XL" (forma corta sin word-chars pegado), puntos como separador de miles.
    Formato: COD QTY BOX X PRODUCT FARM TOTAL_STEMS ST.BUNCH BUNCHES PRICE TOTAL
    """
    @staticmethod
    def _parse_amount(s: str) -> float:
        """Parsea montos en formato europeo: '1 .512,00' -> 1512.0, '1 44,00' -> 144.0"""
        s = re.sub(r'[\s.]', '', s)  # quitar espacios y puntos (miles)
        s = s.replace(',', '.')       # coma decimal -> punto
        return float(s)

    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'INVOICE\s+(\d+)',text,re.I); h.invoice_number=m.group(1) if m else ''
        m=re.search(r'Invoice\s+Date\s+([\d/]+)',text,re.I); h.date=m.group(1) if m else ''
        m=re.search(r'AWB\s+([\d\-]+)',text,re.I); h.awb=re.sub(r'\s+','',m.group(1)) if m else ''
        try:
            m=re.search(r'Amount\s+Due\s*[:\s]*\$\s*([\d\s.,]+)',text,re.I)
            h.total=self._parse_amount(m.group(1)) if m else 0.0
        except: h.total=0.0
        lines=[]
        for ln in text.split('\n'):
            ln=ln.strip()
            # Ejemplos:
            # "96885 1 hb 560 Gypso Xlence Natural 80 cm / 550 gr Violeta Flowers 560 20 28 $ 5,00 $ 1 40,00"
            # "97137 16 hb 450 Gypso Xlence Natural 80 cm / 750 gr Violeta Flowers 7200 25 288 $ 5 ,25 $ 1 .512,00"
            # "97137 1 hb 450 Gyp XL Especial 80 cm /750gr Violeta Flowers 450 25 18 $ 8 ,50 $ 1 53,00"
            # FIX: Gyp(?:so(?:phila)?)? para capturar "Gyp XL", "Gypso Xlence", "Gypsophila ..."
            # FIX: [\d\s.,]+? en totales para capturar puntos de miles
            # Gypsophila: "hb 560 Gypso Xlence Natural 80 cm / 550 gr Farm 560 20 28 $ 5,00 $ 140,00"
            pm=re.search(r'(hb|qb)\s+\d+\s+(Gyp(?:so(?:phila)?)?\s+[^$]+?)\s+(\d+)\s+(\d+)\s+(\d+)\s+\$\s*([\d\s.,]+?)\s+\$\s*([\d\s.,]+?)$',ln,re.I)
            if pm:
                btype=pm.group(1).upper()
                desc_raw=pm.group(2).strip()
                var_m=re.search(r'Gyp(?:so(?:phila)?)?\s+(.+?)\s+\d{2,3}\s*(?:cm|/|$)',desc_raw,re.I)
                var=var_m.group(1).strip().upper() if var_m else desc_raw.upper()
                sz_m=re.search(r'(\d{2,3})\s*(?:cm|/)',desc_raw,re.I)
                sz=int(sz_m.group(1)) if sz_m else 0
                farm_m=re.search(r'(?:Violeta|Fiorella|Margarita)\s+Flowers',desc_raw,re.I)
                farm=farm_m.group(0).strip() if farm_m else ''
                try:
                    stems=int(pm.group(3)); spb=int(pm.group(4)); bunches=int(pm.group(5))
                    price=self._parse_amount(pm.group(6))
                    total=self._parse_amount(pm.group(7))
                except: continue
                full_var='GYPSOPHILA ' + var if 'GYPSOPHILA' not in var else var
                il=InvoiceLine(raw_description=ln,species='GYPSOPHILA',variety=full_var,
                               size=sz,stems_per_bunch=spb,bunches=bunches,stems=stems,
                               price_per_bunch=price,line_total=total,box_type=btype,farm=farm)
                lines.append(il); continue

            # Rosas: "hb 300 Nectarine 50 cm Farm 300 25 12 $ 0,35 $ 105,00"
            pm2=re.search(r'(hb|qb)\s+\d+\s+([A-Za-z][A-Za-z\s.&\-/]+?)\s+(\d{2,3})\s*cm\s+(.+?)\s+(\d+)\s+(\d+)\s+(\d+)\s+\$\s*([\d\s.,]+?)\s+\$\s*([\d\s.,]+?)$',ln,re.I)
            if pm2:
                btype=pm2.group(1).upper()
                var=pm2.group(2).strip().upper()
                sz=int(pm2.group(3))
                farm=pm2.group(4).strip()
                try:
                    stems=int(pm2.group(5)); spb=int(pm2.group(6)); bunches=int(pm2.group(7))
                    price=self._parse_amount(pm2.group(8))
                    total=self._parse_amount(pm2.group(9))
                except: continue
                il=InvoiceLine(raw_description=ln,species='ROSES',variety=var,
                               size=sz,stems_per_bunch=spb,bunches=bunches,stems=stems,
                               price_per_stem=price,line_total=total,box_type=btype,farm=farm)
                lines.append(il)
        return h, lines


class VerdesEstacionParser:
    """Formato Verdes La Estacion / Ponderosa (mismo template SaaS, dos NITs).

    Soporta DOS variantes históricas del mismo template:

    Variante A (antigua):
      "1/39 HB 0,50 1,00 FREEDOM 50CM 240 240 MARL CO 0603110000 $ 0,30 $ 72,00"

    Variante B (actual, tras cambio de plantilla):
      "1 / 31 0,50 1,00 Vendela 50 240 MARL VERALEZA SLU FRESH CUT ROSES*20 CO 0603110000 $ 0,20 $ 48,00"
      "Explorer 60 50 R11-Tita VERALEZA SLU FRESH CUT ROSES*25 CO 0603110000 $ 0,40 $ 20,00"  ← cont. mixed box

    La variante B ya no trae el token CM pegado a la talla y tiene un único
    contador de stems (no duplicado como en A).
    """
    # Variante A: "VARIETY 50CM 240 240 LABEL CO <hts> $ price $ total"
    _RE_A = re.compile(
        r'([A-Z][A-Z\s]+?)\s+(\d{2})CM\s+(\d+)\s+(\d+)\s+([\w\s]*?)\s*CO\s+\d+\s+'
        r'\$\s*([\d,]+)\s+\$\s*([\d,]+)')

    # Variante B: "Variety <size> <stems> [LABEL] VERALEZA SLU FRESH CUT ROSES*<spb> CO <hts> $ price $ total"
    # Label puede ser "R11-Tita", "TIPO B", "MARL", etc. — multi-word posible.
    _RE_B = re.compile(
        r'([A-Za-z][A-Za-z\s\-]+?)\s+'          # variedad (mixed case o upper)
        r'(\d{2,3})\s+'                          # talla sin CM
        r'(\d+)\s+'                              # stems
        r'(.*?)\s*'                              # label (puede incluir espacios: "TIPO B")
        r'VERALEZA\s+SLU\s+FRESH\s+CUT\s+ROSES\s*\*\s*(\d+)\s+'
        r'(?:STEMS\s+)?CO\s+\d+\s+'
        r'\$\s*([\d,]+)\s+\$\s*([\d,]+)')

    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata.get('key', '')
        h.provider_id  = pdata.get('id', 0)
        h.provider_name = pdata.get('name', '')
        m = re.search(r'INVOICE\s+([\d.]+)', text, re.I)
        h.invoice_number = m.group(1).replace('.', '') if m else ''
        m = re.search(r'(\d{1,2}/\d{2}/\d{4})', text)
        h.date = m.group(1) if m else ''
        m = re.search(r'AWB\s+([\d\-]+)', text, re.I)
        h.awb = re.sub(r'\s+', '', m.group(1)) if m else ''
        m = re.search(r'HWB\s+([\w\-]+)', text, re.I)
        h.hawb = m.group(1).strip() if m else ''

        lines = []
        label = ''
        btype = 'HB'
        spb_default = 25
        text_lines = text.split('\n')
        for i, ln in enumerate(text_lines):
            ln = ln.strip()
            # Tipo de caja y marcador de box_num
            bm = re.search(r'\d+\s*/\s*\d+\s+(HB|QB|TB|FB)', ln)
            if bm:
                btype = bm.group(1)
            # SPB por defecto: extraer de ROSES*25 en la misma línea o adyacente
            spb_m = re.search(r'ROSES\s*\*\s*(\d+)', ln, re.I)
            if not spb_m and i + 1 < len(text_lines):
                spb_m = re.search(r'ROSES\s*\*\s*(\d+)', text_lines[i + 1], re.I)
            if spb_m:
                spb_default = int(spb_m.group(1))

            # Probar variante B primero (más común en facturas recientes)
            vm = self._RE_B.search(ln)
            if vm:
                variety = vm.group(1).strip().upper()
                # Descartar matches "falsos" donde la "variedad" es texto de cabecera
                if variety.startswith(('VARIEDAD', 'VARIETY', 'CAJAS', 'DESCRIPCION')):
                    continue
                size = int(vm.group(2))
                stems = int(vm.group(3))
                cur_label = vm.group(4).strip() or label
                if cur_label:
                    label = cur_label
                spb = int(vm.group(5))
                try:
                    price = float(vm.group(6).replace(',', '.'))
                    total = float(vm.group(7).replace(',', '.'))
                except Exception:
                    price = 0.0
                    total = 0.0
                lines.append(InvoiceLine(
                    raw_description=ln[:120], species='ROSES', variety=variety,
                    origin='COL', size=size, stems_per_bunch=spb, stems=stems,
                    price_per_stem=price, line_total=total, label=label,
                    box_type=btype, provider_key=pdata.get('key', ''),
                ))
                continue

            # Variante A (legacy)
            vm = self._RE_A.search(ln)
            if not vm:
                continue
            var = vm.group(1).strip()
            sz = int(vm.group(2))
            stems = int(vm.group(4))
            cur_label = vm.group(5).strip()
            if cur_label and cur_label not in ('CO',):
                label = cur_label
            try:
                price = float(vm.group(6).replace(',', '.'))
                total = float(vm.group(7).replace(',', '.'))
            except Exception:
                price = 0.0
                total = 0.0
            lines.append(InvoiceLine(
                raw_description=ln[:120], species='ROSES', variety=var,
                origin='COL', size=sz, stems_per_bunch=spb_default, stems=stems,
                price_per_stem=price, line_total=total, label=label,
                box_type=btype, provider_key=pdata.get('key', ''),
            ))

        if not h.total and lines:
            h.total = round(sum(l.line_total for l in lines), 2)
        return h, lines


class ValleVerdeParser:
    """Boxs Order BoxT Id. Description Len. Bun/BoxT. Bunch Stems Price Total
    FIX: variedades en mixed-case (Nectarine, Brighton, Iguazu).
    FIX: label R19 aparece como "R19" en la columna Id antes de la variedad.
    """
    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'INVOICE\s+(\S+)',text,re.I); h.invoice_number=m.group(1) if m else ''
        m=re.search(r'Date[:\s]+([\d\-]+)',text,re.I); h.date=m.group(1) if m else ''
        m=re.search(r'M\.\s*A\.?\s*W\.?\s*B\.?[:\s]*([\d\-]+)',text,re.I); h.awb=re.sub(r'\s+','',m.group(1)) if m else ''
        m=re.search(r'H\.\s*A\.?\s*W\.?\s*B\.?[:\s]*([\w\-]+)',text,re.I); h.hawb=m.group(1).strip() if m else ''
        lines=[]; label=''
        for ln in text.split('\n'):
            ln=ln.strip()
            lbl_m=re.search(r'\b(R\d{1,2}[\w\-]*)\b',ln)
            if lbl_m: label=lbl_m.group(1)
            # FIX: [A-Za-z] para mixed-case variedades
            # "1 1-1 HB Nectarine 50 12 12 300 0,300 90,000"
            # "3-3 HB R19 Brighton 50 2 2 50 0,330 16,500"
            # FIX: labels tipo "MARL", "DANS" (delegaciones/códigos) además de R\d+
            pm=re.search(r'(?:HB|QB)\s+(?:(?:R\d+|[A-Z]{2,5})\s+)?([A-Za-z][A-Za-z\s.\-/]+?)\s+(\d{2})\s+\d+\s+(\d+)\s+(\d+)\s+([\d,]+)\s+([\d,]+)',ln)
            if not pm: continue
            # Extraer label si hay codigo antes de la variedad
            lbl2=re.search(r'(?:HB|QB)\s+([A-Z]{2,5})\s+[A-Za-z]',ln)
            if lbl2: label=lbl2.group(1)
            var=pm.group(1).strip().upper(); sz=int(pm.group(2))
            try: bunches=int(pm.group(3)); stems=int(pm.group(4)); price=float(pm.group(5).replace(',','.')); total=float(pm.group(6).replace(',','.'))
            except: continue
            spb=stems//bunches if bunches else 25
            il=InvoiceLine(raw_description=ln,species='ROSES',variety=var,
                           size=sz,stems_per_bunch=spb,bunches=bunches,stems=stems,
                           price_per_stem=price,line_total=total,label=label)
            lines.append(il)
        return h, lines


class FloraromaParser:
    """Formato Floraroma: BOXES ORDER BOXTYPE GRADE BUNCHES VARIETY SIZE SPB STEMS PRICE TOTAL
    Tiene líneas de continuación (sin prefijo box/order) para cajas mixtas.
    Ejemplo:
      "1 1 - 1 HB E 12 Shimmer 50 25 300 0.280 84.000"
      "                E 1 Wasabi 60 25 25 0.320 8.000"
    """
    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        # "I N V O I C E 001097740" o "INVOICE 001097740"
        m = re.search(r'(?:I\s*N\s*V\s*O\s*I\s*C\s*E|INVOICE)\s+(\d+)', text, re.I)
        h.invoice_number = m.group(1) if m else ''
        m = re.search(r'Date:\s*([\d\-/]+)', text, re.I); h.date = m.group(1) if m else ''
        m = re.search(r'M\.?A\.?W\.?B\.?:\s*([\d\-]+)', text, re.I)
        h.awb = re.sub(r'\s+', '', m.group(1)) if m else ''
        m = re.search(r'H\.?A\.?W\.?B\.?:\s*(\S+)', text, re.I); h.hawb = m.group(1) if m else ''
        # Total desde línea TOTALS: "TOTALS 44 1100 0.255 280.500"
        m = re.search(r'TOTALS\s+\d+\s+\d+\s+[\d.]+\s+([\d.]+)', text)
        h.total = float(m.group(1)) if m else 0.0

        lines = []
        box_type = ''
        for ln in text.split('\n'):
            ln = ln.strip()
            # Línea completa (variante A): "1 1 - 1 HB E 12 Shimmer 50 25 300 0.280 84.000"
            # Variante B (2024): "11 - 1 QB GAIA.0050 ANA PREETO S.O2Explorer 50 25 50 0.280 14.000"
            #   (bunches pegado a variedad: "2Explorer")
            pm = re.search(
                r'\d+\s*-\s*\d+\s*(HB|QB|FB|EB)\s+.*?(\d+)\s*([A-Za-z][A-Za-z\s.\-/&]+?)\s+(\d{2,3})\s+(\d+)\s+(\d+)\s+([\d.]+)\s+([\d.]+)',
                ln)
            # Línea de continuación: "E 1 Wasabi 60 25 25 0.320 8.000"
            # Variante B: "E 2Mondial 50 25 50 0.280 14.000" (bunches pegado)
            if not pm:
                pm2 = re.search(
                    r'^[A-Z]\s+(\d+)\s*([A-Za-z][A-Za-z\s.\-/&]+?)\s+(\d{2,3})\s+(\d+)\s+(\d+)\s+([\d.]+)\s+([\d.]+)$',
                    ln)
                if pm2:
                    bunches = int(pm2.group(1)); var = pm2.group(2).strip().upper()
                    sz = int(pm2.group(3)); spb = int(pm2.group(4))
                    stems = int(pm2.group(5)); price = float(pm2.group(6)); total = float(pm2.group(7))
                    il = InvoiceLine(raw_description=ln, species='ROSES', variety=var,
                                     size=sz, stems_per_bunch=spb, bunches=bunches, stems=stems,
                                     price_per_stem=price, line_total=total, box_type=box_type)
                    lines.append(il)
                continue
            if not pm:
                continue

            box_type = pm.group(1)
            bunches = int(pm.group(2)); var = pm.group(3).strip().upper()
            sz = int(pm.group(4)); spb = int(pm.group(5))
            stems = int(pm.group(6)); price = float(pm.group(7)); total = float(pm.group(8))
            il = InvoiceLine(raw_description=ln, species='ROSES', variety=var,
                             size=sz, stems_per_bunch=spb, bunches=bunches, stems=stems,
                             price_per_stem=price, line_total=total, box_type=box_type)
            lines.append(il)
        return h, lines


class GardaParser:
    """Formato GardaExport: BOX_RANGE BOXTYPE PRODUCT VARIETY SIZE BUNCHES STEMS PRICE TOTAL
    Precios en formato europeo (coma decimal).
    Ejemplo:
      "01 - 05 H ROSAS (ROSOIDEA) Explorer 60 50 1250 0,36 450,00"
      "06 H ROSAS (ROSOIDEA) Iguana 50 10 250 0,28 70,00"
    """
    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'INVOICE\s*#\s*(\d+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'Date\s*:\s*([\d/\-]+)', text, re.I); h.date = m.group(1) if m else ''
        m = re.search(r'A\.?W\.?B\.?\s*(?:N.)?\s*:\s*([\d\-]+)', text, re.I)
        h.awb = re.sub(r'[\s.]', '', m.group(1)) if m else ''
        m = re.search(r'H\.?A\.?W\.?B\.?\s*(?:N.)?\s*:\s*(\S+)', text, re.I)
        h.hawb = m.group(1) if m else ''
        m = re.search(r'Total\s+Invoice:\s*\$\s*([\d.,]+)', text, re.I)
        h.total = float(m.group(1).replace('.', '').replace(',', '.')) if m else 0.0

        lines = []
        for ln in text.split('\n'):
            ln = ln.strip()
            # "01 - 05 H ROSAS (ROSOIDEA) Explorer 60 50 1250 0,36 450,00"
            # "06 H ROSAS (ROSOIDEA) Iguana 50 10 250 0,28 70,00"
            pm = re.search(
                r'\d{2}(?:\s*-\s*\d{2})?\s+(H|Q|F|E)\s+ROSAS?\s*\([^)]*\)\s+([A-Za-z][A-Za-z\s.\-/&!]+?)\s+(\d{2,3})\s+(\d+)\s+(\d+)\s+([\d.,]+)\s+([\d.,]+)',
                ln)
            if not pm:
                continue
            bt_map = {'H': 'HB', 'Q': 'QB', 'F': 'FB', 'E': 'EB'}
            box_type = bt_map.get(pm.group(1), pm.group(1))
            var = pm.group(2).strip().upper(); sz = int(pm.group(3))
            bunches = int(pm.group(4)); stems = int(pm.group(5))
            price = float(pm.group(6).replace('.', '').replace(',', '.'))
            total = float(pm.group(7).replace('.', '').replace(',', '.'))
            spb = stems // bunches if bunches else 25
            il = InvoiceLine(raw_description=ln, species='ROSES', variety=var,
                             size=sz, stems_per_bunch=spb, bunches=bunches, stems=stems,
                             price_per_stem=price, line_total=total, box_type=box_type)
            lines.append(il)
        return h, lines


class UtopiaParser:
    """Formato Utopia Farms: facturas de gypsophila con estructura compleja.
    Líneas de producto tipo:
      "GYPSO. XLENCE WHITE 25ST 750GR 12 B ... 4 Q 1 48 BC 1200 0.260 312.00"
    Se parsea: variedad, stems/bunch, peso, boxes, box_type, bunches, stems, price, total.
    """
    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        # "Number Ship Date ... 154747 1/1/2026"
        m = re.search(r'^\s*(\d{5,})\s+([\d/]+)\s*$', text, re.M)
        h.invoice_number = m.group(1) if m else ''
        h.date = m.group(2) if m else ''
        m = re.search(r'Air\s+Waybill:\s*([\d\-\s]+)', text, re.I)
        h.awb = re.sub(r'\s+', '', m.group(1)).strip() if m else ''
        m = re.search(r'USD:\s*([\d,.]+)', text, re.I)
        h.total = float(m.group(1).replace(',', '')) if m else 0.0
        # HAWB desde línea "Santa Martha HAWB: S1331765"
        m = re.search(r'HAWB:\s*(\S+)', text, re.I); h.hawb = m.group(1) if m else ''

        lines = []
        for ln in text.split('\n'):
            ln = ln.strip()
            # Buscar línea con GYPSO + stems/bunch + boxes + bunches + stems + price + total
            # "GYPSO. XLENCE WHITE 25ST 750GR 12 B (ST 1990285-6) 30 GR 4 Q 1 48 BC 1200 0.260 312.00"
            pm = re.search(
                r'(GYPSO\w*\.?\s+.+?)\s+(\d+)\s*ST\s+(\d+)\s*GR\s+.+?(\d+)\s+(Q|H|F|E)\s+[\d.]+\s+(\d+)\s+(?:BC\s+)?(\d+)\s+([\d.]+)\s+([\d.]+)',
                ln, re.I)
            if not pm:
                continue
            desc = pm.group(1).strip()
            spb = int(pm.group(2)); weight = pm.group(3)
            boxes = int(pm.group(4))
            bt_map = {'H': 'HB', 'Q': 'QB', 'F': 'FB', 'E': 'EB'}
            box_type = bt_map.get(pm.group(5).upper(), pm.group(5).upper())
            bunches = int(pm.group(6)); stems = int(pm.group(7))
            price = float(pm.group(8)); total = float(pm.group(9))
            # Extraer variedad: "GYPSO. XLENCE WHITE" -> "XLENCE WHITE"
            var_m = re.search(r'GYPSO\w*\.?\s+(.+)', desc, re.I)
            var = var_m.group(1).strip().upper() if var_m else desc.upper()
            full_var = 'GYPSOPHILA ' + var if 'GYPSOPHILA' not in var else var
            il = InvoiceLine(raw_description=ln, species='GYPSOPHILA', variety=full_var,
                             size=0, stems_per_bunch=spb, bunches=bunches, stems=stems,
                             price_per_stem=price, line_total=total, box_type=box_type,
                             grade=weight + 'GR')
            lines.append(il)
        return h, lines


class ColFarmParser:
    """Formato fincas colombianas (Circasia, Vuelven, Milonga):
    Boxes Description Box# Gr. BoxID Tariff UnxBox TotalUn Un Price Total
    Ejemplo: "1 H Rose Frutteto X 25 - 40 143213 40 0603.11.00.00 300 300 ST 0.25 75.00"
    Continuación (mixed box): "Rose White X 10 - 50 50 70 70 ST 0.30"

    Tolera OCR: 'Rbse'/'Rcse' por 'Rose', 'S1'/'SI'/'Sl'/"'ST" por 'ST',
    decimales con coma ('0,31') y espacios pegados ('NenaX25-50').
    """
    # Alias de Rose con tolerancia OCR: Rose, Rbse, Rcse, Ros
    _ROSE = r'(?:Rose|Rbse|Rcse|Ros)'
    # Unidad: ST, S1, SI, Sl, 'ST, ST'
    _UNIT = r"(?:ST|S1|SI|Sl|'?ST'?)"

    @staticmethod
    def _money(s: str) -> float:
        """Parse money value: handles '3,900.00', '75.00', '0,31'. Tolera
        OCR garbage devolviendo 0.0 en lugar de reventar."""
        s = (s or '').strip()
        if not s or not re.search(r'\d', s):
            return 0.0
        try:
            if ',' in s and '.' not in s:
                return float(s.replace(',', '.'))
            return float(s.replace(',', ''))
        except ValueError:
            return 0.0

    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'INVOICE\s+No\.?\s*([\w\-]+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'Date\s+(?:Invoice|lnvoice)?[:\s]*([\d/\-]+)', text, re.I)
        h.date = m.group(1).strip() if m else ''
        m = re.search(r'AWB\s*/?\s*VL[:\s]*([\d\-\s]+)', text, re.I)
        h.awb = re.sub(r'\s+', '', m.group(1).strip()) if m else ''
        m = re.search(r'HAWB\s*/?\s*HVL[:\s]*([\w\-]+)', text, re.I); h.hawb = m.group(1) if m else ''
        m = re.search(r'INVOICE\s+TOTAL\s*\(?\w*\)?\s*([\d,.]+)', text, re.I)
        h.total = self._money(m.group(1)) if m else 0.0

        lines = []
        box_type = 'HB'
        for ln_raw in text.split('\n'):
            ln = ln_raw.strip()
            # Normaliza ruido OCR típico de estas facturas: pipes, llaves,
            # caracteres raros (� { } [ ]), asteriscos y puntos sueltos
            # entre números. Mantiene la línea original para ``raw_description``.
            ln = re.sub(r'[\u00a6\u2022\u00b0{}\[\]~]', ' ', ln)
            ln = re.sub(r'[\ufffd\u00ef\u00bf\u00bd]', ' ', ln)  # � y variantes
            ln = ln.replace('|', ' ').replace('*', ' ')
            # "X2-5" pegado (OCR rompe X25) → "X 25", " i ee" ruido → " "
            ln = re.sub(r'X(\d)-(\d)(?=\s)', r'X\1\2', ln)
            ln = re.sub(r'\s+i\s+ee\s+', ' ', ln)
            ln = re.sub(r'\s{2,}', ' ', ln).strip()
            # Línea principal: "1 H Rose Frutteto X 25 - 40 ... 300 300 ST 0.25 75.00"
            # Soporta 'RoseFrutteto' pegado, OCR 'Rbse'/'Rcse', unidad ST/S1/Sl,
            # decimales con coma, conteo de caja opcional (sub-líneas OCR sin prefijo).
            pm = re.search(
                rf'(?:\d+\s+)?(H|Q)\s+{self._ROSE}\s*(.+?)\s*X\s*(\d+)\s*[-_]?\s+(\d{{2,3}})\s+.+?\s+(\d+)\s+(\d+)\s+{self._UNIT}\s+([\d,.]+)\s+([\d,.]+)',
                ln, re.I)
            if pm:
                box_type = 'HB' if pm.group(1).upper() == 'H' else 'QB'
                var = pm.group(2).strip().upper()
                spb = int(pm.group(3)); sz = int(pm.group(4))
                stems_box = int(pm.group(5)); stems_total = int(pm.group(6))
                price = self._money(pm.group(7)); total = self._money(pm.group(8))
                # Skip "Rosemix"/"assorted" lines — their sub-lines follow
                if re.match(r'(?:ROSEMIX|ASSORTED|SURTID)', var, re.I):
                    continue
                bunches = stems_total // spb if spb else 0
                il = InvoiceLine(raw_description=ln, species='ROSES', variety=var, origin='COL',
                                 size=sz, stems_per_bunch=spb, bunches=bunches, stems=stems_total,
                                 price_per_stem=price, line_total=total, box_type=box_type)
                lines.append(il)
                continue
            # Línea principal sin X-SPB: "1 H Rose assorted 142985 50 GONZA X 10 ... 200 200 ST 0.30 60.00"
            pm2 = re.search(
                rf'\d+\s+(H|Q)\s+{self._ROSE}\s*(.+?)\s+\d{{5,}}\s+(\d{{2,3}})\s+.+?\s+(\d+)\s+(\d+)\s+{self._UNIT}\s+([\d,.]+)\s+([\d,.]+)',
                ln, re.I)
            if pm2:
                box_type = 'HB' if pm2.group(1).upper() == 'H' else 'QB'
                var = pm2.group(2).strip().upper()
                sz = int(pm2.group(3))
                stems_total = int(pm2.group(5)); price = self._money(pm2.group(6)); total = self._money(pm2.group(7))
                if re.match(r'(?:ROSEMIX|ASSORTED|SURTID)', var, re.I):
                    continue
                il = InvoiceLine(raw_description=ln, species='ROSES', variety=var, origin='COL',
                                 size=sz, stems_per_bunch=25, stems=stems_total,
                                 price_per_stem=price, line_total=total, box_type=box_type)
                lines.append(il)
                continue
            # Continuación (sub-línea mixed box): "NenaX25-50 50 25 25 ST 0.28"
            # o "Rose White X 10 - 50 50 70 70 ST 0.30"
            pm3 = re.search(
                rf'(?:{self._ROSE}\s+)?([A-Za-z][A-Za-z\s.\-/&]*?)\s*X\s*(\d+)\s*[-_:]?\s*(\d{{2,3}})\s+\d{{2,3}}\s+(\d+)\s+(\d+)\s+{self._UNIT}\s+([\d,.]+)',
                ln, re.I)
            if pm3:
                var = pm3.group(1).strip().upper()
                spb = int(pm3.group(2)); sz = int(pm3.group(3))
                stems = int(pm3.group(5)); price = self._money(pm3.group(6))
                total = round(stems * price, 2)
                # Colors without variety name = surtido mixto in a mixed box
                _COLORS_ONLY = {'WHITE','RED','PINK','YELLOW','ORANGE','CREAM','PEACH',
                                'ASSORTED','SURTIDO','ROSEMIX','MIX'}
                if var in _COLORS_ONLY:
                    il = InvoiceLine(raw_description=ln, species='ROSES', variety='SURTIDO MIXTO', origin='COL',
                                     size=sz, stems_per_bunch=spb, stems=stems,
                                     price_per_stem=price, line_total=total, box_type='MIX')
                    il.match_status = 'mixed_box'
                    il.match_method = 'assorted-no-desglose'
                    lines.append(il)
                    continue
                il = InvoiceLine(raw_description=ln, species='ROSES', variety=var, origin='COL',
                                 size=sz, stems_per_bunch=spb, stems=stems,
                                 price_per_stem=price, line_total=total, box_type=box_type)
                lines.append(il)
                continue
            # Vuelven mixed box sub-line: "0 H Rose Freedom 50 - 50 - ... STEMS STEMS Stems PRICE $TOTAL"
            # Pattern: BOXES=0, Rose VARIETY SIZE - SIZE, then stems and price
            pm4 = re.search(
                r'0\s+(H|Q)\s+Rose\s+([A-Za-z][A-Za-z\s.\-/&]*?)\s+(\d{2,3})\s*-\s*\d{2,3}'
                r'.*?(\d+)\s+(\d+)\s+Stems\s+([\d.]+)\s+\$([\d,.]+)',
                ln, re.I)
            if pm4:
                var = pm4.group(2).strip().upper()
                sz = int(pm4.group(3))
                stems = int(pm4.group(5)); price = float(pm4.group(6))
                total = self._money(pm4.group(7))
                if stems > 0 and total > 0:
                    if re.match(r'(?:ASSORTED|SURTID|MIX)', var, re.I):
                        continue
                    il = InvoiceLine(raw_description=ln, species='ROSES', variety=var, origin='COL',
                                     size=sz, stems_per_bunch=25, stems=stems,
                                     price_per_stem=price, line_total=total, box_type=box_type)
                    lines.append(il)
        return h, lines


class IwaParser:
    """Formato IWA Flowers: BOXES HB/QB STEMS ROSA COLOR VARIETY SIZE CM TARIFF ... Stems STEMS USD$ PRICE USD$ TOTAL
    Ejemplo: "10 HB 350 ROSA RED FREEDOM 50 CM 0603110000 Stems 3500 USD$ 0.280 USD$ 980.00"
             "1 HB 350 ROSA ASSORTED ASSORTED R19- 0603110000 SO R19- Stems 350 USD$ 0.291 USD$ 102.00"
    """
    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'(?:FACTURA|INVOICE)[:\s]+(\w+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'DATE\s+ISSUED\s*([\d\-/]+)', text, re.I); h.date = m.group(1) if m else ''
        lines = []
        for ln in text.split('\n'):
            raw = ln.strip()
            pm = re.search(
                r'(\d+)\s+(HB|QB)\s+\d+\s+ROSA\s+(.+?)\s+(\d{2,3})\s+CM\s+\d{10}\s+'
                r'.*?Stems\s+(\d+)\s+USD\$\s+([\d.]+)\s+USD\$\s+([\d.]+)',
                raw, re.I)
            if not pm:
                continue
            btype = pm.group(2).upper()
            desc = pm.group(3).strip().upper()
            sz = int(pm.group(4)); stems = int(pm.group(5))
            price = float(pm.group(6)); total = float(pm.group(7))
            # Clean variety: strip color prefix for common patterns
            var = re.sub(r'^(?:RED|YELLOW|WHITE|PINK)\s+', '', desc).strip()
            if var in ('ASSORTED', 'MIX'):
                var = 'SURTIDO MIXTO'
            il = InvoiceLine(raw_description=raw, species='ROSES', variety=var, origin='COL',
                             size=sz, stems_per_bunch=25, stems=stems,
                             price_per_stem=price, line_total=total, box_type=btype)
            lines.append(il)
        return h, lines


class TimanaParser:
    """Formato Flores Timana: ROSE VARIETY COLOR SIZE TARIFF BOXES HB BUNCHES SPB STEMS PRICE $ TOTAL
    Ejemplo: "ROSE FREEDOM RED 40CM CO-FREE0603110050 4 HB 12 25 1,200 0.260 $ 312.00"
    """
    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'INVOICE\s+(\d+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'(?:Issue|Ship)\s+Date[:\s]+([\d\-/]+)', text, re.I); h.date = m.group(1) if m else ''
        lines = []
        for ln in text.split('\n'):
            raw = ln.strip()
            pm = re.search(
                r'ROSE\s+([A-Z][A-Z\s.\-/&]+?)\s+(\d{2,3})CM\s+'
                r'\S+\s+'                                    # tariff
                r'(\d+)\s+(HB|QB)\s+'                        # boxes + type
                r'(\d+)\s+(\d+)\s+'                          # bunches + spb
                r'([\d,]+)\s+([\d.]+)\s+\$\s+([\d,.]+)',     # stems + price + total
                raw, re.I)
            if not pm:
                continue
            var = pm.group(1).strip()
            sz = int(pm.group(2))
            btype = pm.group(4).upper()
            spb = int(pm.group(6))
            stems = int(pm.group(7).replace(',', ''))
            price = float(pm.group(8))
            total = float(pm.group(9).replace(',', ''))
            il = InvoiceLine(raw_description=raw, species='ROSES', variety=var, origin='COL',
                             size=sz, stems_per_bunch=spb, stems=stems,
                             price_per_stem=price, line_total=total, box_type=btype)
            lines.append(il)
        return h, lines


class NativeParser:
    """Formato Calinama Capital / Native Flower:
    BOX Farm Box Variety Qty Lengt Stems Price/ TOTAL Label
    Ejemplo: "1 RDC HB VENDELA 12 60 300 $0,300 $90,000"
    """
    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'CUSTOMER\s+INVOICE\s+(\d+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'Date\s*:\s*([\d/\-]+)', text, re.I); h.date = m.group(1) if m else ''
        m = re.search(r'A\.W\.B\.?\s*N[o\xba\s]*[:\s]*([\d\-]+)', text, re.I)
        h.awb = re.sub(r'\s+', '', m.group(1)) if m else ''
        m = re.search(r'H\.A\.W\.B\.?\s*(\S+)', text, re.I); h.hawb = m.group(1) if m else ''
        m = re.search(r'TOTAL\s+\d+\s+\d+\s+\$([\d,.]+)', text)
        h.total = float(m.group(1).replace('.', '').replace(',', '.')) if m else 0.0

        lines = []
        for ln in text.split('\n'):
            ln = ln.strip()
            # "1 RDC HB VENDELA 12 60 300 $0,300 $90,000"
            pm = re.search(
                r'\d+\s+(\w{2,5})\s+(HB|QB|FB)\s+([A-Z][A-Z\s.\-/&]+?)\s+(\d+)\s+(\d{2,3})\s+(\d+)\s+\$([\d,.]+)\s+\$([\d,.]+)',
                ln)
            if not pm:
                continue
            farm = pm.group(1); box_type = pm.group(2)
            var = pm.group(3).strip(); bunches = int(pm.group(4))
            sz = int(pm.group(5)); stems = int(pm.group(6))
            price = float(pm.group(7).replace('.', '').replace(',', '.'))
            total = float(pm.group(8).replace('.', '').replace(',', '.'))
            spb = stems // bunches if bunches else 25
            il = InvoiceLine(raw_description=ln, species='ROSES', variety=var,
                             size=sz, stems_per_bunch=spb, bunches=bunches, stems=stems,
                             price_per_stem=price, line_total=total, box_type=box_type, farm=farm)
            lines.append(il)
        return h, lines


class RosaledaParser:
    """Formato Floricola La Rosaleda:

    Variante A (2026): ORDER BOX_CODE BX BOX_TYPE LABEL VARIETY CM SPB BUNCHES STEMS PRICE TOTAL
      "1 - 1 MARL 1 QB ROSALEDA UNFORGIVEN 50 25 4 100 0.30 30.00"

    Variante B (2024, pipe-separada): pipes "I" como delimitadores
      "1 IQBLR I 50IOM I ALQUIMIA 50CMI $0.300000I $15.00 I 4"
      → stems=50, variety=ALQUIMIA, size=50, price=0.30, total=15.00
    """
    # Variante B: "VARIETY SIZECM" seguido de "I $PRICE I $TOTAL"
    _PIPE_LINE_RE = re.compile(
        r'([A-Z][A-Z\s.\-/&]+?)\s+(\d{2,3})CM'   # variety + size
        r'I\s+\$([\d.]+)I\s+\$([\d.]+)'           # I $price I $total
    )

    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'(?:Invoice\s*#|COMERCIAL)[:\s]*([\d]+)', text, re.I)
        h.invoice_number = m.group(1) if m else ''
        m = re.search(r'Date[:\s]+([\d\-/]+)', text, re.I); h.date = m.group(1) if m else ''
        m = re.search(r'(?:AWB|MAWB)#?[:\s]*([\d\-]+)', text, re.I); h.awb = re.sub(r'\s+', '', m.group(1)) if m else ''
        m = re.search(r'HAWB#?[:\s]*(\S+)', text, re.I); h.hawb = m.group(1) if m else ''
        m = re.search(r'TOTAL\s+FCA\s+(\d+)\s+([\d.]+)\s+([\d.]+)', text)
        h.total = float(m.group(3)) if m else 0.0

        lines = []
        box_type = 'HB'; label = ''

        # Detectar variante por presencia de pipes con $ en el texto
        use_pipe = bool(re.search(r'I\s+\$[\d.]+I', text))

        for ln in text.split('\n'):
            ln = ln.strip()

            if use_pipe:
                # Variante B (pipe): "1 IQBLR I 50IOM I ALQUIMIA 50CMI $0.300000I $15.00 I 4"
                # Box type
                bt = re.search(r'I(QB|HB|FB)', ln)
                if bt: box_type = bt.group(1)
                # Stems: primer número tras pipe después de box_type
                stems_m = re.search(r'(?:QB|HB|FB)\w*\s+I\s*(\d+)I', ln)
                pm = self._PIPE_LINE_RE.search(ln)
                if pm:
                    var = pm.group(1).strip().upper()
                    # Limpiar artefactos del pipe: "IOM I ALQUIMIA" → "ALQUIMIA"
                    var = re.sub(r'^I?\w*\s+I\s+', '', var).strip()
                    sz = int(pm.group(2))
                    price = float(pm.group(3))
                    total = float(pm.group(4))
                    stems = int(stems_m.group(1)) if stems_m else int(round(total / price)) if price else 0
                    spb = 25  # default para rosas
                    bunches = stems // spb if spb else 0
                    il = InvoiceLine(raw_description=ln, species='ROSES', variety=var,
                                     size=sz, stems_per_bunch=spb, bunches=bunches, stems=stems,
                                     price_per_stem=price, line_total=total, box_type=box_type, label=label)
                    lines.append(il)
                continue

            # Variante A: "1 - 1 MARL 1 QB ROSALEDA UNFORGIVEN 50 25 4 100 0.30 30.00"
            pm = re.search(
                r'\d+\s*-\s*\d+\s+(?:([A-Z][A-Z\d]+)\s+)?\d+\s+(QB|HB|FB|EB)\s+(?:ROSALEDA\s+)?([A-Za-z][A-Za-z\s.\-/&]+?)\s+(\d{2,3})\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)\s+([\d.]+)',
                ln)
            if pm:
                if pm.group(1): label = pm.group(1)
                box_type = pm.group(2)
                var = pm.group(3).strip().upper(); sz = int(pm.group(4))
                spb = int(pm.group(5)); bunches = int(pm.group(6))
                stems = int(pm.group(7)); price = float(pm.group(8)); total = float(pm.group(9))
                il = InvoiceLine(raw_description=ln, species='ROSES', variety=var,
                                 size=sz, stems_per_bunch=spb, bunches=bunches, stems=stems,
                                 price_per_stem=price, line_total=total, box_type=box_type, label=label)
                lines.append(il)
                continue
            # Continuación (sin prefijo order): "QUEENS CROWN 50 25 2 50 0.350 17.500"
            pm2 = re.search(
                r'^([A-Z][A-Z\s.\-/&]+?)\s+(\d{2,3})\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)\s+([\d.]+)$',
                ln)
            if pm2 and lines:
                var = pm2.group(1).strip(); sz = int(pm2.group(2))
                spb = int(pm2.group(3)); bunches = int(pm2.group(4))
                stems = int(pm2.group(5)); price = float(pm2.group(6)); total = float(pm2.group(7))
                il = InvoiceLine(raw_description=ln, species='ROSES', variety=var,
                                 size=sz, stems_per_bunch=spb, bunches=bunches, stems=stems,
                                 price_per_stem=price, line_total=total, box_type=box_type, label=label)
                lines.append(il)
        return h, lines


class UniqueParser:
    """Formato Unique Flowers:
    BOX_QTY BOX_TYPE UNIT/BOX PRODUCT SM HTS# UNIT TOTAL_STEMS PRICE BUNCHES PRICE TOTAL
    Ejemplo: "1 HB 350 ROSE ASSORTED R-19 ... Stems 350 US$ 0.30 14 US$ 7.50 US$ 105.00"
    Multi-línea: la siguiente línea tiene "ASSORTED 50 Jesma"
    """
    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'INVOICE[:\s]+(\d+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'DATE\s+ISSUED\s*([\d\-/]+)', text, re.I); h.date = m.group(1) if m else ''
        m = re.search(r'MAWB[:\s]*([\d\-]+)', text, re.I); h.awb = re.sub(r'\s+', '', m.group(1)) if m else ''
        m = re.search(r'HAWB[:\s]*([\d\-]+)', text, re.I); h.hawb = m.group(1) if m else ''
        m = re.search(r'TOTAL\s+US\$\s*([\d,.]+)', text)
        h.total = float(m.group(1).replace(',', '')) if m else 0.0

        lines = []
        text_lines = text.split('\n')
        for i, ln in enumerate(text_lines):
            ln = ln.strip()
            # "1 HB 350 ROSE ASSORTED R-19 ... Stems 350 US$ 0.30 14 US$ 7.50 US$"
            # Siguiente línea: "ASSORTED 50 Jesma 105.00"
            pm = re.search(
                r'(\d+)\s+(HB|QB|FB)\s+(\d+)\s+ROSE\s+(\w[\w\s]*?)\s+(\d{2,3})\s+CM\s+06[\d.]+\s+Stems\s+(\d+)\s+US\$\s+([\d.]+)\s+(\d+)\s+US\$',
                ln, re.I)
            if not pm:
                # Fallback without size: "ROSE ASSORTED R-19 0603..."
                pm = re.search(
                    r'(\d+)\s+(HB|QB|FB)\s+(\d+)\s+ROSE\s+(\w[\w\s]*?)\s+(?:R-?\d+\s+)?(?:\w+\s+)?06[\d.]+\s+Stems\s+(\d+)\s+US\$\s+([\d.]+)\s+(\d+)\s+US\$',
                    ln, re.I)
            if not pm:
                continue
            has_size_in_regex = len(pm.groups()) == 8  # primary regex has 8 groups (incl size)
            box_type = pm.group(2); var = pm.group(4).strip().upper()
            if has_size_in_regex:
                sz_from_regex = int(pm.group(5))
                stems = int(pm.group(6)); price = float(pm.group(7)); bunches = int(pm.group(8))
            else:
                sz_from_regex = 0
                stems = int(pm.group(5)); price = float(pm.group(6)); bunches = int(pm.group(7))
            # Strip color prefix from variety (RED FREEDOM → FREEDOM)
            var = re.sub(r'^(?:RED|WHITE|PINK|YELLOW|ORANGE|CREAM|PEACH)\s+', '', var).strip()
            spb = stems // bunches if bunches else 25
            # Total y tamaño pueden estar al final de esta línea o en la siguiente
            total = 0.0; sz = sz_from_regex or 50
            # Buscar total al final: "US$ 105.00"
            tm = re.search(r'US\$\s*([\d.]+)\s*$', ln)
            if tm:
                total = float(tm.group(1))
            # Buscar en línea siguiente: "ASSORTED 50 [farm] 105.00"
            if i + 1 < len(text_lines):
                nxt = text_lines[i + 1].strip()
                nm = re.search(r'(?:ASSORTED|SURTIDO)?\s*(\d{2,3})\s+\w*\s*([\d.]+)\s*$', nxt)
                if nm:
                    sz = int(nm.group(1))
                    if total == 0:
                        total = float(nm.group(2))
            il = InvoiceLine(raw_description=ln, species='ROSES', variety=var, origin='COL',
                             size=sz, stems_per_bunch=spb, bunches=bunches, stems=stems,
                             price_per_stem=price, line_total=total, box_type=box_type)
            lines.append(il)
        return h, lines


class AposentosParser:
    """Formato Flores de Aposentos (claveles colombianos):
    Box Type Stems Description Criterion Grade Brand Tariff No. Unit Price US Dollars
    Ejemplo: "1 Tabaco 500 CARNATIONS BERNARD NOVELTY DUTY FREE FANCY . CO-0603129000 $0.1700 $85.00"
    """
    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'INVOICE\s+No\.?\s*(\d+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'ISSUE\s+DATE\s*:\s*(.+?)(?:\d{2}:\d{2}|$)', text, re.I)
        h.date = m.group(1).strip() if m else ''
        m = re.search(r'AWB\s+([\d\-]+)', text, re.I); h.awb = re.sub(r'\s+', '', m.group(1)) if m else ''
        m = re.search(r'HAWB\s+([\d\-]+)', text, re.I); h.hawb = m.group(1) if m else ''

        lines = []
        for ln in text.split('\n'):
            ln = ln.strip()
            # Normalización OCR para escaneos ruidosos:
            #   "C0-" (cero) → "CO-", "OUTYFREE" → "DUTYFREE",
            #   "DUTYFREE"/"DUTY FREE" indistintos. El grade puede venir
            #   precedido por ".0" o ".", los precios sin "$" prefix.
            ln_n = re.sub(r'\bC0-', 'CO-', ln)
            ln_n = re.sub(r'\bOUTY\s*FREE?\b', 'DUTYFREE', ln_n, flags=re.I)
            # "1 Tabaco 500 CARNATIONS BERNARD NOVELTY DUTY FREE FANCY . CO-0603129000 $0.1700 $85.00"
            # "12 Taba 6000 CARNATIONS ILIAS YELLOW DUTYFREE FANCY 0 CO-0603129000 0.1600 960.00"  (OCR)
            pm = re.search(
                r'(\d+)\s+Taba\w*\s+(\d+)\s+CARNATIONS\s+(.+?)\s+'
                r'(?:DUTY\s*FREE?|DUTYFREE|REGULAR)\s+(\w+)\s+'
                r'[.0\s]+CO-[\d]+\s+'
                r'\$?([\d.]+)\s+\$?([\d.,]+)',
                ln_n, re.I)
            if not pm:
                continue
            boxes = int(pm.group(1)); stems = int(pm.group(2))
            desc = pm.group(3).strip()
            grade = pm.group(4).strip().upper()  # FANCY, SELECT, etc.
            price = float(pm.group(5)); total = float(pm.group(6).replace(',',''))
            # Separar variedad y color del desc: "BERNARD NOVELTY" -> var=BERNARD, color=NOVELTY
            parts = desc.upper().split()
            var = parts[0] if parts else desc.upper()
            color = ' '.join(parts[1:]) if len(parts) > 1 else ''
            full_var = var
            if color and color not in ('SURTIDOS',):
                full_var = f'{var} {color}'
            spb = stems // (boxes * 20) if boxes else 20  # Claveles: 20 SPB default
            il = InvoiceLine(raw_description=ln, species='CARNATIONS', variety=full_var, origin='COL',
                             size=70, stems_per_bunch=20, stems=stems,
                             price_per_stem=price, line_total=total, box_type='TB', grade=grade)
            lines.append(il)
        # Total from sum of lines
        h.total = sum(l.line_total for l in lines)
        return h, lines


class CustomerInvoiceParser:
    """Plataforma 'CUSTOMER INVOICE' (Cananvalle, Trebol, Much, Naranjo).
    Formato: # BOX_TYPE PRODUCT SPECIES ... QTY_BUNCH $BUNCH_PRICE QTY_STEMS $STEM_PRICE $TOTAL
    Ejemplo: "1 QB CARPE DIEM 40CM A 25ST CV ROSES 5 $10.0000 125 $0.4000 $50.00"
    """
    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'CUSTOMER\s+INVOICE\s+(\d+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'Invoice\s+Date\s+([\d/\-]+)', text, re.I); h.date = m.group(1) if m else ''
        m = re.search(r'MAWB\s+([\d\-\s]+)', text, re.I); h.awb = re.sub(r'\s+', '', m.group(1)).strip() if m else ''
        m = re.search(r'HAWB\s+([\w\-]+)', text, re.I); h.hawb = m.group(1) if m else ''
        m = re.search(r'Amount\s+Due\s+\$([\d,.]+)', text, re.I)
        h.total = float(m.group(1).replace(',', '')) if m else 0.0

        lines = []
        for ln in text.split('\n'):
            ln = ln.strip()
            if 'TOTALS' in ln.upper():
                continue
            # Buscar patrón: QTY_BUNCH $PRICE QTY_STEMS $PRICE $TOTAL al final
            pm = re.search(r'(\d+)\s+\$([\d,.]+)\s+(\d+)\s+\$([\d,.]+)\s+\$([\d,.]+)', ln)
            if not pm:
                continue
            bunches = int(pm.group(1)); stems = int(pm.group(3))
            price = float(pm.group(4).replace(',', '')); total = float(pm.group(5).replace(',', ''))
            spb = stems // bunches if bunches else 25
            # Extraer lo que hay antes de los precios como descripción
            desc_part = ln[:pm.start()].strip()
            # Detectar especie
            species = 'ROSES'
            if 'GYPSOPHILA' in desc_part.upper():
                species = 'GYPSOPHILA'
            elif 'PRESERVED' in desc_part.upper():
                species = 'OTHER'
            # Extraer variedad y tamaño del desc
            # Quitar # inicial, box type, species, label, farm
            desc_clean = re.sub(r'^\d+\s+(?:QB|HB|FB|FBG|SUPER JUMBO)\s+', '', desc_part, flags=re.I)
            desc_clean = re.sub(r'\s+(?:ROSES|GYPSOPHILA|PRESERVED\s+ROSES)\s*$', '', desc_clean, flags=re.I)
            # Extraer tamaño: "40CM", "60CM", "80CM"
            sz_m = re.search(r'(\d{2,3})\s*CM', desc_clean, re.I)
            sz = int(sz_m.group(1)) if sz_m else 0
            # Extraer SPB: "25ST"
            spb_m = re.search(r'(\d+)\s*ST\b', desc_clean, re.I)
            if spb_m:
                spb = int(spb_m.group(1))
            # Limpiar variedad
            var = re.sub(r'\d+\s*CM\b|\d+\s*ST\b|\d+\s*GR\b|[A-Z]{1,2}\d+[\w\-]*|\b\d+\b', '', desc_clean, flags=re.I).strip()
            var = re.sub(r'\s+', ' ', var).strip().upper()
            # Quitar farm/label trailing words
            var = re.sub(r'\s+(?:P\w+|F|FC|A|CV|PT|PRAS|VERALEZA|Cotacachi|Exportcalas)\s*$', '', var, flags=re.I).strip()
            if not var or var in ('TOTALS', 'MIXED BOX'):
                continue
            bt_m = re.search(r'(QB|HB|FB|FBG)', desc_part, re.I)
            box_type = bt_m.group(1).upper() if bt_m else 'HB'
            il = InvoiceLine(raw_description=ln, species=species, variety=var,
                             size=sz, stems_per_bunch=spb, bunches=bunches, stems=stems,
                             price_per_stem=price, line_total=total, box_type=box_type)
            lines.append(il)
        return h, lines


class PremiumColParser:
    """Formato Premium Flowers of Boyacá (claveles colombianos).
    Multi-línea: "1 QB 500 25 CARNATION DESC SIZE LABEL HTS# Stems STEMS US$ PRICE US$ PRICE US$"
    seguido de "TOTAL" en la siguiente línea.
    Ejemplo: "1 QB 500 25 CARNATION MIX 55 CM R14 0603.12.7000 Stems 500 US$ 0.130 US$ 2.600 US$\\n65.00"
    """
    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'SHIPMENT\s+INVOICE\s+(\d+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'DATE\s+ISSUED\s+(?:DUE\s+DATE\s+)?.*?(\d{4}-\d{2}-\d{2})', text, re.I)
        h.date = m.group(1) if m else ''
        m = re.search(r'MAWB\s*#?\s*([\d\-\s]+)', text, re.I); h.awb = re.sub(r'\s+', '', m.group(1)).strip() if m else ''
        m = re.search(r'HAWB\s*#?\s*([\d\-]+)', text, re.I); h.hawb = m.group(1) if m else ''
        m = re.search(r'TOTAL\s+US\$\s*([\d,.]+)', text); h.total = float(m.group(1).replace(',', '')) if m else 0.0

        lines = []
        text_lines = text.split('\n')
        for i, ln in enumerate(text_lines):
            ln = ln.strip()
            # "1 QB 500 25 CARNATION MIX 55 CM R14 0603.12.7000 Stems 500 US$ 0.130 US$ 2.600 US$"
            pm = re.search(
                r'(\d+)\s+(QB|HB)\s+(\d+)\s+(\d+)\s+CARNATION\s+(.+?)\s+06[\d.]+\s+Stems\s+(\d+)\s+US\$\s+([\d.]+)\s+US\$',
                ln, re.I)
            if not pm:
                continue
            boxes = int(pm.group(1)); box_type = pm.group(2)
            unit_box = int(pm.group(3)); spb_raw = int(pm.group(4))
            desc = pm.group(5).strip(); stems = int(pm.group(6)); price = float(pm.group(7))
            # Total en siguiente línea
            total = 0.0
            if i + 1 < len(text_lines):
                tm = re.search(r'^\s*([\d,.]+)\s*$', text_lines[i + 1])
                if tm:
                    total = float(tm.group(1).replace(',', ''))
            if total == 0:
                total = round(stems * price, 2)
            # Extraer variedad y color/size del desc: "MIX 55 CM R14", "WHITE MOONLIGHT 55 CM R14"
            desc = re.sub(r'\s+\d+\s*CM\b', '', desc, flags=re.I)  # quitar size
            desc = re.sub(r'\s+R\d+', '', desc)  # quitar label
            desc = re.sub(r'\s+\w*VERALEZA\w*', '', desc, flags=re.I)  # quitar label
            desc = re.sub(r'\s+SHORT\b', '', desc, flags=re.I)
            var = desc.strip().upper()
            sz_m = re.search(r'(\d{2})\s*CM', pm.group(5), re.I)
            sz = int(sz_m.group(1)) if sz_m else 55  # default carnation 55cm
            il = InvoiceLine(raw_description=ln, species='CARNATIONS', variety=var, origin='COL',
                             size=sz, stems_per_bunch=spb_raw, stems=stems,
                             price_per_stem=price, line_total=total, box_type=box_type)
            lines.append(il)
        return h, lines


class DomenicaParser:
    """Formato simple: Boxes HB/QB VARIETY SIZEcm SPB BUNCHES STEMS PRICE TOTAL
    Precios con coma decimal.
    Ejemplo: "1 HB EXPLORER 80cm 25 10 250 1,10 275,00"
    """
    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'INVOICE\s*#\s*(\d+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'Date[:\s]+([\d/\-]+)', text, re.I); h.date = m.group(1) if m else ''
        m = re.search(r'AWB[:\s]*([\d\-\s]+)', text, re.I); h.awb = re.sub(r'\s+', '', m.group(1)).strip() if m else ''
        m = re.search(r'HAWB[:\s]*(\S+)', text, re.I); h.hawb = m.group(1) if m else ''
        m = re.search(r'GRAND\s+TOTAL[:\s]*([\d.,]+)', text, re.I)
        h.total = float(m.group(1).replace('.', '').replace(',', '.')) if m else 0.0

        lines = []
        for ln in text.split('\n'):
            ln = ln.strip()
            pm = re.search(
                r'\d+\s+(HB|QB|FB|EB)\s+([A-Za-z][A-Za-z\s.\-/&]+?)\s+(\d{2,3})\s*cm\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d,]+)\s+([\d,]+)',
                ln, re.I)
            if not pm:
                continue
            box_type = pm.group(1); var = pm.group(2).strip().upper()
            sz = int(pm.group(3)); spb = int(pm.group(4))
            bunches = int(pm.group(5)); stems = int(pm.group(6))
            price = float(pm.group(7).replace('.', '').replace(',', '.'))
            total = float(pm.group(8).replace('.', '').replace(',', '.'))
            il = InvoiceLine(raw_description=ln, species='ROSES', variety=var,
                             size=sz, stems_per_bunch=spb, bunches=bunches, stems=stems,
                             price_per_stem=price, line_total=total, box_type=box_type)
            lines.append(il)
        return h, lines


class InvosParser:
    """Formato Invos Flowers: líneas concatenadas sin espacio.
    Ejemplo: "1Rose Freedom 50 - 28 6 Half 3 2100 0,80 1680,00"
    = Box, Flower, Variety, Size, -, Label, Bunches, BoxType, FBE, Stems, Price, Total
    """
    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'Invoice\s+(\w+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'Date\s+Invoice\s+([\d/\-]+)', text, re.I); h.date = m.group(1) if m else ''
        m = re.search(r'AWB\s+([\d\-]+)', text, re.I); h.awb = re.sub(r'\s+', '', m.group(1)) if m else ''
        m = re.search(r'AMOUNT\s+([\d.,]+)', text, re.I)
        h.total = float(m.group(1).replace('.', '').replace(',', '.')) if m else 0.0

        lines = []
        for ln in text.split('\n'):
            ln = ln.strip()
            # "1Rose Freedom 50 - 28 6 Half 3 2100 0,80 1680,00"
            pm = re.search(
                r'\d+Rose\s+([A-Za-z][A-Za-z\s.\-/&]+?)\s+(\d{2,3})\s+-\s+\S+\s+(\d+)\s+Half\s+[\d.,]+\s+(\d+)\s+([\d,]+)\s+([\d,]+)',
                ln, re.I)
            if not pm:
                continue
            var = pm.group(1).strip().upper(); sz = int(pm.group(2))
            bunches = int(pm.group(3)); stems = int(pm.group(4))
            price = float(pm.group(5).replace('.', '').replace(',', '.'))
            total = float(pm.group(6).replace('.', '').replace(',', '.'))
            spb = stems // bunches if bunches else 25
            il = InvoiceLine(raw_description=ln, species='ROSES', variety=var, origin='COL',
                             size=sz, stems_per_bunch=spb, bunches=bunches, stems=stems,
                             price_per_stem=price, line_total=total, box_type='HB')
            lines.append(il)
        return h, lines


class MeaflosParser:
    """Formato Meaflos: multi-línea con farm encima. Líneas de producto:
    "Rosas - VARIETY SIZEcm GW CW STEMS PRICE TOTAL"
    Ejemplo: "Rosas - Explorer 50cm 0,00 0,00 400 0,73 292,00"
    """
    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'Invoice\s+No\.?[:\s]*([\w]+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'INVOICE\s+DATE[:\s]*([\d\-/]+)', text, re.I); h.date = m.group(1) if m else ''
        m = re.search(r'A\.W\.B\.?[:\s]*([\d\-]+)', text, re.I); h.awb = re.sub(r'\s+', '', m.group(1)) if m else ''
        m = re.search(r'TOTAL\s+(?:VALUE|PRICE)[:\s]*([\d.,]+)', text, re.I)
        h.total = float(m.group(1).replace('.', '').replace(',', '.')) if m else 0.0

        lines = []
        for ln in text.split('\n'):
            ln = ln.strip()
            # "Rosas - Explorer 50cm 0,00 0,00 400 0,73 292,00"
            pm = re.search(
                r'Rosas?\s*-\s*([A-Za-z][A-Za-z\s.\-/&]+?)\s+(\d{2,3})\s*cm\s+[\d,]+\s+[\d,]+\s+(\d+)\s+([\d,]+)\s+([\d,]+)',
                ln, re.I)
            if not pm:
                continue
            var = pm.group(1).strip().upper(); sz = int(pm.group(2))
            stems = int(pm.group(3))
            price = float(pm.group(4).replace('.', '').replace(',', '.'))
            total = float(pm.group(5).replace('.', '').replace(',', '.'))
            spb = 25
            il = InvoiceLine(raw_description=ln, species='ROSES', variety=var,
                             size=sz, stems_per_bunch=spb, stems=stems,
                             price_per_stem=price, line_total=total, box_type='HB')
            lines.append(il)
        return h, lines


class HeraflorParser:
    """Formato Heraflor: líneas concatenadas con farm.
    Ejemplo: "1Rose Explorer Juma Flowers 50cm 0,5 0,5 1 300 300 $ 0,33 $ 99,00"
    """
    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'Invoice\s+n[o\xba][:\s]*(\S+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'Date[:\s]+([\d\-\w]+)', text, re.I); h.date = m.group(1) if m else ''
        m = re.search(r'AWB[:\s]*([\d\-\s]+)', text, re.I); h.awb = re.sub(r'\s+', '', m.group(1)).strip() if m else ''
        m = re.search(r'Total\s+\$\s*([\d.,]+)', text, re.I)
        h.total = float(m.group(1).replace('.', '').replace(',', '.')) if m else 0.0

        lines = []
        for ln in text.split('\n'):
            ln = ln.strip()
            # "1Rose Explorer Juma Flowers 50cm 0,5 0,5 1 300 300 $ 0,33 $ 99,00"
            pm = re.search(
                r'\d+Rose\s+([A-Za-z][A-Za-z\s.\-/&]+?)\s+(\d{2,3})\s*cm\s+[\d,]+\s+[\d,]+\s+\d+\s+\d+\s+(\d+)\s+\$\s*([\d,]+)\s+\$\s*([\d,]+)',
                ln, re.I)
            if not pm:
                continue
            # Variety includes farm name, need to separate: "Explorer Juma Flowers" -> var=EXPLORER, farm=Juma Flowers
            desc = pm.group(1).strip()
            # Farm is typically 2+ words after variety
            parts = desc.split()
            var = parts[0].upper() if parts else desc.upper()
            farm = ' '.join(parts[1:]) if len(parts) > 1 else ''
            sz = int(pm.group(2)); stems = int(pm.group(3))
            price = float(pm.group(4).replace('.', '').replace(',', '.'))
            total = float(pm.group(5).replace('.', '').replace(',', '.'))
            il = InvoiceLine(raw_description=ln, species='ROSES', variety=var,
                             size=sz, stems_per_bunch=25, stems=stems,
                             price_per_stem=price, line_total=total, box_type='HB', farm=farm)
            lines.append(il)
        return h, lines


class InfinityParser:
    """Formato Infinity Trading: colombiano con bunches y price/bunch.
    Ejemplo: "5 HF ROSA FREEDOM GRA 70 ATPDEA0603.11.00.00 25 1250 1.000 50 25.000 1,250.00"
    """
    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'INV(\d+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'Date\s+([\d\-/]+)', text, re.I); h.date = m.group(1) if m else ''
        m = re.search(r'AWB\s+([\d\-]+)', text, re.I); h.awb = re.sub(r'\s+', '', m.group(1)) if m else ''
        m = re.search(r'HAWB[:\s]*([\d\-]+)', text, re.I); h.hawb = m.group(1) if m else ''

        lines = []
        for ln in text.split('\n'):
            ln = ln.strip()
            # "5 HF ROSA FREEDOM GRA 70 ATPDEA0603.11.00.00 25 1250 1.000 50 25.000 1,250.00"
            pm = re.search(
                r'(\d+)\s+(?:HF|QF|HB|QB|Full|Half)\s+ROSA\s+([A-Z][A-Z\s.\-/&]+?)\s+(?:GRA\s+)?(\d{2,3})\s+\w*06[\d.]+\s+(\d+)\s+(\d+)\s+[\d.]+\s+(\d+)\s+[\d.]+\s+([\d,.]+)',
                ln, re.I)
            if not pm:
                continue
            boxes = int(pm.group(1)); var = pm.group(2).strip()
            sz = int(pm.group(3)); spb = int(pm.group(4))
            stems = int(pm.group(5)); bunches = int(pm.group(6))
            total = float(pm.group(7).replace(',', ''))
            price = total / stems if stems else 0
            il = InvoiceLine(raw_description=ln, species='ROSES', variety=var, origin='COL',
                             size=sz, stems_per_bunch=spb, bunches=bunches, stems=stems,
                             price_per_stem=round(price, 4), line_total=total, box_type='HB')
            lines.append(il)
        h.total = sum(l.line_total for l in lines)
        return h, lines


class ProgresoParser:
    """Formato Flores El Progreso:
    "CO-0603110060 ROSA FREEDOM 50 CM 25 HB 350 8,750 0.7800 6,825.00"
    """
    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'INVOICE.*?No\.?\s*(\d+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'Date\s*:\s*([\d\-\w.]+)', text, re.I); h.date = m.group(1) if m else ''
        m = re.search(r'MAWB\s*:\s*([\d\-]+)', text, re.I); h.awb = m.group(1) if m else ''
        m = re.search(r'HAWB\s*:\s*([\d\-]+)', text, re.I); h.hawb = m.group(1) if m else ''
        m = re.search(r'TOTAL\s*:\s*([\d,.]+)', text)
        h.total = float(m.group(1).replace(',', '')) if m else 0.0

        lines = []
        for ln in text.split('\n'):
            ln = ln.strip()
            pm = re.search(
                r'CO-[\d]+\s+ROSA\s+([A-Z][A-Z\s.\-/&]+?)\s+(\d{2,3})\s*CM\s+(\d+)\s+(HB|QB|FB)\s+(\d+)\s+([\d,.]+)\s+([\d.]+)\s+([\d,.]+)',
                ln, re.I)
            if not pm:
                continue
            var = pm.group(1).strip(); sz = int(pm.group(2))
            spb = int(pm.group(3)); box_type = pm.group(4)
            stems_box = int(pm.group(5))
            stems_total = int(pm.group(6).replace(',', ''))
            price = float(pm.group(7)); total = float(pm.group(8).replace(',', ''))
            il = InvoiceLine(raw_description=ln, species='ROSES', variety=var, origin='COL',
                             size=sz, stems_per_bunch=spb, stems=stems_total,
                             price_per_stem=price, line_total=total, box_type=box_type)
            lines.append(il)
        return h, lines


class ColonParser:
    """Formato C.I. Flores Colon (claveles colombianos):
    "10T 5000FA CAR BU x 20 Stems (T) 500 FREE CO-0603.12.7000 0.18000 900.00"
    """
    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'PACKING LIST No\s*(\d+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'DATE:\s*(.+?)$', text, re.M); h.date = m.group(1).strip() if m else ''
        m = re.search(r'GRAND\s+TOTAL\s+INVOICE\s+US\$\s*([\d,.]+)', text)
        h.total = float(m.group(1).replace(',', '')) if m else 0.0

        lines = []
        for ln in text.split('\n'):
            ln = ln.strip()
            # "10T 5000FA CAR BU x 20 Stems (T) 500 FREE CO-0603.12.7000 0.18000 900.00"
            pm = re.search(
                r'(\d+)T\s+(\d+)(\w{2})\s+CAR\s+(\w+)\s+x\s+(\d+)\s+Stems\s+\(T\)\s+(\d+)\s+FREE\s+CO-[\d.]+\s+([\d.]+)\s+([\d,.]+)',
                ln, re.I)
            if not pm:
                continue
            boxes = int(pm.group(1)); stems = int(pm.group(2))
            grade = pm.group(3).upper()  # FA=FANCY, SE=SELECT
            color = pm.group(4).strip().upper()  # BU=bicolor, WH=white, RD=red
            spb = int(pm.group(5)); stems_box = int(pm.group(6))
            price = float(pm.group(7)); total = float(pm.group(8).replace(',', ''))
            color_map = {'WH': 'WHITE', 'RD': 'RED', 'BU': 'BICOLOR', 'PK': 'PINK', 'YE': 'YELLOW', 'OR': 'ORANGE', 'GR': 'GREEN', 'PP': 'PURPLE'}
            var = color_map.get(color, color)
            grade_map = {'FA': 'FANCY', 'SE': 'SELECT', 'ST': 'STANDARD'}
            il = InvoiceLine(raw_description=ln, species='CARNATIONS', variety=var, origin='COL',
                             size=70, stems_per_bunch=spb, stems=stems,
                             price_per_stem=price, line_total=total, box_type='TB',
                             grade=grade_map.get(grade, grade))
            lines.append(il)
        return h, lines


class AguablancaParser:
    """Formato Agrícola Aguablanca (claveles):
    "VERALEZA CARNATION STD MIX 3,50 7 HB 500 0603129000 SO 3.500 0,130 455,00"
    """
    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'INVOICE\s*#\s*(\d+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'Date/Fecha\s*(\S+)', text, re.I); h.date = m.group(1) if m else ''
        m = re.search(r'AWB[#\s]*/?\s*[\w\s]*(\d{3}-\d+)', text, re.I); h.awb = m.group(1) if m else ''
        m = re.search(r'INVOICE\s+TOTAL\s+US\$\s*([\d,.]+)', text)
        h.total = float(m.group(1).replace(',', '')) if m else 0.0

        lines = []
        for ln in text.split('\n'):
            ln = ln.strip()
            # "VERALEZA CARNATION STD MIX 3,50 7 HB 500 0603129000 SO 3 .500 0,130 4 55,00"
            pm = re.search(
                r'CARNATION\s+(\w+)\s+(\w+)\s+[\d,]+\s+(\d+)\s+(HB|QB)\s+(\d+)\s+\d+\s+\w+\s+[\d\s.]+\s+([\d,]+)\s+[\d\s]*([\d,]+)',
                ln, re.I)
            if not pm:
                continue
            grade = pm.group(1).upper(); color = pm.group(2).upper()
            bunches = int(pm.group(3)); box_type = pm.group(4)
            stems_box = int(pm.group(5))
            price = float(pm.group(6).replace('.', '').replace(',', '.'))
            total = float(pm.group(7).replace('.', '').replace(',', '.'))
            stems = bunches * stems_box  # rough estimate
            il = InvoiceLine(raw_description=ln, species='CARNATIONS', variety=color, origin='COL',
                             size=70, stems_per_bunch=20, stems=stems_box * bunches,
                             price_per_stem=price, line_total=total, box_type=box_type,
                             grade=grade)
            lines.append(il)
        return h, lines


class SuccessParser:
    """Formato Success Flowers (colombiano, OCR). Texto viene de OCR y puede tener ruido.
    Líneas: "8 2400 TALLOS ROSA FREEDOM GR 50 ... 0.40 ... 960.00"
    Campos: BUNCHES STEMS TALLOS ROSA VARIETY GR SIZE ... PRICE_STEM ... TOTAL_USD
    """
    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'(?:FACTURA|No\.?)\s*(?:SF\s*)?(\d{3,})', text, re.I)
        h.invoice_number = m.group(1) if m else ''
        m = re.search(r'GUIA\s+MASTER\s+([\d\-]+)', text, re.I); h.awb = m.group(1) if m else ''
        m = re.search(r'GUIA\s+HIJA\s+([\d\-]+)', text, re.I); h.hawb = m.group(1) if m else ''
        m = re.search(r'FECHA.*?(\d{1,2}\s+DE\s+\w+\s+DE\s+\d{4})', text, re.I)
        h.date = m.group(1) if m else ''

        lines = []
        text_lines = text.split('\n')
        for i, ln in enumerate(text_lines):
            ln = ln.strip()
            # OCR multi-línea: "2400 TALLOS ROSA FREEDOM GR 50"
            # Bunches en la línea anterior, price 2 líneas después, total 4 después
            pm = re.search(r'(\d+)\s+TALLOS\s+ROSA\s+([A-Z][A-Z\s.\-/&]+?)\s+(?:GR\s+)?(\d{2,3})', ln, re.I)
            if not pm:
                continue
            stems = int(pm.group(1)); var = pm.group(2).strip().upper()
            sz = int(pm.group(3))
            # Bunches: línea anterior
            bunches = 0
            if i > 0:
                bm = re.match(r'^(\d+)$', text_lines[i - 1].strip())
                if bm:
                    bunches = int(bm.group(1))
            spb = stems // bunches if bunches else 25
            # Price: buscar en líneas i+1 a i+5 un número decimal < 10
            price = 0.0; total = 0.0
            for j in range(i + 1, min(i + 6, len(text_lines))):
                val_s = text_lines[j].strip().replace(',', '')
                try:
                    val = float(val_s)
                except ValueError:
                    continue
                if 0 < val < 10 and price == 0:
                    price = val
                elif val > 10 and total == 0 and price > 0:
                    total = val
                    break
            if total == 0 and price > 0:
                total = round(stems * price, 2)
            il = InvoiceLine(raw_description=ln, species='ROSES', variety=var, origin='COL',
                             size=sz, stems_per_bunch=spb, bunches=bunches, stems=stems,
                             price_per_stem=price, line_total=total, box_type='HB')
            lines.append(il)
        h.total = sum(l.line_total for l in lines)
        return h, lines
