# Hoja de ruta operativa + prompts ultradetallados para VeraBuy Traductor

## Cómo usar este archivo

Este documento está pensado para ir ejecutándolo **por bloques independientes** cuando tengas tiempo.

Reglas de uso:
- Ejecuta **un solo prompt cada vez** en Claude Code.
- Antes de pasar al siguiente, revisa el resultado y confirma que el repo sigue estable.
- Si un prompt toca código, debe **actualizar `CLAUDE.md` en el mismo turno**.
- No avances al siguiente paso si el anterior no deja:
  - cambios aplicados,
  - validación mínima,
  - resumen claro,
  - y `CLAUDE.md` actualizado.
- **Sincroniza estado antes de ejecutar**: si ha pasado más de una sesión,
  releer el "Contexto actual resumido" y compararlo con el historial de
  sesiones de `CLAUDE.md`. Si el contexto está desfasado (p. ej. el paso
  ya se hizo parcialmente), **primero** actualiza este archivo y el
  checklist, **luego** ejecuta el prompt. Esto evita relanzar trabajo
  ya hecho o aplicar un prompt sobre un código que ya no se parece al
  descrito aquí.

## Contexto actual resumido

> Este bloque debe **re-sincronizarse con `CLAUDE.md`** cada vez que se abra
> una sesión nueva. Los números y el estado de las capas del pipeline deben
> venir del último historial de sesiones de `CLAUDE.md`, no de memoria.

Estado del proyecto tras las **sesiones 5 y 6** (abril 2026):

- **Pipeline end-to-end**: extracción (router diagnóstico) → detección de
  proveedor → parser específico → split mixed boxes → rescue → matching por
  evidencia → LLM fallback opcional → validación cruzada → reconciliación →
  serialización con señales finas.
- **Extracción** (sesión 5): ya NO es `pdfplumber → pdftotext → EasyOCR` en
  cascada ciega. Ahora hay un **router** en `src/extraction.py` que hace
  triage por página (nativo vs scan según caracteres + `extract_words`),
  usa **OCRmyPDF+Tesseract** como rama principal cuando detecta escaneado,
  y deja **EasyOCR** como fallback. Se publica un `ExtractionResult` con
  `source` (`native|mixed|ocr|empty`), `confidence`, `ocr_engine`,
  `degraded`. `src/pdf.py` es wrapper delgado con API retrocompatible.
- **Matching** (sesión 6): ya NO es un pipeline de 7 etapas con score fijo
  por método. Ahora los antiguos generadores (sinónimo, priority, branded,
  delegation, color-strip, exact, rose, fuzzy top-N) solo *proponen*
  candidatos; un scorer único con features (variety, size, species,
  origin, spb, marca en nombre, histórico del proveedor, trust del
  sinónimo) + vetos duros (species/origin/size incompatibles descartan) +
  penalty `foreign_brand` decide. Margen adaptativo top1-top2 (0.05 si
  top1 ≥ 0.90, 0.10 si no) introduce el nuevo estado `ambiguous_match`.
- **Modelo** (sesión 6): `InvoiceLine` gana `link_confidence`,
  `candidate_margin`, `candidate_count`, `match_reasons`,
  `match_penalties`, `top_candidates` (defaults seguros).
  `extraction_source='rescue'` marca líneas capturadas por el regex
  genérico para no disimular fallos del parser específico.
- **Sinónimos** (sesión 6): `SynonymStore` extendido con `status`
  (`manual_confirmado` / `aprendido_confirmado` / `aprendido_en_prueba`
  / `ambiguo` / `rechazado`), contadores `times_used/confirmed/corrected`,
  timestamps y `trust_score()` derivado 0–1. Un sinónimo nuevo ya **no**
  vale 1.00 por defecto (0.55). Nuevas APIs `mark_confirmed`,
  `mark_corrected`, `provider_article_usage`.
- **Cobertura**: el triage de proveedores sigue con `84 REGISTRADO_OK`,
  `0 REGISTRADO_STUB`, `8 LOGISTICA` filtrados. Evaluación masiva
  actualizada: **`OK 30/82`**, **`TOTALES_MAL 21/82`**, **`NO_PARSEA 30/82`**,
  `NO_DETECTADO 1/82` (PONDEROSA, por reshuffle del reporte, no
  regresión funcional).
- **Nuevos módulos desde el roadmap original**: `src/extraction.py`,
  `src/validate.py` ya propaga caps a `link_confidence`,
  `src/llm_fallback.py` (Haiku, no-op sin API key).

### Qué pasos del roadmap ya están (al menos parcialmente) hechos

- **Paso 1 (benchmark)**: `tools/evaluate_all.py` existe y es lo que se
  ha usado en sesiones 4–6 para validar regresión. Falta consolidarlo
  con las métricas nuevas (`ambiguous_match`, `needs_review`,
  `extraction_source`, `autoapprove_rate`, `link_accuracy` separado de
  `parse_accuracy`) y con salida JSON/CSV reutilizable. Marcar como
  `[-]` y cerrar con un turno acotado.
