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
    # Regex: línea principal con ORDER MARK BX BOXTYPE.
    # El prefijo de tipo (GARDEN ROSE / ROSE / SPRAY ROSES / TINTED) es
    # OPCIONAL — algunas variantes del formato omiten "ROSE" antes del
    # nombre de la variedad ("EXPLORER 50 ..." en vez de "ROSE EXPLORER 50 ...").
    _MAIN_RE = re.compile(
        r'(\d+)\s*-\s*\d*\s+'             # ORDER range: "1 - 1", "3 - 4"
        r'(.+?)\s+'                       # MARK (farm name): "RICC ROSES"
        r'(\d+)\s+(HB|QB|TB)\s+'          # BX count + BOX TYPE
        r'((?:GARDEN\s+ROSE\s+'           # "GARDEN ROSE "
        r'|SPRAY\s+ROSES?\s+(?:SPR\s+)?'  # "SPRAY ROSES SPR "
        r'|TINTED\s+'                     # "TINTED "
        r'|ROSE\s+'                       # "ROSE "
        r')?)'                            # prefix opcional
        r'(.+?)\s+'                       # VARIETY
        r'(\d{2,3})\s+'                   # CM (talla)
        r'(\d+)\s+(\d+)\s+'               # STEMS per box, TOTAL STEMS
        r'([\d.]+)\s+([\d.]+)',           # UNIT PRICE, TOTAL PRICE
        re.I
    )
    # Regex: línea de continuación (sin ORDER/MARK).
    # Prefijo opcional por la misma razón.
    _CONT_RE = re.compile(
        r'^((?:GARDEN\s+ROSE\s+'
        r'|SPRAY\s+ROSES?\s+(?:SPR\s+)?'
        r'|TINTED\s+'
        r'|ROSE\s+'
        r')?)'
        r'([A-Z][A-Z0-9 \-]+?)\s+'        # variedad (anclado en mayúsculas
                                          # para no devorar texto narrativo)
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
        # Total: preferir "Sub Total XXXX.XXX" (grand total real); el
        # primer "TOTAL" suele ser la fila de totales-de-stems
        # ("TOTAL 6700 0.286 1918.00") y capturaría el stems count.
        m = re.search(r'Sub\s+Total\s+([\d,.]+)', text, re.I)
        if not m:
            m = re.search(r'Total\s+([\d,.]+)', text, re.I)
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

            # Wrap del color de variedad TINTED. La celda VARIETIES tiene
            # "ROSE TINTED ROS TINTED\nRAINBOW" → en extract_text aparece
            # como una línea adicional con solo el color (a veces seguido
            # de un "0" residual de otra columna que también envuelve).
            # El parser limpia "TINTED ROS TINTED" → "TINTED", quedando
            # sin color. Si la siguiente línea es una palabra MAYUS al
            # inicio (no "ROSES" para evitar el wrap del FARM) y la
            # variedad anterior es TINTED escueta, la apendizamos.
            if lines:
                wrap_m = re.match(
                    r'^([A-ZÑÁÉÍÓÚ][A-ZÑÁÉÍÓÚ0-9\-]{2,19})(?:\s+\d+)?\s*$',
                    raw,
                )
                if wrap_m:
                    color = wrap_m.group(1)
                    last = lines[-1]
                    last_var = (last.variety or '').upper()
                    if last_var == 'TINTED' and color != 'ROSES':
                        last.variety = f'TINTED {color}'
                        last.raw_description = f'{last.raw_description} {color}'
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

        # Fix known truncations y typos del proveedor
        if var == 'HIGH AND':
            var = 'HIGH AND MAGIC'
        elif var == 'ULTRA FREEDOM':
            var = 'FREEDOM'
        # TOFFE (BRISSAS) → TOFEE (catálogo). Typo común del proveedor.
        var = re.sub(r'\bTOFFE\b', 'TOFEE', var)

        return var


class TurflorParser:
    """Formato Turflor — dos variantes de layout:

    Variante A (inline, todo en una línea):
        "1 HB Spray Carnation Rainbow - Select R19 - - 500 500 Stems $0.180 $90.00"
        "1 HB Carnation Orange - Fancy - - 500 500 Stems $0.170 $85.00"

    Variante B (wrapped, descripción en línea N, datos en N+1, a veces
    grade repetido en N+2):
        línea N:   "SPRAY CARNATION ASSORTED SELECT -"
        línea N+1: "1 QB GIJON - - 250 250 Stems $0.180 $45.00"
        línea N+2: "Select"

    En variante B la columna "DESCRIPTION" de la línea N+1 queda vacía/
    con guión y el "Box_ID" (GIJON/FVIDA/R19/GONZA) termina en el hueco
    de descripción. Para reconstruir correctamente hay que mirar la
    línea anterior buffered.

    Variedad de salida: solo el color (MIXTO/RAINBOW/BLANCO/NARANJA/...)
    sin prefijo CARNATION/SPRAY CARNATION — es el species (CARNATIONS)
    + spb (10 spray, 20 regular) lo que el matcher usa para distinguir
    mini claveles de claveles regulares contra el catálogo MINI CLAVEL.
    """
    _GRADES = {'FANCY', 'SELECT', 'STANDARD', 'STD', 'ESTANDAR'}
    _GRADE_MAP = {'STANDARD': 'ESTANDAR', 'STD': 'ESTANDAR'}

    # Default sizes por grade (según catálogo TURFLOR):
    #   ESTANDAR → 60CM · FANCY/SELECT → 70CM · spray(mini) → 70CM
    _SIZE_BY_GRADE = {'ESTANDAR': 60, 'FANCY': 70, 'SELECT': 70}
    _DEFAULT_SIZE = 70

    def parse(self, text: str, pdata: dict):
        from src.config import translate_carnation_color
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'INVOICE\s+Nro\.?\s*(\S+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'Date\s+Invoice\s+([\d/]+)', text, re.I); h.date = m.group(1) if m else ''
        m = re.search(r'AWB\s+([\d\-]+)', text, re.I); h.awb = re.sub(r'\s+', '', m.group(1)) if m else ''
        m = re.search(r'HAWB\s+([\w\-]+)', text, re.I); h.hawb = m.group(1) if m else ''
        m = re.search(r'INVOICE\s+TOTAL\s+US\$\s*([\d,.]+)', text, re.I)
        h.total = float(m.group(1).replace(',', '')) if m else 0.0

        lines = []
        pending_desc = ''  # Desc wrapped de línea anterior (variante B)

        for ln in text.split('\n'):
            raw = ln.strip()
            if not raw:
                continue

            # Detectar línea de wrap: "SPRAY CARNATION X GRADE -" sin $ total
            # Se guarda y se consume al llegar la siguiente línea de datos.
            if re.match(r'(?:SPRAY\s+)?CARNATION\s+', raw, re.I) and not re.search(r'\$[\d.,]+\s*$', raw):
                pending_desc = re.sub(r'[\s-]+$', '', raw).strip()
                continue

            # Variante A: con tarifa 0603.xx (histórico)
            pm = re.search(
                r'(\d+)\s+(H|Q)\s+'
                r'((?:SPRAY\s+)?CARNATION\s+.+?)\s+'
                r'0603[\d.]+\s+'
                r'([\d,]+)\s+([\d,]+)\s+Stems\s+'
                r'([\d.]+)\s+\$([\d,.]+)',
                raw, re.I)
            if pm:
                btype = 'HB' if pm.group(2).upper() == 'H' else 'QB'
                desc = pm.group(3).strip()
                stems = int(pm.group(5).replace(',', ''))
                try:
                    price = float(pm.group(6)); total = float(pm.group(7).replace(',', ''))
                except Exception:
                    price = 0.0; total = 0.0
                il = self._build_line(raw, desc, btype, stems, price, total, pdata, translate_carnation_color)
                if il:
                    lines.append(il)
                pending_desc = ''
                continue

            # Variante B: HB/QB sin tarifa. "1 HB <desc> <dashes?> N N Stems $P $T"
            pm_b = re.search(
                r'(\d+)\s+(HB|QB|H|Q)\s+'
                r'(.*?)'
                r'(\d[\d,]*)\s+(\d[\d,]*)\s+Stems\s+'
                r'\$([\d.]+)\s+\$([\d,.]+)',
                raw, re.I)
            if not pm_b:
                continue

            btype_raw = pm_b.group(2).upper()
            btype = 'HB' if btype_raw in ('H', 'HB') else 'QB'
            desc = re.sub(r'[\s-]+$', '', pm_b.group(3)).strip()
            stems = int(pm_b.group(5).replace(',', ''))
            try:
                price = float(pm_b.group(6)); total = float(pm_b.group(7).replace(',', ''))
            except Exception:
                price = 0.0; total = 0.0

            # Si el desc de esta línea no contiene CARNATION pero la línea
            # anterior era un wrap de descripción, merge: el desc real va
            # delante y lo de aquí (GIJON/FVIDA/etc.) queda como label.
            d_upper = desc.upper()
            d_upper = re.sub(r'\s+-\s+', ' ', d_upper).strip()
            if 'CARNATION' not in d_upper and pending_desc:
                merged_desc = pending_desc
                box_label = d_upper.strip(' -')
                il = self._build_line(raw, merged_desc, btype, stems, price, total,
                                       pdata, translate_carnation_color,
                                       label_override=box_label)
            else:
                il = self._build_line(raw, desc, btype, stems, price, total,
                                       pdata, translate_carnation_color)
            if il:
                lines.append(il)
            pending_desc = ''

        return h, lines

    def _build_line(self, raw: str, desc: str, btype: str, stems: int,
                     price: float, total: float, pdata: dict,
                     color_translate, label_override: str | None = None):
        """Construye una InvoiceLine limpia a partir de la descripción.

        La variedad resultante es **solo el color** traducido al español
        (MIXTO/NARANJA/RAINBOW/...), sin prefijo CARNATION/SPRAY CARNATION.
        El species + spb (10 spray, 20 regular) identifican al matcher que
        debe buscar en MINI CLAVEL vs CLAVEL del catálogo.
        """
        d = desc.upper()
        d = re.sub(r'\s+-\s+', ' ', d).strip()
        is_spray = d.startswith('SPRAY ')
        has_carnation = 'CARNATION' in d

        if has_carnation:
            d2 = re.sub(r'^SPRAY\s+CARNATION\s+', '', d) if is_spray else re.sub(r'^CARNATION\s+', '', d)
            tokens = d2.split()
            variety_parts = []
            grade = ''
            inline_label = ''
            for i, tok in enumerate(tokens):
                if tok in self._GRADES:
                    grade = self._GRADE_MAP.get(tok, tok)
                    inline_label = ' '.join(tokens[i+1:]).strip(' -')
                    break
                variety_parts.append(tok)
            color_raw = ' '.join(variety_parts) if variety_parts else 'ASSORTED'
        else:
            # Sin CARNATION en desc y sin pending_desc: no es una factura
            # válida de clavel, skip. (pending_desc ya se manejó arriba.)
            return None

        variety = color_translate(color_raw)
        if not variety:
            variety = color_raw

        label = label_override if label_override is not None else inline_label
        spb = 10 if is_spray else 20
        size = self._SIZE_BY_GRADE.get(grade, self._DEFAULT_SIZE)

        return InvoiceLine(
            raw_description=raw, species='CARNATIONS', variety=variety,
            origin='COL', size=size, stems_per_bunch=spb, stems=stems,
            grade=grade, price_per_stem=price, line_total=total,
            box_type=btype, label=label, provider_key=pdata['key'],
        )


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
        # Línea de datos colgada que aún no tiene grade — el grade
        # ("Selecto" / "Fancy") aparece en la 3ª línea junto al tariff:
        #   'Alstroemeria Virginia/Dubai - CO-'
        #   '1 QB - - 200 200 Stems $0.180 $36.00'
        #   'Selecto 0603190107'
        grade_pending_il = None
        for ln in text.split('\n'):
            ln=ln.strip()
            if not ln:
                continue

            # Si quedó una línea esperando grade (colgada sin grade inline)
            # y esta línea empieza con Selecto/Fancy/Super, completarla.
            # Formato típico: "Selecto ASTURIAS 0603190107" — el label
            # puede ir entre el grade y el tariff numérico.
            if grade_pending_il is not None:
                gm = re.match(r'^(Selecto|Select|Fancy|Super\s+Selecto|Super\s+Select)\b\s*(.*)$',
                              ln, re.I)
                if gm:
                    g = gm.group(1).upper()
                    rest = gm.group(2).strip()
                    if 'SUPER' in g:
                        grade_pending_il.grade = 'SUPERSELECT'
                    elif g.startswith('SELECTO') or g.startswith('SELECT'):
                        grade_pending_il.grade = 'SELECT'
                    else:
                        grade_pending_il.grade = 'FANCY'
                    # Label entre grade y tariff numérico (ej. "ASTURIAS
                    # 0603190107"). Solo si la línea pendiente aún no
                    # tenía label (no pisar el label inline).
                    if not (grade_pending_il.label or '').strip():
                        rest_no_tariff = re.sub(r'\b\d{6,}\S*\s*$', '',
                                                rest).strip()
                        rest_no_tariff = re.sub(r'^MARCA\s+', '',
                                                rest_no_tariff,
                                                flags=re.I).strip()
                        if rest_no_tariff and re.fullmatch(
                                r'[A-Za-z][A-Za-z\s\.\-]*', rest_no_tariff):
                            grade_pending_il.label = rest_no_tariff.upper()
                    grade_pending_il = None
                    continue
                else:
                    grade_pending_il = None

            # Formato cabecera-colgada: descripción en una línea sin números finales.
            hdr_m = re.match(
                r'^(Alstroemeria|Roses?|Carnations?|Hydrangeas?|Chrysanth\w*|Gypsophila)\s+'
                r'(.+?)\s*[-\u2013]\s*(?:MARCA\s+)?(?:CO-.*)?$',
                ln, re.I)
            if hdr_m and 'Stems' not in ln and '$' not in ln:
                pending_sp = self._detect_species(hdr_m.group(1))
                pending_desc = f"{hdr_m.group(1).strip()} {hdr_m.group(2).strip()}"
                continue

            # Normaliza pipes, corchetes residuales, OCR errors (€/—/\ufffd
            # vs $, "o" por "0" antes de ".") antes del patrón principal.
            # Sample DAFLOR 26423 scrape: "1,000]" y "— o.15".
            ln_norm = ln.replace('|', ' ').replace(']', ' ').replace('[', ' ')
            ln_norm = re.sub(r'[\u20ac\u2013\u2014\ufffd]\s*o\.', '$0.', ln_norm)  # "— o.15" -> "$0.15"
            ln_norm = re.sub(r'\bo\.(\d)', r'0.\1', ln_norm)      # "o.15" -> "0.15"
            ln_norm = re.sub(r'\s{2,}', ' ', ln_norm).strip()
            # FIX: usar re.I para mixed-case: "1 QB Alstroemeria Assorted - Fancy"
            # Also allow digits in grade position (for roses where size appears as grade: "- 50").
            # Q alone (1 letra) soportado además de QB/HB.
            desc = ''
            btype = ''
            grade = ''
            label = ''
            used_pending = False
            pm = None
            cont_m = None
            # Si la línea anterior dejó un pending_desc (formato colgado:
            # "Alstroemeria Assorted - CO-" → "1 QB MARCA PYTI - - 200 200
            # Stems $0.170 $34.00"), preferir el regex de continuación
            # SOLO cuando la propia línea no contiene un nombre de especie
            # (Alstroemeria/Roses/etc.). Si la línea ya trae su propio
            # desc completo (ej. "1 QB Alstroemeria Fifi - Fancy MARCA -
            # - 200 200 Stems $0.16 $32.00"), usar pm normal — no pisar
            # la variedad real con el pending_desc colgado de antes.
            line_has_own_species = bool(re.search(
                r'\b(?:Alstroemeria|Roses?|Carnations?|Hydrangeas?|'
                r'Chrysanth\w*|Gypsophila)\b',
                ln_norm, re.I))
            if pending_desc and not line_has_own_species:
                cont_m = re.search(
                    r'(\d+)\s+(QB?|HB?)\s+(?:(.+?)\s+)?\d+\s+\d+\s+Stems\s+\$?',
                    ln_norm, re.I)
            if cont_m:
                btype = cont_m.group(2).upper()
                if len(btype) == 1:
                    btype = btype + 'B'
                extra = (cont_m.group(3) or '').strip()
                desc = pending_desc
                # Lo que queda entre QB y los números es la ETIQUETA
                # (destino/marca como "MARCA PYTI", "ASTURIAS", "LUCAS"),
                # NO el grade. El grade viene en la línea siguiente
                # (Selecto/Fancy + tariff). Limpiar dashes sobrantes.
                cleaned = re.sub(r'^-+\s*|\s*-+\s*$|\s*-\s+-\s*', ' ',
                                 extra).strip()
                cleaned = re.sub(r'^MARCA\s+', '', cleaned, flags=re.I).strip()
                if cleaned and not re.match(r'^-+$', cleaned):
                    label = cleaned.upper()
                grade = ''  # se rellena vía grade_pending_il en la próxima iteración
                used_pending = True
            else:
                pm = re.search(r'(\d+)\s+(QB?|HB?)\s+([A-Za-z][A-Za-z\s.\-/\u00b4\u2019\']+?)\s*[-\u2013]\s*([A-Za-z0-9]+)',
                               ln_norm, re.I)
                if pm:
                    btype=pm.group(2).upper(); desc=pm.group(3).strip(); grade=pm.group(4).strip()
                    if len(btype) == 1:
                        btype = btype + 'B'   # "Q" → "QB", "H" → "HB"
                else:
                    pm=re.search(r'(QB?|HB?)\s+([A-Za-z][A-Za-z\s.\-/\u00b4\u2019\']+?)\s*[-\u2013]\s*([A-Za-z0-9]+)',ln_norm,re.I)
                    if not pm:
                        continue
                    btype=pm.group(1).upper(); desc=pm.group(2).strip(); grade=pm.group(3).strip()
                    if len(btype) == 1:
                        btype = btype + 'B'
                # Extraer label inline: lo que va entre el grade y el
                # bloque de stems. Ej: "1 QB Alstroemeria Assorted - Fancy
                # MARCA DECO - - 200 200 Stems..." \u2192 label=DECO.
                tail = ln_norm[pm.end():]
                stems_start = re.search(r'\d+\s+\d+\s+Stems', tail, re.I)
                if stems_start:
                    label_zone = tail[:stems_start.start()].strip()
                    label_zone = re.sub(r'^-+\s*|\s*-+\s*$|\s*-\s+-\s*', ' ',
                                        label_zone).strip()
                    label_zone = re.sub(r'^MARCA\s+', '', label_zone,
                                        flags=re.I).strip()
                    if label_zone and not re.match(r'^-+$', label_zone):
                        label = label_zone.upper()

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
            variety_up = var_clean.upper()
            # Cajas mixtas (variedad con "/" o "ASSORTED") → una única
            # línea MIXTO. Evita que split_mixed_boxes() las divida en
            # sub-líneas 50/50 con destinos artificiales — el operador
            # prefiere ver una sola caja mixta.
            if '/' in variety_up or variety_up == 'ASSORTED':
                variety_up = 'MIXTO'
            grade_up = grade.upper()
            # Normalizar Selecto→SELECT para matching consistente.
            if grade_up.startswith('SELECTO'):
                grade_up = 'SELECT'
            elif grade_up.startswith('SUPER SELECT') or grade_up.startswith('SUPER SELECTO'):
                grade_up = 'SUPERSELECT'
            elif grade_up.startswith('FANCY'):
                grade_up = 'FANCY'
            elif sp == 'ROSES' and grade_up.isdigit():
                # Para rosas, el "grade" capturado es realmente el tamaño
                # ("Roses Pink O'hara - 50"). El size ya se extrajo aparte.
                grade_up = ''
            il=InvoiceLine(raw_description=ln,species=sp,variety=variety_up,grade=grade_up,origin='COL',
                           size=sz,stems_per_bunch=upb,stems=stems,price_per_stem=price,line_total=total,box_type=btype,label=label)
            lines.append(il)
            # Si vino del formato colgado y NO se capturó grade inline,
            # la 3ª línea de la entrada lo trae. Marcar el line para
            # rellenarlo en la siguiente iteración.
            if used_pending and not grade_up:
                grade_pending_il = il
            # Reset pending tras consumirlo
            if used_pending:
                pending_desc = ''
                pending_sp = ''
        # Header total: intentar extraerlo del PDF; si no, sumar líneas.
        if not h.total:
            m = re.search(r'INVOICE\s+TOTAL\s+US\$?\s*([\d,.]+)', text, re.I)
            if m:
                try:
                    h.total = float(m.group(1).replace(',', ''))
                except Exception:
                    pass
        if not h.total and lines:
            h.total = round(sum(l.line_total for l in lines), 2)
        return h, lines


class EqrParser:
    """Formato: Description 'Roses Color Variety CM x Stems Stem - Boxes BT TotalStems $Unit $Total'

    Estructura de la línea (2026):
      Roses <color> <variety> <sz>Cm x <stems/box> Stem - <boxes> <BT> <total_stems> $<unit> $<amount>
    Bug fix (sesión 10m): antes el parser tomaba el `x 150 Stem` (stems
    por caja) como el total, ignorando que a la derecha viene
    `- 3 QBT 450 $0.250 $112.50` donde 450 = 3 cajas × 150 = total real.
    """
    # Sufijo post-"Stem": separador (guión o código como `R12`/`ROY`),
    # cajas, box_type, total_stems, precio unitario, total línea.
    _SUFFIX = (
        r'\s+(?:-|[A-Z][A-Z0-9]*)\s+'                 # `-` o código alfanumérico
        r'(\d+)\s+(HB|QB|QBT|FB|FBE|TB|EB)\s+'        # boxes + box_type
        r'(\d+)\s+'                                    # total_stems REAL
        r'\$\s*([\d.]+)\s+\$\s*([\d.]+)'              # unit price, total
    )

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

            # Intento principal: line completa con sufijo cajas+total_stems.
            # Bi-Color lines: color IS the variety (Orange Iguana) → capture all
            # Non-Bi-Color lines: first word is color category (Orange Orange Crush) → skip it
            if had_bicolor:
                prefix = r'Roses?\s+([A-Z][a-zA-Z\s.\-/]+?)\s+(\d{2})\s+Cm?\s+x\s+(\d+)\s+Stem'
            else:
                prefix = r'Roses?\s+(?:\w+\s+)?([A-Z][a-zA-Z\s.\-/]+?)\s+(\d{2})\s+Cm?\s+x\s+(\d+)\s+Stem'
            pm_full = re.search(prefix + self._SUFFIX, ln_clean, re.I)
            if pm_full:
                var = pm_full.group(1).strip()
                sz = int(pm_full.group(2))
                stems_per_box = int(pm_full.group(3))  # informativo
                boxes = int(pm_full.group(4))
                box_type = pm_full.group(5).upper()
                stems = int(pm_full.group(6))           # total_stems REAL
                price = float(pm_full.group(7))
                total = float(pm_full.group(8))
                spb = 25  # rosas default
                il = InvoiceLine(raw_description=ln, species='ROSES',
                                 variety=var.upper(), size=sz,
                                 stems_per_bunch=spb, stems=stems,
                                 price_per_stem=price, line_total=total,
                                 box_type=box_type)
                lines.append(il)
                continue

            # Garden Rose formato antiguo: "Garden Rose Color Variety NN Cm N Bun. NN St/Bun at $PRICE"
            pm_g = re.search(
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

            # Fallback legacy: líneas con solo `x N Stem` sin sufijo
            # completo. Se conservan los stems_per_box como stems (valor
            # antiguo) — no ideal, pero mantiene compat si aparece
            # alguna variante sin el bloque cajas/total_stems.
            if had_bicolor:
                pm = re.search(r'Roses?\s+([A-Z][a-zA-Z\s.\-/]+?)\s+(\d{2})\s+Cm?\s+x\s+(\d+)\s+Stem', ln_clean, re.I)
            else:
                pm = re.search(r'Roses?\s+(?:\w+\s+)?([A-Z][a-zA-Z\s.\-/]+?)\s+(\d{2})\s+Cm?\s+x\s+(\d+)\s+Stem', ln_clean, re.I)
            if not pm:
                continue
            var = pm.group(1).strip(); sz = int(pm.group(2)); stems = int(pm.group(3))
            spb = 25
            nm = re.search(r'\$\s*([\d.]+)', ln)
            price = float(nm.group(1)) if nm else 0.0
            total_m = re.search(r'\$\s*[\d.]+\s*$', ln)
            try: total = float(total_m.group(0).strip().lstrip('$')) if total_m else 0.0
            except: total = 0.0
            il = InvoiceLine(raw_description=ln, species='ROSES', variety=var.upper(),
                             size=sz, stems_per_bunch=spb, stems=stems,
                             price_per_stem=price, line_total=total)
            lines.append(il)
        return h, lines


class BosqueParser:
    """Formato: #BOX PRODUCT-VARIETY TARIFF LENGTH BUNCHS STEMS T.STEMS PRICE AMOUNT

    Las cajas multi-talla parten un solo box_type en N sub-líneas: la
    primera lleva ``1 HB R O SAS VARIETY ...``, las siguientes empiezan
    directamente con ``ROSAS VARIETY ...`` (sin prefijo de caja). Cada
    sub-línea es una fila independiente del catálogo (talla distinta,
    stems propios, precio propio); todas comparten el mismo box_type.

    Política: cada caja física es una fila — preservamos cada sub-línea
    como su propio ``InvoiceLine`` con el ``box_type`` heredado.
    """
    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'No\.:\s*(\S+)',text,re.I); h.invoice_number=m.group(1) if m else ''
        m=re.search(r'(?:MAWB|MAWB No)\s*[:\s]*([\d]+)',text,re.I); h.awb=re.sub(r'\s+','',m.group(1)) if m else ''
        # Total real impreso en la factura ("TOTALS 750 USD $ 237.50").
        # Sin esto, derivar h.total de sum(lines) ocultaría siempre las
        # sublíneas que el parser no logre capturar — la validación
        # cruzada nunca detectaría el hueco.
        m=re.search(r'TOTALS?\s+\d+\s+USD\s*\$\s*([\d,]+\.\d{2})', text, re.I)
        if not m:
            m=re.search(r'TOTAL\s+USD?\s*\$?\s*([\d,]+\.\d{2})', text, re.I)
        printed_total = float(m.group(1).replace(',', '')) if m else 0.0

        lines=[]
        last_btype=''  # box_type heredado para sub-líneas de continuación
        for ln in text.split('\n'):
            ln=ln.strip()
            # Format A (legacy): "1 HB ROSAS VARIETY 50 ..."
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
                    last_btype=btype
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
            # Format C (continuación de caja multi-talla): empieza
            # con "ROSAS VARIETY ..." sin prefijo "N HB/QB/TB". Hereda
            # box_type de la línea padre anterior.
            if not pm:
                pm_c=re.search(
                    r'^ROSAS?\s+'
                    r'([A-Z][A-Z\s.\-/]+?)\s+'
                    r'0603\d+\s+\d+\s+'
                    r'(\d{2})\s+'
                    r'(\d+)\s+(\d+)\s+(\d+)\s+'   # bunchs spb stems
                    r'\$\s*([\d.]+)\s+\$\s*([\d.]+)',
                    ln)
                if pm_c and last_btype:
                    var=pm_c.group(1).strip(); sz=int(pm_c.group(2))
                    bun=int(pm_c.group(3)); spb_doc=int(pm_c.group(4))
                    stems=int(pm_c.group(5))
                    price=float(pm_c.group(6)); total=float(pm_c.group(7))
                    spb=spb_doc if spb_doc else 25
                    il=InvoiceLine(raw_description=ln,species='ROSES',variety=var,
                                   size=sz,stems_per_bunch=spb,bunches=bun,stems=stems,
                                   price_per_stem=price,line_total=total,box_type=last_btype)
                    lines.append(il)
                    continue
            if not pm: continue
            btype=pm.group(1); var=pm.group(2).strip(); sz=int(pm.group(3))
            last_btype=btype
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
        h.total = printed_total or sum(l.line_total for l in lines)
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


_FLORSANI_COLOR_MAP = {
    # Rojos / rosados
    'RED': 'ROJO', 'PINK': 'ROSA', 'LIGHT PINK': 'ROSA CLARO',
    'DARK PINK': 'ROSA OSCURO', 'HOT PINK': 'ROSA',
    'FUCSIA': 'FUCSIA', 'FUCHSIA': 'FUCSIA', 'RASPBERRY': 'FRAMBUESA',
    # Naranjas / amarillos / pastel
    'ORANGE': 'NARANJA', 'LIGHT ORANGE': 'NARANJA CLARO', 'DARK ORANGE': 'NARANJA OSCURO',
    'CORAL': 'CORAL', 'SALMON': 'SALMON', 'PEACH': 'MELOCOTON',
    'YELLOW': 'AMARILLO', 'LIGHT YELLOW': 'AMARILLO CLARO', 'DARK YELLOW': 'AMARILLO OSCURO',
    # Azules
    'BLUE': 'AZUL', 'LIGHT BLUE': 'AZUL CLARO', 'BABY BLUE': 'AZUL CLARO',
    'DARK BLUE': 'AZUL OSCURO', 'SKY BLUE': 'AZUL CLARO',
    'TURQUOISE': 'TURQUESA', 'DARK TURQUOISE': 'TURQUESA OSCURO',
    # Morados
    'PURPLE': 'LILA', 'LILAC': 'LILA', 'LIGHT LILAC': 'LILA CLARO',
    'LAVANDER': 'LAVANDA', 'LAVENDER': 'LAVANDA',
    'LIGHT LAVANDER': 'LAVANDA', 'LIGHT LAVENDER': 'LAVANDA',
    'DARK LAVANDER': 'LAVANDA OSCURO', 'DARK LAVENDER': 'LAVANDA OSCURO',
    # Verdes
    'GREEN': 'VERDE', 'LIGHT GREEN': 'VERDE CLARO', 'DARK GREEN': 'VERDE OSCURO',
    'APPLE GREEN': 'VERDE MANZANA', 'LIME GREEN': 'VERDE LIMA', 'LIME': 'VERDE LIMA',
    # Neutros / metales / complejos
    'WHITE': 'BLANCO', 'BLACK': 'NEGRO',
    'GOLD': 'ORO', 'SILVER': 'PLATA', 'COPPER': 'COBRE',
    'BROWN': 'CAFE', 'COFFEE': 'CAFE',
    # Especiales
    'RAINBOW': 'RAINBOW', 'DARK RAINBOW': 'RAINBOW OSCURO',
    'PASTEL RAINBOW': 'RAINBOW PASTEL',
    'TIE DYE': 'TIE DYE', 'GLITTER': 'GLITTER',
    'SALT AND PEPPER': 'SAL Y PIMIENTA',
    'MIX': 'MIXTO', 'MIXED': 'MIXTO', 'ASSORTED': 'MIXTO',
}


def _translate_florsani_color(color_en: str) -> str:
    """Traduce un color EN/raw (p.ej. 'Tinted Light Pink' → 'ROSA CLARO').

    Estrategia:
      1. UPPER + colapsar espacios.
      2. Probar multi-word primero (LIGHT PINK antes que PINK).
      3. Si no hay match, devolver el original normalizado.
    """
    t = re.sub(r'\s+', ' ', color_en.upper().strip())
    # Orden por longitud descendente: multi-word gana a single-word.
    for en, es in sorted(_FLORSANI_COLOR_MAP.items(), key=lambda kv: -len(kv[0])):
        if t == en:
            return es
    return t


class FlorsaniParser:
    """Formato Florsani (Gypsophila / Limonium / Ornithogalum, Ecuador).

    Columnas del PDF:
      Pcs | BoxType | BoxSpLabel | Description | Color | Weight | CM |
      BunchBox | StemsBunch | Price/Stem | TotalStems | TotalPriceUSD

    Variantes observadas (sesión 10m):
    - Línea simple con todas las columnas:
      "7 HE            Gypsophila Xlence NINGUNO 750  80 16 22 0.273 2464 672.01"
      "1 HJ CRISTIAN   Gypsophila Xlence NINGUNO 1000 80 17 25 0.290 425  123.25"
    - Sub-línea SIN `Pcs + BoxType` (hereda del último parent), con
      BoxSpLabel opcional y variety con tint multi-palabra:
      "1 HE MARL Gypsophila Xlence Tinted Pastel Rainbow 750 80 10 20 0.450 200 90.00"
      "       MARL Gypsophila Xlence Tinted Red 750 80 2 20 0.345 40 13.80"
    - Otras especies (Limonium, Ornithogalum) con variety multi-palabra:
      "2 HE Limonium Pinna Colada NINGUNO 750 70 16 25 0.260 800 208.00"
      "5 QB Ornithogalum White Star NINGUNO CB10 50 20 10 0.350 1000 350.00"

    Bug previo: regex solo aceptaba box types `HE|QB` (sin HJ/FB) y
    el extractor `\\d{2}` capturaba `50` dentro del peso `750` como
    talla. Además OCR pegaba variety a weight (`Rainbow750`) y no
    manejaba sub-líneas sin Pcs+BoxType.
    """
    # Especies conocidas de Florsani.
    _SPECIES_MAP = {
        'gypsophila':   'GYPSOPHILA',
        'limonium':     'OTHER',
        'ornithogalum': 'OTHER',
    }

    # Box types conocidos. Florsani usa combinaciones HE/HJ/QB/QJ/HB/FB/EB.
    _BOX_TYPES = r'(?:HE|HJ|HB|QB|QJ|FB|EB|TB)'

    # Bloque final de 7 números: weight CM bunches spb price totalStems totalPrice.
    # `weight` acepta dígitos o un token alfa-numérico corto tipo `CB10`
    # (observado en Ornithogalum) porque no se usa en el matching final.
    _TAIL = (
        r'(\S+)\s+'           # weight/código (750, 1000, CB10)
        r'(\d{2,3})\s+'       # CM (talla)
        r'(\d+)\s+'           # bunches (por caja)
        r'(\d+)\s+'           # stems_per_bunch
        r'([\d.]+)\s+'        # price per stem
        r'([\d,]+)\s+'        # total stems (puede llevar coma de miles: 2,464)
        r'([\d.,]+)'          # total price USD
    )

    @staticmethod
    def _ocr_normalize(ln: str) -> str:
        """Separa word+weight pegados por OCR: `Rainbow750` → `Rainbow 750`."""
        return re.sub(r'([A-Za-z])(\d{3,})\b', r'\1 \2', ln)

    @staticmethod
    def _build_variety(species_token: str, variety_raw: str) -> str:
        """Canónico para match con catálogo.

        Gypsophila/Paniculata:
          - "Xlence Tinted Light Pink" → "PANICULATA XLENCE TEÑIDA ROSA CLARO"
          - "Xlence NINGUNO"           → "PANICULATA XLENCE BLANCO"
          - "Xlence"                   → "PANICULATA XLENCE BLANCO"
          - "Million Stars"            → "PANICULATA MILLION STARS"
          - "Small Bloom"              → "PANICULATA SMALL BLOOM"
        Limonium/Ornithogalum: se devuelve tal cual (UPPER) — sus
        artículos del catálogo ya usan esos nombres.
        """
        raw = re.sub(r'\s*NINGUNO\s*$', '', variety_raw, flags=re.I).strip()
        sp = species_token.lower()
        if sp != 'gypsophila':
            # Limonium, Ornithogalum, etc.: prefijo original + variedad.
            return f'{species_token.upper()} {raw.upper()}' if raw else species_token.upper()

        # Gypsophila → PANICULATA en catálogo.
        up = raw.upper()
        # Línea "Xlence Tinted <color>" — traducir color y normalizar a
        # "PANICULATA XLENCE TEÑIDA <color_es>".
        m = re.match(r'^XLENCE\s+TINTED\s+(.+)$', up)
        if m:
            color_es = _translate_florsani_color(m.group(1))
            return f'PANICULATA XLENCE TEÑIDA {color_es}'
        # Línea "Xlence" sola (NINGUNO quitado): el artículo es BLANCO
        # (el catálogo distingue por tamaño 750GR vs 1000GR, no por
        # color — eso lo resuelve el matcher por size).
        if up == 'XLENCE' or up == '':
            return 'PANICULATA XLENCE BLANCO'
        # Otras familias (MILLION STARS, SMALL BLOOM, ...): conservar
        # palabras tal cual bajo el prefijo PANICULATA.
        return f'PANICULATA {up}'

    def _parse_tail(self, pm, tail_start: int):
        """Extrae las 7 columnas numéricas del tail (helper común).

        `tail_start` es el último grupo ANTES del tail (variety). Los
        grupos del tail empiezan en tail_start+1:
          +1 weight (se ignora, sólo anchor)
          +2 CM (size)  +3 bunches  +4 spb
          +5 price      +6 total_stems  +7 total_price
        """
        sz    = int(pm.group(tail_start + 2))
        bunch = int(pm.group(tail_start + 3))  # noqa: F841 (no se usa aún)
        spb   = int(pm.group(tail_start + 4))
        price = float(pm.group(tail_start + 5))
        stems = int(pm.group(tail_start + 6).replace(',', ''))
        total = float(pm.group(tail_start + 7).replace(',', ''))
        return sz, spb, stems, price, total

    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'COMMERCIAL\s+INVOICE\s+N[o\xba]\s*(\S+)',text,re.I)
        if not m:
            m=re.search(r'N[o\xba]\s*(\S+)',text,re.I)
        h.invoice_number=m.group(1) if m else ''
        m=re.search(r'DATE[:\s]+([\d/\-]+)',text,re.I); h.date=m.group(1) if m else ''
        m=re.search(r'AWB#?[:\s]*([\d\-]+)',text,re.I); h.awb=re.sub(r'\s+','',m.group(1)) if m else ''
        # Total impreso: una o más secciones "Single Flowers" (multi-invoice
        # PDFs incluyen varias). Cada sección trae una línea por especie:
        #   "Gypsophila Caryophyllaceae Gipsófila Gypsophila 6 1,600 0.43 681.60"
        # Sumamos todos los totales de TODAS las secciones para obtener el
        # total real de la(s) factura(s). Si esto falla, cae al sum(lines).
        sf_total = 0.0
        sf_found = False
        for sf_m in re.finditer(
                r'Single\s+Flowers(.+?)(?:Cliente|Direcci|Forma|Moneda|'
                r'COMMERCIAL\s+INVOICE|HTS\s*:|$)',
                text, re.I | re.S):
            for ln in sf_m.group(1).split('\n'):
                ln = ln.strip()
                tm = re.match(
                    r'^[A-Za-z][A-Za-z\s\xc0-\xff°-ſ�\.]+?\s+'
                    r'\d+\s+[\d,]+\s+[\d.]+\s+([\d,]+\.\d{2})\s*$', ln)
                if tm:
                    try:
                        sf_total += float(tm.group(1).replace(',', ''))
                        sf_found = True
                    except ValueError:
                        pass
        if sf_found:
            h.total = round(sf_total, 2)

        lines = []
        last_pcs = None
        last_box_type = None

        for raw_ln in text.split('\n'):
            ln = self._ocr_normalize(raw_ln.strip())
            if not ln:
                continue

            # ── Línea PARENT: "1 HE [LABEL] <Species> <Variety> [<Color>] <tail>"
            # ── Línea SUB-LINEA: sin Pcs+BoxType, hereda del último parent.
            # Probamos parent primero.
            pm = re.search(
                r'^(\d+)\s+(' + self._BOX_TYPES + r')\s+'   # 1=pcs, 2=BT
                r'(?:([A-Z][A-Za-z0-9]+)\s+)?'               # 3=label optional
                r'(Gypsophila|Limonium|Ornithogalum)\s+'     # 4=species
                r'(\S+(?:\s+\S+?)*?)\s+'                     # 5=variety (greedy non-greedy)
                + self._TAIL + r'\s*$',
                ln, re.I)
            if pm:
                last_pcs = int(pm.group(1))
                last_box_type = pm.group(2).upper()
                species_token = pm.group(4).lower()
                species = self._SPECIES_MAP.get(species_token, 'OTHER')
                variety_raw = pm.group(5).strip()
                sz, spb, stems, price, total = self._parse_tail(pm, 5)
                # Limpiar "NINGUNO" del final de la variedad.
                variety = self._build_variety(species_token, variety_raw)
                il = InvoiceLine(raw_description=raw_ln.strip(), species=species,
                                 variety=variety, size=sz, stems_per_bunch=spb,
                                 stems=stems, price_per_stem=price, line_total=total,
                                 box_type=last_box_type)
                lines.append(il)
                continue

            # Sub-línea (hereda pcs + box_type del parent).
            if last_pcs is None:
                continue
            pm2 = re.search(
                r'^(?:([A-Z][A-Za-z0-9]+)\s+)?'              # 1=label optional
                r'(Gypsophila|Limonium|Ornithogalum)\s+'     # 2=species
                r'(\S+(?:\s+\S+?)*?)\s+'                     # 3=variety
                + self._TAIL + r'\s*$',
                ln, re.I)
            if pm2:
                species_token = pm2.group(2).lower()
                species = self._SPECIES_MAP.get(species_token, 'OTHER')
                variety_raw = pm2.group(3).strip()
                sz, spb, stems, price, total = self._parse_tail(pm2, 3)
                variety = self._build_variety(species_token, variety_raw)
                il = InvoiceLine(raw_description=raw_ln.strip(), species=species,
                                 variety=variety, size=sz, stems_per_bunch=spb,
                                 stems=stems, price_per_stem=price, line_total=total,
                                 box_type=last_box_type)
                lines.append(il)
                continue

        # Derivar header.total de suma si no vino.
        if not h.total and lines:
            h.total = round(sum(l.line_total for l in lines), 2)
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
            # PROFORMA spray garden rose: "SPR RGARDEN BELLALINDA SWEETY 50 Cm 1 50 50 .500 25.00"
            # Columnas (cabecera PROFORMA): DESCRIPTION | Q/H/F/E/ADJUST | STEMS_PER_BOX |
            # UNITS_TOTAL | UNIT_PRICE | TOTAL_AMOUNT. Nuestros 3 valores finales son
            # stems · price · total (mismo orden que ROSE).
            pm_spr = re.search(
                r'SPR\s+R?GARDEN\s+([A-Z][A-Z\s.\-/`\']+?)\s+(\d{2})(?:\s*-\s*(\d{2}))?\s*Cm\b',
                ln, re.I)
            if pm_spr:
                after = ln[pm_spr.end():]
                nums = re.findall(r'[\d,]+\.?\d*|\.\d+', after)
                if len(nums) >= 3:
                    var = pm_spr.group(1).strip()
                    sz = int(pm_spr.group(3)) if pm_spr.group(3) else int(pm_spr.group(2))
                    try:
                        stems = int(nums[-3].replace(',', ''))
                        total = float(nums[-1].replace(',', ''))
                    except (ValueError, IndexError):
                        stems = 0
                        total = 0.0
                    spb = 10  # spray rose: bunch típico de 10 tallos
                    price = total / stems if stems else 0.0
                    il = InvoiceLine(
                        raw_description=ln, species='ROSES', variety=var, origin='COL',
                        size=sz, stems_per_bunch=spb, stems=stems,
                        price_per_stem=price, line_total=total,
                        grade='SPRAY',
                    )
                    lines.append(il)
                    continue
            # BOUQUET lines (proforma 2026): "BOUQUET <name> NN CM <boxes> <units_per_box> <total_units> <price> <total>"
            # Ej: "BOUQUET GARDEN WHIMSY 50 CM 4 6 24 9.820 235.68"
            #     "BOUQUET A MOTHER'S LUXURY 50 CM 2 2 4 29.130 116.52"
            # total_units × price = total. stems_per_bunch=1 (cada "stem" = 1 ramo).
            pm_b = re.search(
                r"^BOUQUET\s+([A-Z][A-Z\s.\-/`'`]+?)\s+(\d{2})\s*CM\s+"
                r'(\d+)\s+(\d+)\s+(\d+)\s+([\d,.]+)\s+([\d,.]+)\s*$',
                ln, re.I)
            if pm_b:
                var = pm_b.group(1).strip().upper()
                sz = int(pm_b.group(2))
                try:
                    boxes = int(pm_b.group(3))
                    upb = int(pm_b.group(4))
                    total_units = int(pm_b.group(5))
                    price = float(pm_b.group(6).replace(',', ''))
                    total = float(pm_b.group(7).replace(',', ''))
                except (ValueError, IndexError):
                    continue
                # Sanity: boxes × upb ≈ total_units (puede haber adjust)
                il = InvoiceLine(
                    raw_description=ln, species='OTHER', variety=var, origin='COL',
                    size=sz, stems_per_bunch=1, bunches=total_units, stems=total_units,
                    price_per_stem=price, line_total=total,
                    grade='BOUQUET',
                )
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

    Variante OCR (factura escaneada simple):
      "ROSE FREEDOM 40 CM 2 250 500 0,16 80,00"
      Columnas: ROSE variety SIZE CM HB_BOXES STEMS_PER_H TOTAL_STEMS PRICE TOTAL
    """
    def parse(self, text:str, pdata:dict):
        h=InvoiceHeader(); h.provider_key=pdata['key']; h.provider_id=pdata['id']; h.provider_name=pdata['name']
        m=re.search(r'INVOICE\s+No\.?\s*(\d+)',text,re.I); h.invoice_number=m.group(1) if m else ''
        m=re.search(r'FECHA EXPEDICION\s*([\d\-]+)',text,re.I); h.date=m.group(1) if m else ''
        m=re.search(r'GU[I\xcdÌ]A\s+MASTER\s+([\d\-]+)',text,re.I); h.awb=re.sub(r'\s+','',m.group(1)) if m else ''
        m=re.search(r'GU[I\xcdÌ]A\s+HIJA\s+([\d\w\s\-\(\)]+)',text,re.I)
        h.hawb=re.sub(r'\s+','',m.group(1)).strip() if m else ''
        # Total impreso: "TOTAL A PAGAR 87,50" (USD, coma decimal).
        # Si no aparece, cae al sum(lines) al final — pero entonces
        # una línea faltante NUNCA dispararía aviso de "Parcial".
        m = re.search(r'TOTAL\s+A\s+PAGAR\s+\$?\s*([\d.,]+)', text, re.I)
        if m:
            try:
                h.total = float(m.group(1).replace('.', '').replace(',', '.'))
            except ValueError:
                pass
        lines=[]
        for ln in text.split('\n'):
            ln=ln.strip()
            # "MOMENTUM ROSE 50 CM ROSA0682 1 250 250 $ 0,33 82,50"
            # groups: variety, size, code, unit, qty, stems, price, total
            pm=re.search(r'([A-Z][A-Z\s.\-/]+?)\s+ROSE\s+(\d{2})\s+CM\s+\w+\s+(\d+)\s+(\d+)\s+(\d+)\s+\$\s*([\d,]+)\s+([\d,.]+)',ln,re.I)
            if not pm:
                # Sin "ROSE": "ASSORTED 50 CM ROSA0091 1 250 250 ..."
                pm=re.search(r'([A-Z][A-Z\s.\-/]+?)\s+(\d{2})\s+CM\s+\w+\s+(\d+)\s+(\d+)\s+(\d+)\s+\$\s*([\d,]+)\s+([\d,.]+)',ln,re.I)
            if pm:
                var=pm.group(1).strip(); sz=int(pm.group(2))
                try:
                    stems=int(pm.group(5))
                    price_str=pm.group(6).replace(',','.')
                    total_str=pm.group(7).replace(',','.')
                    price=float(price_str)
                    total=float(total_str)
                except: continue
                spb=25
                il=InvoiceLine(raw_description=ln,species='ROSES',variety=var,origin='COL',
                               size=sz,stems_per_bunch=spb,stems=stems,
                               price_per_stem=price,line_total=total)
                lines.append(il)
                continue
            # Variante OCR: "ROSE FREEDOM 40 CM 2 250 500 0,16 80,00"
            pm2=re.search(
                r'ROSE\s+([A-Z][A-Z\s.\-/]+?)\s+(\d{2})\s+CM\s+'
                r'(\d+)\s+(\d+)\s+(\d+)\s+([\d,]+)\s+([\d,.]+)', ln, re.I)
            if pm2:
                var=pm2.group(1).strip().upper(); sz=int(pm2.group(2))
                try:
                    stems=int(pm2.group(5))
                    price=float(pm2.group(6).replace(',','.'))
                    total=float(pm2.group(7).replace(',','.'))
                except: continue
                il=InvoiceLine(raw_description=ln,species='ROSES',variety=var,origin='COL',
                               size=sz,stems_per_bunch=25,stems=stems,
                               price_per_stem=price,line_total=total,box_type='HB')
                lines.append(il)
        if not h.total and lines:
            h.total = round(sum(l.line_total for l in lines), 2)
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
            # Variante C (proforma 2026): "15,00 QB 35 00001 HYD WHITE PREMIUM 0603199010 525 0,48 252,00"
            #   pdfplumber inserta SPB y CUST_ORD entre PACK y DESCRIPTION;
            #   CUST_ORD es opcional (ej. "5,00 QB 35 HYD GREEN PREMIUM ...").
            pm=re.search(
                r'^[\d,]+\s+(QB|HB)\s+(\d{2,3})\s+(?:\d{4,6}\s+)?'
                r'(HYD\s+[A-Za-z][A-Za-z\s.\-/]+?)\s+\d{8,12}\s+'
                r'(\d+)\s+([\d,.]+)\s+([\d,.]+)\s*$',
                ln, re.I,
            )
            if pm:
                btype=pm.group(1).upper(); _spb_new=pm.group(2)
                desc=pm.group(3).strip().upper()
                stems_g=pm.group(4); price_g=pm.group(5); total_g=pm.group(6)
            else:
                pm=re.search(r'[\d,]+\s+(QB|HB)\s+(HYD\s+[A-Za-z][A-Za-z\s.\-/]+?)\s*(?:\[[\d]+\])?\s+\d{2,}\s*\d*\s+(\d+)\s+([\d,]+)\s+([\d,]+)',ln,re.I)
                if not pm: continue
                btype=pm.group(1).upper(); desc=pm.group(2).strip().upper()
                stems_g=pm.group(3); price_g=pm.group(4); total_g=pm.group(5)
            var=re.sub(r'^HYD\s+','',desc).strip()
            # Traducir colores EN→ES y reordenar a formato catálogo
            # "WHITE PREMIUM" → "PREMIUM BLANCO", "BLUE" → "PREMIUM AZUL".
            # El catálogo CONDOR usa "HYDRANGEA PREMIUM <color_es>".
            _HYD_COLORS = {
                'WHITE': 'BLANCO', 'BLUE': 'AZUL', 'LIGHT BLUE': 'AZUL CLARO',
                'DARK BLUE': 'AZUL OSCURO', 'PINK': 'ROSA',
                'LIGHT PINK': 'ROSA CLARO', 'DARK PINK': 'ROSA OSCURO',
                'GREEN': 'VERDE', 'LIGHT GREEN': 'VERDE CLARO',
                'DARK GREEN': 'VERDE OSCURO', 'LIME GREEN': 'VERDE LIMA',
                'RED': 'ROJO', 'BURGUNDY': 'GRANATE', 'PEACH': 'MELOCOTON',
                'MOCCA': 'MOCCA', 'MIX': 'MIXTO', 'MIXED': 'MIXTO',
            }
            v_up = var
            # Reordenar "COLOR PREMIUM" → "PREMIUM COLOR"
            m_rev = re.match(r'^(.+)\s+PREMIUM$', v_up)
            if m_rev:
                color_en = m_rev.group(1).strip()
                color_es = _HYD_COLORS.get(color_en, color_en)
                var = f'PREMIUM {color_es}'
            elif v_up in _HYD_COLORS:
                var = f'PREMIUM {_HYD_COLORS[v_up]}'
            try:
                stems=int(stems_g)
                price=float(price_g.replace(',','.'))
                total=float(total_g.replace(',','.'))
            except: stems=0; price=0.0; total=0.0
            il=InvoiceLine(raw_description=ln,species='HYDRANGEAS',variety=var,origin='COL',
                           size=60,  # hydrangeas colombianas = 60cm por default
                           stems_per_bunch=1,bunches=stems,stems=stems,
                           price_per_stem=price,line_total=total,box_type=btype)
            lines.append(il)
        return h, lines


class MalimaParser:
    """Formato Malima/Starflowers (Gypsophila Ecuador).

    Bug previo (sesión 10m): precios/totales regex aceptaban solo
    `[\\d.]+`, cortando en la coma de miles US (`$2,450.00` → 2.00).
    Fix: `[\\d.,]+` con `_num_us()` que quita comas.
    """
    @staticmethod
    def _num_us(s: str) -> float:
        """Formato US: `2,450.00` → 2450.00 (coma como miles)."""
        try:
            return float(s.replace(',', ''))
        except ValueError:
            return 0.0

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
            # Variante A (inline): "1 HB MALIMA EUROPA 0.50 XLENCE... GYPSOPHILA N $X.XX N $X.XX $X,XXX.XX"
            pm=re.search(r'\d+\s+(HB|QB)\s+MALIMA\s+EUROPA\s+[\d.,]+\s+(XLENCE[^$]+?)\s+(GYPSOPHILA)\s+(\d+)\s+\$([\d.,]+)\s+(\d+)\s+\$([\d.,]+)\s+\$([\d.,]+)',ln,re.I)
            if pm:
                current_btype=pm.group(1)
                variety=pm.group(2).strip().upper()
                bunches=int(pm.group(4))
                ppb=self._num_us(pm.group(5))
                stems=int(pm.group(6))
                total=self._num_us(pm.group(8))
                spb=stems//bunches if bunches else 25
                il=InvoiceLine(raw_description=ln,species='GYPSOPHILA',variety=variety,
                               stems_per_bunch=spb,bunches=bunches,stems=stems,
                               price_per_bunch=ppb,line_total=total,box_type=current_btype)
                lines.append(il); continue

            # Parent mixed box: solo actualizar btype
            pm_parent=re.search(r'\d+\s+(HB|QB)\s+MALIMA\s+EUROPA\s+[\d.,]+\s+MIXED\s+BOX',ln,re.I)
            if pm_parent:
                current_btype=pm_parent.group(1); continue

            # Variante B (sub-línea): "XLENCE 80CM 30GR 20ST R PTRI TINT GREEN GYPSOPHILA 1 $8.00 20 $0.40 $8.00"
            # o "MILLION STARS 80CM 750GR MIN 20ST R PTRI - MI GYPSOPHILA 1 $8.75 20 $0.44 $8.75"
            pm2=re.search(
                r'^(.+?)\s+GYPSOPHILA\s+(\d+)\s+\$([\d.,]+)\s+(\d+)\s+\$([\d.,]+)\s+\$([\d.,]+)',
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
                # Normalizar a canónico catálogo ES (sesión 10u):
                # "XLENCE TINT GREEN" → "PANICULATA XLENCE TEÑIDA VERDE"
                # Mismo tratamiento que FlorsaniParser._build_variety.
                m_tint = re.match(r'^XLENCE\s+TINT\s+(.+)$', variety)
                if m_tint:
                    color_es = _translate_florsani_color(m_tint.group(1))
                    variety = f'PANICULATA XLENCE TEÑIDA {color_es}'
                elif variety.startswith('XLENCE'):
                    # "XLENCE" solo o "XLENCE 80CM" (sin tint) → blanco natural
                    rest = variety[len('XLENCE'):].strip()
                    variety = f'PANICULATA XLENCE {rest}'.strip() if rest else 'PANICULATA XLENCE BLANCO'
                elif variety.startswith('MILLION STARS'):
                    variety = f'PANICULATA {variety}'
                bunches=int(pm2.group(2))
                ppb=self._num_us(pm2.group(3))
                stems=int(pm2.group(4))
                total=self._num_us(pm2.group(6))
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
        # Estado del último parent de mixed box: las sub-líneas heredan
        # box_type / label cuando el patrón 3 matchea.
        last_btype = ''
        last_label = ''
        _SUBLINE_SKIP = {
            'TESSA', 'TOTALS', 'AWB', 'HAWB', 'USD', 'FUE', 'BOXES',
            'ORDER', 'BOXT', 'LOC', 'DESCRIPTION', 'LEN', 'BUN', 'STEMS',
            'PRICE', 'TOTAL', 'LABEL', 'FARM',
        }
        for i, ln in enumerate(text_lines):
            ln=ln.strip()
            # Patrón: ...HB/QB [loc] [num] VARIETY SIZE BUNCHES STEMS $PRICE $TOTAL LABEL
            # Ejemplo: "1 910573351 HB XL 2 MONDIAL 60 12 300 $0.45 $135.00 R17"
            # (?:[A-Z][A-Z0-9\-]*\s+)? admite farm/route code tipo "TESSA-R1" antes de la variedad
            # Bug histórico (sesión 12j): group(4) son BUNCHES no spb;
            # spb real = stems/bunches. Antes salía spb=10 en MONDIAL 70
            # cuando lo real es spb=25 (250 stems / 10 bunches).
            pm=re.search(r'(HB|QB)\s+(?:\w+\s+)?(?:\d+\s+)?(?:[A-Z][A-Z0-9\-]*\s+)?([A-Z][A-Z\s.\-/]+?)\s+(\d{2})\s+(\d+)\s+(\d+)\s+\$([\d.]+)\s+\$([\d,.]+)',ln)
            if pm:
                btype=pm.group(1); var=pm.group(2).strip()
                try:
                    sz=int(pm.group(3)); bunches=int(pm.group(4))
                    stems=int(pm.group(5)); price=float(pm.group(6))
                    total=float(pm.group(7).replace(',',''))
                except: continue
                spb = stems // bunches if bunches > 0 else 25
                label_m=re.search(r'\$[\d,.]+\s+(\w+)\s*$',ln); label=label_m.group(1) if label_m else ''
                last_btype = btype
                last_label = label
                il=InvoiceLine(raw_description=ln,species='ROSES',variety=var,
                               size=sz,stems_per_bunch=spb,bunches=bunches,stems=stems,
                               price_per_stem=price,line_total=total,label=label,box_type=btype)
                lines.append(il)
                continue
            # FIX: línea sin variedad visible (variedad en la línea siguiente)
            # "1 910927987 QB 3 60 4 100 $0.45 $45.00 R18"
            # siguiente línea: "R2 PINK"  o "MONDIAL"
            pm2=re.search(r'(HB|QB)\s+(\d+)\s+(\d{2})\s+(\d+)\s+(\d+)\s+\$([\d.]+)\s+\$([\d,.]+)',ln)
            if pm2:
                btype=pm2.group(1)
                try:
                    sz=int(pm2.group(3)); bunches=int(pm2.group(4))
                    stems=int(pm2.group(5)); price=float(pm2.group(6))
                    total=float(pm2.group(7).replace(',',''))
                except: continue
                spb = stems // bunches if bunches > 0 else 25
                label_m=re.search(r'\$[\d,.]+\s+(\w+)\s*$',ln); label=label_m.group(1) if label_m else ''
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
                               size=sz,stems_per_bunch=spb,bunches=bunches,stems=stems,
                               price_per_stem=price,line_total=total,label=label,box_type=btype)
                lines.append(il)
                continue

            # Patrón 3: sub-línea de mixed box sin prefijo HB/QB.
            # El parent (pm) dio solo la primera variedad; las siguientes
            # van como "DEEP PURPLE 60 1 25 $0.40 $10.00" heredando box_type.
            # Estructura: VARIETY SIZE BUNCHES STEMS $PRICE $TOTAL.
            if last_btype:
                pm3=re.match(
                    r'^([A-Z][A-Z\s.\'&\-/]+?)\s+(\d{2})\s+(\d+)\s+(\d+)\s+'
                    r'\$([\d.]+)\s+\$([\d,.]+)\s*$', ln)
                if pm3:
                    var=pm3.group(1).strip()
                    head = var.split()[0] if var else ''
                    if not var or head in _SUBLINE_SKIP:
                        continue
                    try:
                        sz=int(pm3.group(2)); bunches=int(pm3.group(3))
                        stems=int(pm3.group(4)); price=float(pm3.group(5))
                        total=float(pm3.group(6).replace(',',''))
                    except Exception:
                        continue
                    spb = stems // bunches if bunches > 0 else 25
                    il=InvoiceLine(raw_description=ln,species='ROSES',variety=var,
                                   size=sz,stems_per_bunch=spb,bunches=bunches,stems=stems,
                                   price_per_stem=price,line_total=total,
                                   label=last_label,box_type=last_btype)
                    lines.append(il)
                    continue

                # Patrón 4: OCR rompe variety multi-palabra en 3 líneas
                # adyacentes:
                #   33: PINK
                #   34: 60 1 25 $0.40 $10.00
                #   35: MONDIAL
                # Captura variety concatenando vecinos si son palabras
                # mayúsculas cortas sin números.
                # Estructura: SIZE BUNCHES STEMS $PRICE $TOTAL.
                pm4=re.match(
                    r'^(\d{2})\s+(\d+)\s+(\d+)\s+\$([\d.]+)\s+\$([\d,.]+)\s*$', ln)
                if pm4:
                    prev_ln = text_lines[i-1].strip() if i > 0 else ''
                    next_ln = text_lines[i+1].strip() if i+1 < len(text_lines) else ''
                    var_parts: list[str] = []
                    for candidate in (prev_ln, next_ln):
                        if (candidate and len(candidate) <= 25
                                and re.match(r'^[A-Z][A-Z\s&\-]*$', candidate)
                                and candidate.split()[0] not in _SUBLINE_SKIP):
                            var_parts.append(candidate)
                    if var_parts:
                        var = ' '.join(var_parts)
                        try:
                            sz=int(pm4.group(1)); bunches=int(pm4.group(2))
                            stems=int(pm4.group(3)); price=float(pm4.group(4))
                            total=float(pm4.group(5).replace(',',''))
                        except Exception:
                            continue
                        spb = stems // bunches if bunches > 0 else 25
                        il=InvoiceLine(raw_description=ln,species='ROSES',variety=var,
                                       size=sz,stems_per_bunch=spb,bunches=bunches,stems=stems,
                                       price_per_stem=price,line_total=total,
                                       label=last_label,box_type=last_btype)
                        lines.append(il)
        if not h.total and lines:
            h.total = round(sum(l.line_total for l in lines), 2)
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
        last_btype = 'HB'
        last_farm = ''
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
                last_btype = btype
                last_farm = farm
                il=InvoiceLine(raw_description=ln,species='ROSES',variety=var,
                               size=sz,stems_per_bunch=spb,bunches=bunches,stems=stems,
                               price_per_stem=price,line_total=total,box_type=btype,farm=farm)
                lines.append(il)
                continue

            # Sub-línea de mixed box (Rosas) — comparte caja con un parent.
            # NO trae prefix "N hb XXX": "<COD> <Variety> <size> cm <Farm> <Stems> <SPB> <Bunches> $ <price> $ <total>".
            # Ej: "3069 Brighton 60 cm Giomiflor 50 25 2 $ 0,26 $ 1 3,00"
            # Hereda btype/farm del último parent. La línea debe empezar
            # con un código numérico (no debe matchear líneas de cabecera).
            pm3=re.match(
                r'^\d+\s+'                                  # COD
                r'([A-Za-z][A-Za-z\s.&\-/]+?)\s+'           # variety
                r'(\d{2,3})\s*cm\s+'                        # size cm
                r'(.+?)\s+'                                  # farm
                r'(\d+)\s+(\d+)\s+(\d+)\s+'                 # stems spb bunches
                r'\$\s*([\d\s.,]+?)\s+'                     # price
                r'\$\s*([\d\s.,]+?)$', ln, re.I)
            if pm3 and last_btype:
                var = pm3.group(1).strip().upper()
                # Descartar matches espurios: variety debe ser corto y
                # no empezar por palabras de cabecera/totales.
                if var.startswith(('TOTAL', 'SUBTOTAL', 'AMOUNT', 'PRODUCT',
                                    'COD', 'INVOICE', 'CARGO', 'AGENCY',
                                    'REF', 'AWB', 'HAWB')):
                    continue
                if len(var) < 2 or len(var) > 60:
                    continue
                try:
                    sz = int(pm3.group(2))
                    farm = pm3.group(3).strip()
                    stems = int(pm3.group(4))
                    spb = int(pm3.group(5))
                    bunches = int(pm3.group(6))
                    price = self._parse_amount(pm3.group(7))
                    total = self._parse_amount(pm3.group(8))
                except (ValueError, IndexError):
                    continue
                il = InvoiceLine(raw_description=ln, species='ROSES', variety=var,
                                 size=sz, stems_per_bunch=spb, bunches=bunches, stems=stems,
                                 price_per_stem=price, line_total=total,
                                 box_type=last_btype, farm=farm)
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
    # Variedad admite apostrofes (MAYRA'S BRIDAL) — se normalizan los
    # curly quotes y el byte 0x92 a ' antes de parsear.
    _RE_A = re.compile(
        r"([A-Z][A-Z\s']+?)\s+(\d{2})CM\s+(\d+)\s+(\d+)\s+([\w\s]*?)\s*CO\s+\d+\s+"
        r"\$\s*([\d,]+)\s+\$\s*([\d,]+)")

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

    # Sub-línea de mixed box (variante A): la variety está colgada en
    # la línea anterior, esta línea empieza directamente por la talla.
    # Ej: "40CM 50 50 TECLY CO 0603110000 $ 0,32 $ 16,00"
    # Ej: "40CM 25 25 CO 0603110000 $ 0,32 $ 8,00" (sin label)
    _RE_C = re.compile(
        r'^(\d{2})CM\s+(\d+)\s+(\d+)\s+'         # size + bunches + stems
        r'([A-Z][A-Z0-9\-]*\s+)?'                # label opcional (TECLY, R11)
        r'CO\s+\d+\s+'
        r'\$\s*([\d,]+)\s+\$\s*([\d,]+)\s*$')

    def parse(self, text: str, pdata: dict):
        # Normalizar apostrofes curvos y acento agudo a apostrofe
        # ASCII para que _RE_A (que incluye ' en la char class) no
        # rompa en variedades tipo "MAYRA'S BRIDAL" cuando el PDF
        # usa U+00B4, U+2019/U+2018 (curly), U+0092 o U+FFFD.
        for _bad in ('’', '‘', '´', '', '�'):
            text = text.replace(_bad, "'")
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
        # Total impreso: "18,00 37 9 .900 TOTAL: 3177,75" (COL, coma decimal).
        # Sin esto, líneas omitidas no dispararían aviso de "Parcial" (la
        # validación cruzada compararía sum(lines) consigo mismo).
        m = re.search(r'TOTAL\s*[:\s]\s*\$?\s*([\d.,]+)', text, re.I)
        if m:
            try:
                # Normaliza formato europeo (3.177,75) y plano (3177,75 / 3177.75)
                raw = m.group(1)
                if ',' in raw and '.' in raw:
                    h.total = float(raw.replace('.', '').replace(',', '.'))
                elif ',' in raw:
                    h.total = float(raw.replace(',', '.'))
                else:
                    h.total = float(raw)
            except ValueError:
                pass

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
                # En facturas LA ESTACION a veces aparece "Variety - FARM" en
                # la columna de variedad (ej. "Atomic - KENTIA", "Mondial -ALHOJA").
                # El regex captura el bloque entero; aquí separamos para que la
                # variedad quede limpia y el farm pase a label.
                farm_from_variety = ''
                m_split = re.match(r'^([A-Z][A-Z\s\']*?)\s*-\s*([A-Z0-9].*)$', variety)
                if m_split:
                    variety = m_split.group(1).strip()
                    farm_from_variety = m_split.group(2).strip()
                size = int(vm.group(2))
                stems = int(vm.group(3))
                cur_label = vm.group(4).strip() or farm_from_variety or label
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
            if vm:
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
                continue

            # Sub-línea de mixed box: variety colgada en la línea anterior
            # (separada por OCR del bloque de la box parent). Ej:
            #   L161: "MAYRA'S BRIDAL FRESH CUT"   ← variety + sufijo
            #   L162: "40CM 25 25 CO 0603110000 $ 0,32 $ 8,00"
            vm = self._RE_C.match(ln)
            if vm and i > 0:
                prev = text_lines[i - 1].strip()
                # Limpiar prev: quitar sufijos comunes ("FRESH CUT",
                # "ROSES*25STEMS", etc.) — la variedad real es lo que
                # queda al inicio en MAYÚSCULAS con apóstrofe permitido.
                m_var = re.match(
                    r"^([A-Z][A-Z\s']{1,30}?)(?:\s+FRESH\s+CUT|\s+ROSES\s*\*|\s*$)",
                    prev)
                if m_var:
                    var = m_var.group(1).strip()
                    if var and len(var) >= 2 and var not in (
                            'FRESH', 'ROSES', 'STEMS', 'PERSON', 'TOTAL',
                            'TIPO', 'CALIDAD', 'BREAKDOWN'):
                        try:
                            sz = int(vm.group(1))
                            stems = int(vm.group(3))
                            cur_label = (vm.group(4) or '').strip()
                            if cur_label and cur_label not in ('CO',):
                                label = cur_label
                            price = float(vm.group(5).replace(',', '.'))
                            total = float(vm.group(6).replace(',', '.'))
                        except (ValueError, AttributeError):
                            continue
                        lines.append(InvoiceLine(
                            raw_description=ln[:120], species='ROSES',
                            variety=var, origin='COL', size=sz,
                            stems_per_bunch=spb_default, stems=stems,
                            price_per_stem=price, line_total=total,
                            label=label, box_type=btype,
                            provider_key=pdata.get('key', ''),
                        ))
                        continue

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

    Variante 2026 (sesión 10l): añade columna `MARK` ("S.O.") entre
    box_type y qual, y usa **coma decimal** en price/total:
      "1 1 - 1 HB S.O. E 5 Salma 60 25 125 0,350 43,750"
    """
    @staticmethod
    def _num(s: str) -> float:
        """Acepta coma o punto como separador decimal.

        Heurística: el **último** separador determina qué es decimal.
        - `0,350` (solo coma) → 0.35
        - `0.350` (solo punto) → 0.35
        - `1,597.00` (formato inglés: miles con coma, decimal punto) → 1597.00
        - `1.597,00` (formato español: miles con punto, decimal coma) → 1597.00
        - `1.597.000` (varios puntos sin coma) → decimal punto si el
          último grupo es de 1-2 dígitos; si es 3 dígitos, se asume
          separador de miles arrastrado por OCR → 1597000.
        Defensivo: si falla el parseo, devuelve 0.0 para no romper el
        procesamiento de toda la factura.
        """
        s = s.strip()
        if not s:
            return 0.0
        last_dot = s.rfind('.')
        last_comma = s.rfind(',')
        try:
            if last_dot == -1 and last_comma == -1:
                return float(s)
            # El último separador (posición mayor) es el decimal.
            if last_dot > last_comma:
                # Decimal = punto; comas son miles (o no hay comas).
                return float(s.replace(',', ''))
            if last_comma > last_dot:
                # Decimal = coma; puntos son miles.
                return float(s.replace('.', '').replace(',', '.'))
            return float(s)
        except ValueError:
            return 0.0

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
        # Total desde línea TOTALS: "TOTALS 44 1100 0.255 280.500" o
        # "TOTALS 20 500 0,388 193,750" (coma decimal).
        m = re.search(r'TOTALS\s+\d+\s+\d+\s+[\d.,]+\s+([\d.,]+)', text)
        h.total = self._num(m.group(1)) if m else 0.0

        lines = []
        box_type = ''
        for ln in text.split('\n'):
            ln = ln.strip()
            # Línea completa (variante A): "1 1 - 1 HB E 12 Shimmer 50 25 300 0.280 84.000"
            # Variante B (2024): "11 - 1 QB GAIA.0050 ANA PREETO S.O2Explorer 50 25 50 0.280 14.000"
            #   (bunches pegado a variedad: "2Explorer")
            # Variante C (2026): "1 1 - 1 HB S.O. E 5 Salma 60 25 125 0,350 43,750"
            #   (coma decimal en price/total, columna MARK=S.O.)
            pm = re.search(
                r'\d+\s*-\s*\d+\s*(HB|QB|FB|EB)\s+.*?(\d+)\s*([A-Za-z][A-Za-z\s.\-/&]+?)\s+(\d{2,3})\s+(\d+)\s+(\d+)\s+([\d.,]+)\s+([\d.,]+)',
                ln)
            # Línea de continuación: "E 1 Wasabi 60 25 25 0.320 8.000"
            # Variante B: "E 2Mondial 50 25 50 0.280 14.000" (bunches pegado)
            # Variante C (2026): "E 5 Salma 70 25 125 0,400 50,000" (coma decimal)
            if not pm:
                pm2 = re.search(
                    r'^[A-Z]\s+(\d+)\s*([A-Za-z][A-Za-z\s.\-/&]+?)\s+(\d{2,3})\s+(\d+)\s+(\d+)\s+([\d.,]+)\s+([\d.,]+)$',
                    ln)
                if pm2:
                    bunches = int(pm2.group(1)); var = pm2.group(2).strip().upper()
                    sz = int(pm2.group(3)); spb = int(pm2.group(4))
                    stems = int(pm2.group(5))
                    price = self._num(pm2.group(6)); total = self._num(pm2.group(7))
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
            stems = int(pm.group(6))
            price = self._num(pm.group(7)); total = self._num(pm.group(8))
            il = InvoiceLine(raw_description=ln, species='ROSES', variety=var,
                             size=sz, stems_per_bunch=spb, bunches=bunches, stems=stems,
                             price_per_stem=price, line_total=total, box_type=box_type)
            lines.append(il)
        return h, lines


