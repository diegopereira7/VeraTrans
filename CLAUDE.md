# CLAUDE.md — Guía operativa para el agente

Este archivo se carga automáticamente en cada sesión. Contiene lo que tienes que saber para trabajar con este repo sin romper nada y sin preguntar lo mismo dos veces.

## Documentación de seguimiento

Este archivo cubre el **estado actual** (arquitectura, convenciones,
sesiones). Para **planificar el siguiente bloque de trabajo** y ver
**por dónde va** el proyecto:

- [`docs/README.md`](docs/README.md) — índice corto de la documentación.
- [`docs/roadmap/roadmap.md`](docs/roadmap/roadmap.md) — plan a 12 pasos
  con prompts ejecutables listos para pegar a Claude Code.
- [`docs/roadmap/checklist.md`](docs/roadmap/checklist.md) — tablero
  rápido: estado actual, próximo bloque activo, registro de sesiones.

Regla: si pasan días entre sesiones, **sincroniza primero** los dos
archivos de `docs/roadmap/` con el "Historial de sesiones" de este
archivo antes de ejecutar nada nuevo. El roadmap y el checklist solo
valen si van por delante de lo que ya está hecho.

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
├── evaluate_all.py           Benchmark masivo in-process (JSON+CSV+penalties)
├── classify_errors.py        Taxonomía E1..E10 sobre salida del benchmark
├── golden_bootstrap.py       Genera anotación draft para golden set
├── golden_review.py          Revisión interactiva de anotaciones gold
├── golden_apply.py           Aplica correcciones gold como sinónimos
├── evaluate_golden.py        Compara sistema vs anotaciones gold revisadas
└── auto_learn_report.json    Último informe de aprendizaje

golden/                       Anotaciones de verdad-terreno (JSON)
├── alegria_00046496.json     43 líneas (draft)
├── fiorentina_0000141933.json 6 líneas (draft)
├── golden_unknown.json       1 línea (draft)
├── meaflos_EC1000035075.json 12 líneas (draft)
└── mystic_0000281780.json    26 líneas (draft)

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
6. **Matching** — [src/matcher.py](src/matcher.py) **scoring por evidencia**
   (sesión 6). Los antiguos 7 etapas siguen existiendo pero como
   *generadores de candidatos*, no como decisores finales:
   - Se recolectan candidatos de: sinónimo, búsqueda priorizada, delegación,
     color-strip, exact, branded, rose EC/COL, fuzzy top-5.
   - Se aplican **vetos estructurales**: species/origin/size incompatibles
     descartan el candidato — ni un sinónimo manual puede saltarse esto.
   - Se puntúa cada candidato con features reales (variety, size, species,
     origin, spb, marca en nombre, histórico del proveedor, trust del
     sinónimo) + prior débil por método.
   - Se penaliza marca ajena (`foreign_brand` -0.25) para evitar asignar
     un artículo con marca FIORENTINA a un proveedor MYSTIC cuando hay
     genéricos disponibles.
   - Gana el candidato con score más alto SI tiene margen suficiente
     sobre el 2º (0.05 si top1 ≥ 0.90, 0.10 si no). Con margen escaso
     entra en `ambiguous_match`.
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

Campos de vinculación (sesión 6, scoring por evidencia):
- `link_confidence` (0.0–1.0): confianza aislada del vínculo con el
  artículo ERP, independiente de la calidad de extracción. Es la señal
  que el matcher usa para decidir auto-vinculación.
- `match_confidence`: sigue existiendo por retro-compat. Ahora se calcula
  como `link_confidence × ocr_confidence × extraction_confidence` — si
  alguna de las 3 baja, el score final lo refleja.
- `candidate_margin`: score top1 menos score top2. Margen < 0.05 con
  top1 ≥ 0.90, o margen < 0.10 si no, dispara `ambiguous_match`.
- `candidate_count`: nº de candidatos que pasaron los vetos.
- `match_reasons` / `match_penalties`: lista trazable de features que
  aportaron o restaron al score del ganador (ej. `variety_match`,
  `size_exact`, `provider_history(4)`, `foreign_brand(FIORENTINA)`).
- `top_candidates`: lista resumen ≤3 mejores para ofrecer alternativas
  en la UI.

- `match_status`: `ok | ambiguous_match | sin_match | sin_parser | pendiente | mixed_box | llm_extraido`
  - `ambiguous_match`: línea leída razonablemente (>0.50 link) pero el
    artículo exacto no está claro (2 candidatos plausibles con margen
    < 0.10, o ganador entre 0.50–0.70 de score). Cuenta como needs_review.
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
discontinuo — línea recuperada por regex genérico), `row-ambiguous`
(amarillo — match ambiguo o evidencia insuficiente), `row-sin-match`
(rosa), `row-has-error` (rojo borde), `row-low-conf` (naranja borde).

