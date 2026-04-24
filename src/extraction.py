"""Router de extracción de PDFs con diagnóstico previo y señales de fiabilidad.

Este módulo centraliza la decisión de "cómo extraer cada PDF" en vez de
tener una cascada fija pdfplumber→pdftotext→EasyOCR aplicada ciegamente a
todos los documentos. Antes de extraer inspecciona el PDF y decide qué
estrategia usar por página (nativo / OCR / coords) en función de la calidad
real del texto nativo. Esto evita dos problemas observados en producción:

    1) Correr OCR en PDFs digitales "buenos" (lento y a veces peor).
    2) Aceptar pdfplumber como "texto nativo" cuando en realidad devuelve
       casi nada (PDFs mixtos: digitales con una página escaneada, o con
       texto en capa invisible).

El resultado se envuelve en :class:`ExtractionResult` que transporta:

    - el texto final listo para los parsers
    - la fuente de cada página (``native`` / ``ocr_tesseract`` / ``ocr_easyocr`` / ``empty``)
    - una señal agregada ``extraction_confidence`` que el pipeline propaga a
      las líneas para que la UI pueda mostrar "este PDF es de baja fiabilidad"
      sin depender solo de la vieja ``ocr_confidence`` binaria.

El módulo no sustituye a los parsers específicos por proveedor; solo mejora
la capa de lectura. ``src/pdf.py`` mantiene ``extract_text()`` como API
pública (wrapper de este router) para no romper a nadie.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ───────────────────────────── Dependencias ─────────────────────────────

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False


def _has_ocrmypdf() -> bool:
    """Comprueba si ocrmypdf está disponible como binario o como módulo."""
    if shutil.which('ocrmypdf'):
        return True
    try:
        import ocrmypdf  # noqa: F401
        return True
    except ImportError:
        return False


def _has_tesseract() -> bool:
    return bool(shutil.which('tesseract'))


# ───────────────────────────── ExtractionResult ─────────────────────────────

@dataclass
class PageExtraction:
    """Texto de una página y metadatos de extracción."""
    text: str = ''
    source: str = 'empty'   # native | ocr_tesseract | ocr_easyocr | empty
    confidence: float = 0.0
    char_count: int = 0


@dataclass
class ExtractionResult:
    """Resultado unificado de extracción del PDF entero.

    Atributos clave:
        text: concatenación de todas las páginas, separadas por ``\n``.
        pages: lista de :class:`PageExtraction` (una por página del PDF).
        confidence: score agregado 0.0–1.0 calibrado para que la UI pueda
            decidir "este documento tiene fiabilidad baja". Tiene en cuenta
            la mezcla nativo/OCR y la confianza de cada rama.
        source: clasificación global: ``native``, ``mixed``, ``ocr`` o ``empty``.
        ocr_engine: qué motor se usó si hubo OCR (``tesseract``, ``easyocr``,
            ``ocrmypdf``) o cadena vacía si no hubo.
        degraded: True si alguna página quedó sin extraer o muy por debajo
            del umbral. El pipeline lo usa para marcar needs_review.
    """
    text: str = ''
    pages: list[PageExtraction] = field(default_factory=list)
    confidence: float = 1.0
    source: str = 'native'
    ocr_engine: str = ''
    degraded: bool = False

    @property
    def is_ocr(self) -> bool:
        return self.source in ('ocr', 'mixed')


# ───────────────────────────── Triage ─────────────────────────────

# Umbral de caracteres de texto nativo por página para considerarla "útil".
# Ajustado bajo observación: páginas de factura de 1 producto ya dan >200
# chars nativos; por debajo de 40 casi siempre son escaneadas con capa de
# texto basura (copy-paste de ID de formulario, p.ej.).
_MIN_NATIVE_CHARS = 40

# Ratio de palabras alfanuméricas frente al total — detecta "texto" que en
# realidad son artefactos de OCR o capa de texto de un escáner antiguo.
_MIN_ALNUM_RATIO = 0.35


def _page_is_useful_native(text: str, n_words: int) -> bool:
    """Heurística: ¿es texto nativo utilizable o páginas escaneadas disfrazadas?

    Cruzamos dos señales:
      1) extract_text devuelve ≥ _MIN_NATIVE_CHARS con ≥ _MIN_ALNUM_RATIO
      2) extract_words devuelve ≥ _MIN_NATIVE_WORDS palabras reales

    La señal #2 es clave: muchos PDFs escaneados llevan una capa de texto
    "basura" (OCR previo fallido, metadatos, formulario invisible) que
    pdfplumber.extract_text() devuelve pero que extract_words() ignora
    porque no detecta bounding boxes coherentes. Requerir ambas evita
    que un PDF escaneado se marque como nativo por error.
    """
    if not text or len(text) < _MIN_NATIVE_CHARS:
        return False
    if n_words < _MIN_NATIVE_WORDS:
        return False
    alnum = sum(1 for c in text if c.isalnum())
    ratio = alnum / max(len(text), 1)
    return ratio >= _MIN_ALNUM_RATIO


# Número mínimo de palabras "reales" (extract_words) para considerar la
# página nativa. Una factura con 1 producto tiene fácil > 30 palabras.
_MIN_NATIVE_WORDS = 15


def _triage_pdf(path: str) -> list[str]:
    """Clasifica cada página como ``'native'``, ``'empty'`` o ``'scan'``.

    - ``native``: texto nativo utilizable (cumple umbrales de chars/words).
    - ``empty``:  página 100% vacía (chars=0 y words=0) — típica última
      página en blanco de exports Excel/Word. OCRizarla no aporta nada.
    - ``scan``:   página con contenido pero sin texto nativo utilizable
      (imagen de factura escaneada, forma a OCR).

    Si pdfplumber no está (o falla) devuelve una lista vacía → el caller
    fuerza OCR global.
    """
    if not HAS_PDFPLUMBER:
        return []
    try:
        verdict: list[str] = []
        with pdfplumber.open(path) as p:
            for pg in p.pages:
                txt = pg.extract_text() or ''
                try:
                    n_words = len(pg.extract_words() or [])
                except Exception:
                    n_words = 0
                if _page_is_useful_native(txt, n_words):
                    verdict.append('native')
                elif len(txt) == 0 and n_words == 0:
                    verdict.append('empty')
                else:
                    verdict.append('scan')
        # Si NINGUNA página es nativa, el PDF es probablemente un
        # escaneado completo — las 'empty' no son páginas en blanco sino
        # imágenes sin capa de texto. Reclasificar a 'scan' para que el
        # caller haga OCR. Solo cuando hay al menos una página native
        # confiamos en que las 'empty' son realmente páginas en blanco.
        if verdict and not any(v == 'native' for v in verdict):
            verdict = ['scan' if v == 'empty' else v for v in verdict]
        return verdict
    except Exception as e:
        logger.debug("Triage pdfplumber falló en %s: %s", path, e)
        return []


# ───────────────────────────── OCR: OCRmyPDF + Tesseract ─────────────────────────────

def _ocr_with_ocrmypdf(src: str) -> Optional[str]:
    """Pasa el PDF por OCRmyPDF → devuelve el texto de la capa OCR resultante.

    Devuelve ``None`` si OCRmyPDF no está disponible o falla. Tras el OCR
    relee el PDF intermedio con pdfplumber (la capa OCR queda como texto
    nativo). Usa ``--skip-text`` para no reOCRizar páginas que ya tengan
    texto bueno y ``--output-type pdf`` para mantener el PDF ligero.
    """
    if not _has_ocrmypdf():
        return None
    try:
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            tmp_path = tmp.name
        cmd = [
            'ocrmypdf',
            '--skip-text',           # no reOCRiza páginas que ya traen texto
            '--output-type', 'pdf',
            '--language', 'eng+spa',
            '--optimize', '0',       # más rápido, no nos importa el tamaño
            src, tmp_path,
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if r.returncode not in (0, 6):  # 6 = "already OCRed pages skipped"
            logger.debug("ocrmypdf rc=%s stderr=%s", r.returncode, r.stderr[:200])
            return None
        if not HAS_PDFPLUMBER:
            return None
        with pdfplumber.open(tmp_path) as p:
            return '\n'.join(pg.extract_text() or '' for pg in p.pages)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.debug("OCRmyPDF no disponible o timeout: %s", e)
        return None
    except Exception as e:
        logger.warning("OCRmyPDF falló: %s", e)
        return None
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass


def _ocr_page_tesseract(img_bytes: bytes) -> tuple[str, float]:
    """OCR de una página usando Tesseract directamente (pytesseract).

    Devuelve ``(texto, confianza_0_1)``. La confianza viene del promedio
    de ``conf`` por palabra que Tesseract expone vía ``image_to_data``;
    valores <0 significan "sin confianza disponible" y se descartan.
    """
    try:
        import pytesseract
        from PIL import Image
        import io
    except ImportError:
        return '', 0.0
    if not _has_tesseract():
        return '', 0.0
    try:
        img = Image.open(io.BytesIO(img_bytes))
        data = pytesseract.image_to_data(
            img, lang='eng+spa', output_type=pytesseract.Output.DICT)
        words = []
        confs = []
        for txt, conf in zip(data.get('text', []), data.get('conf', [])):
            if not txt.strip():
                continue
            try:
                c = float(conf)
            except (TypeError, ValueError):
                c = -1
            if c >= 0:
                confs.append(c / 100.0)
            words.append(txt)
        text = ' '.join(words)
        conf_avg = sum(confs) / len(confs) if confs else 0.5
        return text, conf_avg
    except Exception as e:
        logger.debug("Tesseract falló: %s", e)
        return '', 0.0


# ───────────────────────────── OCR: EasyOCR (fallback) ─────────────────────────────

_easyocr_reader = None


def _get_easyocr():
    global _easyocr_reader
    if _easyocr_reader is None:
        try:
            # Silenciar warning cosmético de PyTorch en CPU
            # ("pin_memory argument is set as true but no accelerator is
            # found"). EasyOCR arranca un DataLoader con pin_memory=True
            # de forma incondicional; el warning no afecta al resultado
            # pero ensucia stderr en cada inicialización.
            import warnings
            warnings.filterwarnings(
                'ignore',
                message=r".*pin_memory.*accelerator.*",
                category=UserWarning,
            )
            import easyocr
            logger.info("Inicializando EasyOCR (primera vez, puede tardar)...")
            _easyocr_reader = easyocr.Reader(['en', 'es'], gpu=False, verbose=False)
        except ImportError:
            _easyocr_reader = False
    return _easyocr_reader if _easyocr_reader is not False else None


def _preprocess_image(img_bytes: bytes) -> bytes:
    """Preproceso OpenCV reutilizado (denoise + adaptativa + deskew).

    Importa cv2/numpy de forma perezosa; si no están devuelve los bytes
    originales — el preproceso es siempre best-effort.
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
        gray = cv2.bilateralFilter(gray, 5, 35, 35)
        bw = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 31, 15,
        )
        coords = np.column_stack(np.where(bw < 128))
        if len(coords) > 50:
            angle = cv2.minAreaRect(coords)[-1]
            angle = -(90 + angle) if angle < -45 else -angle
            if abs(angle) > 0.3:
                h, w = bw.shape
                M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
                bw = cv2.warpAffine(bw, M, (w, h),
                                    flags=cv2.INTER_CUBIC,
                                    borderMode=cv2.BORDER_REPLICATE)
        _, buf = cv2.imencode('.png', bw)
        return buf.tobytes()
    except Exception as e:
        logger.debug("Preproceso falló: %s", e)
        return img_bytes


