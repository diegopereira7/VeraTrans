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
                    for table in (page.extract_tables() or []):
                        lines.extend(self._process_table(table, pdata))
        except Exception:
            return []

        return lines

    def _process_table(self, table: list[list], pdata: dict) -> list[InvoiceLine]:
        """Procesa una tabla extraída buscando filas con QB/HB + variedad."""
        lines = []
        # Buscar fila header para confirmar posiciones de columnas de tamaño
        size_cols = dict(_SIZE_COLS)

        for row in table:
            if not row or len(row) < 17:
                continue

            box_type = (row[1] or '').strip().upper()
            if box_type not in ('QB', 'HB', 'QUA', 'HAL', 'FB'):
                continue

            variety = (row[2] or '').strip().upper()
            if not variety or re.match(r'^(TOT|SUB|TOTAL)', variety):
                continue

            # SPB
            try:
                spb = int(row[3] or 0)
            except (ValueError, TypeError):
                spb = 25

            # Encontrar tamaño: buscar en qué columna de tamaño hay un número > 0
            size = 0
            bunches = 0
            for col_idx, col_size in size_cols.items():
                if col_idx >= len(row):
                    continue
                val = (row[col_idx] or '').strip()
                if val and re.match(r'^\d+$', val) and int(val) > 0:
                    size = col_size
                    bunches = int(val)
                    break

            # Stems, price, total (columnas 16, 17, 18)
            stems = _safe_int(row[16]) if len(row) > 16 else bunches * spb
            price = _safe_float(row[17]) if len(row) > 17 else 0.0
            total = _safe_float(row[18]) if len(row) > 18 else 0.0

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
