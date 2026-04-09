"""Fase 3: Inferencia de reglas de extracción desde un cluster de PDFs."""
from __future__ import annotations

import re
import statistics
from collections import Counter

from .modelos import PDFFingerprint, ExtractionRule

# Mapeo de headers conocidos a campos del sistema
_HEADER_MAP: dict[str, str] = {
    # Descripción / Producto
    'description': 'variety', 'desc': 'variety', 'producto': 'variety',
    'product': 'variety', 'item': 'variety', 'variety': 'variety',
    'variedad': 'variety',
    # Color
    'color': 'color', 'colour': 'color', 'col': 'color',
    # Tallos / Cantidad
    'stems': 'stems', 'tallos': 'stems', 'stm': 'stems',
    'qty': 'stems', 'quantity': 'stems', 'cantidad': 'stems',
    'total stems': 'stems', 'total un': 'stems',
    # Cajas / Bunches
    'boxes': 'bunches', 'cajas': 'bunches', 'bxs': 'bunches',
    'bunch': 'bunches', 'bunches': 'bunches', 'ramos': 'bunches',
    'pieces': 'bunches', 'pcs': 'bunches',
    # Tallos por caja
    'stems per box': 'stems_per_bunch', 'unxbox': 'stems_per_bunch',
    'st bch': 'stems_per_bunch', 'stems box': 'stems_per_bunch',
    # Precio unitario
    'unit price': 'price_per_stem', 'un price': 'price_per_stem',
    'precio': 'price_per_stem', 'price': 'price_per_stem',
    'pu': 'price_per_stem', 'precio unitario': 'price_per_stem',
    # Precio total
    'total': 'line_total', 'amount': 'line_total', 'importe': 'line_total',
    'total price': 'line_total', 'total usd': 'line_total',
    # Talla / Largo
    'grade': 'grade', 'grado': 'grade', 'gr': 'grade',
    'length': 'size', 'largo': 'size', 'cm': 'size', 'size': 'size',
    # Farm / Box
    'farm': 'farm', 'finca': 'farm', 'grower': 'farm',
    'mark': 'label', 'box id': 'label', 'reference': 'label',
    'box type': 'box_type', 'box': 'box_type', 'type': 'box_type',
}

# Patrones de species en texto
_SPECIES_PATTERNS = [
    (re.compile(r'\bROSE?S?\b', re.IGNORECASE), 'ROSES'),
    (re.compile(r'\bCARNATION', re.IGNORECASE), 'CARNATIONS'),
    (re.compile(r'\bHYDRANGEA', re.IGNORECASE), 'HYDRANGEAS'),
    (re.compile(r'\bGYPSOPHILA|PANICULATA', re.IGNORECASE), 'GYPSOPHILA'),
    (re.compile(r'\bALSTR(?:O(?:E)?MERIA)?', re.IGNORECASE), 'ALSTROEMERIA'),
    (re.compile(r'\bCHRYSANTHEMUM|POMPON|DISBUD|SANTINI', re.IGNORECASE), 'CHRYSANTHEMUM'),
]

# Regex comunes para header de factura
_HEADER_REGEXES = {
    'invoice_number': [
        r'INVOICE\s*(?:No\.?|#|NUMBER|N[o\xba]\.?)\s*[:\s]*(\S+)',
        r'FACTURA\s*(?:No\.?|#)\s*[:\s]*(\S+)',
    ],
    'date': [
        r'(?:DATE|FECHA|Invoice\s+Date)\s*[:\s]*([\d/\-]+)',
        r'(\d{1,2}/\d{1,2}/\d{2,4})',
    ],
    'awb': [
        r'(?:M\.?A\.?W\.?B\.?|AWB|Master\s+AWB)\s*(?:No\.?)?\s*[:\s]*([\d\-\s]+)',
    ],
    'total': [
        r'(?:TOTAL|Amount\s+Due|INVOICE\s+TOTAL)\s*(?:USD|US\$|\$)?\s*[:\s]*([\d,]+\.\d+)',
    ],
}


