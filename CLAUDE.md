# CLAUDE.md — Guía operativa para el agente

Este archivo se carga automáticamente en cada sesión. Contiene lo que tienes que saber para trabajar con este repo sin romper nada y sin preguntar lo mismo dos veces.

## Qué es este proyecto

**VeraBuy Traductor** — extrae líneas de producto de facturas PDF de proveedores de flores (~80 proveedores EC/COL/otros), las traduce a artículos del catálogo de VeraBuy, y mantiene un diccionario de sinónimos entrenado. Dos frontends (CLI + Web PHP) comparten el mismo pipeline Python.

**Usuario:** diego.pereira@veraleza.com (Ángel Panadero). Responsable de importaciones de la empresa.

## Cómo está organizado el código

```
src/
├── config.py         PROVIDERS (~95 proveedores), rutas, umbrales, colores
├── models.py         InvoiceHeader, InvoiceLine (con confidence + validation)
├── articulos.py      Carga e indexa catálogo desde SQL/MySQL
├── sinonimos.py      Diccionario persistente de mappings aprendidos
├── historial.py      Registro de facturas procesadas
├── matcher.py        Pipeline de 7 etapas + confidence scoring por método
├── extraction.py     Router de extracción con triage por página:
│                       - diagnóstico nativo vs escaneado vs mixto
│                       - OCRmyPDF+Tesseract como rama principal
│                       - EasyOCR como fallback (+ preproceso OpenCV)
│                       - ExtractionResult agrega señal de fiabilidad
│                       - extract_rows_by_coords helper reusable
├── pdf.py            Wrapper delgado sobre extraction.py — mantiene API
│                     pública (extract_text, get_last_ocr_confidence,
│                     detect_provider) y añade get_last_extraction().
├── validate.py       Reglas cruzadas (stems, totales, line_total vs stems*price)
├── reconciliation.py Delta de precio vs histórico ≥ últimas 20 hojas/proveedor
├── llm_fallback.py   Claude Haiku para líneas sin_parser (opcional, API key)
├── parsers/          **~40 parsers específicos** por proveedor
│   ├── __init__.py   FORMAT_PARSERS registry {fmt_key: Parser()}
│   ├── cantiza.py, golden.py, mystic.py, ...   (parsers originales)
│   └── auto_*.py     (parsers aprendidos en sesiones)
└── learner/          Auto-aprendizaje desde fingerprints de PDF

procesar_pdf.py        Entry point individual (JSON a stdout)
batch_process.py       Entry point lote (ZIP → Excel + estado progreso)
cli.py                 CLI interactivo (legacy)

tools/
├── triage_providers.py       Clasifica carpeta PROVEEDORES por bucket
├── extract_samples.py        Muestra texto de PDFs por proveedor
├── auto_learn_parsers.py     validate / register / evaluate parsers
└── auto_learn_report.json    Último informe de aprendizaje

web/
├── index.php         UI (tabs: Procesar / Lote / Historial / Sinónimos / Auto)
├── api.php           Orquesta llamadas Python vía shell_exec
├── assets/app.js     Frontend (1400+ líneas)
└── assets/style.css  Badges, row states, stat cards
```

## Flujo de procesamiento (end-to-end)

Cada factura recorre este pipeline **idéntico** tanto en individual como en lote:

1. **Extracción de texto** — [src/pdf.py](src/pdf.py) → [src/extraction.py](src/extraction.py)
   - Triage por página: pdfplumber intenta extraer texto; si una página está
     por debajo de un umbral de caracteres útiles o ratio alfanumérico, se
     marca ``scan``. Resto de páginas: ``native``.
   - Si todo es nativo → salida directa (rápido).
   - Si hay ``scan``: intenta **OCRmyPDF** (genera PDF con capa OCR
     Tesseract, se relee con pdfplumber). Si OCRmyPDF no está disponible
     cae a OCR per-page: **Tesseract directo** (pytesseract) → **EasyOCR**
     (último recurso), con preproceso OpenCV (denoise + deskew + binarización
     adaptativa). EasyOCR agrupa segmentos por y-centro del bbox.
   - Publica dos señales:
     - `get_last_ocr_confidence()`: 1.0 si nativo, 0.x si OCR (compat API).
     - `get_last_extraction()`: :class:`ExtractionResult` con
       ``confidence``, ``source`` (``native|mixed|ocr|empty``),
       ``ocr_engine`` (``ocrmypdf|tesseract|easyocr``) y ``degraded``.
