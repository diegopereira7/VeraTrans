from __future__ import annotations

import re

from src.models import InvoiceHeader, InvoiceLine


class SayonaraParser:
    """
    C.I. Cultivos Sayonara SAS -- Crisantemos (id_proveedor=2166).

    Estructura de la factura:
    - Producto individual: "Pom Csh Europa White Bonita CO-... 5 HB 200 1,000 0.950 190.00"
    - Custom Pack (caja mixta): "Pom Csh Europa Custom Pack CO-... MERCO 2 HB 80 400 0.950 76.00"
      Seguido de líneas detalle: "Pom Csh Europa Exportacion Yellow Bernal CO-... 120 0.19"
      Cada línea detalle es una variedad con sus tallos — se divide el total del pack.
    """

    _TYPE_MAP = [
        ('Disbud Cremon', 'BI CREMON',   10),
        ('Disbud Spider', 'BI SPIDER',   10),
        ('Pom Csh',       'SP CUSHION',   5),
        ('Pom Btn',       'SP BUTTON',    5),
        ('Pom Dsy',       'SP DAISY',     5),
        ('Pom Nov',       'SP NOVELTY',   5),
        ('Pom CDN',       'SP CDN',       5),
        ('Santini',       'SA SANTINI',  25),
        # Plantilla reciente: "Pom Europa/Asia White Cushion Bonita ..." — palabra clave final
        ('Cushion',       'SP CUSHION',   5),
        ('Button',        'SP BUTTON',    5),
        ('Daisy',         'SP DAISY',     5),
        ('Cremon',        'BI CREMON',   10),
        ('Spider',        'BI SPIDER',   10),
        # Sesión 12r: "Pom Europa/Asia Assorted CDN x 40 Bunch CO-..." —
        # CDN suelto (sin "Pom" pegado) en facturas mixed-Assorted.
        ('CDN',           'SP CDN',       5),
    ]

    _COLOR_MAP = [
        ('Bronze Dark', 'BRONCE OSCURO'), ('White', 'BLANCO'), ('Yellow', 'AMARILLO'),
        ('Red', 'ROJO'), ('Pink', 'ROSA'), ('Purple', 'LILA'), ('Green', 'VERDE'),
        ('Orange', 'NARANJA'), ('Bronze', 'BRONCE'), ('Cream', 'CREMA'),
        ('Salmon', 'SALMON'), ('Blue', 'AZUL'), ('Bicolor', 'BICOLOR'), ('Mix', 'MIXTO'),
    ]

    _PACK_RE = re.compile(r'(\d+)\s+(HB|QB)\s+(\d+)\s+([\d,]+)\s+([\d.]+)\s+([\d,.]+)')
    # Variante con suffix pegado (HB15 = Half Box bunches x 15) y tokens
    # reordenados: "6 HB15 1200 240 $0.950 $228.00" — (boxes, btype+spb, stems, bunches, price, total)
    _PACK_RE_B = re.compile(r'(\d+)\s+(HB|QB)(\d+)\s+(\d+)\s+(\d+)\s+\$([\d.]+)\s+\$([\d,.]+)')
    _DETAIL_RE = re.compile(r'Exportacion\s+(.+?)\s+CO-\d+.*?\s+(\d+)\s+([\d.]+)\s*$', re.I)
    _TOTAL_RE = re.compile(r'^Pom\s+\w+\s+Europa\s+[\d,]+\s+[\d,.]+\s*$', re.I)

    def _detect_type(self, line: str):
        for prefix, tipo, bunch in self._TYPE_MAP:
            if prefix.lower() in line.lower():
                return prefix, tipo, bunch
        return None

    def _translate_color(self, name: str) -> str:
        """Traduce color inglés → español."""
        for en, es in self._COLOR_MAP:
            if en.lower() in name.lower():
                return es
        return name.upper()

    def _extract_variety_from_name(self, name: str) -> tuple[str, str]:
        """Extrae (variedad, color_es) de un nombre como 'Yellow Bernal' o 'White Bonita WH'.

        Para Sayonara, la variedad es el nombre completo (ej: BERNAL, LAMBRUSCO, VINTAGE CANDID)
        y el color es la primera palabra si es un color conocido (Yellow→AMARILLO, Pink→ROSA).
        Si no empieza con color (ej: 'Vintage Candid'), la variedad es todo y no hay color separado.
        """
        name = re.sub(r'\s+WH\s*$', '', name, flags=re.I).strip()
        # Buscar color al inicio
        for en, es in self._COLOR_MAP:
            if name.lower().startswith(en.lower()):
                rest = name[len(en):].strip().upper()
                return rest, es
        # Sin color reconocido — todo es variedad
        return name.upper(), ''

    def _extract_label(self, line: str) -> str:
        m = re.search(r'CO-\d+\s+([A-ZÀ-Úa-zà-ú][A-ZÀ-Úa-zà-ú\s]{1,}?)\s+\d+\s+(?:HB|QB)', line, re.I)
        if m:
            label = m.group(1).strip().upper()
            if label and label not in ('CO', 'COLOMBIA'):
                return label
        return ''

    def _extract_variety_from_pack(self, line: str, prefix: str) -> tuple[str, str]:
        """Extrae variedad de una línea PACK (no Custom Pack/Mix)."""
        idx = line.lower().find(prefix.lower())
        if idx < 0:
            return '', 'MIXTO'
        rest = line[idx + len(prefix):].strip()
        rest = re.sub(r'\bEuropa\b', '', rest, flags=re.I).strip()
        if re.match(r'Custom\s+Pack|Mix\b', rest, re.I):
            return '', 'MIXTO'
        color_es = 'MIXTO'
        variety = ''
        for en, es in self._COLOR_MAP:
            m = re.search(re.escape(en), rest, re.I)
            if m:
                color_es = es
                after = rest[m.end():].strip()
                var_m = re.match(r'([A-Za-z][A-Za-z\s.\-/]*?)(?=\s+CO-|\s+\d|\s*$)', after)
                if var_m:
                    variety = var_m.group(1).strip().upper()
                break
        return variety, color_es

    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'No\.\s+(\d+)', text); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'Invoice\s+Date\s+([\w\-/]+)', text, re.I); h.date = m.group(1) if m else ''
        m = re.search(r'Master\s+AWB\s+([\d\-]+)', text, re.I); h.awb = re.sub(r'\s+', '', m.group(1)) if m else ''
        m = re.search(r'House\s+AWB\s+([\w\-]+)', text, re.I); h.hawb = m.group(1) if m else ''
        h.total = 0.0
        # Sesión 12r: añadido patrón "Total $<num>" para facturas
        # OCR-corruptas (ej. SAYONARA 64811 donde el detalle es ilegible
        # pero el header total "$114.00" se ve claro). Sin esto el parser
        # devolvía h.total=0 y la UI no podía alertar el gap.
        for pat in (
            r'Total\s+Value\s+\w*\s*US\$?\s*([\d,]+\.\d+)',  # "Total Value USE US 1,520.00"
            r'(?:TOTAL|Total\s+USD)[:\s]*([\d,]+\.\d+)',
            r'(?:^|\s)Total\s*\$\s*([\d,]+\.\d+)',           # "Total $114.00"
        ):
            m = re.search(pat, text, re.I | re.M)
            if m:
                try:
                    h.total = float(m.group(1).replace(',', ''))
                    break
                except Exception:
                    continue

        # Fase 1: clasificar líneas en PACK y DETAIL
        raw_lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
        packs = []      # lista de {line, tipo, prefix, bunch, stems, price, total, label, is_mix, details:[]}
        current_pack = None

        def _ocr_clean(s: str) -> str:
            """Quita ruido de OCR pobre: pipes, corchetes, em-dash, underscore
            entre números. Sample 45997243 tiene '0.950] — 760.00' y '|'
            separadores."""
            s2 = s.replace('|', ' ').replace(']', ' ').replace('[', ' ')
            # em-dash/en-dash/underscore entre números → quitar
            s2 = re.sub(r'[\u2013\u2014\u2015_]\s*(?=\d)', '', s2)
            s2 = re.sub(r'\s{2,}', ' ', s2).strip()
            return s2

        for raw_ln in raw_lines:
            ln = _ocr_clean(raw_ln)
            if self._TOTAL_RE.match(ln):
                continue

            detected = self._detect_type(ln)
            if not detected:
                continue

            prefix, tipo, bunch = detected
            pack_m = self._PACK_RE.search(ln)
            pack_m_b = None if pack_m else self._PACK_RE_B.search(ln)
            detail_m = self._DETAIL_RE.search(ln)

            if pack_m:
                # Línea PACK (facturable). Groups PACK_RE:
                # (boxes, btype, bunches, stems, price, total)
                is_mix = bool(re.search(r'Custom\s+Pack|Mix\b', ln, re.I))
                current_pack = {
                    'line': ln, 'tipo': tipo, 'prefix': prefix, 'bunch': bunch,
                    'boxes': int(pack_m.group(1)),
                    'btype': pack_m.group(2).upper(),
                    'bunches': int(pack_m.group(3)),
                    'stems': int(pack_m.group(4).replace(',', '')),
                    'price': float(pack_m.group(5)),
                    'total': float(pack_m.group(6).replace(',', '')),
                    'label': self._extract_label(ln),
                    'is_mix': is_mix,
                    'details': [],
                }
                packs.append(current_pack)
            elif pack_m_b:
                # Groups PACK_RE_B: (boxes, btype, spb_inline, stems, bunches, price, total).
                # Aquí el spb viene explícito en HB15 y sustituye al del tipo.
                is_mix = bool(re.search(r'Custom\s+Pack|Mix\b', ln, re.I))
                current_pack = {
                    'line': ln, 'tipo': tipo, 'prefix': prefix,
                    'bunch': int(pack_m_b.group(3)) or bunch,
                    'boxes': int(pack_m_b.group(1)),
                    'btype': pack_m_b.group(2).upper(),
                    'bunches': int(pack_m_b.group(5)),
                    'stems': int(pack_m_b.group(4)),
                    'price': float(pack_m_b.group(6)),
                    'total': float(pack_m_b.group(7).replace(',', '')),
                    'label': self._extract_label(ln),
                    'is_mix': is_mix,
                    'details': [],
                }
                packs.append(current_pack)
            elif detail_m and current_pack and current_pack['is_mix']:
                # Línea detalle de Custom Pack
                current_pack['details'].append({
                    'name': detail_m.group(1).strip(),
                    'stems': int(detail_m.group(2)),
                    'price_unit': float(detail_m.group(3)),
                    'raw': ln,
                })

        # Fase 2: generar InvoiceLines
        lines = []
        for pack in packs:
            if not pack['is_mix'] or not pack['details']:
                # Producto individual o mix sin detalle → una línea.
                variety, color = self._extract_variety_from_pack(pack['line'], pack['prefix'])
                var_stored = f"{pack['tipo']} {variety} {color}".replace('  ', ' ').strip()
                lines.append(InvoiceLine(
                    raw_description=pack['line'], species='CHRYSANTHEMUM',
                    variety=var_stored, grade='', origin='COL', size=70,
                    stems_per_bunch=pack['bunch'],
                    bunches=pack['bunches'],
                    stems=pack['stems'], price_per_stem=pack['price'],
                    line_total=pack['total'], label=pack['label'],
                    box_type=pack['btype'], provider_key='sayonara',
                ))
            else:
                # Caja mixta con detalle → una línea por variedad.
                # Cada detalle tiene su propio price_unit (ej 0.19) distinto
                # del price del pack (0.950). Usamos price_unit para que
                # stems * price_per_stem == line_total y evitar disparar
                # validation_errors (total_mismatch) que caparían link_conf.
                for d in pack['details']:
                    variety, color = self._extract_variety_from_name(d['name'])
                    var_stored = f"{pack['tipo']} {variety} {color}".replace('  ', ' ').strip()
                    if not variety:
                        continue
                    price_unit = d.get('price_unit') or pack['price']
                    line_total = round(d['stems'] * price_unit, 2)
                    bunches = d['stems'] // pack['bunch'] if pack['bunch'] else 0
                    lines.append(InvoiceLine(
                        raw_description=d['raw'], species='CHRYSANTHEMUM',
                        variety=var_stored, grade='', origin='COL', size=70,
                        stems_per_bunch=pack['bunch'], bunches=bunches,
                        stems=d['stems'], price_per_stem=price_unit,
                        line_total=line_total, label=pack['label'],
                        box_type='MIX', provider_key='sayonara',
                    ))

        if not h.total and lines:
            h.total = round(sum(l.line_total for l in lines), 2)
        return h, lines
