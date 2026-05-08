# CLAUDE.md — Guía operativa para el agente

**Última actualización:** 2026-05-08 (sesión 12q — helper preventivo `extract_printed_total` en 7 parsers `auto_*`)
**Estado:** **96.1% autoapprove** estable · 3615 líneas · ok 3442 · ambiguous 56 · Golden 992/993 link 99.9% / 993/995 full_line 99.8%. Sesión 12q aplica el patrón de 12p preventivamente a los 7 parsers `auto_*` sin sample activo (auto_elite, auto_natuflor, auto_zorro, auto_sanjorge, auto_sanfrancisco, auto_rosabella, auto_agrosanalfonso). Estos parsers hacían `h.total = sum(lines)` ciegamente — cuando llegue una factura con líneas perdidas, el gap quedaba invisible. Fix: nuevo helper `src/parsers/_helpers.py::extract_printed_total(text)` que prueba 13 patrones comunes (`TOTAL FOB`, `Total Value $`, `INVOICE TOTAL (Dólares)`, `Amount Due`, `TOTAL A PAGAR`, `TOTALS N $ USD`, etc.) con normalización robusta de números US/EU. Cada parser ahora intenta el helper antes de caer al sum. 2 tests añadidos (29/29 OK), benchmark/golden estables. Sesión 12p archivada en [`docs/sessions.md`](docs/sessions.md).

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

**Última sesión** — 2026-04-29 (12m): limpieza técnica
(archivos huérfanos) + tests de regresión (13 tests unittest)
+ correcciones de catálogo del operador (Mystic CARROUSEL,
Maxiflores COLOR MIXTO, Mystic MISS PIGGY eliminado). Detalle
en "Historial reciente" abajo.

### Próximos pasos posibles

**Acción operativa (requiere operador / decisión de catálogo)**:

1. **Casos del shadow `--top-missing-articles`** — el reporte
   ya genera lista accionable. Ejemplos del último run:
   - Tessa MONDIAL spb=10 × 6 rescates → resuelto en 12j (era
     bug del parser, no falta de catálogo).
   - Brissas GARDEN ROSE APPLE 50/60 (3+3 rescates) → alta en
     ERP del artículo "ROSA GARDEN APPLE BRISSAS" si el
     operador lo confirma.
   - Mystic CAROUSEL spb=25 (3 rescates) → alta en ERP.
   - Maxiflores ASSORTED/SPECIAL ASSTD 60 spb=25 (3+3
     rescates) → mapear a SURTIDO MIXTO.
   - Agrivaldani RED MIKADO/PURPLE IRISCHKA/PINK IRISCHKA
     50/60 spb=10 (2 c/u) → spray roses, posiblemente alta o
     mapeo confirmado.
   Comando: `python tools/shadow_report.py --top-missing-articles 30`.

**Deuda preventiva** (auditorías sin evidencia activa):

2. **Total impreso en 7 parsers `auto_*` sin sample** (deuda
   12g): auto_elite, auto_natuflor, auto_zorro, auto_sanjorge,
   auto_sanfrancisco, auto_rosabella, auto_agrosanalfonso. El
   `h.total = sum(lines)` sin total impreso es bug silencioso
   (no rompe pipeline pero esconde líneas faltantes). Aplicar
   patrón cuando llegue una factura del proveedor.
3. **NO_PARSEA restantes** (CEAN GLOBAL, NATIVE BLOOMS, SAYONARA
   64811): ROI bajo — cerrado en 10h salvo cambio de prioridad.

**Auditorías ya cerradas** (sin deuda activa, salvar para
referencia futura):

- ✓ **Variety regex restrictiva** (post-12i): grep
  `[A-Za-z][A-Za-z\s\-]+?` en `src/parsers/`. Verificado en
  sesión 12k contra el batch del operador — no hay líneas
  perdidas con apóstrofe o dígito en variety. Nota: si llega
  una factura con `Pink O'Hara`, `Mayra's Bridal`, `RM001` o
  similar de un proveedor distinto a Garda, revisar.
- ✓ **Prefijo de caja obligatorio** (post-12i): patrón parent
  `<box_n>/<total>` con sub-líneas heredando `last_btype`.
  Verificado en sesión 12k — los gaps del batch ya fueron
  cerrados en 12i. Si aparece nueva factura con sub-líneas
  perdidas, mismo enfoque: regex sin prefijo, herencia de
  estado.
- ✓ **`BUNCHES STEMS` confundido con `spb`** (post-12j):
  verificado en sesión 12k contra el batch del operador. Las
  anomalías de spb=10 en VerdesEstacion/VALTHO/VUELVEN son
  legítimas (el PDF dice `ROSES*10STEMS` o `X 10` o `10ST`
  explícitamente).
- ✓ **Dedupe / line-merging**: verificado, ningún parser
  suma líneas hoy. AGRIVALDANI eliminado post-12c.
- ✓ **Box-code-in-variety** en SAYONARA (SP), APOSENTOS
  (ILIAS), MONTEROSA (EUGENIA), EL CAMPANARIO (ZAIRA): sin
  evidencia activa en batch ni shadow log. Atender si aparece.
