"""Motor de matching: vincula líneas de factura con artículos de VeraBuy.

Incluye el pipeline de 5 etapas y funciones de postproceso
(rescate de líneas no parseadas y split de cajas mixtas).
"""
from __future__ import annotations

import logging
import re
from copy import copy

from src.config import FUZZY_THRESHOLD_AUTO
from src.models import InvoiceLine
from src.articulos import ArticulosLoader
from src.sinonimos import SynonymStore

logger = logging.getLogger(__name__)


# Confianza asignada a cada etapa del pipeline (proxy calibrado, no probabilidad real).
# Valores elegidos para que un umbral de 0.80 separe "auto" de "revisar".
_METHOD_CONFIDENCE = {
    'sinónimo':          1.00,
    'sinónimo→marca':    0.98,
    'exacto':            0.95,
    'marca':             0.90,
    'delegacion':        0.80,   # Life Flowers delegation-stripping
    'color-strip':       0.75,   # "PINK ESPERANCE" → "ESPERANCE"
}


def _confidence_for_method(method: str) -> float:
    """Traduce match_method a un score 0-1.

    Si el método empieza por 'fuzzy NN%', extrae NN y lo divide por 100.
    Si es un método compuesto ('delegacion+exacto'), se queda con el primero.
    """
    if not method:
        return 0.0
    head = method.split('+', 1)[0].strip()
    m = re.match(r'fuzzy\s+(\d+)%', head, re.I)
    if m:
        return int(m.group(1)) / 100.0
    return _METHOD_CONFIDENCE.get(head, 0.70)


def _strip_life_delegation(variety: str, art_index: dict) -> str:
    """Strip Life Flowers delegation prefix by finding a known variety as suffix.

    Strategy: try progressively longer prefixes (1 word, 2 words, 3 words).
    For each, check if the remainder is a known variety in the article index.
    Return the longest match (= shortest delegation prefix that leaves a known variety).

    "RODRIGO PINK FLOYD" → try "PINK FLOYD" (known) → return "PINK FLOYD"
    "CAMPO FLOR EXPLORER" → try "EXPLORER" (no, too short), "FLOR EXPLORER" (no),
                            → try removing 2 words: "EXPLORER" (known) → return "EXPLORER"
    "MARL EXPLORER" → try "EXPLORER" (known) → return "EXPLORER"
    """
    from src.articulos import _normalize
    v = _normalize(variety)
    words = v.split()
    if len(words) <= 1:
        return v

    # Try stripping 1, 2, 3 words from the front (delegation)
    for n_strip in range(1, min(len(words), 4)):
        candidate = ' '.join(words[n_strip:])
        if candidate in art_index:
            return candidate
    # No known variety found — return original
    return v


_COLOR_PREFIX_RE = re.compile(
    r'^(?:PINK|RED|ORANGE|YELLOW|WHITE|PEACH|CREAM|SALMON|HOT PINK|LIGHT PINK)\s+', re.I)


def _strip_color_prefix(variety: str, art_index: dict) -> str | None:
    """Strip a color prefix from a variety if the remainder is a known article variety.

    "PINK ESPERANCE" → "ESPERANCE" (if ESPERANCE exists in catalog)
    "PINK FLOYD" → None (FLOYD doesn't exist, so keep PINK FLOYD)
    """
    from src.articulos import _normalize
    v = _normalize(variety)
    m = _COLOR_PREFIX_RE.match(v)
    if not m:
        return None
    candidate = v[m.end():].strip()
    if candidate and candidate in art_index:
        return candidate
    return None