- **Paso 6 (matching ERP)**: cubierto en gran parte por la sesión 6
  (scoring por evidencia, vetos duros, trazabilidad via
  `match_reasons`/`match_penalties`/`top_candidates`). Lo que **queda**
  del paso 6 es: auditoría real con datos de producción para medir la
  reducción efectiva de falsos positivos y ajustar thresholds.
- **Paso 7 (sinónimos con estado)**: cubierto en gran parte por la
  sesión 6 (status, contadores, `trust_score`, ascenso/degradación
  automáticos al reescribir el mismo sinónimo). Lo que **queda** es
  enchufar `mark_confirmed`/`mark_corrected` al flujo de la UI cuando
  el operador acepta o cambia un match.
- **Paso 4 (NO_PARSEA industrial)**: atacado en sesiones 3 y 4 para los
  peores casos (MYSTIC, LA ESTACION, MILONGA, MULTIFLORA, SAYONARA,
  STAMPSY/STAMPSYBOX, AGROSANALFONSO/GLAMOUR, CONEJERA, ROSABELLA).
  Quedan ~30 con gaps parciales — sigue vivo como paso.

---

# PASO 1 — Congelar línea base y generar benchmark post-cambios

> **Estado parcial.** `tools/evaluate_all.py` ya existe y lo usan las
> sesiones 4–6 para validar regresión. Lo que queda es **consolidarlo**
> con las métricas nuevas que expone el pipeline tras las sesiones 5 y 6
> — no reescribirlo desde cero. El prompt está acotado a ese delta.

## Objetivo
Dejar una foto objetiva del estado actual del sistema tras los cambios ya implementados o tras ejecutar tus prompts anteriores, para que cada mejora futura se compare contra una baseline real.

## Qué debe salir de este paso
- Un script o flujo repetible para benchmark masivo.
- Un artefacto de salida por proveedor y un resumen global.
- Métricas consistentes y comparables en el tiempo.
- `CLAUDE.md` actualizado con el nuevo procedimiento si se añade tooling.

## Criterio de terminado
Este paso está terminado solo si puedes lanzar un comando y obtener un informe global con, como mínimo:
- proveedor
- nº PDFs analizados
- detected
- parsed_any
- totals_ok
- total_rescued
- líneas low_conf
- líneas sin_match
- líneas sin_parser
- líneas needs_review
- autoapprove_rate estimado

## Prompt para Claude Code

```text
Trabaja directamente sobre este repo y convierte el benchmark del proyecto en un proceso repetible y estable. No me des teoría: implementa cambios reales, valida y actualiza CLAUDE.md en el mismo turno.

CONTEXTO
Este repo es VeraBuy Traductor. Según CLAUDE.md, el proyecto ya tiene una carpeta de entrenamiento fija con subcarpetas por proveedor, 5 facturas nuevas + 2 antiguas por proveedor, un pipeline de extracción/parseo/matching/validación/reconciliación y un estado actual de evaluación masiva con 24 OK, 22 TOTALES_MAL, 36 NO_PARSEA y 0 NO_DETECTADO. El propio CLAUDE.md marca como siguiente paso lógico la evaluación masiva de los parsers heredados. Quiero convertir esto en una baseline formal y repetible.

OBJETIVO
Implementa un benchmark masivo reutilizable que permita medir el estado actual del sistema por proveedor y a nivel global, de forma comparable entre sesiones.

REQUISITOS
1. Revisa si ya existe `tools/evaluate_all.py` o tooling equivalente y reutilízalo si sirve.
2. Si no cubre todo lo necesario, mejóralo o crea un script nuevo bien integrado en `tools/`.
3. El benchmark debe generar:
   - salida por proveedor
   - resumen agregado global
   - formato legible en JSON y, si es razonable, CSV
4. Las métricas mínimas deben incluir (las nuevas vienen de sesiones 5-6):
   - detected
   - parsed_any
   - totals_ok
   - total_rescued
   - número de líneas
   - líneas con `sin_match`
   - líneas con `sin_parser`
   - líneas con `ambiguous_match` (sesión 6)
   - líneas `needs_review`
   - líneas con baja confianza (`match_confidence < 0.80`)
   - media de `link_confidence` por proveedor (sesión 6)
   - distribución de `extraction_source` (`native`/`mixed`/`ocr`/`rescue`) (sesión 5)
   - motor OCR usado por muestra (`ocrmypdf`/`tesseract`/`easyocr`) (sesión 5)
   - estimación simple de tasa de autoaprobación (`ok` sin validation_errors,
     `link_confidence ≥ 0.80`, margen suficiente y `extraction_source` no
     rescue)
   - ranking de `match_penalties` más frecuentes (input para Paso 3)
5. No rompas el flujo actual de `procesar_pdf.py`, `batch_process.py` ni la UI.
6. Si detectas que faltan campos en la serialización para medir bien, añádelos con compatibilidad hacia atrás.
7. Si añades un nuevo script o comando, documenta uso y salida esperada en `CLAUDE.md`.
8. Añade una sección clara en `CLAUDE.md` explicando cómo correr el benchmark y cómo interpretar resultados.
9. Si el entorno no permite ejecutar el benchmark completo, deja el comando listo, prueba al menos con una muestra razonable y documenta limitaciones.

ENTREGABLES
- código real implementado
- benchmark reproducible
- ejemplo de salida o validación mínima
- `CLAUDE.md` actualizado en el mismo turno
- resumen final con archivos tocados y cómo correrlo
```