- ✓ **UI `lookup_article` por id_erp/referencia**: implementado
  desde sesión 10r (backend rechaza id autoincrement, frontend
  usa id_erp/referencia con placeholder explícito).
- ✓ **`shadow_report --top-missing-articles`**: implementado
  con scoring (3×rescates + pendientes + foreign_only).
- ✓ **Golden set actualizado tras 12d/12h** (sesión 12l):
  `benchmark_103685` regenerado, `meaflos_EC1000035075`
  añadida línea MONDIAL 1200. Golden 992/993 link 99.9% / 993/995
  full_line 99.8%. Queda 1 link_mismatch en `mystic_0000281780`
  (MISS PIGGY → CANTIZA en gold vs MISS WHITE en sistema por
  sinónimo del operador) — decisión del operador, dejado intacto.

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

# Tests de regresión (sesión 12m, unittest built-in)
python -m unittest tests.test_parser_regressions
python -m unittest tests.test_parser_regressions -v   # detalle por test
python -m unittest tests.test_parser_regressions.TestMeaflosParser   # un caso
```

Comandos con flags (`--provider`, `--max-samples`, `--verbose`,
`--dry-run`) en
[`docs/architecture.md#comandos-con-flags-completos`](docs/architecture.md#comandos-con-flags-completos).

---

## Historial reciente

Solo las 2 últimas sesiones. Todas las anteriores en
[`docs/sessions.md`](docs/sessions.md).

### 2026-04-29 — sesión 12l: regenerar 2 golden files desactualizados → 985/995 → 992/993

Sesión de cierre de la regresión heredada de 12d que se
arrastraba en el TL;DR como "Golden 985/995 link 99.0% / 984/997
full_line 98.7% (regresión esperada heredada de 12d, golden file
congelado con split 50/50 — pendiente regenerar)". Diagnóstico:
2 golden files con discrepancias reales por cambios de
comportamiento del parser desde su creación.

**(a) `golden/benchmark_103685.json`** — el parser viejo (pre-12d)
splitteaba cajas multi-color en sub-líneas por color (ROSA 250 +
BLANCO 250 + ROJO 250 + ...). El parser actual (post-12d)
consolida cajas mixtas a una sola línea `MIXTO`. El gold quedó
congelado con la conducta vieja (32 líneas split por color),
mientras el sistema ahora produce 29 líneas consolidadas.
Suma idéntica en ambos: $3494 = $3494 ✓.

Fix: regeneré el gold completo desde el PDF original (en
`C:/Users/diego.pereira/Desktop/DOC VERA/.../BENCHMARK/`) usando
el pipeline actual. Marqué con `_regenerated` + razón. Status
sigue `reviewed` (el sistema actual es la verdad terreno).

**(b) `golden/meaflos_EC1000035075.json`** — el gold tenía 12
líneas con `sum=$1332` pero `header_total=$1632`, exactamente
$300 menos. La línea faltante es `MONDIAL 50cm 1.200 stems $300`
que el parser viejo perdía por el bug `(\d+)` en stems no acepta
`1.200` (separador de miles con punto), arreglado en sesión 12h.

Fix: añadí la línea MONDIAL 1200 al gold en posición correcta.
Ahora 13 líneas con sum=$1632 ✓.

**(c) `golden/mystic_0000281780.json`** — link_mismatch entre
gold (`MISS PIGGY` → 35818 `ROSA MISS PIGGY 50CM 25U CANTIZA`)
y sistema (`MISS PIGGY` → 33558 `ROSA EC MISS WHITE 50CM 25U`).
Causa: sinónimo `442|ROSES|MISS PIGGY|50|25` está
`aprendido_confirmado` (times_confirmed=2) apuntando a
`ROSA EC MISS WHITE 50CM 25U`. El operador cambió de criterio
post-creación del gold. **Decisión**: dejado intacto, requiere
revisión del operador (¿cuál de los dos es realmente correcto?).

**Resultado** (`tools/evaluate_golden.py`):

| Métrica | Antes (12k) | Ahora (12l) |
|---|---|---|
| Gold lines | 997 | 995 |
| variety | 99.3% | **100%** |
| species | 99.6% | **100%** |
| origin | 99.6% | **100%** |
| size | 99.6% | **100%** |
| stems_per_bunch | 99.4% | 99.8% |
| stems | 99.3% | **100%** |
| line_total | 99.3% | **100%** |
| articulo_id | 99.0% (985/995) | **99.9% (992/993)** |
| full_line | 98.7% (984/997) | **99.8% (993/995)** |
| Discrepancias | 6 link + 4 miss + 2 extra | **1 link** |

**Métricas globales** (post-12l): 3598 líneas, ok 3420,
autoapprove 96.3% estable (no cambia, las regeneraciones de
golden no afectan el benchmark `evaluate_all`).

**Lección transversal**: cuando un fix de parser cambia el
**número** o **composición** de líneas que produce (no solo el
contenido de cada línea), los golden files quedan invalidados.
Política: tras un fix así (12d MIXTO consolidación, 12h MEAFLOS
miles), correr `evaluate_golden.py` y regenerar los golden
afectados desde el PDF original (manteniendo `_status=reviewed`
y añadiendo `_regenerated` + razón). Si no se hace, el roadmap
arrastra una "regresión esperada" indefinida que esconde
desviaciones reales.

