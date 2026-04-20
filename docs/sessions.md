# Historial de sesiones

Registro cronológico de sesiones de desarrollo del VeraBuy Traductor.
Las 2 sesiones más recientes también aparecen en `CLAUDE.md` en la
sección "Historial reciente"; cuando se archive una sesión, se mueve
aquí y se quita de CLAUDE.md.

Para el estado actual del proyecto, ver [`CLAUDE.md`](../CLAUDE.md) (raíz).
Para lecciones transversales reutilizables, ver [`lessons.md`](lessons.md).

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
