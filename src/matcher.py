"""Motor de matching: vincula líneas de factura con artículos de VeraBuy.

Desde la sesión 6 el matcher cambia de "quien llega primero gana, con score
fijo por método" a "se recolectan candidatos de varias fuentes, se puntúan
con features de evidencia + vetos estructurales, y gana el que mejor encaja
con margen suficiente". Las etapas del pipeline siguen existiendo pero
como *generadores* de candidatos, no como decisores del score.

Principales componentes:

    :class:`Candidate`          envoltura de un artículo ERP + por qué se propone.
    :func:`_hard_vetoes`        descarta incompatibles (species/origin/size/spb).
    :func:`_score_candidate`    calcula score 0-1 ponderando features reales.
    :class:`Matcher.match_line` orquesta generación → veto → scoring → margin.

``_METHOD_CONFIDENCE`` se conserva como **prior débil** — solo añade unos
puntos al candidato si su método de origen es fuerte. El score final ya no
depende mayoritariamente de esta tabla.

Trazabilidad en la línea (ver :class:`InvoiceLine`): ``link_confidence``,
``candidate_margin``, ``candidate_count``, ``match_reasons``,
``match_penalties``, ``top_candidates``. El estado ``ambiguous_match`` se
usa cuando hay 2 candidatos por encima del umbral y el margen es pequeño.
"""
from __future__ import annotations

import logging
import re
from copy import copy
from dataclasses import dataclass, field
from typing import Optional

from src.config import FUZZY_THRESHOLD_AUTO, translate_carnation_color
from src.models import InvoiceLine
from src.articulos import ArticulosLoader, _normalize
from src.sinonimos import SynonymStore

logger = logging.getLogger(__name__)


# Prior débil por método (añadido al score final, no dominante).
# Los valores son más bajos que antes: ahora el score se construye con
# features de evidencia y el método solo aporta una "cola" de confianza.
_METHOD_PRIOR = {
    'sinónimo':          0.10,
    'sinónimo→marca':    0.12,
    'exacto':            0.08,
    'marca':             0.10,
    'delegacion':        0.05,
    'color-strip':       0.04,
    'fuzzy':             0.00,
}

# Umbral para considerar un link "aceptable" (estado ok automático).
_LINK_OK_THRESHOLD = 0.70
# Margen mínimo entre top1 y top2 para no marcar ambigüedad.
_MARGIN_MIN = 0.10


# ──────────────────── Tabla antigua (compat) ────────────────────
# Conservada solo por retro-compat: algunos tests / scripts externos leen
# esta tabla. El flujo interno ya no la usa como decisor principal.
_METHOD_CONFIDENCE = {
    'sinónimo':          1.00,
    'sinónimo→marca':    0.98,
    'exacto':            0.95,
    'marca':             0.90,
    'delegacion':        0.80,
    'color-strip':       0.75,
}


def _confidence_for_method(method: str) -> float:
    """Legacy helper: traduce match_method → score 0-1 de la tabla antigua.

    Se mantiene para no romper código externo que lo importe. El matcher
    interno ya no lo usa como driver principal del score.
    """
    if not method:
        return 0.0
    head = method.split('+', 1)[0].strip()
    m = re.match(r'fuzzy\s+(\d+)%', head, re.I)
    if m:
        return int(m.group(1)) / 100.0
    return _METHOD_CONFIDENCE.get(head, 0.70)


# ──────────────────── Scoring por evidencia ────────────────────

@dataclass
class Candidate:
    """Un artículo ERP propuesto como candidato para una línea de factura.

    `source`: qué generador lo propuso (``synonym``, ``priority``,
        ``branded``, ``exact``, ``rose_ec``, ``rose_col``, ``fuzzy``,
        ``delegation``, ``color_strip``).
    `method_hint`: nombre legible del método, almacenado en
        `InvoiceLine.match_method` si este candidato gana.
    `trust`: fiabilidad específica de la fuente (ej. trust del sinónimo).
    `hint_score`: score base que dio el generador (p.ej. ratio fuzzy).
    """
    articulo: dict
    source: str
    method_hint: str = ''
    trust: float = 1.0
    hint_score: float = 0.0
    reasons: list = field(default_factory=list)
    penalties: list = field(default_factory=list)
    score: float = 0.0


_SIZE_TOL = 10  # cm — match "close" sin penalty
_SIZE_TOL_MAX = 20  # cm — umbral duro (veto por encima)

# Modificadores de color (tokens que cambian una variante del color base).
# Si aparecen en el nombre del artículo PERO NO en la variedad, penalizar:
# la variedad "LAVANDA" no debe ganar con "LAVANDA OSCURO" cuando existe
# "LAVANDA" a secas, ni "AZUL" con "AZUL CLARO" cuando existe "AZUL".
_COLOR_MODIFIERS = {
    'OSCURO', 'OSCURA', 'CLARO', 'CLARA',
    'LIGHT', 'DARK', 'PASTEL', 'MEDIUM',
    'NEON', 'BICOLOR',
}


_FOREIGN_BRANDS_CACHE: Optional[set[str]] = None
# Patrón de sufijos que NO son marcas (tamaños, unidades, orígenes)
_NOT_BRAND_RE = re.compile(r'^(\d+|CM|\d+CM|\d+U|EC|COL|BICOLOR|DIRECT|FARM)$', re.I)


def _known_brands() -> set[str]:
    """Conjunto de marcas conocidas: PROVIDERS keys + marcas extraídas del catálogo.

    Se usa para detectar cuándo un artículo "ROSA BRIGHTON 50CM 25U
    FIORENTINA" lleva marca, y así poder penalizar si esa marca NO es la
    del proveedor actual.
    """
    global _FOREIGN_BRANDS_CACHE
    if _FOREIGN_BRANDS_CACHE is None:
        try:
            from src.config import PROVIDERS
            brands = {k.upper() for k in PROVIDERS.keys()}
            # Añadir nombres de PROVIDERS (no solo keys) como variantes
            for pdata in PROVIDERS.values():
                for w in pdata.get('name', '').upper().split():
                    if len(w) >= 4 and not _NOT_BRAND_RE.match(w):
                        brands.add(w)
            # Añadir variantes hardcodeadas que no se derivan de PROVIDERS
            brands.update({'FIORENTINA', 'MYSTIC', 'STAMPSY', 'CANTIZA',
                           'CERES', 'GOLDEN', 'LATIN', 'AGRIVALDANI',
                           'SCARLET', 'MONTEROSAS', 'PONDEROSA', 'SANTOS'})
            _FOREIGN_BRANDS_CACHE = brands
        except Exception:
            _FOREIGN_BRANDS_CACHE = set()
    return _FOREIGN_BRANDS_CACHE