2. **Detección de proveedor** — `detect_provider()` busca en `PROVIDERS[*].patterns`
3. **Parser específico** — `FORMAT_PARSERS[fmt].parse(text, provider_data)` devuelve `(InvoiceHeader, [InvoiceLine])`
4. **Split mixed boxes** — separa `RED/YELLOW` en dos líneas
5. **Rescate** — regex genérico para líneas que el parser no cazó → `match_status='sin_parser'`
6. **Matching** — [src/matcher.py](src/matcher.py) 7 etapas: sinónimo → priorizada (variedad+talla+marca) → delegación (Life) → color-strip (rosas) → exacta → marca → fuzzy ≥90%. Asigna `match_confidence`.
7. **LLM fallback** — para sin_parser, si hay `ANTHROPIC_API_KEY` (no-op sin clave)
8. **Validación cruzada** — `stems == bunches × spb`, `line_total ≈ stems × price`, `sum(lines) ≈ header.total`
9. **Reconciliación** — precio vs media histórica del proveedor (desvío >15% = anómalo)
10. **Serialización** — cada línea lleva: campos de dominio + `match_confidence`, `ocr_confidence`, `validation_errors`, `needs_review`

## Modelo de datos (no romper)

`InvoiceLine` tiene estos campos **críticos** (leerlos antes de tocarlos):

```python
raw_description, species, variety, grade, origin, size, stems_per_bunch,
bunches, stems, price_per_stem, price_per_bunch, line_total, label, farm,
box_type, provider_key,
articulo_id, articulo_name, match_status, match_method,
ocr_confidence, extraction_confidence, extraction_source,
match_confidence, field_confidence, validation_errors
```

Campos de extracción (añadidos en sesión 5, todos con defaults seguros):
- `extraction_confidence` (0.0–1.0): señal agregada de la extracción
  completa del PDF, no solo del OCR. Una página mixta nativo+OCR puede
  dar 0.92 aunque el OCR en sí fuera bueno.
- `extraction_source`: `native` | `mixed` | `ocr` | `empty` | `rescue`.
  Las líneas capturadas por `rescue_unparsed_lines` llevan `rescue`
  para que la UI las pinte distinto — no disimular fallos del parser.

- `match_status`: `ok | sin_match | sin_parser | pendiente | mixed_box | llm_extraido`
- `species`: `ROSES | CARNATIONS | HYDRANGEAS | ALSTROEMERIA | GYPSOPHILA | CHRYSANTHEMUM | OTHER`
- `origin`: `EC | COL | otros` (determina `ROSA EC` vs `ROSA COL` en `expected_name()`)
- Decimales: muchos proveedores usan coma (0,30) no punto. Normalizar con `.replace(',', '.')` o `.replace(',', '')` según contexto.

## Convenciones de parsers (obligatorias)

Cada parser cumple este contrato en [src/parsers/](src/parsers/):

```python
class <Name>Parser:
    def parse(self, text: str, provider_data: dict) -> tuple[InvoiceHeader, list[InvoiceLine]]:
```

Parsers **auto-generados** usan prefijo `auto_`: `src/parsers/auto_<key>.py` con `class AutoParser`.

**Reglas al escribir/modificar parsers:**

1. **Nunca lanzar excepciones por línea mal formada** — saltar (`continue`) y dejar que `rescue_unparsed_lines` lo recoja.
2. **Variety en MAYÚSCULAS siempre** (`.strip().upper()`). El matcher indexa así.
3. **Rellenar `stems_per_bunch` incluso con default** (25 rosas, 20 claveles) — 0 rompe `expected_name()`.
4. **`origin` importante**: determina el prefijo del nombre esperado (`ROSA EC` vs `ROSA COL`).
5. **`line_total` siempre con 2 decimales**: la validación cruzada compara con tolerancia 2%.
6. **Derivar `header.total` de suma de líneas** si el parser no lo extrajo:
   ```python
   if not header.total and lines:
       header.total = round(sum(l.line_total for l in lines), 2)
   ```
7. **Cambios en parser existente = aditivos**. Si hay que soportar variante nueva, añadir regex `_RE_B` junto a `_RE_A` y probar ambos. **Nunca borrar** un regex que ya funciona con facturas en producción.