class GardaParser:
    """Formato GardaExport (Ecuador). Precios en formato europeo (coma decimal).

    Columnas del PDF:
      BOX N° | TB | PRODUCT NAME | BOX CODE | VARIETY | LENGTH(CM) |
      BUNCHES | STEMS | UNIT PRICE | TOTAL FOB $

    Variantes (sesión 10m):
    - Línea parent con box N°:
      "01 - 05 H ROSAS (ROSOIDEA) Explorer 60 50 1250 0,36 450,00"     (sin box code)
      "09 H ROSAS (ROSOIDEA) ELOY Brighton 50 5 125 0,30 37,50"        (con box code ELOY)
      "15 H ROSAS (ROSOIDEA) R16 Nectarine 50 10 250 0,30 75,00"       (box code R16)
    - Sub-línea sin box N° (hereda del parent):
      "H ROSAS (ROSOIDEA) ELOY Iguana 50 1 25 0,28 7,00"
      "H ROSAS (ROSOIDEA) ELOY Iguana 50 4 100 0,28 28,00"

    Bug previo (corregido): el box code (ELOY/ASTURIAS/MARL/R16/R19)
    se pegaba al variety ("ELOY BRIGHTON", "ASTURIAS EXPLORER") y
    las sub-líneas sin box N° se perdían por exigir `\\d{2}` al inicio.
    """
    _BT_MAP = {'H': 'HB', 'Q': 'QB', 'F': 'FB', 'E': 'EB'}

    # Regex único con box N° opcional. Box code = 3+ letras mayúsculas
    # consecutivas (ELOY/ASTURIAS/MARL/MERCO/CRISTIAN/GIJON/SEVILLA) o
    # `R\\d+` (R13/R16/R19). NO casa con variety en Capitalize (Explorer,
    # Iguana, Brighton) porque exige ≥3 mayúsculas seguidas.
    # Variety acepta apóstrofes (Pink O'Hara, Mayra's Bridal) y dígitos
    # (RM001 — código de variedad numérico aún sin nombre comercial).
    _LINE_RE = re.compile(
        r'^(?:\d{2}(?:\s*-\s*\d{2})?\s+)?'              # N° box opcional
        r'(?P<bt>[HQFE])\s+'                            # box_type abbrev
        r'ROSAS?\s*\([^)]*\)\s+'                        # PRODUCT NAME: "ROSAS (ROSOIDEA)"
        r'(?:(?P<code>[A-Z]{3,}|R\d+)\s+)?'             # BOX CODE opcional
        r"(?P<var>[A-Z][A-Za-z0-9\s.\-/&!']+?)\s+"      # VARIETY
        r'(?P<sz>\d{2,3})\s+(?P<b>\d+)\s+(?P<st>\d+)\s+'
        r'(?P<p>[\d.,]+)\s+(?P<tot>[\d.,]+)\s*$',
    )

    @staticmethod
    def _num_eu(s: str) -> float:
        """Formato europeo `1.234,56` → 1234.56."""
        return float(s.replace('.', '').replace(',', '.'))

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
        h.total = self._num_eu(m.group(1)) if m else 0.0

        lines = []
        for ln in text.split('\n'):
            ln = ln.strip()
            pm = self._LINE_RE.match(ln)
            if not pm:
                continue
            box_type = self._BT_MAP.get(pm.group('bt'), pm.group('bt'))
            # box_code va al label (no contamina variety). Casos sin
            # code (líneas sin ELOY/ASTURIAS/R\d+ antes de variety):
            # label queda vacío.
            label = (pm.group('code') or '').upper()
            var = pm.group('var').strip().upper()
            sz = int(pm.group('sz'))
            bunches = int(pm.group('b'))
            stems = int(pm.group('st'))
            price = self._num_eu(pm.group('p'))
            total = self._num_eu(pm.group('tot'))
            spb = stems // bunches if bunches else 25
            il = InvoiceLine(raw_description=ln, species='ROSES', variety=var,
                             size=sz, stems_per_bunch=spb, bunches=bunches, stems=stems,
                             price_per_stem=price, line_total=total, box_type=box_type,
                             label=label)
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
    # Alias de Rose con tolerancia OCR: Rose, Rbse, Rcse, Ros, R:ise, R:lse, Rlse
    _ROSE = r'(?:Rose|Rbse|Rcse|Ros|R:ise|R:lse|Rlse|Rlese|R\|se)'
    # Unidad: ST, S1, SI, Sl, 'ST, ST', sr (OCR garbage)
    _UNIT = r"(?:ST|S1|SI|Sl|SR|'?ST'?)"

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
        if not m:
            # MILONGA OCR: "NJCll:TOTAL (D�lares) 1,173.500" o "Vlr.Total FCA BOGOT�: 1,173.500"
            m = re.search(r'TOTAL\s+\(?D[\wóÓ�]*lares\)?\s*([\d,.]+)', text, re.I)
        if not m:
            m = re.search(r'Vlr\.?\s*Total\s+FCA[^:]*:\s*([\d,.]+)', text, re.I)
        h.total = self._money(m.group(1)) if m else 0.0

        lines = []
        box_type = 'HB'
        for ln_raw in text.split('\n'):
            ln = ln_raw.strip()
            # Normaliza ruido OCR típico de estas facturas: pipes, llaves,
            # caracteres raros (� { } [ ]), asteriscos y puntos sueltos
            # entre números. Mantiene la línea original para ``raw_description``.
            ln = re.sub(r'[\u00a6\u2022\u00b0{}\[\]~;]', ' ', ln)
            ln = re.sub(r'[\ufffd\u00ef\u00bf\u00bd]', ' ', ln)  # � y variantes
            ln = ln.replace('|', ' ').replace('*', ' ').replace('¡', ' ').replace('!', ' ')
            # "X2-5" pegado (OCR rompe X25) → "X 25", " i ee" ruido → " "
            ln = re.sub(r'X(\d)-(\d)(?=\s)', r'X\1\2', ln)
            ln = re.sub(r'\s+i\s+ee\s+', ' ', ln)
            # Dígito seguido de '~' o punto basura: "300 1~ " → "300 " (ruido stems_total)
            ln = re.sub(r'(?<=\d)\s*\d+[~\.]\s*(?=ST|SR|Sl)', ' ', ln, flags=re.I)
            # OCR de MILONGA (force_ocr=True) introduce ruido específico:
            #   "1 H_ Rose"          → "_" tras H/Q
            #   "1 Q — Rose"         → em/en-dash entre H/Q y Rose
            #   "64499:" / "42,000:" → trailing colon en números
            #   "42,000 ."           → punto huérfano al final
            #   "64503 > wo 150"     → tokens cortos sueltos entre números
            ln = re.sub(r'(?<=[HQhq])[_—–\-]+(?=\s)', '', ln)
            ln = re.sub(r'(?<=\s[HQhq])\s+[—–\-_:>.]+(?=\s)', '', ln)
            ln = re.sub(r'(?<=\d)[:.](?=\s|$)', '', ln)
            ln = re.sub(r'(?<=\d)\s+>\s*\w{1,3}\s+(?=\d)', ' ', ln)
            # Normaliza Rose OCR variants antes del regex principal
            ln = re.sub(r'\bR(?:[:]?ise|[:]?lse|lese|\|se)\b', 'Rose', ln, flags=re.I)
            ln = re.sub(r'\s{2,}', ' ', ln).strip()
            # Skip parents de caja mixta antes del regex principal: las
            # sub-lines siguientes traen el detalle real. Sin skip el lazy
            # (.+?) del regex principal rompe "Rose mix 116052 ..." y
            # captura variedad="mi" que no entra al filtro de skip
            # MIX/ASSORTED. Doble conteo del parent sobre la suma de
            # sub-lines.
            if re.match(
                r'^\d+\s+[HQ]\s+Rose\s+(?:mix|mixto|assorted|surtid\w*)\b',
                ln, re.I):
                continue
            # Línea principal: "1 H Rose Frutteto X 25 - 40 ... 300 300 ST 0.25 75.00"
            # Soporta 'RoseFrutteto' pegado, OCR 'Rbse'/'Rcse', unidad ST/S1/Sl,
            # decimales con coma, conteo de caja opcional (sub-líneas OCR sin prefijo).
            pm = re.search(
                rf'(?:\d+\s+)?(H|Q)\s+{self._ROSE}\s*(.+?)\s*X\s*(\d+)\s*[-_]?\s*(\d{{2,3}})\s+.+?\s+(\d+)\s+(\d+)\s+{self._UNIT}\s+([\d,.]+)\s+([\d,.]+)',
                ln, re.I)
            if pm:
                box_type = 'HB' if pm.group(1).upper() == 'H' else 'QB'
                var = pm.group(2).strip().upper()
                spb = int(pm.group(3)); sz = int(pm.group(4))
                stems_box = int(pm.group(5)); stems_total = int(pm.group(6))
                price = self._money(pm.group(7)); total = self._money(pm.group(8))
                # Skip "Rosemix"/"assorted" lines — their sub-lines follow
                if re.match(r'(?:ROSEMIX|ROSE\s*MIX|MIX|ASSORTED|SURTID)\b', var, re.I):
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
                if re.match(r'(?:ROSEMIX|ROSE\s*MIX|MIX|ASSORTED|SURTID)\b', var, re.I):
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
                continue
            # Variante CIRCASIA (factura COL con rango de size y label):
            # "1 Q Rose Tiffany 50 - 50 R14- 0603.11.00.00 150 150 Stems 0.28 $42.00"
            # Boxes H/Q, Rose, Variety, SIZE - SIZE (rango), label, tariff dotted,
            # stems_box stems_total "Stems" price "$total"
            pm5 = re.search(
                r'(\d+)\s+(H|Q)\s+Rose\s+([A-Za-z][A-Za-z\s]*?)\s+(\d{2,3})\s*-\s*\d{2,3}\s+'
                r'(?:\S+\s+)+?\d+\s+(\d+)\s+Stems\s+([\d.]+)\s+\$?([\d,.]+)',
                ln, re.I)
            if pm5:
                box_type = 'HB' if pm5.group(2).upper() == 'H' else 'QB'
                var = pm5.group(3).strip().upper()
                sz = int(pm5.group(4))
                stems = int(pm5.group(5))
                price = float(pm5.group(6))
                total = self._money(pm5.group(7))
                if stems > 0 and total > 0 and not re.match(r'(?:ASSORTED|SURTID|MIX)', var, re.I):
                    il = InvoiceLine(raw_description=ln, species='ROSES', variety=var, origin='COL',
                                     size=sz, stems_per_bunch=25, stems=stems,
                                     price_per_stem=price, line_total=total, box_type=box_type)
                    lines.append(il)
        return h, lines


