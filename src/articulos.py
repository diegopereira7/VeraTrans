"""Cargador e indexador de artículos desde el dump SQL de VeraBuy."""
from __future__ import annotations

import logging
import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from typing import Dict, List, Optional

from src.config import (
    FILE_ENCODING, SPECIES_PREFIXES, BRAND_IGNORE_SUFFIXES, BRAND_MIN_ARTICLES,
    strip_provider_suffix, translate_carnation_color, DEFAULT_SIZE_CARNATIONS,
)
from src.models import InvoiceLine

logger = logging.getLogger(__name__)

# Traducciones variedad inglés → español para búsqueda flexible
VARIETY_TRANSLATIONS = {
    # Multiword first (matched before single words)
    'GYPSOPHILA OVER TIME WHITE': 'OVERTIME BLANCO',
    'GYPSOPHILA OVER TIME': 'OVERTIME',
    'OVER TIME WHITE': 'OVERTIME BLANCO',
    'OVER TIME': 'OVERTIME',
    'GYPSOPHILA XLENCE NATURAL': 'XLENCE BLANCO',
    'GYPSOPHILA XLENCE RAINBOW MIX LIGHT': 'XLENCE TENIDA RAINBOW',
    'GYPSOPHILA XLENCE': 'XLENCE BLANCO',
    'GYPSOPHILA': 'PANICULATA',
    'GARDEN ROSE': 'LA GARDEN',
    'TINTED BLUE': 'TENIDA AZUL',
    'TINTED RED': 'TENIDA ROJO',
    'TINTED PINK': 'TENIDA ROSA',
    'TINTED GREEN': 'TENIDA VERDE',
    'TINTED ORANGE': 'TENIDA NARANJA',
    'TINTED PURPLE': 'TENIDA MORADO',
    'TINTED BLACK': 'TENIDA NEGRO',
    'TINTED': 'TENIDA',
    'WHITE': 'BLANCO',
    'RED': 'ROJO',
    'YELLOW': 'AMARILLO',
    'PINK': 'ROSA',
    'BLUE': 'AZUL',
    'ORANGE': 'NARANJA',
    'GREEN': 'VERDE',
    'PURPLE': 'MORADO',
    'LIGHT': 'CLARO',
    'DARK': 'OSCURO',
    'NATURAL': 'BLANCO',
    # Variaciones ortográficas
    'JESSIKA': 'JESSICA',
    'TOFFE': 'TOFFEE',
    # O'Hara roses
    'OHARA PINK': 'OHARA ROSA',
    'OHARA WHITE': 'OHARA BLANCO',
    'OHARA RED': 'OHARA ROJO',
    "O'HARA PINK": 'OHARA ROSA',
    "O'HARA WHITE": 'OHARA BLANCO',
    "PINK O'HARA": 'OHARA ROSA',
    "WHITE O'HARA": 'OHARA BLANCO',
    'PINK OHARA': 'OHARA ROSA',
    'WHITE OHARA': 'OHARA BLANCO',
    # Spanish variety names
    'LIMONADA': 'LEMONADE',
}


def _normalize(s: str) -> str:
    """Normaliza: mayúsculas, sin tildes, sin espacios extra."""
    s = s.upper().strip()
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', s)


