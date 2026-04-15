# VeraBuy Traductor — Checklist operativa de avance

Usa este archivo como tablero rápido de seguimiento.
La idea es complementar `verabuy_roadmap_y_prompts.md` con una vista corta de:
- qué queda pendiente,
- qué está en curso,
- qué está bloqueado,
- y qué ya está cerrado.

> **Regla de sincronización**: cuando abras sesión tras días sin tocarlo,
> primero relee el historial de sesiones de `CLAUDE.md` y contrasta con
> este archivo. Si hay desfase, **actualiza primero el checklist y el
> roadmap** antes de ejecutar ningún prompt nuevo — así evitas relanzar
> trabajo ya hecho.

## Módulos clave en el estado actual

| Módulo | Qué hace | Sesión |
|---|---|---|
| `src/extraction.py` | Router de extracción + `ExtractionResult` + `extract_rows_by_coords` | 5 |
| `src/pdf.py` | Wrapper delgado con API retrocompatible + `get_last_extraction` | 5 |
| `src/matcher.py` | Scoring por evidencia + vetos duros + `Candidate` + margen | 6 |
| `src/sinonimos.py` | `status`, `trust_score`, contadores, `provider_article_usage`, `mark_confirmed/corrected` | 6 |
| `src/models.py` | `InvoiceLine` + `link_confidence` + `extraction_source` + `match_reasons`/`top_candidates`... | 5-6 |
| `tools/evaluate_all.py` | Benchmark masivo (pendiente consolidar métricas nuevas — Paso 1) | 3 |
| `tools/auto_learn_parsers.py` | validate/register/evaluate por proveedor | 2 |

## Leyenda de estado
- [ ] Pendiente
- [-] En curso
- [x] Hecho
- [!] Bloqueado / revisar

---

## Objetivo general
Subir progresivamente la fiabilidad del sistema hacia un nivel de automatización segura muy alto, priorizando:
1. reducción de `NO_PARSEA`,
2. reducción de falsos matches al ERP,
3. mejora del confidence scoring,
4. aumento del porcentaje de facturas/líneas autoaprobables,
5. mantenimiento continuo de parsers, sinónimos y validación.

---

## Estado rápido actual
_Cifras tomadas del historial de sesiones de `CLAUDE.md` (sesión 6, abril 2026)._

- [x] Base de parsers funcionales ampliada (~40 parsers, 0 stubs pendientes)
- [x] Carpeta de test por proveedor montada con 5 facturas nuevas + 2 antiguas
- [x] Ejecutar prompt de mejora de OCR / routing / extracción **(sesión 5)**
  - nuevo `src/extraction.py` con triage nativo/scan, OCRmyPDF+Tesseract
    principal, EasyOCR fallback, `ExtractionResult` con source/confidence/
    ocr_engine/degraded. `src/pdf.py` queda como wrapper delgado.
- [x] Ejecutar prompt de mejora de confidence scoring / matching ERP **(sesión 6)**
  - scoring por evidencia (features + vetos duros + margen adaptativo)
  - penalty `foreign_brand`, estado `ambiguous_match`
  - `InvoiceLine` + `link_confidence`/`candidate_margin`/`match_reasons`/
    `match_penalties`/`top_candidates`
  - `SynonymStore` + `status`/`trust_score`/contadores/`provider_article_usage`
- [-] Congelar baseline comparativa antes/después
  - `tools/evaluate_all.py` existe; falta consolidar con métricas nuevas
    (ambiguous, link_confidence, extraction_source, autoapprove_rate).
- [ ] Crear golden set manualmente validado
- [ ] Montar ranking de errores por impacto con taxonomía E1..E10
- [ ] Pasar a shadow mode con facturas reales
- [ ] Crear ciclo continuo de aprendizaje desde revisión humana
  - `mark_confirmed`/`mark_corrected` ya existen en `SynonymStore`;
    falta engancharlos a UI/API.