---

# PASO 2 — Crear un golden set revisado manualmente

## Objetivo
Tener un conjunto pequeño pero de altísima calidad para medir la exactitud real del parseo y del linking ERP, no solo si “salieron líneas”.

## Qué debe salir de este paso
- Una estructura de golden set dentro del proyecto.
- Un formato de anotación claro y mantenible.
- Un validador que compare salida real vs verdad-terreno.

## Criterio de terminado
Este paso está terminado solo si puedes comparar al menos un subconjunto de facturas contra anotaciones manuales y obtener métricas de exactitud por campo y por artículo ERP.

## Prompt para Claude Code

```text
Trabaja sobre este repo y añade soporte formal para un golden set de validación manual. No me expliques la idea: implementa estructura, tooling mínimo y documentación en CLAUDE.md dentro del mismo turno.

CONTEXTO
VeraBuy Traductor ya evalúa providers con métricas como detected, parsed_any, totals_ok y rescued, pero eso no mide la verdad real por línea ni la corrección del artículo ERP enlazado. Quiero introducir un golden set pequeño, manualmente revisado, para medir parseo correcto y linking correcto de verdad.

OBJETIVO
Diseñar e implementar una base de verdad-terreno para un subconjunto representativo de facturas, con tooling para comparar la salida del sistema contra anotaciones humanas.

REQUISITOS
1. Crea una estructura clara dentro del repo para almacenar golden set, por ejemplo bajo `tests/`, `fixtures/`, `golden/` o una ruta razonable y coherente con el proyecto.
2. Define un formato de anotación sencillo, legible y versionable. JSON es preferible si encaja.
3. Cada anotación debe poder representar, como mínimo:
   - proveedor esperado
   - líneas esperadas
   - raw_description esperada o identificador de línea
   - species
   - variety
   - size
   - origin
   - stems_per_bunch
   - bunches / stems cuando aplique
   - line_total
   - articulo_id esperado o equivalente ERP correcto
4. Implementa un comparador que procese una factura, lea su anotación gold y calcule:
   - exactitud de parseo por campo
   - exactitud de artículo ERP
   - aciertos completos por línea
   - discrepancias principales
5. El comparador debe tolerar pequeñas diferencias numéricas razonables donde ya existe tolerancia de negocio.
6. No rompas el pipeline actual.
7. Si no hay anotaciones todavía, crea la estructura, documentación, un ejemplo completo y deja el sistema listo para que yo vaya añadiendo más facturas revisadas manualmente.
8. Añade instrucciones precisas en `CLAUDE.md` para:
   - dónde guardar nuevas anotaciones
   - cómo ejecutar el comparador
   - cómo interpretar resultados
9. Si conviene, crea un script helper para bootstrapear una anotación inicial a partir de la salida actual del sistema, dejando claro que luego debe revisarse a mano.

ENTREGABLES
- estructura de golden set creada
- formato definido
- comparador implementado
- ejemplo funcional incluido
- `CLAUDE.md` actualizado en el mismo turno
- resumen final con comandos de uso
```

---

# PASO 3 — Clasificar errores por tipo y generar backlog accionable

## Objetivo
Dejar de trabajar solo “por proveedor” y empezar a trabajar también por familia de fallo, para arreglar patrones enteros de una vez.

## Qué debe salir de este paso
- Taxonomía de errores oficial.
- Clasificación automática o semiautomática de fallos.
- Un backlog priorizado por impacto.

## Criterio de terminado
Este paso está terminado solo si puedes ver para cada proveedor y/o muestra qué familia de error domina.

## Prompt para Claude Code

```text
Trabaja sobre este repo y añade una capa de clasificación de errores que convierta los resultados de evaluación en un backlog accionable. Implementa cambios reales y actualiza CLAUDE.md en el mismo turno.

CONTEXTO
VeraBuy Traductor ya tiene evaluación por proveedor y un reporte masivo con categorías como OK, TOTALES_MAL y NO_PARSEA. Quiero ir un paso más allá: clasificar los fallos por familia de problema para acelerar mejoras transversales.

OBJETIVO
Implementar una taxonomía de errores y una forma de asignar automáticamente o semiautomáticamente a cada fallo una categoría útil para priorización técnica.

REQUISITOS
1. Adopta la taxonomía oficial ya declarada en `checklist.md`:
   - E1_PARSE_ZERO       — el parser no extrae ninguna línea
   - E2_PARSE_PARTIAL    — extrae algunas líneas pero se deja otras
   - E3_LAYOUT_COORDS    — el problema es de columnas/coords, necesita extract_words
   - E4_OCR_BAD          — OCR corrupto irrecuperable con regex
   - E5_TOTAL_HEADER     — suma de líneas bien, pero header.total mal extraído
   - E6_MATCH_WRONG      — artículo ERP incorrecto con línea bien leída
   - E7_SYNONYM_DRIFT    — sinónimo aprendido que ya no encaja
   - E8_AMBIGUOUS_LINK   — varios candidatos plausibles con margen pequeño
   - E9_VALIDATION_FAIL  — stems vs bunches×spb incoherentes, total_mismatch, etc.
   - E10_PROVIDER_COLLISION — dos proveedores comparten fmt/template y se confunden
2. Implementa un módulo, función o paso de análisis que, a partir de los resultados del benchmark o de salidas por factura, infiera la categoría dominante del fallo.
3. Si no es posible inferirlo todo automáticamente, implementa heurísticas útiles y deja una vía sencilla para clasificación manual complementaria.
4. Genera una salida por proveedor con:
   - categoría principal
   - severidad
   - breve motivo
5. Si es razonable, añade una puntuación de prioridad basada en combinación de:
   - frecuencia de fallo
   - severidad
   - coste operativo estimado
6. No rompas el flujo existente.
7. Documenta en `CLAUDE.md`:
   - taxonomía adoptada
   - cómo se calcula
   - cómo usarla para decidir el siguiente trabajo

ENTREGABLES
- clasificación de errores implementada
- salida legible por proveedor
- prioridad o severidad útil
- `CLAUDE.md` actualizado
- resumen final con cómo ejecutar la clasificación
```

