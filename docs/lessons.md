# Lecciones aprendidas

Conocimiento transversal reutilizable acumulado sesión a sesión. Para
el contexto específico de cuándo se aprendió cada cosa, ver la sesión
correspondiente en [`sessions.md`](sessions.md).

---

## Extracción y OCR

- **OCR con detalle de confianza**: EasyOCR con `detail=1` devuelve
  `(bbox, text, conf)` por segmento. La media se expone vía
  `get_last_ocr_confidence()` en [src/pdf.py](../src/pdf.py) y se
  propaga a cada `InvoiceLine.ocr_confidence`.
- **Preproceso OpenCV mejora OCR drásticamente**: denoise bilateral +
  binarización adaptativa gaussiana + deskew. Solo se activa si cv2
  está instalado; si no, no-op.
- **pdfplumber tables no siempre sirve**: MOUNTAIN tiene una tabla
  cuyo `extract_tables()` no detecta bien las columnas de tallas
  (40/50/60/70 cm). Solución: `extract_words()` con x-coordinates para
  mapear cada valor a su columna por posición horizontal.
- **OCR fragmentado por columnas**: si un PDF escaneado tiene columnas
  apretadas, EasyOCR emite un segmento por celda y `_ocr_extract`
  antes producía una palabra por línea — lo que rompía regex por fila.
  Fix: agrupar segmentos por y-centro del bbox (tolerancia 15 px a
  300 dpi). Esto desbloquea parsers como MILONGA-scan y debería ayudar
  a cualquier parser OCR-based a futuro. Se mantiene el orden
  izquierda→derecha dentro de cada fila por x0.
- **Routing de extracción antes de OCR**: no todos los PDFs necesitan
  OCR, y correr OCR "por si acaso" es lento y a veces peor. El router
  en [src/extraction.py](../src/extraction.py) hace un triage página a
  página: si pdfplumber devuelve ≥40 chars con ≥35% alfanuméricos, la
  página es nativa. Si no, se marca `scan`. El resultado final puede
  ser `native`, `mixed` o `ocr` — la UI y el matcher usan esa
  distinción.
- **OCRmyPDF > EasyOCR para escaneados normales**: OCRmyPDF preserva
  el orden de columnas mucho mejor que EasyOCR per-page porque usa
  Tesseract con la geometría original del PDF. Lo usamos primero si
  está disponible; EasyOCR queda solo como último recurso o para PDFs
  problemáticos.
- **Nunca marcar "igual de fiable" un PDF nativo y uno OCRizado**: el
  pipeline ahora multiplica `match_confidence` también por
  `extraction_confidence`, así un PDF mixto con una página OCR mala
  arrastra el score aunque la línea concreta haya matcheado por el
  método más fuerte (sinónimo, exacto).
- **Rescue no debe camuflar fallos**: las líneas capturadas por
  `rescue_unparsed_lines` ahora llevan `extraction_source='rescue'` y
  `extraction_confidence=0.60`. La UI las pinta en lila discontinuo
  para que el operador vea que el parser específico no las capturó.
- **No todos los PDFs son rescatables**: algunas facturas escaneadas
  salen con caracteres OCR tan corrompidos (`R:ise`, `sr` en vez de
  `ST`, `1~` en vez de dígito, tokens fragmentados, acentos basura)
  que ningún regex puede recuperarlas. Aceptar pass_ratio < 100% en
  esos casos (MILONGA scan, SAYONARA scan).

## shadow_report puede mostrar estado viejo de sinónimos

El reporte `shadow_report --top-missing-articles` agrega
**rescates históricos** del operador (decisiones donde
`proposed_articulo_id=0` y el humano asignó manualmente). Esos
rescates son del momento en que ocurrieron — no reflejan si el
sinónimo fue después confirmado y ya no es "pendiente".

Caso concreto (sesión 12m): Brissas `GARDEN ROSE APPLE 50/60`
salía con 6 rescates en el reporte, sugiriendo "alta en ERP
pendiente". En realidad ya estaban `manual_confirmado` desde
hace varias sesiones — el matcher actual ya lo encuentra solo.