def inferir_reglas(cluster_fps: list[PDFFingerprint]) -> list[ExtractionRule] | None:
    """Infiere reglas de extracción a partir de un cluster de fingerprints.

    Returns:
        Lista de reglas o None si no se pudieron inferir.
    """
    if not cluster_fps:
        return None

    rules: list[ExtractionRule] = []

    # Reglas de header (invoice_number, date, awb, total)
    header_rules = _inferir_header_rules(cluster_fps)
    rules.extend(header_rules)

    # Detectar especie dominante
    species_rule = _inferir_species(cluster_fps)
    if species_rule:
        rules.append(species_rule)

    # Reglas de líneas de datos
    fp_ref = cluster_fps[0]
    if fp_ref.tiene_tablas and fp_ref.headers_tabla:
        line_rules = _inferir_desde_tablas(cluster_fps)
    else:
        line_rules = _inferir_desde_texto(cluster_fps)

    if not line_rules:
        return None

    rules.extend(line_rules)

    # Inferir regex de línea de datos
    line_regex_rule = _inferir_line_regex(cluster_fps)
    if line_regex_rule:
        rules.append(line_regex_rule)

    return rules


def _inferir_header_rules(fps: list[PDFFingerprint]) -> list[ExtractionRule]:
    """Infiere reglas para extraer campos del header de la factura."""
    rules = []

    for campo, patterns in _HEADER_REGEXES.items():
        best_pattern = None
        best_matches = 0

        for pat_str in patterns:
            pat = re.compile(pat_str, re.IGNORECASE)
            matches = 0
            evidencia = []

            for fp in fps:
                m = pat.search(fp.texto_completo[:2000])
                if m:
                    matches += 1
                    evidencia.append(m.group(1).strip()[:50])

            if matches > best_matches:
                best_matches = matches
                best_pattern = pat_str
                best_evidencia = evidencia

        if best_pattern and best_matches >= 1:
            conf = best_matches / len(fps)
            rules.append(ExtractionRule(
                campo_destino=campo,
                tipo='header_regex',
                patron_regex=best_pattern,
                grupo_captura=1,
                confianza=conf,
                evidencia=best_evidencia[:5],
            ))

    return rules


def _inferir_species(fps: list[PDFFingerprint]) -> ExtractionRule | None:
    """Detecta la especie dominante en el cluster."""
    species_counts: Counter[str] = Counter()

    for fp in fps:
        text = fp.texto_completo.upper()
        for pat, species in _SPECIES_PATTERNS:
            count = len(pat.findall(text))
            if count > 0:
                species_counts[species] += count

    if not species_counts:
        return None

    dominant = species_counts.most_common(1)[0]
    total = sum(species_counts.values())

    return ExtractionRule(
        campo_destino='species',
        tipo='regex_texto',
        patron_regex=None,
        confianza=dominant[1] / total if total else 0,
        evidencia=[dominant[0]],
        transformacion=dominant[0],
    )


def _inferir_desde_tablas(fps: list[PDFFingerprint]) -> list[ExtractionRule]:
    """Infiere reglas de línea cuando hay tablas estructuradas."""
    rules = []
    fp_ref = fps[0]

    for i, header in enumerate(fp_ref.headers_tabla):
        if not header:
            continue

        # Buscar en el mapa de headers conocidos
        campo = None
        for known_h, campo_dest in _HEADER_MAP.items():
            if known_h in header or header in known_h:
                campo = campo_dest
                break

        if campo:
            rules.append(ExtractionRule(
                campo_destino=campo,
                tipo='columna_tabla',
                indice_columna=i,
                header_columna=fp_ref.headers_originales[i] if i < len(fp_ref.headers_originales) else header,
                confianza=0.8,
                evidencia=[header],
            ))

    return rules