class IwaParser:
    """Formato IWA Flowers: BOXES HB/QB STEMS ROSA COLOR VARIETY [SIZE [CM]] [FARM] TARIFF_10D ... Stems STEMS USD$ PRICE USD$ TOTAL
    Ejemplos:
      "10 HB 350 ROSA RED FREEDOM 50 CM 0603110000 Stems 3500 USD$ 0.280 USD$ 980.00"
      "1 HB 300 ROSA ASSORTED ASSORTED 50 0603110000 SO Stems 300 USD$ 0.293 USD$ 88.00"
      "1 HB 300 ROSA ASSORTED ROSA 0603110000 ADD Stems 300 USD$ 0.240 USD$ 72.00"  (sin size)
      "1 HB 350 ROSA ASSORTED ASSORTED 50 R19-Pili 0603110000 R19- Stems 350 USD$ 0.280 USD$ 98.00"
      "2 HB 350 ROSA WHITE TIBET 50 0603110000 Stems 700 USD$ 0.280 USD$ 196.00"
    El "CM" es opcional, puede haber farm code (R19, R19-Pili) entre size y tariff,
    y algunas lineas no traen size.
    """
    # Anclamos en el tariff de 10 digitos y el bloque final fijo "Stems N USD$ P USD$ T".
    # Todo lo que hay entre "ROSA" y el tariff es variety (+ size opcional + farm opcional).
    _LINE_RE = re.compile(
        r'(\d+)\s+(HB|QB)\s+\d+\s+ROSA\s+(.+?)\s+(\d{10})\b.*?'
        r'Stems\s+(\d+)\s+USD\$\s+([\d,.]+)\s+USD\$\s+([\d,.]+)',
        re.I)
    _SIZE_IN_DESC = re.compile(r'\b(\d{2,3})\b(?:\s*CM)?')

    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'(?:FACTURA|INVOICE)[:\s]+(\w+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'DATE\s+ISSUED\s*([\d\-/]+)', text, re.I); h.date = m.group(1) if m else ''
        m = re.search(r'TOTAL\s+USD\$?\s*([\d,.]+)', text, re.I)
        if m:
            try: h.total = float(m.group(1).replace(',', ''))
            except ValueError: h.total = 0.0
        lines = []
        for ln in text.split('\n'):
            raw = ln.strip()
            pm = self._LINE_RE.search(raw)
            if not pm:
                continue
            btype = pm.group(2).upper()
            middle = pm.group(3).strip().upper()
            stems = int(pm.group(5))
            try:
                price = float(pm.group(6).replace(',', ''))
                total = float(pm.group(7).replace(',', ''))
            except ValueError:
                continue
            # Extrae size si aparece como "50" o "50 CM" al final o en medio del bloque
            sz = 0
            sm = self._SIZE_IN_DESC.search(middle)
            if sm:
                sz_val = int(sm.group(1))
                if 30 <= sz_val <= 120:
                    sz = sz_val
                    # Quitar size y posibles "CM"/farm-code que venian pegados
                    middle = (middle[:sm.start()] + ' ' + middle[sm.end():]).strip()
            # Limpiar farm codes residuales tipo "R19-", "R19-PILI", "CM", "SO", "ADD"
            desc_tokens = [t for t in middle.split() if t
                           and not re.match(r'^R\d+(?:-\S*)?$', t)
                           and t not in ('CM', 'SO', 'ADD')]
            desc = ' '.join(desc_tokens).strip()
            # Clean variety: strip color prefix (RED/YELLOW/WHITE/PINK)
            var = re.sub(r'^(?:RED|YELLOW|WHITE|PINK|ROSA)\s+', '', desc).strip()
            if var in ('ASSORTED', 'MIX', '', 'ASSORTED ASSORTED'):
                var = 'SURTIDO MIXTO'
            il = InvoiceLine(raw_description=raw, species='ROSES', variety=var, origin='COL',
                             size=sz, stems_per_bunch=25, stems=stems,
                             price_per_stem=price, line_total=round(total, 2), box_type=btype)
            lines.append(il)
        if not h.total and lines:
            h.total = round(sum(l.line_total for l in lines), 2)
        return h, lines


