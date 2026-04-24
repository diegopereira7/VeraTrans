# CLAUDE.md — Guía operativa para el agente

**Última actualización:** 2026-04-24 (sesión 11d — triage páginas vacías evita OCR innecesario, 3× speedup)
**Estado:** **96.1% autoapprove** (récord) · Golden 980/997 (98.3%). Ronda de 4 sesiones atacando bucket por bucket los `ambiguous_match`: inicio 114 → **50** (−56%). ok 3235 → 3327 (+92). Fixes: matcher ganó `foreign_brand_soft` (detecta WAYUU via `brands_by_provider`), `fuzzy_typo_overrides_variety` (LIMONADE↔LEMONADE, TIFFANNY↔TIFFANY) y bug fix unit-suffix. Parsers ganaron traducciones EN→ES (MALIMA tint, CONDOR hydrangea, SAN FRANCISCO hydrangea), route-codes separados de variety (EL CAMPANARIO ZAIRA/JOVI/VERALEZA), variedades compuestas (`SUNSET X-PRESSION`), defaults de size para parsers sin CM explícito (ROSABELLA 50, CONDOR 60, PREMIUM 70), y color-split de CONEJERA clavel. 17 mismatches del golden siguen siendo branded nuevos del catálogo — re-anotar cuando toque.

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

- **Autoapprove global:** **96.1%** (récord, +1.8pp sobre 10t).
  Top penalties: weak_synonym 279+ · variety_no_overlap ~140 ·
  foreign_brand ~155 · tie_top2_margin ~80 · low_evidence ~55 ·
  color_modifier_extra ~47 · foreign_brand_soft ~28. Ambiguous
  114 → **50** (−56% en una ronda de 4 sesiones).
- **Catálogo MySQL:** 44,751 artículos. Tabla `articulos` incluye
  `id_erp` (estable entre reimports). **Sesión 10s añade fix para
  68 artículos Florsani con `nombre` truncado** a "PANICULATA
  XLENCE TE" (export phpMyAdmin corrigió mal la Ñ de TEÑIDA):
  `ArticulosLoader` ahora lee también `color`/`marca`/`variedad`
  y reconstruye el canónico "{familia} TEÑIDA {color} {tamano}
  {paquete}U {marca}" en `_reconstruct_truncated_name` al
  cargar. Los 45 colores de PANICULATA XLENCE TEÑIDA (LAVANDA,
  ROSA CLARO, AZUL OSCURO, RAINBOW PASTEL, ...) vuelven a ser
  distinguibles para el matcher.
- **Golden:** 980/997 (98.3%). Los 17 mismatches son artículos
  branded nuevos del catálogo que el matcher ahora prefiere sobre
  genéricos EC/COL anotados en el golden (ej. golden espera
  `33697 ROSA EC PLAYA BLANCA`; matcher propone
  `36678 ROSA PLAYA BLANCA BRISSAS`, branded — más correcto). Son
  mejoras — re-anotar esos goldens en sesión futura.
- **Sesión 10q — migración a id_erp + reimport catálogo:**
  1. El `id` autoincrement de MySQL se renumera al re-importar el
     dump de phpMyAdmin → sinónimos y golden apuntaban a ids que
     ahora son artículos distintos. Detectado tras intentar importar
     directamente: golden cayó 997→111 (11.1%), detectado antes de
     afectar producción.
  2. **Nueva columna estable**: `id_erp` (varchar, ERP externo) se
     preserva entre reimports. Añadida a `ArticulosLoader`
     (`by_id_erp` index, `_register_article`, `load_from_db`,
     `load_from_sql`).
  3. **`SynonymStore`** gana:
     - Campo `articulo_id_erp` en cada entry (poblado al `add`).
     - Método `resolve_article_id(entry, art_loader)`: lookup por
       id_erp si el id local ya no coincide → lazy remap del entry.
     - `matcher._gather_candidates` usa `resolve_article_id` en
       lugar de `s['articulo_id']` directo.
  4. **Migración one-shot**
     [`tools/migrate_add_articulo_id_erp.py`](tools/migrate_add_articulo_id_erp.py):
     parsea el dump SQL nuevo, construye mapping
     `nombre → (id_erp, nuevo_id)`, y re-mapea todos los sinónimos
     + golden por `articulo_name`. Fallback para tildes (TIMANÁ →
     TIMANA) y para truncaciones del export phpMyAdmin
     (`TIMANÁ → TIMAN`). Resultado: 3311/3337 sinónimos + 994/997
     golden remapped. 24 sinónimos huérfanos invalidados
     (`status=rechazado`, `_orphan_pre_id_erp` con traza).
  5. **Retrocompat**: el matcher sigue aceptando entries sin
     `articulo_id_erp` (fallback al `articulo_id` viejo). Los
     sinónimos nuevos creados post-10q incluyen ambos campos
     automáticamente — a partir del próximo reimport ya no
     perderán el vínculo.
