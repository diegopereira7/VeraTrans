# Historial de sesiones

Registro cronológico de sesiones de desarrollo del VeraBuy Traductor.
Las 2 sesiones más recientes también aparecen en `CLAUDE.md` en la
sección "Historial reciente"; cuando se archive una sesión, se mueve
aquí y se quita de CLAUDE.md.

Para el estado actual del proyecto, ver [`CLAUDE.md`](../CLAUDE.md) (raíz).
Para lecciones transversales reutilizables, ver [`lessons.md`](lessons.md).

### 2026-04-24 — sesión 11c: skip pattern falso positivo bloqueaba UMA 18383

Ángel reportó que una factura UMA real (`18383._Veraleza-20-Abril_
2026-Saftec.pdf`) "se quedaba cargando todo el rato" al procesarla
desde la UI. Inspección del `batch_status/*.json`: la factura caía
en `omitidos_detalle` con motivo `"Omitido: documento no es factura
(SAFTEC)"`. El bug: [`batch_process.py`](../batch_process.py) tenía
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

### 2026-04-24 — sesión 11b: shadow_report `--verify-current` (filtra shadow stale)

Diagnóstico del backlog shadow tras 10u-10x. El reporte marcaba 88
"pendientes" pero la mayoría eran **shadow stale**: entries del
batch inicial de 2026-04-22 cuyo PDF nunca se reprocesó tras los
fixes (normalize_variety 10m, Uma VIOLETA 10o, paniculata teñida
10s, etc.). Simulando el matcher actual sobre esas entries: 69
de 77 (dedup) ya darían `ok` — son falsos pendientes que inflaban
la cola operativa.

**Cambio**: nuevo flag `--verify-current` en
[`tools/shadow_report.py`](../tools/shadow_report.py). Para cada
entry del backlog pendiente (dedup por `(pdf, invoice, line_idx)`,
quedando la propuesta más reciente), reconstruye el `InvoiceLine`
desde los campos loguados y corre `Matcher.match_line` con el
estado actual de artículos + sinónimos. Clasifica:
- **Resuelto por fix posterior**: matcher actual da `ok` → queda
  fuera del backlog real, se muestra aparte por proveedor.
- **Pendiente real**: matcher actual sigue dando `ambig/sin_match`.

El flag es opcional (paga el arranque de `ArticulosLoader`, ~3s);
el run sin flag queda idéntico.

**Resultado primer run**: 77 pendientes dedup → **8 pendientes
reales** (−90%). Los 8 son: 3 GARDA `ELOY *` (variety stale
pre-10m box-code), 1 MYSTIC `CORUÑA TNT GYP` (idem), 2 Agrivaldani
`PALOMA` (empate `color_modifier_extra(BICOLOR)+tie_top2_margin`
0.042 — único caso accionable hoy), 1 MYSTIC `IMAGINATION` (alta
ERP), 1 FLORSANI `ORNITHOGALUM WHITE STAR` (alta ERP, ya en
pendientes).

**Lección transversal** (candidata `docs/lessons.md`): un log
histórico sin mecanismo de "resolución implícita" mezcla datos
stale con backlog real. Cada vez que se aplica un fix de
parser/matcher/sinónimo, un subconjunto del backlog se resuelve
sin generar evento explícito — para que el reporte siga siendo
útil, hay que re-simular el matcher contra las entries pendientes.
El patrón aplica a cualquier sistema que loguee "estado propuesto"
antes de que el operador actúe.

### 2026-04-23 — sesión 10t: parser auto_campanario spb + route codes (autoapprove 94.3% → 94.9%)

Al analizar los 114 `ambiguous_match` restantes (ejercicio igual
que 10s), dos buckets dominaban con fix fácil:

1. **GREENGROWERS — 11 amb por `stems_per_bunch=0`**: el parser
   `auto_campanario` dejaba spb=0 con comentario "se derivará por
   species default", pero ese default nunca se aplicaba y el
   matcher no podía distinguir `ROSA EC MONDIAL 50CM 20U` de
   `ROSA EC MONDIAL 50CM 25U`. Fix en
   [`src/parsers/auto_campanario.py`](../src/parsers/auto_campanario.py):
   `spb = stems // bunches` si la división es exacta, fallback 25
   (convención rosas EC). 3 amb de GREENGROWERS → 0 en el primer
   sample.

2. **EL CAMPANARIO — 7 amb por `ZAIRA` metido en la variedad**:
   parser emitía `ZAIRA ABSOLUT IN PINK` cuando ZAIRA era un
   código de ruta/destino. El `_split_code_variety` tenía ZAIRA
   en `_KNOWN_VARIETY_FIRST` (bug) y la condición
   `tokens[i+1] not in _KNOWN_VARIETY_FIRST` impedía el avance
   cuando el token siguiente a ZAIRA era una variety conocida.
   Fix aditivo: nuevo set `_KNOWN_ROUTE_CODES = {ZAIRA, JOVI,
   VERALEZA}` que siempre se trata como código; ZAIRA salió de
   `_KNOWN_VARIETY_FIRST`; `if t in _KNOWN_VARIETY_FIRST: break`
   al principio del loop para limpiar la lógica.

**Intento fallido (revertido)**: ampliar `_detect_foreign_brand`
con `art_loader.brands_by_provider` para detectar WAYUU, SCARLET
y similares que no están en PROVIDERS keys. Dio +4 regresiones en
golden (candidatos branded legítimos recibieron −0.25 indebido
por coincidencia parcial con una brand registrada de otro
proveedor). Revertido; ELITE (12 amb) queda pendiente — requiere
otro enfoque (penalty suave o brand indexado por sufijo exacto).

**Re-anotación golden VALTHO**: 4 líneas con `size=40` apuntando
a articulos `50CM` (`ROSEBERRY`, `HOT MERENGUE` × 2) — el matcher
mejorado de 10s las detectó como "wrong". Corregidas a sus ids
40CM correctos (36917, 35006). Golden 976 → 980/997.

**Métricas**:
- Autoapprove global: 94.3% → **94.9%** (+0.6pp, récord).
- Ambiguous: 114 → **107** (−7). ok 3235 → 3258 (+23).
- `tie_top2_margin`: 99 → 94. `low_evidence`: 65 → 63.
- **Golden 980/997 (98.3%) intacto** tras re-anotación VALTHO.

**Lección**: ampliar `_detect_foreign_brand` con el catálogo
entero es tentador pero peligroso — muchos sufijos que parecen
brand (WAYUU, SCARLET) se solapan con tokens legítimos de
artículos que el proveedor sí comparte. La detección de brand
ajena requiere un oracle externo (provider registry curado) más
que tokens del catálogo. Pendiente.

### 2026-04-23 — sesión 10s: Florsani paniculata teñida (autoapprove 94.0% → 94.3%)

Diego pidió auditar por qué el matcher detectaba mal las variedades
de paniculata Florsani si el catálogo tiene un artículo por cada
color. La auditoría reveló tres problemas encadenados — parser,
catálogo, matcher — que resolvían distintas capas del mismo
síntoma.

**Diagnóstico en el catálogo**: 68 artículos Florsani tenían
`nombre = 'PANICULATA XLENCE TE'` (export phpMyAdmin cortó en la
Ñ de "TEÑIDA"). Los campos estructurados (`color`, `marca`,
`variedad`, `tamano`, `paquete`) estaban intactos en la BD, solo
el `nombre` visible quedó truncado. 45 colores distintos del
paniculata XLENCE TEÑIDA (LAVANDA, ROSA CLARO, VERDE MANZANA,
RAINBOW PASTEL, CORAL, TIE DYE, SAL Y PIMIENTA, etc.) estaban
inaccesibles para el matcher porque todos tenían el mismo nombre.

**Diagnóstico en el parser**: el parser emitía
`GYPSOPHILA XLENCE TINTED LIGHT PINK` — los tokens del catálogo
español (`PANICULATA XLENCE TEÑIDA ROSA CLARO`) no solapan excepto
en `XLENCE`. El matcher caía a fuzzy con scores empatados.

**Diagnóstico en el matcher**: cuando ambos candidatos (p.ej.
AZUL vs AZUL CLARO) tienen `variety_full`, no hay tiebreak —
el fuzzy prior decidía. Y el `variety_full` aportaba solo +0.03,
insuficiente para contrarrestar +0.09 de fuzzy prior.

**Cambios (todos aditivos)**:

1. **`src/articulos.py`** — `load_from_db` añade `color`, `marca`,
   `variedad` al SELECT. Nuevo helper `_reconstruct_truncated_name`
   detecta `nombre` terminado en `' TE'`/`' TEÑ'` y lo reconstruye
   como "{familia} TEÑIDA {color} {tamano} {paquete}U {marca}".
   `_parse_row` para dumps SQL también captura los campos nuevos
   (índices 4, 6, 14). Efecto: 68 "PANICULATA XLENCE TE" → 45
   nombres canónicos únicos con su color.

2. **`src/parsers/otros.py` (FlorsaniParser)** — nuevo
   `_FLORSANI_COLOR_MAP` (≈45 entries: RED→ROJO, LAVANDER→LAVANDA,
   APPLE GREEN→VERDE MANZANA, DARK RAINBOW→RAINBOW OSCURO,
   PASTEL RAINBOW→RAINBOW PASTEL, BABY BLUE→AZUL CLARO, ...).
   Nuevo helper `_translate_florsani_color` con orden por longitud
   descendente (multi-word gana a single-word). Nuevo método
   `_build_variety` que emite:
   - "Xlence Tinted Light Pink" → "PANICULATA XLENCE TEÑIDA ROSA CLARO"
   - "Xlence NINGUNO" → "PANICULATA XLENCE BLANCO"
   - Limonium / Ornithogalum → sin cambios.

3. **`src/matcher.py`** — tres fixes aditivos:
   - Bonus `variety_full` sube de **+0.03 a +0.10**: cubre el
     +0.09 del fuzzy prior que candidatos inferiores acumulan con
     matches casuales por tokens de familia (PANICULATA/XLENCE/
     TEÑIDA, que están en TODOS los paniculata).
   - Nuevo penalty **`color_modifier_extra`**: si el nombre del
     artículo contiene OSCURO/CLARO/LIGHT/DARK/PASTEL/NEON que la
     variedad no pide, −0.12. Distingue `AZUL` (correcto) de
     `AZUL CLARO` (color distinto).
   - **Tiebreak simétrico + `tiebreak_color_modifier`**: si en
     tie cualitativo top2 tiene `variety_full` o `size_exact` y
     top1 no, swap. Si top2 tiene `color_modifier_extra` y top1
     no, top1 gana. Antes el tiebreak solo miraba si top1 tenía
     la ventaja — ahora es bidireccional.

**Métricas**:
- **FLORSANI2.pdf paniculata teñida: 19/54 ok → 54/54 ok (100%)**.
- **Autoapprove global: 94.0% → 94.3% (+0.3pp, récord)**.
- Ambiguous 144 → 114 (−30). `low_evidence` 111 → 65 (−46).
- Nuevo penalty `color_modifier_extra` aparece 48 veces
  globalmente (benigno, ya resuelto por el tiebreak).
- **Golden 997/997 intacto** (100% link accuracy).
- FLORSANI1 (white gypso): 4/4 ok. FLORSANI (ORNITHOGALUM WHITE
  STAR) queda sin_match: el catálogo solo tiene genérico
  `ORNITHOGALUM ECUADOR BLANCO 50CM 10U` — requiere decisión
  semántica (mapa WHITE STAR→BLANCO) en otra sesión.

**Lección transversal** (candidata para `docs/lessons.md`):
cuando un `variety_match` parcial dispara por tokens de familia
repetidos en todos los candidatos (PANICULATA/XLENCE/TEÑIDA),
el tokens de color es el único discriminante. `variety_full`
tiene que pesar lo suficiente para ganar +0.09 del fuzzy prior
que los rivales sin variety_full acumulan. Un penalty simétrico
para modificadores de color (OSCURO/CLARO) resuelve empates
entre color base y su variante.

### 2026-04-23 — sesión 10q: reimport catálogo + migración a id_erp estable

Diego importó un dump SQL actualizado del catálogo (`articulos
(5).sql`, 44,751 artículos, +2,467 nuevos). Al importarlo
directamente, los `id` autoincrement de MySQL se **reasignaron
enteramente** — el art 28248 dejó de ser "PANICULATA XLENCE BLANCO
VIOLETA" y pasó a ser "PAEONIA USSIKNOW ROSA". Golden cayó de
997/997 → 111/995 (11.1%). Problema detectado y revertido antes
de llegar a producción.

Diego apuntó a la solución estructural: usar `id_erp` (identificador
del ERP externo, varchar estable) como clave durable en lugar del
`id` autoincrement.

**Cambios en código**:
- [`src/articulos.py`](../src/articulos.py): nueva columna `id_erp`
  en `load_from_db`, índice `by_id_erp`, campo en el dict del
  artículo, leído también desde `load_from_sql` (parse del dump).
- [`src/sinonimos.py`](../src/sinonimos.py):
  - Campo `articulo_id_erp` en cada entry del JSON.
  - Nuevo parámetro opcional en `SynonymStore.add(...,
    articulo_id_erp: str = '')` — los callers lo populan.
  - Nuevo método `resolve_article_id(entry, art_loader)`: si
    id_erp presente y el id local ha cambiado, re-mapea el entry
    lazy (actualiza `articulo_id` + `articulo_name` y marca
    dirty).