def _own_brands_norm(pkey: str, provider_id: int,
                     art_loader: Optional[ArticulosLoader]) -> set[str]:
    """Marca propia normalizada (sin acentos): pkey + brand_by_provider.

    Se usa tanto en `_score_candidate` (para disparar brand_in_name) como
    en `match_line` (para brand_boost). Centralizar evita divergencia
    si en el futuro se añade una tercera fuente de marca.
    """
    brands: set[str] = set()
    if pkey:
        pn = _normalize(pkey)
        if pn:
            brands.add(pn)
    if art_loader and provider_id:
        # Primary brand (top-1) — retrocompatibilidad.
        catalog_brand = art_loader.brand_by_provider.get(provider_id)
        if catalog_brand:
            cn = _normalize(catalog_brand)
            if cn:
                brands.add(cn)
        # Secondary brands autodetectadas: un proveedor puede tener varias
        # marcas (Uma usa UMA en rosas y VIOLETA en paniculata). Cualquier
        # marca con ≥ BRAND_MIN_ARTICLES en el catálogo cuenta como propia.
        extra = getattr(art_loader, 'brands_by_provider', {}).get(provider_id)
        if extra:
            for b in extra:
                bn = _normalize(b)
                if bn:
                    brands.add(bn)
    # Brands registradas manualmente en config (`catalog_brands`) — para
    # proveedores con marca multi-palabra que el autodetector ignora
    # (p. ej. TIERRA VERDE — `rsplit(' ', 1)` solo ve "VERDE" y está en
    # BRAND_IGNORE_SUFFIXES), o para mapear cuando el id de config no
    # coincide con el id_proveedor del catálogo ERP.
    if pkey:
        from src.config import PROVIDERS
        pdata = PROVIDERS.get(pkey)
        if pdata:
            for b in pdata.get('catalog_brands') or []:
                bn = _normalize(b)
                if bn:
                    brands.add(bn)
    return brands


def _detect_foreign_brand(nombre: str, pkey: str, art_loader=None) -> Optional[str]:
    """Busca una marca conocida en el nombre del artículo que NO sea pkey.

    Devuelve el nombre de la marca ajena si hay match al final del nombre
    (patrón típico: ``ROSA XX 50CM 25U MARCA``), None si el nombre es
    genérico o si la marca que aparece es la del propio proveedor.

    Comparación normalizada (sin tildes) para que ``TIMANÁ`` en el
    nombre no se trate como marca ajena cuando pkey es ``TIMANA``.
    """
    tokens = _normalize(nombre).split()
    if not tokens:
        return None
    # Buscar entre las últimas 2 palabras (las marcas suelen ir al final).
    # Umbral 3 para cubrir marcas cortas como EQR; con 4 se escapaba.
    last_tokens = {t for t in tokens[-2:] if len(t) >= 3 and not t.endswith(('CM', 'U'))}
    known = {_normalize(b) for b in _known_brands()}
    pkey_norm = _normalize(pkey or '')
    for tok in last_tokens:
        if tok in known and tok != pkey_norm:
            return tok
    return None


def _infer_article_species(art: dict) -> Optional[str]:
    """Deduce la especie del nombre del artículo ERP.

    Solo mira prefijos conocidos; si no reconoce, devuelve None — en ese
    caso no aplicamos veto de especie (mejor no-op que falso positivo).
    """
    n = (art.get('nombre') or '').upper()
    if n.startswith('ROSA'):              return 'ROSES'
    if n.startswith(('CLAVEL', 'MINI CLAVEL')): return 'CARNATIONS'
    if n.startswith('HYDRANGEA'):         return 'HYDRANGEAS'
    if n.startswith(('ALSTROMERIA', 'ALSTROEMERIA')):
        return 'ALSTROEMERIA'
    if n.startswith(('PANICULATA', 'GYPSOPHILA')):
        return 'GYPSOPHILA'
    if n.startswith('CRISANTEMO'):        return 'CHRYSANTHEMUM'
    return None


def _infer_article_origin(art: dict) -> Optional[str]:
    """Deduce origen del nombre: ``ROSA EC ...`` / ``ROSA COL ...`` → EC/COL."""
    n = (art.get('nombre') or '').upper()
    m = re.match(r'ROSA\s+(EC|COL)\b', n)
    if m:
        return m.group(1)
    m = re.search(r'\bCLAVEL\s+(COL|EC)\b', n)
    if m:
        return m.group(1)
    return None


def _infer_article_size(art: dict) -> Optional[int]:
    """Extrae el número de centímetros del nombre (``... 50CM ...``)."""
    n = (art.get('nombre') or '').upper()
    m = re.search(r'(\d{2,3})\s*CM\b', n)
    return int(m.group(1)) if m else None


def _infer_article_spb(art: dict) -> Optional[int]:
    """Extrae stems-per-bunch del nombre (``... 25U``)."""
    n = (art.get('nombre') or '').upper()
    m = re.search(r'\b(\d{1,3})\s*U\b', n)
    return int(m.group(1)) if m else None


def _hard_vetoes(line: InvoiceLine, art: dict) -> list[str]:
    """Vetos estructurales: devuelve lista de incompatibilidades.

    Si la lista no está vacía el candidato se descarta — ni el sinónimo
    más fuerte puede saltarse una contradicción de especie u origen.
    """
    v: list[str] = []
    sp_line = line.species
    sp_art = _infer_article_species(art)
    if sp_art and sp_line and sp_art != sp_line:
        # ROSES vs OTHER no cuenta como contradicción, OTHER es neutro.
        if sp_line != 'OTHER' and sp_art != 'OTHER':
            v.append(f'species_mismatch({sp_line}→{sp_art})')
    # Origen solo es vinculante para rosas y claveles (son los únicos
    # que tienen EC/COL en el catálogo).
    if sp_line in ('ROSES', 'CARNATIONS'):
        orig_line = line.origin
        orig_art = _infer_article_origin(art)
        if orig_art and orig_line and orig_art != orig_line:
            v.append(f'origin_mismatch({orig_line}→{orig_art})')
    # Talla incompatible: más de _SIZE_TOL_MAX cm de diferencia es
    # veto duro. Entre _SIZE_TOL (10) y _SIZE_TOL_MAX (20) se permite
    # el candidato pero con penalty en scoring (`size_off`), para que
    # un genérico COL/EC con variedad correcta pueda ganar a una
    # marca ajena con size exacto cuando no hay otra alternativa.
    if line.size:
        sz_art = _infer_article_size(art)
        if sz_art and abs(sz_art - line.size) > _SIZE_TOL_MAX:
            v.append(f'size_mismatch({line.size}→{sz_art})')
    return v