## Cómo añadir un parser nuevo para un proveedor stub

```bash
# 1. Ver muestras
python tools/extract_samples.py <FOLDER_NAME>

# 2. Escribir parser en src/parsers/auto_<key>.py

# 3. Validar contra todas las muestras
python tools/auto_learn_parsers.py validate <provider_key> "ruta/a/carpeta"

# 4. Si pass_ratio >= 0.70, registrar
python tools/auto_learn_parsers.py register <provider_key> auto_<key>

# 5. Verificar end-to-end
python tools/auto_learn_parsers.py evaluate "ruta/a/carpeta"
```

`register` actualiza tanto [src/parsers/__init__.py](src/parsers/__init__.py) (añade import + entry en `FORMAT_PARSERS`) como [src/config.py](src/config.py) (cambia `fmt='unknown'` → `fmt='auto_<key>'`).

## Cómo evaluar un parser existente sin tocarlo

```bash
python tools/auto_learn_parsers.py evaluate "ruta/a/carpeta/<PROVEEDOR>"
```

Output JSON con métricas por muestra:
- `detected` — detect_provider encontró al proveedor
- `parsed_any` — el parser extrajo ≥1 línea
- `totals_ok` — suma de líneas ≈ header.total ±1%
- `total_rescued` — líneas que el parser omitió y el rescue regex capturó

**Regla de oro:** si `evaluate` da 100% detected + 100% parsed_any + 100% totals_ok + 0 rescued, **NO tocar ese parser**. Solo modificar parsers con gaps probados.

## Proveedores: estado actual (triage más reciente)

- **84 REGISTRADO_OK** — detectados y con parser funcional
- **0 REGISTRADO_STUB** — ¡todos los stubs convertidos!
- **8 LOGISTICA** — filtrados por SKIP_PATTERNS del batch:
  `ALLIANCE`, `DSV`, `EXCELE CARGA`, `LOGIZTIK`, `REAL CARGA`, `SAFTEC`, `VERALEZA` (la buyer),
  `FESO` (EXCELLENT CARGO SERVICE SAS, carguero)

### Resultado de evaluación masiva (sesión 3)

Corriendo `python tools/evaluate_all.py` sobre las 82 carpetas:

- **OK (24)**: detectado + parseado + totales cuadran. No tocar.
- **TOTALES_MAL (22)**: parsea bien pero `header.total` no se extrae del PDF
  (muchos parsers no tienen regex de total de cabecera). Cosmético: la suma de
  líneas está bien, solo falla la validación cruzada. Impacto real bajo.
- **NO_PARSEA (36)**: alguna muestra retorna 0 líneas o <60% parse. Prioridad alta.
  Incluye CANTIZA (3/5), COLIBRI (5/5 pero totales mal), DAFLOR (3/5), GOLDEN (ok),
  MYSTIC (1/5), LATIN (3/5), etc. Requiere revisión caso por caso.
- **NO_DETECTADO (0)**: todos los patterns matchean.

Ver [auto_learn_report.json](auto_learn_report.json) para detalle por proveedor
y muestra (qué PDFs fallan, qué líneas rescata el fallback).

**Carpeta de entrenamiento** del usuario (ruta fija):
```
C:\Users\diego.pereira\Desktop\DOC VERA\FACTURAS IMPORTACION\PROVEEDORES
```
Contiene subcarpeta por proveedor con 5 facturas nuevas + 2 antiguas (para regresión). `marca_prov.txt` en la raíz mapea `FOLDER_NAME|id_proveedor` (IDs de tabla `proveedores` en la BD VeraBuy).

## Parsers aprendidos (auto_*.py)