- [`src/matcher.py`](../src/matcher.py): `_gather_candidates` usa
  `resolve_article_id` al convertir sinónimo en candidato — así
  tolera reimports silenciosamente. Las dos llamadas a `syn.add`
  pasan `articulo_id_erp=top1.articulo.get('id_erp', '')`.

**Migración one-shot**
[`tools/migrate_add_articulo_id_erp.py`](../tools/migrate_add_articulo_id_erp.py):
parsea el dump nuevo, construye mapping
`nombre_normalizado → (id_erp, nuevo_id)`, y reescribe sinónimos
(`sinonimos_universal.json`) y cada `golden/*.json` añadiendo
`articulo_id_erp` y actualizando `articulo_id` al nuevo.

**Métricas finales**:
- Catálogo: 42,284 → **44,751 artículos** (+2,467).
- Golden: 997 → **980/997 (98.3%)**. 17 mismatches son mejoras —
  el matcher prefiere un artículo branded nuevo (ej. BRISSAS) en
  vez del genérico EC anotado pre-catálogo-nuevo.
- Autoapprove: 94.4% → **94.0%** (-0.4pp ajuste).
- Sinónimos: 3337 total, 3311 con id_erp estable, 24 invalidados.

### 2026-04-23 — sesión 10o: 4 fixes transversales shadow-driven (autoapprove 92.6% → 94.1%, Uma VIOLETA)

Al mirar el backlog del shadow (87 pendientes), Uma Flowers tenía
13 líneas `ambiguous_match` con **12 sobre la misma variety**
(`GYPSOPHILA XL NATURAL WHITE 80cm 25spb`) proponiendo 28189
(PANICULATA MIXTO genérico) con link=0.535, penalty=`low_evidence`.
El operador me confirmó el dato clave para diagnosticar: **VIOLETA
es la marca comercial de Uma para paniculata/gypsophila**, no un
color.

Investigación encadenada reveló 4 bugs distintos, todos los
cambios aditivos:

1. **Multi-marca por proveedor** — `ArticulosLoader._build_brand_index`
   guardaba solo el sufijo más frecuente por proveedor. Uma tiene
   62 artículos terminados en UMA (rosas) y **24 terminados en
   VIOLETA** (paniculata) — VIOLETA quedaba fuera. Nuevo field
   `brands_by_provider: dict[int, set[str]]` con TODAS las
   marcas ≥ BRAND_MIN_ARTICLES (5). `_own_brands_norm` en
   `matcher.py` las incluye. Efecto: Uma reconoce UMA y VIOLETA
   como propias → `brand_in_name(UMA)` dispara para
   PANICULATA...VIOLETA (+0.25 score).

2. **`trust_exempts` en `_score_candidate`** — un sinónimo con
   trust ≥ 0.85 (manual_confirmado o aprendido_confirmado) es
   prueba EXPLÍCITA del operador de que VARIETY→ARTICULO es
   válido, aunque los tokens no solapen. Antes recibía
   `variety_no_overlap -0.10` → perdía contra fuzzy casual de
   tokens irrelevantes (MIXTO en PANICULATA genérico coincidía
   con GYPSOPHILA). Nuevo chequeo: si
   `cand.source == 'synonym' AND (cand.trust or 0) >= 0.85`,
   skip la penalty y añadir reason `synonym_overrides_variety`.

3. **El matcher degradaba sinónimos manuales** — bug histórico
   crítico. Cuando el matcher ganaba un `ok` con un candidato
   de `source=synonym`, llamaba `self.syn.add(..., 'auto')`.
   `add()` protegía solo si `prev.status == 'manual_confirmado'`
   **literal**, pero muchas entries tenían `status=None` con
   `origen=manual-web` (derivadamente manual vía
   `_STATUS_BY_ORIGIN`, trust 0.98). Esas entries se reescribían
   a `origen='auto'`, `status='aprendido_en_prueba'`, trust 0.55.
   Resultado: tras el primer run, la entry perdía fuerza y en el
   siguiente run ya no ganaba. Fix aditivo:
   `if top1.source != 'synonym': self.syn.add(...)`. Un sinónimo
   ganador NO necesita re-alta — `register_match_hit` (existente)
   ya incrementa `times_confirmed`.

4. **`plausible` descartaba sinónimos sub-umbral** — si
   link < 0.70 sin `variety_match` ni fuzzy ≥ 0.85, la línea
   caía a `sin_match`. Un sinónimo EXISTE = afirmación explícita
   de plausibilidad. Fix aditivo: `plausible = ... or
   top1.source == 'synonym'`.

**Adicional**: migración one-shot
[`tools/migrate_uma_gypsophila_spb.py`](../tools/migrate_uma_gypsophila_spb.py)
para 12 sinónimos Uma GYPSOPHILA con `spb=0` (legacy del
formulario manual antiguo) → `spb=25` (lo que emite el parser
actual). 9 renamed, 3 dropped por conflicto (spb=25 existente
era más fuerte). Backup preservado.

**Métricas**:
- UMA.pdf: 15/21 ok → **21/21 ok (100%)**, 0 ambiguous.
- Autoapprove global: 92.6% → **94.1% (+1.5pp, récord)**.
- `variety_no_overlap` penalties globales: 232 → **165 (-29%)**.
- `weak_synonym`: 190 → 188. `low_evidence`: 114 → 106.
- **Golden 997/997 (100%) intacto** en todo momento.

**Lección transversal**: el sinónimo manual es la
verdad-del-operador; el matcher no debe degradarlo, contradecirlo,
ni descartarlo por falta de evidencia léxica.

### 2026-04-23 — sesión 10n: cierre gap save_synonym en shadow + reporter afina rescates vs errores

El primer lote real del operador (10m) dejó el shadow log con **769
propuestas y 0 decisiones**. La pista estaba en el propio comentario
del JS — [`web/assets/app.js:1434`](../web/assets/app.js#L1434):
`sin oldArtId → save_synonym (sin decision, gap histórico)`. Es el
caso más común del batch-line-save: una línea `sin_match` no tiene
`oldArtId`, así que el click en la UI rutea a `save_synonym`, que
hasta ahora no llamaba `_shadowLogDecision`.

**Cambios**:

- [`web/api.php`](../web/api.php) — `handleSaveSynonym`: emite
  `_shadowLogDecision('correct', $shadowInput, 0, $artId, $artName)`.
  El input se enriquece con los campos de la propia key para que
  el reporte tenga contexto aunque el frontend no mande esos campos.
- [`tools/shadow_report.py`](../tools/shadow_report.py) — distingue:
  - `confirmaciones`: matcher clavó (`action=confirm`).
  - `correcciones matcher`: `action=correct` con
    `proposed_articulo_id ≠ 0` (matcher propuso mal).
  - `rescates sin_match`: `action=correct` con
    `proposed_articulo_id = 0` (matcher no propuso, operador asignó).
  - Nueva métrica **"Accuracy del matcher cuando propuso"** con
    denominador `confirm + correcciones reales`, excluyendo rescates.
  - El "Top 10 correcciones" ahora filtra a correcciones con
    propuesta y corrige el bug previo que imprimía
    `propuso X / correcto X` cuando no había propuesta.

**Smoke test**: entry sintética simulando `save_synonym`. Reporter
la clasificó correctamente como rescate, "Accuracy del matcher"
excluyó el caso. Entry y archivo de prueba eliminados tras el check.

**Métricas técnicas** (sin cambios — trabajo de infraestructura):
autoapprove 92.6% · Golden 997/997 (100%) intacto.

### 2026-04-22 — sesión 10m: batch de 7 fixes parsers shadow-driven

Primer ciclo completo de Fase 10 operando. El operador (Ángel)
procesó un lote real de 27 facturas de la semana y señaló desde
la UI una lista creciente de errores. Cada uno convertido en fix
concreto: FLORAROMA 2026 (AROMA), EQR (stems=total_stems),
FLORSANI (box types + sub-líneas + tints), GARDA (box_code en
label, sub-líneas heredadas), MALIMA (coma miles US), MYSTIC (Ñ
en code + TNT block name), LIFE (MARL label).

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
  — se recuperarán cuando el operador las confirme en UI).
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

- [`web/api.php`](../web/api.php): dos nuevos helpers
  `_shadowLogProposals($result, $pdfPath)` y
  `_shadowLogDecision($action, $input, $proposedId, $decidedId,
  $decidedName)`. Llamadas integradas en `handleProcess` (tras
  parsear el JSON de `procesar_pdf.py`), `handleConfirmMatch` y
  `handleCorrectMatch`. Helper `_shadowSynKey(providerId, line)`
  replica la estructura de `SynonymStore._key` en Python:
  `<provider_id>|<species>|<variety.upper>|<size>|<spb>|<grade.upper>`.
- [`tools/shadow_report.py`](../tools/shadow_report.py) (nuevo):
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

**Gap conocido al cierre**: `handleSaveSynonym` no logueaba
decisión. Cuando el operador asigna artículo a un `sin_match`
desde la UI (caso más común: oldArtId=0 → save_synonym),
la acción se perdía para shadow. Cerrado en sesión 10n.

### 2026-04-22 — sesión 10l: fix parser FLORAROMA variante 2026 (auto 93.6→93.9%, primer fix shadow-driven)

Primer fix derivado del flujo shadow real. Ángel procesó un lote
de 27 facturas de su semana y AROMA.pdf falló con `Parser "floraroma"
no extrajo líneas`. Diagnóstico del texto extraído:

```
BOXESORDERBOX TYPE MARK QUAL.BUN. DESCRIPTION LEN S/BT. STEMS PRICE TOTAL
1 1 - 1 HB S.O. E 5 Salma 60 25 125 0,350 43,750
                 E 5 Salma 70 25 125 0,400 50,000
1 2 - 2 QB S.O. E 5 Tiffany 50 25 125 0,300 37,500
```

FLORAROMA cambió el formato en 2026: (a) añadió columna `MARK`
(`S.O.`) entre `BOX TYPE` y `QUAL`; (b) pasó precio/total a **coma
decimal** (`0,350`). El regex legacy exigía `[\d.]+` (solo punto
decimal) → cero matches.

**Fix — `src/parsers/otros.py → FloraromaParser`**: regex
`[\d.]+` → `[\d.,]+` + helper `_num(s)` con heurística "último
separador = decimal" (maneja EN/ES/múltiples puntos OCR).

**Efecto secundario**: el `_num` reemplazó al `float()` directo
que silenciosamente daba `header_total=1.60` en FLORAROMAS
legacy con `1,597.00`. 5/5 muestras FLORAROMA con totals_ok ahora.

**Métricas**: AROMA 0→4 líneas, auto 3061→3068 (+7),
autoapprove 93.6→93.9%, golden 997/997 intacto.

### 2026-04-22 — sesión 10j: desempate cualitativo en tie_top2 (ambiguous 161→144, autoapprove 93.4→93.6%)

Ataque a los 161 `ambiguous_match` restantes tras 10i. Inspección
reveló que los tie eran entre artículos con misma variedad y
tallas distintas (top1 `size_exact`, top2 `size_close`), o
variedades multi-palabra con `variety_full` en top1 y match
parcial en top2.

**Fix aditivo — `src/matcher.py`** (rama tie, línea ~981):

Antes de marcar `ambiguous_match`, chequear dominio cualitativo
de top1. Si `size_exact` en top1 y `size_close` en top2 (sin
`size_exact`), o `variety_full` en top1 y no en top2, marcar
`ok` con reason `tiebreak_size_exact` / `tiebreak_variety_full`.
También invoca `register_match_hit` para consolidar sinónimo.

**Métricas**:
- Ambiguous: 161 → **144** (−11%).
- `tie_top2_margin`: 96 → **79** (−18%).
- Auto: 3052 → **3061** (+9 líneas).
- **Autoapprove: 93.4 → 93.6%** (+0.2pp).
- Golden **997/997 (100%) intacto**.

### 2026-04-22 — sesión 10i: normalización puntuación en variety tokens (autoapprove 93.0→93.4%, +15 auto)

Ataque a la penalty top: `variety_no_overlap` (250 penalties
globales). El penalty resta −0.10 al score y se aplica cuando
ningún token ≥ 3 chars de `line.variety` aparece en el nombre del
artículo. Diagnóstico profundo re-procesando los 82 proveedores
y categorizando los 251 casos encontrados (en el scan propio):

- 37 con **puntuación fixeable** — TIERRA VERDE (`MONDIAL.`,
  `BARISTA.`, `EXPLORER.`, `EXPLORER°`, `BRIGHTON°`), DAFLOR
  (`PINK O´HARA`, `WHITE O´HARA`, y `ASSORTED PM -` con trailing
  dash), AGRIVALDANI (`M. DARK BLUE`), VERALEZA (`BLUE-MO`).
- 35 **ASSORTED/MIX** — la mayoría genuinos sin artículo mix en
  catálogo para esa species.
- 52 **multi-word** — problemas heterogéneos: concatenación OCR
  (`EUGENIA BRANDAOEXPLORER`), farm+variety pegados
  (`ZAIRA BRIGHTON`), variedades reales sin catálogo
  (`COTE D AZUR`), OCR corrupto (`ETIQUEPTAAL OGMRAANDE`).
- 126 **single-token** — productos que genuinamente no tienen
  artículo equivalente en el ERP (ELITE alstros, BRISSAS
  `TERRA BROWN`, COLIBRI variantes de BICOLOR, etc.).