class TimanaParser:
    """Formato Flores Timana: ROSE VARIETY COLOR SIZE [OF ]TARIFF BOXES HB BUNCHES SPB STEMS PRICE $ TOTAL
    Ejemplo: "ROSE FREEDOM RED 40CM CO-FREE0603110050 4 HB 12 25 1,200 0.260 $ 312.00"
    Algunas facturas añaden "OF " antes del tariff.

    Mixed boxes: parent "ASSORTED BOX LABEL [TARIFF] 1 HB 12 25 300 0.220 $ 66.000"
    se salta; sub-líneas "ROSE VARIETY COLOR SIZECM bunches spb price" heredan btype.
    """
    # Linea principal: captura opcional "OF" entre size y tariff
    _MAIN_RE = re.compile(
        r'ROSE\s+([A-Z][A-Z\s.\-/&+]+?)\s+(\d{2,3})CM\s+'
        r'(?:OF\s+)?'                                # label "OF" opcional
        r'\S+\s+'                                    # tariff (CO-FREE...)
        r'(\d+)\s+(HB|QB)\s+'                        # boxes + type
        r'(\d+)\s+(\d+)\s+'                          # bunches + spb
        r'([\d,]+)\s+([\d.]+)\s+\$\s+([\d,.]+)',     # stems + price + total
        re.I)
    # Sub-línea de assorted box (sin tariff, sin total, sin HB)
    _SUB_RE = re.compile(
        r'^ROSE\s+([A-Z][A-Z\s.\-/&+]+?)\s+(\d{2,3})CM\s+'
        r'(\d+)\s+(\d+)\s+([\d.]+)\s*$',              # bunches + spb + price
        re.I)
    # Parent assorted box: se ignora, las sub-líneas traen el detalle real
    _ASSORTED_RE = re.compile(r'^ASSORTED\s+BOX\b', re.I)

    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'INVOICE\s+(\d+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'(?:Issue|Ship)\s+Date[:\s]+([\d\-/]+)', text, re.I); h.date = m.group(1) if m else ''
        m = re.search(r'Total\s+FCA\s+\w+[:\s]*\$\s*([\d,.]+)', text, re.I)
        if m:
            h.total = float(m.group(1).replace(',', ''))
        lines = []
        last_btype = 'HB'
        for ln in text.split('\n'):
            raw = ln.strip()
            if self._ASSORTED_RE.search(raw):
                # Parent assorted — recordar btype para las sub-líneas, no emitir
                bt = re.search(r'\b(HB|QB)\b', raw)
                if bt:
                    last_btype = bt.group(1).upper()
                continue
            pm = self._MAIN_RE.search(raw)
            if pm:
                var = pm.group(1).strip()
                sz = int(pm.group(2))
                btype = pm.group(4).upper()
                last_btype = btype
                spb = int(pm.group(6))
                stems = int(pm.group(7).replace(',', ''))
                price = float(pm.group(8))
                total = float(pm.group(9).replace(',', ''))
                il = InvoiceLine(raw_description=raw, species='ROSES', variety=var, origin='COL',
                                 size=sz, stems_per_bunch=spb, stems=stems,
                                 price_per_stem=price, line_total=round(total, 2), box_type=btype)
                lines.append(il)
                continue
            sm = self._SUB_RE.match(raw)
            if sm:
                var = sm.group(1).strip()
                sz = int(sm.group(2))
                bunches = int(sm.group(3))
                spb = int(sm.group(4))
                price = float(sm.group(5))
                stems = bunches * spb
                total = round(stems * price, 2)
                il = InvoiceLine(raw_description=raw, species='ROSES', variety=var, origin='COL',
                                 size=sz, stems_per_bunch=spb, bunches=bunches, stems=stems,
                                 price_per_stem=price, line_total=total, box_type=last_btype)
                lines.append(il)
        if not h.total and lines:
            h.total = round(sum(l.line_total for l in lines), 2)
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
        last_bx = 1  # BX de la última línea primaria (variante A); las
                     # continuaciones de caja mixta heredan este BX para
                     # calcular bunches_total = BX × bunches_per_box.

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
            # Formato columnar: ORDER LABEL BX BOXTYPE [USA|EURO] [ROSALEDA] VARIETY CM SPB BUNCHES_PER_BOX STEMS_TOTAL PRICE TOTAL
            # - BOX_CODE: 1 o 2 tokens con dashes/dígitos (ASTURIAS-ALBU,
            #   GIJON R-48, GIJON -R43, GIJON R45, R13, SO, PUERTO...). El
            #   segundo token debe contener letra o dash (no sólo dígitos)
            #   para no confundirse con el BX.
            # - (USA|EURO): calificador opcional entre BOX_TYPE y ROSALEDA.
            #   Si no se captura aparte, entra como parte del variety.
            # - Captura BX para calcular bunches_total = BX × bunches_per_box
            #   (si no, validate reporta stems_mismatch cuando BX>1).
            pm = re.search(
                r'\d+\s*-\s*\d+\s+'
                r'(?:(?P<code>[A-ZÑÁÉÍÓÚÜ�][A-ZÑÁÉÍÓÚÜ�\d\-]*'
                r'(?:\s+(?=[A-ZÑÁÉÍÓÚÜ�\d\-]*[A-ZÑÁÉÍÓÚÜ�\-])[A-ZÑÁÉÍÓÚÜ�\d\-]+)?)\s+)?'
                r'(?P<bx>\d+)\s+(?P<btype>QB|HB|FB|EB)\s+'
                r'(?:(?:USA|EURO)\s+)?(?:ROSALEDA\s+)?'
                r'(?P<var>[A-Za-z][A-Za-z0-9\s.\-/&!]+?)\s+'
                r'(?P<sz>\d{2,3})\s+(?P<spb>\d+)\s+(?P<bpb>\d+)\s+(?P<stems>\d+)\s+'
                r'(?P<price>[\d.]+)\s+(?P<total>[\d.]+)',
                ln)
            if pm:
                if pm.group('code'): label = pm.group('code').strip()
                bx = int(pm.group('bx'))
                last_bx = bx
                box_type = pm.group('btype')
                var = pm.group('var').strip().upper(); sz = int(pm.group('sz'))
                spb = int(pm.group('spb')); bunches_per_box = int(pm.group('bpb'))
                stems = int(pm.group('stems')); price = float(pm.group('price')); total = float(pm.group('total'))
                bunches = bx * bunches_per_box
                il = InvoiceLine(raw_description=ln, species='ROSES', variety=var,
                                 size=sz, stems_per_bunch=spb, bunches=bunches, stems=stems,
                                 price_per_stem=price, line_total=total, box_type=box_type, label=label)
                lines.append(il)
                continue
            # Continuación (sin prefijo order): "QUEENS CROWN 50 25 2 50 0.350 17.500"
            # Hereda el BX de la última línea primaria para que bunches_total
            # cuadre con stems cuando la caja mixta tiene múltiples variedades.
            pm2 = re.search(
                r'^([A-Z][A-Z\s.\-/&]+?)\s+(\d{2,3})\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)\s+([\d.]+)$',
                ln)
            if pm2 and lines:
                var = pm2.group(1).strip(); sz = int(pm2.group(2))
                spb = int(pm2.group(3)); bunches_per_box = int(pm2.group(4))
                stems = int(pm2.group(5)); price = float(pm2.group(6)); total = float(pm2.group(7))
                bunches = last_bx * bunches_per_box
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

    Variante PROFORMA (sesión 10h): encabezados diferentes,
    `HITS No. DESCRIPTION BRAND BOX BOX TYPE PCS FULL PACKING T.STEMS
    UNIT UNIT PRICE TOTAL VALUE`. Línea típica:
    ``0603.11.00.50 ROSES BLUSH 50 HB 1 0.5 300 300 STEMS $ 0.32 $ 96.00``
    """
    # PROFORMA line regex (formato sample 01 y 02 que antes caían en NO_PARSEA).
    # El OCR puede partir el total en dos tokens ("$ 1 92.00" → 192.00);
    # toleramos uno o varios grupos de dígitos antes del `.dd` final.
    _PROFORMA_RE = re.compile(
        r'06\d{2}\.\d{2}\.\d{2}\.\d{2}\s+'          # tariff code
        r'ROSES?\s+'
        r'(?P<variety>[A-Z][A-Z\s]*?)\s+'
        r'(?P<size>\d{2,3})\s+'
        r'(?P<box_type>HB|QB|FB|TB)\s+'
        r'(?P<boxes>\d+)\s+'
        r'[\d.]+\s+'                                 # FULL PACKING
        r'(?P<stems_per_box>\d+)\s+'
        r'(?P<stems>\d+)\s+STEMS\s+'
        r'\$\s*(?P<price>[\d.]+)\s+'
        r'\$\s*(?P<total>[\d\s.,]+?)\s*$',
        re.I,
    )

    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'INVOICE[:\s]+(\d+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'DATE\s+ISSUED\s*([\d\-/]+)', text, re.I); h.date = m.group(1) if m else ''
        m = re.search(r'MAWB[:\s]*([\d\-]+)', text, re.I); h.awb = re.sub(r'\s+', '', m.group(1)) if m else ''
        m = re.search(r'HAWB[:\s]*([\d\-]+)', text, re.I); h.hawb = m.group(1) if m else ''
        m = re.search(r'TOTAL\s+US[D]?\s*\$\s*([\d,.]+)', text, re.I)
        h.total = float(m.group(1).replace(',', '')) if m else 0.0

        lines = []
        text_lines = text.split('\n')
        for i, ln in enumerate(text_lines):
            ln = ln.strip()

            # ── Variante PROFORMA (probar primero; no compite con legacy) ──
            pm_pro = self._PROFORMA_RE.search(ln)
            if pm_pro:
                var = pm_pro.group('variety').strip().upper()
                sz = int(pm_pro.group('size'))
                box_type = pm_pro.group('box_type').upper()
                stems = int(pm_pro.group('stems'))
                price = float(pm_pro.group('price'))
                # El total puede venir como "192.00" o "1 92.00" (OCR split).
                total_raw = pm_pro.group('total').replace(' ', '').replace(',', '')
                try:
                    total = float(total_raw)
                except ValueError:
                    total = round(stems * price, 2)
                spb = 25  # rosas default
                bunches = stems // spb if spb else 0
                lines.append(InvoiceLine(
                    raw_description=ln, species='ROSES', variety=var,
                    origin='COL', size=sz, stems_per_bunch=spb,
                    bunches=bunches, stems=stems,
                    price_per_stem=price, line_total=total,
                    box_type=box_type,
                ))
                continue

            # ── Variante legacy (facturas comerciales con formato "Stems ... US$") ──
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
    Ejemplos:
      "1 Tabaco 500 CARNATIONS BERNARD NOVELTY DUTY FREE FANCY . CO-0603129000 $0.1700 $85.00"
      "1 Tabaco 500 MINICARNATIONS ZUMBA RED DUTY FREE SELECT . CO-0603121000 $0.1800 $90.00"
      "20 Tabaco 10000 CLAVEL SURTIDO (no pink) DUTY FREE FANCY . CO-0603129000 $0.1700 $1,700.00"
    """
    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'INVOICE\s+No\.?\s*(\d+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'ISSUE\s+DATE\s*:\s*(.+?)(?:\d{2}:\d{2}|$)', text, re.I)
        h.date = m.group(1).strip() if m else ''
        m = re.search(r'AWB\s+([\d\-]+)', text, re.I); h.awb = re.sub(r'\s+', '', m.group(1)) if m else ''
        m = re.search(r'HAWB\s+([\d\-]+)', text, re.I); h.hawb = m.group(1) if m else ''
        # Total real impreso en la factura: "Total Value $3,915.00" (o
        # "SubTotal Value"). Necesario para que la validación cruzada
        # detecte si falta alguna línea — antes derivábamos h.total de
        # sum(lines) y eso ocultaba siempre el gap.
        m = re.search(r'Total\s+Value\s*\$?\s*([\d,]+\.\d{2})', text, re.I)
        if not m:
            m = re.search(r'SubTotal\s+Value\s*\$?\s*([\d,]+\.\d{2})', text, re.I)
        printed_total = float(m.group(1).replace(',', '')) if m else 0.0

        lines = []
        for ln in text.split('\n'):
            ln = ln.strip()
            # Normalización OCR para escaneos ruidosos:
            #   "C0-" (cero) → "CO-", "OUTYFREE" → "DUTYFREE",
            #   "DUTYFREE"/"DUTY FREE" indistintos. El grade puede venir
            #   precedido por ".0" o ".", los precios sin "$" prefix.
            ln_n = re.sub(r'\bC0-', 'CO-', ln)
            ln_n = re.sub(r'\bOUTY\s*FREE?\b', 'DUTYFREE', ln_n, flags=re.I)
            # Acepta tres variantes de cabecera de línea:
            #   CARNATIONS         → claveles standard (spb=20)
            #   MINICARNATIONS     → mini claveles (spb=10)
            #   CLAVEL SURTIDO     → mezcla en español (spb=20, var=MIXTO)
            # `desc` es opcional (CLAVEL SURTIDO DUTY FREE FANCY ... viene
            # sin descripción). El separador entre grade y CO-XXX puede
            # ser ".", "0", o un label corto tipo "R14".
            pm = re.search(
                r'(\d+)\s+Taba\w*\s+(\d+)\s+'
                r'(MINICARNATIONS?|CARNATIONS|CLAVEL\s+SURTIDOS?)'
                r'(?:\s+(.+?))?\s+'
                r'(?:DUTY\s*FREE?|DUTYFREE|REGULAR)\s+(\w+)\s+'
                r'(?:[A-Za-z0-9.]+\s+)*'
                r'CO-[\d]+\s+'
                r'\$?([\d.]+)\s+\$?([\d.,]+)',
                ln_n, re.I)
            if not pm:
                continue
            boxes = int(pm.group(1)); stems = int(pm.group(2))
            species_tok = pm.group(3).upper().replace(' ', '')
            desc = (pm.group(4) or '').strip()
            grade = pm.group(5).strip().upper()  # FANCY, SELECT, etc.
            price = float(pm.group(6)); total = float(pm.group(7).replace(',',''))
            # Mini claveles vienen empaquetados en bouquets de 10 tallos.
            spb_default = 10 if species_tok.startswith('MINI') else 20
            # CLAVEL SURTIDO: el desc lleva el color/exclusión entre
            # paréntesis (ej. "(no pink)"). Lo descartamos para el
            # match — la variedad efectiva es siempre MIXTO.
            if species_tok.startswith('CLAVELSURTIDO'):
                full_var = 'MIXTO'
            else:
                # Separar variedad y color del desc:
                #   "BERNARD NOVELTY" → var=BERNARD, color=NOVELTY
                parts = desc.upper().split()
                var = parts[0] if parts else desc.upper()
                color = ' '.join(parts[1:]) if len(parts) > 1 else ''
                full_var = var
                if color and color not in ('SURTIDOS',):
                    full_var = f'{var} {color}'
            il = InvoiceLine(raw_description=ln, species='CARNATIONS', variety=full_var, origin='COL',
                             size=70, stems_per_bunch=spb_default, stems=stems,
                             price_per_stem=price, line_total=total, box_type='TB', grade=grade)
            lines.append(il)
        # Preferir el total impreso; sólo caer al sum(lines) si la
        # factura no expone un total parseable (raro).
        h.total = printed_total or sum(l.line_total for l in lines)
        return h, lines


