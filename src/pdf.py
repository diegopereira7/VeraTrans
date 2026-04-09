"""Extracción de texto de PDFs y detección de proveedor.

Flujo de extracción:
1. pdfplumber (texto nativo del PDF — rápido y preciso)
2. pdftotext / poppler (fallback si no hay pdfplumber)
3. OCR con EasyOCR (fallback para PDFs escaneados sin texto)
"""
from __future__ import annotations

import logging
import subprocess
from typing import Optional

from src.config import PROVIDERS

logger = logging.getLogger(__name__)

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

# OCR lazy-loaded: solo se carga si se necesita (primer PDF sin texto)
_ocr_reader = None


def _get_ocr_reader():
    """Lazy-load del reader EasyOCR. Solo se inicializa una vez."""
    global _ocr_reader
    if _ocr_reader is None:
        try:
            import easyocr
            logger.info("Inicializando EasyOCR (primera vez, puede tardar)...")
            _ocr_reader = easyocr.Reader(['en', 'es'], gpu=False, verbose=False)
            logger.info("EasyOCR listo.")
        except ImportError:
            logger.warning("EasyOCR no instalado. pip install easyocr")
            _ocr_reader = False  # sentinel: intentado pero no disponible
    return _ocr_reader if _ocr_reader is not False else None


def _ocr_extract(path: str) -> str:
    """Extrae texto de un PDF escaneado usando OCR (EasyOCR + PyMuPDF)."""
    reader = _get_ocr_reader()
    if not reader:
        return ''
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.warning("PyMuPDF no instalado. pip install PyMuPDF")
        return ''

    pages_text = []
    try:
        doc = fitz.open(path)
        for page_num in range(len(doc)):
            # Renderizar página a imagen (300 DPI para buena calidad OCR)
            pix = doc[page_num].get_pixmap(dpi=300)
            img_bytes = pix.tobytes("png")
            # EasyOCR acepta bytes directamente
            results = reader.readtext(img_bytes, detail=0, paragraph=True)
            pages_text.append('\n'.join(results))
        doc.close()
    except Exception as e:
        logger.warning("OCR falló para %s: %s", path, e)
        return ''

    text = '\n'.join(pages_text)
    if text.strip():
        logger.info("OCR extrajo %d caracteres de %s", len(text), path)
    return text


def extract_text(path: str) -> str:
    """Extrae el texto completo de un PDF.

    Flujo: pdfplumber → pdftotext → OCR (EasyOCR).

    Args:
        path: Ruta al fichero PDF.

    Returns:
        Texto completo del PDF.

    Raises:
        RuntimeError: Si no hay herramientas de extracción disponibles.
    """
    # 1. pdfplumber (texto nativo)
    if HAS_PDFPLUMBER:
        with pdfplumber.open(path) as p:
            text = '\n'.join(pg.extract_text() or '' for pg in p.pages)
        if text.strip():
            return text
        # Texto vacío → intentar OCR
        logger.info("pdfplumber no extrajo texto de %s, intentando OCR...", path)
        ocr_text = _ocr_extract(path)
        if ocr_text.strip():
            return ocr_text
        return text  # devolver vacío si OCR también falla

    # 2. pdftotext fallback
    try:
        r = subprocess.run(
            ['pdftotext', '-layout', path, '-'],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 3. OCR como último recurso
    ocr_text = _ocr_extract(path)
    if ocr_text.strip():
        return ocr_text

    raise RuntimeError("Instala pdfplumber (pip install pdfplumber) o poppler-utils")


def detect_provider(path: str) -> Optional[dict]:
    """Detecta el proveedor de un PDF por patrones en su contenido.

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
    for pkey, pdata in PROVIDERS.items():
        for pat in pdata['patterns']:
            if pat.lower() in text_lower:
                return {**pdata, 'key': pkey, 'text': text}
    return None