- **Backlog shadow reducido 87 → 4 pendientes** (95.4%). Post-10p,
  solo quedan casos de alta ERP (IMAGINATION, REDIANT, ORNITHOGALUM
  WHITE STAR, GYPSOPHILA XLENCE TINTED DARK RAINBOW) o decisión
  operador (tie residual).
- **Fixes sesión 10p — Tierra Verde multi-ID config/catálogo:**
  1. Tierra Verde es colombiano pero el parser `alegria` usaba
     default `origin='EC'` → artículos `ROSA EC X` ganaban por
     origin_match cuando el correcto era COL. Nuevo campo
     `country` opcional en PROVIDERS y parser lo lee
     (`pdata.get('country', 'EC')`).
  2. Config `id=90038` ≠ catálogo `id_proveedor=9591` para
     Tierra Verde → `brand_by_provider[90038]` vacío, el
     autodetector nunca registraba "TIERRA VERDE" como brand
     propia. Añadido campo `catalog_brands` en PROVIDERS para
     registrar manualmente brands multi-palabra o cuando los IDs
     no coinciden. `_own_brands_norm` (matcher) y `_get_brands`
     (articulos) ambos lo leen.
  3. También: `_get_brands` ahora incluye `brands_by_provider`
     (marcas secundarias autodetectadas desde 10o — Uma VIOLETA).
     Antes solo miraba `brand_by_provider` top-1.
  4. Sinónimo `90038|ROSES|PINK O HARA|50|25|` corregido de
     `art=32348 status=ambiguo` a `art=35791 (ROSA OHARA ROSA
     ... TIERRA VERDE) status=manual_confirmado` — operador ya
     lo había guardado manualmente pero se degradó por el bug de
     10o-#3. Además TIERRA_VERDE1.pdf 3ok/2amb → **5/5 ok**;
     BARISTA 50CM 25U bench: 0.63 (foreign SCARLET) → **1.05
     link 1.000** (TIERRA VERDE branded). 11 Tierra Verde
     ambiguous del bench 10o (BARISTA, PRINCESS CROWN, SUNNY
     DAYS, MAGIC TIMES, LOLA, MANDALA) → todos ok automático.