**Política antes de actuar sobre items del shadow report**:
verificar el estado actual del sinónimo en
`sinonimos_universal.json`:

```bash
grep -F "<provider_id>|ROSES|<VARIETY>|" sinonimos_universal.json
# o programáticamente:
python -c "
import sys, json
sys.stdout.reconfigure(encoding='utf-8')
syns = json.load(open('sinonimos_universal.json', encoding='utf-8'))
for k, v in syns.items():
    if 'GARDEN ROSE APPLE' in k.upper():
        print(k, '→', v.get('articulo_id'), v.get('status'))
"
```

Si está `manual_confirmado` ya, no hay nada que hacer — el
shadow lo está mostrando por inercia histórica. Si está
`aprendido_en_prueba` o `None`, entonces sí es candidato a
confirmación o corrección.

## Tests de regresión sin pytest (unittest built-in)

Si el repo no tiene `pytest` instalado y no quieres añadir
dependencia, `unittest` (built-in) es perfectamente válido para
tests de regresión de parsers. Características recomendadas:

- Usar PDFs reales del `batch_uploads/<id>/` del operador (no
  mockear) — los samples ya cubren los casos edge históricos.
- Cada test cita la sesión que introdujo el comportamiento.
- Solo testear el parser, no el matcher (los `articulo_id`
  cambian al reimportar catálogo).
- Usar `subTest` para múltiples casos del mismo invariante:
  ```python
  for pdf, expected in [...]:
      with self.subTest(pdf=pdf):
          ...
  ```
- Skip en lugar de fail si el PDF no está disponible:
  ```python
  if not pdf_path.exists():
      raise unittest.SkipTest(f'Sample no disponible: {pdf_path}')
  ```

Comando: `python -m unittest tests.test_parser_regressions -v`.

## Sync JSON↔MySQL de sinónimos

El backend Python actualiza `sinonimos_universal.json`
(autoritativo en local). El frontend PHP escribe directamente a
la tabla MySQL `sinonimos` cuando el operador interactúa via UI.
**No hay sync automático** entre los dos en el sentido
JSON→MySQL.

Si modificas `sinonimos_universal.json` directamente (script de
mantenimiento, corrección masiva), MySQL queda desactualizado en
producción. Dos opciones:

1. **Regenerar SQL** y aplicar manualmente (sesión 12m generó
   `sql_sync_12m.sql` con UPDATEs y DELETEs).
2. **Reset MySQL desde JSON** — `verabuy_trainer.py` o un script
   ad-hoc que borre `sinonimos` y haga INSERT bulk desde el JSON
   (`SynonymStore.export_sql()` lo genera).

En la máquina del developer NO hay `mysql.connector` instalado,
así que `_bulk_sync_to_mysql()` falla silenciosamente desde
Python. Es esperado. Solo afecta cuando se ejecuta en
producción.

## Regenerar golden files tras fixes que cambian composición

Cuando un fix de parser cambia el **número** o **composición**
de líneas que produce (no solo el contenido de cada línea), los
golden files quedan invalidados. Política tras un fix así:

1. Correr `python tools/evaluate_golden.py` para detectar
   `missing_line` y `extra_system_line`.
2. Para cada gold afectado: regenerar desde el PDF original
   (en el path absoluto del operador, ej.
   `C:/Users/diego.pereira/Desktop/DOC VERA/.../<PROVEEDOR>/`)
   ejecutando el pipeline manualmente y reemplazando `lines`.
3. Mantener `_status: reviewed` y añadir `_regenerated:
   <ISO date>` + `_regenerated_reason: <sesión>` al JSON
   para trazabilidad.
4. Si la regeneración cambia `articulo_id` (link_mismatch),
   investigar caso por caso — puede ser sinónimo aprendido vs
   asignación manual histórica del operador.

Si esto no se hace, el roadmap arrastra una "regresión
esperada" indefinida que esconde desviaciones reales.

Ejemplos históricos:
- **12d MIXTO consolidación** (split por color → MIXTO single-line):
  invalidó `benchmark_103685.json` (32 → 29 líneas, regenerado
  en 12l).