def _inferir_desde_texto(fps: list[PDFFingerprint]) -> list[ExtractionRule]:
    """Infiere reglas de línea desde texto plano usando análisis posicional."""
    rules = []

    # Recolectar todas las líneas de datos de todos los fps
    all_lines = []
    for fp in fps:
        all_lines.extend(fp.lineas_datos)

    if not all_lines:
        return rules

    # Analizar cada "columna" posicional
    fp_ref = fps[0]
    sep = fp_ref.separador_campos

    # Splitear líneas en campos
    field_sets: list[list[str]] = []
    for line in all_lines:
        if sep == 'tab':
            fields = [f.strip() for f in line.split('\t') if f.strip()]
        else:
            fields = [f.strip() for f in re.split(r'\s{2,}', line) if f.strip()]
        if len(fields) >= 3:
            field_sets.append(fields)

    if not field_sets:
        return rules

    # Analizar cada posición
    max_cols = max(len(fs) for fs in field_sets)

    for col_idx in range(min(max_cols, 15)):
        values = [fs[col_idx] for fs in field_sets if col_idx < len(fs)]
        if not values:
            continue

        campo = _classify_column(values, col_idx, max_cols)
        if campo:
            rules.append(ExtractionRule(
                campo_destino=campo,
                tipo='posicion_fija',
                indice_columna=col_idx,
                confianza=0.6,
                evidencia=values[:5],
            ))

    return rules


def _classify_column(values: list[str], col_idx: int, max_cols: int) -> str | None:
    """Clasifica una columna por su contenido."""
    # Contar tipos de valores
    numeric_count = 0
    float_count = 0
    text_count = 0
    int_count = 0

    for v in values:
        v_clean = v.replace(',', '').replace('$', '').strip()
        if re.match(r'^\d+\.\d+$', v_clean):
            float_count += 1
            numeric_count += 1
        elif re.match(r'^\d+$', v_clean):
            int_count += 1
            numeric_count += 1
        else:
            text_count += 1

    total = len(values)
    if total == 0:
        return None

    numeric_ratio = numeric_count / total
    float_ratio = float_count / total
    int_ratio = int_count / total
    text_ratio = text_count / total

    # Texto descriptivo (probablemente variety/product)
    if text_ratio > 0.7:
        if col_idx <= 2:
            return 'variety'
        return None

    # Enteros (tallos, bunches, stems_per_bunch)
    if int_ratio > 0.7:
        avg = statistics.mean(int(v.replace(',', '')) for v in values
                              if re.match(r'^\d+$', v.replace(',', '')))
        if avg > 100:
            return 'stems'
        elif avg > 10:
            return 'bunches'
        else:
            return 'stems_per_bunch'

    # Decimales (precios)
    if float_ratio > 0.7:
        avg = statistics.mean(float(v.replace(',', '').replace('$', ''))
                              for v in values
                              if re.match(r'^[\d,.]+$', v.replace('$', '').strip()))
        if avg > 10:
            return 'line_total'
        else:
            return 'price_per_stem'

    return None


def _inferir_line_regex(fps: list[PDFFingerprint]) -> ExtractionRule | None:
    """Intenta inferir un regex general para líneas de datos."""
    # Recolectar líneas de datos
    all_lines = []
    for fp in fps:
        all_lines.extend(fp.lineas_datos)

    if len(all_lines) < 3:
        return None

    # Intentar patrones comunes de facturas de flores
    common_patterns = [
        # boxes H/Q + description + numbers
        (r'(\d+)\s+(QB|HB|TB|HALF|QUARTER|FULL)\s+([A-Z][A-Z\s.\-/]+?)\s+(\d+)\s+(\d+)\s+([\d.]+)\s+([\d.]+)',
         'box_desc_nums'),
        # H/Q + description + size CM + numbers
        (r'(HB|QB|TB)\s+([A-Z][A-Z\s.\-/]+?)\s+(\d{2})\s+(\d+)\s+(\d+)\s+([\d.]+)',
         'type_desc_cm_nums'),
        # description + size CM + stems + price
        (r'([A-Z][A-Z\s.\-/]+?)\s+(\d{2})\s*CM\s+\d*\s*(\d+)\s+([\d.]+)',
         'desc_cm_stems_price'),
    ]

    best_pattern = None
    best_matches = 0

    for pat_str, name in common_patterns:
        pat = re.compile(pat_str, re.IGNORECASE)
        matches = sum(1 for l in all_lines if pat.search(l))

        if matches > best_matches:
            best_matches = matches
            best_pattern = pat_str

    if best_pattern and best_matches >= len(all_lines) * 0.3:
        return ExtractionRule(
            campo_destino='line_pattern',
            tipo='regex_texto',
            patron_regex=best_pattern,
            confianza=best_matches / len(all_lines),
            evidencia=[f'{best_matches}/{len(all_lines)} lines matched'],
        )

    return None