def _score_candidate(line: InvoiceLine, cand: Candidate,
                     syn_entry: Optional[dict] = None,
                     provider_id: int = 0,
                     syn_store: Optional[SynonymStore] = None,
                     art_loader: Optional[ArticulosLoader] = None,
                     has_own_branded_peer: bool = False) -> None:
    """Rellena cand.score / cand.reasons / cand.penalties con evidencia real.

    Features:
        +0.30 si variedad literal coincide
        +0.20 si talla coincide exacta
        +0.05 si talla coincide aproximada (±10cm)
        +0.15 si especie coincide explícitamente
        +0.10 si origen coincide (solo rosas/claveles)
        +0.10 si SPB coincide
        +0.10 si marca/proveedor aparece en el nombre del artículo
        +0.10 si este proveedor ya usa otras veces este artículo
        +trust(sinónimo) cuando el candidato viene de un synonym
        +method_prior (tabla reducida, cola de confianza)
        +hint_score para candidatos fuzzy (usa el ratio)

    Penalizaciones suaves (el candidato puede seguir pero pierde puntos):
        -0.10 si variedad no contiene ninguna palabra de la factura
        -0.15 si el articulo tiene grade pero la línea no lo comparte

    El score final se clampa a [0, 1].
    """
    art = cand.articulo
    nombre = (art.get('nombre') or '').upper()
    # Normalizar puntuación en la variedad antes de tokenizar: OCR y
    # parsers dejan ruido (`MONDIAL.`, `EXPLORER°`, `O´HARA`, `ASSORTED PM -`)
    # que antes impedía el `variety_match` aunque la variedad real
    # apareciera en el nombre del artículo. Mantener solo A-Z/0-9/espacios.
    _var_clean = re.sub(r'[^A-Z0-9 ]+', ' ',
                        (line.variety or '').upper())
    line_var_tokens = {t for t in _var_clean.split() if len(t) >= 3}

    # Para claveles el catálogo suele indexar por color en español
    # (CLAVEL COL FANCY NARANJA), pero la factura llega con variedad
    # + color en inglés ("COWBOY ORANGE"). Añadimos al set la versión
    # traducida para que variety_match pueda disparar por color.
    if line.species == 'CARNATIONS' and line.variety:
        translated = translate_carnation_color(line.variety).upper()
        for t in translated.split():
            if len(t) >= 3:
                line_var_tokens.add(t)

    score = 0.0
    reasons: list[str] = []
    penalties: list[str] = []

    # — Variedad
    if line_var_tokens and any(t in nombre for t in line_var_tokens):
        score += 0.30
        reasons.append('variety_match')
        # `variety_full`: todos los tokens ≥3 chars de la variedad de
        # la factura aparecen en el nombre. Marca útil para desempatar
        # en brand_boost (p.ej. línea "PINK MONDIAL" debe preferir
        # artículo "PINK MONDIAL" sobre el hermano "MONDIAL" de la
        # misma marca propia). Bonus pequeño para también influir en
        # el ranking fuera de brand_boost.
        if all(t in nombre for t in line_var_tokens):
            # Bonus alto porque variety_full significa que el candidato
            # cubre *todos* los tokens de la variedad. Cuando la variedad
            # incluye palabras genéricas de familia (PANICULATA/XLENCE/
            # TEÑIDA/ROSA), el `variety_match` parcial puede dispararse
            # por esos tokens — en ese caso el candidato correcto es el
            # único con variety_full porque tiene también el token
            # discriminante (color, modelo). El bonus de 0.10 es
            # suficiente para ganar +0.09 del fuzzy prior que los
            # rivales inferiores suelen acumular.
            score += 0.10
            reasons.append('variety_full')
        # Penalty por *modificador de color extra* en el nombre del
        # artículo que no está en la variedad. Casos típicos: variedad
        # "LAVANDA" empatando con "LAVANDA OSCURO", o "AZUL" empatando
        # con "AZUL CLARO". El modificador añade especificidad que la
        # factura no pide, así que el artículo más ajustado debe ganar.
        _NOMBRE_TOKS = set(re.findall(r'[A-ZÑ]{3,}', nombre))
        extra_mods = (_NOMBRE_TOKS & _COLOR_MODIFIERS) - line_var_tokens
        if extra_mods:
            score -= 0.12
            penalties.append(f'color_modifier_extra({"/".join(sorted(extra_mods))})')
    elif line.variety:
        # Excepción: un sinónimo de alto trust (manual_confirmado o
        # aprendido_confirmado) ES prueba explícita de que la traducción
        # tokens→artículo es válida aunque no haya overlap literal
        # (ej: GYPSOPHILA XL NATURAL WHITE → PANICULATA XLENCE BLANCO).
        # Sin esta excepción el sinónimo manual pierde -0.10 y puede ser
        # superado por un candidato fuzzy con overlap casual de tokens
        # irrelevantes (MIXTO por GYPSOPHILA genérico). El trust ya pesa
        # 0.98*0.25=0.245 en el score, que es proporcional al hecho.
        trust_exempts = (cand.source == 'synonym'
                         and (cand.trust or 0) >= 0.85)
        if not trust_exempts:
            penalties.append('variety_no_overlap')
            score -= 0.10
        else:
            reasons.append('synonym_overrides_variety')

    # — Talla
    sz_art = _infer_article_size(art)
    if line.size and sz_art:
        diff = abs(sz_art - line.size)
        if sz_art == line.size:
            score += 0.20
            reasons.append('size_exact')
        elif diff <= _SIZE_TOL:
            score += 0.05
            reasons.append('size_close')
        elif diff <= _SIZE_TOL_MAX:
            # Diff 11–20cm: permitido (no veto) pero con penalty para
            # que solo gane cuando no hay candidatos con size_exact
            # sin foreign_brand.
            score -= 0.10
            penalties.append(f'size_off({diff}cm)')

    # — Especie
    sp_art = _infer_article_species(art)
    if sp_art and sp_art == line.species and line.species != 'OTHER':
        score += 0.15
        reasons.append('species_match')

    # — Origen (rosas/claveles). Premio sustancial (0.15): el prefijo
    # EC/COL en el catálogo es autoritativo para desempatar contra
    # entradas genéricas sin origen (que suelen ganar por fuzzy 100%).
    if line.species in ('ROSES', 'CARNATIONS'):
        orig_art = _infer_article_origin(art)
        if orig_art and orig_art == line.origin:
            score += 0.15
            reasons.append('origin_match')

    # — Stems per bunch
    spb_art = _infer_article_spb(art)
    if line.stems_per_bunch and spb_art and spb_art == line.stems_per_bunch:
        score += 0.10
        reasons.append('spb_match')

    # — Marca/proveedor en nombre del artículo.
    # Comparamos con acentos normalizados: pkey='TIMANA' debe matchear
    # 'ROSA VENDELA ... TIMANÁ'. El catalog_brand lleva tilde en BD.
    pkey = (line.provider_key or '').upper()
    nombre_norm = _normalize(nombre)
    own_brands_norm = _own_brands_norm(pkey, provider_id, art_loader)
    own_brand_match = any(b in nombre_norm for b in own_brands_norm)
    if own_brand_match:
        score += 0.25
        reasons.append(f'brand_in_name({pkey})')
    else:
        foreign_brand = _detect_foreign_brand(nombre, pkey)
        if foreign_brand and _normalize(foreign_brand) not in own_brands_norm:
            score -= 0.25
            penalties.append(f'foreign_brand({foreign_brand})')
        elif has_own_branded_peer and own_brands_norm:
            # Genérico (ROSA EC / ROSA COL sin marca ni foreign) cuando
            # en el pool existe otro candidato con marca propia del
            # proveedor. Sin esta penalty, un sinónimo `aprendido_en_prueba`
            # heredado que apuntaba al genérico (trust 0.55 + method_prior
            # 0.10 = +0.24) derrotaba al branded propio (+0.25 brand). La
            # regla de negocio es "marca propia > genérico > marca ajena";
            # simetrizamos con -0.15 (menor que foreign -0.25, pero
            # suficiente para cerrar el gap de 0.24).
            score -= 0.15
            penalties.append('generic_vs_own_brand')

    # — Histórico del proveedor con este artículo
    if syn_store and provider_id and art.get('id'):
        usage = syn_store.provider_article_usage(provider_id, art['id'])
        if usage >= 3:
            score += 0.10
            reasons.append(f'provider_history({usage})')
        elif usage >= 1:
            score += 0.05
            reasons.append(f'provider_history({usage})')

    # — Trust del sinónimo (si vino de synonym)
    if cand.source == 'synonym' and syn_entry is not None:
        trust = SynonymStore.trust_score(syn_entry)
        score += 0.25 * trust
        reasons.append(f'synonym_trust({trust:.2f})')
        if trust < 0.60:
            penalties.append('weak_synonym')

    # — Prior de método (cola débil)
    head = (cand.method_hint.split('+', 1)[0].strip()
            if cand.method_hint else '')
    if head.startswith('fuzzy'):
        prior = _METHOD_PRIOR.get('fuzzy', 0.0) + (cand.hint_score * 0.15)
    else:
        prior = _METHOD_PRIOR.get(head, 0.05)
    score += prior
    if prior > 0:
        reasons.append(f'method_prior({head or "?"}:{prior:.2f})')

    # Clamp inferior a 0. Sin techo: candidatos con evidencia fuerte
    # (sinónimo confirmado + histórico + variety/size/species match)
    # pueden superar 1.0 y eso nos da un desempate real cuando el
    # brand_boost iguala a varios candidatos a 1.05.
    cand.score = round(max(0.0, score), 3)
    cand.reasons = reasons
    cand.penalties = penalties


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

