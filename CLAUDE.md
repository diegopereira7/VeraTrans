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
├── pdf.py            pdfplumber → pdftotext → EasyOCR (con preproceso OpenCV)
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

1. **Extracción de texto** — [src/pdf.py](src/pdf.py) `extract_text()`
   - pdfplumber (nativo) → pdftotext → EasyOCR con preproceso OpenCV (denoise + deskew + binarización adaptativa)
   - Publica `get_last_ocr_confidence()` (1.0 si nativo, 0.x si OCR)
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
ocr_confidence, match_confidence, field_confidence, validation_errors
```

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

- **78 REGISTRADO_OK** — detectados y con parser funcional
- **5 REGISTRADO_STUB** — detectados pero `fmt='unknown'` (pendientes de parser):
  `CEAN GLOBAL`, `ELITE`, `FESO`, `MOUNTAIN`, `NATIVE BLOOMS`, `SAN FRANCISCO`, `ZORRO`
- **7 LOGISTICA** — filtrados por SKIP_PATTERNS del batch:
  `ALLIANCE`, `DSV`, `EXCELE CARGA`, `LOGIZTIK`, `REAL CARGA`, `SAFTEC`, `VERALEZA` (la buyer)

**Carpeta de entrenamiento** del usuario (ruta fija):
```
C:\Users\diego.pereira\Desktop\DOC VERA\FACTURAS IMPORTACION\PROVEEDORES
```
Contiene subcarpeta por proveedor con 5 facturas nuevas + 2 antiguas (para regresión). `marca_prov.txt` en la raíz mapea `FOLDER_NAME|id_proveedor` (IDs de tabla `proveedores` en la BD VeraBuy).

## Parsers aprendidos (auto_*.py)

| Parser | Proveedores que lo usan |
|---|---|
| `auto_farin` | FARIN |
| `auto_qualisa` | QUALISA, BELLAROSA |
| `auto_agrinag` | AGRINAG |
| `auto_natuflor` | NATUFLOR (dual: colombiano + SaaS, delega en auto_agrinag) |
| `auto_campanario` | GREENGROWERS, EL CAMPANARIO (mismo template Lasso) |
| `auto_floreloy` | FLORELOY |
| `auto_sanjorge` | SAN JORGE |
| `auto_milagro` | MILAGRO (EL MILAGRO DE LAS FLORES SAS) |

## Signals al usuario (UI)

Nuevas tarjetas + badges añadidos a [web/assets/app.js](web/assets/app.js):

- **A Revisar**: líneas con `match_confidence < 0.80` OR `sin_match` OR `sin_parser` OR `llm_extraido` OR con `validation_errors`. Excluye `mixed_box`.
- **Totales**: ✓ si `sum_lines ≈ header.total ±1%`, si no muestra diff en rojo
- **Precio Anómalo**: precios con >15% desvío vs histórico del proveedor
- **OCR**: aparece solo si el PDF es escaneado; muestra % confianza media
- **Omitidos** (lote): cuenta archivos filtrados por SKIP_PATTERNS, con detalle expandible

Clases CSS de fila: `row-sin-parser` (ámbar), `row-sin-match` (rosa), `row-has-error` (rojo borde), `row-low-conf` (naranja borde).

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

Si el usuario pide "seguir con los difíciles" o "atacar los stubs pendientes", son:
- CEAN GLOBAL (factura electrónica colombiana columnar)
- ELITE (Alstroemeria multi-variedad por caja)
- FESO (factura electrónica, similar CEAN)
- MOUNTAIN (layout poco estándar)
- NATIVE BLOOMS (tropical foliage)
- SAN FRANCISCO (Hydrangeas, datos escasos)
- ZORRO (1 sola muestra, riesgo overfit)

Si pide "evaluar los existentes", usar `python tools/auto_learn_parsers.py evaluate <carpeta>` uno por uno y solo tocar los que muestren gaps reales.