- **12h MEAFLOS miles** (`(\d+)` → `([\d.]+)` en stems):
  faltaba la línea `MONDIAL 1.200` ($300) en
  `meaflos_EC1000035075.json` (12 → 13 líneas, gold sum
  cuadraba con header tras añadirla en 12l).

## `spb` vs `bunches` en regex multi-columna

Cuando el patrón captura `... SIZE BUNCHES STEMS PRICE TOTAL`
(orden común en proveedores con plantilla "boxes/box bunches/
stems"), no asignar el group de `bunches` a la variable `spb`.
El comentario del regex puede decir correctamente
`BUNCHES STEMS` pero el código asigna mal — bug invisible con
coste oculto en rescates del operador (sesión 12j, TessaParser:
MONDIAL 70 caía siempre en spb=10, el operador rescataba
manualmente al artículo correcto spb=25).

Patrón seguro:
```python
sz = int(group(3))
bunches = int(group(4))
stems = int(group(5))
spb = stems // bunches if bunches > 0 else 25
il = InvoiceLine(..., stems_per_bunch=spb, bunches=bunches, stems=stems)
```

Importante poblar también `bunches=` en el `InvoiceLine` para
que la UI tenga la información completa y la validación cruzada
pueda detectar inconsistencias. Síntoma a buscar en
shadow_report `--top-missing-articles`: el mismo proveedor +
variety + size pero **spb anómalo** (ej. spb=10 en MONDIAL/
EXPLORER cuando lo normal es spb=25).

## Mixed-box sub-líneas con variety colgada

Los proveedores de flor empaquetan a menudo varias variedades en
una "caja física" (HB/QB/TB). En el PDF impreso, esto suele
expresarse con un **parent** que trae el prefijo de cantidad de
caja (`<box_n>/<total>`, `N hb XXX`, etc.) seguido por **N
sub-líneas** que comparten esa caja pero solo traen variety y
totales propios. Tres patrones encontrados:

- **UmaParser** (sesión 12i): parent `<COD> 1 hb 300 ...`,
  sub-line `<COD> Brighton 60 cm Farm 50 25 2 $ 0,26 $ 13,00`
  (solo cambia que falta `1 hb 300`). Fix: regex pm3 sin prefijo
  `N hb XXX`, hereda `last_btype`/`last_farm`.
- **VerdesEstacionParser** (sesión 12i): parent `1/37 HB 0,50 1,00 BRIGHTON 40CM ...`,
  sub-line empieza directamente por talla porque la variety está
  colgada en la línea anterior con sufijo OCR
  (`MAYRA'S BRIDAL FRESH CUT` arriba, `40CM 25 25 CO ... $ 8,00`
  abajo). Fix: regex `_RE_C` que matchea `^<size>CM` y busca
  variety en `text_lines[i-1]` extrayendo bloque mayúsculas
  inicial antes de `FRESH CUT`/`ROSES*`.

**Auditoría**: parsers donde `N hb XXX`/`<box>/<total>` sea
prefijo obligatorio. Sin un segundo regex de sub-line con
herencia de estado, las líneas extra se pierden silenciosas
(no aparecen en `rescue_unparsed_lines` porque tampoco encajan
en el regex genérico de rescate).

## Variety con caracteres especiales

Nombres de variedades comerciales pueden incluir:

- **Apóstrofes**: `Pink O'Hara`, `Mayra's Bridal`. Si el regex
  trae `[A-Za-z\s\-]`, falla. Añadir `'` (y normalizar curly
  quotes `'`/`'`/`´`/U+0092/U+FFFD a `'` antes de parsear, como
  ya hace VerdesEstacionParser).
- **Dígitos**: `RM001`, códigos numéricos de variedades sin
  nombre comercial todavía. Char class debe incluir `0-9`.
- **`Roses` vs `Rosas`**: cuantificador `s?` no abarca ambos.
  Usar `Ros[ae]s?` (sesión 12h, MeaflosParser con
  `Garden Roses -`).

## Regex de detalle en parsers

- **`Rosas?` no matchea `Roses`**: el cuantificador `s?` hace `s`
  opcional al final de `Rosa`, no en alternation. Para aceptar
  ambos idiomas (proveedores que mezclan español/inglés) usar
  `Ros[ae]s?` o `(?:Rosas?|Roses?)`. Caso típico: `Garden Roses -`
  en MEAFLOS (sesión 12h), `Roses` en facturas de proveedores
  internacionales.
- **`(\d+)` no acepta `1.200`**: cuando una caja lleva ≥1000 stems
  el PDF imprime el separador de miles con punto. El regex
  `(\d+)` sólo matchea dígitos contiguos y la línea entera se
  ignora silenciosamente. Patrón seguro: `([\d.]+)` y al
  convertir `int(s.replace('.', ''))`. Aplicable a stems, bunches
  y cualquier "cantidad alta" potencial. Bug encontrado en MEAFLOS
  (sesión 12h) — auditar otros parsers con cuantificador `\d+`
  para stems.

## Reproceso de batches con `reparse_batch.py`

- **Propagar el dict `validation` al JSON**: `validate_invoice`
  produce `sum_lines`/`header_total`/`header_diff`/`header_ok` que
  la UI usa para el badge "Parcial" en cabecera. Si solo
  reescribes `lines` y los `total_usd`/`ok_count` derivados, el
  campo `validation` queda con los valores viejos del primer
  procesamiento — el badge sigue mostrando el gap antiguo aunque
  el sum nuevo cuadre. Fix: `inv['validation'] = validation` tras
  el `validate_invoice` del pipeline (sesión 12h).
- **Sincronizar thresholds entre tools**: el threshold de
  `needs_review` por confidence vive en 5 sitios distintos
  (`api.php`, `app.js`, `app.extras.js`, `tools/rematch_batch.py`,
  `tools/reparse_batch.py`). Cuando cambia uno, sincronizar todos
  o algunas vistas mostrarán números distintos. Histórico: 0.90 →
  0.84 en sesión que cerró el problema "stuck en Revisar".

## Validación cruzada y totales

- **`header.total = sum(lines)` sin fallback al total impreso es un
  bug silencioso**: si una línea no parsea, `sum_lines` es trivialmente
  igual al "total" derivado y la validación cruzada NUNCA dispara
  aviso. El operador no ve "Parcial" en la cabecera y el hueco pasa
  inadvertido. Patrón correcto: extraer primero el total impreso del
  texto (`Total Value`, `TOTAL USD`, `TOTAL A PAGAR`, `Amount Due`,
  según proveedor) y dejar el `sum(lines)` SOLO como fallback. El
  `if not h.total and lines: h.total = sum(...)` es necesario pero
  no suficiente — debe haber una extracción del total impreso ANTES.
- **Comando de auditoría**: `Grep h\.total\s*=\s*(?:round\()?sum\(`
  en `src/parsers/`. Para cada hit, verificar que el parser tenga
  `m = re.search(r'<patrón_total_impreso>', text)` ANTES del fallback.
  Si no, el parser oculta líneas faltantes.
- **Multi-invoice PDFs**: usa `re.finditer(...)` no `re.search(...)`
  cuando el texto puede traer varias facturas concatenadas (FLORSANI
  trae 1-3 secciones "Single Flowers" según número de invoices del
  PDF). Sumar todas, no solo la primera.
- **Propagar `pdata['pdf_path']` en TODOS los callsites que recreen
  pdata**: parsers tabulares (AlegriaParser → Tierra Verde, Olimpo,
  Ceres) usan `pdfplumber.extract_tables()` desde ahí. Sin la ruta,
  caen silenciosamente al fallback de texto y restan ok-matches sin
  avisar. Callsites a auditar: `cli.py`, `procesar_pdf.py`,
  `batch_process.py`, `tools/{evaluate_all, golden_bootstrap,
  golden_apply, evaluate_golden, reparse_batch, auto_learn_parsers}.py`.

## Parseo de decimales y formatos

- **Decimal con coma vs punto**: muchos proveedores COL/EC usan coma.
  Helper típico: `float(s.replace('.', '').replace(',', '.'))` para
  formato europeo (1.234,56), `float(s.replace(',', '.'))` si solo hay
  coma. NATIVE BLOOMS es peor: usa coma para decimales Y para miles
  (ej "81,000" son $81, no 81k). Ver `_num()` en `auto_native.py` para
  heurística.
- **Acentos en clases de caracteres**: `[A-Z]` no incluye Ñ ni vocales
  acentuadas. Variedades como `PIÑA COLADA` fallan con regex `[A-Z]+`.
  Usar `[A-ZÀ-ÖØ-Ý\u00D1]` o clases de instancia.

## Layouts y templates SaaS

- **Templates SaaS compartidos**: varios proveedores ecuatorianos usan
  el mismo template (parece comercial de algún SaaS local).
  Detectables por la cabecera `# BOX PRODUCT SPECIES LABEL`. Ejemplos:
  QUALISA, BELLAROSA, AGRINAG, NATUFLOR, GREENGROWERS, EL CAMPANARIO.
  Cuando aparezcan stubs con layout así, probar primero con
  `--fmt-name auto_qualisa` o `auto_agrinag` antes de escribir parser
  nuevo.
- **Layout de parent/sub-líneas para mixed boxes**: AGRINAG, MILAGRO
  y TIMANA tienen cajas parent con sub-líneas de detalle.
  Estrategia: emitir sub-líneas (traen variedad real) y saltar parents
  que dicen "MIXED BOX" o "ASSORTED BOX" (no aportan info de
  variedad). En TIMANA las sub-líneas **no traen total ni btype**:
  heredan el box_type del parent y el total se calcula como
  `bunches × spb × price`.
- **Variedades en mixed case**: algunos proveedores (QUALISA,
  NATUFLOR_SaaS, BELLAROSA, ART ROSES) usan mixed case ("Vendela",
  "Freedom", "Mondial") en el PDF. Siempre normalizar con
  `.strip().upper()` antes de guardar en InvoiceLine. **Además**: si
  el regex del parser usa `[A-Z]` estricto, añadir `re.I` o ampliar
  la clase a `[A-Za-z]` — ART ROSES compartía `fmt='mystic'` con
  templates upper-case y fallaba hasta que Mystic se hizo
  case-insensitive.
- **Un fmt → varios proveedores similares**: cuando al arreglar un
  parser hereditado (ej. MYSTIC) varios otros mejoran (STAMPSY,
  STAMPSYBOX, FIORENTINA todos compartían `fmt='mystic'` con su propio
  template ligeramente distinto). Verificar todos los proveedores que
  usan el mismo fmt después de cada fix con regex añadiendo fallbacks
  cuando haya pequeñas diferencias (ej. falta de box_code).
- **Proveedores con dos templates**: algunos cambiaron de template
  (LIFE FLOWERS usaba Agrivaldani en 2024, ahora tiene formato
  propio). Solución: fallback al parser del template antiguo si el
  principal no parsea nada. No mezclar parsers en el mismo regex.

## Detección de proveedor y colisiones

- **Colisión de patterns en detect_provider**: un proveedor puede
  mencionar el nombre de OTRO proveedor en su factura (ej:
  "LIFEFLOWERS" como nombre de cliente/orden en una factura de
  MOUNTAIN). La solución es devolver el match cuyo pattern aparezca
  **más temprano** en el texto (la cabecera del PDF siempre tiene el
  emisor), no el primer match por orden de dict.

## Performance y optimización

- **`SequenceMatcher` en fuzzy_search**: dominante cuando el pool
  supera 5k artículos. Dos optimizaciones cheap que siempre son
  seguras: (i) cache por `(species_key, query, threshold)` — facturas
  suelen repetir variedades; (ii) prefiltro `real_quick_ratio()` y
  `quick_ratio()` antes de `ratio()` completo. En la práctica el
  prefiltro skipea ~2% (los nombres ERP comparten demasiados chars
  con la query); el cache aporta más valor. Reutilizar una instancia
  de `SequenceMatcher` con `set_seq2()` también ayuda marginalmente.
- **Reclassify > sinónimo nuevo para MIXED**: cuando una línea es
  claramente mixed box (`SURTIDO MIXTO`, `ASSORTED ROSA`, `MIX`)
  reclasificar a `match_status = 'mixed_box'` en lugar de dejar
  `ambiguous_match` / pedir sinónimo. Es más honesto y el operador
  entiende enseguida que la caja no tiene desglose por variedad.
  Regex en `reclassify_assorted` (matcher.py). Sesión 9q: IWA 19
  ambig → 2 ambig + 17 mixed_box.

## Benchmark y métricas

- **Abrir parsers puede bajar autoapprove_rate temporalmente**. Una
  regex que captura 30 líneas nuevas de MIXED boxes aporta al
  denominador pero no necesariamente al numerador (muchas caen como
  ambiguous/sin_match hasta que aprendan sinónimos). Medir por
  **buckets de proveedores OK** y **líneas ok absolutas**, no solo
  por tasa. Sesión 9p: líneas ok 2739→2785 (+46) pero autoapprove
  87.1%→86.7% (−0.4pp).
- **MUCHO_RESCATE es peor señal que NO_PARSEA**: NO_PARSEA con
  parsed_any alto suele ser "1 sample OCR corrupto"; MUCHO_RESCATE
  significa que el parser ve lineas pero el regex no encaja.
  Priorizar MUCHO_RESCATE → rescatadas se convierten en parsed real
  cambiando 1 regex (IWA sesión 9p: 32 rescued → 0 con regex
  reescrita anclada en tariff).

## Matching

Reglas vivas del matcher (tablas con aportes/penalizaciones) están en
[`architecture.md`](architecture.md#matching). Aquí solo las lecciones
transversales:

- **Los "generadores de candidatos" no deben decidir el match**.
  Sinónimo, priority, branded, delegation, color-strip, exact, rose y
  fuzzy proponen candidatos; un único scorer de evidencia decide quién
  gana. Llegar primero no da ventaja.
- **Vetos estructurales antes que score**: species/origin/size
  incompatibles descartan el candidato aunque venga de un sinónimo
  manual — si un sinónimo activa un veto, se degrada a `ambiguo`.
- **Scores > 1.0 permitidos internamente**: el clamp superior aplasta
  candidatos con evidencia rica y destroza los desempates de
  `brand_boost`. Mantener `cand.score` sin techo; solo clampar
  `line.link_confidence` a 1.0 para la UI y `match_confidence`.
- **`size_exact` y `size_close` no son intercambiables**: un artículo
  a ±10 cm de la talla parseada nunca debe disparar `brand_boost`
  aunque tenga la marca correcta. Cambio sutil con impacto grande.
- **Margen requerido depende del tramo de score**: ≥1.05 basta 0.02,
  ≥0.90 basta 0.05, 0.70–0.90 requiere 0.10. Un top1=1.138 frente a
  top2=1.10 con margen 0.03 es victoria clara, no empate.
- **Marcas cortas (EQR, etc.) no deben ser excluidas por longitud**:
  el filtro `len(tok) >= 4` en `_detect_foreign_brand` deja pasar
  marcas ajenas de 3 letras. Usar 3 con protección contra tokens tipo
  `CM`/`U` que son sufijo de talla/packaging.
- **`origin_match` merece peso alto en rosas/claveles (0.15, no 0.10)**:
  el prefijo EC/COL del catálogo es autoritativo y debe imponerse
  contra un fuzzy 100% sobre artículo genérico sin origen.
- **Filtro anti-ruido al caer en `low_evidence`**: si el ganador no
  tiene `variety_match` Y su fuzzy `hint_score` < 0.85, la línea debe
  ir a `sin_match`, no a `ambiguous_match`. Matches arbitrarios tipo
  "SHY → SYMBOL" confunden al operador más de lo que ayudan. Umbral
  0.85 preserva casos como LIMONADA→LEMONADE (similitud 0.88 sin
  solape literal, pero semánticamente relacionados).
- **CARNATIONS: traducir la variedad antes de puntuar**: el catálogo
  indexa claveles por color en español (`CLAVEL COL FANCY NARANJA`)
  pero las facturas llegan con "COWBOY ORANGE". Al puntuar, añadir
  los tokens traducidos al set de `line_var_tokens` para que
  `variety_match` dispare correctamente.
- **`brand_by_provider` cubre casos donde la key ≠ marca**: p. ej.
  `verdesestacion` vende como PONDEROSA. Añadir `brand_by_provider`
  al `own_brands` evita que PONDEROSA se penalice como foreign_brand.
- **Los sinónimos `aprendido_en_prueba` son deuda que crece hacia el
  artículo equivocado**: un sinónimo heredado con trust 0.55 +
  method_prior 0.10 aporta +0.24 al candidato al que apunta. Si ese
  sinónimo apunta a un genérico (`ROSA EC LEMONADE 70CM`) y existe un
  branded propio del proveedor (`... SCARLET`), el +0.24 derrota al
  `brand_in_name(+0.25)`. La regla "marca propia > genérico > marca
  ajena" exige cerrar ese gap: penalty `generic_vs_own_brand` (−0.15)
  cuando el candidato es genérico Y en el pool existe un candidato
  branded propio. Lección transferible: **cualquier bonus por evidencia
  externa (sinónimo, histórico, prior) debe tener un contrapeso
  contextual cuando compite con una señal estructural fuerte** como la
  marca propia.
- **`variety_match` parcial por tokens de familia es ruido**: cuando
  la variety incluye palabras que aparecen en TODOS los candidatos del
  mismo pool (PANICULATA/XLENCE/TEÑIDA para gypsophila teñida, ROSA/EC
  para rosas EC), el +0.30 de `variety_match` dispara universalmente
  y el único discriminante real es el token del color. `variety_full`
  (todos los tokens cubiertos) debe pesar lo suficiente (+0.10) para
  superar el +0.09 del fuzzy prior que los rivales inferiores
  acumulan. Sesión 10s.
- **Modificadores de color (OSCURO/CLARO/PASTEL) cambian el color,
  no lo matizan**: si la variety pide "AZUL" pero el candidato es
  "AZUL CLARO", son artículos distintos — penalty
  `color_modifier_extra` (−0.12) cuando el nombre del artículo
  contiene un modificador que la variety no incluye. Sesión 10s.
- **Tiebreak cualitativo simétrico**: cuando dos candidatos empatan
  dentro del margen, el tiebreak debe mirar las dos direcciones —
  si top2 tiene la ventaja crítica (variety_full, size_exact, o
  ausencia de color_modifier_extra) que top1 no, swap. No basta con
  mirar si top1 tiene la ventaja: el fuzzy prior puede poner en top1
  un candidato inferior. Sesión 10s.

## Catálogo / BD

- **Nombres truncados por export phpMyAdmin**: 68 artículos Florsani
  tenían `nombre = 'PANICULATA XLENCE TE'` (se perdió la Ñ de
  "TEÑIDA" en el volcado histórico). Los campos estructurados
  (`color`, `marca`, `variedad`, `tamano`, `paquete`) estaban
  intactos. Fix: `ArticulosLoader._reconstruct_truncated_name`
  detecta el truncado y reconstruye `{familia} TEÑIDA {color}
  {tamano} {paquete}U {marca}`. Lección transferible: **cuando la BD
  tiene múltiples fuentes de verdad para un atributo (campo canónico
  vs campo estructurado), prefiere la fuente más rica cuando la
  canónica falla**. La heurística "si es truncado, reconstruir" es
  aditiva y no afecta artículos con nombre completo.
- **Traducción EN→ES en parsers cuando el catálogo es ES**: parsers
  de proveedores que emiten factura en inglés (Florsani, Latin,
  partes de Auto_Cean) deben traducir colores/grados al español del
  catálogo en el propio parser. Pretender que el matcher haga
  fuzzy-translate EN↔ES es frágil: "LAVANDER" ↔ "LAVANDA" ↔
  "LAVANDA OSCURO" son tres artículos distintos y la distancia
  léxica no captura la semántica.