# El input a la regex viene ya por _normalize (espacios colapsados a
# un espacio único), así que basta 'HOT PINK' literal en ambas regex.
_COLOR_SUFFIX_RE = re.compile(
    r'\s+(?:(?:IN|EN)\s+)?(?:HOT\s+PINK|LIGHT\s+PINK|PINK|RED|ORANGE|YELLOW|WHITE|PEACH|CREAM|SALMON|BLANCO|NARANJA|AMARILLO|ROJO|ROSA)$', re.I)

_CONNECTOR_RE = re.compile(r'\s+(?:AND|&|Y)\s+', re.I)


def _strip_color_prefix(variety: str, art_index: dict) -> str | None:
    """Strip a color prefix from a variety if the remainder is a known article variety.

    "PINK ESPERANCE" → "ESPERANCE" (if ESPERANCE exists in catalog)
    "PINK FLOYD" → None (FLOYD doesn't exist, so keep PINK FLOYD)
    """
    v = _normalize(variety)
    m = _COLOR_PREFIX_RE.match(v)
    if not m:
        return None
    candidate = v[m.end():].strip()
    if candidate and candidate in art_index:
        return candidate
    return None


def _simplified_variants(variety: str) -> list[str]:
    """Genera variantes simplificadas de una variedad sin verificar existencia.

    Aplica strip de color suffix y connector (AND/&/Y) en combinaciones.
    Uso: probar candidatos para matching cuando la variedad de factura
    ("HIGH AND MAGIC ORANGE") no coincide literal con el catálogo
    ("HIGH MAGIC BICOLOR"). El que llama filtra por existencia.
    """
    v = _normalize(variety)
    variants = [v]
    # Variante sin color suffix
    m = _COLOR_SUFFIX_RE.search(v)
    if m:
        base = v[:m.start()].strip()
        if base:
            variants.append(base)
    # Variante sin connector (AND/&/Y)
    without_conn = re.sub(r'\s+', ' ', _CONNECTOR_RE.sub(' ', v)).strip()
    if without_conn != v:
        variants.append(without_conn)
    # Combinación: sin color suffix Y sin connector
    for variant in list(variants):
        simplified = re.sub(r'\s+', ' ', _CONNECTOR_RE.sub(' ', variant)).strip()
        if simplified and simplified not in variants:
            variants.append(simplified)
    return variants


def _strip_connector(variety: str, art_index: dict) -> str | None:
    """Strip connector words (AND, &, Y) from a variety if the result exists.

    "HIGH AND MAGIC" → "HIGH MAGIC" (if HIGH MAGIC exists in catalog)
    "ROSA Y AZUL" → "ROSA AZUL" (if exists)

    Facturas escriben a veces variedades con conectores que el catálogo
    no conserva. Esto permite recuperar el match base.
    """
    v = _normalize(variety)
    simplified = _CONNECTOR_RE.sub(' ', v)
    simplified = re.sub(r'\s+', ' ', simplified).strip()
    if simplified != v and simplified in art_index:
        return simplified
    return None


def _strip_color_suffix(variety: str, art_index: dict) -> str | None:
    """Strip a color suffix from a variety if the remainder is a known article variety.

    Muchas facturas de rosas añaden el color al final ("VENDELA WHITE",
    "MONDIAL WHITE", "PINK MONDIAL PINK") mientras que el catálogo indexa
    la variedad sin color ("VENDELA", "MONDIAL", "PINK MONDIAL"). Este
    strip permite recuperar la variedad base cuando el catálogo la tiene.

    "VENDELA WHITE" → "VENDELA" (if VENDELA exists in catalog)
    "PINK MONDIAL PINK" → "PINK MONDIAL" (if PINK MONDIAL exists)
    "MONDIAL WHITE" → "MONDIAL" (if MONDIAL exists)
    """
    v = _normalize(variety)
    m = _COLOR_SUFFIX_RE.search(v)
    if not m:
        return None
    candidate = v[:m.start()].strip()
    if candidate and candidate in art_index:
        return candidate
    return None