### KPIs objetivos hoy (baseline)
- OK: **30/82** proveedores (parsed_any + totals_ok)
- TOTALES_MAL: **21/82**
- NO_PARSEA: **30/82**
- NO_DETECTADO: **1/82** (PONDEROSA, reshuffle del reporte)
- Rama OCR real disponible: **OCRmyPDF+Tesseract** + EasyOCR fallback
- Matching: **scoring por evidencia** con vetos duros y trazabilidad

---

## Tablero maestro

## FASE 1 — Estabilizar extracción y benchmark
- [x] Ejecutar prompt 1: OCR / routing / extracción / fiabilidad general (sesión 5)
- [x] Verificar que no rompe procesamiento individual
- [x] Verificar que no rompe batch
- [x] Verificar que no rompe UI web
- [x] Confirmar que `CLAUDE.md` se actualizó correctamente
- [x] Guardar resumen técnico de cambios (commit `650e0d7`)
- [-] Ejecutar benchmark masivo post-cambios (se ha corrido `evaluate_all.py`
  en sesiones 5–6; falta consolidar con métricas nuevas ambiguous/link/
  extraction_source/autoapprove)
- [ ] Guardar informe comparativo antes/después (JSON/CSV versionado)

### Criterio de cierre de fase
- prompt 1 aplicado,
- benchmark ejecutado,
- sin regresiones graves,
- documentación actualizada.

### Delta pendiente para cerrar la fase
Consolidar `tools/evaluate_all.py` para que emita las métricas nuevas
(ambiguous_match, link_confidence, extraction_source, autoapprove_rate,
ranking de match_penalties). Este es el Paso 1 del roadmap en su
versión acotada — un solo turno de trabajo.

---

## FASE 2 — Medición real de calidad
- [ ] Definir KPIs oficiales del proyecto
- [ ] Separar métricas de parseo y métricas de linking ERP
- [ ] Crear golden set de alta calidad revisado manualmente
- [ ] Etiquetar al menos los proveedores de mayor volumen
- [ ] Medir accuracy real por línea
- [ ] Medir accuracy real de link ERP
- [ ] Medir tasa de autoaprobación segura
- [ ] Medir tasa de revisión manual necesaria

### Criterio de cierre de fase
- existe dataset manual de referencia,
- existen métricas comparables en el tiempo,
- ya no se depende solo de `parsed_any` o `totals_ok`.

---

## FASE 3 — Mejorar matching y confidence scoring
- [x] Ejecutar prompt 2: scoring / evidencia / candidate margin / ambigüedad (sesión 6)
- [x] Verificar compatibilidad con flujo actual
- [x] Verificar serialización de nuevos campos (link_confidence,
  candidate_margin, candidate_count, match_reasons, match_penalties,
  top_candidates)
- [x] Confirmar señales nuevas en UI (stat "Ambiguas", clase `row-ambiguous`,
  tooltip por fila con reasons+penalties+margin)
- [x] Confirmar que `CLAUDE.md` quedó actualizado
- [ ] **Medir impacto** del nuevo scoring en falsos positivos
  _(requiere golden set — Fase 2)_
- [ ] **Medir reducción** de matches incorrectos por sinónimos
  _(requiere golden set o shadow mode)_

### Criterio de cierre de fase
- el sistema distingue mejor entre línea bien leída y artículo mal vinculado,
- baja el falso positivo silencioso,
- sube la calidad de revisión.

### Delta pendiente para cerrar la fase
La parte estructural ya está hecha. Lo que queda es **empírico**: sin
golden set no podemos cuantificar la mejora. Esta fase se cierra cuando
Fase 2 esté operativa y se haya corrido una auditoría con el Paso 6
acotado a auditoría/afinado.

---

## FASE 4 — Taxonomía de errores
- [ ] Crear categorías oficiales de error
- [ ] Etiquetar errores históricos y nuevos con esa taxonomía
- [ ] Separar problemas de OCR, parser, layout, matching y sinónimos
- [ ] Crear ranking de causas recurrentes
- [ ] Priorizar backlog por tipo de fallo y no solo por proveedor

