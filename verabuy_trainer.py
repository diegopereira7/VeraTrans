"""Wrapper de compatibilidad — el código real está en src/.

DEPRECADO: Usa 'from src.X import Y' directamente.
Este archivo existe solo para no romper imports existentes.
"""
import warnings
warnings.warn(
    "verabuy_trainer.py está deprecado. Importa desde src/ directamente.",
    DeprecationWarning, stacklevel=2,
)

# Re-exportar todo lo que procesar_pdf.py y otros scripts puedan necesitar
from src.config import *
from src.models import *
from src.articulos import ArticulosLoader
from src.sinonimos import SynonymStore
from src.historial import History
from src.matcher import Matcher, rescue_unparsed_lines as _rescue_unparsed_lines, split_mixed_boxes as _split_mixed_boxes
from src.pdf import detect_provider, extract_text as _pdf_text
from src.parsers import FORMAT_PARSERS