| Parser | Proveedores que lo usan | Notas |
|---|---|---|
| `auto_farin` | FARIN | layout lineal simple |
| `auto_qualisa` | QUALISA, BELLAROSA | template SaaS compartido |
| `auto_agrinag` | AGRINAG | parent/sub-línea para mixed box |
| `auto_natuflor` | NATUFLOR | dual: colombiano + SaaS (delega en auto_agrinag) |
| `auto_campanario` | GREENGROWERS, EL CAMPANARIO | template Lasso; código "R14 ZAIRA"/"VERALEZA" antes de variety |
| `auto_floreloy` | FLORELOY | parent + data en líneas separadas |
| `auto_sanjorge` | SAN JORGE | decimal coma; marcador 'T' entre price y total |
| `auto_milagro` | MILAGRO | sub-líneas "Milagro" con stems reales; skip parents MIXED |
| `auto_mountain` | MOUNTAIN | usa `pdfplumber.extract_words()` con x-coords para mapear CM |
| `auto_native` | NATIVE BLOOMS | dual: roses + tropical foliage; heurística para decimal/miles con coma |
| `auto_sanfrancisco` | SAN FRANCISCO | Hydrangeas; size=60 default, spb=1 |
| `auto_zorro` | ZORRO | single-sample overfit acceptable; tolera OCR 'l'→'1', 'ASSORTEO'→'ASSORTED' |
| `auto_cean` | CEAN GLOBAL | factura electrónica COL; colores inglés→español via `translate_carnation_color` |
| `auto_elite` | ELITE | Alstroemeria parent + sub-líneas solo-stems heredando price |
| `auto_conejera` | FLORES LA CONEJERA | factura electrónica COL; translate_carnation_color para colores EN→ES |
| `auto_agrosanalfonso` | AGROSANALFONSO, GLAMOUR | template `I`-separado; GLAMOUR = marca comercial de AgroSanAlfonso |
| `auto_rosabella` | ROSABELLA | layout lineal simple; "ABC" abreviatura de "ASSORTED" |

## Signals al usuario (UI)

Nuevas tarjetas + badges añadidos a [web/assets/app.js](web/assets/app.js):

- **A Revisar**: líneas con `match_confidence < 0.80` OR `sin_match` OR `sin_parser` OR `llm_extraido` OR con `validation_errors`. Excluye `mixed_box`.
- **Totales**: ✓ si `sum_lines ≈ header.total ±1%`, si no muestra diff en rojo
- **Precio Anómalo**: precios con >15% desvío vs histórico del proveedor
- **Extracción OCR/Mixta**: aparece solo si la extracción no fue 100% nativa.
  Muestra % de confianza agregada + tooltip con motor usado (ocrmypdf /
  tesseract / easyocr) y si hubo páginas degradadas. Reemplaza al antiguo
  badge "OCR" que solo distinguía nativo/OCR sin detalle.
- **Omitidos** (lote): cuenta archivos filtrados por SKIP_PATTERNS, con detalle expandible

Clases CSS de fila: `row-sin-parser` (ámbar), `row-rescue` (lila
discontinuo — línea recuperada por regex genérico), `row-sin-match`
(rosa), `row-has-error` (rojo borde), `row-low-conf` (naranja borde).

## SKIP_PATTERNS del batch