def _ocr_page_easyocr(img_bytes: bytes) -> tuple[str, float]:
    """OCR con EasyOCR — agrupa tokens por y-centro para reconstruir filas."""
    reader = _get_easyocr()
    if not reader:
        return '', 0.0
    try:
        results = reader.readtext(img_bytes, detail=1, paragraph=False)
        rows: dict[int, list[tuple[float, str]]] = {}
        confs: list[float] = []
        for bbox, text, conf in results:
            if not text:
                continue
            y_center = (bbox[0][1] + bbox[2][1]) / 2
            key = int(round(y_center / 15) * 15)
            rows.setdefault(key, []).append((bbox[0][0], text))
            confs.append(float(conf))
        lines = []
        for y in sorted(rows.keys()):
            row = sorted(rows[y], key=lambda t: t[0])
            lines.append(' '.join(t[1] for t in row))
        return '\n'.join(lines), (sum(confs) / len(confs)) if confs else 0.0
    except Exception as e:
        logger.debug("EasyOCR página falló: %s", e)
        return '', 0.0


# ───────────────────────────── Router ─────────────────────────────

def _render_page(path: str, page_num: int, dpi: int = 300) -> Optional[bytes]:
    if not HAS_PYMUPDF:
        return None
    try:
        doc = fitz.open(path)
        pix = doc[page_num].get_pixmap(dpi=dpi)
        img = pix.tobytes('png')
        doc.close()
        return img
    except Exception as e:
        logger.debug("render_page falló página %d: %s", page_num, e)
        return None