### Categorías recomendadas
- [ ] E1_PARSE_ZERO
- [ ] E2_PARSE_PARTIAL
- [ ] E3_LAYOUT_COORDS
- [ ] E4_OCR_BAD
- [ ] E5_TOTAL_HEADER
- [ ] E6_MATCH_WRONG
- [ ] E7_SYNONYM_DRIFT
- [ ] E8_AMBIGUOUS_LINK
- [ ] E9_VALIDATION_FAIL
- [ ] E10_PROVIDER_COLLISION

### Criterio de cierre de fase
- cada incidencia relevante cae en una categoría útil,
- el backlog ya se puede atacar industrialmente.

---

## FASE 5 — Ataque industrial a NO_PARSEA
- [ ] Sacar ranking actualizado de proveedores `NO_PARSEA`
- [ ] Ordenarlos por impacto real
- [ ] Revisar primero los 10 más importantes
- [ ] Reutilizar plantillas/layouts cuando sea posible
- [ ] Extender uso de coordenadas a layouts complejos
- [ ] Reducir dependencia del rescue
- [ ] Re-ejecutar benchmark tras cada bloque de mejoras

### Criterio de cierre de fase
- baja clara del bloque `NO_PARSEA`,
- menos rescates,
- más parsers robustos por layout reutilizable.

---

## FASE 6 — TOTALES_MAL y validación estructural
- [ ] Revisar extracción de `header.total`
- [ ] Corregir parsers donde el total sea cosméticamente incorrecto
- [ ] Mejorar coherencia `sum(lines) vs header.total`
- [ ] Revisar tolerancias si hace falta
- [ ] Confirmar que no se introducen falsos errores

### Criterio de cierre de fase
- menos casos `TOTALES_MAL`,
- mejor confianza global,
- menos ruido en validación.

---

## FASE 7 — Sinónimos y aprendizaje controlado
- [x] Añadir estados de fiabilidad a sinónimos (status: manual_confirmado,
  aprendido_confirmado, aprendido_en_prueba, ambiguo, rechazado)
- [x] Distinguir sinónimos confirmados de sinónimos en prueba
  (trust_score 0–1 por status + contadores)
- [x] Desactivar o penalizar sinónimos conflictivos (degradación automática
  al reescribir el mismo key a un artículo distinto; rechazado tras 2
  correcciones)
- [x] Añadir trazabilidad por proveedor / especie / talla / origen
  (fields ya en el entry JSON)
- [ ] **Registrar correcciones humanas útiles** desde la UI
  _(API `mark_confirmed`/`mark_corrected` ya existe; falta endpoint
  web/api.php y llamada desde app.js cuando el operador confirma o cambia)_
- [ ] Medir cuántos errores provienen de sinónimos
  _(requiere golden set o shadow mode)_

### Criterio de cierre de fase
- los sinónimos dejan de ser una fuente importante de falsos matches,
- el sistema aprende sin introducir ruido.

### Delta pendiente para cerrar la fase
Enganchar las acciones del operador (aceptar match / cambiar artículo) a
las APIs `mark_confirmed` y `mark_corrected` del `SynonymStore`. Trabajo
backend + frontend pequeño, un solo turno.

---

## FASE 8 — Históricos y prior por proveedor
- [x] Añadir señal histórica por proveedor al matching
  (`SynonymStore.provider_article_usage()` + feature `provider_history(N)`
  en el scorer — sesión 6)
- [x] Reforzar artículos frecuentes correctamente usados (+0.10 si ≥3 usos,
  +0.05 si ≥1)
- [x] Penalizar artículos improbables para ese proveedor (implícito: sin
  prior histórico no hay bonus, y la penalty `foreign_brand` resta −0.25
  cuando el nombre del artículo tiene marca de OTRO proveedor)
