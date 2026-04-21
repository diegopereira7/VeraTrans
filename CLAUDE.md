# CLAUDE.md — Guía operativa para el agente

**Última actualización:** 2026-04-21 (sesión 10b)
**Estado:** 92.7% autoapprove · Golden 575/575 reviewed (link **100%**) — PONDEROSA + ROSALEDA añadidos · NO_PARSEA 5 · TOTALES_MAL 0 · matcher 26× más rápido

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

- **Autoapprove global:** 92.7% (3501 líneas sobre 82 proveedores)
- **Golden set:** 575/575 reviewed (14 proveedores). **Link
  accuracy 100% (575/575)**. Nuevas incorporaciones en sesión 10b:
  PONDEROSA 1920 (103 líneas) + cleanup legacy 1896 (8 líneas
  reconciliadas con spb→U).
- **NO_PARSEA restantes:** 5 proveedores
- **Buckets:** OK 76 · NO_PARSEA 5 · TOTALES_MAL 0 · NO_DETECTADO 1
- **Última sesión:** 10b (2026-04-21) — cierra BRISSAS/COLIBRI +
  añade PONDEROSA + ROSALEDA. Fixes parser: PONDEROSA
  (normalización de U+00B4 acento agudo en MAYRA'S BRIDAL),
  ROSALEDA (bunches total = BX × bunches_per_box para cuadrar
  validación stems). ROSALEDA 95.0 → 99.2% (+4.2pp). Gold legacy
  1896 reconciliado: 8 líneas donde spb/U eran inconsistentes
  ahora alineados al SKU correcto por tamaño.

### Próximos pasos posibles

1. **Correr `golden_apply.py` en cada ampliación de golden** es
   ahora el camino cierre-del-bucle: el matcher respeta
   `manual_confirmado` en los 4 puntos críticos (brand_boost
   skip, veto skip+penalty, add() no-clobber, manual-pin final).
2. **Shadow mode** (Fase 10) — procesar facturas reales, comparar
   propuesta vs decisión humana, capturar fallos de producción.
3. **NO_PARSEA restantes (5)**: CANANVALLE, CEAN GLOBAL, NATIVE
   BLOOMS, SAYONARA, UNIQUE. Restos típicamente con 1 sample por
   proveedor con OCR muy corrupto o formato "Bouquet" exótico que
   no compensa en ROI. SAYONARA y NATIVE BLOOMS ya parsean 4/5.
   CEAN GLOBAL requeriría extender parser para rosas en español
   ("ROSAS EXPLORER 40CM ..."). CANANVALLE tiene totales mal
   interpretados (fmt=custinv compartido con otros).
4. **TOTALES_MAL (3)**: CANTIZA, MILAGRO, MILONGA — parse OK pero
   sum no cuadra con header en algunos samples.
5. **Ampliar golden set** a más proveedores para robustecer el
   feedback loop.
6. **Optimizar matcher** — cerrado en sesión 9u con fix de deferred
   save (26× speedup, 238→9ms/línea). El fuzzy ya no es dominante.
   Si hace falta más perf: indexar por variety+size en
   `_gather_candidates`, precalcular brand set, limitar fan-out
   fuzzy (top-5 actual).

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

### 2026-04-21 — sesión 10b: PONDEROSA + ROSALEDA (autoapprove 92.2→92.7%, golden 444→575)

Continuación de 10a. Tres focos: cerrar FA-117549 pendiente,
ROSALEDA val_errors, PONDEROSA fix + golden.

**Fixes de parsers**:

- `src/parsers/otros.py` **VerdesEstacionParser (PONDEROSA)**:
  normalización de apóstrofes al inicio de `parse()` — U+2019/
  U+2018 (curly), **U+00B4** (acento agudo, aparece en PDFs
  Ponderosa como apóstrofe en `MAYRA'S BRIDAL`), U+0092 (Win-1252)
  y U+FFFD → `'`. Char class `_RE_A` extendida a `[A-Z\s']`. Sin
  el fix, `MAYRA'S BRIDAL WHITE` se capturaba como `S BRIDAL
  WHITE` (parte de MAYRA se perdía) y el matcher elegía artículo
  incorrecto.
- `src/parsers/otros.py` **RosaledaParser**: el regex de variante
  A capturaba `bunches` como número por caja, pero `stems` es
  total. Para BX>1 la validación `stems == bunches × spb` fallaba
  (5 val_errors). Fix: capturar BX, `bunches_total = BX ×
  bunches_per_box`. Continuaciones (caja mixta) heredan `last_bx`
  del primary anterior.

**Goldens**:

- COLIBRI FA-117549 auto-corregido con las reglas aprendidas
  (COLIBRI 97.0 → 98.6%). Variedades novedad (GOLEM, MUSTARD,
  ANTIGUA, ROYAL DAMASCUS, SPRITZ SPORT) mapeadas a BICOLOR
  branded por grade (FAN→12715, SEL→12883).
- PONDEROSA golden verdesestacion_1920 bootstrappeado y revisado
  (103 líneas). 8 líneas con spb=20/10 que el review tool había
  propagado al SKU 25U ahora apuntan al 20U/10U correcto (FREEDOM
  50→33948, MONDIAL/BLUSH/VENDELA 40→10U branded).
- PONDEROSA legacy 1896 **reconciliado**: 8 líneas donde spb y el
  sufijo U del artículo eran inconsistentes (decisiones antiguas
  cuando el catálogo no tenía 10U/20U variants) ahora alineadas
  al SKU spb-correcto. Regla aplicada: `articulo_id` debe
  coincidir con `stems_per_bunch` del parser.

**Métricas**:
- COLIBRI auto: 97.0 → **98.6%** (+1.6pp)
- ROSALEDA auto: 95.0 → **99.2%** (+4.2pp, 5 val_err → 0)
- PONDEROSA auto: 97.0 → **100%** en samples parseables
- Global auto: 92.2 → **92.7%** (+0.5pp)
- Golden link: 100% (444/444) → **100% (575/575)** (+131 líneas)

### 2026-04-21 — sesión 10a: repaso BRISSAS + COLIBRI (autoapprove 91.2→92.2%, golden +152 líneas)

Repaso de proveedores top volumen. Dos proveedores auditados a
fondo: COLIBRI (80 líneas, rate 71.6% baseline) y BRISSAS (504
líneas, sin samples hasta esta sesión).

**Fixes de parsers**:

- [src/parsers/colibri.py](src/parsers/colibri.py): tres bugs
  aditivos. (1) `prices[-1].replace(',','.')` convertía
  "2,565.000" en "2.565.000" → `float()` fallaba silenciosamente
  → 12 líneas con `line_total=0` y val_errors (formato Colibri
  es US: coma=miles, punto=decimal). Fix: `replace(',','')`.
  (2) Regex `(\d+)\s+ST` sin word boundary capturaba "581314" de
  "581314 STA" → `total_mismatch` en 3 líneas. Fix:
  `(\d+)\s+ST\b`. (3) `GRADE_MAP` no incluía `STA` (literal de
  Colibri para Standard) → default a FANCY → sinónimos con grade
  incorrecto. Fix: añadir `'STA':'STANDARD'`.
- [src/parsers/colibri.py](src/parsers/colibri.py): nueva regla
  "MIX Color/Color → una sola línea". Líneas tipo `Carn Mix
  Red/Yellow` o `Mini Mix Red/White` ya no se dividen en dos
  medio-tallos; mantienen stems/total íntegros con `variety=MIX`.
  El grade+spb deciden el SKU MIXTO concreto
  (FAN+20→12790, SEL+10→26798, STD+20→12659, etc).
- [src/matcher.py](src/matcher.py): añadido `\bHAWB\b` al regex
  de ruido de `rescue_unparsed_lines`. Líneas `HB XX.XXX HAWB:
  SN` de BRISSAS (resumen de cajas) se capturaban como producto
  → 11 sin_match fantasma (1 por sample). Ahora 0.

**Golden set ampliado**:

2 facturas BRISSAS (000003919 + 000003952 = 112 líneas) y 3
COLIBRI (FA-117295 + FA-117449 + FA-117549 = 73 líneas; la
última queda draft para revisar en próxima sesión).
`golden_apply.py` propagó 443 confirmaciones + 1 corrección al
diccionario de sinónimos.

**Reglas aprendidas** (guardadas en memory):

- **BRISSAS MIX COLORS**: mapear a 36900-36903 (ROSA SURTIDO
  MIXTO XcmCM 25U BRISSAS) por tamaño (40/50/60/70), no al
  `32437 ROSA COLOR MIXTO "BRISAS"` antiguo.
- **COLIBRI MIX Color/Color**: una sola línea MIX grade-aware
  (FAN/SEL/STD) + spb-aware (20 normal / 10 mini). SKUs branded
  preferidos (…COLIBRI).
- **COLIBRI columna Gr.**: `FAN`=Fancy, `SEL`=Select, `STA`/`STD`
  =Standard. `golden_review.py` auto-propaga sólo por
  (variety, size, origin) — no considera grade+spb → en review
  manual hay que verificar SIEMPRE la columna Gr.

**Métricas**:
- COLIBRI auto: 71.6 → 81.25% (fixes parser) → **97.0%**
  (golden apply) = +25.4pp
- BRISSAS auto: nuevo → **100%**
- Global auto: 91.2 → **92.2%** (+1.0pp)
- Golden link: 100% (292/292) → **100% (444/444)** (+152 líneas)

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
