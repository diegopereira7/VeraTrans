"""Fase 1: Extracción de huella digital estructural de PDFs."""
from __future__ import annotations

import re
import statistics
from pathlib import Path

from .modelos import PDFFingerprint

# Keywords de proveedores/industria para identificar candidatos
_BUSINESS_KEYWORDS = re.compile(
    r'\b(FLOWERS?|ROSES?|FLOR(?:ES|AL|ICOLA)?|FARM|GROWER|INVOICE|FACTURA|'
    r'BOUQUET|CARNATION|HYDRANGEA|GYPSOPHILA|ALSTROEMERIA|CHRYSANTHEMUM|'
    r'S\.?A\.?S?|LTDA|S\.?L\.?U?|CORP|INC|LLC)\b', re.IGNORECASE
)

# Patrones de header de factura
_INVOICE_PATTERNS = {
    'invoice_number': re.compile(r'INVOICE\s*(?:No\.?|#|NUMBER)\s*[:\s]*(\S+)', re.IGNORECASE),
    'date': re.compile(r'(?:DATE|FECHA)\s*[:\s]*([\d/\-]+)', re.IGNORECASE),
    'awb': re.compile(r'(?:M\.?A\.?W\.?B\.?|AWB)\s*(?:No\.?)?\s*[:\s]*([\d\-\s]+)', re.IGNORECASE),
}

# Patrones de línea de datos (producto). Lista deliberadamente amplia para
# capturar la mayor variedad de formatos posibles — el clustering posterior
# filtra falsos positivos por similitud estructural.
_DATA_LINE_INDICATORS = re.compile(
    r'(?:^\s*\d+\s+(?:QB|HB|TB|HALF|QUARTER|FULL)\b|'
    r'\b(?:QB|HB|TB)\s+\d|'
    r'\b(?:ROSE|HYDRANGEA|CARNATION|GYPSOPHILA|ALSTRO)\b|'
    r'^\s*\d+\s+[A-Z].*\d+\.\d{2}|'
    # Líneas tipo "<int> <int> <int> <VARIETY> <size> CMS $price $total"
    # (formato compacto FARIN-style sin marcador HB/QB pero con CM/CMS+precio)
    r'^\s*\d+\s+\d+\s+\d+\s+[A-Z][A-Z\s.\-/]*\s+\d{2,3}\s*CM|'
    # Líneas con descripción + tamaño CM + precio
    r'[A-Z]{3,}\s+\d{2,3}\s*CMS?\b.*\$?\d+\.\d{2})',
    re.IGNORECASE | re.MULTILINE
)

# Líneas de ruido a ignorar
_NOISE_LINE = re.compile(
    r'^\s*(?:TOTAL|SUBTOTAL|DISCOUNT|FREIGHT|PAGE|www\.|Powered by|Disclaimer|'
    r'phone|fax|email|address|ship to|bill to|consign|net weight|gross weight|'
    r'THE EXPORTER|THESE FLOWERS|All quality|Credit|Failure)\b',
    re.IGNORECASE
)

# Header de tabla (columnas conocidas)
_KNOWN_HEADERS = {
    'description', 'desc', 'producto', 'product', 'item', 'variety', 'variedad',
    'color', 'colour', 'stems', 'tallos', 'stm', 'qty', 'quantity', 'cantidad',
    'boxes', 'cajas', 'bxs', 'bunch', 'bunches', 'ramos',
    'unit price', 'precio', 'price', 'total', 'amount', 'importe',
    'farm', 'finca', 'grower', 'grade', 'grado', 'length', 'cm', 'size',
    'mark', 'po', 'order', 'box type', 'box', 'reference',
}


def extraer_fingerprint(pdf_path: str, text: str) -> PDFFingerprint | None:
    """Extrae la huella estructural de un PDF.

    Args:
        pdf_path: Ruta al archivo PDF.
        text: Texto ya extraído del PDF.

    Returns:
        PDFFingerprint o None si el PDF no parece una factura.
    """
    if not text or len(text.strip()) < 50:
        return None

    fp = PDFFingerprint(pdf_path=pdf_path, texto_completo=text)

    # Contar páginas (estimación por saltos de página o longitud)
    fp.num_paginas = max(1, text.count('\f') + 1)

    # Intentar extraer tablas con pdfplumber
    _extract_table_info(pdf_path, fp)

    # Extraer estructura de texto
    _extract_text_structure(text, fp)

    # Identificar proveedor candidato
    _identify_provider_candidate(text, fp)

    # Calcular confianza
    _calculate_confidence(fp)

    # Calcular hash
    fp.calcular_hash()

    return fp


def _extract_table_info(pdf_path: str, fp: PDFFingerprint):
    """Intenta extraer información de tablas con pdfplumber."""
    try:
        import pdfplumber
    except ImportError:
        return

    try:
        with pdfplumber.open(pdf_path) as pdf:
            fp.num_paginas = len(pdf.pages)
            biggest_table = None
            biggest_rows = 0

            for page in pdf.pages:
                tables = page.extract_tables() or []
                fp.num_tablas_por_pagina.append(len(tables))

                for table in tables:
                    if table and len(table) > biggest_rows:
                        biggest_table = table
                        biggest_rows = len(table)

            if biggest_table and biggest_rows >= 3:
                fp.tiene_tablas = True
                fp.num_columnas_tabla_principal = len(biggest_table[0]) if biggest_table[0] else 0

                # Extraer headers
                first_row = biggest_table[0]
                if first_row:
                    fp.headers_originales = [str(c).strip() if c else '' for c in first_row]
                    fp.headers_tabla = [_normalize_header(h) for h in fp.headers_originales]
    except Exception:
        pass


