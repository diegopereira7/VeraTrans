# Arquitectura del VeraBuy Traductor

Referencia técnica detallada: árbol del código, pipeline end-to-end,
matcher (scoring por evidencia), golden set, comandos con todos los
flags. La instrucción operativa vive en [`../CLAUDE.md`](../CLAUDE.md).

---

## Árbol del código

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
├── parsers/          ~40 parsers específicos por proveedor
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

web/
├── index.php         UI (tabs: Procesar / Lote / Historial / Sinónimos / Auto)
├── api.php           Orquesta llamadas Python vía shell_exec
├── assets/app.js     Frontend (1400+ líneas)
└── assets/style.css  Badges, row states, stat cards
```

## Flujo

Cada factura recorre este pipeline **idéntico** tanto en individual
como en lote:

1. **Extracción de texto** — [src/pdf.py](../src/pdf.py) →
   [src/extraction.py](../src/extraction.py)
   - Triage por página: pdfplumber intenta extraer texto; si una
     página está por debajo de un umbral de caracteres útiles o ratio
     alfanumérico, se marca `scan`. Resto de páginas: `native`.
   - Si todo es nativo → salida directa (rápido).
   - Si hay `scan`: intenta **OCRmyPDF** (genera PDF con capa OCR
     Tesseract, se relee con pdfplumber). Si OCRmyPDF no está
     disponible cae a OCR per-page: **Tesseract directo** (pytesseract)
     → **EasyOCR** (último recurso), con preproceso OpenCV (denoise +
     deskew + binarización adaptativa). EasyOCR agrupa segmentos por
     y-centro del bbox.
   - Publica dos señales:
     - `get_last_ocr_confidence()`: 1.0 si nativo, 0.x si OCR (compat API).
     - `get_last_extraction()`: `ExtractionResult` con `confidence`,
       `source` (`native|mixed|ocr|empty`), `ocr_engine`
       (`ocrmypdf|tesseract|easyocr`) y `degraded`.
2. **Detección de proveedor** — `detect_provider()` busca en
   `PROVIDERS[*].patterns`, devuelve el match **más temprano** en el
   texto.
3. **Parser específico** — `FORMAT_PARSERS[fmt].parse(text, provider_data)`
   devuelve `(InvoiceHeader, [InvoiceLine])`.
4. **Split mixed boxes** — separa `RED/YELLOW` en dos líneas.
5. **Rescate** — regex genérico para líneas que el parser no cazó →
   `match_status='sin_parser'`, `extraction_source='rescue'`.
6. **Matching** — [src/matcher.py](../src/matcher.py) **scoring por
   evidencia**. Los antiguos 7 etapas siguen existiendo pero como
   *generadores de candidatos*, no como decisores finales:
   - Se recolectan candidatos de: sinónimo, búsqueda priorizada,
     delegación, color-strip, exact, branded, rose EC/COL, fuzzy top-5.
   - Se aplican **vetos estructurales**: species/origin/size
     incompatibles descartan el candidato — ni un sinónimo manual
     puede saltarse esto.
   - Se puntúa cada candidato con features reales (variety, size,
     species, origin, spb, marca en nombre, histórico del proveedor,
     trust del sinónimo) + prior débil por método.
   - Se penaliza marca ajena (`foreign_brand` −0.25) para evitar
     asignar un artículo con marca FIORENTINA a un proveedor MYSTIC
     cuando hay genéricos disponibles.
   - Gana el candidato con score más alto SI tiene margen suficiente
     sobre el 2º. Con margen escaso entra en `ambiguous_match`.
7. **LLM fallback** — para `sin_parser`, si hay `ANTHROPIC_API_KEY`
   (no-op sin clave).
8. **Validación cruzada** — `stems == bunches × spb`,
   `line_total ≈ stems × price`, `sum(lines) ≈ header.total`.
9. **Reconciliación** — precio vs media histórica del proveedor
   (desvío >15% = anómalo).
10. **Serialización** — cada línea lleva: campos de dominio +
    `match_confidence`, `ocr_confidence`, `validation_errors`,
    `needs_review`, `review_lane`.

## Matching

Sistema de **scoring por evidencia** (sesión 6). El `link_confidence`
se construye sumando features.

### Features (aportan score)

| Feature | Aporte |
|---|---|
| `variety_match` (alguna palabra ≥3 chars coincide) | +0.30 |
| `size_exact` | +0.20 |
| `size_close` (±10cm) | +0.05 |
| `species_match` | +0.15 |
| `origin_match` (rosas/claveles) | +0.15 |
| `spb_match` | +0.10 |
| `brand_in_name(pkey)` | +0.25 |
| `provider_history(≥3)` | +0.10 |
| `provider_history(1–2)` | +0.05 |
| `synonym_trust × 0.25` | ≤ +0.25 |
| `method_prior` | +0.04–0.12 |
| `fuzzy hint_score × 0.15` | ≤ +0.15 |

### Penalizaciones (suaves — el candidato puede seguir compitiendo)

| Penalización | Resta |
|---|---|
| `variety_no_overlap` | −0.10 |
| `foreign_brand(X)` (marca ajena al proveedor) | −0.25 |
| `weak_synonym` (trust < 0.60) | mark-only |
| `tie_top2_margin(X)` | mark-only (dispara ambiguous) |
| `low_evidence(X)` (ganador < 0.70) | mark-only (dispara ambiguous) |

### Umbrales

- `link_confidence ≥ 0.70` con margen suficiente → `ok` automático.
- `0.50 ≤ link_confidence < 0.70` o margen insuficiente →
  `ambiguous_match` (solo si top1 tiene `variety_match` o
  `hint_score` ≥ 0.85; si no → `sin_match`).
- `link_confidence < 0.50` → `sin_match`.

Margen requerido adaptativo:

- `top1.score ≥ 1.05` → margen 0.02 (evidencia rica)
- `top1.score ≥ 0.90` → margen 0.05
- `top1.score ∈ [0.70, 0.90)` → margen 0.10

### Vetos duros (descartan el candidato, no solo penalizan)

- `species_mismatch` (ROSES ↔ CARNATIONS etc.)
- `origin_mismatch` (EC ↔ COL para rosas/claveles)
- `size_mismatch` (diferencia > 10 cm)

Un sinónimo manual NO puede saltarse un veto duro; si lo activa, el
sinónimo pasa a status `ambiguo` y se incrementa `times_corrected`.

### Fiabilidad de sinónimos

Feature `synonym_trust`:

| Status | Trust base |
|---|---|
| `manual_confirmado` | 0.98 |
| `aprendido_confirmado` | 0.85 |
| `aprendido_en_prueba` | 0.55 |
| `ambiguo` | 0.30 |
| `rechazado` | 0.00 (se descarta como candidato) |

Cada `times_corrected` resta 0.15 del trust; cada `times_confirmed`
≥ 2 añade 0.05 hasta el tope del status.

### Brand boost y scores >1.0

Si `brand_by_provider[pid]` existe y aparece en el nombre del artículo
Y el candidato tiene `variety_match` + `size_exact` (no basta
`size_close`), se aplica `score = max(score, 1.05)`.

El score interno del candidato **no se clampa arriba**. Un candidato
con sinónimo confirmado + histórico + variety/size/species/spb/origin
puede acumular ~1.40. Esto da desempates reales cuando el brand_boost
aplica un piso de 1.05 a varios candidatos con marca propia.
`line.link_confidence` sí se clampa a 1.0 para la UI y
`match_confidence = link × ocr × ext`.

### Reglas que bajan el score automáticamente

- `validation_errors` no vacío → `link_confidence` y
  `match_confidence` capados a 0.70.
- OCR/extracción < 1.0 → multiplica `match_confidence` (link queda
  intacto para poder diferenciar problema de lectura vs de
  vinculación).

### Compatibilidad legacy

`_METHOD_CONFIDENCE` y `_confidence_for_method()` siguen existiendo en
[src/matcher.py](../src/matcher.py) por si algún script externo los
importa, pero el motor interno ya no los usa como driver principal —
solo como prior débil entre 0.04 y 0.12.

## Golden set

El golden set es una base de verdad-terreno para medir la accuracy
real del parseo y del linking ERP, no solo si "salieron líneas". Se
almacena en `golden/` como JSONs por factura.

### Formato de anotación

Cada JSON tiene:

- `_status`: `draft` (generado, sin revisar) o `reviewed` (validado
  por humano)
- `pdf`: nombre del fichero PDF
- `provider_key`, `provider_id`, `invoice_number`, `header_total`
- `lines[]`: lista de líneas con todos los campos de parseo +
  `articulo_id` esperado

### Flujo de trabajo

```bash
# 1. Generar anotación draft desde la salida del pipeline
python tools/golden_bootstrap.py path/to/invoice.pdf

