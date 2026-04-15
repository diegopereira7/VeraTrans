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

# Último score medio de confianza OCR (0.0-1.0). 1.0 = texto nativo.
# Lo expone get_last_ocr_confidence() para que el pipeline propague la
# incertidumbre a cada InvoiceLine sin tener que reestructurar la API.
_last_ocr_confidence: float = 1.0


def get_last_ocr_confidence() -> float:
    """Confianza media del último extract_text() (1.0 si fue texto nativo)."""
    return _last_ocr_confidence


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


def _preprocess_for_ocr(img_bytes: bytes) -> bytes:
    """Mejora la imagen antes de pasarla al OCR.

    Aplica: grayscale → denoise (bilateral) → binarización adaptativa → deskew.
    Reduce errores de OCR en escaneos ruidosos o ligeramente inclinados,
    que es justo el escenario donde una sola pasada de LLM vision falla
    con mayor frecuencia (ver anyformat.ai/es/blog/anyformat-chatgpt-wont-cutit).

    Si OpenCV/numpy no están instalados devuelve los bytes originales —
    el preproceso es "best effort", nunca bloquea el OCR.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return img_bytes
    try:
        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return img_bytes
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # Denoise preservando bordes (bilateral barato para documentos).
        gray = cv2.bilateralFilter(gray, 5, 35, 35)
        # Binarización adaptativa — robusta a iluminación desigual.
        bw = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 31, 15,
        )
        # Deskew: coordenadas de píxeles oscuros → ángulo de rotación mínimo.
        coords = np.column_stack(np.where(bw < 128))
        if len(coords) > 50:
            angle = cv2.minAreaRect(coords)[-1]
            if angle < -45:
                angle = -(90 + angle)
            else:
                angle = -angle
            if abs(angle) > 0.3:
                h, w = bw.shape
                M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
                bw = cv2.warpAffine(bw, M, (w, h),
                                    flags=cv2.INTER_CUBIC,
                                    borderMode=cv2.BORDER_REPLICATE)
        _, buf = cv2.imencode('.png', bw)
        return buf.tobytes()
    except Exception as e:
        logger.debug("Preproceso OCR falló, uso imagen original: %s", e)
        return img_bytes


def _ocr_extract(path: str) -> str:
    """Extrae texto de un PDF escaneado usando OCR (EasyOCR + PyMuPDF).

    Además del texto, calcula el score medio de confianza y lo publica en
    _last_ocr_confidence para que el pipeline lo propague a cada línea.
    """
    global _last_ocr_confidence
    reader = _get_ocr_reader()
    if not reader:
        return ''
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.warning("PyMuPDF no instalado. pip install PyMuPDF")
        return ''

    pages_text = []
    confidences: list[float] = []
    try:
        doc = fitz.open(path)
        for page_num in range(len(doc)):
            pix = doc[page_num].get_pixmap(dpi=300)
            img_bytes = _preprocess_for_ocr(pix.tobytes("png"))
            # detail=1 devuelve (bbox, text, conf) para poder agregar confianza.
            results = reader.readtext(img_bytes, detail=1, paragraph=False)
            page_lines = []
            for _bbox, text, conf in results:
                if text:
                    page_lines.append(text)
                    confidences.append(float(conf))
            pages_text.append('\n'.join(page_lines))
        doc.close()
    except Exception as e:
        logger.warning("OCR falló para %s: %s", path, e)
        return ''

    text = '\n'.join(pages_text)
    if confidences:
        _last_ocr_confidence = round(sum(confidences) / len(confidences), 3)
        logger.info("OCR extrajo %d caracteres de %s (confianza media %.2f)",
                    len(text), path, _last_ocr_confidence)
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
    global _last_ocr_confidence
    # 1. pdfplumber (texto nativo)
    if HAS_PDFPLUMBER:
        with pdfplumber.open(path) as p:
            text = '\n'.join(pg.extract_text() or '' for pg in p.pages)
        if text.strip():
            _last_ocr_confidence = 1.0  # texto nativo → confianza máxima
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
            _last_ocr_confidence = 1.0
            return r.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 3. OCR como último recurso
    ocr_text = _ocr_extract(path)
    if ocr_text.strip():
        return ocr_text

    raise RuntimeError("Instala pdfplumber (pip install pdfplumber) o poppler-utils")


def extract_tables(path: str) -> list[list[list[str]]]:
    """Extrae tablas estructuradas de un PDF con pdfplumber.

    Devuelve una lista de tablas (una por tabla detectada en todas las páginas),
    donde cada tabla es una lista de filas, y cada fila una lista de celdas
    (strings, posibles valores vacíos). Los parsers que operen sobre facturas
    tabulares pueden usarlo en lugar de regex sobre texto plano — evita el
    problema clásico de "tablas aplanadas" (columnas mal alineadas al usar
    solo extract_text).

    Devuelve [] si pdfplumber no está instalado o el PDF no tiene tablas.
    """
    if not HAS_PDFPLUMBER:
        return []
    tables: list[list[list[str]]] = []
    try:
        with pdfplumber.open(path) as p:
            for page in p.pages:
                for tbl in page.extract_tables() or []:
                    # Normalizar celdas a str, colapsar None → ''
                    norm = [[('' if c is None else str(c).strip()) for c in row]
                            for row in tbl]
                    # Descarta tablas vacías y falsos positivos de 1 celda.
                    if any(any(c for c in row) for row in norm) and len(norm) > 1:
                        tables.append(norm)
    except Exception as e:
        logger.debug("extract_tables falló para %s: %s", path, e)
    return tables


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