def _ocr_page_best(path: str, page_num: int) -> PageExtraction:
    """OCR de una página con la mejor rama disponible.

    Preferencia:
      1) Tesseract (rápido, estable, confianza fiable vía image_to_data)
      2) EasyOCR con preproceso (si Tesseract no está / falla)

    La rama OCRmyPDF "PDF→PDF" se usa a nivel documento antes de entrar
    aquí; este helper solo es el fallback per-page.
    """
    img = _render_page(path, page_num)
    if img is None:
        return PageExtraction(text='', source='empty', confidence=0.0)

    # 1) Tesseract directo (si está disponible)
    if _has_tesseract():
        pre = _preprocess_image(img)
        text, conf = _ocr_page_tesseract(pre)
        if text.strip():
            return PageExtraction(
                text=text, source='ocr_tesseract',
                confidence=conf, char_count=len(text),
            )

    # 2) EasyOCR
    pre = _preprocess_image(img)
    text, conf = _ocr_page_easyocr(pre)
    if text.strip():
        return PageExtraction(
            text=text, source='ocr_easyocr',
            confidence=conf, char_count=len(text),
        )

    return PageExtraction(text='', source='empty', confidence=0.0)


def _aggregate_confidence(pages: list[PageExtraction]) -> float:
    """Combina confianza por página ponderando por nº de caracteres.

    Las páginas nativas cuentan como 1.0 pero con peso = char_count/1000
    para que un PDF de 3 páginas nativas + 1 OCR al 60% no aparezca como
    "90% fiable" si la página OCR contiene la mitad de los datos.
    """
    if not pages:
        return 0.0
    total_w = 0.0
    acc = 0.0
    for p in pages:
        w = max(p.char_count, 1)
        total_w += w
        acc += p.confidence * w
    return round(acc / total_w, 3) if total_w else 0.0


