"""Configuración centralizada del proyecto VeraBuy Traductor.

Todas las constantes, rutas, registros de proveedores y mapeos de color
se definen aquí. Ningún otro módulo debe contener paths hardcodeados
ni magic numbers.
"""
from __future__ import annotations

import re
import sys
import os
from pathlib import Path


# --- Rutas base ---
# BASE_DIR apunta a la raíz del proyecto (el padre de src/)
BASE_DIR    = Path(__file__).resolve().parent.parent
DATA_DIR    = BASE_DIR
PDF_DIR     = BASE_DIR / 'facturas'
EXPORT_DIR  = BASE_DIR / 'exportar'
SQL_FILE    = DATA_DIR / 'articulos (3).sql'
SYNS_FILE   = DATA_DIR / 'sinonimos_universal.json'
HIST_FILE   = DATA_DIR / 'historial_universal.json'

# --- Encoding por defecto para todos los ficheros ---
FILE_ENCODING = 'utf-8'

# --- Umbrales de matching ---
FUZZY_THRESHOLD_AUTO  = 0.90   # Umbral para auto-fuzzy en el Matcher
FUZZY_THRESHOLD_RESOLVE = 0.40 # Umbral para mostrar candidatos en resolución manual

# --- Valores por defecto de flores ---
DEFAULT_SPB_ROSES       = 25   # Tallos por ramo por defecto para rosas
DEFAULT_SPB_CARNATIONS  = 20   # Tallos por ramo por defecto para claveles
DEFAULT_SPB_MINI_CARN   = 10   # Tallos por ramo por defecto para mini claveles
DEFAULT_SIZE_CARNATIONS = 70   # Talla por defecto (cm) si la factura no la trae
DEFAULT_SIZE_HYDRANGEAS = 60   # Talla por defecto para hortensias
DEFAULT_SPB_HYDRANGEAS  = 1    # SPB por defecto para hortensias (siempre 1U en VeraBuy)

# --- Especies reconocidas ---
SPECIES_ROSES       = 'ROSES'
SPECIES_CARNATIONS  = 'CARNATIONS'
SPECIES_HYDRANGEAS  = 'HYDRANGEAS'
SPECIES_ALSTROEMERIA = 'ALSTROEMERIA'
SPECIES_GYPSOPHILA  = 'GYPSOPHILA'
SPECIES_CHRYSANTHEMUM = 'CHRYSANTHEMUM'
SPECIES_OTHER       = 'OTHER'

# --- Prefijos de especie para indexación de artículos ---
SPECIES_PREFIXES = {
    'ROSA EC':      'ROSES_EC',
    'ROSA COL':     'ROSES_COL',
    'MINI CLAVEL':  'CARNATIONS',
    'CLAVEL':       'CARNATIONS',
    'HYDRANGEA':    'HYDRANGEAS',
    'ALSTROMERIA':  'ALSTROEMERIA',
    'ALSTROEMERIA': 'ALSTROEMERIA',
    'PANICULATA':   'GYPSOPHILA',
    'CRISANTEMO':   'CHRYSANTHEMUM',
    'DIANTHUS':     'OTHER',
}

# --- Mapa de colores: inglés → español (claveles) ---
CARNATION_COLOR_MAP = {
    'WHITE': 'BLANCO', 'BLANCA': 'BLANCO', 'RED': 'ROJO', 'ROJA': 'ROJO',
    'PINK': 'ROSA', 'ROSE': 'ROSA', 'YELLOW': 'AMARILLO', 'AMARILLA': 'AMARILLO',
    'MIX': 'MIXTO', 'MIXED': 'MIXTO', 'ORANGE': 'NARANJA', 'PURPLE': 'MORADO',
    'VIOLET': 'VIOLETA', 'LILAC': 'LILA', 'PEACH': 'MELOCOTON', 'SALMON': 'SALMON',
    'GREEN': 'VERDE', 'NOVELTY': 'NOVEDADES', 'NOVELTIES': 'NOVEDADES',
    'BICOLOR': 'BICOLOR', 'DARK': 'OSCURO', 'LIGHT': 'CLARO',
}