En [batch_process.py:297](batch_process.py#L297) — filenames que contienen estos substrings NO son tratados como facturas. Logísticas/aduanas:

```python
'DUA', 'NYD', 'ALLIANCE', 'FULL', 'GUIA', 'PREALERT', 'PRE ALERT', 'REAL CARGA',
'SAFTEC', 'EXCELLENT', 'EXCELLENTE', 'BTOS', 'PARTE', 'CORRECTA', 'LINDA', 'SLU',
'DSV', 'LOGIZTIK', 'EXCELE', 'EXCELE CARGA',
```

**NO incluir `JORGE`** — falso positivo con el proveedor SAN JORGE.

## Confidence scoring (calibración aprendida)

Valores en [src/matcher.py:_METHOD_CONFIDENCE](src/matcher.py), sobre 1.0:

| Método | Score |
|---|---|
| sinónimo | 1.00 |
| sinónimo→marca | 0.98 |
| exacto | 0.95 |
| marca | 0.90 |
| delegación (Life Flowers) | 0.80 |
| color-strip | 0.75 |
| fuzzy NN% | NN/100 |

Reglas que **bajan** el score automáticamente:
- `validation_errors` no vacío → cap a 0.70
- Delta de precio >15% histórico → cap a 0.70
- Delta >30% → cap a 0.55
- OCR < 1.0 → multiplica el score (escaneos siempre tendrán menos confianza)

Umbral de "A Revisar": < 0.80.

## Cosas que no hay que hacer

1. **No llamar APIs externas** salvo que el usuario lo pida explícitamente. Trabajar con Claude Code (agente) para generar parsers, no con API.
2. **No tocar parsers existentes "por estética"** — solo si `evaluate` demuestra un gap real.
3. **No añadir campos obligatorios a `InvoiceLine`**. Si se añade un campo nuevo, debe tener default para no romper parsers legacy.
4. **No usar `find` / `grep` / `cat` desde Bash** — el harness ofrece Glob, Grep, Read.
5. **No crear docs markdown** salvo que el usuario los pida.
6. **No intentar arreglar facturas OCR-muy-corruptas con regex**. Escanes con `~OSES`, `SO` por `50`, `(` por `0` no se solucionan con parser — son fallos de reconocimiento óptico. Aceptar pass_ratio 80% en esos casos.
7. **No mezclar proveedores distintos bajo el mismo fmt** a menos que se haya verificado que comparten plantilla SaaS idéntica (ej: QUALISA+BELLAROSA, GREENGROWERS+EL CAMPANARIO).

## Comandos habituales

```bash
# Triage completo de proveedores
python tools/triage_providers.py

# Procesar una factura individual
python procesar_pdf.py ruta/al.pdf

# Ver texto extraído de PDFs de un proveedor
python tools/extract_samples.py NOMBRE_CARPETA

# Aprender parser nuevo (stub → funcional)
python tools/auto_learn_parsers.py validate <key> <carpeta>
python tools/auto_learn_parsers.py register <key> auto_<key>

# Evaluar parser existente sin tocarlo
python tools/auto_learn_parsers.py evaluate <carpeta>

# Lote (desde UI) — genera Excel
# O desde CLI:
python batch_process.py carpeta_con_pdfs/ --output resultado.xlsx
```

## Colisiones / ambigüedades conocidas

- **PONDEROSA = VERDES LA ESTACION** (mismo negocio, dos NITs: 900.408.822 y 900.428.540). Fusionados bajo `verdesestacion` en config, id=11748. Layout cambió recientemente — `VerdesEstacionParser` soporta variantes A (legacy) y B (actual).
- **STAMPSY / STAMPSYBOX** → mismo id=2220, mismo fmt=mystic.
- **MILAGRO** (original stub id 90025) renombrado a `milagro_old`; el real es `milagro_finca` id=2652 (EL MILAGRO DE LAS FLORES SAS).
- **UNIQUE** se desdobló: `unique` (id 90041, UNIQUE FLOWERS) y `unique_export` (id 7908, UNIQUE EXPORT SAS) — dos empresas distintas.
- **GLAMOUR** se detecta como "Agro San Alfonso" — es la marca comercial de esa finca (layout idéntico, correcto).

## Para el próximo turno

Todos los stubs convertidos a parsers funcionales. Lo siguiente lógico:

- **Evaluación masiva de los 66 parsers heredados** (no auto_*.py): correr
  `python tools/auto_learn_parsers.py evaluate <carpeta>` uno por uno contra las
  nuevas facturas + las 2 antiguas de regresión. Solo tocar los que muestren
  gaps reales. Anotar en esta doc qué parsers fueron modificados y por qué.
- **Añadir mejoras puntuales** a parsers auto_* que hayan dado <100% pass ratio
  cuando aparezcan nuevas muestras (MILAGRO 80%, NATIVE 80%, ELITE 80%, CEAN 80%).

## REGLA OBLIGATORIA — mantener este archivo actualizado

Cada vez que hagas cambios en el código del proyecto (añadir parser, arreglar
bug, cambiar convenciones, añadir nueva herramienta, etc.), **DEBES** actualizar
este CLAUDE.md dentro del MISMO turno, sin esperar a que el usuario lo pida.

Qué actualizar según el cambio:
- Parser nuevo → añadir fila en la tabla "Parsers aprendidos", mover al proveedor
  de REGISTRADO_STUB → REGISTRADO_OK en "Proveedores: estado actual"
- Arreglo de parser existente → anotarlo en "Cosas que no hay que hacer" si se
  aprendió algo reutilizable, o en "Colisiones / ambigüedades" si es relevante
- Nuevo módulo / archivo → añadirlo al árbol de "Cómo está organizado el código"
- Nuevo comando de CLI → añadirlo a "Comandos habituales"
- Cambio en contrato de parsers (InvoiceLine, etc.) → actualizar "Modelo de datos"
  y "Convenciones de parsers"
- Añadir nueva lección aprendida (ej. un tipo de OCR que falla, un truco de
  pdfplumber.extract_words) → añadirla a "Lecciones aprendidas"

Siempre terminar el turno añadiendo la fecha y un resumen de 1-2 líneas al
final de este archivo, en la sección "Historial de sesiones".

## Lecciones aprendidas (en orden cronológico)

- **OCR con detalle de confianza**: EasyOCR con `detail=1` devuelve `(bbox, text, conf)`
  por segmento. La media se expone vía `get_last_ocr_confidence()` en `pdf.py` y se
  propaga a cada `InvoiceLine.ocr_confidence`.
- **Preproceso OpenCV mejora OCR drásticamente**: denoise bilateral + binarización
  adaptativa gaussiana + deskew. Solo se activa si cv2 está instalado; si no, no-op.
- **pdfplumber tables no siempre sirve**: MOUNTAIN tiene una tabla cuyo `extract_tables()`
  no detecta bien las columnas de tallas (40/50/60/70 cm). Solución: `extract_words()`
  con x-coordinates para mapear cada valor a su columna por posición horizontal.
- **Decimal con coma vs punto**: muchos proveedores COL/EC usan coma. Helper típico:
  `float(s.replace('.', '').replace(',', '.'))` para formato europeo (1.234,56),
  `float(s.replace(',', '.'))` si solo hay coma. NATIVE BLOOMS es peor: usa coma
  para decimales Y para miles (ej "81,000" son $81, no 81k). Ver `_num()` en
  `auto_native.py` para heurística.
- **Templates SaaS compartidos**: varios proveedores ecuatorianos usan el mismo
  template (parece comercial de algún SaaS local). Detectables por la cabecera
  `# BOX PRODUCT SPECIES LABEL`. Ejemplos: QUALISA, BELLAROSA, AGRINAG, NATUFLOR,
  GREENGROWERS, EL CAMPANARIO. Cuando aparezcan stubs con layout así, probar
  primero con `--fmt-name auto_qualisa` o `auto_agrinag` antes de escribir
  parser nuevo.
- **Layout de parent/sub-líneas para mixed boxes**: AGRINAG y MILAGRO tienen
  cajas parent con sub-líneas de detalle. Estrategia: emitir sub-líneas (traen
  variedad real) y saltar parents que dicen "MIXED BOX" (no aportan info).
- **Variedades en mixed case**: algunos proveedores (QUALISA, NATUFLOR_SaaS,
  BELLAROSA) usan mixed case ("Vendela", "Freedom") en el PDF. Siempre normalizar
  con `.strip().upper()` antes de guardar en InvoiceLine.
- **OCR fragmentado por columnas**: si un PDF escaneado tiene columnas
  apretadas, EasyOCR emite un segmento por celda y `_ocr_extract` antes
  producía una palabra por línea — lo que rompía regex por fila. Fix:
  agrupar segmentos por y-centro del bbox (tolerancia 15 px a 300 dpi).
  Esto desbloquea parsers como MILONGA-scan y debería ayudar a cualquier
  parser OCR-based a futuro. Se mantiene el orden izquierda→derecha
  dentro de cada fila por x0.
- **Un fmt → varios proveedores similares**: cuando al arreglar un parser
  hereditado (ej. MYSTIC) varios otros mejoran (STAMPSY, STAMPSYBOX,
  FIORENTINA todos compartían `fmt='mystic'` con su propio template
  ligeramente distinto). Verificar todos los proveedores que usan el
  mismo fmt después de cada fix con regex añadiendo fallbacks cuando
  haya pequeñas diferencias (ej. falta de box_code).
- **Routing de extracción antes de OCR**: no todos los PDFs necesitan
  OCR, y correr OCR "por si acaso" es lento y a veces peor. El router en
  `src/extraction.py` hace un triage página a página: si pdfplumber
  devuelve ≥40 chars con ≥35% alfanuméricos, la página es nativa. Si
  no, se marca `scan`. El resultado final puede ser `native`, `mixed` o
  `ocr` — la UI y el matcher usan esa distinción.
- **OCRmyPDF > EasyOCR para escaneados normales**: OCRmyPDF preserva el
  orden de columnas mucho mejor que EasyOCR per-page porque usa
  Tesseract con la geometría original del PDF. Lo usamos primero si está
  disponible; EasyOCR queda solo como último recurso o para PDFs
  problemáticos.
- **Nunca marcar "igual de fiable" un PDF nativo y uno OCRizado**: el
  pipeline ahora multiplica `match_confidence` también por
  `extraction_confidence`, así un PDF mixto con una página OCR mala
  arrastra el score aunque la línea concreta haya matcheado por el
  método más fuerte (sinónimo, exacto).
- **Rescue no debe camuflar fallos**: las líneas capturadas por
  `rescue_unparsed_lines` ahora llevan `extraction_source='rescue'` y
  `extraction_confidence=0.60`. La UI las pinta en lila discontinuo
  para que el operador vea que el parser específico no las capturó.
- **No todos los PDFs son rescatables**: algunas facturas escaneadas
  salen con caracteres OCR tan corrompidos (`R:ise`, `sr` en vez de `ST`,
  `1~` en vez de dígito, tokens fragmentados, acentos basura) que ningún
  regex puede recuperarlas. Aceptar pass_ratio < 100% en esos casos
  (MILONGA scan, SAYONARA scan).

## Historial de sesiones

- **2026-04-15 sesión 1**: Mejoras de pipeline (confidence, validación, conciliación,
  LLM fallback), UI de revisión con badges/dots, 10 parsers nuevos (FARIN, QUALISA,
  BELLAROSA, AGRINAG, NATUFLOR, GREENGROWERS, EL CAMPANARIO, FLORELOY, SAN JORGE,
  MILAGRO), arreglo de VerdesEstacionParser (variante B sin CM), CLAUDE.md inicial.
  Commit `5856f26`.
- **2026-04-15 sesión 2**: Atacando los 5 stubs difíciles. +MOUNTAIN (5/5 con
  x-coords de pdfplumber) +NATIVE BLOOMS (4/5, soporta layout roses + tropical).
  Añadida regla obligatoria de mantener CLAUDE.md actualizado solo.
- **2026-04-15 sesión 2 (cont)**: +SAN FRANCISCO (5/5 Hydrangeas) +ZORRO (1/1
  con tolerancia OCR) +CEAN (4/5 factura electrónica COL con traducción colores)
  +ELITE (4/5 Alstroemeria parent/sub-líneas). FESO descartado por ser carguero
  (EXCELLENT CARGO SERVICE SAS), añadido a SKIP_PATTERNS. **0 stubs pendientes.**
- **2026-04-15 sesión 3**: Evaluación masiva de los 66 parsers heredados con
  nuevo script `tools/evaluate_all.py`. Arreglados los 4 parsers completamente
  rotos (0 líneas parseadas): CONEJERA (era fmt='turflor' incorrecto, nuevo
  auto_conejera), AGROSANALFONSO+GLAMOUR (nuevo auto_agrosanalfonso para su
  template `I`-separado), ROSABELLA (nuevo auto_rosabella). De 37 NO_PARSEA
  quedan 36 parsers con gaps parciales documentados en auto_learn_report.json.
- **2026-04-15 sesión 3 (fixes)**: Reportes del usuario:
  1) CONEJERA aún no parseaba porque `register` no actualizó `fmt='turflor'→
     'auto_conejera'` (su regex solo toca stubs con fmt='unknown'). Fix manual
     en config.py. Ahora 8/9 líneas parsean, la 9ª es un resumen científico
     del pie de factura, no producto.
  2) GLAMOUR recortaba variety a fragmentos ('AL', 'GHTON') porque `split('I')`
     rompía tokens como 'R11-BCPI' o `$0.300000I 13.00` (I pegado a dígito/$).
     Fix: `re.split(r'(?<![A-Z])I\s+')` — solo separa cuando la I no está
     precedida por mayúscula. Ahora GLAMOUR extrae 4/4 variedades correctas.
