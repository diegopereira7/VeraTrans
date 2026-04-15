"""Fallback con LLM para líneas 'sin_parser'.

Filosofía (alineada con anyformat.ai/es/blog/anyformat-chatgpt-wont-cutit):
el LLM NO es el extractor principal. Los 27 parsers deterministas de este
proyecto son más fiables para el dominio de flores, donde una confusión
entre QB/HB/TB o entre variedades de rosa cuesta dinero real.

El LLM entra solo como último recurso, con un contrato muy acotado:
  - Recibe una línea de texto que el rescate regex marcó como "probablemente
    producto" pero que ningún parser entendió.
  - Debe devolver los mismos campos que extrae un parser normal (variety,
    size, stems, price…) o indicar que no puede.
  - Nunca se usa para OCR ni para reescribir líneas ya parseadas.

Si la API key no está disponible el módulo es un no-op: devuelve las líneas
intactas. Esto es intencional — el pipeline debe funcionar offline.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Iterable

from src.models import InvoiceLine

logger = logging.getLogger(__name__)


# Confianza máxima asignable a un campo extraído por LLM. Mantener baja
# para forzar revisión humana incluso cuando el modelo está "seguro".
_LLM_CONFIDENCE = 0.65


_PROMPT = """Eres un extractor de líneas de facturas de flores. Recibes UNA línea de texto de una factura de un proveedor ecuatoriano o colombiano y devuelves los campos estructurados.

Campos a extraer (JSON estricto, sin texto extra):
  species:        "ROSES" | "CARNATIONS" | "HYDRANGEAS" | "ALSTROEMERIA" | "GYPSOPHILA" | "CHRYSANTHEMUM" | "OTHER"
  variety:        nombre de la variedad en mayúsculas (ej: "EXPLORER", "MONDIAL")
  size:           int en cm, 0 si no aparece
  stems_per_bunch: int, tallos por ramo (25 default rosas, 20 claveles)
  bunches:        int, número de ramos (0 si no se puede inferir)
  stems:          int, tallos totales
  price_per_stem: float, precio unitario por tallo
  line_total:     float, total de la línea
  box_type:       "QB" | "HB" | "TB" | "FB" | "" (full / half / quarter / third)

Si no puedes extraer la línea con razonable seguridad, devuelve {"error":"unparseable"}.
Si la línea no es una línea de producto (es un total, dirección, etc.), devuelve {"error":"not_a_product"}.

Línea a extraer:
%s
"""


def _call_llm(raw: str) -> dict | None:
    """Invoca el LLM con la línea. Devuelve dict o None si no disponible."""
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        logger.debug("anthropic no instalado; LLM fallback deshabilitado")
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=400,
            messages=[{'role': 'user', 'content': _PROMPT % raw}],
        )
        text = resp.content[0].text.strip()
        # El prompt pide JSON estricto; si el modelo devuelve algo con
        # preámbulo, extraemos el primer bloque {...}.
        start = text.find('{')
        end = text.rfind('}')
        if start < 0 or end < 0:
            return None
        return json.loads(text[start:end + 1])
    except Exception as e:
        logger.warning("LLM fallback falló: %s", e)
        return None


def enrich_unparsed_lines(lines: Iterable[InvoiceLine]) -> list[InvoiceLine]:
    """Intenta rellenar campos en líneas con match_status='sin_parser'.

    Muta cada línea rellenable:
      - Asigna campos extraídos.
      - Cambia match_status a 'llm_extraido' (para que la UI lo marque en revisión).
      - Asigna match_confidence = _LLM_CONFIDENCE.
      - Marca todos los field_confidence del valor devuelto con _LLM_CONFIDENCE.

    Deja intactas las líneas que no son sin_parser o para las que el LLM
    no aportó información utilizable.
    """
    lines = list(lines)
    for l in lines:
        if l.match_status != 'sin_parser':
            continue
        if not l.raw_description:
            continue
        data = _call_llm(l.raw_description)
        if not data or 'error' in data:
            continue
        # Poblar campos — solo los que el modelo devolvió con valor útil.
        for key in ('species', 'variety', 'box_type'):
            v = data.get(key)
            if isinstance(v, str) and v:
                setattr(l, key, v)
                l.field_confidence[key] = _LLM_CONFIDENCE
        for key in ('size', 'stems_per_bunch', 'bunches', 'stems'):
            v = data.get(key)
            if isinstance(v, (int, float)) and v > 0:
                setattr(l, key, int(v))
                l.field_confidence[key] = _LLM_CONFIDENCE
        for key in ('price_per_stem', 'line_total'):
            v = data.get(key)
            if isinstance(v, (int, float)) and v > 0:
                setattr(l, key, float(v))
                l.field_confidence[key] = _LLM_CONFIDENCE
        l.match_status = 'llm_extraido'
        l.match_method = 'llm-fallback'
        l.match_confidence = _LLM_CONFIDENCE
    return lines
