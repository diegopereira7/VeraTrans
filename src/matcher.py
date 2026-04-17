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
from src.articulos import ArticulosLoader
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


_SIZE_TOL = 10  # cm


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


def _detect_foreign_brand(nombre: str, pkey: str) -> Optional[str]:
    """Busca una marca conocida en el nombre del artículo que NO sea pkey.

    Devuelve el nombre de la marca ajena si hay match al final del nombre
    (patrón típico: ``ROSA XX 50CM 25U MARCA``), None si el nombre es
    genérico o si la marca que aparece es la del propio proveedor.
    """
    tokens = nombre.split()
    if not tokens:
        return None
    # Buscar entre las últimas 2 palabras (las marcas suelen ir al final).
    # Umbral 3 para cubrir marcas cortas como EQR; con 4 se escapaba.
    last_tokens = {t for t in tokens[-2:] if len(t) >= 3 and not t.endswith(('CM', 'U'))}
    known = _known_brands()
    pkey_up = (pkey or '').upper()
    for tok in last_tokens:
        if tok in known and tok != pkey_up:
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
    # Talla incompatible: más de _SIZE_TOL cm de diferencia.
    if line.size:
        sz_art = _infer_article_size(art)
        if sz_art and abs(sz_art - line.size) > _SIZE_TOL:
            v.append(f'size_mismatch({line.size}→{sz_art})')
    return v


def _score_candidate(line: InvoiceLine, cand: Candidate,
                     syn_entry: Optional[dict] = None,
                     provider_id: int = 0,
                     syn_store: Optional[SynonymStore] = None,
                     art_loader: Optional[ArticulosLoader] = None) -> None:
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
    line_var_tokens = {t for t in (line.variety or '').upper().split() if len(t) >= 3}

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
    elif line.variety:
        penalties.append('variety_no_overlap')
        score -= 0.10

    # — Talla
    sz_art = _infer_article_size(art)
    if line.size and sz_art:
        if sz_art == line.size:
            score += 0.20
            reasons.append('size_exact')
        elif abs(sz_art - line.size) <= _SIZE_TOL:
            score += 0.05
            reasons.append('size_close')

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

    # — Marca/proveedor en nombre del artículo
    pkey = (line.provider_key or '').upper()
    # Marca propia: pkey + brand_by_provider del catálogo
    own_brands = set()
    if pkey:
        own_brands.add(pkey)
    if art_loader and provider_id:
        catalog_brand = art_loader.brand_by_provider.get(provider_id)
        if catalog_brand:
            own_brands.add(catalog_brand.upper())
    own_brand_match = any(b in nombre for b in own_brands if b)
    if own_brand_match:
        score += 0.25
        reasons.append(f'brand_in_name({pkey})')
    else:
        foreign_brand = _detect_foreign_brand(nombre, pkey)
        if foreign_brand and foreign_brand not in own_brands:
            score -= 0.25
            penalties.append(f'foreign_brand({foreign_brand})')

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
        if s and int(s.get('articulo_id', 0) or 0) > 0 and s.get('status') != 'rechazado':
            art = self.art.articulos.get(s['articulo_id'])
            if art is None:
                # Fallback: reconstruir art mínimo a partir del entry del syn.
                art = {'id': s['articulo_id'], 'nombre': s.get('articulo_name', '')}
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

        # 2c) Color-strip para rosas
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
        pkey = getattr(line, 'provider_key', '')
        syn_entry = self.syn.find(provider_id, line)

        candidates = self._gather_candidates(provider_id, line)

        # Vetos estructurales — separa los descartados y degrada sinónimos
        # que contradigan la estructura.
        viable: list[Candidate] = []
        for c in candidates:
            vetos = _hard_vetoes(line, c.articulo)
            if vetos:
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
        for c in viable:
            s = syn_entry if c.source == 'synonym' else None
            _score_candidate(line, c, syn_entry=s,
                             provider_id=provider_id, syn_store=self.syn,
                             art_loader=self.art)

        # Brand boost: si existe un candidato con la marca propia del
        # proveedor en el nombre Y tiene variety+size EXACTO, promoverlo.
        # Regla de negocio: el artículo con marca propia SIEMPRE gana
        # sobre genéricos o marcas ajenas con la misma variedad+talla.
        # Score > 1.0 garantiza que gana cualquier empate.
        # size_close (±10cm) NO cuenta: si el parser leyó 50CM y hay
        # un artículo 60CM con la misma marca, no queremos empatarlos.
        own_brand = (self.art.brand_by_provider.get(provider_id) or '').upper()
        if own_brand:
            for c in viable:
                nombre = (c.articulo.get('nombre') or '').upper()
                if (own_brand in nombre
                        and 'variety_match' in c.reasons
                        and 'size_exact' in c.reasons):
                    c.score = max(c.score, 1.05)
                    if 'brand_boost' not in c.reasons:
                        c.reasons.append('brand_boost')

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
            self.syn.add(provider_id, line, line.articulo_id, line.articulo_name,
                         _origin_from_source(top1.source), invoice=invoice)
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
        plausible = ('variety_match' in top1.reasons
                     or top1.hint_score >= 0.85)
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
        """
        out = []
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