- **2026-04-15 sesión 5**: Refuerzo transversal de la capa de extracción
  (no se tocan parsers). Cambios:
  * **Nuevo módulo `src/extraction.py`** con routing diagnóstico:
    triage página a página (nativa vs escaneada), OCRmyPDF+Tesseract
    como rama principal, Tesseract per-page y EasyOCR como fallback,
    `ExtractionResult` con `source`, `confidence`, `ocr_engine`,
    `degraded`, y helper reusable `extract_rows_by_coords()`.
  * **`src/pdf.py` refactor**: ahora es wrapper delgado del router;
    API pública intacta (`extract_text`, `get_last_ocr_confidence`,
    `detect_provider`, `extract_tables`) y añade `get_last_extraction()`
    para que el pipeline acceda a las señales finas sin cambios en
    callers existentes.
  * **`InvoiceLine.extraction_confidence` + `extraction_source`** con
    defaults seguros (`1.0` / `'native'`). El matcher multiplica el
    score por `extraction_confidence` además de `ocr_confidence`.
  * **Rescue marcado como `extraction_source='rescue'`** con
    `extraction_confidence=0.60`. Nueva clase CSS `row-rescue` (lila
    discontinuo) en `web/assets/style.css` y `web/assets/app.js`.
  * **UI**: el stat card "OCR" se convierte en "Extracción OCR/Mixta"
    con tooltip indicando motor y si hubo degradación.
  * Cobertura: **OK 27→30, NO_PARSEA 35→31**. El triage desbloquea
    PDFs mixtos que antes se marcaban nativos vacíos (se saltaba la
    rama OCR) o escaneados que nunca llegaban a Tesseract.
