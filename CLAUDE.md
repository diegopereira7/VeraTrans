# CLAUDE.md — Guía operativa para el agente

**Última actualización:** 2026-04-22 (sesión 10m)
**Estado:** 92.6% autoapprove · Golden 997/997 reviewed (link **100%**) — **4 fixes parsers shadow-driven** detectados por el primer lote real de Ángel (27 facturas): EQR (stems = total_stems no stems_per_box), FLORSANI (box types ampliados + sub-líneas heredan parent + tints multi-palabra), GARDA (box_code separado de variety + sub-líneas), MALIMA (coma de miles US en totales). +200 líneas nuevas parseadas en benchmark; rate global baja porque muchas no tienen artículo en ERP todavía (normal).

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

- **Autoapprove global:** 92.6% (>3700 líneas sobre 82 proveedores,
  +200 vs 10l por parsers recuperando líneas que antes ignoraban).
  El rate cayó de 93.9% → 92.6% porque las nuevas líneas
  recuperadas (FLORSANI2 con 54 variantes tinted, GARDA con 17
  sub-líneas heredadas) aún no tienen sinónimo manual en el ERP,
  pero son líneas REALES que antes se perdían silenciosamente.
  Cuando Ángel confirme/corrija desde la UI, `register_match_hit`
  (10g) + golden las recuperará gradualmente.
- **Golden set:** 997/997 reviewed (24 facturas, 13 proveedores).
  **Link accuracy 100% (997/997)** intacto tras los 4 fixes.
- **NO_PARSEA restantes:** 3 proveedores
- **Buckets:** OK 79 · NO_PARSEA 3 · TOTALES_MAL 0 ·
  NO_DETECTADO 1 (PONDEROSA)