- [ ] Medir mejora frente a candidatos ambiguos
  _(requiere golden set o shadow mode)_

### Criterio de cierre de fase
- mejor desempate entre candidatos parecidos,
- menos errores de linking semántico.

---

## FASE 9 — Revisión humana eficiente
- [x] Mejorar señales de "a revisar"
  - stat cards: "A Revisar", "Ambiguas", "Extracción OCR/Mixta"
  - clases CSS: `row-sin-parser`, `row-rescue`, `row-ambiguous`,
    `row-sin-match`, `row-has-error`, `row-low-conf`
- [x] Diferenciar extracción dudosa de linking dudoso
  (`extraction_confidence` vs `link_confidence` separados desde sesión 6;
  `extraction_source` distingue native/mixed/ocr/rescue)
- [x] Mostrar razones del match / penalizaciones
  (tooltip por `<tr>` con `match_reasons` + `match_penalties` + `candidate_margin`)
- [x] Añadir visibilidad de candidatos ambiguos si aplica
  (`top_candidates` serializado; estado `ambiguous_match` + fila amarilla)
- [ ] Reducir tiempo de revisión manual por factura
  _(empírico — medir cuando haya operación real + shadow mode)_

### Criterio de cierre de fase
- revisar es más rápido,
- revisar sirve también para entrenar el sistema.

### Delta pendiente para cerrar la fase
Que la UI de revisión use las acciones en Fase 7 (aceptar/corregir) para
alimentar `SynonymStore.mark_confirmed`/`mark_corrected`. Y medir tiempos
reales de revisión, que solo se puede hacer en producción real.

---

## FASE 10 — Shadow mode con producción real
- [ ] Procesar facturas reales en modo sombra
- [ ] Comparar propuesta del sistema vs decisión humana
- [ ] Capturar nuevos formatos y fallos reales
- [ ] Convertir correcciones en dataset útil
- [ ] Reinyectar aprendizaje al sistema

### Criterio de cierre de fase
- el sistema mejora con producción real sin riesgo operativo.

---

## FASE 11 — Automatización segura por niveles
- [ ] Definir reglas de autoaprobación
- [ ] Definir reglas de revisión rápida
- [ ] Definir reglas de revisión completa
- [ ] Medir ratio de líneas en cada carril
- [ ] Subir el % autoaprobado sin subir errores

### Carriles sugeridos
- [ ] Carril 1 — Autoaprobar
- [ ] Carril 2 — Revisión rápida
- [ ] Carril 3 — Revisión completa

### Criterio de cierre de fase
- automatización creciente,
- errores contenidos,
- revisión enfocada donde realmente aporta valor.

---

## FASE 12 — Mantenimiento continuo
- [ ] Ritual semanal de benchmark
- [ ] Ritual semanal de revisión de incidencias
- [ ] Ritual quincenal de mejoras estructurales
- [ ] Ritual mensual de métricas globales
- [ ] Actualización continua de `CLAUDE.md`
- [ ] Limpieza de backlog resuelto / obsoleto

---

## Próximo bloque recomendado
Marca uno como activo para no dispersarte. La lista está re-priorizada
tras las sesiones 5–6 (antes el prompt 1 y 2 eran los siguientes; ya no).

- [-] **1. Consolidar `tools/evaluate_all.py` con métricas nuevas**
      (ambiguous_match, link_confidence, extraction_source, autoapprove_rate).
      Requisito para medir cualquier mejora siguiente. Es el Paso 1
      acotado del roadmap. **← activo**
- [ ] 2. Crear golden set manual (Paso 2)
- [ ] 3. Aplicar taxonomía E1..E10 sobre la salida del benchmark (Paso 3)
- [ ] 4. Atacar Top-10 `NO_PARSEA` guiado por la taxonomía (Paso 4)
- [ ] 5. TOTALES_MAL (Paso 5)
- [ ] 6. Enganchar `mark_confirmed`/`mark_corrected` a la UI (cierra Paso 7)
- [ ] 7. Auditar matcher con golden set (cierra Paso 6)
- [ ] 8. Shadow mode (Paso 9)