# 2. Revisar interactivamente
python tools/golden_review.py golden/mystic_0000281780.json
#    Atajos: Enter=aceptar, 1-5=elegir alternativa, /texto=buscar,
#            s=skip, q=guardar+salir (se puede retomar)
#    Al terminar todas las líneas, cambia _status a "reviewed" automáticamente

# 3. Evaluar el sistema contra el golden set
python tools/evaluate_golden.py              # todas las reviewed
python tools/evaluate_golden.py --verbose    # detalle por línea
python tools/evaluate_golden.py --provider mystic  # filtrar
```

### Métricas que produce

- **Parse accuracy** por campo: variety, species, origin, size, spb,
  stems, total
- **Link accuracy**: % de `articulo_id` correctos vs gold
- **Full line accuracy**: % de líneas con TODOS los campos + link
  correctos
- **Discrepancias**: lista de errores concretos (field mismatch, link
  mismatch, missing/extra lines)

### Proveedores iniciales en golden set

| Anotación | Proveedor | Líneas | Notas |
|---|---|---|---|
| `alegria_00046496.json` | LA ALEGRIA | 43 | 99% auto, baseline ideal |
| `mystic_0000281780.json` | MYSTIC | 26 | 69% auto, muchas marcas |
| `fiorentina_0000141933.json` | FIORENTINA | 6 | 50% auto, marca propia |
| `meaflos_EC1000035075.json` | MEAFLOS | 12 | 83% auto, rosas EC |
| `golden_unknown.json` | BENCHMARK | 1 | Parser captura pocas líneas |

Todas revisadas al 2026-04-17. `evaluate_golden.py` confirma 100%
parse + link accuracy.

## Cómo leer el benchmark

[tools/evaluate_all.py](../tools/evaluate_all.py) ejecuta el pipeline
completo (extracción → parser → rescue → matcher) y agrega métricas.
Campos clave del CSV por proveedor:

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

El **global** que aparece al final del stdout es el KPI operativo:
cuánto porcentaje de líneas linkables es autoaprobable con los
umbrales actuales.

`auto_learn_penalties_top.json` contiene el ranking global de
penalties del matcher. [tools/classify_errors.py](../tools/classify_errors.py)
convierte estas penalties + métricas del benchmark en una taxonomía
E1..E10 por proveedor (ver [`taxonomy.md`](taxonomy.md)).

## Comandos con flags completos

Versión compacta de los comandos básicos en
[`../CLAUDE.md`](../CLAUDE.md). Aquí todos con sus variantes:

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
python batch_process.py carpeta_con_pdfs/ --output resultado.xlsx

# Benchmark masivo
python tools/evaluate_all.py                       # todos los proveedores
python tools/evaluate_all.py --provider MYSTIC     # filtrar
python tools/evaluate_all.py --max-samples 3       # recortar

# Taxonomía de errores
python tools/classify_errors.py                    # backlog completo
python tools/classify_errors.py --top 20           # solo los 20 peores
python tools/classify_errors.py --report path/to/report.json

# Golden set
python tools/golden_bootstrap.py path/to/invoice.pdf
python tools/golden_review.py golden/<prov>_<id>.json
python tools/golden_apply.py                       # aplicar correcciones
python tools/golden_apply.py --dry-run             # sin modificar
python tools/evaluate_golden.py                    # todas las reviewed
python tools/evaluate_golden.py --verbose
python tools/evaluate_golden.py --provider mystic
```

Artefactos que genera el benchmark:

- `auto_learn_report.json` detalle por proveedor + muestras raw
- `auto_learn_report.csv` fila por proveedor, columnas comparables
- `auto_learn_penalties_top.json` ranking global de match_penalties
- `auto_learn_taxonomy.json` (vía classify_errors) backlog priorizado
- `golden/golden_eval_results.json` (vía evaluate_golden)