---

# PASO 4 — Atacar los parsers heredados NO_PARSEA con método industrial

## Objetivo
Bajar el bloque de 36 `NO_PARSEA` priorizando solo gaps reales y sin tocar parsers sanos. Esto es la prioridad más alta declarada hoy en el proyecto.

## Qué debe salir de este paso
- Un ranking de parsers heredados a revisar.
- Mejoras aditivas proveedor a proveedor.
- Validación contra 5 nuevas + 2 antiguas.

## Criterio de terminado
Este paso está terminado solo si se reduce de forma medible el número de proveedores o muestras en `NO_PARSEA` sin degradar regresión.

## Prompt para Claude Code

```text
Trabaja sobre este repo y ataca de forma sistemática los parsers heredados con gaps reales de parseo. No hagas cambios cosméticos ni toques parsers sanos. Implementa mejoras reales, valida y actualiza CLAUDE.md en el mismo turno.

CONTEXTO
Según CLAUDE.md, el resultado actual de evaluación masiva deja 36 proveedores en NO_PARSEA, mientras que los stubs ya están resueltos. La propia guía del proyecto dice que el siguiente paso lógico es evaluar y corregir parsers heredados caso por caso, solo cuando haya gaps probados.

OBJETIVO
Reducir el bloque NO_PARSEA con un enfoque industrial, priorizando los parsers heredados más problemáticos y aplicando cambios aditivos, seguros y validados.

REQUISITOS
1. Usa el benchmark/reporte actual para identificar los proveedores heredados con peor pass ratio.
2. No toques parsers que ya den 100% detected + 100% parsed_any + 100% totals_ok + 0 rescued.
3. Para cada parser tocado:
   - inspecciona muestras reales
   - identifica el patrón de fallo
   - aplica cambios aditivos
   - nunca borres regex válidos en producción
4. Prioriza patrones reutilizables:
   - layouts compartidos
   - problemas de coordenadas
   - parent/sub-lines
   - decimal coma/punto
   - variantes A/B de plantilla
5. Después de cada modificación, valida contra las 5 facturas nuevas + 2 antiguas del proveedor.
6. Si un parser no puede llegar a 100% por OCR corrupto real, no lo fuerces con regex absurdas; deja mejor señal de revisión y documenta el límite.
7. Si detectas que varios proveedores comparten el mismo layout y pueden beneficiarse de una misma mejora, hazlo con cuidado y documenta claramente la relación.
8. Documenta en `CLAUDE.md`:
   - qué parsers heredados se tocaron
   - qué gap real tenían
   - qué se cambió
   - antes/después
   - cualquier nueva lección aprendida

IMPORTANTE
Quiero trabajo real en el repo, no una lista de sugerencias. Si no puedes atacar todos en un turno, prioriza los de mayor impacto y deja el trabajo claramente segmentado.

ENTREGABLES
- parsers heredados mejorados
- validación antes/después
- regresión controlada
- `CLAUDE.md` actualizado
- resumen final con los proveedores tocados y resultados
```

---

# PASO 5 — Arreglar los TOTALES_MAL sin sobreinvertir

## Objetivo
Corregir el bloque de 22 `TOTALES_MAL` de forma eficiente, porque es impacto medio-bajo pero mejora validación, confianza y revisión.

## Qué debe salir de este paso
- Mejor captura de `header.total`.
- Menos falsas alertas en validación.
- Criterio homogéneo para fallback a suma de líneas.

## Criterio de terminado
Este paso está terminado solo si disminuye el bloque `TOTALES_MAL` sin romper los parsers que ya suman bien las líneas.

## Prompt para Claude Code