---

## Registro rápido de avances

### Último bloque cerrado
- Fecha: 2026-04-15
- Paso: Fase 3 (matching y confidence scoring) — estructural
- Qué se hizo (sesión 6, commit `42cdb64`):
  * Reescritura del matcher a scoring por evidencia (candidatos + vetos
    duros + features + margen adaptativo).
  * Penalty `foreign_brand` (−0.25) para evitar artículos de marca ajena.
  * Nuevo estado `ambiguous_match` + propagación (stats, UI, badges).
  * `InvoiceLine`: link_confidence, candidate_margin, candidate_count,
    match_reasons, match_penalties, top_candidates.
  * `SynonymStore`: status, contadores, trust_score(),
    provider_article_usage, mark_confirmed/corrected.
  * `validate.py` capa también `link_confidence` con errors.
  * UI: stat "Ambiguas", `row-ambiguous`, tooltip con motivos.
- Resultado: OK 30/82 sin regresión funcional; MYSTIC deja de asignar
  a `ROSA BRIGHTON 50CM 25U FIORENTINA` (marca ajena) y elige el
  genérico correcto.
- Riesgos / pendientes: el 2º candidato suele ser la misma variedad
  con otra marca — el margen adaptativo 0.05 en dominantes resuelve la
  mayoría, pero si aparecen colisiones añadir feature
  `siblings_same_variety`. Falta empírica (golden set) para cerrar.

### Penúltimo bloque cerrado (sesión 5, commit `650e0d7`)
- Fecha: 2026-04-15
- Paso: Fase 1 (extracción) — estructural
- Qué se hizo:
  * Nuevo `src/extraction.py` con router diagnóstico (triage nativo/scan,
    OCRmyPDF+Tesseract principal, EasyOCR fallback).
  * `src/pdf.py` queda como wrapper; API pública intacta; nuevo
    `get_last_extraction()`.
  * `InvoiceLine` gana `extraction_confidence` y `extraction_source`.
  * Rescue marcado como `extraction_source='rescue'` con conf 0.60.
  * UI: stat card "Extracción OCR/Mixta" con motor en tooltip; clase
    `row-rescue`.
- Resultado: OK 27→30 (+3), NO_PARSEA 36→31 (−5). Real OCR con OCRmyPDF
  funciona sobre escaneados (p. ej. APOSENTOS) con calidad 0.85+.

### Bloque actual
- Fecha: _(en curso)_
- Paso: Paso 1 consolidado — benchmark formal con métricas nuevas
- Objetivo: dejar `tools/evaluate_all.py` emitiendo JSON/CSV con
  ambiguous, link_confidence, extraction_source, autoapprove_rate y
  ranking de `match_penalties`. Input para Paso 3 (taxonomía) y Paso 2
  (golden set).
- Estado: pendiente
- Nota rápida: no reescribir; solo extender la serialización del script
  actual con los campos que ya existen en `_serialize_line`.

### Próximo bloque
- Paso: Paso 3 — taxonomía E1..E10 sobre la salida del Paso 1
- Motivo: convierte el benchmark en backlog accionable por familia de
  error en vez de por proveedor.
- Dependencias: Paso 1 consolidado (este bloque actual).

---

## Regla operativa personal
No abrir demasiados frentes a la vez.
Cada vez que cierres un bloque:
1. marca estado,
2. deja nota breve,
3. actualiza `CLAUDE.md` si tocaste código,
4. re-ejecuta la validación mínima necesaria.

---

## Meta final
No perseguir “99%” como número abstracto.
Perseguir simultáneamente:
- altísima precisión de parseo,
- altísima precisión de linking ERP,
- alta tasa de autoaprobación segura,
- mínima revisión manual innecesaria,
- aprendizaje continuo desde producción real.