class ArticulosLoader:
    """Carga artículos del dump SQL y los indexa para búsqueda rápida."""

    def __init__(self):
        self.articulos: Dict[int, dict] = {}
        self.by_name: Dict[str, int] = {}
        self.rosas_ec: Dict[str, int] = {}
        self.rosas_col: Dict[str, int] = {}
        self.by_species: Dict[str, List] = {}
        self.brand_by_provider: Dict[int, str] = {}
        # Marcas secundarias: muchos proveedores tienen una marca principal en
        # rosas (ej. UMA) y una distinta en gypsophila/paniculata (ej. VIOLETA).
        # `brand_by_provider` guarda solo el top-1 para retrocompatibilidad;
        # `brands_by_provider` guarda todas las marcas que superan
        # BRAND_MIN_ARTICLES para que el matcher pueda reconocerlas todas
        # como "propias". Detectado al añadir GYPSOPHILA Uma en sesión 10o
        # (VIOLETA tiene 24 artículos de Uma pero el top-1 era UMA con 62).
        self.brands_by_provider: Dict[int, set] = {}
        # Índice `id_erp → articulo_dict`. El `id` autoincrement de MySQL
        # puede renumerarse al re-importar el dump desde phpMyAdmin
        # (sesión 10q). `id_erp` es el identificador del ERP externo y
        # es estable — lo usamos como clave durable para sinónimos y
        # golden, y al cargar el catálogo re-mapeamos id_erp → id actual.
        self.by_id_erp: Dict[str, dict] = {}
        # Índice `referencia → articulo_dict` (ej. F000636001). Clave
        # administrativa estable — sesión 10r hace que sea el otro
        # identificador válido de entrada (junto con id_erp). El `id`
        # autoincrement queda solo para uso interno (FKs de MySQL).
        self.by_referencia: Dict[str, dict] = {}
        # Índice variedad+talla → lista de artículos (para matching mejorado)
        self.by_variety_size: Dict[str, List[dict]] = defaultdict(list)
        # Índice variedad → lista de artículos (sin talla)
        self.by_variety: Dict[str, List[dict]] = defaultdict(list)
        self.loaded = False

    def load_from_sql(self, sql_path: str) -> int:
        """Carga artículos desde un dump SQL de INSERT statements.

        Si el dump no existe en disco, hace fallback automático a MySQL.
        El proyecto migró los artículos a la BD `traductor-verabuy` y el
        dump dejó de mantenerse, pero los callers (batch_process,
        procesar_pdf) siguen invocando este método con la ruta histórica.

        Args:
            sql_path: Ruta al fichero .sql.

        Returns:
            Número de artículos cargados.
        """
        from pathlib import Path
        if not Path(sql_path).exists():
            # NB: usamos logger.info (no warning) a propósito: el handler
            # `lastResort` de Python descarta INFO por defecto, así no se
            # imprime nada en stderr y la salida JSON de los CLI (procesar_pdf
            # / batch_process) queda limpia para el wrapper PHP.
            logger.info("Dump SQL no encontrado en %s; cargando desde MySQL", sql_path)
            return self.load_from_db()

        count = 0
        for sp in set(SPECIES_PREFIXES.values()):
            self.by_species[sp] = []

        with open(sql_path, 'r', encoding=FILE_ENCODING) as f:
            for raw in f:
                ln = raw.strip()
                if not ln.startswith('('):
                    continue
                ln = ln.rstrip(',;')
                try:
                    art = self._parse_row(ln)
                    if not art:
                        continue
                    self._reconstruct_truncated_name(art)
                    self._register_article(art)
                    count += 1
                except (ValueError, IndexError):
                    continue

        self._build_brand_index()
        self._build_variety_index()
        self.loaded = True
        logger.info("Artículos cargados: %d, rosas EC: %d, variedades: %d",
                     count, len(self.rosas_ec), len(self.by_variety))
        return count

    def load_from_db(self) -> int:
        """Carga artículos desde la tabla MySQL `articulos`.

        Lee también los campos estructurados (color, marca, variedad) para
        reconstruir el nombre canónico cuando está truncado en la BD
        (export histórico cortó en la Ñ de "TEÑIDA").

        Returns:
            Número de artículos cargados.
        """
        from src.db import get_connection

        count = 0
        for sp in set(SPECIES_PREFIXES.values()):
            self.by_species[sp] = []

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, id_proveedor, tamano, paquete, nombre, familia, "
                    "id_erp, referencia, color, marca, variedad "
                    "FROM articulos"
                )
                for row in cur.fetchall():
                    art = {
                        'id':           int(row[0] or 0),
                        'id_proveedor': int(row[1] or 0),
                        'tamano':       row[2] or '',
                        'paquete':      int(row[3] or 0),
                        'nombre':       row[4] or '',
                        'familia':      row[5] or '',
                        'id_erp':       row[6] or '',
                        'referencia':   row[7] or '',
                        'color':        row[8] or '',
                        'marca':        row[9] or '',
                        'variedad':     row[10] or '',
                    }
                    if not art['id']:
                        continue
                    self._reconstruct_truncated_name(art)
                    self._register_article(art)
                    count += 1
        finally:
            conn.close()

        self._build_brand_index()
        self._build_variety_index()
        self.loaded = True
        logger.info("Artículos cargados desde MySQL: %d, rosas EC: %d, variedades: %d",
                     count, len(self.rosas_ec), len(self.by_variety))
        return count

    @staticmethod
    def _reconstruct_truncated_name(art: dict) -> None:
        """Reconstruye `nombre` cuando el export phpMyAdmin lo dejó truncado.

        Histórico: muchos artículos tienen `nombre='PANICULATA XLENCE TE'`
        porque un export viejo cortó la Ñ de "TEÑIDA". Los campos
        estructurados (`color`, `marca`, `variedad`, `familia`, `tamano`,
        `paquete`) sí están intactos. Esta función detecta el truncado y
        genera el canónico "{familia} TEÑIDA {color} {tamano} {paquete}U
        {marca}" para que el matcher pueda distinguirlos.
        """
        nombre = (art.get('nombre') or '').strip()
        is_truncated = (
            nombre.upper().endswith(' TE') or
            nombre.upper().endswith(' TEÑ') or
            nombre.upper().endswith(' TEÑIDA') or
            nombre.upper() == 'PANICULATA XLENCE TE'
        )
        if not is_truncated:
            return
        familia = (art.get('familia') or '').strip().upper()
        color   = (art.get('color')   or '').strip().upper()
        tamano  = (art.get('tamano')  or '').strip().upper()
        marca   = (art.get('marca')   or '').strip().upper()
        paquete = art.get('paquete') or 0
        if not (familia and color):
            return
        bits = [familia, 'TEÑIDA', color]
        if tamano:
            bits.append(tamano)
        if paquete:
            bits.append(f'{paquete}U')
        if marca:
            bits.append(marca)
        art['nombre'] = ' '.join(bits)

    @staticmethod
    def _is_matchable(art: dict) -> bool:
        """True si el artículo entra al pool de candidatos del matcher.

        Política: solo artículos con `referencia` que empieza por `F*`
        son considerados — son los de flor de corte. Prefijos `A*`
        (artículos inactivos/viejos) y `P*` (plantas en maceta —
        ABELIA, etc.) se excluyen del matching aunque algunos tengan
        nombre de flor (P000... ALSTROEMERIA en maceta, A... ROSA
        deprecated). Los A/P siguen en `articulos` / `by_id_erp` /
        `by_referencia` para lookup directo desde la UI, pero no
        aparecen como candidatos en `match_line`.
        """
        ref = (art.get('referencia') or '').strip().upper()
        return ref.startswith('F')

    def _register_article(self, art: dict) -> None:
        """Registra un artículo en los índices internos (compartido SQL/DB)."""
        self.articulos[art['id']] = art
        # Índice por id_erp (estable entre reimports). Si el dump SQL no
        # trae la columna id_erp queda vacío y el índice no se usa.
        erp = (art.get('id_erp') or '').strip()
        if erp:
            self.by_id_erp[erp] = art
        # Índice por referencia (F...) — clave administrativa estable.
        ref = (art.get('referencia') or '').strip().upper()
        if ref:
            self.by_referencia[ref] = art
        # Índices de matching (by_name/by_species) solo para F* — el
        # resto queda accesible por id_erp/referencia desde la UI pero
        # nunca aparece como candidato del matcher.
        if not self._is_matchable(art):
            return
        nombre = art['nombre']
        if nombre:
            self.by_name[nombre.upper()] = art['id']
            clean = strip_provider_suffix(nombre.upper())
            if clean != nombre.upper():
                self.by_name[clean] = art['id']
            self._index_species(art)

    # --- Búsquedas ---

    def find_by_erp_or_ref(self, q: str) -> Optional[dict]:
        """Resuelve un artículo por `id_erp` o `referencia` (sesión 10r).

        Política: **no aceptar nunca el `id` autoincrement como input**.
        El `id` local se renumera al reimportar el catálogo y causa
        asignaciones equivocadas (3037 local ≠ 3037 id_erp). El usuario
        siempre teclea id_erp (típicamente numérico) o referencia
        (F000...). Centralizar aquí garantiza que todas las vías de
        asignación (CLI golden_review, web API, UI) compartan criterio.
        """
        if not q:
            return None
        q = q.strip()
        by_erp = self.by_id_erp.get(q)
        if by_erp:
            return by_erp
        by_ref = self.by_referencia.get(q.upper())
        if by_ref:
            return by_ref
        return None

    def find_by_name(self, name: str) -> Optional[dict]:
        """Busca un artículo por nombre exacto."""
        name = name.upper().strip()
        if name in self.by_name:
            return self.articulos[self.by_name[name]]
        no_orig = re.sub(r'^(ROSA)\s+(EC|COL)\s+', r'\1 ', name)
        if no_orig != name and no_orig in self.by_name:
            return self.articulos[self.by_name[no_orig]]
        return None

    def find_branded(self, name: str, provider_id: int, provider_key: str = '') -> Optional[dict]:
        """Busca artículo con el sufijo de marca del proveedor.

        Args:
            name: Nombre esperado genérico (ej: 'ROSA EC MONDIAL 50CM 25U').
            provider_id: ID del proveedor en VeraBuy.
            provider_key: Clave del proveedor en PROVIDERS.

        Returns:
            Artículo con marca si existe (ej: 'ROSA MONDIAL 50CM 25U CERES'), None si no.
        """
        brands = set()
        # Marca del índice SQL (por id_proveedor del artículo)
        b = self.brand_by_provider.get(provider_id)
        if b:
            brands.add(b)
        # Marca de la clave del proveedor en PROVIDERS
        if provider_key:
            brands.add(provider_key.upper())
        # Buscar también marcas de otros providers con el mismo fmt (aliases)
        # Ej: cantiza(2222) y valtho(435) comparten fmt='cantiza'
        from src.config import PROVIDERS
        for pkey, pdata in PROVIDERS.items():
            if pdata.get('id') == provider_id:
                brands.add(pkey.upper())
                # Buscar marcas de otros providers con mismo fmt
                fmt = pdata.get('fmt', '')
                for pkey2, pdata2 in PROVIDERS.items():
                    if pdata2.get('fmt') == fmt and pdata2.get('id') != provider_id:
                        b2 = self.brand_by_provider.get(pdata2['id'])
                        if b2:
                            brands.add(b2)
                break
        if not brands:
            return None
        name = name.upper().strip()
        base = re.sub(r'^(ROSA)\s+(EC|COL)\s+', r'\1 ', name)
        for brand in brands:
            branded = f"{base} {brand}"
            if branded in self.by_name:
                return self.articulos[self.by_name[branded]]
            branded2 = f"{name} {brand}"
            if branded2 in self.by_name:
                return self.articulos[self.by_name[branded2]]
        return None

    def find_rose_ec(self, variety: str, size: int, spb: int) -> Optional[dict]:
        """Busca una rosa EC por variedad, talla y tallos por ramo."""
        key = f"{variety.upper()} {size}CM {spb}U"
        if key in self.rosas_ec:
            return self.articulos[self.rosas_ec[key]]
        for k, aid in self.rosas_ec.items():
            if k.startswith(variety.upper()) and f"{size}CM" in k and f"{spb}U" in k:
                return self.articulos[aid]
        return None

    def find_rose_col(self, variety: str, size: int, spb: int, grade: str = '') -> Optional[dict]:
        """Busca una rosa COL por variedad, talla, SPB y grado."""
        targets = [
            f"{grade.upper()} {variety.upper()} {size}CM {spb}U",
            f"{variety.upper()} {size}CM {spb}U",
        ]
        for t in targets:
            if t.strip() in self.rosas_col:
                return self.articulos[self.rosas_col[t.strip()]]
        return None

    def fuzzy_search(self, line: InvoiceLine, threshold: float = 0.4) -> list:
        """Búsqueda fuzzy por similitud dentro del pool de la especie.

        Optimizaciones:
        - Cache por (sp_key, query, threshold) — una factura repite variedades.
        - Prefiltro con ``real_quick_ratio()`` (O(1)) y ``quick_ratio()``
          (O(n+m)) antes del ``ratio()`` completo (O(n·m)).
        """
        sp_map = {
            'ROSES': 'ROSES_EC', 'ROSES_EC': 'ROSES_EC', 'ROSES_COL': 'ROSES_COL',
            'CARNATIONS': 'CARNATIONS', 'HYDRANGEAS': 'HYDRANGEAS',
            'ALSTROEMERIA': 'ALSTROEMERIA', 'GYPSOPHILA': 'GYPSOPHILA',
            'CHRYSANTHEMUM': 'CHRYSANTHEMUM',
        }
        if line.origin == 'COL' and line.species == 'ROSES':
            sp_key = 'ROSES_COL'
        else:
            sp_key = sp_map.get(line.species, 'ROSES_EC')
        pool = self.by_species.get(sp_key, [])
        if not pool:
            return []
        query = self._query_key(line)
        # Cache hit?
        cache = getattr(self, '_fuzzy_cache', None)
        if cache is None:
            cache = {}
            self._fuzzy_cache = cache
        ckey = (sp_key, query, threshold)
        if ckey in cache:
            return cache[ckey]
        cands = []
        sm = SequenceMatcher(None, query, '', autojunk=False)
        for rest, aid in pool:
            sm.set_seq2(rest)
            # real_quick_ratio es O(1); quick_ratio O(n+m). Ambos son
            # cotas superiores; si caen por debajo del threshold, ratio()
            # tampoco pasará.
            if sm.real_quick_ratio() < threshold:
                continue
            if sm.quick_ratio() < threshold:
                continue
            r = sm.ratio()
            if r >= threshold:
                cands.append({
                    'id': aid, 'nombre': self.articulos[aid]['nombre'],
                    'similitud': round(r * 100, 1), 'key': rest,
                })
        result = sorted(cands, key=lambda x: x['similitud'], reverse=True)[:5]
        cache[ckey] = result
        return result

    # --- Indexación interna ---

    def _index_species(self, art: dict) -> None:
        nombre = art['nombre'].upper()
        for prefix, sp in SPECIES_PREFIXES.items():
            if nombre.startswith(prefix):
                rest = strip_provider_suffix(nombre[len(prefix):].strip())
                self.by_species[sp].append((rest, art['id']))
                if sp == 'ROSES_EC':
                    rm = re.match(r'(.+?)\s+(\d+)CM\s+(\d+)U', rest)
                    if rm:
                        key = f"{rm.group(1).strip()} {rm.group(2)}CM {rm.group(3)}U"
                        self.rosas_ec[key] = art['id']
                elif sp == 'ROSES_COL':
                    rm = re.match(r'(?:([A-Z0-9]+)\s+)?(.+?)\s+(\d+)CM\s+(\d+)U', rest)
                    if rm:
                        self.rosas_col[rest] = art['id']
                break
        else:
            clean = strip_provider_suffix(nombre)
            if re.match(r'ROSA\s+[A-Z]', clean):
                rest = clean[5:].strip()
                self.by_species['ROSES_EC'].append((rest, art['id']))
                self.by_species['ROSES_COL'].append((rest, art['id']))
                rm = re.match(r'(.+?)\s+(\d+)CM\s+(\d+)U', rest)
                if rm:
                    key = f"{rm.group(1).strip()} {rm.group(2)}CM {rm.group(3)}U"
                    self.rosas_ec[key] = art['id']
                    self.rosas_col[key] = art['id']

    def _build_brand_index(self) -> None:
        """Calcula el sufijo de marca más frecuente por proveedor."""
        prov_suffixes: Dict[int, list] = {}
        for a in self.articulos.values():
            # Solo F* contribuyen a la detección de marca. Los A*/P* no
            # son candidatos del matcher y no deben sesgar los sufijos
            # propios del proveedor.
            if not self._is_matchable(a):
                continue
            pid = a.get('id_proveedor', 0)
            if not pid:
                continue
            parts = a['nombre'].upper().rsplit(None, 1)
            if (len(parts) == 2 and len(parts[1]) > 2
                    and parts[1].isalpha() and parts[1] not in BRAND_IGNORE_SUFFIXES):
                prov_suffixes.setdefault(pid, []).append(parts[1])
        for pid, suffixes in prov_suffixes.items():
            counts = Counter(suffixes)
            top = counts.most_common(1)[0]
            if top[1] >= BRAND_MIN_ARTICLES:
                self.brand_by_provider[pid] = top[0]
            # Registrar TODAS las marcas que superan el umbral (no solo la
            # principal). Un proveedor puede tener líneas distintas con
            # marcas distintas (Uma: ROSAS→UMA, PANICULATA→VIOLETA) y el
            # matcher debe reconocer ambas como propias.
            all_brands = {b for b, n in counts.items() if n >= BRAND_MIN_ARTICLES}
            if all_brands:
                self.brands_by_provider[pid] = all_brands

    def _build_variety_index(self) -> None:
        """Construye índices por variedad y variedad+talla para búsqueda flexible."""
        rose_re = re.compile(
            r'^ROSA\s+(?:EC\s+|COL\s+)?(.+?)\s+(\d+)CM\s+(\d+)U(?:\s+(.+))?$'
        )
        paniculata_re = re.compile(
            r'^PANICULATA\s+(.+?)(?:\s+\d+GR\s+\d+U)?(?:\s+([A-Z][A-Z ]+))?$'
        )
        hydrangea_re = re.compile(
            r'^HYDRANGEA\s+(.+?)\s+(\d+)CM\s+(\d+)U(?:\s+(.+))?$'
        )
        clavel_re = re.compile(
            r'^(?:MINI\s+)?CLAVEL\s+(?:COL\s+|EC\s+)?(?:SPRAY\s+)?(?:FANCY\s+)?(.+?)\s+(\d+)CM\s+(\d+)U(?:\s+(.+))?$'
        )
        crisantemo_re = re.compile(
            r'^CRISANTEMO\s+(.+?)\s+(\d+)CM\s+(\d+)U(?:\s+(.+))?$'
        )
        alstro_re = re.compile(
            r'^ALSTROMERIA\s+(?:EC\s+|COL\s+)?(.+?)\s+(\d+)CM\s+(\d+)U(?:\s+(.+))?$'
        )

        for art in self.articulos.values():
            # Solo F* entran al índice de variedad (política sesión 11f).
            if not self._is_matchable(art):
                continue
            nombre = _normalize(art['nombre'])
            if not nombre:
                continue

            variedad = None
            talla = 0
            marca = ''

            m = rose_re.match(nombre)
            if m:
                variedad = m.group(1).strip()
                talla = int(m.group(2))
                marca = (m.group(4) or '').strip()
            else:
                m = paniculata_re.match(nombre)
                if m:
                    variedad = m.group(1).strip()
                    variedad = re.sub(r'\s+\d+GR$', '', variedad)
                    marca = (m.group(2) or '').strip()
                    # Also index with GYPSOPHILA prefix
                    self.by_variety[f"GYPSOPHILA {variedad}"].append(art)
                else:
                    m = hydrangea_re.match(nombre)
                    if m:
                        variedad = m.group(1).strip()
                        talla = int(m.group(2))
                        marca = (m.group(4) or '').strip()
                    else:
                        m = clavel_re.match(nombre)
                        if m:
                            variedad = m.group(1).strip()
                            talla = int(m.group(2))
                            marca = (m.group(4) or '').strip()
                        else:
                            m = crisantemo_re.match(nombre)
                            if m:
                                variedad = m.group(1).strip()
                                talla = int(m.group(2))
                                marca = (m.group(4) or '').strip()
                            else:
                                m = alstro_re.match(nombre)
                                if m:
                                    variedad = m.group(1).strip()
                                    talla = int(m.group(2))
                                    marca = (m.group(4) or '').strip()

            if variedad:
                self.by_variety[variedad].append(art)
                if talla:
                    self.by_variety_size[f"{variedad}|{talla}"].append(art)

    # --- Búsqueda mejorada (proceso manual replicado) ---

    def search_variety(self, variety: str, size: int = 0) -> List[dict]:
        """Busca artículos por variedad, intentando traducciones si no hay match.

        Args:
            variety: Variedad tal como viene de la factura.
            size: Talla en CM (0 = sin filtro de talla).

        Returns:
            Lista de artículos candidatos.
        """
        variantes = self._translate_variety(variety)
        results = []
        for var in variantes:
            var_n = _normalize(var)
            if size:
                key = f"{var_n}|{size}"
                results.extend(self.by_variety_size.get(key, []))
            else:
                results.extend(self.by_variety.get(var_n, []))
        # Deduplicar manteniendo orden
        seen = set()
        unique = []
        for r in results:
            if r['id'] not in seen:
                seen.add(r['id'])
                unique.append(r)
        return unique

    def search_with_priority(self, variety: str, size: int,
                              provider_id: int, provider_key: str = '') -> Optional[dict]:
        """Búsqueda con el orden de prioridad del proceso manual:

        1. Variedad + talla + marca/farm del proveedor en nombre
        2. Variedad + talla + campo proveedor (id_proveedor)
        3. Variedad + talla + genérico (sin marca, o EC/COL)
        4. Variedad genérica sin talla exacta + marca
        5. Variedad genérica sin talla + proveedor
        6. Variedad genérica (cualquier artículo de esa variedad)
        7. None (sin match)

        Returns:
            Tuple (articulo_dict, confidence, method) or (None, '', '')
        """
        brands = self._get_brands(provider_id, provider_key)

        # Candidatos con talla exacta
        con_talla = self.search_variety(variety, size) if size else []
        # Candidatos sin filtro de talla (fallback)
        sin_talla = self.search_variety(variety, 0)

        # --- Paso 3: Variedad + talla + marca en nombre ---
        if brands and con_talla:
            for art in con_talla:
                if self._has_brand(art, brands):
                    return art, 'ALTA', 'variedad+talla+marca'

        # --- Paso 4: Variedad + talla + campo proveedor ---
        if provider_id and con_talla:
            for art in con_talla:
                if art.get('id_proveedor') == provider_id:
                    return art, 'MEDIA', 'variedad+talla+proveedor_id'

        # --- Paso 5: Variedad + talla + genérico ---
        if con_talla:
            for art in con_talla:
                if self._is_generic(art):
                    return art, 'BAJA', 'variedad+talla+generico'

        # --- Variedad sin talla + marca ---
        if brands and sin_talla:
            best = self._closest_size(sin_talla, size, brands)
            if best:
                return best, 'ALTA', 'variedad+marca(sin_talla_exacta)'

        # --- Variedad sin talla + proveedor ---
        if provider_id and sin_talla:
            for art in sin_talla:
                if art.get('id_proveedor') == provider_id:
                    return art, 'MEDIA', 'variedad+proveedor_id(sin_talla)'

        # --- Paso 6: Artículo genérico de esa variedad ---
        if sin_talla:
            # Preferir genéricos, luego cualquiera
            generics = [a for a in sin_talla if self._is_generic(a)]
            if generics:
                best = self._closest_size(generics, size)
                if best:
                    return best, 'BAJA', 'variedad+generico(sin_talla)'
            # Cualquier artículo de la variedad
            best = self._closest_size(sin_talla, size)
            if best:
                return best, 'MUY_BAJA', 'variedad(cualquier)'

        # --- Paso 7: Sin match ---
        return None, '', 'sin_match'

    def _translate_variety(self, variety: str) -> List[str]:
        """Genera variantes traducidas inglés→español de una variedad."""
        v = _normalize(variety)
        variantes = [v]

        # Quitar prefijo de especie si lo tiene (GYPSOPHILA, GARDEN ROSE, etc.)
        stripped = v
        for prefix in ('GYPSOPHILA ', 'GARDEN ROSE ', 'PANICULATA '):
            if v.startswith(prefix):
                stripped = v[len(prefix):]
                if stripped not in variantes:
                    variantes.append(stripped)
                break

        # Traducciones completas (primero las más largas)
        bases = [v, stripped] if stripped != v else [v]
        for base in bases:
            for eng, esp in sorted(VARIETY_TRANSLATIONS.items(), key=lambda x: -len(x[0])):
                if eng in base:
                    translated = base.replace(eng, esp)
                    if translated and translated not in variantes:
                        variantes.append(translated)

        # Traducción palabra por palabra
        for base in bases:
            words = base.split()
            tw = [VARIETY_TRANSLATIONS.get(w, w) for w in words]
            word_t = ' '.join(tw)
            if word_t not in variantes:
                variantes.append(word_t)

        # Variantes con prefijo GYPSOPHILA → también sin él y viceversa
        extra = []
        for vk in list(variantes):
            if vk.startswith('GYPSOPHILA '):
                nopfx = vk[len('GYPSOPHILA '):]
                if nopfx not in variantes:
                    extra.append(nopfx)
            # Add GYPSOPHILA prefix variant for paniculata searches
            gypso = f"GYPSOPHILA {vk}"
            if gypso not in variantes:
                extra.append(gypso)
        variantes.extend(extra)

        # Fuzzy: si ninguna variante está en el índice, buscar parecida
        if not any(vk in self.by_variety for vk in variantes):
            best_ratio, best_key = 0, None
            for known in self.by_variety:
                if len(known) < 4:
                    continue
                for vk in variantes[:3]:
                    if abs(len(known) - len(vk)) > 3:
                        continue
                    r = SequenceMatcher(None, vk, known).ratio()
                    if r > best_ratio and r >= 0.80:
                        best_ratio = r
                        best_key = known
            if best_key:
                variantes.append(best_key)

        return variantes

    def _get_brands(self, provider_id: int, provider_key: str = '') -> List[str]:
        """Obtiene marcas posibles para un proveedor.

        NO mezcla marcas de proveedores que comparten fmt (formato de parser),
        ya que fmt indica formato de factura, no marca comercial.
        """
        brands = []
        # Marca detectada del índice SQL (sufijo más frecuente)
        b = self.brand_by_provider.get(provider_id)
        if b:
            brands.append(b)
        # Marcas secundarias autodetectadas (Uma: UMA + VIOLETA).
        extra_auto = self.brands_by_provider.get(provider_id)
        if extra_auto:
            brands.extend(extra_auto)
        # Clave del proveedor en PROVIDERS como posible marca
        if provider_key:
            brands.append(provider_key.upper())
        # Buscar la clave del proveedor por id + registrar catalog_brands
        # manuales (marcas multi-palabra que el autodetector no capta o
        # cuando el id config no coincide con id_proveedor del catálogo).
        from src.config import PROVIDERS
        for pkey, pdata in PROVIDERS.items():
            if pdata.get('id') == provider_id:
                brands.append(pkey.upper())
                for b in pdata.get('catalog_brands') or []:
                    brands.append(b)
                break
        return list(dict.fromkeys(_normalize(b) for b in brands if b))

    def _has_brand(self, art: dict, brands: List[str]) -> bool:
        """Comprueba si un artículo tiene alguna de las marcas en su nombre."""
        nombre = _normalize(art['nombre'])
        # Extraer la(s) última(s) palabra(s) del nombre (lo que va después de NNU)
        tail_m = re.search(r'\d+U\s+(.+)$', nombre)
        tail = tail_m.group(1).strip() if tail_m else ''
        for brand in brands:
            # Match exacto del sufijo
            if tail == brand:
                return True
            # Match parcial: "ALEGRIA" coincide con "LA ALEGRIA"
            if tail and brand in tail:
                return True
            # Fallback: buscar en todo el nombre
            if nombre.endswith(f" {brand}"):
                return True
        return False

    def _is_generic(self, art: dict) -> bool:
        """Artículo genérico: termina en \\d+U (sin marca) o tiene EC/COL."""
        nombre = _normalize(art['nombre'])
        # Termina en NNu sin marca
        if re.search(r'\d+U$', nombre):
            return True
        return False

    def _closest_size(self, arts: List[dict], target_size: int,
                       brands: List[str] = None) -> Optional[dict]:
        """De una lista de artículos, elige el de talla más cercana (con marca si se da)."""
        if brands:
            arts = [a for a in arts if self._has_brand(a, brands)]
        if not arts:
            return None
        if not target_size:
            return arts[0]

        def size_dist(a):
            m = re.search(r'(\d+)CM', a['nombre'].upper())
            return abs(int(m.group(1)) - target_size) if m else 999
        return min(arts, key=size_dist)

    def _query_key(self, line: InvoiceLine) -> str:
        v = line.variety.upper()
        s = line.size
        u = line.stems_per_bunch
        g = line.grade.upper()
        if line.species in ('ROSES', 'ROSES_EC', 'ROSES_COL'):
            return f"{v} {s}CM {u}U" if s and u else v
        if line.species == 'CARNATIONS':
            color = translate_carnation_color(v)
            sz = s if s else DEFAULT_SIZE_CARNATIONS
            if getattr(line, 'provider_key', '') == 'golden':
                return f"FANCY {color} {sz}CM {u}U"
            base = f"COL {g} {color} {sz}CM {u}U" if g else f"COL {color} {sz}CM {u}U"
            return base.replace('  ', ' ').strip()
        if line.species in ('HYDRANGEAS', 'ALSTROEMERIA', 'CHRYSANTHEMUM'):
            return f"{v} {s}CM {u}U" if s and u else v
        if line.species == 'GYPSOPHILA':
            return v
        return v

    @staticmethod
    def _parse_row(line: str) -> Optional[dict]:
        if not line.startswith('('):
            return None
        inner = line[1:].rstrip(')')
        flds = ArticulosLoader._split_sql(inner)
        if len(flds) < 10:
            return None

        def cs(v: str) -> str:
            v = v.strip()
            if v == 'NULL':
                return ''
            if v.startswith("'") and v.endswith("'"):
                return v[1:-1].replace("\\'", "'")
            return v

        def ci(v: str) -> int:
            v = v.strip()
            return int(v) if v.replace('-', '').isdigit() else 0

        return {
            'id': ci(flds[0]), 'nombre': cs(flds[8]), 'familia': cs(flds[9]),
            'tamano': cs(flds[5]), 'paquete': ci(flds[7]), 'id_proveedor': ci(flds[3]),
            'id_erp': cs(flds[1]),
            'referencia': cs(flds[10]) if len(flds) > 10 else '',
            'color':    cs(flds[4])  if len(flds) >  4 else '',
            'marca':    cs(flds[6])  if len(flds) >  6 else '',
            'variedad': cs(flds[14]) if len(flds) > 14 else '',
        }

    @staticmethod
    def _split_sql(s: str) -> list:
        """Divide una fila SQL respetando strings entre comillas simples."""
        parts = []
        cur = ''
        inq = False
        esc = False
        for ch in s:
            if esc:
                cur += ch
                esc = False
                continue
            if ch == '\\':
                cur += ch
                esc = True
                continue
            if ch == "'" and not inq:
                inq = True
                cur += ch
                continue
            if ch == "'" and inq:
                inq = False
                cur += ch
                continue
            if ch == ',' and not inq:
                parts.append(cur)
                cur = ''
                continue
            cur += ch
        if cur:
            parts.append(cur)
        return parts