class Matcher:
    """Matcher por evidencia: genera candidatos, aplica vetos y puntúa.

    Arquitectura en 3 pasos:

    1. **Generación de candidatos** (`_gather_candidates`): varias fuentes
       proponen artículos — sinónimo, búsqueda priorizada por talla+marca,
       delegación/color-strip, exact, branded, rose, fuzzy.
    2. **Vetos estructurales** (`_hard_vetoes`): descarta candidatos con
       contradicción dura (especie, origen, talla ±10cm). Ni siquiera un
       sinónimo manual se salta esto — en ese caso el sinónimo se marca
       como ``ambiguo``.
    3. **Scoring por evidencia** (`_score_candidate`): cada candidato
       recibe un score 0-1 basado en features reales + prior débil por
       método. El ganador se elige por score máximo; si el margen frente
       al 2º es pequeño la línea pasa a ``ambiguous_match``.
    """

    def __init__(self, art: ArticulosLoader, syn: SynonymStore):
        self.art = art
        self.syn = syn

    # ──────────────── Generadores de candidatos ────────────────

    def _gather_candidates(self, provider_id: int,
                           line: InvoiceLine) -> list[Candidate]:
        """Recolecta todos los artículos plausibles para la línea.

        Los generadores pueden proponer el mismo artículo varias veces; se
        deduplica por ``articulo.id`` conservando el generador con mayor
        ``hint_score`` / prioridad.
        """
        cands: list[Candidate] = []
        pkey = getattr(line, 'provider_key', '')

        # 1) Sinónimo guardado — si existe y no está rechazado
        s = self.syn.find(provider_id, line)
        if s and s.get('status') != 'rechazado':
            # Resolver el articulo_id actual vía id_erp si está presente
            # (re-mapea tras reimport de la tabla que haya reasignado ids).
            art_id = self.syn.resolve_article_id(s, self.art)
            if art_id > 0:
                art = self.art.articulos.get(art_id)
                if art is None:
                    # Fallback: reconstruir art mínimo a partir del entry del syn.
                    art = {'id': art_id, 'nombre': s.get('articulo_name', '')}
                cands.append(Candidate(
                    articulo=art, source='synonym', method_hint='sinónimo',
                    trust=SynonymStore.trust_score(s),
                ))

        # 2) Búsqueda priorizada (variedad+talla+marca > proveedor > genérico)
        if line.variety and self.art.by_variety:
            result, confidence, method = self.art.search_with_priority(
                variety=line.variety, size=line.size,
                provider_id=provider_id, provider_key=pkey,
            )
            if result:
                cands.append(Candidate(
                    articulo=result, source='priority', method_hint=method,
                ))

        # 2b) Delegación Life Flowers
        if provider_id == 4471 and line.variety:
            stripped = _strip_life_delegation(line.variety, self.art.by_variety)
            if stripped and stripped != line.variety.upper():
                result, confidence, method = self.art.search_with_priority(
                    variety=stripped, size=line.size,
                    provider_id=provider_id, provider_key=pkey,
                )
                if result:
                    cands.append(Candidate(
                        articulo=result, source='delegation',
                        method_hint=f'delegacion+{method}',
                    ))

        # 2c) Color-strip (prefijo) para rosas
        if line.variety and line.species == 'ROSES':
            stripped = _strip_color_prefix(line.variety, self.art.by_variety)
            if stripped:
                result, confidence, method = self.art.search_with_priority(
                    variety=stripped, size=line.size,
                    provider_id=provider_id, provider_key=pkey,
                )
                if result:
                    cands.append(Candidate(
                        articulo=result, source='color_strip',
                        method_hint=f'color-strip+{method}',
                    ))

        # 2d) Color-strip (sufijo) para rosas: "VENDELA WHITE" → "VENDELA"
        # si la base existe. Recupera los artículos con marca del proveedor
        # (ROSA VENDELA ... TIMANÁ) que no aparecen por by_variety con la
        # variedad completa, porque el catálogo indexa solo la base.
        if line.variety and line.species == 'ROSES':
            stripped = _strip_color_suffix(line.variety, self.art.by_variety)
            if stripped:
                result, confidence, method = self.art.search_with_priority(
                    variety=stripped, size=line.size,
                    provider_id=provider_id, provider_key=pkey,
                )
                if result:
                    cands.append(Candidate(
                        articulo=result, source='color_strip',
                        method_hint=f'color-suffix+{method}',
                    ))

        # 2e) Connector strip: "HIGH AND MAGIC ORANGE" → "HIGH MAGIC
        # ORANGE" si la versión sin AND/&/Y existe en by_variety. Se
        # aplica sobre la variedad directa y sobre la base post-
        # color-suffix ("HIGH AND MAGIC" → "HIGH MAGIC").
        if line.variety and line.species == 'ROSES':
            for source_variety in (line.variety,
                                    _strip_color_suffix(line.variety, self.art.by_variety)):
                if not source_variety:
                    continue
                without_conn = _strip_connector(source_variety, self.art.by_variety)
                if without_conn:
                    result, confidence, method = self.art.search_with_priority(
                        variety=without_conn, size=line.size,
                        provider_id=provider_id, provider_key=pkey,
                    )
                    if result:
                        cands.append(Candidate(
                            articulo=result, source='connector_strip',
                            method_hint=f'connector+{method}',
                        ))

        # 2f) Variety + BICOLOR: muchas rosas bicolor se facturan sin
        # "BICOLOR" pero el catálogo las indexa con sufijo (IGUAZU →
        # IGUAZU BICOLOR, CHERRY BRANDY PEACH → CHERRY BRANDY →
        # CHERRY BRANDY BICOLOR, HIGH AND MAGIC ORANGE → HIGH MAGIC →
        # HIGH MAGIC BICOLOR). Se prueban todas las simplificaciones
        # (color-suffix + connector-strip) con sufijo BICOLOR.
        # Si la variedad base también existe en by_variety, el scoring
        # natural decide (el genérico sin marca ajena gana al BICOLOR
        # cuando corresponde).
        if line.variety and line.species == 'ROSES':
            seen_bicolor = set()
            for base in _simplified_variants(line.variety):
                extended = base + ' BICOLOR'
                if extended in seen_bicolor:
                    continue
                seen_bicolor.add(extended)
                if extended in self.art.by_variety:
                    result, confidence, method = self.art.search_with_priority(
                        variety=extended, size=line.size,
                        provider_id=provider_id, provider_key=pkey,
                    )
                    if result:
                        cands.append(Candidate(
                            articulo=result, source='bicolor_ext',
                            method_hint=f'bicolor-ext+{method}',
                        ))

        # 3) Exact name
        a = self.art.find_by_name(line.expected_name())
        if a:
            cands.append(Candidate(articulo=a, source='exact', method_hint='exacto'))

        # 4) Branded
        a = self.art.find_branded(line.expected_name(), provider_id, pkey)
        if a:
            cands.append(Candidate(articulo=a, source='branded', method_hint='marca'))

        # 5) Rose-specific
        if line.species == 'ROSES' and line.size and line.stems_per_bunch:
            if line.origin != 'COL':
                a = self.art.find_rose_ec(line.variety, line.size, line.stems_per_bunch)
                if a:
                    cands.append(Candidate(articulo=a, source='rose_ec',
                                           method_hint='exacto'))
            else:
                a = self.art.find_rose_col(line.variety, line.size,
                                           line.stems_per_bunch, line.grade)
                if a:
                    cands.append(Candidate(articulo=a, source='rose_col',
                                           method_hint='exacto'))

        # 6) Fuzzy — siempre recolectamos los top-N por si el ganador por
        #    evidencia es uno que fuzzy propone aunque no llegue al umbral
        #    antiguo de "auto". El scoring final decide.
        try:
            # Threshold bajo (0.4): catálogos con varietys largas
            # (ALSTROMERIA COL WINTERFELL PREMIUM 70CM 10U) contra
            # líneas cortas (variety='WINTERFELL') dan ratios 40-50%.
            # El scoring por evidencia filtra después: candidatos sin
            # variety_match + size_exact no pasan el umbral de auto.
            fuzzy_hits = self.art.fuzzy_search(line, threshold=0.4) or []
        except Exception:
            fuzzy_hits = []
        for f in fuzzy_hits[:5]:
            sim = int(f.get('similitud', 0) or 0)
            cands.append(Candidate(
                articulo=f, source='fuzzy',
                method_hint=f'fuzzy {sim}%', hint_score=sim / 100.0,
            ))

        # Deduplicar por articulo_id conservando el candidato con mayor
        # prioridad (synonym > priority > branded > exact > delegation/color
        # > rose > fuzzy).
        priority_order = {
            'synonym': 0, 'priority': 1, 'branded': 2, 'exact': 3,
            'delegation': 4, 'color_strip': 4,
            'connector_strip': 4, 'bicolor_ext': 4,
            'rose_ec': 5, 'rose_col': 5, 'fuzzy': 6,
        }
        best_by_id: dict[int, Candidate] = {}
        for c in cands:
            aid = c.articulo.get('id') if c.articulo else None
            if aid is None:
                continue
            if aid not in best_by_id:
                best_by_id[aid] = c
            else:
                cur = best_by_id[aid]
                if priority_order.get(c.source, 99) < priority_order.get(cur.source, 99):
                    best_by_id[aid] = c
        return list(best_by_id.values())

    # ──────────────── Match por evidencia ────────────────

    def match_line(self, provider_id: int, line: InvoiceLine,
                   invoice: str = '') -> InvoiceLine:
        """Elige el mejor artículo por evidencia + vetos + margen.

        Proceso:
          1. Genera candidatos (varios generadores).
          2. Aplica vetos estructurales — descarta y degrada sinónimos
             contradictorios a status ``ambiguo``.
          3. Puntúa cada candidato superviviente con
             :func:`_score_candidate`.
          4. Ordena por score; si el ganador supera el umbral con margen
             suficiente → ``ok``; si varios superan el umbral con margen
             < 0.10 → ``ambiguous_match``; si ninguno → ``sin_match``.

        Rellena `line.link_confidence`, `candidate_margin`,
        `candidate_count`, `match_reasons`, `match_penalties`,
        `top_candidates` para trazabilidad.
        """
        pkey = getattr(line, 'provider_key', '') or ''
        # Fallback: algunos parsers no rellenan provider_key. Lo derivamos
        # del provider_id para que brand_in_name/foreign_brand/brand_boost
        # funcionen aunque el parser lo haya dejado vacío.
        if not pkey and provider_id:
            from src.config import PROVIDERS
            for k, pdata in PROVIDERS.items():
                if pdata.get('id') == provider_id:
                    pkey = k
                    line.provider_key = k
                    break
        syn_entry = self.syn.find(provider_id, line)

        candidates = self._gather_candidates(provider_id, line)

        # Vetos estructurales — separa los descartados y degrada sinónimos
        # que contradigan la estructura.
        viable: list[Candidate] = []
        for c in candidates:
            vetos = _hard_vetoes(line, c.articulo)
            if vetos:
                # Un sinónimo `manual_confirmado` indica que el operador
                # mapeó explícitamente esta línea a ese artículo aunque
                # origen/talla/spb no encajen (p.ej. "YELLOW SUMMER COL
                # 40/10" → único artículo existente "YELLOW SUMMER EC
                # 50/25"). Respetar la decisión: mantener el candidato
                # con el veto como penalty y no degradar el sinónimo.
                if (c.source == 'synonym' and syn_entry
                        and syn_entry.get('status') == 'manual_confirmado'):
                    c.penalties.extend(vetos)
                    viable.append(c)
                    continue
                c.penalties.extend(vetos)
                # Si el candidato era un sinónimo, degradar el syn entry.
                if c.source == 'synonym' and syn_entry:
                    syn_entry['status'] = 'ambiguo'
                    syn_entry['times_corrected'] = int(
                        syn_entry.get('times_corrected', 0) or 0) + 1
                    self.syn.save()
                continue
            viable.append(c)

        # Scoring por evidencia.
        # Precalcular si algún candidato viable tiene la marca propia del
        # proveedor en el nombre — flag que usa `_score_candidate` para
        # penalizar a los genéricos competidores y que el branded propio
        # pueda ganar a sinónimos débiles que apuntan al genérico.
        _own_brands_pool = _own_brands_norm(pkey, provider_id, self.art)
        has_own_branded_peer = bool(_own_brands_pool) and any(
            any(b in _normalize(c.articulo.get('nombre') or '')
                for b in _own_brands_pool)
            for c in viable
        )
        for c in viable:
            s = syn_entry if c.source == 'synonym' else None
            _score_candidate(line, c, syn_entry=s,
                             provider_id=provider_id, syn_store=self.syn,
                             art_loader=self.art,
                             has_own_branded_peer=has_own_branded_peer)

        # Brand boost: si existe un candidato con la marca propia del
        # proveedor en el nombre Y tiene variety+size EXACTO, promoverlo.
        # Regla de negocio: el artículo con marca propia SIEMPRE gana
        # sobre genéricos o marcas ajenas con la misma variedad+talla.
        # size_close (±10cm) NO cuenta: si el parser leyó 50CM y hay
        # un artículo 60CM con la misma marca, no queremos empatarlos.
        # Si existe un sinónimo `manual_confirmado` para esta línea
        # (p.ej. tras `golden_apply.py`) respetar esa decisión: saltar
        # brand_boost, que de otro modo promovería un candidato distinto
        # con la misma marca pero spb/variante diferente y sobrescribiría
        # la elección del operador.
        manual_syn_locked = (
            syn_entry is not None
            and syn_entry.get('status') == 'manual_confirmado'
            and int(syn_entry.get('articulo_id', 0) or 0) > 0
        )

        own_brands_norm = _own_brands_norm(pkey, provider_id, self.art)
        if own_brands_norm and not manual_syn_locked:
            boost_candidates = [
                c for c in viable
                if any(b in _normalize(c.articulo.get('nombre') or '')
                       for b in own_brands_norm)
                and 'variety_match' in c.reasons
                and 'size_exact' in c.reasons
            ]
            # Entre candidatos con marca propia preferimos `spb_match`
            # (elige el SKU con la talla por bouquet correcta) y luego
            # el score. Sólo promovemos si hay un líder claro — empates
            # reales se dejan al scoring base para no crear
            # ambiguous_match artificial en provs con mucho catálogo
            # marcado (ECOFLOR/MYSTIC).
            boost_candidates.sort(
                key=lambda c: ('spb_match' in c.reasons,
                               'variety_full' in c.reasons,
                               c.score),
                reverse=True)
            second = (boost_candidates[1] if len(boost_candidates) > 1
                      else None)
            clear_winner = (
                len(boost_candidates) == 1
                or (second is not None
                    and (('spb_match' in boost_candidates[0].reasons
                          and 'spb_match' not in second.reasons)
                         or ('variety_full' in boost_candidates[0].reasons
                             and 'variety_full' not in second.reasons)
                         or boost_candidates[0].score > second.score + 0.05))
            )
            if boost_candidates and clear_winner:
                c = boost_candidates[0]
                other_top = max(
                    (o.score for o in viable if o is not c), default=0.0)
                c.score = max(c.score, 1.05, other_top + 0.05)
                if 'brand_boost' not in c.reasons:
                    c.reasons.append('brand_boost')

        # Manual pin: si existe sinónimo manual_confirmado y el candidato
        # ligado está en viable, forzarlo a ganar. El operador ya decidió;
        # el matcher respeta esa decisión como verdad absoluta. Diferencia
        # con brand_boost: no requiere variety_match ni size_exact; basta
        # con que el sinónimo apunte a un articulo válido y ese candidato
        # siga en viable (el fix de sesión 9y garantiza que los vetos
        # duros no descarten a un manual_confirmado, solo lo penalizan).
        if manual_syn_locked:
            target_id = int(syn_entry['articulo_id'])
            pinned = next(
                (c for c in viable
                 if int(c.articulo.get('id') or 0) == target_id),
                None,
            )
            if pinned is not None:
                other_top = max(
                    (c.score for c in viable if c is not pinned),
                    default=0.0,
                )
                pinned.score = max(pinned.score, 1.10, other_top + 0.05)
                if 'manual_pin' not in pinned.reasons:
                    pinned.reasons.append('manual_pin')

        viable.sort(key=lambda c: c.score, reverse=True)
        line.candidate_count = len(viable)
        line.top_candidates = [
            {'id': c.articulo.get('id'),
             'nombre': c.articulo.get('nombre', ''),
             'score': c.score,
             'source': c.source,
             'reasons': list(c.reasons),
             'penalties': list(c.penalties)}
            for c in viable[:3]
        ]

        if not viable:
            line.match_status = 'sin_match'
            line.match_method = ''
            line.link_confidence = 0.0
            line.candidate_margin = 0.0
            line.match_reasons = []
            line.match_penalties = []
            return line

        top1 = viable[0]
        top2_score = viable[1].score if len(viable) > 1 else 0.0
        margin = round(top1.score - top2_score, 3)
        line.candidate_margin = margin
        # link_confidence queda en [0,1] para la UI y match_confidence;
        # el score interno puede exceder 1.0 para desempatar brand_boost.
        line.link_confidence = min(1.0, top1.score)
        line.match_reasons = list(top1.reasons)
        line.match_penalties = list(top1.penalties)

        # Decisión.
        if top1.score >= _LINK_OK_THRESHOLD:
            # Margen requerido adaptativo: los scores pueden exceder 1.0
            # cuando la evidencia es muy fuerte (sinónimo + histórico +
            # match pleno). Tres tramos:
            #   ≥ 1.05 (brand_boost o evidencia rica): margen mínimo 0.02
            #   ≥ 0.90 (candidato fuerte):             margen mínimo 0.05
            #   0.70–0.90 (zona media):                margen completo (0.10)
            if top1.score >= 1.05:
                required_margin = 0.02
            elif top1.score >= 0.90:
                required_margin = 0.05
            else:
                required_margin = _MARGIN_MIN
            if margin < required_margin and top2_score >= _LINK_OK_THRESHOLD:
                # Desempate cualitativo: el margen numérico es ajustado,
                # pero uno puede dominar objetivamente si tiene una
                # feature crítica que el otro NO tiene. Dos son
                # determinantes:
                #   - `size_exact` vs `size_close`: un candidato
                #     coincide en talla exacta (ej. sz 40 == 40CM) y el
                #     otro solo coincide aproximada. Típico en tallas
                #     cercanas del mismo branded.
                #   - `variety_full` vs `variety_match` parcial: todos
                #     los tokens de la variedad aparecen en el nombre,
                #     frente a uno solo. Típico en variedades
                #     multi-palabra ("VIOLET HILL", "RAINBOW PASTEL").
                # El desempate es SIMÉTRICO: si el ganador cualitativo es
                # top2 (no top1), lo promovemos a ganador antes de
                # aplicar el tiebreak. Ej.: top1 = fuzzy 63% con score
                # levemente superior por el prior, top2 = variety_full
                # exacto — el correcto es top2.
                top2_reasons = set(viable[1].reasons or [])
                top1_reasons_set = set(top1.reasons)
                # ¿top2 gana cualitativamente? Si sí, swap.
                top2_decisive_size = ('size_exact' in top2_reasons
                                      and 'size_exact' not in top1_reasons_set
                                      and 'size_close' in top1_reasons_set)
                top2_decisive_variety = ('variety_full' in top2_reasons
                                         and 'variety_full' not in top1_reasons_set)
                if top2_decisive_size or top2_decisive_variety:
                    # Swap: top2 pasa a ser top1 (ganador).
                    top1, viable[0], viable[1] = viable[1], viable[1], top1
                    top1_reasons_set = set(top1.reasons)
                    top2_reasons = set(viable[1].reasons or [])
                    line.match_reasons = list(top1.reasons)
                    line.match_penalties = list(top1.penalties)
                decisive_size = ('size_exact' in top1_reasons_set
                                 and 'size_exact' not in top2_reasons
                                 and 'size_close' in top2_reasons)
                decisive_variety = ('variety_full' in top1_reasons_set
                                    and 'variety_full' not in top2_reasons)
                # Color-modifier asimétrico: top2 introduce un modificador
                # (OSCURO/CLARO/PASTEL...) que la variedad no pide, top1
                # no. Ej: la línea dice "AZUL" y top2 es "AZUL CLARO".
                # Color distinto → top1 es el correcto.
                top2_pen_names = {p.split('(', 1)[0] for p in (viable[1].penalties or [])}
                top1_pen_names = {p.split('(', 1)[0] for p in (top1.penalties or [])}
                decisive_color_mod = ('color_modifier_extra' in top2_pen_names
                                      and 'color_modifier_extra' not in top1_pen_names)
                if decisive_size or decisive_variety or decisive_color_mod:
                    tag = ('tiebreak_size_exact' if decisive_size
                           else 'tiebreak_variety_full' if decisive_variety
                           else 'tiebreak_color_modifier')
                    line.match_reasons.append(tag)
                    # Ganador claro por desempate cualitativo.
                    line.match_status = 'ok'
                    line.match_method = top1.method_hint or 'evidencia'
                    line.articulo_id = top1.articulo.get('id')
                    line.articulo_name = top1.articulo.get('nombre', '')
                    # No rescribir el sinónimo si él mismo fue el ganador
                    # (evita degradar entries manual_confirmado a 'auto').
                    if top1.source != 'synonym':
                        self.syn.add(provider_id, line, line.articulo_id,
                                     line.articulo_name,
                                     _origin_from_source(top1.source),
                                     invoice=invoice,
                                     articulo_id_erp=top1.articulo.get('id_erp', '') or '')
                    has_independent_evidence = (
                        'variety_match' in top1.reasons
                        and ('size_exact' in top1.reasons
                             or 'brand_in_name' in top1.reasons)
                    )
                    if has_independent_evidence:
                        self.syn.register_match_hit(provider_id, line,
                                                    line.articulo_id)
                    return line
                # Dos candidatos buenos y realmente empatados → ambigüedad.
                line.match_status = 'ambiguous_match'
                line.match_method = top1.method_hint or 'evidencia'
                line.match_penalties.append(f'tie_top2_margin({margin})')
                line.articulo_id = top1.articulo.get('id')
                line.articulo_name = top1.articulo.get('nombre', '')
                return line
            # Ganador claro
            line.match_status = 'ok'
            line.match_method = top1.method_hint or 'evidencia'
            line.articulo_id = top1.articulo.get('id')
            line.articulo_name = top1.articulo.get('nombre', '')
            # Guardar sinónimo (en prueba) para refuerzo si no lo había.
            # PERO: si el ganador YA vino del sinónimo, no tiene sentido
            # hacer add(): el sinónimo preexiste, no hay "alta", y un add
            # con origen='auto' degradaría una entry previa con
            # status=manual_confirmado a aprendido_en_prueba (perdiendo la
            # verdad del operador). register_match_hit abajo ya incrementa
            # times_confirmed — suficiente para reforzar el sinónimo.
            if top1.source != 'synonym':
                self.syn.add(provider_id, line, line.articulo_id,
                             line.articulo_name,
                             _origin_from_source(top1.source),
                             invoice=invoice,
                             articulo_id_erp=top1.articulo.get('id_erp', '') or '')
            # Auto-confirmación del sinónimo: si el ok ganó con evidencia
            # independiente (variety+size_exact o variety+brand_in_name),
            # cuenta como hit. Tras ≥ 2 hits el sinónimo promueve de
            # aprendido_en_prueba → aprendido_confirmado. Esto ataca el
            # bloqueo ok → auto causado por synonym_trust 0.55 y reduce
            # el penalty mark-only `weak_synonym` sin riesgo: requiere
            # que la evidencia del match no dependa del sinónimo.
            has_independent_evidence = (
                'variety_match' in top1.reasons
                and ('size_exact' in top1.reasons
                     or 'brand_in_name' in top1.reasons)
            )
            if has_independent_evidence:
                self.syn.register_match_hit(provider_id, line, line.articulo_id)
            return line

        # Ningún candidato supera el umbral de auto-vinculación.
        # Si hay score razonable (≥0.50) lo dejamos como ambiguous para
        # revisión, en vez de descartarlo como sin_match. Esto evita que
        # una lectura buena pero sin evidencia dura caiga al abismo.
        # EXCEPCIÓN: si el ganador NO tiene variety_match (la variedad
        # ni siquiera solapa parcialmente con el artículo) Y la similitud
        # fuzzy es baja (<0.70), el candidato es ruido. Mejor sin_match
        # para no proponer matches arbitrarios tipo "SHY → SYMBOL".
        # Mantenemos ambiguous si la fuzzy es alta (LIMONADA→LEMONADE
        # sin solape literal pero similitud 88%) — el operador decide.
        # Un sinónimo preexistente es por definición una afirmación
        # explícita (manual o aprendida) de que VARIETY→ARTICULO es
        # válido. Aunque los tokens no solapen ni la fuzzy sea alta, el
        # match es plausible por la mera existencia del sinónimo.
        plausible = ('variety_match' in top1.reasons
                     or top1.hint_score >= 0.85
                     or top1.source == 'synonym')
        if top1.score >= 0.50 and plausible:
            line.match_status = 'ambiguous_match'
            line.match_method = top1.method_hint or 'evidencia'
            line.articulo_id = top1.articulo.get('id')
            line.articulo_name = top1.articulo.get('nombre', '')
            line.match_penalties.append(f'low_evidence({top1.score})')
            return line

        line.match_status = 'sin_match'
        line.match_method = ''
        return line

    def match_all(self, provider_id: int, lines: list[InvoiceLine],
                   invoice: str = '') -> list[InvoiceLine]:
        """Matchea todas las líneas y combina link_confidence con
        extraction/ocr para el match_confidence global (retrocompat).

        Envuelve el loop en ``syn.batch()`` para diferir la escritura del
        JSON de sinónimos y el sync a MySQL hasta el final: antes cada
        línea disparaba un save completo del archivo (~190ms/línea
        dominante, ~80% del tiempo total del match).
        """
        out = []
        with self.syn.batch():
            for l in lines:
                matched = self.match_line(provider_id, l, invoice=invoice)
                ocr = matched.ocr_confidence if matched.ocr_confidence > 0 else 1.0
                ext = matched.extraction_confidence if matched.extraction_confidence > 0 else 1.0
                # match_confidence = link_confidence × extraction × ocr.
                # Los 3 factores son independientes; si alguno flaquea el score
                # final baja aunque el enlace sea sólido.
                matched.match_confidence = round(
                    matched.link_confidence * ocr * ext, 3)
                out.append(matched)
        return out