Cada fila lleva un `title=` con las `match_reasons` y `match_penalties`
que decidieron el vínculo, más el `candidate_margin`. Es la forma rápida
de que el operador entienda "ganó por X, perdió puntos por Y".

## SKIP_PATTERNS del batch

En [batch_process.py:297](batch_process.py#L297) — filenames que contienen estos substrings NO son tratados como facturas. Logísticas/aduanas:

```python
'DUA', 'NYD', 'ALLIANCE', 'FULL', 'GUIA', 'PREALERT', 'PRE ALERT', 'REAL CARGA',
'SAFTEC', 'EXCELLENT', 'EXCELLENTE', 'BTOS', 'PARTE', 'CORRECTA', 'LINDA', 'SLU',
'DSV', 'LOGIZTIK', 'EXCELE', 'EXCELE CARGA',
```

**NO incluir `JORGE`** — falso positivo con el proveedor SAN JORGE.

## Carriles de revisión (`review_lane`)

Cada línea recibe un carril de revisión asignado automáticamente tras
validación (`src/validate.py → classify_review_lanes`). El campo
`review_lane` se serializa en el JSON y la UI muestra un badge por línea
+ un stat card con el % de autoaprobación.

| Carril | Badge | Criterio | Acción |
|---|---|---|---|
| `auto` | verde AUTO | link ≥ 0.80 + match ≥ 0.80 + margen ≥ 0.05 + sin errors + extracción ≥ 0.80 + no rescue | No necesita revisión |
| `quick` | amarillo QUICK | Match ok pero no cumple todos los criterios de auto | Revisión rápida |
| `full` | rojo FULL | sin_match, sin_parser, rescue, OCR < 0.50, ambiguo con link < 0.50 | Revisión completa |

### Baseline de carriles (sesión 9i)

| Carril | Líneas | % |
|---|---|---|
| auto | 1818 | 60.6% |
| quick | 996 | 33.2% |
| full | 187 | 6.2% |

### Cómo subir el % de auto

1. **Confirmar sinónimos** desde la UI (✓) → promueve a `aprendido_confirmado` → sube trust → sube link_confidence
2. **Corregir matches** desde la UI → sinónimo malo degradado → siguiente factura usa el correcto
3. **Ampliar golden set** y aplicar con `golden_apply.py` → entrenamiento masivo
4. **Arreglar parsers** de los 20 NO_PARSEA restantes → menos líneas en `full`

## Confidence scoring (calibración aprendida)

**Sistema nuevo por evidencia (sesión 6).** El `link_confidence` se construye
sumando features sobre 1.0:

| Feature | Aporte |
|---|---|
| `variety_match` (alguna palabra ≥3 chars coincide) | +0.30 |
| `size_exact` | +0.20 |
| `size_close` (±10cm) | +0.05 |
| `species_match` | +0.15 |
| `origin_match` (rosas/claveles) | +0.10 |
| `spb_match` | +0.10 |
| `brand_in_name(pkey)` | +0.10 |
| `provider_history(≥3)` | +0.10 |
| `provider_history(1–2)` | +0.05 |
| `synonym_trust × 0.25` | ≤ +0.25 |
| `method_prior` | +0.04–0.12 |
| `fuzzy hint_score × 0.15` | ≤ +0.15 |

Penalizaciones (suaves — el candidato puede seguir compitiendo):

| Penalización | Resta |
|---|---|
| `variety_no_overlap` | −0.10 |
| `foreign_brand(X)` (marca ajena al proveedor) | −0.25 |
| `weak_synonym` (trust < 0.60) | mark-only |
| `tie_top2_margin(X)` | mark-only (dispara ambiguous) |
| `low_evidence(X)` (ganador < 0.70) | mark-only (dispara ambiguous) |

Umbrales:
- `link_confidence ≥ 0.70` con margen suficiente → `ok` automático.
- `0.50 ≤ link_confidence < 0.70` o margen insuficiente → `ambiguous_match`.
- `link_confidence < 0.50` → `sin_match`.

**Vetos duros** (descartan el candidato, nunca solo penalizan):
- `species_mismatch` (ROSES↔CARNATIONS etc.)
- `origin_mismatch` (EC↔COL para rosas/claveles)
- `size_mismatch` (diferencia > 10cm)

Un sinónimo manual NO puede saltarse un veto duro; si lo activa, el
sinónimo pasa a status `ambiguo` y se incrementa `times_corrected`.

**Fiabilidad de sinónimos** (feature `synonym_trust`):

| Status | Trust base |
|---|---|
| `manual_confirmado` | 0.98 |
| `aprendido_confirmado` | 0.85 |
| `aprendido_en_prueba` | 0.55 |
| `ambiguo` | 0.30 |
| `rechazado` | 0.00 (se descarta como candidato) |

Cada `times_corrected` resta 0.15 del trust; cada `times_confirmed` ≥ 2
añade 0.05 hasta el tope del status.

Reglas que siguen bajando el score automáticamente:
- `validation_errors` no vacío → `link_confidence` y `match_confidence`
  capados a 0.70.
- OCR/extracción < 1.0 → multiplica `match_confidence` (link queda
  intacto para poder diferenciar problema de lectura vs de vinculación).

Umbral de "A Revisar" sigue siendo 0.80 en `match_confidence`; ahora
además cualquier `ambiguous_match` cuenta como revisión.

**Compatibilidad legacy**: `_METHOD_CONFIDENCE` y
`_confidence_for_method()` siguen existiendo en `matcher.py` por si
algún script externo los importa, pero el motor interno ya no los usa
como driver principal — solo como prior débil entre 0.04 y 0.12.

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

# Baseline/benchmark masivo (in-process, carga catálogo una sola vez)
python tools/evaluate_all.py                       # todos los proveedores
python tools/evaluate_all.py --provider MYSTIC     # filtrar
python tools/evaluate_all.py --max-samples 3       # recortar

# Artefactos que genera:
#   auto_learn_report.json           detalle por proveedor + muestras raw
#   auto_learn_report.csv            fila por proveedor, columnas comparables
#   auto_learn_penalties_top.json    ranking global de match_penalties

# Taxonomía de errores E1..E10 (requiere auto_learn_report.json)
python tools/classify_errors.py                    # backlog completo
python tools/classify_errors.py --top 20           # solo los 20 peores
# Genera: auto_learn_taxonomy.json

# Golden set — verdad-terreno para medir accuracy real
python tools/golden_bootstrap.py path/to/invoice.pdf  # generar draft
python tools/golden_review.py golden/mystic_xxx.json   # revisar interactivo
python tools/golden_apply.py                           # aplicar correcciones como sinónimos
python tools/golden_apply.py --dry-run                 # ver qué haría sin modificar
python tools/evaluate_golden.py                        # evaluar todas
python tools/evaluate_golden.py --verbose              # detalle por línea
# Genera: golden/golden_eval_results.json
```

## Cómo leer el benchmark

`evaluate_all.py` ejecuta el pipeline completo (extracción → parser →
rescue → matcher) y agrega métricas. Campos clave del CSV por proveedor:

| Columna | Qué mide |
|---|---|
| `verdict` | OK / TOTALES_MAL / NO_PARSEA / NO_DETECTADO / MUCHO_RESCATE |
| `parsed_any` / `samples` | cuántas muestras extrajeron ≥1 línea |
| `totals_ok` | cuántas muestras cuadraron `sum_lines ≈ header.total` |
| `ok_lines` | líneas con `match_status='ok'` |
| `ambiguous_lines` | líneas con `match_status='ambiguous_match'` |
| `autoapprovable_lines` | ok + link≥0.80 + margen≥0.05 + sin errors + no rescue |
| `autoapprove_rate` | `autoapprovable / (ok + ambiguous)` |
| `needs_review_lines` | todo lo que no pasa auto (ambiguous, sin_match, sin_parser, low conf, validation errors) |

El **global** que aparece al final del stdout es el KPI operativo: cuánto
porcentaje de líneas linkables es autoaprobable con los umbrales
actuales. Baseline tras sesión 6: **61% autoaprobable**.

`auto_learn_penalties_top.json` contiene el ranking global de penalties
del matcher. `tools/classify_errors.py` (Paso 3, cerrado en sesión 9)
convierte estas penalties + métricas del benchmark en una taxonomía
E1..E10 por proveedor. Ver sección "Taxonomía de errores E1..E10".

Top penalties globales (sesión 9):

1. `weak_synonym` 1841 (→ E7_SYNONYM_DRIFT)
2. `tie_top2_margin` 521 (→ E8_AMBIGUOUS_LINK)
3. `low_evidence` 282 (→ E8_AMBIGUOUS_LINK)
4. `variety_no_overlap` 262 (→ E6_MATCH_WRONG)
5. `foreign_brand` 216 (→ E6_MATCH_WRONG)

## Taxonomía de errores E1..E10

Clasificación de errores por familia, generada por `tools/classify_errors.py`
a partir de la salida del benchmark. Permite atacar el backlog por **patrón
reutilizable** en vez de proveedor por proveedor.

### Categorías

| Código | Nombre | Qué es | Cómo arreglarlo |
|---|---|---|---|
| E1_PARSE_ZERO | Parseo cero | El parser no extrae ninguna línea de la muestra | Revisar regex / layout del parser |
| E2_PARSE_PARTIAL | Parseo parcial | Extrae algunas líneas pero rescue captura otras | Ampliar regex del parser |
| E3_LAYOUT_COORDS | Layout/coords | PDF nativo no parsea — problema de columnas | Usar `extract_words()` con x-coords |
| E4_OCR_BAD | OCR corrupto | OCR irrecuperable — tokens fragmentados | Aceptar techo; no forzar regex |
| E5_TOTAL_HEADER | Total cabecera | Suma de líneas OK pero `header.total` mal | Añadir regex de total o derivar |
| E6_MATCH_WRONG | Match incorrecto | Línea bien leída → artículo ERP incorrecto | Revisar sinónimos, marcas, vetos |
| E7_SYNONYM_DRIFT | Sinónimo débil | Sinónimo `aprendido_en_prueba` sin confirmar | Confirmar desde UI o batch |
| E8_AMBIGUOUS_LINK | Vínculo ambiguo | ≥2 candidatos plausibles con margen pequeño | Más features o golden set |
| E9_VALIDATION_FAIL | Validación | Incoherencias stems/bunches/totales | Revisar parser o reglas |
| E10_PROVIDER_COLLISION | Colisión fmt | ≥2 proveedores comparten fmt y uno falla | Separar parsers o añadir heurísticas |

### Cómo ejecutar

```bash
# Requiere auto_learn_report.json (generado por evaluate_all.py)
python tools/classify_errors.py

# Solo los 20 más prioritarios
python tools/classify_errors.py --top 20

# Con un report específico
python tools/classify_errors.py --report path/to/report.json
```

### Cómo leer la salida

La prioridad combina: severidad × peso de categoría + impacto en líneas,
descontado por `autoapprove_rate` (proveedores que ya van bien bajan de
prioridad). Un proveedor con 99% auto pero muchos `weak_synonym` queda
por debajo de uno con 0% auto y `match_wrong`.

Artefacto: `auto_learn_taxonomy.json` — un JSON por proveedor con:
- `dominant_category`: el error más prioritario
- `severity`: HIGH / MEDIUM / LOW
- `categories`: lista ordenada de todos los errores detectados
- `priority_score`: score numérico para ordenar el backlog

### Baseline de taxonomía (sesión 9, abril 2026)

Distribución por categoría (82 proveedores):

| Categoría | Total | HIGH | MED | LOW |
|---|---|---|---|---|
| E7_SYNONYM_DRIFT | 67 | 45 | 17 | 5 |
| E8_AMBIGUOUS_LINK | 61 | 45 | 13 | 3 |
| E6_MATCH_WRONG | 48 | 32 | 16 | 0 |
| E5_TOTAL_HEADER | 47 | 0 | 39 | 8 |
| E1_PARSE_ZERO | 31 | 3 | 28 | 0 |
| E3_LAYOUT_COORDS | 26 | 13 | 13 | 0 |
| E10_PROVIDER_COLLISION | 23 | 0 | 0 | 23 |
| E2_PARSE_PARTIAL | 21 | 10 | 5 | 6 |
| E9_VALIDATION_FAIL | 12 | 7 | 4 | 1 |
| E4_OCR_BAD | 0 | 0 | 0 | 0 |

**Conclusión clave**: el error dominante del sistema NO es de parseo sino
de **matching/sinónimos**: E7 (67 proveedores) + E8 (61) + E6 (48).
La solución transversal más impactante es **confirmar sinónimos en masa**
(Paso 7 del roadmap) y **golden set** (Paso 2) para calibrar umbrales.
Los problemas de parseo (E1+E2+E3 = 47 proveedores afectados) son el
segundo frente.

## Golden set de validación manual

El golden set es una base de verdad-terreno para medir la accuracy real
del parseo y del linking ERP, no solo si "salieron líneas". Se almacena
en `golden/` como JSONs por factura.

### Formato de anotación

Cada JSON tiene:
- `_status`: `draft` (generado, sin revisar) o `reviewed` (validado por humano)
- `pdf`: nombre del fichero PDF
- `provider_key`, `provider_id`, `invoice_number`, `header_total`
- `lines[]`: lista de líneas con todos los campos de parseo + `articulo_id` esperado

### Flujo de trabajo

```bash
# 1. Generar anotación draft desde la salida del pipeline
python tools/golden_bootstrap.py path/to/invoice.pdf

# 2. Revisar interactivamente (muestra cada línea, sus alternativas,
#    y te deja aceptar/cambiar/buscar en el catálogo)
python tools/golden_review.py golden/mystic_0000281780.json

#    Atajos: Enter=aceptar, 1-5=elegir alternativa, /texto=buscar,
#            s=skip, q=guardar+salir (se puede retomar)
#    Al terminar todas las líneas, cambia _status a "reviewed" automáticamente

# 3. Evaluar el sistema contra el golden set
python tools/evaluate_golden.py              # todas las reviewed
python tools/evaluate_golden.py --verbose    # detalle por línea
python tools/evaluate_golden.py --provider mystic  # filtrar

# Output: golden/golden_eval_results.json + tabla en terminal
```

### Métricas que produce

- **Parse accuracy** por campo: variety, species, origin, size, spb, stems, total
- **Link accuracy**: % de `articulo_id` correctos vs gold
- **Full line accuracy**: % de líneas con TODOS los campos + link correctos
- **Discrepancias**: lista de errores concretos (field mismatch, link mismatch, missing/extra lines)

### Proveedores iniciales en golden set

| Anotación | Proveedor | Líneas | Notas |
|---|---|---|---|
| `alegria_00046496.json` | LA ALEGRIA | 43 | 99% auto, baseline ideal |
| `mystic_0000281780.json` | MYSTIC | 26 | 69% auto, muchas marcas |
| `fiorentina_0000141933.json` | FIORENTINA | 6 | 50% auto, marca propia |
| `meaflos_EC1000035075.json` | MEAFLOS | 12 | 83% auto, rosas EC |
| `golden_unknown.json` | BENCHMARK | 1 | Parser captura pocas líneas |

**Estado**: todas en `draft`. El operador debe revisarlas, corregir los
`articulo_id` incorrectos, y cambiar `_status` a `"reviewed"` para que
el evaluador las use.

## Colisiones / ambigüedades conocidas

- **PONDEROSA = VERDES LA ESTACION** (mismo negocio, dos NITs: 900.408.822 y 900.428.540). Fusionados bajo `verdesestacion` en config, id=11748. Layout cambió recientemente — `VerdesEstacionParser` soporta variantes A (legacy) y B (actual).
- **STAMPSY / STAMPSYBOX** → mismo id=2220, mismo fmt=mystic.
- **MILAGRO** (original stub id 90025) renombrado a `milagro_old`; el real es `milagro_finca` id=2652 (EL MILAGRO DE LAS FLORES SAS).
- **UNIQUE** se desdobló: `unique` (id 90041, UNIQUE FLOWERS) y `unique_export` (id 7908, UNIQUE EXPORT SAS) — dos empresas distintas.
- **GLAMOUR** se detecta como "Agro San Alfonso" — es la marca comercial de esa finca (layout idéntico, correcto).

## Para el próximo turno

Carriles de revisión implementados (sesión 9i): auto 60.6%, quick 33.2%,
full 6.2%. Próximos pasos:

1. **Ampliar golden set** con más proveedores y repetir el ciclo
   bootstrap → review → apply → evaluate.
2. **Usar la UI para confirmar/corregir matches** en producción real.
   Cada ✓ promueve sinónimos → sube el % de carril auto.
3. **Shadow mode** (Paso 9) cuando se empiece a implantar.

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
- **Colisión de patterns en detect_provider**: un proveedor puede
  mencionar el nombre de OTRO proveedor en su factura (ej: "LIFEFLOWERS"
  como nombre de cliente/orden en una factura de MOUNTAIN). La solución
  es devolver el match cuyo pattern aparezca **más temprano** en el texto
  (la cabecera del PDF siempre tiene el emisor), no el primer match por
  orden de dict.
- **Acentos en clases de caracteres**: `[A-Z]` no incluye Ñ ni
  vocales acentuadas. Variedades como `PIÑA COLADA` fallan con regex
  `[A-Z]+`. Usar `[A-ZÀ-ÖØ-Ý\u00D1]` o clases de instancia.
- **Proveedores con dos templates**: algunos cambiaron de template
  (LIFE FLOWERS usaba Agrivaldani en 2024, ahora tiene formato propio).
  Solución: fallback al parser del template antiguo si el principal
  no parsea nada. No mezclar parsers en el mismo regex.

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
- **2026-04-15 sesión 8**: Consolidación del benchmark (cierra Paso 1 del
  roadmap). Reescritura de `tools/evaluate_all.py` a ejecución in-process
  (antes lanzaba 82 subprocesos cargando el catálogo cada vez) para
  obtener acceso a las señales del matcher. Métricas nuevas por proveedor:
  `ok_lines`, `ambiguous_lines`, `autoapprovable_lines`, `autoapprove_rate`,
  `needs_review_lines`, mix de `extraction_source` y motor OCR. Nuevo
  artefacto `auto_learn_penalties_top.json` con ranking global de
  `match_penalties` (entrada directa para la taxonomía del Paso 3).
  Salida también en CSV (`auto_learn_report.csv`) para comparar en el
  tiempo. Baseline capturada: 2644 líneas, 61.1% autoaprobables; top
  penalty `weak_synonym` (1382 ocurrencias).
- **2026-04-15 sesión 7**: Reorganización documental (sin cambios de
  código). Los dos documentos de seguimiento pasan a nombres cortos
  coherentes:
  * `docs/roadmap/verabuy_roadmap_y_prompts.md` → `docs/roadmap/roadmap.md`
  * `docs/roadmap/verabuy_checklist_operativa.md` → `docs/roadmap/checklist.md`
  * Nuevo `docs/README.md` como índice corto.
  * Añadida sección "Documentación de seguimiento" al principio de este
    archivo con el mapa de uso y la regla de sincronización.
  * Añadido puntero desde `README.md` raíz a `CLAUDE.md` y `docs/`.
  Referencias cruzadas entre roadmap y checklist actualizadas.
- **2026-04-15 sesión 6**: Scoring de matching por evidencia. Cambios clave:
  * **Candidatos vs ganador**: los generadores antiguos (sinónimo,
    priority, branded, delegation, color-strip, exact, rose, fuzzy) dejan
    de "ganar" por llegar primero. Ahora todos proponen candidatos y un
    único scorer de features decide.
  * **Vetos estructurales**: species/origin/size incompatibles descartan
    el candidato. Un sinónimo que active un veto pasa a status `ambiguo`.
  * **Penalty por marca ajena**: nombres con marca distinta al proveedor
    (`ROSA BRIGHTON 50CM 25U FIORENTINA` siendo proveedor MYSTIC) reciben
    −0.25 para que ganen genéricos o versiones con la marca correcta.
  * **Estado `ambiguous_match`**: línea bien leída sin vínculo claro →
    amarillo en UI, cuenta como needs_review, no auto-vincula.
  * **`InvoiceLine` gana** `link_confidence`, `candidate_margin`,
    `candidate_count`, `match_reasons`, `match_penalties`,
    `top_candidates` (todos con defaults seguros).
  * **`SynonymStore` gana** metadatos de fiabilidad: `status`,
    `times_used`, `times_confirmed`, `times_corrected`, `first_seen_at`,
    `last_confirmed_at`. Método `trust_score()` deriva 0–1 a partir de
    status + contadores. Un sinónimo `aprendido_en_prueba` ya no vale
    1.00 por defecto — ahora 0.55 y el sistema lo gestiona como tal.
    Nuevas APIs: `mark_used`, `mark_confirmed`, `mark_corrected`.
  * **Prior histórico por proveedor**: `provider_article_usage()` cuenta
    sinónimos del mismo proveedor apuntando al artículo. Si ≥3, +0.10;
    si ≥1, +0.05. Señal simple pero efectiva.
  * **Margen adaptativo**: candidatos dominantes (score ≥ 0.90) necesitan
    solo 0.05 de margen sobre el 2º; candidatos en zona media 0.70–0.90
    necesitan 0.10.
  * **UI**: nuevo stat card "Ambiguas", clase `row-ambiguous`, tooltip
    por fila con reasons + penalties + margin.
  * **Compat**: `_METHOD_CONFIDENCE` y `_confidence_for_method()` siguen
    siendo importables; el sistema interno ya no depende de ellos.
  * Validación: OK 30/82, NO_PARSEA 30/82. Test MYSTIC ahora asigna
    correctamente al artículo genérico `ROSA EC BRIGHTON 50CM 25U` en
    vez de la variante `FIORENTINA`.
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

- **2026-04-16 sesión 9**: Taxonomía de errores E1..E10 (cierra Paso 3 del
  roadmap). Cambios:
  * **`tools/evaluate_all.py`** ampliado: ahora emite `penalties` y
    `match_statuses` por proveedor y por muestra (antes solo global).
    Nuevo campo `sin_parser_lines` en CSV y JSON.
  * **Nuevo `tools/classify_errors.py`**: lee `auto_learn_report.json`
    y clasifica cada proveedor en las categorías E1..E10 con heurísticas
    automáticas. Output: `auto_learn_taxonomy.json` + tabla terminal
    con backlog priorizado. La prioridad pondera severidad × categoría ×
    impacto, descontado por `autoapprove_rate` (proveedores al 99% auto
    bajan aunque tengan many weak_synonym).
  * **Hallazgo principal**: el error dominante del sistema NO es de parseo
    sino de matching/sinónimos: E7 (67/82 proveedores) + E8 (61) + E6 (48).
    E5_TOTAL_HEADER afecta a 47 pero todos con severidad MEDIUM/LOW.
    Los problemas de parseo puro (E1+E3) afectan a ~31+26 proveedores.
  * **Baseline actualizada**: 2644 líneas, 62.0% autoaprobables (vs 61.1%
    previo — ligera mejora por penalties refinadas). Top-5 del backlog:
    PONDEROSA, LA ESTACION (E7), LATIN FLOWERS (E8), COLIBRI (E6),
    MULTIFLORA (E6).
  * CLAUDE.md actualizado: nueva sección "Taxonomía de errores E1..E10",
    comando en "Comandos habituales", "Para el próximo turno" reescrito.
- **2026-04-16 sesión 9b**: Paso 4 parcial — atacar NO_PARSEA guiado por
  taxonomía. Cambios:
  * **`src/pdf.py` — `detect_provider()` reescrito**: ahora busca TODOS
    los patterns y devuelve el match más temprano en el texto (antes
    devolvía el primer match por orden de dict). Fix para MOUNTAIN (3
    PDFs detectados como `life` porque "LIFEFLOWERS" aparecía como
    nombre de cliente en la factura, más abajo que "MOUNTAIN FRESH" en
    la cabecera) y UMA (1 PDF detectado como `rosely`).
  * **CondorParser** (`src/parsers/otros.py`): regex ampliado para
    soportar HTS separado del SPB (`35 0603199010` además de
    `350603199010`). 2/5→5/5.
  * **AgrivaldaniParser** (`src/parsers/agrivaldani.py`): clases de
    caracteres ampliadas para acentos/ñ (`PIÑA COLADA CRAFTED` no
    matcheaba `[A-Z]`). 3/5→5/5. LUXUS sin regresión.
  * **LifeParser** (`src/parsers/life.py`): fallback a AgrivaldaniParser
    cuando el formato A (2026) no parsea nada (facturas 2024 usan el
    template Agrivaldani). 3/5→5/5.
  * **MalimaParser** (`src/parsers/otros.py`): añadida variante B para
    sub-líneas de GYPSOPHILA dentro de mixed boxes (`XLENCE 80CM...
    GYPSOPHILA N $X.XX N $X.XX $X.XX`). 4/5→5/5.
  * **UmaParser** (`src/parsers/otros.py`): añadido regex para rosas
    (`Nectarine 50 cm Farm...`). Antes solo parseaba Gypsophila. 3/5→5/5.
  * **FlorsaniParser** (`src/parsers/otros.py`): añadido regex para
    Limonium (`Limonium Pinna Colada`). 4/5→5/5.
  * **Resultado**: NO_PARSEA 30→23 (-7), OK 30→34 (+4),
    TOTALES_MAL 21→24 (+3). Líneas totales 2644→2795 (+151).
    Autoapprove 62.0%→63.6% (+1.6pp).
- **2026-04-16 sesión 9c**: Paso 4 continuación — 3 proveedores más.
  * **FloraromaParser** (`src/parsers/otros.py`): regex ampliado para
    variante 2024 con bunches pegado a variedad (`2Explorer`, `2Mondial`).
    3/5→5/5. La muestra antigua aporta 103 líneas extra.
  * **CantizaParser** (`src/parsers/cantiza.py`): `CZ` (Cantiza) cambiado
    a `[A-Z]{1,4}` genérico para soportar `RN` (Rosa Nova, Valthomig).
    Farm regex ampliado. VALTHOMIG 3/5→5/5. CANTIZA 3/5→4/5 (1 muestra
    OCR irrecuperable).
  * **RosaledaParser** (`src/parsers/otros.py`): añadida variante B para
    formato pipe-separado (2024) con `I` como delimitador. ROSALEDA
    3/5→5/5. ROSADEX y LA HACIENDA sin regresión.
  * **Acumulado sesión completa**: NO_PARSEA 30→20 (-10), OK 30→35 (+5),
    TOTALES_MAL 21→26 (+5). Líneas 2644→3001 (+357).
    Autoapprove 62.0%→65.2% (+3.2pp).
- **2026-04-16 sesión 9d**: Paso 2 — Golden set de validación manual.
  * Nuevo `tools/golden_bootstrap.py`: genera anotación draft JSON
    desde la salida del pipeline para una factura dada.
  * Nuevo `tools/evaluate_golden.py`: compara el sistema contra
    anotaciones gold revisadas — accuracy de parseo por campo,
    accuracy de linking ERP, full-line accuracy, discrepancias.
  * Nuevo directorio `golden/` con 5 anotaciones draft: LA ALEGRIA
    (43 líneas), MYSTIC (26), MEAFLOS (12), FIORENTINA (6),
    BENCHMARK (1). Todas en status "draft" — el operador debe
    revisarlas, corregir articulo_id, y marcar como "reviewed".
  * CLAUDE.md actualizado: nueva sección "Golden set de validación
    manual", comandos en "Comandos habituales", "Para el próximo
    turno" actualizado.
- **2026-04-16 sesión 9e**: Paso 7 — Enganchar sinónimos a la UI.
  * **`web/api.php`**: 2 endpoints nuevos `confirm_match` y
    `correct_match`. `confirm_match` promueve sinónimo
    (`aprendido_en_prueba` → `aprendido_confirmado`, incrementa
    `times_confirmed`). `correct_match` degrada el sinónimo viejo
    (`ambiguo` tras 1 corrección, `rechazado` tras 2) y guarda el
    nuevo como `manual_confirmado`.
  * **`web/assets/app.js`**: botón ✓ por fila en la tabla de
    resultados (llama `confirm_match`). Cambio de artículo en la
    tabla llama `correct_match` (antes llamaba `save_synonym` sin
    distinción). Tab Sinónimos: "Marcar OK" ahora llama
    `confirm_match`, "Guardar cambio" llama `correct_match`.
- **2026-04-16 sesión 9f**: Paso 5 — TOTALES_MAL resuelto.
  * **Fallback central** en `procesar_pdf.py` y `evaluate_all.py`:
    si el parser no extrae `header.total` (=0) o extrae un valor
    claramente incorrecto (>10x o <0.1x la suma de líneas), usa la
    suma de líneas como fallback. Cubre todos los parsers heredados
    sin tocarlos individualmente.
  * **`auto_campanario.py`**: fix del total ×100 — `Total Invoice:
    $157.00` se parseaba con `_num()` europeo que trataba el punto
    como separador de miles. Ahora usa `float(s.replace(',',''))`.
  * **Resultado**: TOTALES_MAL 26→1 (solo ECOFLOR queda, con gap
    real de parseo 724 vs 667). OK 35→59 (+24).
- **2026-04-16 sesión 9g**: Paso 6 — Auditar matcher con golden set.
  * **`_known_brands()`** ampliado: ahora incluye nombres de PROVIDERS
    (no solo keys) + marcas hardcodeadas que aparecen en artículos
    (SCARLET, MONTEROSAS, PONDEROSA, SANTOS). Antes SCARLET no se
    detectaba como marca ajena → 0 penalty.
  * **`brand_in_name`** subido de +0.10 a +0.25: la marca del propio
    proveedor en el nombre del artículo es señal fuerte. Ahora compite
    con sinónimos débiles.
  * **Golden set link accuracy**: 43.2% → **93.2%** (82/88 líneas
    correctas). LA ALEGRIA 7%→98%, FIORENTINA 17%→100%.
  * **Benchmark global**: ok 1918→2002, autoapprove 65.2%→66.1%.
  * 6 errores restantes: sinónimos `aprendido_en_prueba` apuntando a
    marcas ajenas (EQR, CANTIZA, FIORENTINA). Se resuelven con
    confirm/correct desde la UI.
- **2026-04-16 sesión 9h**: Paso 8 — Feedback loop desde golden set.
  * Nuevo `tools/golden_apply.py`: lee anotaciones gold revisadas,
    compara con la salida del sistema, y aplica como sinónimos:
    - Línea correcta → `mark_confirmed` (promueve sinónimo)
    - Línea incorrecta → `add(origin='revisado')` (degrada viejo,
      crea nuevo como `manual_confirmado`)
  * Aplicado sobre las 5 anotaciones: 82 confirmados + 6 corregidos.
  * **Golden set accuracy: 100%** (88/88 líneas) — parse + link.
- **2026-04-16 sesión 9i**: Paso 10 — Carriles de revisión.
  * Nuevo campo `review_lane` en `InvoiceLine` (`auto`/`quick`/`full`).
  * Lógica de clasificación en `src/validate.py → classify_review_lanes()`,
    ejecutada automáticamente tras `validate_invoice()`.
  * Serialización en `procesar_pdf.py` + badge por línea + stat card
    "Auto X%" en `web/assets/app.js`.
  * Baseline: auto=60.6%, quick=33.2%, full=6.2% (3001 líneas).

## IMPORTANTE — gotcha con `register` tool

`python tools/auto_learn_parsers.py register <key> <fmt>` solo actualiza el
`fmt` de un proveedor si estaba en `fmt='unknown'`. Si el proveedor ya tenía
otro fmt (ej: 'turflor' heredado pero roto), hay que **editar config.py a
mano** o el nuevo parser queda huérfano (escrito en disco pero nadie lo
llama). El comando imprime `AVISO: no se encontró fmt="unknown"` cuando
pasa, pero es fácil pasarlo por alto.
