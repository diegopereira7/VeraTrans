"""Parser auto-generado para MOUNTAIN FRESH FLOWERS.

Layout peculiar — tabla con 4 columnas CM (40/50/60/70) donde solo UNA está
populada por línea. El texto plano (`extract_text`) colapsa las columnas
vacías, perdiendo la info de talla. Necesitamos las x-coordinates de las
palabras para mapear cada dato a su columna CM.

Usa pdfplumber.extract_words() directamente. El provider_data trae pdf_path.
"""
from __future__ import annotations

import re
from src.models import InvoiceHeader, InvoiceLine


# Tolerancia en pixels para asignar un valor a una columna CM.
_CM_COL_TOLERANCE = 20.0

# Centros x aproximados de las columnas 40/50/60/70 CM en este template.
# Si el PDF cambia de layout estos valores pueden necesitar ajuste.
_CM_COLUMNS = {
    40: 366.0,
    50: 396.0,
    60: 417.0,
    70: 437.0,
}


def _closest_size(x: float) -> int:
    best = 0
    best_diff = _CM_COL_TOLERANCE + 1
    for cm, cx in _CM_COLUMNS.items():
        diff = abs(x - cx)
        if diff < best_diff:
            best_diff = diff
            best = cm
    return best


def _num(s: str) -> float:
    return float(s.replace(',', '.')) if s else 0.0


class AutoParser:
    fmt_key = 'auto_mountain'

    def parse(self, text: str, provider_data: dict) -> tuple[InvoiceHeader, list[InvoiceLine]]:
        header = InvoiceHeader(
            provider_id=provider_data.get('id', 0),
            provider_name=provider_data.get('name', ''),
            provider_key=provider_data.get('key', ''),
        )
        m = re.search(r'INVOICE\s+(\d+)', text, re.I)
        if m:
            header.invoice_number = m.group(1)
        m = re.search(r'Date\s*:\s*(\d{1,2}/\d{1,2}/\d{4})', text, re.I)
        if m:
            header.date = m.group(1)
        m = re.search(r'AWB\s*N[ºo°]?\s*\n?\s*([\d\-\s]+)', text, re.I)
        if m:
            header.awb = re.sub(r'\s+', '', m.group(1))
        m = re.search(r'TOTAL\s*-+>*\s*[\d\.,\s]+\$\s*([\d,.]+)', text, re.I)
        if m:
            header.total = _num(m.group(1).replace('.', '').replace(',', '.')) if ',' in m.group(1) else _num(m.group(1))

        lines: list[InvoiceLine] = []
        pdf_path = provider_data.get('pdf_path')
        if not pdf_path:
            return header, lines

        try:
            import pdfplumber
        except ImportError:
            return header, lines

        try:
            with pdfplumber.open(pdf_path) as p:
                for page in p.pages:
                    lines.extend(self._parse_page(page, provider_data))
        except Exception:
            return header, lines

        if not header.total and lines:
            header.total = round(sum(l.line_total for l in lines), 2)
        return header, lines

    def _parse_page(self, page, provider_data) -> list[InvoiceLine]:
        from collections import defaultdict
        words = page.extract_words(x_tolerance=2, y_tolerance=2)
        rows = defaultdict(list)
        for w in words:
            rows[round(w['top'], 0)].append(w)

        out: list[InvoiceLine] = []
        for y in sorted(rows.keys()):
            row = sorted(rows[y], key=lambda w: w['x0'])
            texts = [w['text'] for w in row]
            if not any('0603.' in t for t in texts):
                continue
            # Línea de producto. Extraer: type, variety, grade, hts, spb, size_col_value,
            # total_bunches, total_stems, unit_price, total.
            try:
                out.append(self._line_from_row(row, provider_data))
            except Exception:
                continue
        return [l for l in out if l]

    def _line_from_row(self, row, provider_data) -> InvoiceLine | None:
        """Extrae una línea a partir de las palabras ordenadas por x."""
        texts = [w['text'] for w in row]
        xs    = [w['x0'] for w in row]

        # Identificar índices clave por contenido
        hts_idx = next(i for i, t in enumerate(texts) if t.startswith('0603.'))
        # Antes de hts: [code?] TYPE [pieces fulls] variety [grade]
        # Después de hts: [spb] [size_col_val] [total_bunch] [total_stems] [price] [total]

        # Grade = la palabra inmediatamente antes del HTS (A, AA, etc.)
        grade = ''
        if hts_idx > 0 and re.match(r'^[A-Z]{1,2}$', texts[hts_idx - 1]):
            grade = texts[hts_idx - 1]

        # TYPE
        box_type = 'HB'
        for t in texts[:hts_idx]:
            if t in ('HB', 'QB', 'TB', 'FB'):
                box_type = t
                break

        # Variety: palabras entre fulls y grade (o HTS si no hay grade)
        # Encontrar el índice donde empieza la variety: tras '0,5' o '1,0' o similar (fulls con coma)
        variety_start = 0
        for i, t in enumerate(texts[:hts_idx]):
            if re.match(r'^\d+[,.]\d+$', t):   # fulls
                variety_start = i + 1
                break
            if t in ('HB', 'QB', 'TB', 'FB'):
                variety_start = i + 1 + 2    # HB seguido de pieces + fulls
        variety_end = hts_idx - (1 if grade else 0)
        variety = ' '.join(texts[variety_start:variety_end]).strip().upper()
        if not variety or len(variety) < 2:
            return None

        # Post-HTS: spb a price a total
        post = row[hts_idx + 1:]
        if len(post) < 5:
            return None

        spb_w, *rest = post
        try:
            spb = int(spb_w['text'])
        except ValueError:
            return None

        # Los siguientes tokens son: <size_col_val> <total_bunches> <total_stems> <price> <total>
        # El primero (size_col_val) tiene x-position que indica la columna CM
        if len(rest) < 4:
            return None
        size_col_word = rest[0]
        total_bunches_w = rest[1]
        total_stems_w = rest[2]
        price_w = rest[-2]
        total_w = rest[-1]

        size = _closest_size(size_col_word['x0'])
        try:
            bunches = int(total_bunches_w['text'])
            stems = int(total_stems_w['text'])
            price = _num(price_w['text'])
            total = _num(total_w['text'].replace('.', '').replace(',', '.')) if ',' in total_w['text'] else _num(total_w['text'])
        except (ValueError, IndexError):
            return None

        return InvoiceLine(
            raw_description=' '.join(texts)[:120],
            species='ROSES',
            variety=variety,
            grade=grade,
            origin='EC',
            size=size,
            stems_per_bunch=spb,
            bunches=bunches,
            stems=stems,
            price_per_stem=price,
            line_total=total,
            box_type=box_type,
            provider_key=provider_data.get('key', ''),
        )