- **Última sesión:** 10m (2026-04-22) — **7 fixes parsers
  shadow-driven** del primer lote real de Ángel (27 facturas).
  Ciclo completo de Fase 10 operando por primera vez — cada fix
  fue detectado por un error o inconsistencia que Ángel señaló
  en la UI, no por el benchmark:
  (a) **FLORAROMA** (AROMA.pdf): variante 2026 con columna
  `MARK` (S.O.) + coma decimal. Fix regex + helper `_num`
  robusto con heurística último separador para todos los
  formatos (EN/ES/múltiples puntos OCR).
  (b) **EQR**: el parser tomaba stems_per_box (`x 150 Stem` del
  desc) como stems totales. Fix regex captura
  `boxes BT total_stems $unit $total`, stems=450=3×150.
  (c) **FLORSANI**: box types ampliados (`HJ` faltaba),
  reescritura con tail de 7 columnas numéricas, soporte
  **sub-líneas que heredan pcs+box_type** (FLORSANI2: 0→54
  líneas parseadas), variedades multi-palabra con tints,
  normalización OCR `Rainbow750` → `Rainbow 750`.
  (d) **GARDA**: **box_code** (ELOY/ASTURIAS/MARL/R16/R19)
  ahora va al campo `label` separado en lugar de contaminar
  variety. Soporte sub-líneas sin box N° heredando parent
  (GARDA: 11→28 líneas).
  (e) **MALIMA**: coma de miles US (`$2,450.00`) rompía
  regex `[\d.]+`, total quedaba en 2.00. Fix `[\d.,]+` con
  `_num_us()`.
  (f) **MYSTIC**: regex del box_code no aceptaba `Ñ` (letra
  española), `CORUÑA` no matcheaba como code y contaminaba
  variety con `CORUÑA TNT Gyp ...`. Fix `[A-ZÑÁÉÍÓÚ]` en el
  regex + `TNT/VDAY/MDAY` añadidos a `_BLOCK_NAMES`.
  (g) **LIFE**: `MARL Explorer` → `Explorer` con label=MARL.
  Regex con grupo opcional `[A-Z]{3,}` antes de variety.
  (h) **OLIMPO (fmt=alegria) tallas desplazadas**: el parser
  `alegria` usaba `_SIZE_COLS` fijo (6..15 → 30,40,50,...120,
  10 tallas). OLIMPO añade **35** en la cabecera (11 tallas) y
  eso desplaza toda la matriz + stems/price/total un col a la
  derecha. Efecto: `EXPLORER 4 bunches @ 50cm` leía size=60,
  stems=100, price=100.00, total=0.30 (en vez de 0.30 / 30.00,
  todo invertido). Fix en
  [src/parsers/alegria.py](src/parsers/alegria.py): nuevo
  `_detect_sizes_from_tables()` busca la cabecera en **todas**
  las tablas de la página (pdfplumber a veces la separa de la
  tabla de datos), y `_process_table()` deriva stems/price/total
  como `6 + n_tallas + {0,1,2}`. ALEGRIA / CERES /
  TIERRA_VERDE (10 tallas) sin cambios; OLIMPO pasa de datos
  corruptos a 23/23 líneas con matemática consistente
  (sum=570 = header.total=570).
  (i) **ROSALEDA variety contaminada + líneas perdidas**: el
  regex primario aceptaba `[A-Z][A-Z\d]+` para el BOX_CODE (1
  token sin dashes) y no saltaba el calificador `USA|EURO`
  opcional entre BOX_TYPE y `ROSALEDA`. Efecto: (1) líneas con
  codes compuestos (ASTURIAS-ALBU, GIJON R-48, GIJON -R43,
  GIJON R45, IRUÑA) fallaban el match y se perdían 8+ filas
  primarias; las continuations heredaban label del match
  anterior (todas `PUERTO` incorrectamente); (2) la variedad
  absorbía el calificador (`EURO ROSALEDA FRUTTETO` en vez de
  `FRUTTETO`). Fix: regex box_code ampliado a 1-2 tokens con
  dashes/dígitos + placeholder OCR `�` + acentos ES, y
  `(?:(?:USA|EURO)\s+)?` opcional antes de la etiqueta
  `ROSALEDA`. Resultado: 68 → **88 líneas**, sum = header
  $3256.25 exacto, 25 labels únicos capturados correctamente
  (ASTURIAS-ALBU, GIJON R-48, GIJON -R43, IRUÑA, LILAS, etc.).
  Afecta también a `hacienda` y `rosadex` (mismo fmt). Golden
  997/997 intacto.
  (j) **TURFLOR spray carnation + box_id en variedad**: el
  parser antiguo incluía `SPRAY CARNATION` como prefijo de la
  variedad (no matcheaba con `MINI CLAVEL` del catálogo) y no
  manejaba el layout wrapped donde descripción + datos van en
  líneas distintas (el box_id GIJON/FVIDA/R19/GONZA terminaba
  en el campo descripción). Fix en `TurflorParser`:
  (1) detecta la línea wrap "SPRAY CARNATION X GRADE -" y la
  guarda en `pending_desc` para consumirla con la siguiente
  línea de datos; (2) la variedad se reduce al color
  traducido (`MIXTO/RAINBOW/BLANCO/...` vía
  `translate_carnation_color` — añadido `ASSORTED→MIXTO` en el
  mapa); (3) `spb=10` para spray, `20` para regular → el
  matcher diferencia MINI CLAVEL vs CLAVEL del catálogo vía
  spb_match; (4) `size` por grade (ESTANDAR=60, FANCY/SELECT=70);
  (5) `label` en campo separado (GIJON/FVIDA/R19/GONZA).
  Resultado: 6/6 líneas TURFLOR con matching `ok` link=1.00
  (antes 0 spray matchaban por el prefijo erróneo). Golden
  997/997 intacto.
  (l) **Sinónimos fantasmas por puntuación en synonym_key**: el
  operador corregía un match (`MANDARIN. X-PRESSION`→art) pero
  al reprocesar, si el parser emitía la misma variedad **sin**
  punto (`MANDARIN X-PRESSION`), la clave no casaba y había que
  volver a corregirlo. 176 sinónimos tenían claves no
  canónicas y 7 grupos duplicados apuntaban al mismo artículo
  (`BARISTA` / `BARISTA.`, `EXPLORER` / `EXPLORER.` / `EXPLORER°`,
  `PINK O HARA` / `PINK O°HARA` / `PINK O'HARA`, ...). Fix:
  (1) Nuevo helper `normalize_variety_key()` en
  [src/models.py](src/models.py) que colapsa no-alfanuméricos a
  espacios y compacta. (2) `InvoiceLine.match_key()` usa la
  normalización. (3) `SynonymStore.find()` fallback idem. (4)
  `_shadow_syn_key` en [batch_process.py](batch_process.py).
  (5) PHP `_shadowSynKey` en [web/api.php](web/api.php). (6) JS
  `_normalizeVariety` en [web/assets/app.js](web/assets/app.js) —
  aplicado en los 3 puntos donde se compone la synKey (single-PDF,
  batch collapsed, batch expanded).
  **Migración one-shot**: 176 claves re-normalizadas, 13 duplicados
  mergeados (3321→3308 entries). Backup:
  `sinonimos_universal.json.backup_normalize_*`. Golden 997/997
  intacto.
  (m) **MYSTIC precio paniculata**: el precio unitario de la
  paniculata en MYSTIC viene por ramo (paquete), no por tallo.
  Antes `price_per_stem = $8.00` y `stems × $8 = $200` no cuadraba
  con `line_total = $16` (2 ramos × $8). Fix en
  [src/parsers/mystic.py](src/parsers/mystic.py): autodetectar
  comparando `|price*stems - total|` vs `|price*bunches - total|`;
  si gana el lado bunches, asignar `price_per_bunch=price` y
  derivar `price_per_stem = price/spb`. Heurística también sirve
  para cualquier otra especie donde el precio venga por ramo.
  Golden 997/997 intacto tras el fix.

  **Métricas del batch**:
  - Golden **997/997 (100%) intacto** en todo momento.
  - ~200 líneas NUEVAS recuperadas en el benchmark (antes no
    parseaban o tenían datos corruptos).
  - Autoapprove global baja de 93.9% → 92.6% porque las nuevas
    líneas recuperadas (tints FLORSANI2, sub-líneas GARDA/LIFE,
    rosa AROMA, etc.) aún no tienen sinónimo manual. Bajada
    esperada: el denominador crece con líneas reales que antes
    se perdían silenciosamente. Cuando Ángel las confirme desde
    la UI, `register_match_hit` (10g) las promoverá.
  - **Primer ciclo completo benchmark↔shadow↔fix operativo**
    de la Fase 10: errores detectados en producción real, fixes
    aplicados, verificados contra golden sin regresión.

  **Nota sobre el patrón box-code-en-variety**: aparece en
  varios parsers (GARDA ELOY/MARL/R16, MYSTIC CORUÑA/TNT, LIFE
  MARL). Audit global detectó candidatos restantes en otros
  parsers (ROSALEDA EURO, SAYONARA SP, APOSENTOS ILIAS,
  MONTEROSA EUGENIA, EL CAMPANARIO ZAIRA) pendientes de fix —
  se atenderán cuando aparezcan en errores de shadow reales
  o en la siguiente revisión.
