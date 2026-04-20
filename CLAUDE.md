# CLAUDE.md — Guía operativa para el agente

**Última actualización:** 2026-04-20 (sesión 9r)
**Estado:** 89.4% autoapprove · Golden 148/148 reviewed (link 93.9%) · NO_PARSEA 7

---

## TL;DR — léeme siempre al empezar

**Proyecto:** VeraBuy Traductor — extrae líneas de facturas PDF de
proveedores de flores, las traduce a artículos del catálogo VeraBuy,
mantiene diccionario de sinónimos aprendidos. Dos frontends (CLI +
Web PHP), mismo pipeline Python. Usuario: Ángel Panadero
(diego.pereira@veraleza.com).

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

- **Autoapprove global:** 89.4% (3309 líneas sobre 82 proveedores)
- **Golden set:** 148/148 reviewed (8 proveedores). **Link accuracy
  93.9% (139/148)** — 9 mismatches restantes, todos gap del matcher:
  5 en timana (HIGH AND MAGIC ORANGE x2, ASSORTED ASSORTED, GOLDFINCH
  60, CHERRY BRANDY 60), 3 en benchmark (MINICARNS → CLAVEL FANCY),
  1 en florifrut (IGUAZU → IGUAZU BICOLOR).
- **NO_PARSEA restantes:** 7 proveedores
- **Buckets:** OK 71 · NO_PARSEA 7 · TOTALES_MAL 3 · NO_DETECTADO 1
- **Última sesión:** 9r (2026-04-20) — revisión golden drafts +
  matcher: color-suffix strip, pkey fallback desde provider_id,
  brand_boost contextual. Autoapprove 87.8→89.4, golden 91.2→93.9.

### Próximos pasos posibles

1. **Matcher: cerrar los 9 mismatches restantes del golden**
   ([src/matcher.py](src/matcher.py)). Casos pendientes que requieren
   trabajo más específico:
   - **HIGH AND MAGIC ORANGE → HIGH MAGIC BICOLOR** (2 casos timana):
     remover stopword "AND" + fuzzy a prefijo "HIGH MAGIC*".
   - **ASSORTED ASSORTED → COLOR MIXTO** (1 caso): sinónimo o mapping
     de ASSORTED/MIXED/SURTIDO a COLOR MIXTO en la búsqueda de variety.
   - **GOLDFINCH 60CM / CHERRY BRANDY 60CM** (2 casos): relajar
     `_SIZE_TOL` de 10→20cm cuando no hay candidato con marca propia
     (usuario prefiere genérico con variety correcta aunque size off
     sobre marca ajena con size exacto).
   - **IGUAZU → IGUAZU BICOLOR** (1 florifrut): búsqueda por prefijo
     de variety si no hay match exacto en by_variety.
   - **MINICARNS → CLAVEL FANCY** (3 benchmark): el parser produce
     `spb=10` (mini) pero gold dice spb=20 (fancy). Caso golden-
     específico, revisar si es el parser o el mapping.
2. **Shadow mode** (Fase 10) — procesar facturas reales, comparar
   propuesta vs decisión humana, capturar fallos de producción.
3. **NO_PARSEA restantes (7)**: CANANVALLE, CEAN GLOBAL, DAFLOR,
   ELITE, NATIVE BLOOMS, SAYONARA, UNIQUE. OCR duro o match, no
   parse.
4. **TOTALES_MAL (3)**: CANTIZA, MILAGRO, MILONGA — parse OK pero
   sum no cuadra con header en algunos samples.
5. **Ampliar golden set** a más proveedores para robustecer el
   feedback loop.
6. **Optimizar matcher** (backlog) — ~6.5s para 43 líneas contra 42k
   artículos. Indexar por variety+size, precalcular brand set, limitar
   fan-out fuzzy.

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

### 2026-04-20 — sesión 9r: revisión golden + matcher prioridad de marca

- **Golden drafts** (timana_88112, benchmark_103685, florifrut_0001093134):
  confirmados como reviewed en sesión 9q pero quedaba pegada la
  `_note` DRAFT — limpiada en los 3 archivos. Estado: 148/148
  líneas reviewed en 8 proveedores.
- **Diagnóstico golden**: link accuracy inicial 91.2% (135/148), 13
  mismatches, todos gap del matcher (no del golden). Patrón: el
  sistema elige genérico `ROSA COL ...` o artículo con marca ajena
  (CANTIZA, LUXUS, CERES) en lugar del artículo con marca del
  proveedor actual (TIMANÁ, GOLDEN).
- **Regla de negocio confirmada por el usuario** (guardada en
  `feedback_matcher_priority.md`): marca del proveedor > genérico
  COL/EC > marca ajena. Variedad correcta con tamaño aproximado
  pesa más que variedad+tamaño exactos con marca ajena.
- **[src/matcher.py](src/matcher.py) → `_strip_color_suffix`**:
  nuevo helper paralelo a `_strip_color_prefix`. Quita sufijos de
  color (`WHITE`, `PINK`, etc.) si la base resultante existe en
  `by_variety`. Permite que `VENDELA WHITE` resuelva a `VENDELA`
  y encuentre el artículo TIMANÁ. Generador adicional añadido en
  `_gather_candidates` (case 2d).