def _origin_from_source(source: str) -> str:
    """Mapea la fuente del candidato al `origen` del sinónimo guardado."""
    return {
        'synonym':     'auto',
        'priority':    'auto-matching',
        'branded':     'auto-marca',
        'exact':       'auto',
        'delegation':  'auto-delegacion',
        'color_strip': 'auto-color-strip',
        'rose_ec':     'auto',
        'rose_col':    'auto',
        'fuzzy':       'auto-fuzzy',
    }.get(source, 'auto')


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
    r'|\bHAWB\b'  # resumen BRISSAS: "HB 21.000 HAWB: SN"
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
        # La red de seguridad NO debe disimular fallos del parser específico:
        # marcamos extraction_source='rescue' para que la UI las pinte como
        # "recuperadas" y no igual que una línea parseada normal.
        il.extraction_source = 'rescue'
        il.extraction_confidence = 0.60
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
        r'|ASSORTED\s+(?:COLOR|ROSA|ROSE)|MIX\s+COLORS?|MIX|MIXED|MIXTO'
        r'|SPECIAL\s+PACK|SURTIDO(?:\s+MIXTO)?'
        r'|(?:SPRAY\s+)?CARNATION\s+(?:ASSORTED|MIX))$', re.I)
    for l in lines:
        # También reclasifica ambiguous_match si la variedad es claramente
        # un "assorted" — no tiene sentido pedir revisión para esos.
        if (l.match_status in ('sin_match', 'ambiguous_match')
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