# --- Sufijos de marca a ignorar al construir el brand index ---
BRAND_IGNORE_SUFFIXES = {
    'PREMIUM', 'FANCY', 'SELECT', 'STANDARD', 'BICOLOR', 'MIX', 'ROSES', 'VERDE',
    'ROJO', 'BLANCO', 'ROSA', 'NARANJA', 'PINK', 'MEDIUM', 'NATURAL', 'GRANEL',
    'FLOWERS', 'GARDENS', 'DIAS', 'DIRECT', 'CONT', 'INCH', 'AÑOS', 'LED', 'COPA',
}

# Mínimo de artículos con un sufijo para considerarlo marca de proveedor
BRAND_MIN_ARTICLES = 5

# --- Registro de proveedores ---
# id=0 → proveedor aún no dado de alta en la BD; actualiza cuando lo tengas
PROVIDERS = {
    'cantiza'    : {'id': 2222,  'name': 'Cantiza Flores',         'fmt': 'cantiza',      'patterns': ['cantizafloral.com', 'CANTIZA FLORES']},
    'valtho'     : {'id': 435,   'name': 'Valthomig',              'fmt': 'cantiza',      'patterns': ['VALTHOMIG']},
    'agrivaldani': {'id': 2228,  'name': 'Agrivaldani',            'fmt': 'agrivaldani',  'patterns': ['AGRIVALDANI']},
    'luxus'      : {'id': 1429,  'name': 'Luxus Blumen',           'fmt': 'agrivaldani',  'patterns': ['LUXUSBLUMEN', 'LUXUS BLUMEN']},
    'brissas'    : {'id': 90001, 'name': 'Brissas',                'fmt': 'brissas',      'patterns': ['RUC: 1716780331001', 'BRISSAS']},
    'alegria'    : {'id': 8870,  'name': 'La Alegria Farm',        'fmt': 'alegria',      'patterns': ['LA ALEGRIAFARM', 'rosasdelaalegria']},
    'olimpo'     : {'id': 430,   'name': 'Olimpo Flowers',         'fmt': 'alegria',      'patterns': ['OLIMPO FLOWERS']},
    'fairis'     : {'id': 90013, 'name': 'Fairis Garden',          'fmt': 'alegria',      'patterns': ['FAIRIS GARDEN', 'fairisgarden']},
    'aluna'      : {'id': 3375,  'name': 'Inversiones del Neusa',  'fmt': 'aluna',        'patterns': ['INVERSIONES DEL NEUSA', 'alunaflowers']},
    'daflor'     : {'id': 9750,  'name': 'Daflor',                 'fmt': 'daflor',       'patterns': ['DAFLOR S.A', 'Daflor SAS', 'diagudelo@daflor', 'maqudelo', 'NIT:860.522.815']},
    'turflor'    : {'id': 306,   'name': 'Turflor',                'fmt': 'turflor',      'patterns': ['TURFLOR']},
    'eqr'        : {'id': 2229,  'name': 'EQR USA',                'fmt': 'eqr',          'patterns': ['EQUATOROSES', 'EQR USA']},
    'bosque': {'id': 90005,     'name': 'Bosque Flowers',         'fmt': 'bosque',       'patterns': ['BOSQUEFLOWERS', 'bosqueflowers']},
    'colibri'    : {'id': 313,   'name': 'Colibri Flowers',        'fmt': 'colibri',      'patterns': ['COLIBRI FLOWERS']},
    'golden'     : {'id': 310,   'name': 'Benchmark Growers',      'fmt': 'golden',       'patterns': ['Benchmark Growers', 'benchmarkgrowers']},
    'latin'      : {'id': 6323,  'name': 'Latin Flowers',          'fmt': 'latin',        'patterns': ['LATIN FLOWERS', 'latinflowers.com.co']},
    'multiflora' : {'id': 8342,  'name': 'Multiflora',             'fmt': 'multiflora',   'patterns': ['MULTIFLORA CORPORATION', 'multiflorasales', 'Multiflora']},
    'florsani'   : {'id': 419,   'name': 'Florsani',               'fmt': 'florsani',     'patterns': ['FLORSANI', 'FLORICOLA SAN ISIDRO', '1792059232001']},
    'maxi'       : {'id': 281,   'name': 'Maxiflores',             'fmt': 'maxi',         'patterns': ['MAXIFLORES', 'C.I. MAXIFLORES']},
    'mystic'     : {'id': 442,   'name': 'Mystic Flowers',         'fmt': 'mystic',       'patterns': ['MYSTICFLOWERS']},
    'fiorentina' : {'id': 6916,  'name': 'Fiorentina Flowers',     'fmt': 'mystic',       'patterns': ['FIORENTINA FLOWERS']},
    'stampsy'    : {'id': 2220,  'name': 'Stampsybox',             'fmt': 'mystic',       'patterns': ['STAMPSYBOX']},
    'prestige'   : {'id': 11391, 'name': 'Prestige Roses',         'fmt': 'prestige',     'patterns': ['PRESTIGE ROSES', 'prestigeroses.com', 'ventas@prestigeroses', '900,149,336', '900.149.336']},
    'rosely': {'id': 90034,     'name': 'Rosely Flowers',         'fmt': 'rosely',       'patterns': ['ROSELY FLOWERS', 'roselyflowers']},
    'condor'     : {'id': 11915, 'name': 'Condor Andino',          'fmt': 'condor',       'patterns': ['CONDOR ANDINO']},
    'malima'     : {'id': 7563,  'name': 'Starflowers (Malima)',    'fmt': 'malima',       'patterns': ['STARFLOWERS', 'MALIMA EUROPA']},
    'monterosa'  : {'id': 1434,  'name': 'Monterosas Farms',       'fmt': 'monterosa',    'patterns': ['MONTEROSASLIMITADA', 'MONTEROSAS']},
    'secore'     : {'id': 7338,  'name': 'Secore Floral',          'fmt': 'secore',       'patterns': ['Sécore Floral', 'SECORE FLORAL', 'Score Floral']},
    'tessa'      : {'id': 13001, 'name': 'Tessa Corp',             'fmt': 'tessa',        'patterns': ['TESSA CORP', 'tessacorporation']},
    'uma'        : {'id': 440,   'name': 'Uma Flowers',            'fmt': 'uma',          'patterns': ['UMAFLOWERS', 'umaflowers']},
    'valleverde' : {'id': 2219,  'name': 'Valle Verde Farms',      'fmt': 'valleverde',   'patterns': ['VALLEVERDE FARMS', 'VALLE VERDE FARMS', 'valleverderoses', '1792027691001']},
    'verdesestacion': {'id': 11748, 'name': 'Verdes La Estacion / Ponderosa', 'fmt': 'verdesestacion', 'patterns': ['VERDES LA ESTACION', '900.408.822', 'PONDEROSA FLOWERS', 'PONDEROSA FLOWERS S.A.S', 'NIT 900.428.540', '900.428.540']},
    'sayonara'   : {'id': 2166,  'name': 'Sayonara',               'fmt': 'sayonara',     'patterns': ['CULTIVOS SAYONARA', 'SAYONARA']},
    'life'       : {'id': 4471,  'name': 'Life Flowers',           'fmt': 'life',         'patterns': ['LIFEFLOWERS', 'lifeflowersecuador']},
    'latina'     : {'id': 12990, 'name': 'Floricola Latinafarms',  'fmt': 'alegria',      'patterns': ['FLORICOLA LATINAFARMS', 'LATINA']},
    'ceres': {'id': 90007,     'name': 'Ceresfarms',              'fmt': 'alegria',      'patterns': ['CERESFARMS']},
    'floraroma': {'id': 90014,     'name': 'Floraroma',               'fmt': 'floraroma',    'patterns': ['FLORAROMA']},
    'garda': {'id': 90017,     'name': 'GardaExport',             'fmt': 'garda',        'patterns': ['GARDAEXPORT']},
    'utopia': {'id': 90042,     'name': 'Utopia Farms',            'fmt': 'utopia',       'patterns': ['UTOPIA FARMS']},
    'ecoflor': {'id': 90012,     'name': 'Ecoflor Groupchile',      'fmt': 'mystic',       'patterns': ['ECOFLOR GROUPCHILE']},
    'florifrut': {'id': 90015,     'name': 'Flores y Frutas Florifrut','fmt': 'mystic',       'patterns': ['FLORIFRUT']},
    'solpacific': {'id': 90036,     'name': 'Sol Pacific',              'fmt': 'valleverde',   'patterns': ['solpacificecuador', 'SOLPACIFIC']},
    'rosaleda'   : {'id': 2226,  'name': 'Floricola La Rosaleda',    'fmt': 'rosaleda',     'patterns': ['FLORICOLA LA ROSALEDA', 'FLORICOLALAROSALEDA', 'LA ROSALEDA']},
    'circasia': {'id': 90008,     'name': 'Agricola Circasia',        'fmt': 'colfarm',      'patterns': ['AGRICOLA CIRCASIA']},
    'vuelven': {'id': 90044,     'name': 'Vuelven',                  'fmt': 'colfarm',      'patterns': ['VUELVEN S.A']},
    'milonga': {'id': 90026,     'name': 'Flores Milonga',           'fmt': 'colfarm',      'patterns': ['FLORES MILONGA']},
    'native': {'id': 90029,     'name': 'Calinama (Native)',        'fmt': 'native',       'patterns': ['CALINAMA CAPITAL']},
    'unique': {'id': 90041,     'name': 'Unique Flowers',           'fmt': 'unique',       'patterns': ['UNIQUE FLOWERS']},
    'unique_export': {'id': 7908, 'name': 'Unique Export SAS',       'fmt': 'unique',       'patterns': ['UNIQUE EXPORT SAS', 'UNIQUE EXPORT', '901398892']},
    'aposentos': {'id': 90004,     'name': 'Flores de Aposentos',      'fmt': 'aposentos',    'patterns': ['FLORES DE APOSENTOS']},
    # Farms registradas por formato existente
    'laila': {'id': 90023,     'name': 'Laila Flowers',            'fmt': 'alegria',      'patterns': ['LAILA FLOWERS', 'LOMCEM']},
    'tierraverde': {'id': 90038,     'name': 'Tierra Verde',             'fmt': 'alegria',      'patterns': ['TIERRA VERDE CIA']},
    'hacienda': {'id': 90018,     'name': 'Flores de la Hacienda',    'fmt': 'rosaleda',     'patterns': ['FLORES DE LA HACIENDA']},
    'rosadex': {'id': 90033,     'name': 'Rosadex',                  'fmt': 'rosaleda',     'patterns': ['ROSADEX']},
    'cananvalle': {'id': 90006,     'name': 'Cananvalley Flowers',      'fmt': 'custinv',      'patterns': ['CANANVALLEY', 'CANANVALLE']},
    'trebol': {'id': 90040,     'name': 'Plantaciones Plantreb',    'fmt': 'custinv',      'patterns': ['PLANTREB', 'trebolroses']},
    'much': {'id': 90027,     'name': 'Comercializadora Almanti', 'fmt': 'custinv',      'patterns': ['ALMANTI']},
    'naranjo': {'id': 90028,     'name': 'Naranjo Roses',            'fmt': 'custinv',      'patterns': ['NARANJO ROSES']},
    'premium': {'id': 90030,     'name': 'Premium Flowers Boyacá',   'fmt': 'premiumcol',   'patterns': ['VRD FIRAYA', '901800337']},
    'domenica': {'id': 90011,     'name': 'Domenica (Valencia Pozo)', 'fmt': 'domenica',     'patterns': ['FAUSTO BAYARDO', 'VALENCIA POZO']},
    'invos': {'id': 90021,     'name': 'Invos Flowers',            'fmt': 'invos',        'patterns': ['INVOS FLOWERS']},
    'meaflos': {'id': 90024,     'name': 'Meaflos',                  'fmt': 'meaflos',      'patterns': ['MEAFLOS', 'meaflos']},
    'heraflor': {'id': 90019,     'name': 'Heraflor',                 'fmt': 'heraflor',     'patterns': ['HERAFLOR']},
    'infinity': {'id': 90020,     'name': 'Infinity Trading',         'fmt': 'infinity',     'patterns': ['INFINITY TRADING']},
    'progreso': {'id': 90031,     'name': 'Flores El Progreso',       'fmt': 'progreso',     'patterns': ['FLORES EL PROGRESO', 'FLORESPROGRESO']},
    'colon': {'id': 90009,     'name': 'C.I. Flores Colon',        'fmt': 'colon',        'patterns': ['FLORES COLON']},
    'aguablanca': {'id': 90003,     'name': 'Agrícola Aguablanca',      'fmt': 'aguablanca',   'patterns': ['AGUABLANCA']},
    'success': {'id': 90037,     'name': 'Success Flowers',           'fmt': 'success',      'patterns': ['Success Flowers', 'SUCCESSFLOWERS']},
    # Proveedores nuevos (SEMANA 7)
    'conejera': {'id': 90010,     'name': 'Flores La Conejera',       'fmt': 'turflor',      'patterns': ['FLORES LA CONEJERA', 'LA CONEJERA']},
    'iwa': {'id': 90022,     'name': 'IWA Flowers',              'fmt': 'iwa',          'patterns': ['IWA FLOWERS', 'IWA7']},
    'timana': {'id': 90039,     'name': 'Flores Timana',            'fmt': 'timana',       'patterns': ['FLORES TIMANA', 'florestimana']},
    'rosabella': {'id': 90032,     'name': 'Rosabella',                'fmt': 'auto_rosabella', 'patterns': ['rosabella.ec', 'ROSABELLA', 'teresita@rosabella']},
    'agrosanalfonso': {'id': 90002,  'name': 'Agro San Alfonso (Glamour)','fmt': 'auto_agrosanalfonso', 'patterns': ['AGROSANALFONSO', 'SANALFONSO', 'AGROSANALFONSOS.A.', '1791289714']},
    # Stubs — proveedores detectados sin parser (TODO: crear parser cuando haya ejemplos)
    'victoria': {'id': 90043,     'name': 'Flores de la Victoria',    'fmt': 'unknown',      'patterns': ['FLORES DE LA VICTORIA']},
    'milagro_finca': {'id': 2652, 'name': 'El Milagro de las Flores', 'fmt': 'auto_milagro',      'patterns': ['EL MILAGRO DE LAS FLORES', 'elmilagro.co', '830.144.787']},
    'milagro_old': {'id': 90025,  'name': 'Finca Milagro',            'fmt': 'unknown',      'patterns': ['FINCA MILAGRO']},
    'saga': {'id': 90035,     'name': 'Saga Flowers',             'fmt': 'unknown',      'patterns': ['SAGA']},
    'flowerco': {'id': 90016,     'name': 'The Flower Company',       'fmt': 'unknown',      'patterns': ['THE FLOWER CO', 'THE FLOWER COMPANY']},
    # --- Proveedores nuevos registrados desde carpeta PROVEEDORES (stubs) ---
    # fmt='unknown' => la auto-learning pipeline generará un parser cuando el
    # usuario suba ≥2 facturas en Importación Masiva. IDs extraídos de marca_prov.txt.
    'agrinag':       {'id': 443,   'name': 'Agrinag',                'fmt': 'auto_agrinag', 'patterns': ['AGRINAG S.A.S', 'AGRINAG', '0991515941']},
    'bellarosa':     {'id': 2331,  'name': 'Bellarosa',              'fmt': 'auto_qualisa', 'patterns': ['collectings@bellarosa', 'bellarosa.com', 'BELLAROSA', 'BELLARO']},
    'cean':          {'id': 311,   'name': 'CEAN Global',            'fmt': 'auto_cean', 'patterns': ['CEAN GLOBAL SAS', 'CEAN GLOBAL', 'ceanglobal', '901377544']},
    'campanario':    {'id': 90046, 'name': 'El Campanario',          'fmt': 'auto_campanario', 'patterns': ['EL CAMPANARIO', 'CAMPANARIO']},
    'elite':         {'id': 90047, 'name': 'The Elite Flower',       'fmt': 'auto_elite', 'patterns': ['THE ELITE FLOWER', 'ELITE FLOWER S.A.S']},
    'farin':         {'id': 1426,  'name': 'Farin Roses',            'fmt': 'auto_farin', 'patterns': ['FARIN ROSES', 'farinroses', '1715889844']},
    'feso':          {'id': 90048, 'name': 'FESO',                   'fmt': 'unknown', 'patterns': ['FESO ']},  # hay que afinar, nombre genérico
    'floreloy':      {'id': 90049, 'name': 'Floreloy',               'fmt': 'auto_floreloy', 'patterns': ['FLORELOY']},
    'greengrowers':  {'id': 90050, 'name': 'Green Growers',          'fmt': 'auto_campanario', 'patterns': ['GREEN GROWERS', 'GREENGROWERS']},
    'mountain':      {'id': 90051, 'name': 'Mountain Fresh Flowers', 'fmt': 'auto_mountain', 'patterns': ['mountainfreshflowers', 'MOUNTAIN FRESH']},
    'native_blooms': {'id': 12898, 'name': 'Native Blooms',          'fmt': 'auto_native', 'patterns': ['NATIVE BLOOMS', 'NATIVEFARM']},
    'natuflor':      {'id': 2628,  'name': 'Natuflor',               'fmt': 'auto_natuflor', 'patterns': ['natuflor.com', 'NATUFLOR']},
    'qualisa':       {'id': 90052, 'name': 'Qualisa',                'fmt': 'auto_qualisa', 'patterns': ['collectings@qualisa', 'qualisa.com', 'QUALISA']},
    'san_francisco': {'id': 90053, 'name': 'San Francisco Gardens',  'fmt': 'auto_sanfrancisco', 'patterns': ['SAN FRANCISCO GARDENS', 'CI SAN FRANCISCO']},
    'san_jorge':     {'id': 90054, 'name': 'San Jorge',              'fmt': 'auto_sanjorge', 'patterns': ['SAN JORGE']},
    'zorro':         {'id': 90055, 'name': 'Flores El Zorro',        'fmt': 'auto_zorro', 'patterns': ['FLORES EL ZORRO', 'floreselzorro']},
}

