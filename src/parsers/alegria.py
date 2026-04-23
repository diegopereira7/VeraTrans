from __future__ import annotations

import re

import pdfplumber

from src.models import InvoiceHeader, InvoiceLine


# Columnas de tamaño en la tabla (índices 6..15 = 30,40,50,60,70,80,90,100,110,120)
_SIZE_COLS = {6: 30, 7: 40, 8: 50, 9: 60, 10: 70, 11: 80, 12: 90, 13: 100, 14: 110, 15: 120}


class AlegriaParser:
    """Formato tabular con cuadrícula de tamaños por columna.

    La factura tiene columnas 30-120cm. El número en cada columna indica
    cuántos bunches de ese tamaño hay. Se usa pdfplumber.extract_tables()
    para respetar la posición de columnas que el texto plano pierde.
    """

    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']
        h.provider_id = pdata['id']
        h.provider_name = pdata['name']

        # Header: regex sobre texto plano (funciona bien)
        m = re.search(r'INVOICE[:\s]*(\d+)', text, re.I)
        h.invoice_number = m.group(1) if m else ''
        # FIX: CERES pega DATE sin espacio ("DATE31/12/2025"), \s* en vez de \s+
        m = re.search(r'DATE\s*([\d/\-]+)', text, re.I)
        h.date = m.group(1) if m else ''
        m = re.search(r'M\.?A\.?W\.?B\.?\s*([\d\-]+)', text, re.I)
        h.awb = re.sub(r'\s+', '', m.group(1)) if m else ''
        m = re.search(r'H\.?A\.?W\.?B\.?\s*(\S+)', text, re.I)
        h.hawb = m.group(1) if m else ''
        m = re.search(r'TOTAL\s+USD\D*([\d,]+\.?\d*)', text, re.I)
        h.total = float(m.group(1).replace(',', '')) if m else 0.0

        # Líneas: extraer de la tabla con pdfplumber
        lines = self._parse_from_table(pdata, h)

        # Fallback al texto plano si pdfplumber no sacó nada
        if not lines:
            lines = self._parse_from_text(text, pdata)

        return h, lines

    def _parse_from_table(self, pdata: dict, header: InvoiceHeader) -> list[InvoiceLine]:
        """Extrae líneas usando pdfplumber.extract_tables() para respetar columnas."""
        pdf_path = pdata.get('pdf_path', '')
        if not pdf_path:
            return []

        lines = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    page_tables = page.extract_tables() or []
                    # El header con la secuencia de tallas suele estar en una
                    # tabla distinta a la de datos (OLIMPO: TABLE 5 header,
                    # TABLE 6 datos). Buscamos en toda la página.
                    sizes_ordered = self._detect_sizes_from_tables(page_tables)
                    for table in page_tables:
                        lines.extend(self._process_table(table, pdata, sizes_ordered))
        except Exception:
            return []

        return lines

    def _detect_sizes_from_tables(self, tables: list) -> list[int]:
        """Busca la fila de cabecera con tallas (30, 40, 50...) en cualquiera
        de las tablas de la página y devuelve la lista ordenada."""
        for table in tables or []:
            for row in table or []:
                if not row:
                    continue
                if any('VARIEDAD' in (c or '').upper() or 'VARIETY' in (c or '').upper() for c in row):
                    sz = [
                        int((c or '').strip())
                        for c in row
                        if (c or '').strip() and re.fullmatch(r'\d{2,3}', (c or '').strip())
                    ]
                    if sz:
                        return sz
        # Fallback al layout legacy (ALEGRIA/CERES/etc.)
        return [30, 40, 50, 60, 70, 80, 90, 100, 110, 120]

    def _process_table(self, table: list[list], pdata: dict,
                       sizes_ordered: list[int] | None = None) -> list[InvoiceLine]:
        """Procesa una tabla extraída buscando filas con QB/HB + variedad.

        Variantes conocidas:
          - ALEGRIA/CERES/TIERRA_VERDE: 10 tallas (30,40,50,60,70,80,90,100,110,120)
          - OLIMPO: 11 tallas (incluye 35) → desplaza stems/price/total un col
        """
        lines = []
        if sizes_ordered is None:
            sizes_ordered = self._detect_sizes_from_tables([table])

        # En datos: [#box, boxtype, variedad, spb, X, OTR., <sizes...>, stems, price, total]
        size_base = 6
        n_sz = len(sizes_ordered)
        stems_idx = size_base + n_sz
        price_idx = stems_idx + 1
        total_idx = stems_idx + 2

        for row in table:
            if not row or len(row) < total_idx + 1:
                continue

            box_type = (row[1] or '').strip().upper()
            if box_type not in ('QB', 'HB', 'QUA', 'HAL', 'FB'):
                continue

            variety = (row[2] or '').strip().upper()
            if not variety or re.match(r'^(TOT|SUB|TOTAL)', variety):
                continue

            # SPB
            try:
                spb = int((row[3] or '').strip() or 0)
            except (ValueError, TypeError):
                spb = 25

            # Tamaño: primera columna de size con número > 0
            size = 0
            bunches = 0
            for i, sz in enumerate(sizes_ordered):
                col = size_base + i
                val = (row[col] or '').strip() if col < len(row) else ''
                if val and re.fullmatch(r'\d+', val) and int(val) > 0:
                    size = sz
                    bunches = int(val)
                    break

            # Stems/price/total van a continuación de las size cols
            stems = _safe_int(row[stems_idx])
            price = _safe_float(row[price_idx])
            total = _safe_float(row[total_idx])

            if stems == 0 and bunches > 0:
                stems = bunches * spb
            if bunches == 0 and stems > 0 and spb > 0:
                bunches = stems // spb

            # Label: texto al final de la línea después del total
            label = ''
            raw = ' '.join((c or '') for c in row).strip()
            lm = re.search(r'[\d.]+\s*([A-Z]\S.*?)$', raw)
            if lm:
                label = lm.group(1).strip()

            il = InvoiceLine(
                raw_description=raw[:120],
                species='ROSES',
                variety=variety,
                size=size,
                stems_per_bunch=spb,
                bunches=bunches,
                stems=stems,
                price_per_stem=price,
                line_total=total,
                box_type=box_type,
                provider_key=pdata.get('key', ''),
                origin=pdata.get('country', 'EC'),
            )
            lines.append(il)

        return lines

    def _parse_from_text(self, text: str, pdata: dict) -> list[InvoiceLine]:
        """Fallback: parseo de texto plano (sin info de tamaño)."""
        lines = []
        for ln in text.split('\n'):
            ln = ln.strip()
            pm = re.search(r'(\d+)\s+(QB|HB|QUA|HAL)\s+([A-Z][A-Z\s.\-/]+?)\s+(\d+)\s*X\s*\.00', ln)
            if not pm:
                pm = re.search(r'(QB|HB|QUA|HAL)\s+([A-Z][A-Z\s.\-/]+?)\s+(\d+)\s*X\s*\.00', ln)
                if pm:
                    btype, var, spb = pm.group(1), pm.group(2).strip(), int(pm.group(3))
                else:
                    # Latinafarms format: "N VARIETY SPB SIZE PPB PRICE STEMS TOTAL"
                    pm2 = re.search(
                        r'^\d+\s+([A-Z][A-Z\s.\-/]+?)\s+'   # variety
                        r'(\d+)\s+(\d{2,3})\s+'               # SPB + size
                        r'[\d.]+\s+([\d.]+)\s+'                # ppb + price
                        r'([\d,.]+)\s+([\d,.]+)\s*$',          # stems + total
                        ln)
                    if pm2:
                        var = pm2.group(1).strip()
                        spb = int(pm2.group(2))
                        sz = int(pm2.group(3))
                        price = float(pm2.group(4))
                        stems_f = float(pm2.group(5).replace(',', ''))
                        total = float(pm2.group(6).replace(',', ''))
                        il = InvoiceLine(
                            raw_description=ln, species='ROSES', variety=var,
                            size=sz, stems_per_bunch=spb, stems=int(stems_f),
                            price_per_stem=price, line_total=total, box_type='',
                            provider_key=pdata.get('key', ''),
                            origin=pdata.get('country', 'EC'),
                        )
                        lines.append(il)
                    continue
            else:
                btype, var, spb = pm.group(2), pm.group(3).strip(), int(pm.group(4))

            if not var or re.match(r'^(TOT|SUB|TOTAL|DESCUENTO)', var.upper()):
                continue

            after = re.split(r'\d+\s*X\s*\.00\s+', ln, maxsplit=1)
            stems = 0; price = 0.0; total = 0.0
            if len(after) > 1:
                nm = re.search(r'(\d+)\s+(\d+)\s+([\d.]+)\s+([\d.]+)', after[1])
                if nm:
                    try:
                        stems = int(nm.group(2)); price = float(nm.group(3)); total = float(nm.group(4))
                    except (ValueError, TypeError):
                        pass

            il = InvoiceLine(
                raw_description=ln, species='ROSES', variety=var,
                size=0, stems_per_bunch=spb, stems=stems,
                price_per_stem=price, line_total=total, box_type=btype,
                provider_key=pdata.get('key', ''),
                origin=pdata.get('country', 'EC'),
            )
            lines.append(il)

        return lines


def _safe_int(val) -> int:
    try:
        return int(str(val or '').replace(',', '').strip())
    except (ValueError, TypeError):
        return 0


def _safe_float(val) -> float:
    try:
        return float(str(val or '').replace(',', '').strip())
    except (ValueError, TypeError):
        return 0.0