class CustomerInvoiceParser:
    """Plataforma 'CUSTOMER INVOICE' (Cananvalle, Trebol, Much, Naranjo).
    Formato: # BOX_TYPE PRODUCT SPECIES ... QTY_BUNCH $BUNCH_PRICE QTY_STEMS $STEM_PRICE $TOTAL
    Ejemplo: "1 QB CARPE DIEM 40CM A 25ST CV ROSES 5 $10.0000 125 $0.4000 $50.00"

    Variante SAMPLE (Cananvalle, sesión 10h): "Commercial Invoice"
    en lugar de "Customer Invoice", tabla sin $ signs, columnas:
    ``Qty BoxNo(a-b) BoxType Variety Length BunchesPerBox TotalBunches
    StemsPerBunch TotalStems UnitPrice TotalPrice[SAMPLE]``.
    Ejemplo: ``1 1 - 1 HB Brighton 50 1 1 25 25 0.010 0.250SAMPLE``.
    """
    # Variante SAMPLE (sin $, con rango box no y sufijo SAMPLE).
    _SAMPLE_RE = re.compile(
        r'^(?P<qty>\d+)\s+'
        r'\d+\s*-\s*\d+\s+'                       # Box No. range "1 - 1"
        r'(?P<box_type>HB|QB|FB|TB)\s+'
        r'(?P<variety>[A-Za-z][A-Za-z\s]*?)\s+'
        r'(?P<length>\d{2,3})\s+'
        r'\d+\s+(?P<total_bunches>\d+)\s+'        # bunches_per_box total_bunches
        r'(?P<spb>\d+)\s+(?P<stems>\d+)\s+'       # stems_per_bunch total_stems
        r'(?P<price>[\d.]+)\s+'
        r'(?P<total>[\d.]+)(?:SAMPLE)?\s*$',
        re.I,
    )

    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'(?:CUSTOMER|COMMERCIAL)\s+INVOICE\s+(?:No\.)?\s*(\d+)', text, re.I)
        h.invoice_number = m.group(1) if m else ''
        m = re.search(r'Invoice\s+Date\s+([\d/\-]+)', text, re.I); h.date = m.group(1) if m else ''
        m = re.search(r'MAWB\s*:?\s*([\d\-\s]+)', text, re.I); h.awb = re.sub(r'\s+', '', m.group(1)).strip() if m else ''
        m = re.search(r'HAWB\s*:?\s*([\w\-]+)', text, re.I); h.hawb = m.group(1) if m else ''
        m = re.search(r'Amount\s+Due\s+\$([\d,.]+)', text, re.I)
        h.total = float(m.group(1).replace(',', '')) if m else 0.0

        lines = []
        for ln in text.split('\n'):
            ln = ln.strip()
            if 'TOTALS' in ln.upper():
                continue

            # ── Variante SAMPLE (Commercial Invoice sin $) ─────────────
            ps = self._SAMPLE_RE.match(ln)
            if ps:
                var = ps.group('variety').strip().upper()
                sz = int(ps.group('length'))
                spb = int(ps.group('spb'))
                stems = int(ps.group('stems'))
                bunches = int(ps.group('total_bunches'))
                price = float(ps.group('price'))
                total = float(ps.group('total'))
                lines.append(InvoiceLine(
                    raw_description=ln, species='ROSES', variety=var,
                    origin='EC', size=sz, stems_per_bunch=spb,
                    bunches=bunches, stems=stems,
                    price_per_stem=price, line_total=total,
                    box_type=ps.group('box_type').upper(),
                ))
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
    Multi-línea: "1 QB 500 25 CARNATION DESC SIZE LABEL HTS# [ORDEN] Stems STEMS US$ PRICE US$ [PRICE] US$"
    seguido de "TOTAL" en la siguiente línea.
    Ejemplos:
      "1 QB 500 25 CARNATION MIX 55 CM R14 0603.12.7000 Stems 500 US$ 0.130 US$ 2.600 US$\\n65.00"
      "2 HB 600 60 CARNATION MIX VERALEZA 0603.12.7000 ORDEN Stems 1200 US$ 0.080 US$ US$"
      "l QB 500 25 CARNATION MIX 55 Rl4 0603.12.7000 ORDEN Stems 500 US$ 0.120 .US$ US$"  (OCR)
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
            # OCR cleanup: "l" al inicio suele ser "1"; ".US$" ruido -> "US$"; "US$0.120!" -> "US$ 0.120"
            ln_norm = re.sub(r'^l(?=\s)', '1', ln)
            ln_norm = re.sub(r'(?<=\s)Rl(\d)', r'R1\1', ln_norm)  # Rl4 -> R14
            ln_norm = re.sub(r'\.US\$', 'US$', ln_norm)
            ln_norm = re.sub(r'US\$(\d)', r'US$ \1', ln_norm)     # US$0.120 -> US$ 0.120
            ln_norm = ln_norm.replace('!', '').replace("'CARNATION", 'CARNATION')
            # "1 QB 500 25 CARNATION MIX 55 CM R14 0603.12.7000 [ORDEN] Stems 500 US$ 0.130 US$"
            # .+? antes de Stems absorbe "ORDEN" u otros tokens opcionales.
            pm = re.search(
                r'(\d+)\s+(QB|HB)\s+(\d+)\s+(\d+)\s+CARNATION\s+(.+?)\s+06[\d.]+\s+.*?Stems\s+(\d+)\s+US\$\s+([\d.]+)\s+(?:\.?US\$|\S+)',
                ln_norm, re.I)
            if not pm:
                continue
            boxes = int(pm.group(1)); box_type = pm.group(2)
            stems_box = int(pm.group(3)); bunches_box = int(pm.group(4))
            # spb = stems_per_box / bunches_per_box (no bunches_per_box directo).
            spb_raw = stems_box // bunches_box if bunches_box else 25
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
            # Si la variety es solo tokens de color (RED RED, WHITE WHITE,
            # YELLOW, etc.), traducir a ES y de-duplicar. Estos claveles
            # genéricos indexan por color en catálogo (CLAVEL COL FANCY
            # ROJO 70CM 20U).
            from src.config import CARNATION_COLOR_MAP
            var_tokens = var.split()
            if var_tokens and all(t.rstrip('.') in CARNATION_COLOR_MAP for t in var_tokens):
                # Usar primer token (normalmente todos son iguales o duplicado OCR)
                first = var_tokens[0].rstrip('.')
                var = CARNATION_COLOR_MAP.get(first, first)
            sz_m = re.search(r'(\d{2})\s*CM', pm.group(5), re.I)
            sz = int(sz_m.group(1)) if sz_m else 70  # default clavel COL 70cm
            il = InvoiceLine(raw_description=ln, species='CARNATIONS', variety=var, origin='COL',
                             size=sz, stems_per_bunch=spb_raw, stems=stems,
                             price_per_stem=price, line_total=total, box_type=box_type)
            lines.append(il)

        # Variante B (factura electrónica COL / DIAN): línea repetitiva
        # "CARNATION DIANTHUS CARYOPHYLLUS DIANTHUS CARYOPHYLLUS CARNATION STEMS $PRICE $TOTAL"
        # Solo ejecutar si la variante A (parser principal) no encontró nada.
        if not lines:
            for ln in text_lines:
                ln = ln.strip()
                bm = re.search(
                    r'CARNATION\s+DIANTHUS\s+CARYOPHYLLUS\s+DIANTHUS\s+CARYOPHYLLUS\s+CARNATION\s+'
                    r'(\d+)\s+\$([\d.]+)\s+\$([\d,.]+)',
                    ln, re.I)
                if not bm:
                    continue
                try:
                    stems = int(bm.group(1))
                    price = float(bm.group(2))
                    total = float(bm.group(3).replace(',', ''))
                except ValueError:
                    continue
                il = InvoiceLine(raw_description=ln, species='CARNATIONS', variety='MIXTO',
                                 origin='COL', size=55, stems_per_bunch=25, stems=stems,
                                 price_per_stem=price, line_total=round(total, 2), box_type='HB')
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

    También captura "Garden Roses - VARIETY ..." (rosas garden) que antes
    el regex `Rosas?` (Rosa con `s?`) no matcheaba — sesión 12h.
    Stems acepta separador de miles con punto: "1.200" → 1200.
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
            # "Garden Roses - Country Home 50cm 0,00 0,00 550 0,27 148,50"
            # Stems puede traer punto de miles ("1.200" = 1200).
            pm = re.search(
                r'\b(?:Garden\s+)?Ros[ae]s?\s*-\s*'
                r'([A-Za-z][A-Za-z\s.\-/&]+?)\s+(\d{2,3})\s*cm\s+'
                r'[\d,]+\s+[\d,]+\s+([\d.]+)\s+([\d,]+)\s+([\d,]+)',
                ln, re.I)
            if not pm:
                continue
            var = pm.group(1).strip().upper(); sz = int(pm.group(2))
            try:
                stems = int(pm.group(3).replace('.', ''))
            except ValueError:
                continue
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
        # Total real: línea resumen al final de la tabla, formato:
        # "16 Full Equivalent:7.750 ... 4,475 179 1,337.50". El último
        # número con 2 decimales tras la columna "bunches" es el total.
        m = re.search(
            r'Full\s+Equivalent[:\s\d.,]*\s+\d+\s+\d+\s+([\d,]+\.\d{2})',
            text, re.I)
        printed = float(m.group(1).replace(',', '')) if m else 0.0
        h.total = printed or sum(l.line_total for l in lines)
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
        # Total real impreso ("TOTAL USD $ XXX.XX" / "VALOR TOTAL XXX,XX").
        # Sin esto, derivar de sum(lines) ocultaría líneas no parseadas.
        m = re.search(r'(?:TOTAL\s+USD?|VALOR\s+TOTAL|TOTAL\s+A\s+PAGAR)\s*\$?\s*([\d,]+\.\d{2})', text, re.I)
        printed = float(m.group(1).replace(',', '')) if m else 0.0
        h.total = printed or sum(l.line_total for l in lines)
        return h, lines
