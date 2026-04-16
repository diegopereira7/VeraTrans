"""Extracción de texto de PDFs y detección de proveedor.

Esta capa es ahora un **wrapper delgado** sobre :mod:`src.extraction`, que
implementa el routing con diagnóstico previo (nativo vs escaneado vs mixto),
OCRmyPDF+Tesseract como rama principal y EasyOCR como fallback. Ver
``src/extraction.py`` para los detalles de la política.

Se mantienen intactas las APIs históricas para no romper llamantes:

    - ``extract_text(path) -> str``
    - ``get_last_ocr_confidence() -> float``
    - ``extract_tables(path) -> list[list[list[str]]]``
    - ``detect_provider(path) -> dict | None``

Se añade:

    - ``get_last_extraction() -> ExtractionResult | None`` para quienes
      quieran acceder a las señales finas (fuente por página, motor OCR,
      degradación). El pipeline individual/batch las propaga a las líneas
      para que la UI muestre fiabilidad de extracción como señal propia.
"""
from __future__ import annotations

import logging
import subprocess
from typing import Optional

from src.config import PROVIDERS
from src.extraction import (
    ExtractionResult,
    extract as _extract_result,
    extract_rows_by_coords,  # re-export para parsers
)

logger = logging.getLogger(__name__)

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False


# Último resultado completo de extracción (incluye texto, fuente por página,
# motor OCR, degradado). Lo mantenemos como variable-módulo por compatibilidad
# con el patrón ``get_last_ocr_confidence()`` que ya usaba procesar_pdf.py y
# batch_process.py. Un único threading model asumido (el pipeline no procesa
# dos PDFs a la vez dentro del mismo proceso).
_last_extraction: Optional[ExtractionResult] = None


def get_last_ocr_confidence() -> float:
    """Confianza media del último extract_text() (1.0 si fue texto nativo).

    Se conserva por compatibilidad — el valor se deriva de
    ``_last_extraction.confidence`` si la extracción fue OCR/mixta, o 1.0
    si fue texto nativo puro.
    """
    if _last_extraction is None:
        return 1.0
    if _last_extraction.source == 'native':
        return 1.0
    return _last_extraction.confidence


def get_last_extraction() -> Optional[ExtractionResult]:
    """Devuelve el último ExtractionResult, o None si aún no se extrajo nada."""
    return _last_extraction


def extract_text(path: str) -> str:
    """Extrae el texto completo de un PDF (API pública, retrocompatible).

    Internamente llama a :func:`src.extraction.extract` que elige estrategia
    por página. Si el router no está disponible (p.ej. pdfplumber sin instalar)
    cae al fallback de ``pdftotext``.

    Raises:
        RuntimeError: Si no hay ninguna herramienta de extracción disponible.
    """
    global _last_extraction
    try:
        result = _extract_result(path)
    except Exception as e:
        logger.warning("Router de extracción falló en %s: %s", path, e)
        result = None

    if result and result.text.strip():
        _last_extraction = result
        return result.text

    # Fallback: pdftotext como último recurso
    try:
        r = subprocess.run(
            ['pdftotext', '-layout', path, '-'],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0 and r.stdout.strip():
            from src.extraction import PageExtraction
            _last_extraction = ExtractionResult(
                text=r.stdout,
                pages=[PageExtraction(text=r.stdout, source='native',
                                      confidence=1.0, char_count=len(r.stdout))],
                confidence=1.0, source='native', ocr_engine='',
            )
            return r.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    if result is not None:
        _last_extraction = result
        return result.text  # puede ser '' — que el pipeline decida

    raise RuntimeError("Instala pdfplumber (pip install pdfplumber) o poppler-utils")


def extract_tables(path: str) -> list[list[list[str]]]:
    """Extrae tablas estructuradas de un PDF con pdfplumber.

    Devuelve una lista de tablas (una por tabla detectada en todas las páginas),
    donde cada tabla es una lista de filas, y cada fila una lista de celdas.
    Los parsers que operen sobre facturas tabulares pueden usarlo en lugar de
    regex sobre texto plano — evita el problema clásico de "tablas aplanadas".

    Devuelve [] si pdfplumber no está instalado o el PDF no tiene tablas.
    """
    if not HAS_PDFPLUMBER:
        return []
    tables: list[list[list[str]]] = []
    try:
        with pdfplumber.open(path) as p:
            for page in p.pages:
                for tbl in page.extract_tables() or []:
                    norm = [[('' if c is None else str(c).strip()) for c in row]
                            for row in tbl]
                    if any(any(c for c in row) for row in norm) and len(norm) > 1:
                        tables.append(norm)
    except Exception as e:
        logger.debug("extract_tables falló para %s: %s", path, e)
    return tables


def detect_provider(path: str) -> Optional[dict]:
    """Detecta el proveedor de un PDF por patrones en su contenido.

    Busca todos los patterns de PROVIDERS y devuelve el proveedor cuyo
    pattern aparece **más temprano** en el texto (la cabecera del PDF
    siempre contiene el nombre del emisor, los patterns de otros
    proveedores pueden aparecer más abajo como referencia al cliente o
    a una orden interna).

    Args:
        path: Ruta al fichero PDF.

    Returns:
        Dict con datos del proveedor + 'key' y 'text', o None si no se reconoce.
    """
    try:
        text = extract_text(path)
    except (RuntimeError, OSError) as e:
        logger.warning("No se pudo extraer texto de %s: %s", path, e)
        return None
    text_lower = text.lower()
    best_pos = len(text_lower) + 1
    best_key = None
    best_data = None
    for pkey, pdata in PROVIDERS.items():
        for pat in pdata['patterns']:
            idx = text_lower.find(pat.lower())
            if idx != -1 and idx < best_pos:
                best_pos = idx
                best_key = pkey
                best_data = pdata
                break  # un match por proveedor es suficiente
    if best_key is not None:
        return {**best_data, 'key': best_key, 'text': text}
    return None


__all__ = [
    'extract_text', 'extract_tables', 'extract_rows_by_coords',
    'detect_provider',
    'get_last_ocr_confidence', 'get_last_extraction',
]
