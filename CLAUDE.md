# CLAUDE.md — Guía operativa para el agente

**Última actualización:** 2026-04-28 (sesión 12f — DAFLOR mixed→MIXTO + GOLDEN inline color + tools/reparse_batch.py)
**Estado:** **96.3% autoapprove** (récord, +0.3pp tras revisión del batch que añadió 48 sinónimos confirmados) · 3596 líneas · ok 3415 · ambiguous 55 · Golden 985/995 link 99.0% / 984/997 full_line 98.7% (regresión esperada heredada de 12d, golden file congelado con split 50/50 — pendiente regenerar). Sesión 12f cierra revisión del batch real (114 facturas reprocesadas in-place): (a) DAFLOR colapsa `Virginia/Dubai`/`Assorted` etc. a una sola línea `MIXTO`, captura `Selecto/Fancy` cuando aparece en la 3ª línea del formato colgado, y extrae label de las 3 posiciones (inline tras grade, colgado tras btype, junto al grade lookahead) limpiando `MARCA `; (b) GOLDEN/BENCHMARK añade layout secundario `CARNATION FANCY <COLOR> <LABEL>` (sin `CONSUMER BUNCH`, color inline tipo `DARK PINK`/`BICOLOR`) con helper `_translate_inline_color` y labels ARCEDIANO/CORUNA/ELIXIR/ORQUIDEA — antes salía como NO PARSEADO; (c) nuevo `tools/reparse_batch.py` que re-procesa un batch desde cero preservando ediciones manuales (label, _deleted, articulo_id manual) y mergeando por `raw_description` — bug crítico cazado: faltaba propagar `pdf_path` a `pdata`, lo que tiraba silenciosamente AlegriaParser al fallback de texto y restaba 130 ok-matches al batch (LAILA salía con 0 líneas). Sesiones 12d (CONDOR/MAXI/NATIVE/GOLDEN MIX) y 12c (MILONGA CMap) archivadas en [`docs/sessions.md`](docs/sessions.md).

---

## TL;DR — léeme siempre al empezar

**Proyecto:** VeraBuy Traductor — extrae líneas de facturas PDF de
proveedores de flores, las traduce a artículos del catálogo VeraBuy,
mantiene diccionario de sinónimos aprendidos. Dos frontends (CLI +
Web PHP), mismo pipeline Python. Desarrollo: Diego Pereira. Operador
del UI en producción (facturas reales que alimentan el shadow): Ángel
Panadero — cuando se mencione "Ángel" en sessions/estado se refiere
a acciones del operador en la UI, no al desarrollador.

**Reglas críticas** (detalle en "Reglas de oro" más abajo):
1. Usa `Read`/`Glob`/`Grep`/`Edit`/`Write` del harness. Nunca
   `find`/`grep`/`cat` desde Bash.
2. Parsers: solo tocar con evidencia (`evaluate_all.py` con gap real).
   Cambios **aditivos** (`_RE_B` junto al `_RE_A`, nunca borrar).
3. Variety en MAYÚSCULAS siempre; decimales con coma:
   `.replace(',', '.')` según contexto.
4. Al terminar el turno: actualiza "Estado actual" y "Historial
   reciente" (ver Política de actualización al final).

## Estado actual (fuente única de verdad)

**Métricas (post-12c, 2026-04-27)**

- Autoapprove **96.0%** sobre líneas linkables (récord 96.1% en 12b).
- Benchmark: 3566 líneas · ok 3355 · ambiguous 54 · needs_review 245.
- Golden: **997/997** (link 100%, full_line 99.8%, 1 link_mismatch
  residual sobre branded nuevo del catálogo).
- Buckets: OK 79 · NO_PARSEA 3 (CEAN GLOBAL, NATIVE BLOOMS,
  SAYONARA OCR-corrupto) · NO_DETECTADO 1 (PONDEROSA edge) ·
  TOTALES_MAL 0.
- Top penalties: weak_synonym 278 · variety_no_overlap 161 ·
  foreign_brand 159 · color_modifier_extra 58 · tie_top2_margin 57.

**Catálogo y persistencia (invariantes)**

- 44,751 artículos en MySQL. Solo `referencia` con prefijo **F\***
  (flor de corte, 15,342 arts) entra al pool del matcher. A\*
  (deprecated) y P\* (plantas) se indexan por `id` / `id_erp` /
  `referencia` para lookup UI pero el matcher no los propone
  (sesión 11f).