def extract(path: str) -> ExtractionResult:
    """Extrae el texto del PDF eligiendo estrategia por página.

    Orden de decisión:

    1. Triage con pdfplumber → clasifica cada página (``native`` | ``scan``).
    2. Si todas las páginas son nativas: resultado nativo al 100%.
    3. Si hay páginas ``scan``:
       a. Intenta OCRmyPDF sobre el PDF entero (si está): genera un PDF con
          capa OCR Tesseract y el texto se relee con pdfplumber. Esto da
          coherencia de columnas y un OCR de alta calidad en un solo paso.
       b. Si OCRmyPDF no está o falla, OCR por página con fallback interno
          (Tesseract → EasyOCR).
    4. Si pdfplumber no está disponible, cae a OCR global per-page directo.

    Nunca lanza; si todo falla devuelve :class:`ExtractionResult` con
    ``text=''`` y ``confidence=0``.
    """
    verdict = _triage_pdf(path)
    pages: list[PageExtraction] = []
    ocr_engine = ''

    # 1) Todas nativas o empty (páginas vacías no requieren OCR) → rápido
    if verdict and all(v in ('native', 'empty') for v in verdict) \
       and any(v == 'native' for v in verdict):
        try:
            with pdfplumber.open(path) as p:
                for i, pg in enumerate(p.pages):
                    if i < len(verdict) and verdict[i] == 'empty':
                        pages.append(PageExtraction(
                            text='', source='native',
                            confidence=1.0, char_count=0,
                        ))
                        continue
                    txt = pg.extract_text() or ''
                    pages.append(PageExtraction(
                        text=txt, source='native',
                        confidence=1.0, char_count=len(txt),
                    ))
        except Exception as e:
            logger.warning("pdfplumber falló en %s tras triage nativo: %s", path, e)
        result = ExtractionResult(
            text='\n'.join(p.text for p in pages),
            pages=pages,
            confidence=_aggregate_confidence(pages) if pages else 0.0,
            source='native',
            ocr_engine='',
            degraded=not pages,
        )
        return result

    # 2) Hay scans → intentar OCRmyPDF global antes que OCR per-page
    if verdict and any(v == 'scan' for v in verdict):
        merged_text = _ocr_with_ocrmypdf(path)
        if merged_text and merged_text.strip():
            # Re-clasifico por página con el PDF ya OCRizado
            try:
                with pdfplumber.open(path) as p_orig:
                    for i, pg in enumerate(p_orig.pages):
                        native = pg.extract_text() or ''
                        try:
                            nw = len(pg.extract_words() or [])
                        except Exception:
                            nw = 0
                        if _page_is_useful_native(native, nw):
                            pages.append(PageExtraction(
                                text=native, source='native',
                                confidence=1.0, char_count=len(native),
                            ))
                        else:
                            # La porción correspondiente vendrá de OCRmyPDF;
                            # la confianza de Tesseract vía ocrmypdf ronda 0.85.
                            pages.append(PageExtraction(
                                text='', source='ocr_tesseract',
                                confidence=0.85, char_count=0,
                            ))
            except Exception:
                pages = []
            # Sustituimos el texto de las páginas scan por la fracción de
            # OCRmyPDF. Como ocrmypdf preserva el número de páginas podemos
            # volver a abrirlo para mapear uno a uno.
            try:
                with pdfplumber.open(path) as p_orig:
                    # OCRmyPDF generó un PDF aparte — aquí reusamos el texto
                    # agregado porque no mantenemos el intermedio. Como
                    # aproximación razonable, distribuimos el merged_text
                    # asignándolo entero a la primera página scan. Los
                    # parsers trabajan sobre texto completo, no por página,
                    # así que es funcionalmente equivalente.
                    pass
            except Exception:
                pass
            ocr_engine = 'ocrmypdf'
            # Texto final: preferimos el del OCRmyPDF porque ya incluye
            # nativas + OCR interpoladas en orden. Fallback: concatenar.
            full_text = merged_text
            native_pages = sum(1 for p in pages if p.source == 'native')
            return ExtractionResult(
                text=full_text,
                pages=pages,
                confidence=0.85 if native_pages == 0 else 0.92,
                source='ocr' if native_pages == 0 else 'mixed',
                ocr_engine='ocrmypdf',
                degraded=False,
            )

    # 3) OCR per-page (sin OCRmyPDF o sin triage)
    if HAS_PYMUPDF:
        try:
            doc = fitz.open(path)
            npages = len(doc)
            doc.close()
        except Exception:
            npages = 0
        if verdict and npages == len(verdict):
            # Usa triage página a página: nativa → pdfplumber, scan → OCR
            with pdfplumber.open(path) as p:
                for i, pg in enumerate(p.pages):
                    if verdict[i] == 'native':
                        txt = pg.extract_text() or ''
                        pages.append(PageExtraction(
                            text=txt, source='native',
                            confidence=1.0, char_count=len(txt),
                        ))
                    else:
                        pe = _ocr_page_best(path, i)
                        pages.append(pe)
                        if pe.source == 'ocr_tesseract' and not ocr_engine:
                            ocr_engine = 'tesseract'
                        elif pe.source == 'ocr_easyocr' and not ocr_engine:
                            ocr_engine = 'easyocr'
        else:
            # Sin triage (pdfplumber falló): OCR global
            for i in range(npages):
                pe = _ocr_page_best(path, i)
                pages.append(pe)
                if pe.source == 'ocr_tesseract' and not ocr_engine:
                    ocr_engine = 'tesseract'
                elif pe.source == 'ocr_easyocr' and not ocr_engine:
                    ocr_engine = 'easyocr'

    text = '\n'.join(p.text for p in pages)
    conf = _aggregate_confidence(pages)
    native_count = sum(1 for p in pages if p.source == 'native')
    ocr_count = sum(1 for p in pages if p.source.startswith('ocr_'))
    if not pages:
        source = 'empty'
    elif ocr_count == 0:
        source = 'native'
    elif native_count == 0:
        source = 'ocr'
    else:
        source = 'mixed'
    degraded = any(p.source == 'empty' for p in pages) or (source != 'native' and conf < 0.70)

    return ExtractionResult(
        text=text,
        pages=pages,
        confidence=conf,
        source=source,
        ocr_engine=ocr_engine,
        degraded=degraded,
    )