```text
Trabaja sobre este repo y corrige de forma eficiente los casos TOTALES_MAL. No sobrerrefactorices: quiero mejoras prácticas, seguras y bien documentadas.

CONTEXTO
Según CLAUDE.md, actualmente hay 22 proveedores/muestras en TOTALES_MAL. El problema es principalmente cosmético o de extracción de `header.total`, porque la suma de líneas suele estar bien. Aun así, esto degrada validación cruzada y puede ensuciar la revisión.

OBJETIVO
Reducir significativamente los casos TOTALES_MAL mejorando la extracción o derivación de `header.total` de forma robusta y compatible con los parsers actuales.

REQUISITOS
1. Identifica qué parsers o layouts fallan por no capturar `header.total`.
2. Cuando exista un patrón claro de total de cabecera, añade extracción específica.
3. Cuando no exista o falle de forma razonable, aplica de manera segura la derivación por suma de líneas, respetando la convención ya descrita en CLAUDE.md.
4. No dupliques lógica de forma caótica: si conviene, centraliza helpers reutilizables para parseo de totales.
5. Revisa especialmente problemas de formato numérico coma/punto y miles/decimales.
6. No rompas parsers que ya funcionan.
7. Si una mejora afecta a varios proveedores, intenta reutilizarla.
8. Actualiza `CLAUDE.md` con:
   - criterio oficial para `header.total`
   - lecciones aprendidas si aparecen
   - parsers ajustados y resultados

ENTREGABLES
- reducción medible de TOTALES_MAL
- código real implementado
- validación antes/después
- `CLAUDE.md` actualizado
- resumen final con el cambio y su alcance
```

---

# PASO 6 — Auditar y reforzar el matching ERP con errores reales

> **Estado parcial (sesión 6 ya aplicó las mejoras estructurales).** El
> refuerzo del matcher (candidatos + vetos duros + features de evidencia +
> penalty `foreign_brand` + estado `ambiguous_match` + trazabilidad vía
> `match_reasons`/`match_penalties`/`top_candidates`) **ya está hecho**.
> Lo que queda de este paso es la **auditoría empírica**: medir con
> datos reales la reducción de falsos positivos y ajustar thresholds.
> El prompt de abajo sigue siendo válido pero centrado solo en auditar
> y afinar, no en reimplementar.

## Objetivo
Reducir falsos positivos de artículo ERP incorrecto cuando la línea está bien leída pero mal vinculada, que es uno de los problemas de negocio más caros.

## Qué debe salir de este paso
- Auditoría de matches incorrectos contra la baseline y/o el golden set (paso 2).
- Ranking de causas reales usando `match_reasons`/`match_penalties` ya disponibles.
- Ajustes finos de thresholds (`_LINK_OK_THRESHOLD`, `_MARGIN_MIN`, pesos
  de features) y/o nuevas features si la auditoría descubre patrones no
  cubiertos (ej. `siblings_same_variety`, más marcas ajenas en la lista).

## Criterio de terminado
Este paso está terminado solo si bajan los casos donde variedad/talla/proveedor parecen bien, pero el artículo ERP final es claramente incorrecto.

## Prompt para Claude Code

```text
Trabaja sobre este repo y audita el matching ERP con foco en falsos positivos semánticos. Implementa mejoras reales y actualiza CLAUDE.md en el mismo turno.

CONTEXTO
En VeraBuy Traductor ya existe un matcher por etapas en `src/matcher.py` y un sistema de confianza, pero operativamente siguen apareciendo casos donde proveedor, variedad y talla parecen bien leídos y aun así se enlaza a un artículo ERP incorrecto. Quiero atacar ese problema con datos reales del repo y con trazabilidad.

OBJETIVO
Detectar, clasificar y reducir errores de linking ERP debidos a sinónimos demasiado agresivos, fuzzy engañoso, falta de vetos estructurales o poca separación entre candidatos.

REQUISITOS
1. Inspecciona el matcher actual y las señales disponibles en modelos/serialización.
2. Añade tooling o logging útil para poder ver, por línea:
   - candidato ganador
   - top candidatos alternativos si es posible
   - método usado
   - motivos principales del match
   - penalizaciones aplicadas
3. Identifica patrones de falsos positivos reales, especialmente:
   - sinónimos demasiado fuertes
   - matches con size incompatible
   - origin contradictorio
   - candidato top1 demasiado cerca de top2
   - artículo improbable para ese proveedor
4. Refuerza el matcher con cambios de evidencia real y trazabilidad, manteniendo compatibilidad con el flujo actual.
5. Si ya se implementó separación extraction/link confidence, úsala; si no, prepara el terreno sin romper nada.
6. No conviertas esto en una caja negra opaca. Todo lo importante debe quedar explicable.
7. Actualiza `CLAUDE.md` con:
   - nueva lógica aplicada
   - nuevos campos o señales si los hubiera
   - límites conocidos
   - cómo revisar los casos ambiguos

ENTREGABLES
- mejoras reales del matcher
- más trazabilidad de candidatos y motivos
- reducción de falsos positivos semánticos donde sea comprobable
- `CLAUDE.md` actualizado
- resumen final con qué cambió y cómo validarlo
```

---

# PASO 7 — Endurecer el sistema de sinónimos y aprendizaje

> **Estado parcial (sesión 6 ya aplicó las mejoras estructurales).**
> `SynonymStore` tiene ya `status`, `times_used/confirmed/corrected`,
> `first_seen_at`, `last_confirmed_at`, `trust_score()` y ascenso/
> degradación automáticos cuando se reescribe el mismo sinónimo. El
> matcher ya usa `trust_score` como feature en vez de dar 1.00 por
> defecto. Lo que **queda** de este paso es: enganchar las acciones de
> la UI (aceptar match, corregir match) a `mark_confirmed` y
> `mark_corrected` para que los contadores reflejen la realidad del
> operador, y exponer esas acciones en `web/api.php` / `app.js`.