- **[src/matcher.py](src/matcher.py) → `_score_candidate`**:
  comparación de `own_brands` vs `nombre` ahora usa `_normalize`
  (strip acentos). Antes `'TIMANA' in 'TIMANÁ'` = False y
  `brand_in_name` nunca disparaba para proveedores con tilde en el
  sufijo del catálogo. `foreign_brand` también normalizado.
- **[src/matcher.py](src/matcher.py) → `match_line` fallback
  `pkey`**: si el parser deja `line.provider_key=''` (caso TIMANA
  y otros), se deriva del `provider_id` iterando `PROVIDERS`.
  Desbloquea `brand_boost` para proveedores donde antes nunca
  disparaba por el id mismatch entre PROVIDERS config (90039) y
  `id_proveedor` del catálogo (2651).
- **[src/matcher.py](src/matcher.py) → `match_line` brand_boost
  contextual**: solo aplica si hay **exactamente un** candidato con
  `own_brand + variety_match + size_exact`; el score se eleva sobre
  el top alternativo + 0.05 (antes 1.05 fijo, insuficiente para
  superar synonyms legacy que llegaban a ~1.19). El gating por
  unicidad evita empates en proveedores con mucho catálogo marcado
  (ECOFLOR, MYSTIC) que causaban −11pp al aplicar boost a varios.
- **Globales**: autoapprove **87.8% → 89.4%** (+1.6pp). ok 2795→
  2833 (+38), ambiguous 228→205 (−23), autoapprovable 2666→2715
  (+49). Golden **91.2% → 93.9%** (+2.7pp, −4 mismatches: 4
  cerrados en TIMANA — VENDELA WHITE 40/50, MONDIAL WHITE 60,
  PINK MONDIAL PINK 40). Quedan 9 mismatches que requieren trabajo
  más específico (ver "Próximos pasos").

### 2026-04-17 — sesión 9q: IWA mixed_box + CANTIZA/MILAGRO/MILONGA + fuzzy cache

- **[src/matcher.py](src/matcher.py) → `reclassify_assorted`**:
  ampliado el regex para aceptar `SURTIDO MIXTO`, `ASSORTED ROSA`,
  `MIXTO` y variantes de 2 palabras. Reclasifica `ambiguous_match`
  con variedad claramente "mixed box" a `mixed_box`. IWA ambig
  19→2, líneas a `mixed_box` = 17.
- **[src/parsers/cantiza.py](src/parsers/cantiza.py)**: OCR cleanup
  para sample `01 - V. 075-6577 1440` (N255T→N 25ST, S0/SOCM→50,
  `2351`→`25ST`, pipes a espacios). CANTIZA NO_PARSEA → OK
  (100 líneas, 95 ok).
- **[src/parsers/otros.py](src/parsers/otros.py) → ColFarmParser**:
  aliases `_ROSE` y `_UNIT` amplicados (R:ise/R:lse/Rlse/SR); pre-
  normalización OCR (pipes, `¡`/`!`, ruido `\d~` entre stems y ST,
  Rose-variants → Rose uniform). Header fallback (`TOTAL (Dolares)`
  y `Vlr.Total FCA BOGOTA`). MILONGA NO_PARSEA → TOTALES_MAL,
  02b sample 0→5 parsed.
- **[src/parsers/auto_milagro.py](src/parsers/auto_milagro.py)**:
  nuevo `_ocr_normalize()` (`~OSES`→`ROSES`, `FREE DOM`→`FREEDOM`,
  `SO/S0`→`50` contextual, `25(`/`0.28(`→`250`/`0.280` paréntesis
  OCR de un cero, `\ufffd`/`\u2022`/`\u00b0`/`\u00b7` → `-`).
  MILAGRO NO_PARSEA → TOTALES_MAL, 02b sample 0→1 parsed.
- **[src/articulos.py](src/articulos.py) → `fuzzy_search`**: cache
  por `(sp_key, query, threshold)` + prefiltro con
  `real_quick_ratio()`/`quick_ratio()` antes de `ratio()`. El cache
  ayuda en facturas con variedades repetidas; el prefiltro skipea
  ~2% (aporta poco por naturaleza de los nombres).
- **Golden set**: +3 drafts (timana_88112, benchmark_103685,
  florifrut_0001093134) generados con `golden_bootstrap.py` —
  pendientes de revisión manual para convertirlos en reviewed.
- **Global**: autoapprove **86.7% → 87.8%** (+1.1pp, mejor sesión
  de las últimas 3). ok 2785→2795 (+10), ambiguous 268→228 (−40,
  gracias al reclassify a mixed_box). Líneas totales 3297→3309
  (+12). **Buckets**: OK 70→71, NO_PARSEA 10→7 (−3), TOTALES_MAL
  1→3 (CANTIZA→OK; MILAGRO+MILONGA+CANANVALLE suben desde
  NO_PARSEA). Golden 100% (88/88).

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