- **`id_erp`** (varchar) es la fuente de verdad para vínculos
  sinónimo↔artículo. El `id` autoincrement se renumera en cada
  reimport del catálogo desde phpMyAdmin. `SynonymStore` guarda
  ambos campos; el matcher hace lazy-remap si el id local quedó
  desfasado (sesión 10q).
- Marcas: `brand_by_provider` top-1 + `brands_by_provider` (multi-marca,
  ej. Uma usa UMA en rosas y VIOLETA en paniculata, sesión 10o).
  Cuando provider_id config ≠ catalog_provider_id, registrar a mano
  vía `catalog_brands` en PROVIDERS (sesión 10p, Tierra Verde).
- `synonym_key` normaliza puntuación con `normalize_variety_key()`
  en `src/models.py` (colapsa no-alfanuméricos a espacios). Cliente
  PHP/JS y `batch_process.py` aplican la misma normalización
  (sesión 10m).
- Auto-confirmación de sinónimos: `register_match_hit` promueve
  `aprendido_en_prueba → aprendido_confirmado` tras ≥2 hits con
  evidencia no-sinónimo (variety+size o variety+brand). Gate evita
  bootstrapping circular (sesión 10g).

**Shadow mode (Fase 10)** — captura propuesta vs decisión del
operador en `shadow_log.jsonl`. `tools/shadow_report.py` cruza por
`synonym_key` y separa confirmaciones / correcciones / rescates.
Activo desde sesión 10k. `--verify-current` filtra entradas
obsoletas tras parser fixes (sesión 11b).

**Última sesión** — 2026-04-27 (12c): MILONGA OCR condicional para
PDFs con CMap roto (`ocr_if_corrupt: r'\bRlse\b'`). Detalle en
"Historial reciente" abajo. Histórico completo en
[`docs/sessions.md`](docs/sessions.md).

### Próximos pasos posibles

1. **Auditar dedupe / line-merging en otros parsers**. AGRIVALDANI
   tenía un `seen={}` final que sumaba líneas de cajas distintas
   (eliminado post-12c, además captura MARK como `label`). Política
   confirmada por usuario: **ningún parser debe sumar líneas, ni
   aunque variety/size/spb coincidan** — cada caja física es una
   fila. Buscar patrones similares en parsers no auditados.
2. **Box-code-in-variety pendiente** en SAYONARA (SP), APOSENTOS
   (ILIAS), MONTEROSA (EUGENIA), EL CAMPANARIO (ZAIRA). Patrón ya
   resuelto en GARDA, MYSTIC, LIFE, ROSALEDA, TURFLOR, PONDEROSA.
   Atender solo cuando aparezca en errores de shadow reales o se
   quiera eliminar penalty residual.
3. **UI `lookup_article` por id_erp/referencia**. Backend ya
   persiste `articulo_id_erp`. Falta que el frontend
   ([`web/assets/app.js`](web/assets/app.js) ~línea 1479,
   `lookup_article` call en batch-line-save) acepte buscar por
   id_erp/referencia, no solo `id` autoincrement.
4. **`shadow_report.py --top-missing-articles`**: listar variedades
   `sin_match` por frecuencia para priorizar altas en ERP
   (MYSTIC/VALTHOMIG son típicos según Ángel).
5. **NO_PARSEA restantes** (CEAN GLOBAL, NATIVE BLOOMS, SAYONARA
   64811): ROI bajo — cerrado en 10h salvo cambio de prioridad.

## Documentación de seguimiento

Este archivo cubre **instrucción operativa + estado actual**. Para
detalle:

- [`docs/roadmap/roadmap.md`](docs/roadmap/roadmap.md) — plan a 12
  pasos con prompts ejecutables.
- [`docs/roadmap/checklist.md`](docs/roadmap/checklist.md) — tablero
  operativo, próximo bloque activo.
- [`docs/architecture.md`](docs/architecture.md) — tree detallado del
  código, flujo end-to-end, matcher por evidencia, golden set,
  comandos con flags.
- [`docs/sessions.md`](docs/sessions.md) — historial completo de
  sesiones.
- [`docs/lessons.md`](docs/lessons.md) — lecciones transversales
  reutilizables.