## Objetivo
Hacer que los sinónimos aprendidos no valgan todos lo mismo y que la corrección humana alimente el sistema de forma segura.

## Qué debe salir de este paso
- Estados de sinónimo (hecho).
- Metadatos de fiabilidad (hecho).
- Integración con revisión/corrección (**pendiente** — endpoints + UI).

## Criterio de terminado
Este paso está terminado solo si un sinónimo nuevo o dudoso ya no puede competir como uno manualmente confirmado y si las correcciones humanas quedan aprovechables.

## Prompt para Claude Code

```text
Trabaja sobre este repo y refuerza el sistema de sinónimos para que deje de ser esencialmente binario. Implementa cambios reales, mantén compatibilidad y actualiza CLAUDE.md en el mismo turno.

CONTEXTO
VeraBuy Traductor mantiene un diccionario persistente de sinónimos en `src/sinonimos.py`, pero operativamente los sinónimos pueden estar provocando matches demasiado confiados. Quiero que el sistema refleje mejor la fiabilidad real de cada sinónimo y que las correcciones humanas sirvan para entrenarlo con más seguridad.

OBJETIVO
Evolucionar el sistema de sinónimos para que cada mapping tenga estado, trazabilidad y peso de confianza acorde a su grado de confirmación.

REQUISITOS
1. Revisa el diseño actual de `src/sinonimos.py` y mantén compatibilidad con datos existentes.
2. Añade, si el almacenamiento actual lo permite, metadatos como:
   - status
   - source
   - provider_key
   - species
   - size
   - origin
   - times_used
   - times_confirmed
   - times_corrected
   - last_confirmed_at
3. Si no todos los metadatos pueden backfillearse, deja defaults razonables.
4. Haz que el matcher pueda distinguir entre:
   - sinónimo manual confirmado
   - sinónimo aprendido confirmado
   - sinónimo en prueba
   - sinónimo ambiguo o rechazado
5. Evita que un sinónimo débil dé confianza máxima automática.
6. Si existe o puedes añadir una vía de corrección humana en el flujo actual, conecta esa corrección para enriquecer o degradar el sinónimo correspondiente.
7. No rompas el uso actual de sinónimos ni la UI existente.
8. Documenta en `CLAUDE.md`:
   - nuevo modelo de sinónimos
   - estados posibles
   - impacto en matching
   - cómo se alimentan desde revisión humana

ENTREGABLES
- sistema de sinónimos ampliado
- compatibilidad con datos actuales
- integración útil con matcher
- `CLAUDE.md` actualizado
- resumen final con cambios y uso esperado
```

---

# PASO 8 — Instrumentar revisión humana y feedback loop

## Objetivo
Conseguir que cada revisión manual sirva para entrenar el sistema y no se pierda como trabajo muerto.

## Qué debe salir de este paso
- Registro de correcciones humanas.
- Hook para reinyectar aprendizajes.
- Historial útil para análisis.

## Criterio de terminado
Este paso está terminado solo si una corrección manual deja rastro estructurado que luego pueda usarse para mejorar matching, sinónimos o parsers.

## Prompt para Claude Code

```text
Trabaja sobre este repo y añade una base real de feedback loop desde la revisión humana. No me des solo ideas: implementa los cambios posibles y actualiza CLAUDE.md en el mismo turno.

CONTEXTO
VeraBuy Traductor ya marca líneas a revisar y tiene historial, sinónimos y matcher. Pero para subir hacia una automatización alta necesito que las correcciones humanas de producción se conviertan en datos reutilizables para mejorar el sistema.

OBJETIVO
Registrar de forma estructurada las correcciones humanas relevantes y dejar conectado ese feedback con el aprendizaje del sistema.

REQUISITOS
1. Revisa si `src/historial.py`, la UI o la API web ya guardan suficiente información de revisión. Reutiliza lo que exista.
2. Implementa una forma estructurada de guardar, al menos:
   - línea original procesada
   - propuesta del sistema
   - corrección humana
   - proveedor
   - fecha
   - motivo o tipo de corrección si puede inferirse
3. Prioriza especialmente correcciones de:
   - artículo ERP
   - sinónimo
   - variety
   - size
   - origin
4. Si no existe aún una UI de corrección completa, deja al menos la estructura y helpers listos para integrarla luego.
5. Si es razonable, crea una utilidad que convierta ciertas correcciones en:
   - actualización de sinónimo
   - veto de un match
   - aumento/disminución de fiabilidad
6. No rompas el flujo batch/web actual.
7. Documenta en `CLAUDE.md`:
   - qué feedback se guarda
   - dónde se guarda
   - cómo se aprovecha después

ENTREGABLES
- almacenamiento estructurado de correcciones
- base de feedback loop implementada
- documentación en `CLAUDE.md`
- resumen final con alcance real y próximos usos
```

---

# PASO 9 — Shadow mode con producción real

## Objetivo
Probar el sistema con facturas reales en paralelo a la revisión humana, sin tomar decisiones automáticas irreversibles todavía.

