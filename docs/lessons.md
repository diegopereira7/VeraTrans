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