- [`docs/providers.md`](docs/providers.md) — parsers auto_*,
  colisiones, skip patterns.
- [`docs/taxonomy.md`](docs/taxonomy.md) — errores E1..E10 detallado.

Regla: si pasan días entre sesiones, **sincroniza primero**
`docs/roadmap/` con el estado de este archivo antes de ejecutar nada
nuevo.

---

## Reglas de oro (no negociables)

1. **No llamar APIs externas nuevas.** Usa Claude Code (agente) para
   generar parsers, no la API. Excepción: LLM fallback con
   `ANTHROPIC_API_KEY`.
2. **No tocar parsers existentes "por estética".** Solo si
   `evaluate_all.py` demuestra un gap real.
3. **No añadir campos obligatorios a `InvoiceLine`.** Siempre default
   para no romper parsers legacy.
4. **No usar `find`/`grep`/`cat` desde Bash.** El harness ofrece
   `Glob`, `Grep`, `Read`.
5. **No crear docs markdown nuevos** salvo que el usuario los pida.
6. **No intentar arreglar facturas OCR-muy-corruptas con regex.**
   Aceptar pass_ratio 80% en esos casos.
7. **No mezclar proveedores distintos bajo el mismo `fmt`** salvo que
   compartan plantilla SaaS idéntica (ej: QUALISA+BELLAROSA,
   GREENGROWERS+EL CAMPANARIO).
8. **Vinculación de artículos — `id_erp` es la fuente de verdad**
   (sesión 10q). Siempre que se persista un vínculo
   sinónimo↔artículo (JSON, MySQL `sinonimos`, golden, shadow log),
   guardar `articulo_id_erp` **además** del `articulo_id`
   autoincrement. El `id_erp` sobrevive a reimports del catálogo;
   el `id` local no. En la UI (búsqueda de artículos), el usuario
   debe poder identificar por `id_erp` o `referencia` (código
   administrativo estable) — el `id` autoincrement es accesorio.

### Gotcha con el comando `register`

`python tools/auto_learn_parsers.py register <key> <fmt>` solo
actualiza el `fmt` si el proveedor estaba en `fmt='unknown'`. Si ya
tenía otro fmt (ej. `turflor` heredado pero roto), hay que **editar
`config.py` a mano** o el nuevo parser queda huérfano. El comando
imprime `AVISO: no se encontró fmt="unknown"` — fácil de pasar por
alto.

---

## Árbol del código (resumen)

Ver [`docs/architecture.md`](docs/architecture.md) para descripción
por archivo.

```
src/
  config.py, models.py, articulos.py, sinonimos.py, historial.py,
  matcher.py (scoring evidencia), extraction.py (triage+OCR),
  pdf.py (wrapper), validate.py, reconciliation.py, llm_fallback.py,
  parsers/ (~40, incluye auto_*), learner/

procesar_pdf.py  batch_process.py  tools/  golden/  web/
```

## Flujo end-to-end (resumen)