## Qué debe salir de este paso
- Modo sombra explícito.
- Comparación propuesta vs decisión final humana.
- Dataset real de producción para seguir afinando.

## Criterio de terminado
Este paso está terminado solo si puedes usar el sistema en operación real sin autopost ciego y con trazabilidad de qué habría decidido el sistema.

## Prompt para Claude Code

```text
Trabaja sobre este repo y prepara un modo sombra seguro para usar el sistema con facturas reales mientras seguimos aprendiendo. Implementa cambios reales y actualiza CLAUDE.md en el mismo turno.

CONTEXTO
VeraBuy Traductor ya procesa facturas y marca revisión, pero el objetivo es acercarse a una automatización alta sin disparar falsos positivos. Quiero un shadow mode donde el sistema proponga y se compare con la decisión humana real antes de automatizar más.

OBJETIVO
Introducir un modo sombra explícito y trazable para producción real, donde el sistema genere propuestas completas pero no se consideren automáticamente verdad operativa salvo en carriles seguros que se definan más adelante.

REQUISITOS
1. Implementa una noción clara de `shadow_mode` o equivalente, configurable y compatible con CLI/web si es posible.
2. En este modo, el sistema debe guardar o exponer:
   - propuesta del sistema
   - señales de confianza
   - si habría autoaprobado o no
   - resultado/corrección humana final cuando esté disponible
3. No automatices escritura irreversible en ERP ni acciones externas.
4. Asegúrate de que este modo es útil para análisis posterior:
   - tasa de acierto en producción real
   - top errores reales
   - evolución por proveedor
5. Si no puedes integrar todo de una vez, deja la infraestructura básica y documenta cómo usarla.
6. Actualiza `CLAUDE.md` con:
   - qué es shadow mode
   - cómo activarlo
   - qué guarda
   - cómo ayuda a seguir mejorando fiabilidad

ENTREGABLES
- shadow mode implementado o preparado de forma robusta
- trazabilidad útil de propuestas vs resultado humano
- `CLAUDE.md` actualizado
- resumen final con uso y límites
```

---

# PASO 10 — Definir autoaprobación por carriles seguros

## Objetivo
Maximizar automatización sin subir errores, aprobando solo los casos realmente sólidos.

## Qué debe salir de este paso
- Reglas de autoaprobación claras.
- Carriles: autoaprobar / revisión rápida / revisión completa.
- Señales consistentes para UI y reporting.

## Criterio de terminado
Este paso está terminado solo si existe un criterio técnico visible de qué casos pasan solos y cuáles no.

## Prompt para Claude Code

```text
Trabaja sobre este repo y define una política técnica de automatización por carriles seguros. Implementa cambios reales y actualiza CLAUDE.md en el mismo turno.

CONTEXTO
VeraBuy Traductor ya dispone de señales como match_confidence, ocr_confidence, validation_errors, anomalías de precio y estados como ok / sin_match / sin_parser / pendiente. Quiero convertir esto en una política práctica de autoaprobación segura para maximizar automatización sin disparar errores silenciosos.

OBJETIVO
Implementar una clasificación operativa de resultados en al menos tres carriles:
- autoaprobar
- revisión rápida
- revisión completa

REQUISITOS
1. Define reglas técnicas claras y trazables para cada carril.
2. El carril autoaprobar debe exigir evidencia fuerte, por ejemplo:
   - extracción fiable
   - parser específico exitoso
   - buen encaje estructural
   - margen suficiente frente a candidatos alternativos
   - sin validaciones graves
   - sin precio anómalo fuerte
3. Revisión rápida debe cubrir casos razonablemente buenos pero no totalmente sólidos.
4. Revisión completa debe capturar `sin_parser`, `sin_match`, OCR malo, ambigüedad fuerte y contradicciones relevantes.
5. No conviertas el sistema en una caja negra; debe ser explicable por qué una línea cae en cada carril.
6. Si ya existe `needs_review`, reutilízalo y amplíalo con compatibilidad.
7. Si procede, añade señales a la UI para ver el carril asignado.
8. Actualiza `CLAUDE.md` con:
   - criterios de carriles
   - campos o flags añadidos
   - cómo usar esta política operativamente

ENTREGABLES
- carriles implementados
- lógica de clasificación clara
- integración razonable con serialización/UI
- `CLAUDE.md` actualizado
- resumen final con cómo validar y ajustar thresholds
```

---

# PASO 11 — Crear dashboard operativo de progreso hacia el 99%

## Objetivo
Poder ver de un vistazo cuánto falta y dónde se está perdiendo fiabilidad y automatización.

## Qué debe salir de este paso
- Un dashboard simple, aunque sea en JSON/CSV + tabla resumen.
- Tendencias por proveedor y por familia de error.
- Seguimiento de autoaprobación.

## Criterio de terminado
Este paso está terminado solo si puedes revisar rápidamente qué ha mejorado, qué sigue mal y dónde conviene invertir tiempo.

## Prompt para Claude Code