- **Shadow loop cerrado (10n):** `handleSaveSynonym`
  en [web/api.php](web/api.php) ahora emite
  `_shadowLogDecision('correct', ..., proposed=0, decided=$artId)`.
  Antes, cuando el operador asignaba un artículo a un `sin_match`
  desde la UI (flujo más común del batch-line-save porque
  `oldArtId=0`), la acción se perdía para shadow — quedaba como
  "gap histórico" según comentario en
  [web/assets/app.js:1434](web/assets/app.js#L1434). Ahora se
  captura como **rescate** (matcher no propuso, operador asignó)
  y [tools/shadow_report.py](tools/shadow_report.py) lo separa
  visualmente de las **correcciones del matcher** (matcher
  propuso artículo distinto al correcto):
  - Nuevo breakdown en global: `confirmaciones / correcciones
    matcher / rescates sin_match`.
  - Nueva métrica "Accuracy del matcher cuando propuso"
    (denominador = confirm + correct real, excluye rescates para
    no diluir con cobertura humana extra).
  - `Top correcciones` ahora ignora rescates (no son errores del
    matcher); si no hay correcciones reales imprime "0 errores de
    matcher".
  - `Top correcciones` también corrige un bug previo que mostraba
    "propuso X / correcto X" (mismo nombre en ambos lados) cuando
    no había propuesta previa — ahora deja `propuso=''` si la
    propuesta no existe.
- **Fixes transversales sesión 10o (2026-04-23, record 94.1%):**
  **Detectado via shadow backlog** — 12 líneas Uma Flowers
  `GYPSOPHILA XL NATURAL WHITE 80cm` en `ambiguous_match`
  proponiendo 28189 (PANICULATA MIXTO genérico) en lugar de
  28248 (PANICULATA XLENCE BLANCO 1U **VIOLETA**). Diagnóstico
  encadenado reveló 4 bugs distintos — el más profundo llevaba
  un año sin aparecer porque nadie había procesado Uma GYPSOPHILA
  dos veces seguidas:
  1. **Multi-marca por proveedor**
     ([src/articulos.py](src/articulos.py)): `_build_brand_index`
     solo guardaba el top-1 por proveedor (Uma→UMA). Uma usa
     UMA en rosas (62 arts) y **VIOLETA en paniculata/gypsophila
     (24 arts)**. Nuevo field `brands_by_provider: dict[int,
     set[str]]` guarda TODAS las marcas que superan
     BRAND_MIN_ARTICLES. `_own_brands_norm` en matcher.py las
     incluye → `brand_in_name(UMA)` dispara en
     `PANICULATA ... VIOLETA` (VIOLETA ∈ own_brands de Uma).
  2. **`variety_no_overlap` destruía sinónimos manuales con
     traducción no-literal** ([src/matcher.py:334-350](src/matcher.py#L334)):
     `GYPSOPHILA XL NATURAL WHITE ↔ PANICULATA XLENCE BLANCO`
     son el mismo producto (VIOLETA es la línea comercial) pero
     no comparten tokens. El operador guardó el sinónimo manual,
     el matcher le aplicaba -0.10 → fuzzy 28189 ganaba por 0.04.
     Fix: si `cand.source=='synonym' AND trust >= 0.85`, no
     aplicar penalty. El sinónimo manual ES la prueba explícita.
  3. **El matcher degradaba sinónimos manuales en cada run**
     ([src/matcher.py:1057-1078](src/matcher.py#L1057)): cuando
     ganaba un `ok` vía `source=synonym`, llamaba
     `self.syn.add(..., 'auto')`. `add()` protegía solo si
     `prev.status=='manual_confirmado'` literal — pero muchas
     entries tenían `status=None` con `origen=manual-web`
     (derivadamente manual vía `_STATUS_BY_ORIGIN`, trust 0.98).
     Esas se reescribían con origen='auto', status=
     'aprendido_en_prueba' y trust 0.55. Fix aditivo:
     `if top1.source != 'synonym': self.syn.add(...)`. Sinónimo
     ganador no necesita re-alta — solo `register_match_hit`
     para incrementar times_confirmed (ya existía).
  4. **`plausible` check descartaba sinónimos sub-umbral**
     ([src/matcher.py:1090-1098](src/matcher.py#L1090)): si
     link < 0.70 y no había `variety_match` ni fuzzy ≥ 0.85,
     la línea caía a `sin_match`. Un sinónimo por definición
     ES plausible (el operador lo asertó). Fix aditivo:
     `plausible = ... or top1.source == 'synonym'`.

  Adicional: migración one-shot
  [tools/migrate_uma_gypsophila_spb.py](tools/migrate_uma_gypsophila_spb.py)
  para 12 sinónimos Uma GYPSOPHILA con `spb=0` (legacy del
  formulario manual antiguo) → `spb=25` (lo que emite el parser
  actual). 9 renamed, 3 dropped por conflicto (spb=25 existente
  era más fuerte). Backup en
  `sinonimos_universal.json.backup_uma_gypso_spb_*`.

  **Métricas**: líneas totales 3562 (benchmark stable) · ok 3212
  (+201) · ambiguous 144→134 · autoapprove **92.6% → 94.1%**
  (+1.5pp, nuevo récord histórico). weak_synonym 190→188 ·
  variety_no_overlap **232→165 (-29%)** · low_evidence 114→106.
  **Golden 997/997 (100%) intacto** en todo momento. UMA: 15/21
  ok → 21/21 ok (100%). Otros proveedores GYPSOPHILA (FLORSANI,
  MYSTIC) también beneficiados por el fix multi-marca.
- **Golden set:** 997/997 reviewed (24 facturas, 13 proveedores).
  **Link accuracy 100% (997/997)** intacto.
- **NO_PARSEA restantes:** 3 proveedores (CEAN GLOBAL, NATIVE
  BLOOMS, SAYONARA OCR-corrupto — ROI bajo).
- **Buckets:** OK 79 · NO_PARSEA 3 · TOTALES_MAL 0 ·
  NO_DETECTADO 1 (PONDEROSA).
- **Sesión 10m** (2026-04-22) — **7 fixes parsers
  shadow-driven** del primer lote real del operador (27 facturas).
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

**Drafts entregados (sesión 10q) para revisión interactiva**:
- [`golden/pendientes/florsani_750.json`](golden/pendientes/florsani_750.json)
  — FLORSANI2.pdf, 54 líneas (1 pendiente:
  `GYPSOPHILA XLENCE TINTED DARK RAINBOW 80cm 20spb` → matcher
  propone `PANICULATA XLENCE TEÑIDA RAINBOW FLORSANI` link 0.78).
- [`golden/pendientes/florsani_CB10.json`](golden/pendientes/florsani_CB10.json)
  — FLORSANI.pdf, 1 línea (`ORNITHOGALUM WHITE STAR 50cm 10spb`
  sin_match — no hay WHITE STAR FLORSANI en catálogo; genérico
  43864 `ORNITHOGALUM ECUADOR BLANCO 50CM 10U` puede servir).
- [`golden/pendientes/mystic_0000285929.json`](golden/pendientes/mystic_0000285929.json)
  — MYSTIC.pdf, 12 líneas (2 pendientes: `IMAGINATION 40cm 25spb`
  matcher propone FASCINATION por fuzzy 85% casual; `REDIANT`
  sin_match — probable OCR de RADIANT).

**UI pendiente — principio "id_erp/referencia en búsqueda"** (10q):
- El backend ya persiste `articulo_id_erp` en sinónimos
  (`_getArtIdErp` en `web/api.php`, llamado en
  `handleSaveSynonym`/`handleCorrectMatch`/`handleConfirmMatch`).
- **Falta el front**: `handleLookupArticle` (GET
  `api.php?action=lookup_article&id=N`) solo acepta el `id`
  autoincrement. Añadir un campo `id_erp` / `referencia` de
  búsqueda para los administrativos, y que devuelva ambos al
  frontend para persistir. Ver
  [`web/assets/app.js`](web/assets/app.js) línea 1479
  (`lookup_article` call en batch-line-save).

**Orden sugerido para la próxima sesión** (post-10n):

1. **Florsani — 45 pendientes en backlog** (mayor bucket sin
   decisión). Con el save_synonym ya logueado, basta con que
   Ángel confirme/corrija desde la UI un bloque y correr
   `shadow_report.py --top-errors 20 --provider Florsani` para
   ver si hay un patrón dominante (tints mal mapeados, sub-línea
   con spb/size heredado erróneo, variedad concatenada por OCR,
   etc.). Sospecha: las 45 son en gran parte el resultado de los
   fixes de 10m recuperando líneas nuevas sin sinónimo aún — un
   único bloque de correcciones en UI puede cerrar la mayoría.

2. **Uma Flowers — 13 `ambiguous_match` sobre GYPSOPHILA XL
   NATURAL WHITE 80cm** (todas proponiendo 28189). Patrón
   repetido, probable gap de sinónimo o tie_top2_margin residual.
   Revisar por qué el matcher no cierra como `ok` teniendo el
   mismo artículo siempre en top1.

3. **Auditoría box-code-in-variety en parsers pendientes**.
   El patrón "código de ruta/destino metido en la variedad"
   apareció en MYSTIC (CORUÑA/TNT), GARDA (ELOY/ASTURIAS/MARL),
   LIFE (MARL), ROSALEDA (ASTURIAS-ALBU, GIJON R-48, IRUÑA) y
   TURFLOR (GIJON/FVIDA/R19/GONZA) — todos arreglados. Pendiente
   auditar: **SAYONARA** (SP), **APOSENTOS** (ILIAS),
   **MONTEROSA** (EUGENIA), **EL CAMPANARIO** (ZAIRA). Grep
   sobre propuestas de shadow_log con varieties que contengan
   estos tokens UPPERCASE cortos al inicio.

4. **sin_match del backlog = artículos a dar de alta en ERP**.
   Montar `shadow_report.py --top-missing-articles` que liste
   variedades `sin_match` ordenadas por frecuencia global — da
   la lista priorizada para alta en ERP (MYSTIC/VALTHOMIG tenían
   varios según lo indicado por Ángel).

5. **Histórico aún útil — otros pasos arrastrados**:
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

### 2026-04-24 — sesión 11d: triage de páginas vacías evita OCR innecesario (3× speedup)

Ángel reportó que UMA 18383 tardaba mucho en procesarse. Perfilado:
5.1s end-to-end. `extraction_source=mixed, engine=ocrmypdf`. El
PDF tiene 2 páginas — la 1 nativa con 993 chars, la 2 **vacía**
(última página en blanco típica de exports). El triage marcaba la
página vacía como `'scan'` y disparaba OCRmyPDF global sobre todo
el PDF — OCR de una página literalmente en blanco.

**Cambio en [`src/extraction.py`](src/extraction.py)**:
- `_triage_pdf` ahora devuelve 3 estados: `'native'`, `'empty'`
  (chars=0 AND words=0) y `'scan'` (tiene contenido pero sin texto
  utilizable).
- La rama rápida (sin OCR) acepta ahora `all(v in ('native',
  'empty'))` **siempre que al menos una página sea native**. Las
  empty aportan un `PageExtraction(text='', source='native',
  confidence=1.0)`.
- Guardrail: si **ninguna** página es native, las `'empty'` se
  reclasifican a `'scan'` — indica un PDF íntegramente escaneado
  sin capa de texto (CANTIZA sample V.075-6577 1440 con 0 chars).

**Métricas**:
- UMA 18383: 5.1s → **1.75s** (−66%, 3×).
- Benchmark global: 3562 líneas, 3333 ok, 50 ambig — **idéntico**
  al pre-fix. Sin regresiones en CANTIZA (PDFs escaneados puros)
  ni en providers con multi-página.
- Aplica a cualquier PDF con última página en blanco (~30% de
  las facturas UMA según muestreo rápido).

**Lección transversal** (candidata `docs/lessons.md`): el triage
binario `native vs scan` es demasiado pobre cuando `scan` arrastra
como consecuencia "ejecuta OCR global". Un tercer estado explícito
para páginas vacías evita invocar OCR sobre nada. La regla
`ninguna native → todas las empty son scan` protege los
escaneados íntegros (donde `empty` es `scan` disfrazado).

### 2026-04-24 — sesión 11c: skip pattern falso positivo bloqueaba UMA 18383

Ángel reportó que una factura UMA real (`18383._Veraleza-20-Abril_
2026-Saftec.pdf`) "se quedaba cargando todo el rato" al procesarla
desde la UI. Inspección del `batch_status/*.json`: la factura caía
en `omitidos_detalle` con motivo `"Omitido: documento no es factura
(SAFTEC)"`. El bug: [`batch_process.py`](batch_process.py) tenía
`SKIP_PATTERNS = [..., 'SAFTEC', ...]` y `_should_skip` hacía
`if pat in upper:` — match por substring en cualquier posición
del nombre. El archivo contenía la palabra "Saftec" solo como
sufijo (la agencia de carga) y se confundía con una factura de
SAFTEC.

**Cambio**: nuevo `_should_skip` más estricto. Normaliza el nombre
(sin extensión, quitando prefijos no-alnum) y skipea solo si el
primer token alfanumérico del nombre coincide con un patrón de la
lista. Si arranca con dígitos (número de factura típico), nunca
skipea. Tabla de 12 casos de test pasa: `SAFTEC.pdf`,
`SAFTEC_VERALEZA.pdf`, `DUA_34342.pdf`, `FESO_CARGO.pdf` skipean;
`18383._Veraleza-...-Saftec.pdf`, `UMA SAFTEC.pdf` (UMA legítimo
en historial), `ECOFLOR-...-Saftec.pdf`, `123-DUA.pdf` pasan.

**Parser UMA — fix descartado**: el PDF 18383 trae 2 líneas con
variety `GYPSOPHILA XLENCE NATURAL WHITE` que caen a `fuzzy 53%`
ambig porque el sinónimo manual_confirmado existente usa la forma
corta `GYPSOPHILA XL NATURAL WHITE` (Uma mezcla ambas formas en
el mismo PDF). Intenté canonicalizar `XLENCE → XL` en
`UmaParser` pero rompió 7 líneas del benchmark (otras facturas
emiten `GYPSOPHILA XLENCE` *sin* más tokens y matcheaban el
sinónimo XLENCE puro). Revertido. El flujo operativo normal
resuelve esto: Ángel corrige las 2 ambig desde la UI, el
`register_match_hit` (10g) promociona tras 2 usos.

**Resultado en UMA 18383**: antes: omitido como SAFTEC. Ahora:
3 líneas parseadas, header $2,754 cuadra, 1 ok + 2 ambig (las
NATURAL WHITE — dentro del flujo operativo normal).

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