### 2026-04-29 — sesión 12m: limpieza técnica + tests de regresión + correcciones de catálogo del operador

Sesión disparada por feedback directo del operador (Diego) tras
revisar el shadow report:

> "Brissas garden rose apple es apple jack, Carousel suele ser
> Carrousel con 2 r, Assorted significa mixto, surtido mixto o
> color mixto. Miss piggy en mystic no puede ser de cantiza
> tiene que ser el genérico si no hay marca propia"

**(A) Limpieza técnica**: borrados 7 archivos huérfanos en raíz
(`agrival_out.json`, `garda_out.json`, `milonga_out.json`,
`ponderosa_out.json`, `rosaleda_out.json`, `milonga_400.png`,
`milonga_page1.png` — outputs ad-hoc de debugging sin
referencia en código). Añadidos patrones `*_out.json`,
`milonga_*.png`, `altas_erp.txt` al `.gitignore`.

**(B) Tests de regresión** ([`tests/test_parser_regressions.py`](tests/test_parser_regressions.py)):
13 tests con `unittest` (sin nueva dependencia) cubriendo los
fixes de las sesiones 12g–12l. Cada test cita la sesión que
introdujo el comportamiento y usa los PDFs reales del batch del
operador. Cobertura:
- `TestMeaflosParser`: Garden Roses (12h) + stems con miles
  + total cuadra para 3 facturas MEAFLOS.
- `TestUmaParser`: sub-líneas mixed-box (12i).
- `TestGardaParser`: variety con apóstrofes + dígitos (12i)
  + total cuadra.
- `TestVerdesEstacionParser`: variety colgada en línea anterior
  (12i).
- `TestTessaParser`: bunches no confundidos con spb + bunches
  poblados (12j).
- `TestFlorsaniParser`: multi-invoice `Single Flowers` (12g).
- `TestPrestigeParser`: total impreso `TOTAL A PAGAR` (12g).
- `TestNativeParser`: total con espacios OCR (12g).

Todos pasan en ~11s. Comando: `python -m unittest tests.test_parser_regressions`.

**(C) Correcciones de catálogo de sinónimos** según operador:

1. *Brissas APPLE JACK* (`90001|ROSES|GARDEN ROSE APPLE|50/60|25`):
   ya estaban `manual_confirmado` ✓ — el shadow report mostraba
   estados viejos.
2. *Mystic CARROUSEL* (`442|ROSES|CAROUSEL|50|25`): existía con
   `status=None` → `manual_confirmado` apuntando a 33181
   `ROSA EC CARROUSEL BICOLOR 50CM 25U` (genérico EC encontrado
   en el catálogo, no había que dar de alta nada nuevo).
3. *Maxiflores ASSORTED/SPECIAL ASSTD*
   (`281|ROSES|{ASSORTED,SPECIAL ASSTD}|{40,60}|25`): existían
   con `status=None` → `manual_confirmado` apuntando a 32569/
   32571 `ROSA COL COLOR MIXTO {40,60}CM 25U` (Maxiflores es
   COL).
4. *Mystic MISS PIGGY* (`442|ROSES|MISS PIGGY|50|25`):
   **eliminado**. Apuntaba a `ROSA EC MISS WHITE 50CM 25U`
   (id 33558, `aprendido_confirmado` con times_confirmed=2),
   claramente erróneo (PIGGY ≠ WHITE). Mystic no tiene marca
   propia y NO existe genérico `ROSA EC MISS PIGGY` — queda
   sin_match para forzar alta del genérico en ERP.

Backup en `sinonimos_universal.json.backup_catalog_12m_<ts>.json`.

**MySQL sync**: la máquina del developer no tiene
`mysql.connector`, por lo que `_bulk_sync_to_mysql` falla
silenciosamente. Generado script SQL `sql_sync_12m.sql` con los
4 UPDATEs + 1 DELETE para que el operador (o la próxima ejecución
en producción) sincronice MySQL con el JSON.

**Validación integral**:
- Tests regresión: 13/13 OK en 11s.
- Benchmark global: 3598 líneas, ok 3420, **autoapprove 96.3%**
  estable. Sin regresión.
- Golden: 992/993 link 99.9% / 993/995 full_line 99.8% (sin
  cambios — golden no cubre estos casos directamente).
- Batch del operador: 1 gap pendiente (SAYONARA $1610 NO_PARSEA),
  igual que antes. Las 4 confirmaciones de sinónimos no afectan
  totales — afectan solo la propuesta de artículo del matcher.

**Lección transversal** ([`docs/lessons.md`](docs/lessons.md)):
"Estado del shadow_report puede estar viejo — siempre validar
contra el JSON de sinónimos antes de actuar". El reporte de
Brissas APPLE JACK marcaba "6 rescates pendientes" cuando ya
estaban `manual_confirmado` desde antes. Para verificar estado
real: `grep -F "<key>" sinonimos_universal.json` antes de hacer
cambios.

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