- **Sesión 10k** (2026-04-22) — **Shadow mode arrancado
  (Fase 10)**. Infraestructura para capturar la telemetría real de
  producción: qué propone el matcher y qué decide el operador.
  Complementa el golden (997 líneas curadas) con la realidad
  operativa diaria. Implementación:
  - `web/api.php`: nuevos helpers `_shadowLogProposals` (interceptor
    en `handleProcess` tras recibir el JSON del Python, itera
    líneas + mixed_box children y escribe una entry `propuesta`
    por línea con synonym_key, articulo_id, reasons, penalties,
    lane) y `_shadowLogDecision` (invocado por
    `handleConfirmMatch` → action=confirm, y
    `handleCorrectMatch` → action=correct con old vs new
    articulo_id). Ambos escriben a `shadow_log.jsonl` en la raíz,
    formato JSONL, silenciosos en error (nunca rompen la
    respuesta al cliente).
  - `tools/shadow_report.py`: agregador. Cruza propuestas con
    decisiones por `synonym_key` (tomando la propuesta más
    reciente anterior a la decisión). Produce: accuracy global
    real, accuracy por proveedor, top-N patrones de corrección
    (qué propuso mal el matcher y qué era correcto), y backlog
    pendiente (líneas ambiguous/sin_match sin decisión humana
    aún). Flags `--since`, `--provider`, `--top-errors`.
  - Smoke test con entradas sintéticas confirmó pipeline de
    escritura/lectura/agregación correcto. Log vacío ahora —
    se acumula con el uso real.

  **Siguiente paso natural**: usar el sistema con facturas reales
  durante N días, correr `shadow_report.py` semanalmente, y
  convertir los patrones de corrección top en fixes concretos
  (parser, sinónimo, regla de matcher) — cerrando el loop
  aprendizaje-desde-producción de la Fase 10.