- **2026-04-15 sesión 4**: Ataque a los 36 parciales. Parsers mejorados:
  * **MYSTIC** (1/5 → 5/5): reescrito regex para soportar box_codes con
    dígitos (`R14`, `R19`), block names opcionales (`SORIALES`, `IGLESIAS`),
    variedades mixed-case (`Gyp Natural Xlence 750 G`), sufijo `N/A`, y
    detección automática de especie (GYPSOPHILA, ROSES, etc.).
  * **LA ESTACION / PONDEROSA** (2/5 → 5/5): el regex de VerdesEstacionParser
    variante B no soportaba labels multi-palabra (`TIPO B`). Fix: `(.*?)`
    en lugar de `(\S*?)` para capturar label antes de `VERALEZA SLU`.
  * **MILONGA** (2/5 → 4/5): ColFarmParser ampliado con tolerancia OCR
    (`Rbse`/`Rcse` por `Rose`, `S1`/`SI`/`Sl` por `ST`, decimales coma).
    Count de caja opcional, separador `-` opcional entre SPB y size para
    soportar `FreedomX25 50` pegado. El 5º sample sigue fallando por OCR
    demasiado corrupto (`R:ise`, `sr`, `1~`).
  * **MULTIFLORA** (2/5 → 5/5): añadidas variantes B (`N Box/Half/Quarter
    N N PRICE TOTAL FBE` sin segunda palabra en box_type) y C (`FBE PIECES
    Half Tall UNITS description UPB St(Stems) PRICE $TOTAL` con $ prefix).
    Detección de especie CARN/ROSE además de ALSTRO/CHRY/DIANTHUS.
  * **SAYONARA** (2/5 → 3/5): añadidas keywords `Cushion`/`Button`/`Daisy`/
    `Cremon`/`Spider` a `_TYPE_MAP` para template nuevo "Pom Europa/Asia
    White Cushion Bonita". Nuevo `_PACK_RE_B` para formato `6 HB15 1200 240
    $0.950 $228.00` (btype+spb pegado, stems y bunches invertidos).
  * **STAMPSY / STAMPSYBOX / FIORENTINA** (0/5 → 5/5): al arreglar MYSTIC,
    estos tres comparten el mismo fmt='mystic' y se beneficiaron. Añadido
    fallback `_LINE_RE_NOCODE` para STAMPSYBOX que no tiene box_code
    (variety va directamente tras `H|Q`).
  * **Mejora en pdf.py**: `_ocr_extract` ahora agrupa tokens OCR por
    y-centro del bbox (tolerancia 15 px) en lugar de emitir un token por
    línea. Desbloquea regex por fila para facturas escaneadas con columnas.
  * Tabla global: **OK 24→27, NO_PARSEA 36→35**. Los fallos remanentes
    son casi todos PDFs OCR muy corruptos (irrecuperables con regex) o
    gaps de totales (cosmético).

## IMPORTANTE — gotcha con `register` tool

`python tools/auto_learn_parsers.py register <key> <fmt>` solo actualiza el
`fmt` de un proveedor si estaba en `fmt='unknown'`. Si el proveedor ya tenía
otro fmt (ej: 'turflor' heredado pero roto), hay que **editar config.py a
mano** o el nuevo parser queda huérfano (escrito en disco pero nadie lo
llama). El comando imprime `AVISO: no se encontró fmt="unknown"` cuando
pasa, pero es fácil pasarlo por alto.