class Matcher:
    """Pipeline de matching de 5 etapas: sinónimo → marca → exacto → rosa → fuzzy."""

    def __init__(self, art: ArticulosLoader, syn: SynonymStore):
        self.art = art
        self.syn = syn

    def match_line(self, provider_id: int, line: InvoiceLine,
                   invoice: str = '') -> InvoiceLine:
        """Intenta vincular una línea de factura con un artículo de VeraBuy.

        Pipeline de 7 etapas siguiendo el proceso manual del usuario:
        1. Sinónimo guardado (con upgrade a marca si aplica)
        2. Búsqueda priorizada: variedad+talla+marca > proveedor > genérico
        3. Match exacto por nombre esperado (legacy)
        4. Match por rosa EC/COL (legacy)
        5. Auto-fuzzy >=90%

        Args:
            provider_id: ID del proveedor.
            line: Línea de factura a matchear.
            invoice: Número de factura (para trazabilidad en sinónimos).

        Returns:
            La misma línea con match_status y match_method actualizados.
        """
        # 1. Sinónimo guardado
        s = self.syn.find(provider_id, line)
        if s and s['articulo_id'] > 0:
            # Verificar si existe artículo con marca (upgrade de sinónimo genérico)
            branded = self.art.find_branded(line.expected_name(), provider_id,
                                            getattr(line, 'provider_key', ''))
            if branded and branded['id'] != s['articulo_id']:
                self.syn.add(provider_id, line, branded['id'], branded['nombre'],
                             'auto-marca', invoice=invoice)
                line.articulo_id = branded['id']
                line.articulo_name = branded['nombre']
                line.match_status = 'ok'
                line.match_method = 'sinónimo→marca'
                return line
            # Enriquecer sinónimo con raw/invoice si faltan
            if not s.get('raw') and getattr(line, 'raw_description', ''):
                s['raw'] = line.raw_description[:120]
                s['invoice'] = invoice
                self.syn.syns[self.syn._key(provider_id, line)] = s
                self.syn.save()
            line.articulo_id = s['articulo_id']
            line.articulo_name = s['articulo_name']
            line.match_status = 'ok'
            line.match_method = 'sinónimo'
            return line

        # 2. Búsqueda priorizada por variedad+talla+marca (proceso manual)
        #    Prioridad: marca > proveedor_id > genérico > sin talla > cualquier
        if line.variety and self.art.by_variety:
            result, confidence, method = self.art.search_with_priority(
                variety=line.variety,
                size=line.size,
                provider_id=provider_id,
                provider_key=getattr(line, 'provider_key', ''),
            )
            if result:
                line.articulo_id = result['id']
                line.articulo_name = result['nombre']
                line.match_status = 'ok'
                line.match_method = method
                origin = 'auto-marca' if confidence == 'ALTA' else 'auto-matching'
                self.syn.add(provider_id, line, result['id'], result['nombre'],
                             origin, invoice=invoice)
                return line

        # 2b. Delegación stripping para Life Flowers (provider_id=4471)
        #     "MARL EXPLORER" → "EXPLORER", "CAMPO FLOR MONDIAL" → "MONDIAL"
        if provider_id == 4471 and line.variety:
            stripped = _strip_life_delegation(line.variety, self.art.by_variety)
            if stripped and stripped != line.variety.upper():
                result, confidence, method = self.art.search_with_priority(
                    variety=stripped, size=line.size,
                    provider_id=provider_id,
                    provider_key=getattr(line, 'provider_key', ''),
                )
                if result:
                    line.articulo_id = result['id']
                    line.articulo_name = result['nombre']
                    line.match_status = 'ok'
                    line.match_method = f'delegacion+{method}'
                    self.syn.add(provider_id, line, result['id'], result['nombre'],
                                 'auto-delegacion', invoice=invoice)
                    return line

        # 2c. Color prefix stripping for varieties like "PINK ESPERANCE" → "ESPERANCE"
        #     Only if the stripped variety exists in the article index.
        if line.variety and line.species == 'ROSES':
            stripped = _strip_color_prefix(line.variety, self.art.by_variety)
            if stripped:
                result, confidence, method = self.art.search_with_priority(
                    variety=stripped, size=line.size,
                    provider_id=provider_id,
                    provider_key=getattr(line, 'provider_key', ''),
                )
                if result:
                    line.articulo_id = result['id']
                    line.articulo_name = result['nombre']
                    line.match_status = 'ok'
                    line.match_method = f'color-strip+{method}'
                    self.syn.add(provider_id, line, result['id'], result['nombre'],
                                 'auto-color-strip', invoice=invoice)
                    return line

        # 3. Match exacto por nombre esperado (fallback legacy)
        a = self.art.find_by_name(line.expected_name())
        if a:
            line.articulo_id = a['id']
            line.articulo_name = a['nombre']
            line.match_status = 'ok'
            line.match_method = 'exacto'
            self.syn.add(provider_id, line, a['id'], a['nombre'], 'auto',
                         invoice=invoice)
            return line

        # 4. Match con marca del proveedor (fallback legacy)
        a = self.art.find_branded(line.expected_name(), provider_id,
                                  getattr(line, 'provider_key', ''))
        if a:
            line.articulo_id = a['id']
            line.articulo_name = a['nombre']
            line.match_status = 'ok'
            line.match_method = 'marca'
            self.syn.add(provider_id, line, a['id'], a['nombre'], 'auto-marca',
                         invoice=invoice)
            return line

        # 5. Match por rosa (si es rosa, fallback legacy)
        if line.species == 'ROSES' and line.size and line.stems_per_bunch:
            if line.origin != 'COL':
                a = self.art.find_rose_ec(line.variety, line.size, line.stems_per_bunch)
            else:
                a = self.art.find_rose_col(line.variety, line.size, line.stems_per_bunch, line.grade)
            if a:
                line.articulo_id = a['id']
                line.articulo_name = a['nombre']
                line.match_status = 'ok'
                line.match_method = 'exacto'
                self.syn.add(provider_id, line, a['id'], a['nombre'], 'auto',
                             invoice=invoice)
                return line

        # 6. Auto-fuzzy ≥90%
        cands = self.art.fuzzy_search(line, threshold=FUZZY_THRESHOLD_AUTO)
        if cands:
            best = cands[0]
            line.articulo_id = best['id']
            line.articulo_name = best['nombre']
            line.match_status = 'ok'
            line.match_method = f"fuzzy {best['similitud']}%"
            self.syn.add(provider_id, line, best['id'], best['nombre'], 'auto-fuzzy',
                         invoice=invoice)
            return line

        line.match_status = 'sin_match'
        line.match_method = ''
        return line

    def match_all(self, provider_id: int, lines: list[InvoiceLine],
                   invoice: str = '') -> list[InvoiceLine]:
        """Matchea todas las líneas de una factura."""
        out = []
        for l in lines:
            matched = self.match_line(provider_id, l, invoice=invoice)
            # Confidence del matching combinada con la del OCR.
            if matched.match_status == 'ok':
                base = _confidence_for_method(matched.match_method)
            else:
                base = 0.0
            matched.match_confidence = round(base * matched.ocr_confidence, 3)
            out.append(matched)
        return out