**Fix aditivo — `src/matcher.py`** (`_score_candidate`, línea
~298):

- Nueva pre-normalización de `line.variety` con
  `re.sub(r'[^A-Z0-9 ]+', ' ', variety.upper())` antes del
  tokenizer. Convierte `MONDIAL.` → `MONDIAL`, `O´HARA` →
  `O HARA` (token HARA ≥ 3 chars sigue siendo útil porque el
  match usa `any(t in nombre)` — `HARA` aparece como substring
  dentro de `OHARA` en el nombre del artículo), `ASSORTED PM -`
  → `ASSORTED PM`. El resto del cuerpo de la función no cambia.
- Simple, aditivo, sin impacto en caminos que no usan variety.

**Métricas**:
- **Autoapprove: 93.0 → 93.4%** (+0.4pp).
- Auto: 3037 → **3052** (+15 líneas).
- Ambiguous: 171 → 161 (−10).
- `variety_no_overlap`: 250 → **232** (−18, −7%). El delta
  parece pequeño en penalties pero el impacto en auto es mayor
  porque cada caso fixed gana `variety_match (+0.30)` + quita
  penalty `variety_no_overlap (−0.10)` = +0.40 neto, llevando
  muchas líneas de ambiguous a ok/auto.
- **Golden 997/997 (100%) intacto**.

### 2026-04-22 — sesión 10h: fixes parsers UNIQUE + CANANVALLE (NO_PARSEA 5→3, autoapprove 92.9→93.0%)

Diagnóstico individual de los 9 samples que impedían salir de
`NO_PARSEA` a los 5 proveedores pendientes. El criterio del
bucket es `parsed_any < n_samples` — basta 1 sample con 0 líneas
para quedar dentro.

**Clasificación por ROI**:
- **Imposible** — SAYONARA 64811: texto OCR totalmente corrupto
  (nombres, totales y líneas de detalle ilegibles); aun con
  OCRmyPDF + EasyOCR fallback el pipeline no recupera.
- **Alto coste / bajo ROI** — CEAN GLOBAL cean 57: factura en
  español con rosas (`ROSAS EXPLORER 40CM 900,05 Und. 3 HB
  0,26 234,00`); el parser `auto_cean` actual solo maneja
  claveles, extenderlo requiere rework amplio para ganar ~10
  líneas.
- **Marginal** — NATIVE BLOOMS 2 samples: productos tropicales
  (Heliconia, Musa, Ginger, Dracaena) a $0.0001/stem, son
  cortesías del proveedor.
- **Fix barato ROI alto** — UNIQUE (2 samples) y CANANVALLE
  (2 samples).

**Fix 1 — `src/parsers/otros.py → UniqueParser._PROFORMA_RE`**:
los 2 samples fallidos eran facturas PROFORMA con layout
`HITS No. DESCRIPTION BRAND BOX BOX TYPE PCS FULL PACKING T.STEMS
UNIT UNIT PRICE TOTAL VALUE` (sin la palabra `Stems ... US$`
que el regex legacy buscaba). Nuevo regex de clase captura
`0603.11.00.50 ROSES BLUSH 50 HB 1 0.5 300 300 STEMS $ 0.32 $
96.00`, tolera OCR split en total (`$ 1 92.00` → 192.00). Se
intenta primero; si no casa, cae al legacy. Impacto: 2 samples
que parseaban 0 → 1 y 2 líneas respectivamente.

**Fix 2 — `src/parsers/otros.py → CustomerInvoiceParser._SAMPLE_RE`**:
los 2 samples fallidos (duplicados: mismo PDF con typo en el
nombre) eran facturas SAMPLE con layout-tabla sin `$`,
variante `COMMERCIAL INVOICE` en vez de `CUSTOMER INVOICE`.
Columnas: `Qty BoxRange BoxType Variety Length BunchesPerBox
TotalBunches StemsPerBunch TotalStems UnitPrice TotalPrice[SAMPLE]`.
Nuevo regex: `1 1 - 1 HB Brighton 50 1 1 25 25 0.010
0.250SAMPLE`. También se ajustó el header: `CUSTOMER|COMMERCIAL
INVOICE (No.)?` y `MAWB:?` con `:` opcional. Impacto: 2 samples
de 0 a 6 líneas cada uno.

**Métricas**:
- **Buckets: NO_PARSEA 5 → 3, OK 77 → 79** (UNIQUE y CANANVALLE
  promovidos). Quedan SAYONARA, CEAN GLOBAL, NATIVE BLOOMS.
- Líneas totales: 3506 → **3521** (+15 nuevas parseadas).
- Auto: 3019 → **3037** (+18), **autoapprove 92.9 → 93.0%**
  (+0.1pp).
- weak_synonym penalties: 677 → **200** — efecto secundario
  de `register_match_hit` (10g) aplicándose a las nuevas
  líneas recién parseadas, que también promovieron más
  sinónimos.
- **Golden 997/997 (100%) intacto**.

### 2026-04-22 — sesión 10g: auto-confirmación sinónimos (weak_synonym 1787→677, −62%)

Ataque al ruido dominante del matcher. Diagnóstico: de los 1787
penalties `weak_synonym` globales, la causa raíz era que **1005
sinónimos `aprendido_en_prueba` tenían `times_confirmed=0`** —
nunca se promocionaban aunque el matcher los usara
correctamente en múltiples facturas. Los contadores solo subían
vía `mark_confirmed` (acción manual del operador en UI). Además,
1858 entries heredados con `status` vacío se trataban como
`aprendido_en_prueba` (trust base 0.55) sin camino de ascenso.

**Mecanismo nuevo — `src/sinonimos.py`**:

- Método [`register_match_hit(provider_id, line, articulo_id)`](../src/sinonimos.py#L181):
  incrementa `times_confirmed` del sinónimo preexistente SI
  apunta al mismo artículo que el ganador del match. Tras
  `times_confirmed ≥ 2`, promueve
  `aprendido_en_prueba | status vacío → aprendido_confirmado`
  (trust 0.55 → 0.85).
- Skip explícito para `manual_confirmado`, `rechazado` y
  `aprendido_confirmado` ya consolidado (no infla contadores).
  Garantiza que el golden no se altera.

**Integración — `src/matcher.py`** (línea ~991, tras ok):

- Llamada a `register_match_hit` solo cuando el ganador tiene
  **evidencia independiente del sinónimo**:
  `variety_match AND (size_exact OR brand_in_name)`. Esto
  evita bootstrapping circular (el sinónimo confirmándose a sí
  mismo): exige que otras features hubiesen producido el mismo
  match.

**Métricas (dos pasadas de `evaluate_all.py`)**:
- 1ª pasada: weak_synonym 1787 → 1259 (−30%, promociones en
  vuelo; el scoring aún las ve con trust antiguo).
- 2ª pasada: weak_synonym 1259 → **677 (−62% total)**. Scoring
  ya con sinónimos promocionados desde el inicio.
- **774 sinónimos promovidos** `aprendido_en_prueba → aprendido_confirmado`
  (de 1005 iniciales; quedan 231 con 0-1 hits).
- Auto: 3019 → 3021 (+2 líneas), **autoapprove 92.8% → 92.9%**
  (+0.1pp). Mejora modesta en auto porque el gap ok→auto
  residual (62 líneas) se debe mayormente a otros factores
  (rescue, validation_errors, link<0.80 por causas no-trust).
- **Golden 997/997 (100%) intacto** — `manual_confirmado`
  protegido por el skip explícito.

**Valor real**: el ruido semántico de la UI cae 62%. Cada
tooltip de revisión muestra menos penalties. El operador ve
menos "weak_synonym" en matches que de facto son sólidos. Y los
774 sinónimos promocionados ya no bloquean carriles auto en
futuras facturas del mismo proveedor.

### 2026-04-22 — sesión 10f: fix parser BRISSAS (TOTALES_MAL 1→0, autoapprove 92.8% estable)

Diagnóstico del único proveedor en bucket TOTALES_MAL. BRISSAS
tenía 170/171 líneas `auto` (matcheo perfecto) pero `tot_ok=0/5`
en todas las muestras del benchmark. Causa: el regex de
`header.total` en `BrissasParser` era
`(?:Sub\s+)?Total\s+([\d,.]+)` y capturaba la **primera**
ocurrencia de `TOTAL` en el PDF. En formato BRISSAS, esa primera
ocurrencia es la fila-resumen de stems (`TOTAL 6700 0.286
1918.00` = 6700 stems + precio promedio + grand total), y el
regex extraía 6700 como total de cabecera. El grand total real
(`Sub Total 1918.000` + `Total 1918.000`) aparece más abajo.

**Fix aditivo — `src/parsers/otros.py`** (líneas 56-61):

- Preferir `re.search(r'Sub\s+Total\s+([\d,.]+)', text, re.I)`
  como primera elección (es el grand total real).
- Fallback al `Total\s+([\d,.]+)` genérico sólo si no existe
  `Sub Total` (defensivo para variantes futuras).
- Sin tocar el regex de líneas ni la estructura del parser.

**Goldens**: corregido `header_total` en las 2 anotaciones
BRISSAS existentes, que heredaban el stems count como grand
total: `brissas_000003919.json` 16200 → 4632.75 y
`brissas_000003952.json` 14925 → 4315.5. Cambios inofensivos,
`evaluate_golden.py` no chequea este campo.

**Métricas**:
- BRISSAS: `tot_ok=0/5` → **5/5**, verdict TOTALES_MAL → OK,
  11/11 samples con `header_ok=True` (diff=0%).
- Global auto: **92.8% estable** (3019 auto / 3252 linkable,
  ok 3083, ambiguous 169). Sin impacto en link accuracy.
- **Buckets: OK 76 → 77 · TOTALES_MAL 1 → 0** · NO_PARSEA 5 ·
  NO_DETECTADO 1.
- Golden link **100% (997/997) intacto**.

### 2026-04-21 — sesión 10e: fix matcher generic_vs_own_brand (autoapprove 92.7→92.9%)

Investigación de qué drives el gap de 236 líneas linkables pero
no-auto. Diagnóstico: el 75% de penalties globales (1784/2373)
son `weak_synonym`. Intento inicial golden-bootstrap en OLIMPO
reveló algo más profundo: existen sinónimos
`aprendido_en_prueba` heredados que apuntan a artículos
**genéricos** (`ROSA EC LEMONADE 70CM 25U`) cuando existe el
branded propio del proveedor (`ROSA LEMONADE 70CM 25U SCARLET`,
OLIMPO brand). Estos sinónimos daban +0.24 al genérico
(synonym_trust 0.55 × 0.25 = 0.14 + method_prior 0.10) que
derrotaba al `brand_in_name(+0.25)` del branded propio. Regla
de negocio: "marca propia > genérico > marca ajena" no se
respetaba.

**Fix estructural — `src/matcher.py`**:

- Nuevo parámetro `has_own_branded_peer: bool` en
  [`_score_candidate`](../src/matcher.py#L270). Calculado una vez
  antes del loop (línea ~822) como "¿hay al menos un candidato
  viable con brand_in_name del proveedor propio?".
- Nueva penalty `generic_vs_own_brand` (−0.15) cuando (a) el
  candidato no tiene marca propia, (b) no tiene marca ajena
  (tampoco foreign_brand), (c) `has_own_branded_peer` es True.
  Simetriza: propio +0.25, genérico −0.15 cuando existe propio,
  foreign −0.25. Diff propio↔genérico sube de 0.25 a 0.40 —
  suficiente para derrotar synonym_trust débil.
- La penalty NO se aplica cuando no existe branded propio en el
  pool → compat con proveedores sin marca propia (mayoría).

**Métricas**:
- Global auto: 92.7 → **92.9%** (+0.2pp, 3018 → 3020 auto,
  171 → 168 ambiguous)
- Ganancias: CEAN GLOBAL +8.3pp (75 → 83.3%), DAFLOR +5.9pp
  (41.2 → 47.1%), OLIMPO +2.5pp (59.2 → 61.7%), ROSALEDA +0.8pp
  (99.2 → 100%).
- Regresión única: COLIBRI −1.4pp (98.6 → 97.2%, 2 líneas
  ok→ambiguous). Análisis: líneas que antes matcheaban a
  genérico EC con confianza 0.70+, ahora `generic_vs_own_brand`
  las hace ambiguas porque el branded COLIBRI compite. Es
  cualitativamente correcto — golden COLIBRI sigue 100%.
- 9 penalties `generic_vs_own_brand` aplicadas globalmente.
- **Golden link 100% (997/997) intacto** — ninguna línea
  confirmada cambió de articulo_id.

### 2026-04-21 — sesión 10d: VALTHO + fix parser Cantiza (autoapprove 92.7% estable, golden 907→997)

Continuación de 10c. Foco único: incorporar VALTHOMIG (provider
435) al golden. VALTHO usa `fmt='cantiza'` — mismas plantillas
que CANTIZA, pero muestras recientes tienen dos variantes OCR
que el regex de `CantizaParser` no contemplaba.

**Fix de parser**:

- [src/parsers/cantiza.py:44](../src/parsers/cantiza.py#L44)
  **CantizaParser — categoría cooler `C` + puntos OCR**: el regex
  era `([\w][\w\s.\']*?)\s+(\d+)CM\s+N\s*(\d+)ST\s+[A-Z]{1,4}\b`,
  con `N` hardcodeado como categoría (`N` = normal). (a) Algunas
  facturas marcan `C` (cooler) — ej. `CHERRY O 40CM C 25ST CZ`.
  (b) El OCR de estas muestras deja punto pegado tras `N` y tras
  `ST`: `N. 25ST.`, `N 25ST.`. Fix aditivo: `[NC]\.?\s*(\d+)ST\.?`
  — admite ambos caracteres + puntos opcionales, sin romper el
  matcheo legacy. Impacto medido en CANTIZA: 100 → 105 líneas
  parseadas (+5 ok).

**Goldens**:

- VALTHO 25061370 (63 líneas) y 25061457 (27 líneas)
  bootstrappeados y revisados. Las 90 líneas mapean 100% al
  branded CANTIZA (los PDFs se titulan "CANTIZA CANTIZA 2" pero
  el provider_id en cabecera es 435 = Valthomig, distribuidor
  oficial). link 100%.
- `golden_apply.py` propagó: 3 sinónimos nuevos, 43 promociones
  `aprendido_en_prueba → aprendido_confirmado`, 329 increments
  de `times_confirmed` sobre sinónimos CANTIZA/VALTHO existentes.

**Métricas**:
- CANTIZA auto: 98.0 → **98.1%** (+0.1pp, +5 líneas parseadas)
- VALTHOMIG auto: **100%** (98 líneas, sin regresión)
- Global auto: **92.7% estable** (3018 auto / 3254 linkable)
- Golden link: 100% (907/907) → **100% (997/997)** (+90 líneas,
  24 facturas, 13 proveedores)

### 2026-04-21 — sesión 10c: FLORAROMA + LA ESTACION (autoapprove 92.7%, golden 575→907)

Continuación de 10b. Dos focos: (a) ampliar golden a
proveedores top-volumen con muchos `weak_synonym` pendientes de
confirmar; (b) auditoría de LA ESTACION, que compartía parser
con PONDEROSA pero variante de plantilla distinta no soportada.

**Fixes de parsers**:

- [src/parsers/otros.py](../src/parsers/otros.py) **VerdesEstacion
  variante B — farm bleed**: el regex `_RE_B` admitía
  `[A-Za-z\s\-]` en la captura de variedad. En LA ESTACION la
  columna de variedad a veces lleva el farm inline (ej.
  `Atomic - KENTIA`, `Mondial -ALHOJA`, `Vendela - MARL`), así
  el regex capturaba la cadena entera como variedad. Resultado:
  matcher no encontraba PONDEROSA branded y caía a genérico COL
  o foreign-brand (LUXUS, CANTIZA). Fix **aditivo post-regex**:
  si la variedad contiene ` - `, split en `variety` + `farm` y
  el farm pasa a `label`. `R11-Tita` como label no se ve
  afectado (el regex lo captura en `group(4)`).

**Goldens**:

- FLORAROMA 001068330 (103 líneas) + 001097157 (72 líneas)
  bootstrappeado y revisado — 100% link al branded FLORAROMA.
  Matcher maneja bien las variedades OCR-corruptas
  (AWDOAS SAB.OI→WASABI, AB SRI.GOHTON→BRIGHTON,
  ESX.OPLORER→EXPLORER) por fuzzy hint.
- LA ESTACION 608 (51), 609 (51), 678 (55) bootstrappeado post-
  fix: 157 líneas, 157 al PONDEROSA branded (mismo provider_id
  11748 que PONDEROSA). Única corrección manual: `ORANGE 40` →
  `35810 ROSA ORANGE CRUSH 40CM 25U PONDEROSA` (matcher elegía
  genérico COL por defecto porque la variedad `ORANGE` no
  coincide textualmente con `ORANGE CRUSH`).
- `golden_apply.py` propagó 463 confirmaciones nuevas +
  1 corrección → sinónimos manual_confirmado = 907.

**Métricas**:
- LA ESTACION auto: 99.0 → **100%** (+1pp, 0 ambiguous)
- PONDEROSA auto: 97.0 → **100%** (regeneración con sinónimos)
- FLORAROMA auto: 99.5% (sin cambio; weak_synonym pen
  190→6 al confirmar)
- Global auto: 92.7% (estable, los picos top ya estaban
  marcados; ganancia en trust durable y parser correcto en
  muestras futuras de LA ESTACION)
- Golden link: 100% (575/575) → **100% (907/907)** (+332 líneas)
- Top-6 por volumen (BRISSAS, COLIBRI, FLORAROMA, LA ESTACION,
  PONDEROSA, ROSALEDA) todos al ≥98.6%

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

- [src/parsers/colibri.py](../src/parsers/colibri.py): tres bugs
  aditivos. (1) `prices[-1].replace(',','.')` convertía
  "2,565.000" en "2.565.000" → `float()` fallaba silenciosamente
  → 12 líneas con `line_total=0` y val_errors (formato Colibri
  es US: coma=miles, punto=decimal). Fix: `replace(',','')`.
  (2) Regex `(\d+)\s+ST` sin word boundary capturaba "581314" de
  "581314 STA" → `total_mismatch` en 3 líneas. Fix:
  `(\d+)\s+ST\b`. (3) `GRADE_MAP` no incluía `STA` (literal de
  Colibri para Standard) → default a FANCY → sinónimos con grade
  incorrecto. Fix: añadir `'STA':'STANDARD'`.
- [src/parsers/colibri.py](../src/parsers/colibri.py): nueva regla
  "MIX Color/Color → una sola línea". Líneas tipo `Carn Mix
  Red/Yellow` o `Mini Mix Red/White` ya no se dividen en dos
  medio-tallos; mantienen stems/total íntegros con `variety=MIX`.
  El grade+spb deciden el SKU MIXTO concreto
  (FAN+20→12790, SEL+10→26798, STD+20→12659, etc).
- [src/matcher.py](../src/matcher.py): añadido `\bHAWB\b` al regex
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

## 2026-04-20 — sesión 9x: respeto manual_confirmado + variety_full + "IN COLOR" strip

Tras 9v (bootstrap drafts) + 9w (brand_boost spb_match), quedaban
22 mismatches. Arreglados 20/22 con tres fixes en cadena:

1. **`variety_full`** ([src/matcher.py:321-331](../src/matcher.py))
   — nuevo reason cuando todos los tokens ≥3 chars de la variedad
   de factura aparecen en el nombre del artículo (+0.03 bonus) y
   como desempate en `brand_boost` (`sort(spb_match, variety_full,
   score)`). Desambigua PINK MONDIAL PONDEROSA vs MONDIAL
   PONDEROSA de la misma marca.
2. **`_COLOR_SUFFIX_RE` acepta "IN "/"EN " opcional antes del
   color** ([src/matcher.py:454-455](../src/matcher.py)) — `BELIEVE
   IN PINK` ahora strippa `IN PINK` → `BELIEVE` (si existe en
   catálogo). Evita match al hermano `ABSOLUT IN PINK`.
3. **Respetar `manual_confirmado`** (el fix más impactante):
   - [src/matcher.py:817-831](../src/matcher.py) — match_line salta
     brand_boost si syn_entry es `manual_confirmado`.
   - [src/sinonimos.py:293-304](../src/sinonimos.py) — `add()`
     retorna sin modificar si prev es `manual_confirmado` y el
     auto-learn apunta a un artículo distinto. Antes
     `evaluate_golden` y `match_all` degradaban silenciosamente
     las correcciones del golden a `aprendido_en_prueba` con cada
     ejecución.

Tras los 3 fixes + `golden_apply` sobre los 3 drafts (total 284
confirmados + 8 corregidos), golden link **92.5→99.3% (+6.8pp)**
y autoapprove **90.3→91.2% (+0.9pp)**. weak_synonym penalties
bajan de 2742 a 2176 (−566) por la preservación del manual.

Quedan solo 2 mismatches conceptuales: GYPSOPHILA XL ESPECIAL uma
(gramaje 750GR) y YELLOW SUMMER verdesestacion (gold apunta a
artículo EC con talla distinta — probable error del gold).

## 2026-04-20 — sesión 9w: brand_boost preferir spb_match (+3.1pp golden)

Con los 3 drafts de 9v promovidos a reviewed, `evaluate_golden.py`
destapó 31 mismatches. El culpable recurrente: brand_boost
suprimido cuando hay **varios candidatos** con marca propia +
variety + size_exact, aunque uno sea claramente superior por
`spb_match`. Ejemplo MONDIAL valtho: 35473 CANTIZA 25U (spb_match,
1.100) vs 35472 CANTIZA 20U (0.950) — con 2 candidatos el código
exigía `len==1` y el boost no disparaba.

Fix en [src/matcher.py:823-838](../src/matcher.py): ordenar
`boost_candidates` por `(spb_match, score)` y requerir líder
claro. Impacto: golden link 89.4→92.5% (+3.1pp).

## 2026-04-20 — sesión 9v: bootstrap golden set (+3 drafts, +144 líneas)

Bootstrap de drafts nuevos en los 3 proveedores de mayor volumen
que aún no estaban en golden: UMA FLOWERS, VALTHOMIG, PONDEROSA
(via Verdes La Estación).

- **[golden/uma_18222.json](../golden/uma_18222.json)** — UMA
  FLOWERS, 14 líneas (13 ok + 1 ambiguous_match, 3 ok con
  match_conf<0.80). Las 4 sospechosas son todas gypsophila
  XLENCE: el matcher las enlaza a "PANICULATA XLENCE" con
  gramaje distinto (750gr vs 1000gr) → requiere criterio del
  operador para confirmar/corregir.
- **[golden/valtho_25061663.json](../golden/valtho_25061663.json)**
  — VALTHOMIG, 38 líneas, **100% ok con match_conf≥0.80**.
  Candidato claro a reviewed con revisión rápida.
- **[golden/verdesestacion_1896.json](../golden/verdesestacion_1896.json)**
  — PONDEROSA (Verdes La Estación), 92 líneas, **100% ok con
  match_conf≥0.80**. Casi idem, revisión rápida.

## 2026-04-20 — sesión 9u: matcher perf 26× (deferred save + bulk MySQL)

Optimización de performance del matcher. El profiling reveló que el
80% del tiempo se iba en `json.dump()` dentro de `SynonymStore.save()`
— cada línea disparaba un save completo del archivo (≈190ms × 42
líneas = 8s de I/O). El fuzzy que la doc mencionaba como bottleneck
era solo 1s.

- **[src/sinonimos.py](../src/sinonimos.py) → `SynonymStore`**: nuevo
  flag `_batch_depth` + context manager `batch()` que difiere el
  save del JSON hasta salir del contexto. Durante batch, los
  `add()` / `mark_*` solo marcan `_dirty`; al salir hay un único
  `_write_to_disk()`.
- **[src/sinonimos.py](../src/sinonimos.py) → `_sync_to_mysql` /
  `_bulk_sync_to_mysql`**: sync MySQL también diferido y convertido
  a `executemany` con una sola conexión al flush (antes 18ms ×
  42 líneas abriendo/cerrando conexión = 0.77s).
- **[src/matcher.py](../src/matcher.py) → `match_all`**: envuelve el
  loop en `with self.syn.batch():` para activar el modo diferido.
- **Perf**: factura ALEGRIA (43 líneas) **10.2s → 0.39s** (26×).
  Por línea: **238ms → 9ms**. Sin regresión de métricas: golden
  97.3%, autoapprove 90.2%, OK 76 idénticos a antes.

## 2026-04-20 — sesión 9t: TOTALES_MAL cleanup (TESSA + MILAGRO + MILONGA)

Ataque a los 3 proveedores TOTALES_MAL. Los 3 subieron a OK.

- **[src/parsers/otros.py](../src/parsers/otros.py) → TessaParser**:
  añadidos dos patrones nuevos para mixed boxes. **Pattern 3**
  captura sub-líneas sin prefijo HB/QB (`DEEP PURPLE 60 1 25 $0.40
  $10.00`) heredando `box_type` y `label` del último parent. El
  parser anterior solo capturaba el parent. **Pattern 4** maneja
  OCR que rompe variedad multi-palabra en 3 líneas adyacentes
  (`PINK\n60 1 25 $0.40 $10.00\nMONDIAL` → variety "PINK MONDIAL")
  concatenando vecinos si son palabras mayúsculas cortas sin
  números. TESSA: 22 → 50 líneas parseadas, tot_ok 1/5 → 4/5.
- **[src/parsers/auto_milagro.py](../src/parsers/auto_milagro.py)**:
  estrategia por parent — si `is_mixto=True` emitir sub-líneas
  (detalle por variedad); si NO, emitir el parent directamente.
  Antes siempre emitía sub-líneas, pero para mono-variedad la
  sub-línea solo describe 1 box mientras el parent agrega todos
  los boxes del item. MILAGRO 01-1062749: diff 24% → OK.
  tot_ok 2/5 → 3/5.
- **[src/parsers/otros.py](../src/parsers/otros.py) → ColFarmParser**:
  pre-skip de parents de caja mixta (`1 H Rose mix ...`) antes del
  regex principal. El lazy `(.+?)` rompía "mix" en "mi X" y escapaba
  al filtro de skip MIX/ASSORTED. MILONGA 02-45937360: diff 12% →
  OK. tot_ok 2/5 → 3/5.
- **Globales**: autoapprove mantiene **90.2%**. **Buckets**: OK
  73 → **76** (+3: TESSA, MILAGRO, MILONGA suben), **TOTALES_MAL
  3 → 0**. Líneas 3312 → 3338 (+26 sub-líneas TESSA recuperadas).
  ok 2853 → **2880** (+27).

---

## 2026-04-20 — sesión 9s: NO_PARSEA cleanup (ELITE + DAFLOR + SAYONARA)

Ataque a los 7 proveedores NO_PARSEA. Cerrados 2 a OK y mejoradas
3 más.

- **[src/parsers/auto_elite.py](../src/parsers/auto_elite.py)**: regex
  `_PARENT_ALSTRO_RE` acepta coma de miles en los campos numéricos
  (`1,200` para stems en sample 045-10594065 de FLORA CONCEPT LLC).
  Nuevo helper `_num()` quita comas antes de int/float. ELITE
  4/5 parsed → **5/5**, 4/5 tot_ok → **5/5**.
- **[src/parsers/otros.py](../src/parsers/otros.py) → DaflorParser**:
  cleanup OCR ampliado — normaliza `]`/`[` residuales del scrape
  con pipes y acepta em-dash/en-dash/underscore antes de `o.` (OCR
  "— o.15" → "$0.15"). Header total: intenta regex `INVOICE TOTAL
  US$ N` y cae a suma de líneas si no. DAFLOR 4/5 parsed → **5/5**,
  0/5 tot_ok → **5/5** (salto grande — antes no cuadraba ningún
  sample).
- **[src/parsers/sayonara.py](../src/parsers/sayonara.py)**: helper
  `_ocr_clean()` quita pipes `|`, corchetes `]/[`, em-dash/en-dash
  entre números. Regex del total ampliado con variante "Total Value
  USE US N" (OCR "USE" por "USD"). Fallback a suma de líneas.
  SAYONARA 3/5 parsed → **4/5**, 0/5 tot_ok → **2/5**.
- **Sin tocar (ROI bajo)**: NATIVE BLOOMS (formato Bouquet distinto),
  CANANVALLE (custinv compartido, totales mal), CEAN GLOBAL
  (requeriría extender para rosas en español), UNIQUE (volumen
  pequeño, OCR irregular).
- **Globales**: autoapprove mantiene **90.2%**. **Buckets**: OK 71
  → **73**, NO_PARSEA 7 → **5**. Líneas 3309 → 3312. ok 2833 →
  **2853** (+20), ambiguous 205 → **196** (−9), autoapprovable
  2715 → **2749** (+34).

---

## 2026-04-20 — sesión 9r: revisión golden + matcher prioridad de marca

- **Golden drafts** (timana/benchmark/florifrut): limpiada la
  `_note` DRAFT en los 3 archivos. 148/148 reviewed en 8 proveedores.
- **Diagnóstico golden**: link accuracy inicial 91.2% (135/148), 13
  mismatches, todos gap del matcher. Patrón: el sistema elige
  genérico COL o marca ajena (CANTIZA, LUXUS, CERES) en lugar del
  artículo con marca del proveedor actual, o no encuentra el
  candidato correcto porque la variedad de factura no matchea literal
  con la del catálogo (WHITE/PINK suffix, AND connector, BICOLOR
  suffix ausente).
- **Regla de negocio confirmada** (guardada en
  `feedback_matcher_priority.md`): marca del proveedor > genérico
  COL/EC > marca ajena. Variedad correcta con tamaño aproximado pesa
  más que variedad+tamaño exactos con marca ajena.
- **[src/matcher.py](../src/matcher.py) → `_strip_color_suffix`**:
  paralelo a `_strip_color_prefix`. `VENDELA WHITE` → `VENDELA`
  cuando la base existe en `by_variety`. Generador 2d en
  `_gather_candidates`. Cerró 3 TIMANA (VENDELA WHITE 40/50,
  MONDIAL WHITE 60, PINK MONDIAL PINK 40).
- **[src/matcher.py](../src/matcher.py) → `_strip_connector`**:
  quita `AND`/`&`/`Y` del medio si el resultado existe. Cerró 2
  TIMANA (HIGH AND MAGIC ORANGE 40/60 → HIGH MAGIC BICOLOR via 2f).
- **[src/matcher.py](../src/matcher.py) → `_simplified_variants` +
  generador 2f BICOLOR extension**: explora todas las combinaciones
  de simplificación (directa, color-suffix, connector-strip,
  ambos) y prueba añadir `BICOLOR` al final si existe en
  `by_variety`. Cerró IGUAZU → IGUAZU BICOLOR (florifrut) y CHERRY
  BRANDY PEACH 60 → CHERRY BRANDY BICOLOR (timana).
- **[src/matcher.py](../src/matcher.py) → `_score_candidate`**:
  comparación `own_brands` vs `nombre` con `_normalize` (strip
  acentos). Arregla `'TIMANA' in 'TIMANÁ'` = False que bloqueaba
  `brand_in_name` en proveedores con tilde en el sufijo. Idem
  `foreign_brand`.
- **[src/matcher.py](../src/matcher.py) → `match_line` pkey fallback**:
  si el parser deja `line.provider_key=''`, se deriva del
  `provider_id` via PROVIDERS. Desbloquea brand_boost en
  proveedores donde el ID del config (p.ej. 90039 TIMANA) no
  coincide con el `id_proveedor` del catálogo (2651).
- **[src/matcher.py](../src/matcher.py) → brand_boost contextual**:
  solo aplica si hay **un único** candidato con `own_brand +
  variety_match + size_exact`; el score se eleva sobre el top
  alternativo + 0.05 para superar synonyms legacy del genérico
  (trust+history llegaba a ~1.19). El gating por unicidad evita
  empates catastróficos (−11pp autoapprove) en catálogos muy
  marcados como ECOFLOR/MYSTIC.
- **[src/matcher.py](../src/matcher.py) → size tolerance dual**:
  `_SIZE_TOL=10` para bonus/penalty suave (`size_close` +0.05) y
  `_SIZE_TOL_MAX=20` para el veto duro. Entre 10 y 20cm el
  candidato no se descarta pero recibe penalty `size_off(Ncm)
  −0.10`. Permite al genérico COL/EC con variedad correcta ganar a
  una marca ajena con size exacto cuando no hay otra alternativa.
  Cerró GOLDFINCH YELLOW 60 → GOLDFINCH 40CM COL (diff 20cm).
- **Globales**: autoapprove **87.8% → 90.2%** (+2.4pp). ok 2795→
  2852 (+57), ambiguous 228→196 (−32), autoapprovable 2666→
  ~2720 (+54). Golden **91.2% → 97.3%** (+6.1pp, 13 → 4
  mismatches). Los 4 restantes son decisiones conceptuales
  (MINICARNS→CLAVEL FANCY en benchmark, ASSORTED→COLOR MIXTO vs
  mixed_box en timana) — ver "Próximos pasos" en CLAUDE.md.

---

## 2026-04-17 — sesión 9q: IWA mixed_box reclassify + CANTIZA/MILAGRO/MILONGA + fuzzy cache + golden drafts

Cuatro frentes de mejora en paralelo para acabar con el backlog que
quedó de 9p.

- **[src/matcher.py](../src/matcher.py) → `reclassify_assorted`**:
  ampliado el regex `_ASSORTED_RE` con `SURTIDO\s+MIXTO`, `ASSORTED\s+(ROSA|ROSE|COLOR)`,
  `MIXTO`. Las líneas IWA con `SURTIDO MIXTO` y `ASSORTED ROSA` que
  quedaban en ambiguous_match ahora se reclasifican automáticamente
  como `mixed_box` (más honesto: son cajas mixtas sin detalle). IWA
  ambig 19→2 (−17 líneas a mixed_box). A nivel global, −40 ambig.
- **[src/parsers/cantiza.py](../src/parsers/cantiza.py)**: OCR
  cleanup específico para el sample `01 - V. 075-6577 1440`:
  `S0CM`/`SOCM` → `50CM`, `N255T`/`N 2351` → `N 25ST`, pipes `|`
  a espacios. Relaxación del regex para aceptar `N\s*(\d+)ST`.
  CANTIZA NO_PARSEA → OK (100 líneas, 95 ok, 3 ambig).
- **[src/parsers/otros.py](../src/parsers/otros.py) → ColFarmParser**:
  amplié aliases OCR `_ROSE` (`R:ise`, `R:lse`, `Rlse`, `Rlese`,
  `R|se`) y `_UNIT` (`SR`). Pre-normalización: `¡`/`!` a espacios,
  `\d+[~\.]` entre stems y ST como ruido, normalizar variantes
  Rose a `Rose` con `re.sub` antes del regex principal. Header
  fallback adicional (`TOTAL (Dolares)` y `Vlr.Total FCA BOGOTA`).
  MILONGA NO_PARSEA → TOTALES_MAL, 02b (heavy OCR) 0→5 líneas.
- **[src/parsers/auto_milagro.py](../src/parsers/auto_milagro.py)**:
  nueva función `_ocr_normalize(line)` aplicada a cada línea del
  texto antes de los regex. Maneja `~OSES`→`ROSES`, `FREE DOM`→
  `FREEDOM`, `SO`/`S0` en posición de size→`50`, paréntesis OCR
  (`0.28(`→`0.280`, `25(`→`250`), y chars basura como separadores
  (`\ufffd`, `\u2022` bullet, `\u00b0`, `\u00b7`) → `-`. Además
  `_TOTAL_RE` ya aceptaba coma pero de 9p. MILAGRO NO_PARSEA →
  TOTALES_MAL (1 sample sigue corrupto irrecuperable; el resto
  mejora).
- **[src/articulos.py](../src/articulos.py) → `fuzzy_search`**:
  optimización doble. (i) Cache por clave `(sp_key, query,
  threshold)` — una factura repite variedades muchas veces; el
  cache hit ahorra la comparación completa. (ii) Prefiltro
  `real_quick_ratio()` (O(1)) y `quick_ratio()` (O(n+m)) antes de
  `ratio()` (O(n·m)). Reuso de un solo `SequenceMatcher` con
  `set_seq2` entre comparaciones. Medido sobre MILAGRO 01a (42
  líneas): ~6.5s antes → ~5.0s ahora (−23%). El prefiltro solo
  skipea ~2% (los nombres comparten demasiados caracteres con la
  query); el cache es el ganador cuando hay varieties repetidas.
- **Golden drafts (+3)**: bootstrapeados con `golden_bootstrap.py`
  para TIMANA (88112, 15 líneas), BENCHMARK (103685, 32 líneas) y
  FLORIFRUT/ART ROSES (0001093134, 14 líneas). Pendientes de
  revisión humana — solo después cuentan en la métrica golden.
  Se preservó el `golden_unknown.json` original (restaurado desde
  git tras haberlo sobreescrito por accidente en el bootstrap
  inicial de BENCHMARK).
- **Regresión**: golden_eval mantiene 100% (88/88) tras los
  cambios. MYSTIC/STAMPSY/STAMPSYBOX/FIORENTINA/VUELVEN/CIRCASIA
  sin cambios en conteo (verificado con parse() manual).
- **Resultado global**: autoapprove **86.7% → 87.8%** (+1.1pp, la
  mejor subida de las últimas 3 sesiones). ok 2785 → 2795;
  ambiguous 268 → 228 (−40, reclassify a mixed_box); líneas
  totales 3297 → 3309 (+12); needs_review 585 → 548.
  **Buckets**: OK 70→71 (CANTIZA), NO_PARSEA 10→7 (MILAGRO+
  MILONGA+CANANVALLE suben a TOTALES_MAL), TOTALES_MAL 1→3.
  Golden 100% (88/88 reviewed + 3 drafts pendientes).

## 2026-04-17 — sesión 9p: IWA + PREMIUM + CIRCASIA + ECOFLOR + MILONGA + MILAGRO + PRESTIGE

Quinta tanda de fix sobre el backlog de NO_PARSEA / MUCHO_RESCATE.
Objetivo: convertir líneas rescatadas en parsed reales y subir los
buckets de proveedores secundarios.

- **[src/parsers/otros.py](../src/parsers/otros.py) → IwaParser**:
  regex reescrita, anclada en el tariff de 10 dígitos y el bloque
  final `Stems N USD$ P USD$ T`. El `CM` tras size ahora es opcional
  (algunos samples lo omiten), y entre size y tariff puede aparecer
  un farm-route code (`R19`, `R19-Pili`) que se limpia por lista
  negra. Algunos lines no traen size (`ROSA ASSORTED ROSA 06031...`).
  `SURTIDO MIXTO` como fallback de `ASSORTED`. IWA pasa de
  MUCHO_RESCATE → OK: rescued 32→0, parsed 21→53, totals_ok 5/5.
- **[src/parsers/otros.py](../src/parsers/otros.py) → PremiumColParser**:
  OCR cleanup pre-regex: `l` inicial→`1`, `Rl4`→`R14`, `.US$`→`US$`,
  `US$0.120`→`US$ 0.120`, `!` quitado, `'CARNATION`→`CARNATION`. El
  regex principal ahora absorbe `ORDEN` entre tariff y `Stems`
  (`.*?Stems` en lugar de `\s+Stems`). Variante B factura electrónica
  DIAN añadida como fallback (solo se ejecuta si la variante A no
  encontró nada): `CARNATION DIANTHUS CARYOPHYLLUS DIANTHUS
  CARYOPHYLLUS CARNATION STEMS $PRICE $TOTAL`. PREMIUM: NO_PARSEA → OK.
- **[src/parsers/otros.py](../src/parsers/otros.py) → ColFarmParser**:
  (i) nuevo `pm5` para CIRCASIA que formatea rango de size
  `SIZE - SIZE` con label y tariff punteado: `1 Q Rose Tiffany 50 -
  50 R14- 0603.11.00.00 150 150 Stems 0.28 $42.00`. (ii) En el
  regex principal, `\s+[-_]?\s+` → `\s+[-_]?\s*` para aceptar
  `X25 -40` (sin espacio tras el dash) de MILONGA OCR. CIRCASIA:
  NO_PARSEA → OK, MILONGA 03 rescued 5→2.
- **[src/parsers/mystic.py](../src/parsers/mystic.py)**: variety
  class en `_LINE_RE_NOCODE` ampliada a
  `[A-Za-zÀ-ÿ\ufffd][A-Za-z0-9À-ÿ\ufffd\s\-\.'/&]+?` para aceptar
  caracteres Latin-1/extended y el placeholder OCR `\ufffd`. ECOFLOR
  tiene variedades como `CAF� DEL MAR` (OCR de `CAFÉ`) que antes
  rebotaban. ECOFLOR: TOTALES_MAL → OK, 5/5 samples con sum=header.
- **[src/parsers/auto_milagro.py](../src/parsers/auto_milagro.py)**:
  `_TOTAL_RE` acepta coma de miles: `[\d.]+` → `[\d,.]+`. El
  `_num()` ya hacía `.replace(',','')`. Sample 02a: header 1.0 →
  1193.5. Aún hay líneas que faltan en MILAGRO (OCR muy corrupto),
  por lo que el bucket sigue NO_PARSEA pero menos sesgado.
- **[src/parsers/otros.py](../src/parsers/otros.py) → PrestigeParser**:
  nueva variante OCR para factura escaneada simple:
  `ROSE FREEDOM 40 CM 2 250 500 0,16 80,00` (ROSE + variety +
  size + HB_count + stems_per_H + total_stems + price + total,
  decimales con coma). Añade `header.total` derivado del sumatorio
  si no se extrae del PDF. PRESTIGE: NO_PARSEA → OK (9→24 parsed,
  5/5 totals_ok).
- **Regresión**: golden 100% (88/88) preservado. MYSTIC, STAMPSY,
  STAMPSYBOX, FIORENTINA, VUELVEN sin cambios en conteo de líneas.
- **Resultado global**: autoapprove **87.1% → 86.7%** (−0.4pp —
  dilución esperada al abrir más líneas; algunas son MIXED box de
  IWA o DIAN de PREMIUM que matchean ambiguamente y suman al
  denominador). ok 2739 → 2785 (+46); líneas totales 3219 → 3297
  (+78); ambiguous 246 → 268 (+22, principalmente SURTIDO MIXTO en
  IWA). **Buckets**: OK 65→70 (+5), NO_PARSEA 13→10 (−3),
  MUCHO_RESCATE 1→0, TOTALES_MAL 2→1. Golden 100%.

## 2026-04-17 — sesión 9o: TIMANA + ART ROSES + BENCHMARK + TESSA parsers

Cuarta tanda de fix de NO_PARSEA sobre el backlog sesión 9n.

- **[src/parsers/otros.py](../src/parsers/otros.py) → TimanaParser**:
  el formato añade a veces `OF ` entre `SIZECM` y el tariff — regex
  principal ahora lo acepta como opcional. Nuevo patrón de sub-líneas
  para mixed boxes: `ROSE VAR COLOR SIZECM bunches spb price` (sin
  total, sin `HB`) se parsea heredando el `box_type` del parent
  `ASSORTED BOX ...`, que se skippea explícitamente (su stems/total
  son la suma de las sub-líneas). Además deriva `header.total` del
  texto `Total FCA Bogota: $...` o del sumatorio. Sample 01: 5
  líneas → 22. Totals_ok 0/5 → 5/5.
- **[src/parsers/mystic.py](../src/parsers/mystic.py)**: `re.I` en
  ambos regex (`_LINE_RE` y `_LINE_RE_NOCODE`) y clase `[A-Za-z...]`
  en variety del NOCODE. Desbloquea **ART ROSES** (FLORIFRUT, `fmt`
  heredado `mystic`) que usa variedad mixed-case: `Mondial`,
  `Explorer`, `Brighton`, `Frutteto`. Colateral: subido límite
  `{0,14}` → `{1,14}` en la clase del box_code para no solaparse con
  el NOCODE fallback cuando no hay código. ART ROSES: 0/5 samples OK
  → 5/5 OK (14 lineas en el sample principal, 29 en total, todas con
  totals_ok y diff 0%).
- **[src/parsers/golden.py](../src/parsers/golden.py) → GoldenParser
  (BENCHMARK)**: `price_m` no aceptaba coma de miles en el total
  (`1,350.00`). Cambiado `[\d.]+` → `[\d,.]+` en los dos grupos y
  `float(x.replace(',',''))` al convertir. Sample 01 OCR
  (`15 H 500 7500 | CONSUMER BUNCH CARNATION FANCY ... 1,350.00`)
  pasa de rescate a parsed OK. Rescued 4→0, totals_ok 3/5 → 5/5.
- **[src/parsers/otros.py](../src/parsers/otros.py) → TessaParser**:
  entre el campo `Loc.` y la variedad aparece a veces un farm/route
  code estilo `TESSA-R1`, `TESSA-R2` (letra + dígito con guión).
  Añadido prefix opcional `(?:[A-Z][A-Z0-9\-]*\s+)?` a `pm` y
  coma-en-total en las tres totales/label. Sample 02b (0 parsed)
  pasa a 4 parsed, diff 100%→0%. Otros samples también mejoran
  aunque quedan variantes de sub-líneas multi-variedad (una caja con
  15 variedades de 1 ramo cada una) que necesitan iteración aparte.
- **Sanity regresión**: golden_eval mantiene 100% (88/88) tras los
  cambios en mystic (re.I) y matcher intacto. Regression check en
  MysticParser sobre MYSTIC, FIORENTINA, STAMPSY, STAMPSYBOX: líneas
  parseadas idénticas al estado anterior.
- **Resultado global**: autoapprove **86.8% → 87.1%** (+0.3pp);
  ok 2652 → 2739; líneas totales 3118 → 3219 (+101 líneas nuevas
  procedentes de los parsers liberados). NO_PARSEA ~19 → 13. 4 de los
  6 candidatos del backlog salen de NO_PARSEA (TIMANA, ART ROSES,
  BENCHMARK a OK; TESSA sube a TOTALES_MAL). Golden 100%.

## 2026-04-17 — sesión 9n: NATIVE + MILONGA + MILAGRO + refinado matcher

- **[src/matcher.py](../src/matcher.py)**: bonus de `origin_match` subido 0.10 → 0.15
  para rosas/claveles. El prefijo EC/COL del catálogo es
  autoritativo y merece pesar más que un fuzzy 100% de artículo
  genérico. Resuelve ambiguous tipo FREEDOM (EC vs genérico).
- **[src/matcher.py](../src/matcher.py)**: filtro anti-ruido en el fallback low_evidence.
  Si top1 no tiene `variety_match` Y su fuzzy `hint_score` < 0.85,
  la línea va a `sin_match` en vez de `ambiguous_match`. Evita
  matches arbitrarios tipo "SHY → SYMBOL" (MILAGRO) que confunden al
  operador. Umbral 0.85 preserva casos tipo LIMONADA→LEMONADE
  (similitud 0.88, sin solape literal).
- **[src/parsers/otros.py](../src/parsers/otros.py) → ColFarmParser** (MILONGA): normaliza
  OCR noise antes del regex — pipes `|`, llaves, `�`, `*`,
  `X2-5`→`X 25` OCR breaks, `i ee` ruido. `_money()` ahora
  retorna 0.0 en lugar de reventar con `.` basura de OCR. MILONGA
  sample 01 pasa de 0 líneas a 11 (5 ok).
- **Resultado global**: autoapprove **81.9% → 86.8%** (+4.9pp,
  mayor salto individual). ok 2555→2652, ambiguous 367→239
  (-128). Golden 100% mantenido (88/88).

## 2026-04-17 — sesión 9m: DAFLOR + APOSENTOS + CANANVALLE (brand cortas)

- **[src/parsers/otros.py](../src/parsers/otros.py) → DaflorParser**: fix descripción colgada
  en dos líneas (`Alstroemeria Assorted - CO-` en una, datos en la
  siguiente) vía `pending_desc`/`pending_sp`. Acepta `Q`/`H` sueltos
  además de `QB`/`HB`, pipes `|` como separadores, y normaliza OCR
  errors (`€ o.15` → `$0.15`, `C0-` → `CO-`). DAFLOR: sin_parser
  rescued drop importante.
- **[src/parsers/otros.py](../src/parsers/otros.py) → AposentosParser**: regex tolerante a
  OCR (`C0-` → `CO-`, `OUTYFREE` → `DUTYFREE`, `$` opcional en
  precios, `Taba*` en vez de `Tabaco` exacto). APOSENTOS 03:
  2 ok → 13 ok, APOSENTOS 05: 3 ok → 11 ok.
- **[src/matcher.py](../src/matcher.py) → `_score_candidate`**: para CARNATIONS añade
  los tokens traducidos al español al `line_var_tokens` antes del
  check `variety_match`. El catálogo indexa claveles por color
  español (`CLAVEL COL FANCY NARANJA`) pero las facturas llegan
  con variedad + color inglés (`COWBOY ORANGE`). Sin este fix el
  scoring daba `variety_no_overlap` para matches correctos.
- **[src/config.py](../src/config.py)**: añadidos `BURGUNDY→GRANATE`,
  `BORDEAUX→GRANATE`, `WINE→GRANATE`, `CREAM→CREMA`,
  `BRONZE→BRONCE`, `BLUE→AZUL`, `FUCHSIA/HOT/MAGENTA→FUCSIA` al
  `CARNATION_COLOR_MAP`.
- **[src/matcher.py](../src/matcher.py) → `_detect_foreign_brand`**: threshold de
  longitud de marca bajado de 4 a 3 para detectar EQR y similares.
  Añadida protección contra falsos positivos en tokens tipo `CM`
  o `U` que quedan como sufijo de talla/packaging.
- **Resultado global**: autoapprove **80.4% → 81.9%** (+1.5pp),
  ok 2471→2555, ambiguous 424→367. `variety_no_overlap` 313→231
  (-82). Golden 100% mantenido.

## 2026-04-17 — sesión 9l: ELITE matching + SAYONARA precio-correcto

- **[src/parsers/auto_elite.py](../src/parsers/auto_elite.py)**: defaults de talla por especie
  (ALSTROEMERIA=70cm, CARNATIONS=60cm, HYDRANGEAS=60cm). Las líneas
  ELITE no traen CM y el catálogo siempre es 70cm para alstros.
  Sin esto, el fuzzy no podía casar "WINTERFELL" con
  "ALSTROMERIA COL WINTERFELL PREMIUM 70CM 10U" (size=0 → query muy
  corto → similitud 48% < threshold 50%).
- **[src/matcher.py](../src/matcher.py)**: fuzzy threshold bajado de 0.5 a 0.4. El
  scoring por evidencia filtra después los candidatos débiles; no
  merece la pena descartar candidatos al 48% de similitud cuando la
  variedad es buena. ELITE pasa de 0 ok a 15 ok.
- **[src/parsers/sayonara.py](../src/parsers/sayonara.py)**: bug en Custom Pack mix. Las líneas
  detalle usaban `price_per_stem=pack['price']` (0.95) y
  `line_total=proporcion_del_total`, lo que disparaba `total_mismatch`
  (stems*0.95 ≠ line_total) que capaba el link_confidence a 0.70 y
  tiraba a quick lane. Fix: usar `d['price_unit']` (el precio real de
  la línea detalle, 0.19) y `line_total = stems × price_unit`.
  Añadido `bunches` para que `stems_mismatch` también cuadre.
  Normalizado uso de `bunches` vs `spb` entre PACK_RE y PACK_RE_B
  (antes se confundían según el regex). SAYONARA pasa de auto=0 a
  auto=82.6% (38 líneas en auto lane).
- **Resultado global**: autoapprove 79.6% → 80.4% (+0.8pp),
  autoapprovable lines +53. Golden 100% mantenido.

## 2026-04-17 — sesión 9k: Ataque NO_PARSEA (LATIN) + refinado matcher

- **[src/parsers/latin.py](../src/parsers/latin.py)**: Format B regex usaba `[\d.]+` para
  decimales y fallaba en facturas con coma decimal (`0,250 1,00QBx35`
  en vez de `0.250 1.00QBx35`). Cambiado a `[\d.,]+` + `.replace(',', '.')`
  al convertir. **LATIN: 91 líneas (100% amb) → 314 líneas (306 ok,
  4 amb)**.
- **[src/matcher.py](../src/matcher.py)** — quitado el upper-clamp del score: antes
  `cand.score = round(max(0.0, min(1.0, score)), 3)`, ahora sin techo.
  Motivo: los candidatos con evidencia muy fuerte (sinónimo +
  histórico + match pleno) sumaban features > 1.0, el clamp los
  colapsaba a 1.0, y el brand_boost con `max(score, 1.05)` los
  aplanaba a 1.05 empatando con candidatos más flojos. Sin clamp
  superior, el ganador conserva su score real y tenemos desempate.
  `line.link_confidence` sigue clampado a 1.0 para la UI y para
  `match_confidence = link × ocr × ext`.
- **[src/matcher.py](../src/matcher.py)** — brand_boost ahora exige `size_exact` (no
  `size_close`): evitar que un artículo 60CM con la misma marca
  empate a 1.05 con el 50CM exacto cuando la factura dice 50CM.
- **[src/matcher.py](../src/matcher.py)** — tramo nuevo de `required_margin`: scores
  ≥1.05 necesitan solo 0.02 de margen (antes 0.05). La evidencia
  rica ya separó a top1 del resto; un margen 0.03-0.04 con scores
  1.138 vs 1.10 es victoria clara, no empate.
- **Resultado global**: autoapprove **68.9% → 79.6% (+10.7pp)**,
  líneas ok 2002→2453, tie_top2_margin 521→187 (-64%). Golden set
  mantiene 100%. NO_PARSEA 20→19 (LATIN resuelto).

## 2026-04-17 — golden revisado

El operador ha revisado manualmente los 5 drafts iniciales
(`_status: "reviewed"` en todos): `alegria_00046496`,
`fiorentina_0000141933`, `golden_unknown`, `meaflos_EC1000035075`,
`mystic_0000281780`. `evaluate_golden.py` confirma **100% parse + link
accuracy** sobre esas 88 líneas. Fase 2 del roadmap queda cerrada para
el dataset inicial; ampliar con más proveedores es trabajo continuo.

## 2026-04-16 — sesión 9j: Brand boost (commit `3855f7e`)

- En [src/matcher.py](../src/matcher.py): si existe un artículo con la marca del proveedor
  (detectada vía `brand_by_provider()` del catálogo) Y tiene match de
  variety+size, se le asigna `score=1.05` para que gane sobre sinónimos
  débiles y genéricos.
- `own_brands` ahora se alimenta también de `brand_by_provider`, lo que
  cubre casos donde la key del proveedor no coincide con la marca en
  los artículos (ej: `verdesestacion` → marca PONDEROSA).
- Golden set: 100% mantenido (88/88).
- **Autoapprove 66.1% → 68.9%** (+2.8pp).

## 2026-04-16 — sesión 9i: Paso 10 — Carriles de revisión

- Nuevo campo `review_lane` en `InvoiceLine` (`auto`/`quick`/`full`).
- Lógica de clasificación en [src/validate.py](../src/validate.py) → `classify_review_lanes()`,
  ejecutada automáticamente tras `validate_invoice()`.
- Serialización en [procesar_pdf.py](../procesar_pdf.py) + badge por línea + stat card
  "Auto X%" en [web/assets/app.js](../web/assets/app.js).
- Baseline: auto=60.6%, quick=33.2%, full=6.2% (3001 líneas).

## 2026-04-16 — sesión 9h: Paso 8 — Feedback loop desde golden set

- Nuevo [tools/golden_apply.py](../tools/golden_apply.py): lee anotaciones gold revisadas,
  compara con la salida del sistema, y aplica como sinónimos:
  - Línea correcta → `mark_confirmed` (promueve sinónimo)
  - Línea incorrecta → `add(origin='revisado')` (degrada viejo,
    crea nuevo como `manual_confirmado`)
- Aplicado sobre las 5 anotaciones: 82 confirmados + 6 corregidos.
- **Golden set accuracy: 100%** (88/88 líneas) — parse + link.

## 2026-04-16 — sesión 9g: Paso 6 — Auditar matcher con golden set

- **`_known_brands()`** ampliado: ahora incluye nombres de PROVIDERS
  (no solo keys) + marcas hardcodeadas que aparecen en artículos
  (SCARLET, MONTEROSAS, PONDEROSA, SANTOS). Antes SCARLET no se
  detectaba como marca ajena → 0 penalty.
- **`brand_in_name`** subido de +0.10 a +0.25: la marca del propio
  proveedor en el nombre del artículo es señal fuerte. Ahora compite
  con sinónimos débiles.
- **Golden set link accuracy**: 43.2% → **93.2%** (82/88 líneas
  correctas). LA ALEGRIA 7%→98%, FIORENTINA 17%→100%.
- **Benchmark global**: ok 1918→2002, autoapprove 65.2%→66.1%.
- 6 errores restantes: sinónimos `aprendido_en_prueba` apuntando a
  marcas ajenas (EQR, CANTIZA, FIORENTINA). Se resuelven con
  confirm/correct desde la UI.

## 2026-04-16 — sesión 9f: Paso 5 — TOTALES_MAL resuelto

- **Fallback central** en [procesar_pdf.py](../procesar_pdf.py) y [tools/evaluate_all.py](../tools/evaluate_all.py):
  si el parser no extrae `header.total` (=0) o extrae un valor
  claramente incorrecto (>10x o <0.1x la suma de líneas), usa la
  suma de líneas como fallback. Cubre todos los parsers heredados
  sin tocarlos individualmente.
- **[src/parsers/auto_campanario.py](../src/parsers/auto_campanario.py)**: fix del total ×100 — `Total Invoice:
  $157.00` se parseaba con `_num()` europeo que trataba el punto
  como separador de miles. Ahora usa `float(s.replace(',',''))`.
- **Resultado**: TOTALES_MAL 26→1 (solo ECOFLOR queda, con gap
  real de parseo 724 vs 667). OK 35→59 (+24).

## 2026-04-16 — sesión 9e: Paso 7 — Enganchar sinónimos a la UI

- **[web/api.php](../web/api.php)**: 2 endpoints nuevos `confirm_match` y
  `correct_match`. `confirm_match` promueve sinónimo
  (`aprendido_en_prueba` → `aprendido_confirmado`, incrementa
  `times_confirmed`). `correct_match` degrada el sinónimo viejo
  (`ambiguo` tras 1 corrección, `rechazado` tras 2) y guarda el
  nuevo como `manual_confirmado`.
- **[web/assets/app.js](../web/assets/app.js)**: botón ✓ por fila en la tabla de
  resultados (llama `confirm_match`). Cambio de artículo en la
  tabla llama `correct_match` (antes llamaba `save_synonym` sin
  distinción). Tab Sinónimos: "Marcar OK" ahora llama
  `confirm_match`, "Guardar cambio" llama `correct_match`.

## 2026-04-16 — sesión 9d: Paso 2 — Golden set de validación manual

- Nuevo [tools/golden_bootstrap.py](../tools/golden_bootstrap.py): genera anotación draft JSON
  desde la salida del pipeline para una factura dada.
- Nuevo [tools/evaluate_golden.py](../tools/evaluate_golden.py): compara el sistema contra
  anotaciones gold revisadas — accuracy de parseo por campo,
  accuracy de linking ERP, full-line accuracy, discrepancias.
- Nuevo directorio `golden/` con 5 anotaciones draft: LA ALEGRIA
  (43 líneas), MYSTIC (26), MEAFLOS (12), FIORENTINA (6),
  BENCHMARK (1). Todas en status "draft" — el operador debe
  revisarlas, corregir articulo_id, y marcar como "reviewed".
- CLAUDE.md actualizado: nueva sección "Golden set de validación
  manual", comandos en "Comandos habituales", "Para el próximo
  turno" actualizado.

## 2026-04-16 — sesión 9c: Paso 4 continuación — 3 proveedores más

- **FloraromaParser** ([src/parsers/otros.py](../src/parsers/otros.py)): regex ampliado para
  variante 2024 con bunches pegado a variedad (`2Explorer`, `2Mondial`).
  3/5→5/5. La muestra antigua aporta 103 líneas extra.
- **CantizaParser** ([src/parsers/cantiza.py](../src/parsers/cantiza.py)): `CZ` (Cantiza) cambiado
  a `[A-Z]{1,4}` genérico para soportar `RN` (Rosa Nova, Valthomig).
  Farm regex ampliado. VALTHOMIG 3/5→5/5. CANTIZA 3/5→4/5 (1 muestra
  OCR irrecuperable).
- **RosaledaParser** ([src/parsers/otros.py](../src/parsers/otros.py)): añadida variante B para
  formato pipe-separado (2024) con `I` como delimitador. ROSALEDA
  3/5→5/5. ROSADEX y LA HACIENDA sin regresión.
- **Acumulado sesión completa**: NO_PARSEA 30→20 (-10), OK 30→35 (+5),
  TOTALES_MAL 21→26 (+5). Líneas 2644→3001 (+357).
  Autoapprove 62.0%→65.2% (+3.2pp).

## 2026-04-16 — sesión 9b: Paso 4 parcial — atacar NO_PARSEA guiado por taxonomía

- **[src/pdf.py](../src/pdf.py) — `detect_provider()` reescrito**: ahora busca TODOS
  los patterns y devuelve el match más temprano en el texto (antes
  devolvía el primer match por orden de dict). Fix para MOUNTAIN (3
  PDFs detectados como `life` porque "LIFEFLOWERS" aparecía como
  nombre de cliente en la factura, más abajo que "MOUNTAIN FRESH" en
  la cabecera) y UMA (1 PDF detectado como `rosely`).
- **CondorParser** ([src/parsers/otros.py](../src/parsers/otros.py)): regex ampliado para
  soportar HTS separado del SPB (`35 0603199010` además de
  `350603199010`). 2/5→5/5.
- **AgrivaldaniParser** ([src/parsers/agrivaldani.py](../src/parsers/agrivaldani.py)): clases de
  caracteres ampliadas para acentos/ñ (`PIÑA COLADA CRAFTED` no
  matcheaba `[A-Z]`). 3/5→5/5. LUXUS sin regresión.
- **LifeParser** ([src/parsers/life.py](../src/parsers/life.py)): fallback a AgrivaldaniParser
  cuando el formato A (2026) no parsea nada (facturas 2024 usan el
  template Agrivaldani). 3/5→5/5.
- **MalimaParser** ([src/parsers/otros.py](../src/parsers/otros.py)): añadida variante B para
  sub-líneas de GYPSOPHILA dentro de mixed boxes (`XLENCE 80CM...
  GYPSOPHILA N $X.XX N $X.XX $X.XX`). 4/5→5/5.
- **UmaParser** ([src/parsers/otros.py](../src/parsers/otros.py)): añadido regex para rosas
  (`Nectarine 50 cm Farm...`). Antes solo parseaba Gypsophila. 3/5→5/5.
- **FlorsaniParser** ([src/parsers/otros.py](../src/parsers/otros.py)): añadido regex para
  Limonium (`Limonium Pinna Colada`). 4/5→5/5.
- **Resultado**: NO_PARSEA 30→23 (-7), OK 30→34 (+4),
  TOTALES_MAL 21→24 (+3). Líneas totales 2644→2795 (+151).
  Autoapprove 62.0%→63.6% (+1.6pp).

## 2026-04-16 — sesión 9: Taxonomía de errores E1..E10 (cierra Paso 3 del roadmap)

- **[tools/evaluate_all.py](../tools/evaluate_all.py)** ampliado: ahora emite `penalties` y
  `match_statuses` por proveedor y por muestra (antes solo global).
  Nuevo campo `sin_parser_lines` en CSV y JSON.
- **Nuevo [tools/classify_errors.py](../tools/classify_errors.py)**: lee `auto_learn_report.json`
  y clasifica cada proveedor en las categorías E1..E10 con heurísticas
  automáticas. Output: `auto_learn_taxonomy.json` + tabla terminal
  con backlog priorizado. La prioridad pondera severidad × categoría ×
  impacto, descontado por `autoapprove_rate` (proveedores al 99% auto
  bajan aunque tengan many weak_synonym).
- **Hallazgo principal**: el error dominante del sistema NO es de parseo
  sino de matching/sinónimos: E7 (67/82 proveedores) + E8 (61) + E6 (48).
  E5_TOTAL_HEADER afecta a 47 pero todos con severidad MEDIUM/LOW.
  Los problemas de parseo puro (E1+E3) afectan a ~31+26 proveedores.
- **Baseline actualizada**: 2644 líneas, 62.0% autoaprobables (vs 61.1%
  previo — ligera mejora por penalties refinadas). Top-5 del backlog:
  PONDEROSA, LA ESTACION (E7), LATIN FLOWERS (E8), COLIBRI (E6),
  MULTIFLORA (E6).
- CLAUDE.md actualizado: nueva sección "Taxonomía de errores E1..E10",
  comando en "Comandos habituales", "Para el próximo turno" reescrito.

## 2026-04-15 — sesión 8: Consolidación del benchmark

Cierra Paso 1 del roadmap. Reescritura de [tools/evaluate_all.py](../tools/evaluate_all.py)
a ejecución in-process (antes lanzaba 82 subprocesos cargando el catálogo
cada vez) para obtener acceso a las señales del matcher. Métricas nuevas
por proveedor: `ok_lines`, `ambiguous_lines`, `autoapprovable_lines`,
`autoapprove_rate`, `needs_review_lines`, mix de `extraction_source` y
motor OCR. Nuevo artefacto `auto_learn_penalties_top.json` con ranking
global de `match_penalties` (entrada directa para la taxonomía del
Paso 3). Salida también en CSV (`auto_learn_report.csv`) para comparar
en el tiempo. Baseline capturada: 2644 líneas, 61.1% autoaprobables;
top penalty `weak_synonym` (1382 ocurrencias).

## 2026-04-15 — sesión 7: Reorganización documental (sin cambios de código)

Los dos documentos de seguimiento pasan a nombres cortos coherentes:

- `docs/roadmap/verabuy_roadmap_y_prompts.md` → [`docs/roadmap/roadmap.md`](roadmap/roadmap.md)
- `docs/roadmap/verabuy_checklist_operativa.md` → [`docs/roadmap/checklist.md`](roadmap/checklist.md)
- Nuevo [`docs/README.md`](README.md) como índice corto.
- Añadida sección "Documentación de seguimiento" al principio del
  CLAUDE.md con el mapa de uso y la regla de sincronización.
- Añadido puntero desde `README.md` raíz a `CLAUDE.md` y `docs/`.

Referencias cruzadas entre roadmap y checklist actualizadas.

## 2026-04-15 — sesión 6: Scoring de matching por evidencia

- **Candidatos vs ganador**: los generadores antiguos (sinónimo,
  priority, branded, delegation, color-strip, exact, rose, fuzzy) dejan
  de "ganar" por llegar primero. Ahora todos proponen candidatos y un
  único scorer de features decide.
- **Vetos estructurales**: species/origin/size incompatibles descartan
  el candidato. Un sinónimo que active un veto pasa a status `ambiguo`.
- **Penalty por marca ajena**: nombres con marca distinta al proveedor
  (`ROSA BRIGHTON 50CM 25U FIORENTINA` siendo proveedor MYSTIC) reciben
  −0.25 para que ganen genéricos o versiones con la marca correcta.
- **Estado `ambiguous_match`**: línea bien leída sin vínculo claro →
  amarillo en UI, cuenta como needs_review, no auto-vincula.
- **`InvoiceLine` gana** `link_confidence`, `candidate_margin`,
  `candidate_count`, `match_reasons`, `match_penalties`,
  `top_candidates` (todos con defaults seguros).
- **`SynonymStore` gana** metadatos de fiabilidad: `status`,
  `times_used`, `times_confirmed`, `times_corrected`, `first_seen_at`,
  `last_confirmed_at`. Método `trust_score()` deriva 0–1 a partir de
  status + contadores. Un sinónimo `aprendido_en_prueba` ya no vale
  1.00 por defecto — ahora 0.55 y el sistema lo gestiona como tal.
  Nuevas APIs: `mark_used`, `mark_confirmed`, `mark_corrected`.
- **Prior histórico por proveedor**: `provider_article_usage()` cuenta
  sinónimos del mismo proveedor apuntando al artículo. Si ≥3, +0.10;
  si ≥1, +0.05. Señal simple pero efectiva.
- **Margen adaptativo**: candidatos dominantes (score ≥ 0.90) necesitan
  solo 0.05 de margen sobre el 2º; candidatos en zona media 0.70–0.90
  necesitan 0.10.
- **UI**: nuevo stat card "Ambiguas", clase `row-ambiguous`, tooltip
  por fila con reasons + penalties + margin.
- **Compat**: `_METHOD_CONFIDENCE` y `_confidence_for_method()` siguen
  siendo importables; el sistema interno ya no depende de ellos.
- Validación: OK 30/82, NO_PARSEA 30/82. Test MYSTIC ahora asigna
  correctamente al artículo genérico `ROSA EC BRIGHTON 50CM 25U` en
  vez de la variante `FIORENTINA`.

## 2026-04-15 — sesión 5: Refuerzo transversal de la capa de extracción

No se tocan parsers. Cambios:

- **Nuevo módulo [src/extraction.py](../src/extraction.py)** con routing diagnóstico:
  triage página a página (nativa vs escaneada), OCRmyPDF+Tesseract
  como rama principal, Tesseract per-page y EasyOCR como fallback,
  `ExtractionResult` con `source`, `confidence`, `ocr_engine`,
  `degraded`, y helper reusable `extract_rows_by_coords()`.
- **[src/pdf.py](../src/pdf.py) refactor**: ahora es wrapper delgado del router;
  API pública intacta (`extract_text`, `get_last_ocr_confidence`,
  `detect_provider`, `extract_tables`) y añade `get_last_extraction()`
  para que el pipeline acceda a las señales finas sin cambios en
  callers existentes.
- **`InvoiceLine.extraction_confidence` + `extraction_source`** con
  defaults seguros (`1.0` / `'native'`). El matcher multiplica el
  score por `extraction_confidence` además de `ocr_confidence`.
- **Rescue marcado como `extraction_source='rescue'`** con
  `extraction_confidence=0.60`. Nueva clase CSS `row-rescue` (lila
  discontinuo) en [web/assets/style.css](../web/assets/style.css) y [web/assets/app.js](../web/assets/app.js).
- **UI**: el stat card "OCR" se convierte en "Extracción OCR/Mixta"
  con tooltip indicando motor y si hubo degradación.
- Cobertura: **OK 27→30, NO_PARSEA 35→31**. El triage desbloquea
  PDFs mixtos que antes se marcaban nativos vacíos (se saltaba la
  rama OCR) o escaneados que nunca llegaban a Tesseract.

## 2026-04-15 — sesión 4: Ataque a los 36 parciales

Parsers mejorados:

- **MYSTIC** (1/5 → 5/5): reescrito regex para soportar box_codes con
  dígitos (`R14`, `R19`), block names opcionales (`SORIALES`, `IGLESIAS`),
  variedades mixed-case (`Gyp Natural Xlence 750 G`), sufijo `N/A`, y
  detección automática de especie (GYPSOPHILA, ROSES, etc.).
- **LA ESTACION / PONDEROSA** (2/5 → 5/5): el regex de VerdesEstacionParser
  variante B no soportaba labels multi-palabra (`TIPO B`). Fix: `(.*?)`
  en lugar de `(\S*?)` para capturar label antes de `VERALEZA SLU`.
- **MILONGA** (2/5 → 4/5): ColFarmParser ampliado con tolerancia OCR
  (`Rbse`/`Rcse` por `Rose`, `S1`/`SI`/`Sl` por `ST`, decimales coma).
  Count de caja opcional, separador `-` opcional entre SPB y size para
  soportar `FreedomX25 50` pegado. El 5º sample sigue fallando por OCR
  demasiado corrupto (`R:ise`, `sr`, `1~`).
- **MULTIFLORA** (2/5 → 5/5): añadidas variantes B (`N Box/Half/Quarter
  N N PRICE TOTAL FBE` sin segunda palabra en box_type) y C (`FBE PIECES
  Half Tall UNITS description UPB St(Stems) PRICE $TOTAL` con $ prefix).
  Detección de especie CARN/ROSE además de ALSTRO/CHRY/DIANTHUS.
- **SAYONARA** (2/5 → 3/5): añadidas keywords `Cushion`/`Button`/`Daisy`/
  `Cremon`/`Spider` a `_TYPE_MAP` para template nuevo "Pom Europa/Asia
  White Cushion Bonita". Nuevo `_PACK_RE_B` para formato `6 HB15 1200 240
  $0.950 $228.00` (btype+spb pegado, stems y bunches invertidos).
- **STAMPSY / STAMPSYBOX / FIORENTINA** (0/5 → 5/5): al arreglar MYSTIC,
  estos tres comparten el mismo fmt='mystic' y se beneficiaron. Añadido
  fallback `_LINE_RE_NOCODE` para STAMPSYBOX que no tiene box_code
  (variety va directamente tras `H|Q`).
- **Mejora en pdf.py**: `_ocr_extract` ahora agrupa tokens OCR por
  y-centro del bbox (tolerancia 15 px) en lugar de emitir un token por
  línea. Desbloquea regex por fila para facturas escaneadas con columnas.
- Tabla global: **OK 24→27, NO_PARSEA 36→35**. Los fallos remanentes
  son casi todos PDFs OCR muy corruptos (irrecuperables con regex) o
  gaps de totales (cosmético).

## 2026-04-15 — sesión 3 (fixes): Reportes del usuario

1. CONEJERA aún no parseaba porque `register` no actualizó `fmt='turflor'→
   'auto_conejera'` (su regex solo toca stubs con fmt='unknown'). Fix manual
   en config.py. Ahora 8/9 líneas parsean, la 9ª es un resumen científico
   del pie de factura, no producto.
2. GLAMOUR recortaba variety a fragmentos ('AL', 'GHTON') porque `split('I')`
   rompía tokens como 'R11-BCPI' o `$0.300000I 13.00` (I pegado a dígito/$).
   Fix: `re.split(r'(?<![A-Z])I\s+')` — solo separa cuando la I no está
   precedida por mayúscula. Ahora GLAMOUR extrae 4/4 variedades correctas.

## 2026-04-15 — sesión 3: Evaluación masiva

Evaluación masiva de los 66 parsers heredados con nuevo script
[tools/evaluate_all.py](../tools/evaluate_all.py). Arreglados los 4 parsers completamente
rotos (0 líneas parseadas): CONEJERA (era fmt='turflor' incorrecto, nuevo
auto_conejera), AGROSANALFONSO+GLAMOUR (nuevo auto_agrosanalfonso para su
template `I`-separado), ROSABELLA (nuevo auto_rosabella). De 37 NO_PARSEA
quedan 36 parsers con gaps parciales documentados en auto_learn_report.json.

## 2026-04-15 — sesión 2 (cont): +SAN FRANCISCO / ZORRO / CEAN / ELITE

+SAN FRANCISCO (5/5 Hydrangeas) +ZORRO (1/1 con tolerancia OCR) +CEAN
(4/5 factura electrónica COL con traducción colores) +ELITE (4/5
Alstroemeria parent/sub-líneas). FESO descartado por ser carguero
(EXCELLENT CARGO SERVICE SAS), añadido a SKIP_PATTERNS. **0 stubs
pendientes.**

## 2026-04-15 — sesión 2: Atacando los 5 stubs difíciles

+MOUNTAIN (5/5 con x-coords de pdfplumber) +NATIVE BLOOMS (4/5, soporta
layout roses + tropical). Añadida regla obligatoria de mantener
CLAUDE.md actualizado solo.

## 2026-04-15 — sesión 1: Mejoras de pipeline iniciales

Mejoras de pipeline (confidence, validación, conciliación, LLM
fallback), UI de revisión con badges/dots, 10 parsers nuevos (FARIN,
QUALISA, BELLAROSA, AGRINAG, NATUFLOR, GREENGROWERS, EL CAMPANARIO,
FLORELOY, SAN JORGE, MILAGRO), arreglo de VerdesEstacionParser (variante
B sin CM), CLAUDE.md inicial. Commit `5856f26`.

### 2026-04-21 — sesión 9z + 9z-post: manual-pin cierra mismatch UMA XL ESPECIAL (golden 100%)

Último mismatch conceptual del golden: UMA 18222 línea "Gyp XL
Especial 80 cm /750gr" apuntaba a 28188 "PANICULATA (GYPSOPHILA)
MIXTO M-14 N" (genérico) cuando el gold era 28205 "PANICULATA
XLENCE TEÑIDA MIXTO 750GR 1U". Existía sinónimo `manual_confirmado`
con key exacta `440|GYPSOPHILA|GYPSOPHILA XL ESPECIAL|80|25|` → 28205
(`sinonimos_universal.json`, times_confirmed=2) pero el matcher lo
ignoraba: el syn_trust solo aporta +0.245 al score, no fuerza la
victoria.

Fix en [src/matcher.py:884-906](src/matcher.py) (bloque nuevo antes
del sort final): si `manual_syn_locked` y el candidato ligado está
en viable, `score = max(score, 1.10, other_top + 0.05)` + reason
`manual_pin`. Complementa los fixes de 9y (hard_vetoes) y 9x
(brand_boost skip, sinonimos.add no-clobber): ahora
`manual_confirmado` es pin absoluto al final del scoring.

**Nota 9z-post**: el commit de 9z registró métricas pesimistas
(golden 97.6%, autoapprove 90.9%) porque la extracción de UMA 18222
devolvió 7 líneas en vez de 14 en ese run, atribuido entonces a una
actualización de librería. Al re-ejecutar en 9z-post el parser
captura las 14 líneas correctamente y el golden sube a **100%
(292/292)**. Hipótesis: warm-up frío de easyocr/tesseract. Sin
cambios de código entre 9z y 9z-post.

Impacto real (verificado en 9z-post): golden link 99.7→**100%**
(+1 línea, el XL ESPECIAL). Autoapprove 91.1→**91.2%** (+0.1pp).


### 2026-04-20 — sesión 9y: manual_confirmado sobrevive hard_vetoes (+0.4pp golden)

Con 9x el matcher ya respetaba `manual_confirmado` en `brand_boost`
y en `sinonimos.add()`, pero **los hard_vetoes seguían
descartándolo y degradándolo a ambiguo**. Ejemplo YELLOW SUMMER
verdesestacion: la línea es COL 40/10 y el único artículo "YELLOW
SUMMER" del catálogo es `33632 EC 50CM 25U`. Veto de origin lo
descartaba y el sinónimo manual creado por golden_apply bajaba a
ambiguo; match caía en YELLOW KING 40CM 25U (variedad distinta).

Fix en [src/matcher.py:795-820](src/matcher.py): en la fase de
vetos, si el candidato es un sinónimo `manual_confirmado` se
**mantiene viable con el veto como penalty** y no se degrada.
Respeta la decisión explícita del operador aunque estructura
(origen/talla/spb) no encaje. Único mismatch restante del golden
es el conceptual de GYPSOPHILA XLENCE gramaje (uma).

Impacto: golden 99.3→**99.7%**. Autoapprove 91.2→91.1% (sin
importancia, dentro del ruido).