def _normalize_header(h: str) -> str:
    """Normaliza un header de columna para comparación."""
    h = h.lower().strip()
    h = re.sub(r'[^a-z0-9\s]', '', h)
    h = re.sub(r'\s+', ' ', h).strip()
    return h


def _extract_text_structure(text: str, fp: PDFFingerprint):
    """Analiza la estructura del texto plano."""
    lines = text.split('\n')

    # Detectar zona de header (antes de la primera línea de datos)
    header_end = 0
    for i, line in enumerate(lines):
        if _DATA_LINE_INDICATORS.search(line):
            header_end = i
            break
    fp.zona_header_lines = header_end

    # Detectar zona de footer (después de la última línea de datos)
    footer_start = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if _DATA_LINE_INDICATORS.search(lines[i]):
            footer_start = i + 1
            break
    fp.zona_footer_lines = len(lines) - footer_start

    # Extraer líneas de datos (entre header y footer, filtrar ruido)
    data_lines = []
    for line in lines[header_end:footer_start]:
        line = line.strip()
        if not line or len(line) < 10:
            continue
        if _NOISE_LINE.match(line):
            continue
        if re.search(r'\d+\.\d{2}', line):  # Tiene al menos un precio
            data_lines.append(line)

    fp.lineas_datos = data_lines[:50]  # Guardar máximo 50 para análisis

    # Detectar separador de campos
    if data_lines:
        tab_count = sum(l.count('\t') for l in data_lines)
        multi_space = sum(len(re.findall(r'\s{2,}', l)) for l in data_lines)

        if tab_count > len(data_lines):
            fp.separador_campos = 'tab'
        elif multi_space > len(data_lines) * 2:
            fp.separador_campos = 'spaces'
        else:
            fp.separador_campos = 'mixed'

        # Contar campos por línea. Si el split por 2+ espacios devuelve
        # 1 sólo campo, reintentamos con espacio simple para detectar
        # formatos compactos tipo FARIN ROSES.
        field_counts = []
        for line in data_lines:
            if fp.separador_campos == 'tab':
                fields = [f.strip() for f in line.split('\t') if f.strip()]
            else:
                fields = [f.strip() for f in re.split(r'\s{2,}', line) if f.strip()]
                if len(fields) <= 1:
                    fields = [f.strip() for f in re.split(r'\s+', line) if f.strip()]
            field_counts.append(len(fields))

        if field_counts:
            fp.num_campos_por_linea = int(statistics.median(field_counts))


def _identify_provider_candidate(text: str, fp: PDFFingerprint):
    """Intenta identificar el nombre del proveedor desde el texto."""
    # Buscar en las primeras 10 líneas (header de la factura)
    lines = text.split('\n')[:10]
    header_text = '\n'.join(lines)

    # Buscar keywords de negocio
    keywords = list(set(m.group(0).upper() for m in _BUSINESS_KEYWORDS.finditer(header_text)))
    fp.keywords_encontrados = sorted(keywords)[:15]

    # Primera línea no vacía suele ser el nombre del proveedor
    for line in lines:
        line = line.strip()
        if line and len(line) > 3 and not line.startswith(('http', 'www', '(')):
            # Filtrar líneas que son claramente datos
            if not re.match(r'^\d+\s', line) and not _NOISE_LINE.match(line):
                # Limpiar artefactos del extractor de PDF (CID, control chars).
                cleaned = re.sub(r'\(cid:\d+\)', '', line)
                cleaned = re.sub(r'\s+', ' ', cleaned).strip()
                fp.proveedor_candidato = cleaned[:60].strip()
                break


def _calculate_confidence(fp: PDFFingerprint):
    """Calcula el score de confianza de la detección."""
    score = 0.0

    # +0.30 si detectó tablas con headers claros
    if fp.tiene_tablas and fp.headers_tabla:
        known_count = sum(1 for h in fp.headers_tabla
                         if any(kh in h for kh in _KNOWN_HEADERS))
        if known_count >= 2:
            score += 0.30
        elif known_count >= 1:
            score += 0.15

    # +0.20 si detectó separador de campos consistente
    if fp.separador_campos and fp.num_campos_por_linea >= 4:
        score += 0.20

    # +0.20 si hay líneas de datos
    if len(fp.lineas_datos) >= 3:
        score += 0.20
    elif len(fp.lineas_datos) >= 1:
        score += 0.10

    # +0.20 si detectó keywords de proveedor
    if len(fp.keywords_encontrados) >= 3:
        score += 0.20
    elif len(fp.keywords_encontrados) >= 1:
        score += 0.10

    # +0.10 si detectó zonas de header/footer claramente
    if fp.zona_header_lines >= 3 and fp.zona_footer_lines >= 1:
        score += 0.10

    fp.confianza_deteccion = min(score, 1.0)