```text
Trabaja sobre este repo y crea una capa de reporting operativo que permita seguir el avance real del sistema hacia una automatización alta y una fiabilidad cercana al 99%. Implementa cambios reales y actualiza CLAUDE.md en el mismo turno.

CONTEXTO
Después de introducir benchmark, golden set, clasificación de errores, mejoras de parser/matcher y carriles de automatización, necesito una forma clara de seguir el progreso sin leer logs sueltos.

OBJETIVO
Crear un dashboard operativo o al menos un reporte consolidado que muestre el estado del sistema por proveedor, por familia de error y a nivel global.

REQUISITOS
1. Genera una salida consolidada reutilizable, en JSON y si es razonable también CSV o tabla terminal.
2. Debe incluir al menos:
   - proveedores OK / TOTALES_MAL / NO_PARSEA u otras categorías vigentes
   - error family dominante
   - parse accuracy disponible
   - ERP link accuracy disponible
   - needs_review rate
   - autoapprove rate
   - top proveedores problemáticos
3. Si hay golden set o shadow mode, intégralos en el reporte.
4. No hace falta un frontend complejo; puede ser tooling CLI bien hecho.
5. Si la UI web actual puede mostrar algo útil sin gran refactor, añade una vista o bloque simple, pero solo si compensa.
6. Actualiza `CLAUDE.md` con el nuevo reporte y cómo usarlo.

ENTREGABLES
- dashboard/reporte operativo implementado
- salida clara y reutilizable
- `CLAUDE.md` actualizado
- resumen final con comandos y lectura recomendada
```

---

# PASO 12 — Mantenimiento continuo y disciplina del repo

## Objetivo
Evitar que el proyecto vuelva a degradarse y que las mejoras se pierdan por falta de rutina.

## Qué debe salir de este paso
- Checklist operativo recurrente.
- Scripts o comandos fáciles de usar.
- Documentación clara dentro del repo.

## Criterio de terminado
Este paso está terminado solo si el proyecto queda preparado para mejora continua sin depender de memoria personal.

## Prompt para Claude Code

```text
Trabaja sobre este repo y deja institucionalizado un flujo de mantenimiento continuo para que la fiabilidad siga subiendo sin depender de recordar pasos manuales. Implementa cambios reales donde tenga sentido y actualiza CLAUDE.md en el mismo turno.

CONTEXTO
VeraBuy Traductor ya tiene una guía operativa potente en CLAUDE.md, pero el proyecto necesita disciplina de mejora continua: benchmark, revisión de regresión, promoción/degradación de sinónimos, incorporación de nuevas muestras y priorización de fallos.

OBJETIVO
Dejar definido dentro del propio repo un flujo recurrente de mantenimiento y mejora continua, con comandos, checklist y criterios claros.

REQUISITOS
1. Añade a la documentación del proyecto una checklist operativa de mantenimiento continuo.
2. Incluye como mínimo rutinas de:
   - benchmark de regresión
   - incorporación de nuevas facturas al corpus
   - actualización del golden set
   - revisión de top proveedores problemáticos
   - revisión de sinónimos confirmados/problemáticos
   - revisión de autoaprobación vs revisión manual
3. Si procede, crea scripts auxiliares o comandos wrapper para facilitar estas rutinas.
4. No añadas burocracia inútil; todo debe ser realmente accionable.
5. Actualiza `CLAUDE.md` con:
   - checklist recurrente
   - nuevos comandos si los hubiera
   - criterios para decidir en qué invertir el siguiente bloque de trabajo

ENTREGABLES
- mantenimiento continuo documentado
- tooling auxiliar si compensa
- `CLAUDE.md` actualizado
- resumen final con el flujo recomendado
```

---

# Orden recomendado si no sabes por dónde seguir

Tras las sesiones 5 y 6 parte del trabajo de los pasos 6 y 7 ya está
hecho estructuralmente. El orden efectivo aconsejado hoy es:

1. **Paso 1 (consolidar)** — acotar `tools/evaluate_all.py` con las
   métricas nuevas (`ambiguous_match`, `link_confidence`,
   `extraction_source`, autoapprove_rate). Es requisito para medir
   cualquier mejora posterior.
2. **Paso 3** — aplicar la taxonomía E1..E10 sobre la salida del paso 1
   y generar backlog priorizado.
3. **Paso 4** — atacar los ~30 proveedores `NO_PARSEA` restantes
   usando el backlog del paso 3, priorizando patrones reutilizables.
4. **Paso 2** — golden set (se puede hacer antes si quieres medir la
   *accuracy real* en vez de *pass_ratio* antes de ponerte con el 4).
5. **Paso 5** — TOTALES_MAL (21 proveedores).
6. **Paso 7 (cerrar)** — enchufar `mark_confirmed`/`mark_corrected` a
   la UI/API para que el operador entrene los sinónimos en producción.
7. **Paso 6 (auditar)** — con golden set ya montado, auditar empíricamente
   el nuevo matcher y ajustar thresholds.
8. **Paso 8** — feedback loop estructurado.
9. **Paso 9** — shadow mode.
10. **Paso 10** — autoaprobación por carriles.
11. **Paso 11** — dashboard de progreso.
12. **Paso 12** — mantenimiento continuo.

## Regla de oro final

No consideres una mejora “hecha” si no deja:
- código real en el repo,
- validación mínima,
- compatibilidad razonable,
- y `CLAUDE.md` actualizado dentro del mismo turno.