- **Sesión 10j** (2026-04-22) — **desempate cualitativo
  en `tie_top2_margin`**. Diagnóstico de los 161 `ambiguous_match`:
  96 `tie_top2_margin` (empates por margen insuficiente) y 118
  `low_evidence` (score < 0.70 pero plausible). Los tie
  inspeccionados por nombre: muchos eran empates entre artículos
  con **misma variedad pero tallas distintas** donde top1 tenía
  `size_exact` y top2 solo `size_close` (ej. AGROSANALFONSO
  NECTARINE 40CM vs 50CM, EL CAMPANARIO VIOLET HILL 60CM vs 50CM,
  CANTIZA STAR PLATINUM 50 vs 40). Otros eran variedades
  multi-palabra donde top1 tenía `variety_full` y top2 solo match
  parcial. **Fix en `src/matcher.py`** (línea ~981): antes de
  marcar `ambiguous_match`, chequear dominio cualitativo — si
  top1 tiene `size_exact` y top2 solo `size_close`, o top1 tiene
  `variety_full` y top2 no, marcar `ok` con reason
  `tiebreak_size_exact` / `tiebreak_variety_full`. Resultado:
  ambiguous 161 → **144** (−17), `tie_top2_margin` 96 → **79**
  (−18%), auto **3052 → 3061** (+9), autoapprove **93.4 → 93.6%**.
  Casos residuales en tie: empates genuinos entre FANCY/SELECT
  (grade), genérico/branded propio mismo size, o size+size
  idénticos con distinto SPB (parser no extrae SPB). **Golden
  997/997 intacto**.
- **Sesión 10i** (2026-04-22) — **normalización de
  puntuación en tokens de variety**. Diagnóstico: de 250
  `variety_no_overlap` penalties globales, 37 eran casos con
  puntuación fixeable (`MONDIAL.`, `EXPLORER°`, `O´HARA`,
  `BLUE-MO`, etc); los demás eran productos sin equivalente en
  catálogo (ELITE alstros), OCR corrupto irrecuperable
  (FLORAROMA `ESX.OPLORER`) o variedades multi-word con
  concatenación OCR (`EUGENIA BRANDAOEXPLORER`). **Fix en
  `src/matcher.py`** (`_score_candidate`, línea ~298):
  pre-normalizar `line.variety` eliminando todo carácter que
  no sea `[A-Z0-9 ]+` antes del tokenizer. Resultado:
  variety_no_overlap 250 → 232, auto **3037 → 3052** (+15),
  autoapprove **93.0 → 93.4%** (+0.4pp), ambiguous 171 → 161
  (−10). **Golden 997/997 intacto**. Casos residuales (232)
  son genuinos: producto inexistente o OCR irrecuperable.