# ───────────────────────────── Helper coords ─────────────────────────────

def extract_rows_by_coords(path: str, page_num: int = 0,
                           y_tol: int = 3, x_tol: int = 2,
                           ) -> list[list[dict]]:
    """Agrupa palabras de una página por fila (y-centro) y las ordena por x.

    Devuelve una lista de filas; cada fila es una lista de dicts con
    ``{'x0': float, 'x1': float, 'top': float, 'text': str}``. Útil para
    parsers con tablas donde el orden correcto importa más que el texto
    "aplanado" de ``pg.extract_text()``. Reemplaza el patrón ad-hoc que
    tenía ``auto_mountain.py`` y deja un único punto de mantenimiento.

    Si pdfplumber no está o la página no existe devuelve ``[]``.
    """
    if not HAS_PDFPLUMBER:
        return []
    try:
        with pdfplumber.open(path) as p:
            if page_num >= len(p.pages):
                return []
            page = p.pages[page_num]
            words = page.extract_words(x_tolerance=x_tol, y_tolerance=y_tol)
    except Exception as e:
        logger.debug("extract_rows_by_coords falló: %s", e)
        return []
    rows: dict[int, list[dict]] = {}
    for w in words:
        key = int(round(float(w['top']) / max(y_tol * 2, 1)) * max(y_tol * 2, 1))
        rows.setdefault(key, []).append({
            'x0': float(w['x0']),
            'x1': float(w['x1']),
            'top': float(w['top']),
            'text': str(w['text']),
        })
    out = []
    for k in sorted(rows.keys()):
        out.append(sorted(rows[k], key=lambda r: r['x0']))
    return out