# --- Postproceso ---

# Patrones genéricos de líneas que probablemente son producto
_PRODUCT_LINE_RE = re.compile(
    r'(?:'
    r'^\s*\d+\s+(?:QB|HB|TB|QUARTER|HALF|FULL)\b'
    r'|'
    r'^\s*(?:QB|HB|TB)\s+\d'
    r'|'
    r'\b(?:ROSE|HYDRANGEA|CARNATION|CLAVEL|ALSTRO|GYPS|PANICULATA|CRISANTEMO|HYD)\b'
    r'|'
    r'^\s*\d+\s+[A-Z][A-Z\s.\-/]+\d+\s+\d+.*\d+\.\d{2}'
    r')',
    re.I
)
_NOISE_LINE_RE = re.compile(
    r'(?:'
    r'\bTOTAL\b|\bSUBTOTAL\b|\bSUB\s+TOTAL\b|\bGROSS\s+WEIGHT\b|\bNET\s+WEIGHT\b'
    r'|\bFULL\s+EQUIVALENT\b|\bPRODUCT\s+OF\b|\bCERTIFY\b|\bDISCLAIMER\b'
    r'|\bNAME\s+AND\s+TITLE\b|\bFREIGHT\b|\bPOWERED\s+BY\b|\bPACKING\b'
    r'|\bPage\s+\d|\bPieces\s+Product\b|\bBox\s+Units\b|\bREFERENCE\b'
    r'|\bTotal\s+pieces\b|\bTotal\s+Bunch\b|\bTotal\s+Stems\b|\bTotal\s+FULL\b'
    r'|\bTotal\s+USD\b|\bAmount\s+Due\b|\bTOT\.BOX\b|\bTOT\.BOUNCH\b|\bTOT\.\s*STEMS\b'
    r'|\bDISCOUNT\b|\bIVA\b|\bDOLLAR\b|\bSUB\s*TOTAL\b|\bINVOICE\b|\bPLEASE\b'
    r'|\bBENEFIC\b|\bWIRE\s+TRANSFER\b|\bCUSTOMER\b|\bCONSIGNEE\b|\bADDRESS\b'
    r'|\bCARRIER\b|\bSELLER\b|\bCOUNTRY\s+ESPA\b|\bDAE\b|\bM\.?A\.?W\.?B\b'
    r'|\bVARIEDAD\b|\bBOX\b.*\bTXB\b'
    r'|\bMIXED\s+BOX\b|\bTOTALS\b|\bFOB\b|\b\d+\s+TOTALS\b'
    r'|\bFlowers\s+Detail\b|\bBox\s+Detail\b|\bStems\s+Half\b|\bGross\s*$'
    r'|^(?:HB|QB|TB|FB)\s+[\d.]+\s+[\d.]+\s+[\d.]+\s*$'  # box summary: "HB 19.000 28.50 418.00"
    r'|^Carnation\s+[\d,]+\s+\d+\s+\d|^Minicarnation\s+[\d,]+\s+\d+\s+\d'
    r')',
    re.I
)