# --- Regex para eliminar sufijo de proveedor del nombre del artículo ---
# Ej: "ROSA EC EXPLORER 60CM 25U CANTIZA" → "ROSA EC EXPLORER 60CM 25U"
_PROVIDER_SUFFIX_RE = re.compile(
    r'\s+(' + '|'.join(re.escape(k.upper()) for k in PROVIDERS) + r')\s*$', re.I)


def strip_provider_suffix(name: str) -> str:
    """Elimina el sufijo de proveedor del nombre de un artículo."""
    return _PROVIDER_SUFFIX_RE.sub('', name).strip()


def translate_carnation_color(color: str) -> str:
    """Traduce palabras de color de claveles del inglés al español.

    Args:
        color: Color en inglés (ej: 'WHITE', 'RED/YELLOW').

    Returns:
        Color traducido al español (ej: 'BLANCO', 'ROJO').
    """
    v_up = color.upper().strip()
    if v_up in CARNATION_COLOR_MAP:
        return CARNATION_COLOR_MAP[v_up]
    return ' '.join(CARNATION_COLOR_MAP.get(w, w) for w in v_up.split())


# --- Colores ANSI para la CLI ---
class CLIColors:
    """Códigos ANSI para output con color en terminal."""
    if sys.platform == 'win32':
        os.system('')  # Habilita ANSI en Windows
    OK    = '\033[92m'
    WARN  = '\033[93m'
    ERR   = '\033[91m'
    BOLD  = '\033[1m'
    DIM   = '\033[2m'
    RESET = '\033[0m'
    CYAN  = '\033[96m'
    MAG   = '\033[95m'