- **Sesión 10h** (2026-04-22) — **fixes parsers UNIQUE +
  CANANVALLE (NO_PARSEA 5→3)**. Diagnosticados los 9 samples
  que fallaban en los 5 NO_PARSEA. (a) UNIQUE: los 2 samples
  fallidos eran facturas PROFORMA con layout distinto
  (`HITS No. DESCRIPTION BRAND BOX BOX TYPE PCS FULL PACKING
  T.STEMS UNIT UNIT PRICE TOTAL VALUE`). Añadido regex
  `_PROFORMA_RE` que captura `0603.11.00.50 ROSES BLUSH 50 HB 1
  0.5 300 300 STEMS $ 0.32 $ 96.00`, tolera OCR split en total
  (`$ 1 92.00` → 192). (b) CANANVALLE: los 2 samples fallidos
  (duplicados literales con typo en nombre) eran facturas
  SAMPLE con layout-tabla sin signos `$`. Añadido regex
  `_SAMPLE_RE` en `CustomerInvoiceParser` que captura
  `1 1 - 1 HB Brighton 50 1 1 25 25 0.010 0.250SAMPLE`. Ambos
  fixes son aditivos (nuevo regex primero, legacy intacto).
  Resto de NO_PARSEA **no justificados**: SAYONARA 64811 (OCR
  totalmente corrupto), CEAN GLOBAL cean 57 (factura en
  español con rosas que requeriría reescribir `auto_cean`),
  NATIVE BLOOMS 2 samples con productos tropicales de cortesía
  ($0.0001/stem).