def rescue_unparsed_lines(text: str, parsed_lines: list[InvoiceLine]) -> list[InvoiceLine]:
    """Detecta líneas de producto en el texto que el parser no capturó.

    Args:
        text: Texto completo del PDF.
        parsed_lines: Líneas ya parseadas por el parser específico.

    Returns:
        Lista de InvoiceLine con match_status='sin_parser'.
    """
    parsed_raws = {l.raw_description.strip() for l in parsed_lines}
    # Variedades ya parseadas para evitar duplicados cuando raw_description no coincide
    # (ej: parser de tabla genera raw diferente al texto plano)
    parsed_varieties = {l.variety.strip().upper() for l in parsed_lines if l.variety.strip()}
    rescued = []
    for ln in text.split('\n'):
        ln_s = ln.strip()
        if not ln_s or len(ln_s) < 10:
            continue
        if ln_s in parsed_raws:
            continue
        if any(pr and pr in ln_s for pr in parsed_raws):
            continue
        # Si la línea contiene una variedad ya parseada, no rescatar
        ln_upper = ln_s.upper()
        if parsed_varieties and any(v in ln_upper for v in parsed_varieties if len(v) >= 4):
            continue
        if not _PRODUCT_LINE_RE.search(ln_s):
            continue
        if _NOISE_LINE_RE.search(ln_s):
            continue
        if not re.search(r'\d+\.\d{2}', ln_s):
            continue
        il = InvoiceLine(
            raw_description=ln_s,
            species='OTHER',
            variety='(NO PARSEADO)',
            match_status='sin_parser',
            match_method='',
        )
        rescued.append(il)
    return rescued


def reclassify_assorted(lines: list[InvoiceLine]) -> list[InvoiceLine]:
    """Reclassify unmatched ASSORTED/MIX lines as mixed_box.

    Lines with variety matching assorted/mix patterns that didn't match
    (sin_match) are reclassified as mixed_box since they represent mixed
    boxes without per-variety breakdown.

    Applies to all species (ROSES, ALSTROEMERIA, CARNATIONS, etc.).
    Does NOT touch lines that already matched (synonym or auto-match).
    """
    _ASSORTED_RE = re.compile(
        r'^(?:ASSORTED|SPECIAL\s+ASSTD|SPECIAL\s+ASSORTED|ASSTD'
        r'|ASSORTED\s+COLOR|MIX\s+COLORS?|MIX|MIXED'
        r'|SPECIAL\s+PACK|SURTIDO'
        r'|(?:SPRAY\s+)?CARNATION\s+(?:ASSORTED|MIX))$', re.I)
    for l in lines:
        if (l.match_status == 'sin_match'
                and _ASSORTED_RE.match(l.variety.strip())):
            l.match_status = 'mixed_box'
            l.match_method = 'assorted-no-desglose'
    return lines


def split_mixed_boxes(lines: list[InvoiceLine]) -> list[InvoiceLine]:
    """Divide líneas con variedad compuesta (A/B) en líneas individuales.

    Ej: variety='RED/YELLOW' → 2 líneas: RED y YELLOW, cada una con la mitad
    de tallos y total. Se marca box_type='MIX' en las líneas divididas.

    Args:
        lines: Líneas de factura ya parseadas.

    Returns:
        Lista con las líneas originales más las divididas.
    """
    result = []
    for l in lines:
        v = l.variety.strip()
        mix_m = re.search(r'^(.*[A-Za-z])\s*/\s*([A-Za-z].*)$', v)
        if not mix_m or l.box_type == 'MIX':
            result.append(l)
            continue
        c1 = mix_m.group(1).strip().upper()
        c2 = mix_m.group(2).strip().upper()
        half_stems = l.stems // 2
        half_total = round(l.line_total / 2, 2)
        half_bunches = l.bunches // 2 if l.bunches else 0
        for cv in (c1, c2):
            nl = copy(l)
            nl.variety = cv
            nl.stems = half_stems
            nl.line_total = half_total
            nl.bunches = half_bunches
            nl.box_type = 'MIX'
            result.append(nl)
    return result