Detalle completo en [`docs/architecture.md#flujo`](docs/architecture.md#flujo).

1. **Extracción** — triage por página; nativo vs OCRmyPDF vs EasyOCR
   fallback.
2. **Detect provider** — match más temprano en el texto.
3. **Parser específico** — `FORMAT_PARSERS[fmt].parse()`.
4. **Split mixed boxes** — separa RED/YELLOW en dos líneas.
5. **Rescue** — regex genérico para líneas que el parser no cazó.
6. **Matching** — scoring por evidencia, vetos duros, margen
   adaptativo.
7. **LLM fallback** — solo si `ANTHROPIC_API_KEY`, solo para
   `sin_parser`.
8. **Validación cruzada** — stems, totales, line_total.
9. **Reconciliación** — precio vs histórico ≥ últimas 20
   hojas/proveedor.
10. **Serialización** — match_confidence, validation_errors,
    needs_review, review_lane.

---

## Modelo de datos (contrato crítico)

`InvoiceLine` tiene estos campos. Leerlos antes de tocarlos:

```python
raw_description, species, variety, grade, origin, size, stems_per_bunch,
bunches, stems, price_per_stem, price_per_bunch, line_total, label, farm,
box_type, provider_key,
articulo_id, articulo_name, match_status, match_method,
ocr_confidence, extraction_confidence, extraction_source,
match_confidence, link_confidence, field_confidence, validation_errors,
candidate_margin, candidate_count, match_reasons, match_penalties,
top_candidates, review_lane
```

- `extraction_confidence` (0.0–1.0) es señal agregada del PDF, no solo
  del OCR. `extraction_source`: `native|mixed|ocr|empty|rescue`
  (rescue = capturado por `rescue_unparsed_lines`, pintado distinto
  en la UI).
- `link_confidence` (0.0–1.0): vínculo aislado con el artículo ERP.
  `match_confidence = link × ocr × extraction`.
- `candidate_margin`, `match_reasons`/`match_penalties`,
  `top_candidates`: trazabilidad del matcher (ver sección Matching).
- `match_status`: `ok | ambiguous_match | sin_match | sin_parser |
  pendiente | mixed_box | llm_extraido`. `ambiguous_match` cuenta
  como needs_review.
- `species`: `ROSES | CARNATIONS | HYDRANGEAS | ALSTROEMERIA |
  GYPSOPHILA | CHRYSANTHEMUM | OTHER`.
- `origin`: `EC | COL | otros` (prefijo `ROSA EC` vs `ROSA COL` en
  `expected_name()`).

## Convenciones de parsers (obligatorias)

Cada parser cumple este contrato en [src/parsers/](src/parsers/):

```python
class <Name>Parser:
    def parse(self, text: str, provider_data: dict) -> tuple[InvoiceHeader, list[InvoiceLine]]:
```

Parsers **auto-generados** usan prefijo `auto_`:
`src/parsers/auto_<key>.py` con `class AutoParser`.

**Reglas al escribir/modificar parsers:**

1. **Nunca lanzar excepciones por línea mal formada** — saltar
   (`continue`) y dejar que `rescue_unparsed_lines` lo recoja.
2. **Variety en MAYÚSCULAS siempre** (`.strip().upper()`). El matcher
   indexa así.
3. **Rellenar `stems_per_bunch` incluso con default** (25 rosas, 20
   claveles) — 0 rompe `expected_name()`.
4. **`origin` importante**: determina el prefijo del nombre esperado
   (`ROSA EC` vs `ROSA COL`).
5. **`line_total` siempre con 2 decimales**: la validación cruzada
   compara con tolerancia 2%.
6. **Derivar `header.total` de suma de líneas** si el parser no lo
   extrajo:
   ```python
   if not header.total and lines:
       header.total = round(sum(l.line_total for l in lines), 2)
   ```
7. **Cambios en parser existente = aditivos**. Si hay que soportar
   variante nueva, añadir regex `_RE_B` junto a `_RE_A` y probar
   ambos. **Nunca borrar** un regex que ya funciona con facturas en
   producción.

## Añadir / evaluar parsers

Añadir (stub → funcional): `extract_samples.py <FOLDER>` → escribir
`src/parsers/auto_<key>.py` → `validate <key> <carpeta>` → si
`pass_ratio ≥ 0.70` → `register <key> auto_<key>` → `evaluate
<carpeta>`. `register` actualiza `src/parsers/__init__.py` + `fmt` en
`src/config.py` (solo si estaba en `unknown`).

Evaluar sin tocar: `python tools/auto_learn_parsers.py evaluate
"ruta/<PROVEEDOR>"`. Devuelve `detected`, `parsed_any`, `totals_ok`,
`total_rescued` por muestra. **Regla de oro:** si da 100% en los 3
primeros + 0 rescued → NO tocar. Solo modificar parsers con gaps
probados.

---

## Matching: scoring por evidencia

Tablas compactas — detalle y notas históricas en
[`docs/architecture.md#matching`](docs/architecture.md#matching).

### Features (aportan score)

| Feature | Aporte |
|---|---|
| `variety_match` (alguna palabra ≥3 chars coincide) | +0.30 |
| `variety_full` (todos los tokens de la variedad cubiertos) | +0.10 |
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

### Penalizaciones

| Penalización | Resta |
|---|---|
| `variety_no_overlap` | −0.10 |
| `foreign_brand(X)` | −0.25 |
| `generic_vs_own_brand` (genérico cuando hay branded propio en pool) | −0.15 |
| `color_modifier_extra(X)` (OSCURO/CLARO/PASTEL… en nombre no pedido) | −0.12 |
| `weak_synonym` (trust < 0.60) | mark-only |
| `tie_top2_margin(X)` | mark-only (dispara ambiguous) |
| `low_evidence(X)` (ganador < 0.70) | mark-only (dispara ambiguous) |

**Vetos duros** (descartan candidato): `species_mismatch`,
`origin_mismatch` (EC↔COL rosas/claveles), `size_mismatch` (>10 cm).

**Umbrales**: `link ≥ 0.70` + margen → `ok`; `0.50 ≤ link < 0.70` o
margen bajo → `ambiguous_match` (solo si top1 tiene `variety_match` o
`hint_score ≥ 0.85`); `link < 0.50` → `sin_match`. Margen adaptativo:
`≥1.05 → 0.02`, `≥0.90 → 0.05`, `[0.70, 0.90) → 0.10`.

### Fiabilidad de sinónimos

| Status | Trust base |
|---|---|
| `manual_confirmado` | 0.98 |
| `aprendido_confirmado` | 0.85 |
| `aprendido_en_prueba` | 0.55 |
| `ambiguo` | 0.30 |
| `rechazado` | 0.00 (se descarta como candidato) |

Cada `times_corrected` resta 0.15; cada `times_confirmed ≥ 2` añade
0.05 hasta el tope del status.

---

## Carriles de revisión (`review_lane`)

Cada línea recibe un carril automáticamente tras validación
([src/validate.py](src/validate.py) → `classify_review_lanes`). La UI
muestra un badge por línea y un stat card con el % de auto.

| Carril | Criterio | Acción |
|---|---|---|
| `auto` | link ≥ 0.80, match ≥ 0.80, margen ≥ 0.05, sin errors, extracción ≥ 0.80, no rescue | No necesita revisión |
| `quick` | Match ok pero no cumple todos los criterios de auto | Revisión rápida |
| `full` | sin_match, sin_parser, rescue, OCR < 0.50, ambiguo con link < 0.50 | Revisión completa |

Distribución se regenera con `python tools/evaluate_all.py`.

**Cómo subir el % de auto:** confirmar sinónimos ✓ desde UI (sube
trust), corregir matches (degrada sinónimo malo), ampliar golden set
+ `golden_apply.py`, arreglar parsers NO_PARSEA.

## Signals al usuario (UI)

Tarjetas + badges en [web/assets/app.js](web/assets/app.js):
**A Revisar** (match_conf<0.80 o sin_match/sin_parser/llm_extraido/
validation_errors), **Totales** (✓ si sum_lines ≈ header.total ±1%),
**Precio Anómalo** (>15% vs histórico), **Extracción OCR/Mixta**
(tooltip con motor ocrmypdf/tesseract/easyocr), **Omitidos** (lote).

Clases CSS de fila: `row-sin-parser` (ámbar), `row-rescue` (lila
discontinuo), `row-ambiguous` (amarillo), `row-sin-match` (rosa),
`row-has-error` (rojo borde), `row-low-conf` (naranja borde).

Cada fila lleva un `title=` con las `match_reasons` y
`match_penalties` que decidieron el vínculo, más el
`candidate_margin`. Es la forma rápida de que el operador entienda
"ganó por X, perdió puntos por Y".

## Comandos habituales

```bash
# Procesar una factura individual
python procesar_pdf.py ruta/al.pdf

# Evaluar un parser existente
python tools/auto_learn_parsers.py evaluate "ruta/a/carpeta/<PROVEEDOR>"

# Benchmark global (KPI operativo)
python tools/evaluate_all.py

# Taxonomía de errores (requiere auto_learn_report.json)
python tools/classify_errors.py

# Golden set
python tools/golden_bootstrap.py path/to/invoice.pdf
python tools/golden_review.py golden/<prov>_<id>.json
python tools/evaluate_golden.py

# Shadow mode (Fase 10) — agrega shadow_log.jsonl
python tools/shadow_report.py
python tools/shadow_report.py --since 2026-04-01 --provider BRISSAS
python tools/shadow_report.py --verify-current   # filtra shadow stale

# Aprender parser nuevo
python tools/auto_learn_parsers.py validate <key> <carpeta>
python tools/auto_learn_parsers.py register <key> auto_<key>

# Lote con Excel
python batch_process.py carpeta_con_pdfs/ --output resultado.xlsx
```

Comandos con flags (`--provider`, `--max-samples`, `--verbose`,
`--dry-run`) en
[`docs/architecture.md#comandos-con-flags-completos`](docs/architecture.md#comandos-con-flags-completos).

---

## Historial reciente

Solo las 2 últimas sesiones. Todas las anteriores en
[`docs/sessions.md`](docs/sessions.md).

### 2026-04-28 — sesión 12f: review batch — DAFLOR + GOLDEN inline-color + reparse_batch tool

Sesión de revisión del batch real (`20260427083117_229c58c3`, 114
facturas) tras los fixes de 12d/12e. Tres correcciones nuevas + un
tool de reproceso que preserva ediciones manuales del operador.

(a) **DAFLOR — cajas mixtas, grade lookahead y label tri-fuente**
[`src/parsers/otros.py`](src/parsers/otros.py) `DaflorParser`. Tres
problemas observados en el batch:

1. *Variedad `Virginia/Dubai` (mixta) se splitteaba 50/50 en
   sublíneas Virginia + Dubai con destinos artificiales*. Fix:
   variedad con `/` o `ASSORTED` → `MIXTO` en una sola línea.
2. *Grade `Selecto`/`Fancy` perdido en el formato colgado*. La
   plantilla tiene 3 líneas por entrada y el grade aparece en la
   3ª (`Selecto 0603190107` o `Selecto ASTURIAS 0603190107`). Fix:
   variable `grade_pending_il` que apunta a la línea recién creada
   sin grade; la siguiente iteración del loop la rellena si empieza
   por Selecto/Fancy/Super. Normaliza `Selecto`→`SELECT`.
3. *Label perdido*. Hay 3 sitios donde aparece el destino:
   - Inline tras grade: `1 QB Alstroemeria Assorted - Fancy MARCA DECO - - 200 200 Stems...`
   - Colgado tras btype: `1 QB MARCA PYTI - - 200 200 Stems...`
   - Junto al grade lookahead: `Selecto ASTURIAS 0603190107`
   Fix: extracción específica para cada caso, prefijo `MARCA `
   eliminado, dashes residuales limpios.

Resultado en batch: las 14 líneas DAFLOR ahora con variety MIXTO
(no splitted), grade SELECT/FANCY correcto, labels DECO/PYTI/
ASTURIAS/LUCAS preservados, suma cuadra al total $798.

(b) **GOLDEN/BENCHMARK — layout secundario `CARNATION FANCY <COLOR>` con destino**
[`src/parsers/golden.py`](src/parsers/golden.py). Las facturas
Benchmark traen, además del estándar `CONSUMER BUNCH CARNATION
FANCY R45- MIX WH RD CB S2 ...`, líneas tipo:
```
1 Q 300 300 CARNATION FANCY DARK PINK ARCEDIANO FCY DP S2 DP 0.180 54.00
3 Q 300 900 CARNATION FANCY BICOLOR ARCEDIANO BICOLORES S2 BI 0.180 162.00
```
(sin `CONSUMER BUNCH`, color inline tras `FANCY`, label en medio,
item code `S2 <abrev>` distinto de `CB`/`MC`). Antes: NO PARSEADO.

Fix: nuevo bloque alternativo en la regex `desc_m` que captura
`CARNATION (FANCY|SELEC) (DARK|LIGHT)? <COLOR>`. Helper
`_translate_inline_color` traduce `DARK PINK`→`ROSA OSCURO`,
`LIGHT BLUE`→`AZUL CLARO`, etc. Item code `\b(CB|MC|S\d+)\s+\S+\s*$`
amplía el patrón de stripping. Set `_LABELS` ampliado:
ARCEDIANO, CORUNA, ELIXIR, ORQUIDEA. Spb se mantiene en 20 (clavel
regular) — solo `MINICARNS` marca mini, **no** este layout (el
operador confirmó: ARCEDIANO/CORUÑA son destinos, no mini-claveles).

Resultado: 4 líneas ARCEDIANO de BG-106379 ahora se parsean y
matchean a `CLAVEL FANCY {BICOLOR,ROSA OSCURO,ROSA,AMARILLO} 70CM
20U GOLDEN`.

(c) **`tools/reparse_batch.py` — reproceso de batch preservando ediciones**
Nueva herramienta. Lee `batch_status/{id}.json`, encuentra los PDFs
en `batch_uploads/{id}/`, los re-extrae con la pipeline actual y
mergea con los datos viejos por `raw_description`:

- **Preserva del viejo**: `_deleted` (líneas borradas), `label`
  (destino editado a mano por el operador), `articulo_id` cuando
  el operador asignó manualmente y la nueva línea quedó
  sin/ambiguous (siempre que `match_method` indique manual).
- **Toma del nuevo**: variety/size/spb/stems/precios/totales (lo
  que el parser actualizado extrae) y `articulo_id` cuando viene
  vía sinónimo aprendido (los sinónimos persisten entre runs).
- **Splits→merge**: si N líneas viejas comparten `raw_description`
  y la nueva extracción produce 1 línea (ej. cajas MIX de Golden
  o Daflor que ahora son MIXTO), se toma la nueva tal cual y se
  descartan las correcciones de las sublíneas — ese es el caso
  que motiva el reproceso.
- **Counters**: recalcula `ok_count`/`sin_match`/`needs_review`
  por factura y `procesadas_ok`/`con_error`/`total_usd` global.

Bug detectado en la primera iteración: no se propagaba `pdf_path`
a `pdata`. AlegriaParser usa `pdfplumber.extract_tables()` desde
ahí; sin la ruta, caía silenciosamente al fallback de texto. Tras
el fix, LAILA pasó de 0→15 líneas y el reproceso global +130 ok
matches.

Uso: `python tools/reparse_batch.py <batch_id>`.

**Métricas globales** (post-12f):
- Benchmark global: **3596 líneas, ok 3415, ambig 55**, autoapprove
  **96.3% (récord, +0.3pp)** tras los sinónimos confirmados durante
  la revisión del batch (de 3801 a 3849 sinónimos en la sesión).
- DAFLOR (batch): 14 líneas, suma cuadra al $798 del total real
  de la factura.
- Batch del operador (`20260427083117_229c58c3`): 114/114 facturas
  ok, 1874 líneas, 1795 ok, 155 needs_review (vs 280 pre-fix).
- **Golden 985/995 link 99.0% / 984/997 full_line 98.7%** (regresión
  esperada: el golden file `benchmark_103685.json` quedó congelado
  con la conducta vieja del split 50/50 multi-color — pendiente
  regenerarlo con `golden_bootstrap.py`).

**Lección transversal** (candidata
[`docs/lessons.md`](docs/lessons.md)): cuando un parser usa
infraestructura externa al texto (pdfplumber.extract_tables(),
imágenes, OCR), un script auxiliar que re-ejecute el pipeline
debe pasarle TODO el contexto que el flujo principal le pasa —
no solo el texto. El bug de `pdf_path` en `reparse_batch.py`
estuvo ~1 hora oculto porque "el parser no fallaba", solo caía a
un fallback peor sin avisar. Auditar otros sitios que recreen
`pdata` (no debería haber muchos: `procesar_pdf.py`,
`evaluate_all.py`, `reparse_batch.py`).

### 2026-04-27 — sesión 12e: APOSENTOS — 3 variantes nuevas + total real impreso + MINI CLAVEL COL

Ángel mostró una factura APOSENTOS donde el total de la fila salía
$2,125.00 cuando el real era $3,915.00 (gap de $1,790 = 1 línea
faltante de 10 cajas + 2 sub-líneas) y el badge de "Parcial" no
disparaba. Diagnóstico:

**Causa raíz**:
1. El regex de `AposentosParser` solo aceptaba `CARNATIONS` como
   cabecera de línea. Las facturas tienen también `MINICARNATIONS`
   (mini claveles, spb=10) y `CLAVEL SURTIDO` (mezcla en español).
2. En `CLAVEL SURTIDO DUTY FREE FANCY ...` la descripción entre el
   tipo y `DUTY FREE` está vacía, y el regex exigía `\s+(.+?)\s+`
   (al menos un char).
3. El separador entre grade y `CO-XXXX` admitía solo `[.0\s]+`
   pero hay líneas con label `R14`: `FANCY R14 CO-0603129000`.
4. **Crítico**: `header.total = sum(l.line_total for l in lines)` —
   es decir, el "total" de la cabecera siempre era la suma de las
   líneas parseadas. Cuando una línea no parseaba, el sum cuadraba
   trivialmente y la validación cruzada nunca detectaba el hueco.

**Fix multi-pieza** ([`src/parsers/otros.py`](src/parsers/otros.py)
`AposentosParser`):

(a) **Cabecera de línea ampliada** —
`(MINICARNATIONS?|CARNATIONS|CLAVEL\s+SURTIDOS?)`. Token detectado
controla `spb_default` (10 para MINI, 20 resto) y maneja `CLAVEL
SURTIDO` mapeando a `variety='MIXTO'` (descarta el `(no pink)` u
otra exclusión entre paréntesis del desc).

(b) **Descripción opcional** — `(?:\s+(.+?))?` permite que la línea
no traiga descripción específica entre tipo y `DUTY FREE`.

(c) **Separador label-tolerante** — `(?:[A-Za-z0-9.]+\s+)*CO-`
acepta `R14`, `R-14`, `0`, `.`, etc. entre grade y `CO-XXXX`.

(d) **Total real impreso** —
`re.search(r'Total\s+Value\s*\$?\s*([\d,]+\.\d{2})', text)`
(con fallback a `SubTotal Value`). `header.total` ahora es el total
impreso; sólo cae al `sum(lines)` si la factura no expone ningún
total parseable. La validación cruzada vuelve a tener señal: si
falta una línea por parsear, `sum_lines != header.total` y la UI
pinta "Parcial" en la cabecera.

**Cambio en matcher** ([`src/models.py`](src/models.py) línea ~140):
`expected_name` para `species='CARNATIONS'` no-golden ahora prefija
`MINI CLAVEL COL` cuando `spb=10`. El catálogo tiene la familia
`MINI CLAVEL COL FANCY/SELECT <COLOR> 70CM 10U` (id 26772+) que
antes era inalcanzable por nombre exacto desde proveedores no-Golden
(solo lograba match vía sinónimo). Aposentos `MINICARNATIONS ZUMBA
RED` ahora propone `MINI CLAVEL COL SELECT ROJO 70CM 10U` como
candidato — la variedad ZUMBA específica no existe en catálogo, por
lo que el ganador final es ambiguous_match (operador confirma desde
UI).

**Métricas**:
- Benchmark global: 3589 líneas (+23 vs 12d), ok 3376 (+0 — los
  +23 nuevos son ambiguous/needs_review en samples APOSENTOS), ambig
  56 (+0), autoapprove **96.0% estable**.
- APOSENTOS: bucket TOTALES_MAL → **OK**. 5/5 detect/parsed,
  4/5 totales_ok (1 sample OCR-corrupto sigue 391/791), 32/35 ok,
  **97% autoapprove sobre el folder**. Antes: 29 líneas, 26 ok.
  Ahora: 35 líneas (+6 — descubre líneas que antes simplemente no
  parseaba), 32 ok (+6).
- Factura del usuario en
  `batch_uploads/20260427083117_229c58c3/APOSENTOS.pdf`: 4/4 líneas
  (antes 3/3 con la 4ta perdida). Total $3,915 = sum_lines $3,915 ✓.
- Golden 988/995 (regresión heredada de 12d con `benchmark_103685`
  congelado a la conducta vieja del split 50/50 — pendiente
  regenerar el golden file con el comportamiento nuevo).

**Lección transversal**: si el parser deriva `header.total` de
`sum(lines)`, las líneas que no parsean **nunca** disparan el aviso
de validación, porque el `sum_lines == header.total` es
trivialmente cierto. El total impreso de la factura es la única
señal independiente. Auditar otros parsers que hagan
`h.total = sum(...)` sin fallback a un total parseado del texto:
`grep -n "h.total = sum\|h.total = round(sum"` en `src/parsers/`.

---

## Política de actualización (obligatoria)

Al terminar cada turno con cambios:

1. **Estado actual**: reemplaza métricas (autoapprove, golden,
   NO_PARSEA, última sesión). No acumules.
2. **Historial reciente**: añade la sesión nueva al principio. Si ya
   había 2, mueve la más antigua a [`docs/sessions.md`](docs/sessions.md).
3. Lección transversal → [`docs/lessons.md`](docs/lessons.md).
   Específica de sesión → basta en `sessions.md`.
4. Parser nuevo → tabla de [`docs/providers.md`](docs/providers.md).
5. Contrato de `InvoiceLine` o convenciones → sección
   correspondiente **de este archivo**.