- **Sesión 10g** (2026-04-22) — **auto-confirmación de
  sinónimos**: nuevo método
  [`SynonymStore.register_match_hit`](src/sinonimos.py#L181) y
  llamada desde el matcher tras `ok` con evidencia independiente
  (variety_match + size_exact o variety_match + brand_in_name).
  Incrementa `times_confirmed` y, tras ≥ 2 hits, promueve
  `aprendido_en_prueba → aprendido_confirmado` (trust 0.55 →
  0.85). Medición dos pasadas: 1ª pasada promueve 774 sinónimos;
  2ª pasada aprovecha scoring ya con trust alto. Resultado:
  **weak_synonym 1787 → 677 (−62%)**, auto 3019 → 3021 (+2),
  autoapprove 92.8 → 92.9% (+0.1pp). Golden 997/997 **intacto**
  (manual_confirmado protegido; auto-promoción nunca lo toca).
  Gate de seguridad: el sinónimo solo promociona si el match
  ganó por evidencia *no-sinónimo* (variety+size o variety+brand)
  → no hay bootstrapping circular.
- **Sesión 10f** (2026-04-22) — **fix parser BRISSAS**:
  el regex de `header.total` era `(?:Sub\s+)?Total\s+([\d,.]+)` y
  matcheaba la PRIMERA ocurrencia de `TOTAL` en el PDF, que en
  BRISSAS es la fila-resumen de stems (`TOTAL 6700 0.286 1918.00`
  → capturaba 6700 stems en lugar de $1918 grand total). Fix
  aditivo: preferir `Sub\s+Total\s+([\d,.]+)` (que aparece más
  abajo con el grand total real) y fallback al `Total` genérico
  si no existe. Resultado: 11/11 samples BRISSAS con
  `header_ok=True` (antes 0/5). BRISSAS pasa de TOTALES_MAL → OK
  (verdict OK, tot_ok=5/5). Global auto 92.8% estable (el fix no
  impacta link accuracy, solo consistencia validación). También
  se corrigió `header_total` en los 2 goldens BRISSAS existentes
  (16200 → 4632.75 y 14925 → 4315.5, que heredaban el stems count
  como grand total).

### Próximos pasos posibles

**Orden sugerido para la próxima sesión** (post-10m):

1. **Verificar shadow loop end-to-end con un batch nuevo**.
   Ángel tiene pendiente procesar el siguiente lote de facturas
   reales. Con los fixes 10m(a)-(l) ya aplicados, el flujo ahora
   captura propuestas en `batch_process.py` y decisiones via el
   tick ✓ del batch (routing confirm/correct/save_synonym). Tras
   1-2 facturas procesadas y corregidas, correr
   `shadow_report.py` y comprobar que: (a) las propuestas se
   loguean, (b) las decisiones se loguean, (c) el cruce por
   `synonym_key` produce accuracy real. Si algo no cruza,
   investigar mismatch key frontend ↔ backend (la normalización
   ya está en los 3 sitios).

2. **Auditoría box-code-in-variety en parsers pendientes**.
   El patrón "código de ruta/destino metido en la variedad"
   apareció en MYSTIC (CORUÑA/TNT), GARDA (ELOY/ASTURIAS/MARL),
   LIFE (MARL), ROSALEDA (ASTURIAS-ALBU, GIJON R-48, IRUÑA) y
   TURFLOR (GIJON/FVIDA/R19/GONZA) — todos arreglados. Pendiente
   auditar: **SAYONARA** (SP), **APOSENTOS** (ILIAS),
   **MONTEROSA** (EUGENIA), **EL CAMPANARIO** (ZAIRA). Grep
   sobre propuestas de shadow_log con varieties que contengan
   estos tokens UPPERCASE cortos al inicio.

3. **Uma Flowers — 7 `ambiguous_match` sin tocar**. En el batch
   retrospectivo salieron 7 líneas ambiguas en Uma Flowers. No
   las tocó ninguno de los 12 fixes de 10m. Extraer de
   `shadow_log.jsonl` las líneas con `provider_name=Uma Flowers
   match_status=ambiguous_match`, ver `reasons`/`penalties`,
   decidir si es bug del parser o gap de catálogo.

4. **Cerrar gap `save_synonym` en shadow**. Cuando el operador
   corrige un `sin_match` (no había propuesta), el endpoint
   `save_synonym` NO escribe al shadow_log. Hacer que también
   emita una entry `decision: correct` con `proposed_articulo_id=0`
   para medir cobertura matcher real (qué % de sin_match rescata
   el operador vs qué % son genuinamente sin catálogo).

5. **sin_match del backlog = artículos a dar de alta en ERP**.
   Ángel confirmó que varios `sin_match` de MYSTIC/VALTHOMIG son
   productos que él no tiene en catálogo. Montar
   `shadow_report.py --top-missing-articles` que liste variedades
   que aparecen como `sin_match` ordenadas por frecuencia — da
   la lista priorizada de artículos para alta en ERP.

6. **Histórico aún útil — otros pasos arrastrados**:
   - Ampliar golden set a más proveedores (feedback loop).
   - NO_PARSEA restantes (CEAN GLOBAL, NATIVE BLOOMS, SAYONARA
     64811): ROI no compensa — diagnóstico cerrado en 10h.
   - Optimizar matcher (indexar variety+size, precalc brand set)
     — solo si hace falta perf.

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
| `generic_vs_own_brand` (genérico cuando hay branded propio en pool) | −0.15 |
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

### 2026-04-22 — sesión 10m: batch de 7 fixes parsers shadow-driven

Primer ciclo completo de Fase 10 operando. Ángel procesó un lote
real de 27 facturas de la semana y señaló desde la UI una lista
creciente de errores. Cada uno convertido en fix concreto
(detalle en "Estado actual" arriba): FLORAROMA 2026 (AROMA),
EQR (stems=total_stems), FLORSANI (box types + sub-líneas +
tints), GARDA (box_code en label, sub-líneas heredadas), MALIMA
(coma miles US), MYSTIC (Ñ en code + TNT block name), LIFE
(MARL label).

Pattern recurrente detectado: **box codes/labels metidos en
variety**. Los parsers capturaban como parte del nombre de la
variedad tokens UPPERCASE que en realidad son destinos/rutas/
códigos internos (ELOY, MARL, R16, CORUÑA, TNT, ZAIRA). Fix
común: grupo opcional `[A-Z]{3,}` o `[A-ZÑÁÉÍÓÚ]{3,}` antes de
variety que se guarda en `label`. Audit global detectó 5
parsers más con el patrón (ROSALEDA EURO, SAYONARA SP, APOSENTOS
ILIAS, MONTEROSA EUGENIA, EL CAMPANARIO ZAIRA) — se atenderán
cuando aparezcan en shadow real.

**Métricas**:
- ~200 líneas nuevas recuperadas en benchmark (antes no
  parseaban o tenían datos corruptos silenciosamente).
- Golden **997/997 (100%) intacto** en todo momento.
- Autoapprove 93.9% → **92.6%** (dilución por denominador
  creciente; las nuevas líneas todavía no tienen sinónimo manual
  — se recuperarán cuando Ángel las confirme en UI).
- FLORSANI2.pdf: 0 → **54** líneas. GARDA: 11 → **28** líneas.
  AROMA: 0 → 4. LIFE: variety limpia sin MARL. MYSTIC1: variety
  limpia sin CORUÑA/TNT. MALIMA: total correcto (2.00 → 2450.00).

### 2026-04-22 — sesión 10k: shadow mode arrancado (Fase 10) — infraestructura propuesta↔decisión

Fin del ciclo técnico de quick wins (10f-10j llevaron de 92.7% a
93.6% autoapprove) y arranque de la Fase 10 del roadmap. El
objetivo ya no es extraer más del benchmark sino **medir la
calidad real en producción**: de las propuestas del matcher, ¿qué
porcentaje confirma el operador y qué porcentaje corrige? ¿Qué
patrones de corrección se repiten?

**Arquitectura**:

Dos tipos de entry en `shadow_log.jsonl` (JSONL en raíz):

- `propuesta`: una por línea de factura al procesarse en la web.
  Incluye `synonym_key` (clave de cruce), variety/size/spb/grade,
  proposed_articulo_id+name, match_status, link_confidence,
  review_lane, reasons, penalties.
- `decision`: una por acción confirm/correct del operador. Lleva
  `synonym_key` + `proposed_articulo_id` + `decided_articulo_id`
  + action ∈ {confirm, correct}.

**Cambios en código**:

- [`web/api.php`](web/api.php): dos nuevos helpers
  `_shadowLogProposals($result, $pdfPath)` y
  `_shadowLogDecision($action, $input, $proposedId, $decidedId,
  $decidedName)`. Llamadas integradas en `handleProcess` (tras
  parsear el JSON de `procesar_pdf.py`), `handleConfirmMatch` y
  `handleCorrectMatch`. Helper `_shadowSynKey(providerId, line)`
  replica la estructura de `SynonymStore._key` en Python:
  `<provider_id>|<species>|<variety.upper>|<size>|<spb>|<grade.upper>`.
- [`tools/shadow_report.py`](tools/shadow_report.py) (nuevo):
  - Cruza propuestas con decisiones por `synonym_key`, eligiendo
    la propuesta más reciente anterior a la decisión.
  - Reporta: accuracy global real (% confirmaciones /
    decisiones), accuracy por proveedor, top-N correcciones con
    par "propuso X / correcto Y", backlog pendiente (líneas
    ambiguous/sin_match sin decisión humana).
  - Flags: `--since YYYY-MM-DD`, `--provider <substr>`,
    `--top-errors N`.

**Diseño**:

- Logueo silencioso (nunca rompe la respuesta al cliente aunque
  falle el file_put_contents).
- Propuestas se loguean ANTES de que el operador toque nada —
  evita contaminación por las acciones posteriores.
- Cruce por `synonym_key` + timestamp permite atribución correcta
  incluso si varias propuestas comparten key (fractura de
  líneas, varias facturas del mismo proveedor).
- El log también captura propuestas sin articulo_id (sin_match,
  sin_parser) — útil para medir cobertura del matcher.

**Smoke test** con 4 entries sintéticas (2 propuestas + 2
decisiones: 1 confirm + 1 correct) confirmó pipeline correcto:
accuracy 50%, top error correctamente identificado como "ROSA EC
FREEDOM genérico propuesto cuando el correcto era el branded
BRISSAS". Log limpiado tras el test.

**Métricas técnicas (sin cambios vs 10j)**:
- Autoapprove 93.6% · Golden 997/997 100%.

**Siguiente natural**: 1-2 semanas de uso operativo real →
correr `shadow_report.py` → convertir top-N patrones de
corrección en fixes concretos (nuevos sinónimos manual_confirmado,
parsers con bugs, reglas de matcher). Cierra el ciclo
benchmark-shadow-fix que es la Fase 10.

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
