# VeraBuy Traductor — Checklist operativa de avance

Usa este archivo como tablero rápido de seguimiento.
La idea es complementar [`roadmap.md`](roadmap.md) con una vista corta de:
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
- [x] Crear golden set manualmente validado
  - `tools/golden_bootstrap.py` + `tools/evaluate_golden.py` (sesión 9d)
  - 5 anotaciones draft en `golden/` — pendiente revisión manual
- [x] Montar ranking de errores por impacto con taxonomía E1..E10
  - `tools/classify_errors.py` implementado (sesión 9)
  - `auto_learn_taxonomy.json` generado con backlog priorizado
- [ ] Pasar a shadow mode con facturas reales
- [ ] Crear ciclo continuo de aprendizaje desde revisión humana
  - `mark_confirmed`/`mark_corrected` ya existen en `SynonymStore`;
    falta engancharlos a UI/API.

### KPIs actuales (sesión 10q, `tools/evaluate_all.py`)
- Autoapprove **94.0%** (estable tras reimport catálogo).
- Catálogo: **44,751 artículos** (+2,467 nuevos).
- Golden: **980/997 (98.3%)** — 17 mismatches son mejoras
  (artículos branded nuevos preferidos sobre genéricos).
- Sinónimos: 3311/3337 migrados a `id_erp` (estable entre
  reimports). 24 invalidados (artículos removidos del catálogo).
- Buckets: OK 79 · NO_PARSEA 3 · TOTALES_MAL 0 · NO_DETECTADO 1
- Top penalties: `weak_synonym` 212 · `variety_no_overlap` 176 ·
  `foreign_brand` 170 · `low_evidence` 111 · `tie_top2_margin` 75

### KPIs baseline (sesión 9q, `tools/evaluate_all.py`)
- Líneas totales procesadas: **3309** (+12 vs 9p)
- Líneas `ok`: **2795** · `ambiguous_match`: **228** · `autoapprovable`: **2654**
- **autoapprove_rate: 87.8%** de las líneas linkables (+1.1pp vs 9p)
- **Golden set: 100%** parse + link accuracy (88/88 líneas reviewed)
  + 3 drafts pendientes (timana, benchmark, florifrut)
- Buckets: OK 71 · NO_PARSEA 7 · TOTALES_MAL 3 · NO_DETECTADO 1
- Top-5 penalties globales:
  1. `weak_synonym` 2673
  2. `variety_no_overlap` 245
  3. `foreign_brand` 191
  4. `low_evidence` 152
  5. `tie_top2_margin` 125
- Feedback loop operativo: golden → review → apply → sinónimos confirmados
- Rama OCR real disponible: **OCRmyPDF+Tesseract** + EasyOCR fallback
- Matching: **scoring por evidencia** con vetos duros y trazabilidad
- Top-5 penalties globales:
  1. `weak_synonym` 1841 — sinónimos en prueba con trust bajo
  2. `tie_top2_margin` 521 — empates prácticos entre candidatos
  3. `low_evidence` 282 — ganador < 0.70 de score
  4. `variety_no_overlap` 262 — variedad no coincide con el ganador
  5. `foreign_brand` 216 — marca ajena al proveedor actual
- **Taxonomía E1..E10 aplicada** (sesión 9): E7_SYNONYM_DRIFT domina
  (67/82 proveedores), seguido de E8_AMBIGUOUS_LINK (61) y
  E6_MATCH_WRONG (48). Ver `auto_learn_taxonomy.json`.

---

## Tablero maestro

## FASE 1 — Estabilizar extracción y benchmark
- [x] Ejecutar prompt 1: OCR / routing / extracción / fiabilidad general (sesión 5)
- [x] Verificar que no rompe procesamiento individual
- [x] Verificar que no rompe batch
- [x] Verificar que no rompe UI web
- [x] Confirmar que `CLAUDE.md` se actualizó correctamente
- [x] Guardar resumen técnico de cambios (commit `650e0d7`)
- [x] Ejecutar benchmark masivo post-cambios (sesión 8, reescrito
  `tools/evaluate_all.py` a in-process con todas las métricas nuevas)
- [x] Guardar informe comparativo antes/después
  (`auto_learn_report.json`, `auto_learn_report.csv`,
  `auto_learn_penalties_top.json`)

### Criterio de cierre de fase
- prompt 1 aplicado,
- benchmark ejecutado,
- sin regresiones graves,
- documentación actualizada.

### Baseline capturada (sesión 8)
- 2644 líneas procesadas en 82 proveedores
- 1620 `ok` · 796 `ambiguous_match` · 1476 `autoapprovable`
- **autoapprove_rate: 61.1%** de las líneas linkables
- Top penalties: `weak_synonym` (1382) · `tie_top2_margin` (533) ·
  `low_evidence` (282) · `variety_no_overlap` (262) · `foreign_brand` (216)

---

## FASE 2 — Medición real de calidad
- [x] Definir KPIs oficiales del proyecto (sesión 9d)
- [x] Separar métricas de parseo y métricas de linking ERP
- [x] Crear golden set de alta calidad revisado manualmente
  - Estructura: `golden/` con JSONs por factura
  - Bootstrap: `tools/golden_bootstrap.py`
  - Evaluador: `tools/evaluate_golden.py`
- [x] Etiquetar al menos los proveedores de mayor volumen
  - 5 anotaciones reviewed: ALEGRIA, MYSTIC, FIORENTINA, MEAFLOS, BENCHMARK
  - Revisión manual completada por el operador (17 abril 2026)
- [x] Medir accuracy real por línea (100% en golden reviewed)
- [x] Medir accuracy real de link ERP (100% en golden reviewed)
- [x] Medir tasa de autoaprobación segura (68.9% tras brand boost)
- [x] Medir tasa de revisión manual necesaria (needs_review en benchmark)

### Criterio de cierre de fase
- existe dataset manual de referencia,
- existen métricas comparables en el tiempo,
- ya no se depende solo de `parsed_any` o `totals_ok`.
- **CERRADA (17 abril 2026)**: 5 anotaciones reviewed, 100% accuracy
  en `evaluate_golden.py`. Ampliar el dataset a más proveedores es
  trabajo continuo (Fase 12).

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
- [x] Crear categorías oficiales de error (sesión 9)
- [x] Etiquetar errores históricos y nuevos con esa taxonomía
- [x] Separar problemas de OCR, parser, layout, matching y sinónimos
- [x] Crear ranking de causas recurrentes
- [x] Priorizar backlog por tipo de fallo y no solo por proveedor

### Categorías implementadas (sesión 9)
- [x] E1_PARSE_ZERO (31 proveedores, 3 HIGH)
- [x] E2_PARSE_PARTIAL (21 proveedores, 10 HIGH)
- [x] E3_LAYOUT_COORDS (26 proveedores, 13 HIGH)
- [x] E4_OCR_BAD (0 proveedores — OCRmyPDF resuelve bien)
- [x] E5_TOTAL_HEADER (47 proveedores, 0 HIGH, cosmético)
- [x] E6_MATCH_WRONG (48 proveedores, 32 HIGH)
- [x] E7_SYNONYM_DRIFT (67 proveedores, 45 HIGH — causa raíz dominante)
- [x] E8_AMBIGUOUS_LINK (61 proveedores, 45 HIGH)
- [x] E9_VALIDATION_FAIL (12 proveedores, 7 HIGH)
- [x] E10_PROVIDER_COLLISION (23 proveedores, 0 HIGH, informativo)

### Criterio de cierre de fase
- cada incidencia relevante cae en una categoría útil,
- el backlog ya se puede atacar industrialmente.
- **CERRADA en sesión 9**: `tools/classify_errors.py` genera
  `auto_learn_taxonomy.json` con backlog priorizado.

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
- [x] **Registrar correcciones humanas útiles** desde la UI (sesión 9e)
  - `confirm_match` → promueve sinónimo a `aprendido_confirmado`
  - `correct_match` → degrada viejo a `ambiguo`/`rechazado`, guarda nuevo
  - Botón ✓ en tabla de resultados + tab Sinónimos actualizado
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
- [x] **Infraestructura de captura** (sesión 10k):
  - `shadow_log.jsonl` en raíz, formato JSONL con entries
    `propuesta` (una por línea de factura en `handleProcess`) y
    `decision` (confirm/correct desde UI).
  - `_shadowLogProposals` + `_shadowLogDecision` en
    [`web/api.php`](../../web/api.php). Silenciosos en error.
  - [`tools/shadow_report.py`](../../tools/shadow_report.py):
    cruza ambos por `synonym_key` y produce accuracy real,
    accuracy por proveedor, top correcciones, backlog pendiente.
- [-] Procesar facturas reales en modo sombra (operación diaria)
- [-] Comparar propuesta del sistema vs decisión humana
      (automático vía shadow_report)
- [ ] Capturar nuevos formatos y fallos reales (ver backlog
      pendiente en shadow_report)
- [ ] Convertir correcciones en dataset útil (top patterns →
      fixes concretos)
- [ ] Reinyectar aprendizaje al sistema

### Criterio de cierre de fase
- el sistema mejora con producción real sin riesgo operativo.

---

## FASE 11 — Automatización segura por niveles
- [x] Definir reglas de autoaprobación (sesión 9i)
- [x] Definir reglas de revisión rápida
- [x] Definir reglas de revisión completa
- [x] Medir ratio de líneas en cada carril
- [-] Subir el % autoaprobado sin subir errores (operación continua)

### Carriles implementados (sesión 9i)
- [x] Carril `auto` — link≥0.80 + match≥0.80 + margen≥0.05 + sin errors + ext≥0.80
- [x] Carril `quick` — match ok pero no cumple todos los criterios de auto
- [x] Carril `full` — sin_match, sin_parser, rescue, OCR<0.50, ambiguo con link<0.50
- Baseline: auto=60.6%, quick=33.2%, full=6.2%

### Criterio de cierre de fase
- automatización creciente,
- errores contenidos,
- revisión enfocada donde realmente aporta valor.
- **Parcialmente cerrada**: carriles definidos y medidos. Se sigue cerrando
  a medida que sube el % auto con el uso diario.

---

## FASE 12 — Mantenimiento continuo
- [ ] Ritual semanal de benchmark
- [ ] Ritual semanal de revisión de incidencias
- [ ] Ritual quincenal de mejoras estructurales
- [ ] Ritual mensual de métricas globales
- [ ] Actualización continua de `CLAUDE.md`
- [ ] Limpieza de backlog resuelto / obsoleto

## Backlog de optimización
- [ ] **Optimizar velocidad del matcher** — actualmente ~6.5s para 43 líneas
  (match_all evalúa muchos candidatos por línea contra 42k artículos).
  Ideas: indexar artículos por variety+size, precalcular brand set,
  limitar candidatos fuzzy. No es urgente pero mejora la UX.

---

## Próximo bloque recomendado
Marca uno como activo para no dispersarte. La lista está re-priorizada
tras la sesión 8 (baseline ya capturada).

- [x] 1. Consolidar `tools/evaluate_all.py` con métricas nuevas (sesión 8)
- [x] 2. Aplicar taxonomía E1..E10 sobre la salida del benchmark (sesión 9)
- [x] 3. Atacar Top-10 `NO_PARSEA` guiado por la taxonomía (sesión 9b+9c)
      — 30→20 NO_PARSEA, +357 líneas, +3.2pp autoapprove
- [x] 4. Crear golden set manual (sesión 9d) — tooling listo, 5 drafts
- [x] 5. Revisar golden set manualmente (17 abril 2026) — 5/5 reviewed,
      100% parse + link accuracy
- [x] 6. Enganchar `mark_confirmed`/`mark_corrected` a la UI (sesión 9e)
      — botón ✓ en tabla + correct_match al cambiar artículo
- [x] 7. Auditar matcher con golden set (sesión 9g) — link accuracy 43%→93%
- [x] 8. TOTALES_MAL (sesión 9f) — 26→1, fallback central + fix campanario
- [x] 9. Brand boost (sesión 9j, commit `3855f7e`) — autoapprove 66.1%→68.9%
- [x] 10. LATIN + refinado matcher (sesión 9k) — autoapprove 68.9%→79.6%
- [x] 11. ELITE + SAYONARA (sesión 9l) — autoapprove 79.6%→80.4%
- [x] 12. DAFLOR + APOSENTOS + CANANVALLE (sesión 9m) — 80.4%→81.9%
- [x] 13. NATIVE + MILONGA + MILAGRO + refinado (sesión 9n) — 81.9%→86.8%
- [x] 14. TIMANA + ART ROSES + BENCHMARK + TESSA (sesión 9o) —
      86.8%→87.1%, NO_PARSEA ~19→13 (+101 líneas rescatadas)
- [x] 15. IWA + PREMIUM + CIRCASIA + ECOFLOR + MILONGA + MILAGRO +
      PRESTIGE (sesión 9p) — 87.1%→86.7% (dilución por +78 líneas),
      NO_PARSEA 13→10, +5 proveedores a OK, MUCHO_RESCATE vaciado
- [x] 16. IWA mixed_box + CANTIZA/MILAGRO/MILONGA + fuzzy cache +
      golden drafts (sesión 9q) — 86.7%→87.8%, NO_PARSEA 10→7,
      ambig 268→228 (reclassify), matcher ~6.5s→~5.0s para 42 líneas
- [x] 17. Fix parser BRISSAS header `Sub Total` (sesión 10f) —
      BRISSAS TOTALES_MAL → OK, TOTALES_MAL 1→0, auto 92.8% estable
- [x] 18. Auto-confirmación de sinónimos (sesión 10g) —
      `register_match_hit` + promoción ≥2 hits, weak_synonym
      1787→677 (−62%), 774 sinónimos promovidos, auto 92.8→92.9%
- [x] 19. Fixes parsers UNIQUE + CANANVALLE (sesión 10h) —
      nuevos regex proforma/sample-table, NO_PARSEA **5→3**,
      auto 92.9→93.0%, weak_synonym 677→200 (−89% total vs 10f)
- [x] 20. Normalización puntuación en variety tokens (sesión
      10i) — pre-normalize `[^A-Z0-9 ]+` en `_score_candidate`,
      variety_no_overlap 250→232, auto 93.0→93.4% (+15 líneas)
- [x] 21. Desempate cualitativo tie_top2 (sesión 10j) —
      si top1 tiene `size_exact` y top2 solo `size_close`, o
      top1 tiene `variety_full` y top2 no, marcar ok con reason
      `tiebreak_*`. ambig 161→144 (−11%), auto 93.4→93.6% (+9)
- [x] 22. **Shadow mode — infraestructura** (Fase 10, sesión 10k)
      — `shadow_log.jsonl` + hooks en api.php (process/confirm/
      correct) + `tools/shadow_report.py`.
- [x] 23. **Primer fix shadow-driven** (sesión 10l): error en
      AROMA.pdf durante lote real → fix FLORAROMA variante 2026.
- [x] 24. **Batch de 7 fixes shadow-driven** (sesión 10m): Ángel
      procesó lote real de 27 facturas y señaló errores en UI.
      Fixes: FLORAROMA, EQR, FLORSANI, GARDA, MALIMA, MYSTIC,
      LIFE. Patrón común: **box_code/label contaminando
      variety** — ahora separado a campo `label`. ~200 líneas
      nuevas recuperadas. Golden 997/997 intacto.
- [-] 25. Ciclo continuo de uso real + shadow_report semanal +
      conversión de top-N patrones en fixes. Pendiente: revisar
      parsers aún con patrón box-code-en-variety (ROSALEDA EURO,
      SAYONARA SP, APOSENTOS ILIAS, MONTEROSA EUGENIA,
      EL CAMPANARIO ZAIRA).
- [x] 26. **Cierre gap save_synonym en shadow** (sesión 10n):
      `handleSaveSynonym` ahora emite `_shadowLogDecision` con
      `proposed=0`; `shadow_report.py` separa "correcciones del
      matcher" vs "rescates sin_match" y calcula accuracy real del
      matcher excluyendo rescates del denominador.
- [x] 27. **4 fixes transversales shadow-driven Uma VIOLETA**
      (sesión 10o, autoapprove 92.6→94.1%): multi-marca por
      proveedor (`brands_by_provider`), trust_exempts en
      `variety_no_overlap`, evitar degradar sinónimos manuales en
      `match_line`, `plausible` incluye `source=='synonym'`.
      Golden 997/997 intacto.
- [x] 28. **Cierre residuales shadow (sesión 10p)**: reprocesar
      batch real validó 81/87 pendientes resueltos por 10o.
      Los 2 Tierra Verde (PINK O'HARA) requerían fix adicional
      porque el `id` de config (90038) ≠ `id_proveedor` del
      catálogo (9591). Añadidos campos `country` y
      `catalog_brands` en PROVIDERS; `_get_brands` y
      `_own_brands_norm` los leen. Parser `alegria` usa
      `pdata.get('country')` para origin. Bench 94.1→94.4%.
      Residuales: 4 altas ERP (IMAGINATION, REDIANT,
      ORNITHOGALUM WHITE STAR, DARK RAINBOW) — decisión
      operador.
- [x] 29. **Reimport catálogo + migración a id_erp (sesión 10q)**:
      catálogo ampliado a 44,751 artículos (+2,467).
      `ArticulosLoader` carga `id_erp`, `SynonymStore` guarda
      `articulo_id_erp` + método `resolve_article_id`, matcher
      re-mapea lazy tras reimport. Migración one-shot remapea
      3311 sinónimos + 994 golden por nombre del artículo.
      24 sinónimos huérfanos invalidados. Golden 98.3%
      (17 mismatches son mejoras por branded nuevos).
- [ ] 21. NO_PARSEA restantes (3): SAYONARA (OCR corrupto
      irrecuperable), CEAN GLOBAL (rosas en español, reescritura
      parser auto_cean), NATIVE BLOOMS (tropicales cortesía
      $0.0001). ROI bajo para el esfuerzo requerido.
- [ ] 22. Samples con totals_ok parcial (4-5 samples): CANTIZA,
      MILAGRO, MILONGA, ROSALEDA, TESSA, UMA FLOWERS — bucket OK
      pero ruido en validación

---

## Registro rápido de avances

### Último bloque cerrado
- Fecha: 2026-04-23
- Paso: sesión 10q — reimport catálogo + migración a id_erp estable
- Qué se hizo:
  * Reimport del dump `articulos (5).sql` a MySQL
    `traductor-verabuy` → catálogo pasa de 42,284 a **44,751
    artículos** (+2,467 nuevos).
  * Los `id` autoincrement se reasignaron en el nuevo dump →
    sinónimos y golden apuntaban a ids que ahora son artículos
    distintos (detectado al intentar directamente: golden
    colapsó a 11.1%). Revertido antes de afectar producción.
  * **`ArticulosLoader`** (`src/articulos.py`): nueva columna
    `id_erp` cargada desde MySQL/SQL, índice `by_id_erp`.
  * **`SynonymStore`** (`src/sinonimos.py`): campo
    `articulo_id_erp` en cada entry, nuevo método
    `resolve_article_id(entry, art_loader)` (lazy remap
    si el id local ha cambiado).
  * **`matcher`** (`src/matcher.py`): `_gather_candidates` usa
    `resolve_article_id`; las llamadas `syn.add(...)` pasan
    `articulo_id_erp=top1.articulo.get('id_erp')`.
  * **Migración one-shot**
    `tools/migrate_add_articulo_id_erp.py`: parsea dump SQL,
    mapping `nombre_normalizado → (id_erp, nuevo_id)`, remapea
    3311/3337 sinónimos y 994/997 golden lines. Tolera tildes
    y truncación del export phpMyAdmin (`TIMANÁ`→`TIMAN`).
  * 24 sinónimos huérfanos (artículos borrados del catálogo,
    mayormente PANICULATA XLENCE TEÑIDA * MALIMA) invalidados
    con traza en campo `_orphan_pre_id_erp`.
- Resultado:
  * Golden **980/997 (98.3%)** — 17 mismatches son mejoras
    (matcher prefiere branded nuevos sobre genéricos anotados
    en golden). Re-anotar cuando toque.
  * Autoapprove 94.4% → **94.0%** (-0.4pp ajuste temporal;
    weak_synonym 176→212 por sinónimos reposicionados).
  * Sistema ahora resistente a futuros reimports (el `id_erp`
    preserva el vínculo aunque phpMyAdmin reasigne los `id`).
  * **Residuales (IMAGINATION, REDIANT, ORNITHOGALUM WHITE
    STAR, DARK RAINBOW) no están en el dump** — Diego los
    añadirá en próxima actualización.

### Penúltimo bloque cerrado
- Fecha: 2026-04-23
- Paso: sesión 10o — 4 fixes transversales shadow-driven (autoapprove 92.6→94.1%)
- Qué se hizo:
  * Detectado vía shadow backlog: 12 líneas Uma Flowers
    `GYPSOPHILA XL NATURAL WHITE 80cm` ambiguous proponiendo
    MIXTO genérico en vez de PANICULATA XLENCE BLANCO 1U
    VIOLETA. El operador confirmó: **VIOLETA es la marca de Uma
    para paniculata, no un color**.
  * **`src/articulos.py`**: `ArticulosLoader` gana
    `brands_by_provider: dict[int, set[str]]` con TODAS las
    marcas ≥ `BRAND_MIN_ARTICLES` (antes solo top-1). Uma pasa
    de `{UMA}` a `{UMA, VIOLETA}`.
  * **`src/matcher.py → _own_brands_norm`**: incluye marcas
    secundarias. `brand_in_name` dispara también para artículos
    con la marca secundaria del proveedor.
  * **`src/matcher.py → _score_candidate`**: sinónimo con trust
    ≥ 0.85 ya no recibe `variety_no_overlap` (excepción
    `synonym_overrides_variety`). El sinónimo manual es prueba
    explícita de traducción no-literal.
  * **`src/matcher.py → match_line`** (dos puntos): ganador con
    `source=synonym` ya NO llama `syn.add(..., 'auto')` — evita
    degradar entries `manual_confirmado` en cada run.
  * **`src/matcher.py → plausible check`**: incluye
    `top1.source == 'synonym'` para no descartar sinónimos con
    score < 0.70 hacia sin_match.
  * **Migración one-shot** `tools/migrate_uma_gypsophila_spb.py`:
    12 sinónimos Uma GYPSOPHILA `spb=0` → `spb=25`. 9 renamed,
    3 dropped por conflicto.
- Resultado:
  * UMA.pdf: 15/21 ok → **21/21 ok (100%)**.
  * Autoapprove global: 92.6% → **94.1% (+1.5pp, récord)**.
  * `variety_no_overlap` global: 232 → **165 (-29%)**.
  * **Golden 997/997 (100%) intacto**.

### Penúltimo bloque cerrado
- Fecha: 2026-04-23
- Paso: sesión 10n — cierre gap save_synonym en shadow + reporter afina rescates
- Qué se hizo:
  * **`web/api.php → handleSaveSynonym`**: añadida llamada
    `_shadowLogDecision('correct', $shadowInput, 0, $artId,
    $artName)`. El input se enriquece con los campos derivados
    de la key (provider_id|species|variety|size|spb|grade) para
    que el reporte tenga contexto incluso cuando el formulario
    no los envía.
  * **`tools/shadow_report.py`**:
    - Desglose global: confirmaciones / correcciones matcher
      (proposed≠0) / rescates sin_match (proposed=0).
    - Nueva métrica "Accuracy del matcher cuando propuso" con
      denominador `confirm + correcciones reales`, excluyendo
      rescates (cobertura humana extra, no mide al matcher).
    - "Top correcciones" filtra solo correcciones con propuesta
      (los patrones de error accionables); corrige bug previo
      `propuso X / correcto X` cuando no había propuesta.
  * Smoke test: entry sintética de save_synonym → reporter la
    clasifica como rescate, no contamina accuracy. Log limpio
    tras el test.
- Resultado:
  * Loop shadow completo end-to-end (batch 10m dejó 769
    propuestas y 0 decisiones; próximo uso de UI empezará a
    poblarlas sin perder las save_synonym).
  * Métricas técnicas sin cambios (trabajo de infraestructura):
    autoapprove 92.6% · Golden 997/997 100%.
  * Backlog pendiente actual: 87 líneas (45 Florsani · 13 Uma
    Flowers · 10 Garda · 9 Mystic · 6 Tierra Verde · ...).

### Penúltimo bloque cerrado
- Fecha: 2026-04-22
- Paso: sesión 10m — batch 7 fixes shadow-driven
- Qué se hizo:
  * Ángel procesó lote real de 27 facturas y señaló errores en
    UI (AROMA no parsea, GARDA box code en variety, FLORSANI
    solo 2 de 4 líneas y TALLA/TALLOS mal, MALIMA totales por
    coma de miles, MYSTIC CORUÑA+TNT en variety, LIFE MARL en
    variety, EQR Carpe Diem con stems 150 en vez de 450).
  * **7 fixes parsers aplicados** (detalle en CLAUDE.md Estado):
    FLORAROMA 2026 (MARK + coma decimal), EQR (stems total),
    FLORSANI (box types + sub-líneas + tints + OCR normalize),
    GARDA (box_code→label + sub-líneas heredadas), MALIMA
    (coma miles US), MYSTIC (Ñ + TNT block name), LIFE (MARL
    label).
  * **Patrón común detectado**: box codes (ELOY/MARL/R16/CORUÑA/
    ASTURIAS) metidos como parte de variety. Fix común: grupo
    opcional `[A-Z]{3,}` antes de variety → campo `label`.
  * Audit global detectó 5 parsers más pendientes (ROSALEDA
    EURO, SAYONARA SP, APOSENTOS ILIAS, MONTEROSA EUGENIA,
    EL CAMPANARIO ZAIRA) — se atenderán en siguiente batch
    shadow.
- Resultado:
  * ~200 líneas nuevas recuperadas (FLORSANI2 0→54, GARDA
    11→28, AROMA 0→4, etc.).
  * Golden **997/997 (100%) intacto** en todo el batch.
  * Autoapprove 93.9% → 92.6% por dilución (nuevas líneas sin
    sinónimo). El `register_match_hit` (10g) las recuperará.
  * **Ciclo Fase 10 operando**: errores de producción →
    diagnóstico → fix aditivo → verificación golden.

### Penúltimo bloque cerrado
- Fecha: 2026-04-22
- Paso: sesión 10l — fix parser FLORAROMA variante 2026
  (primer fix shadow-driven)
- Qué se hizo:
  * Ángel procesó lote real de 27 facturas; AROMA.pdf falló con
    "parser floraroma no extrajo líneas". Diagnóstico: formato
    FLORAROMA 2026 tiene columna nueva `MARK` (`S.O.`) y
    **coma decimal** (`0,350` en lugar de `0.350`).
  * **`src/parsers/otros.py → FloraromaParser`**:
    - Regex main y continuation: `[\d.]+` → `[\d.,]+` en price/total.
    - Nuevo helper `_num(s)` con heurística "último separador =
      decimal": maneja `0,350`, `0.350`, `1,597.00` (EN),
      `1.597,00` (ES), `1.597.000` (OCR). Defensivo con fallback
      0.0.
  * Efecto secundario: el `_num` reemplaza `float()` directo que
    tenía bug silencioso con totales >$1000 en FLORAROMA legacy
    (header daba 1.60 en lugar de 1597.00). 5/5 muestras legacy
    ahora con totals_ok.
- Resultado:
  * AROMA: 0 → **4** líneas parseadas, totals OK.
  * Auto: 3061 → **3068** (+7), **autoapprove 93.6 → 93.9%**.
  * Golden **997/997 (100%) intacto**.
  * **Primer fix derivado del shadow flow** — valida Fase 10.

### Penúltimo bloque cerrado
- Fecha: 2026-04-22
- Paso: sesión 10k — shadow mode arrancado (Fase 10)
- Qué se hizo:
  * **`web/api.php`**: nuevos helpers `_shadowLogProposals` y
    `_shadowLogDecision` + helper `_shadowSynKey` replicando la
    key de `SynonymStore._key` en Python. Integración silenciosa
    en `handleProcess` (intercepta JSON de Python, loguea
    propuesta por línea + children de mixed_box),
    `handleConfirmMatch` (decision=confirm) y
    `handleCorrectMatch` (decision=correct).
  * **`tools/shadow_report.py`** (nuevo ~200 líneas):
    agregador. Carga `shadow_log.jsonl`, cruza decisiones con
    propuestas por `synonym_key` (eligiendo la propuesta más
    reciente anterior a la decisión). Reporta: accuracy global,
    accuracy por proveedor, top correcciones con par propuso/
    correcto, backlog pendiente (ambiguous/sin_match sin
    decisión humana). Flags `--since`, `--provider`,
    `--top-errors`.
  * Smoke test con 4 entries sintéticas validó pipeline
    completo: escritura, cruce, métricas, identificación del
    patrón de corrección. Log reseteado tras el test.
- Resultado:
  * Infraestructura lista. Shadow log vacío esperando uso real.
  * Métricas técnicas (autoapprove 93.6%, golden 100%) sin
    cambios vs 10j — el valor de esta sesión es operativo.
- Pendiente:
  * Acumular 1-2 semanas de uso real.
  * Correr `shadow_report.py` semanalmente.
  * Convertir top-N patrones de corrección en fixes concretos.

### Penúltimo bloque cerrado
- Fecha: 2026-04-22
- Paso: sesión 10j — desempate cualitativo en tie_top2_margin
- Qué se hizo:
  * Diagnóstico de los 161 `ambiguous_match` residuales.
    Categorías: 96 tie_top2_margin sólo (empates de margen),
    118 low_evidence sólo (score < 0.70, mucho foreign_brand).
  * Inspección por nombre de artículo reveló que muchos tie
    eran entre artículos con **misma variedad y tallas
    distintas** donde top1 tenía `size_exact` y top2 solo
    `size_close`, o variedades multi-palabra con
    `variety_full` en top1 y match parcial en top2.
  * **`src/matcher.py`** (línea ~981, rama tie): antes de
    marcar ambiguous, chequear dominio cualitativo — si
    top1.reasons tiene `size_exact` AND top2.reasons tiene
    solo `size_close`, o top1 tiene `variety_full` y top2 no,
    marcar `ok` con reason `tiebreak_size_exact` /
    `tiebreak_variety_full`. También integrado
    `register_match_hit` del 10g.
- Resultado:
  * Ambiguous: 161 → **144** (−17, −11%).
  * `tie_top2_margin`: 96 → **79** (−18%).
  * Auto: 3052 → **3061** (+9), **autoapprove 93.4 → 93.6%**.
  * Golden **997/997 (100%) intacto**.
- Residuo (79 tie_top2): empates genuinos FANCY/SELECT,
  branded propio vs genérico mismo size, SPB faltante cuando
  parser no extrae spb (EL CAMPANARIO). Requieren revisión
  humana u otro tipo de fix (enriquecer parsers con SPB
  default).

### Penúltimo bloque cerrado
- Fecha: 2026-04-22
- Paso: sesión 10i — normalización puntuación en variety tokens
- Qué se hizo:
  * Diagnóstico profundo de las 250 penalties
    `variety_no_overlap`: 37 fixeables por puntuación
    (TIERRA VERDE `MONDIAL.`, DAFLOR `O´HARA`, AGRIVALDANI
    `M. DARK BLUE`), 35 ASSORTED/MIX genuinos, 52 multi-word
    heterogéneos, 126 single-token sin catálogo equivalente.
  * **`src/matcher.py → _score_candidate`** línea ~298. Añadido
    `re.sub(r'[^A-Z0-9 ]+', ' ', variety.upper())` antes del
    tokenizer. Convierte `MONDIAL.` → `MONDIAL`, `O´HARA` →
    `O HARA` (HARA aparece como substring de OHARA en el nombre
    del artículo, `any(t in nombre)` sigue funcionando). Fix
    aditivo, ~5 líneas.
- Resultado:
  * `variety_no_overlap`: 250 → **232** (−7%).
  * Auto: 3037 → **3052** (+15), **autoapprove 93.0 → 93.4%**.
  * Ambiguous: 171 → 161 (−10, los casos fix salieron del
    bucket porque ahora tienen variety_match +0.30 y no
    penalty −0.10, sube 0.40 neto).
  * Golden **997/997 (100%) intacto**.
- Residuo (232): productos genuinamente no existentes en
  catálogo (ELITE alstros), OCR corrupto irrecuperable
  (FLORAROMA `ESX.OPLORER`), variedades multi-word con
  concatenación OCR. Fuera de alcance de normalización simple.

### Penúltimo bloque cerrado
- Fecha: 2026-04-22
- Paso: sesión 10h — fixes parsers UNIQUE + CANANVALLE
- Qué se hizo:
  * Diagnóstico de los 9 samples que impedían a los 5 NO_PARSEA
    salir del bucket. 3 clasificados como no-recuperables
    (SAYONARA 64811 OCR corrupto total, CEAN cean 57 español
    con rosas → reescritura amplia, NATIVE BLOOMS samples con
    tropicales gratis).
  * **`src/parsers/otros.py → UniqueParser._PROFORMA_RE`**
    (nuevo). 2 samples fallidos eran facturas PROFORMA con
    layout `HITS No. DESCRIPTION BRAND BOX BOX TYPE PCS FULL
    PACKING T.STEMS UNIT UNIT PRICE TOTAL VALUE`. Nuevo regex
    captura `0603.11.00.50 ROSES BLUSH 50 HB 1 0.5 300 300
    STEMS $ 0.32 $ 96.00`, tolera OCR split en total.
  * **`src/parsers/otros.py → CustomerInvoiceParser._SAMPLE_RE`**
    (nuevo). 2 samples duplicados de CANANVALLE eran facturas
    SAMPLE con layout-tabla sin `$` (`COMMERCIAL INVOICE`).
    Nuevo regex captura `1 1 - 1 HB Brighton 50 1 1 25 25
    0.010 0.250SAMPLE`.
  * Ambos fixes aditivos — nuevo regex primero, legacy intacto.
- Resultado:
  * **Buckets: NO_PARSEA 5 → 3, OK 77 → 79** (UNIQUE y
    CANANVALLE promovidos).
  * Líneas totales: 3506 → **3521** (+15 nuevas parseadas).
  * Auto: 3019 → **3037** (+18), **autoapprove 92.9 → 93.0%**.
  * weak_synonym: 677 → **200** (efecto secundario 10g +
    nuevas líneas parseadas que reforzaron sinónimos).
  * Golden **997/997 (100%) intacto**.

### Penúltimo bloque cerrado
- Fecha: 2026-04-22
- Paso: sesión 10g — auto-confirmación de sinónimos
- Qué se hizo:
  * **`src/sinonimos.py → register_match_hit`** (nuevo método).
    Incrementa `times_confirmed` del sinónimo preexistente si
    apunta al mismo artículo que el ganador. Tras ≥ 2 hits,
    promueve `aprendido_en_prueba | status vacío → aprendido_confirmado`
    (trust 0.55 → 0.85). Skip explícito para `manual_confirmado`,
    `rechazado`, `aprendido_confirmado` ya consolidado.
  * **`src/matcher.py`** (línea ~991). Llama a
    `register_match_hit` tras cerrar un `ok` solo si el match tiene
    **evidencia independiente del sinónimo**:
    `variety_match AND (size_exact OR brand_in_name)`. Evita
    bootstrapping circular.
- Resultado (dos pasadas de evaluate_all):
  * weak_synonym penalties 1787 → 1259 → **677 (−62%)**.
  * **774 sinónimos promovidos** `aprendido_en_prueba → aprendido_confirmado`.
  * auto 3019 → 3021 (+2), **autoapprove 92.8 → 92.9%** (+0.1pp).
  * Golden **997/997 (100%) intacto** (manual_confirmado skip).
- Valor: cada tooltip de revisión muestra menos ruido
  `weak_synonym` (−62%). Los 774 sinónimos promocionados dejan
  de bloquear carriles auto en futuras facturas.

### Penúltimo bloque cerrado
- Fecha: 2026-04-22
- Paso: sesión 10f — fix parser BRISSAS (header `Sub Total` vs
  primera fila `TOTAL`)
- Qué se hizo:
  * **`src/parsers/otros.py → BrissasParser`**: el regex de
    `header.total` era `(?:Sub\s+)?Total\s+([\d,.]+)` y capturaba
    la fila-resumen de stems (`TOTAL 6700 0.286 1918.00`, donde
    6700 son stems y 1918 el grand total). Fix aditivo: preferir
    `Sub\s+Total\s+([\d,.]+)` (grand total real, aparece más
    abajo), fallback a `Total\s+([\d,.]+)` si no existe. Uniforme
    en los 11 samples disponibles.
  * **Goldens**: corregido `header_total` en
    `brissas_000003919.json` (16200→4632.75) y
    `brissas_000003952.json` (14925→4315.5). `evaluate_golden.py`
    no chequea este campo, cambios cosméticos.
- Resultado: BRISSAS `tot_ok=0/5` → **5/5**, verdict
  TOTALES_MAL → OK. 11/11 samples con `header_ok=True`. Buckets:
  OK 76→**77**, TOTALES_MAL 1→**0**. Global auto **92.8% estable**
  (3019/3252 linkables). Golden **100% (997/997) intacto**.
  Matchmaking de BRISSAS mantiene 170/171 auto (100% de
  linkables), sin cambios en link accuracy.

### Penúltimo bloque cerrado
- Fecha: 2026-04-17
- Paso: sesión 9q — IWA mixed_box + CANTIZA/MILAGRO/MILONGA + fuzzy
  cache + golden drafts
- Qué se hizo:
  * **`matcher.py → reclassify_assorted`**: regex ampliado para
    `SURTIDO MIXTO`, `ASSORTED ROSA`, `MIXTO` y variantes de 2
    palabras. IWA 17 líneas `ambiguous_match` → `mixed_box`.
  * **`parsers/cantiza.py`**: OCR cleanup (`S0CM`→`50CM`, `N255T`→
    `N 25ST`, pipes). CANTIZA NO_PARSEA → OK (100 líneas).
  * **`parsers/otros.py → ColFarmParser`**: aliases Rose/Unit
    ampliados (R:ise, R:lse, Rlse, SR), cleanup OCR ruido `\d~`,
    header fallback con `TOTAL (Dolares)` y `Vlr.Total FCA`.
    MILONGA NO_PARSEA → TOTALES_MAL.
  * **`parsers/auto_milagro.py`**: `_ocr_normalize()` maneja `~OSES`,
    `FREE DOM`, `SO/S0` contextual, paréntesis OCR `(`→`0`, y chars
    basura (bullet, replacement, etc.) → `-`. MILAGRO NO_PARSEA →
    TOTALES_MAL.
  * **`articulos.py → fuzzy_search`**: cache por `(sp_key, query,
    threshold)` + prefiltro `real_quick_ratio`/`quick_ratio`. ~23%
    speedup en invoice de 42 líneas (6.5s → 5.0s).
  * **Golden**: +3 drafts (timana, benchmark, florifrut).
- Resultado: autoapprove **86.7% → 87.8%** (+1.1pp); ok 2785→2795;
  ambig 268→228 (−40 por mixed_box). Buckets: OK 70→71, NO_PARSEA
  10→7, TOTALES_MAL 1→3. Golden 100% (88/88 reviewed + 3 drafts).

### Penúltimo bloque cerrado
- Fecha: 2026-04-17
- Paso: sesión 9p — IWA + PREMIUM + CIRCASIA + ECOFLOR + MILONGA +
  MILAGRO + PRESTIGE
- Qué se hizo:
  * **`parsers/otros.py → IwaParser`**: regex anclada en tariff 10d
    + bloque `Stems N USD$ P USD$ T`. CM opcional, farm codes
    limpiados por lista, size opcional. IWA: rescued 32→0, parsed
    21→53; MUCHO_RESCATE → OK.
  * **`parsers/otros.py → PremiumColParser`**: OCR cleanup
    (l→1, Rl4→R14, .US$→US$, US$0→US$ 0) + `.*?Stems` para absorber
    ORDEN intermedio. Variante B DIAN como fallback. PREMIUM:
    NO_PARSEA → OK.
  * **`parsers/otros.py → ColFarmParser`**: pm5 nuevo para CIRCASIA
    (`SIZE - SIZE` range + label + tariff dotted + stems+Stems+price+
    $total). `\s+[-_]?\s*` relajado para `X25 -40` de MILONGA.
    CIRCASIA: NO_PARSEA → OK.
  * **`parsers/mystic.py`**: variety class a
    `[A-Za-zÀ-ÿ\ufffd]` — acepta CAFÉ OCR-corrompido a CAF�.
    ECOFLOR: TOTALES_MAL → OK.
  * **`parsers/auto_milagro.py`**: `_TOTAL_RE` con coma de miles.
    MILAGRO 02a header 1.0 → 1193.5.
  * **`parsers/otros.py → PrestigeParser`**: variante OCR simple
    `ROSE FREEDOM 40 CM 2 250 500 0,16 80,00`. PRESTIGE:
    NO_PARSEA → OK (9→24 parsed).
- Resultado: autoapprove **87.1% → 86.7%** (−0.4pp, dilución por
  líneas nuevas); ok 2739→2785 (+46); líneas totales 3219→3297
  (+78); ambiguous 246→268 (IWA MIXTO). **Buckets: OK 65→70,
  NO_PARSEA 13→10, MUCHO_RESCATE 1→0, TOTALES_MAL 2→1**. Golden 100%.

### Penúltimo bloque cerrado
- Fecha: 2026-04-17
- Paso: sesión 9o — TIMANA + ART ROSES + BENCHMARK + TESSA parsers
- Qué se hizo:
  * **`parsers/otros.py → TimanaParser`**: `OF ` opcional antes del
    tariff; parent `ASSORTED BOX` se skippea y las sub-líneas (`ROSE
    VAR COLOR SIZECM bunches spb price`, sin total ni `HB`) heredan
    btype del parent; `header.total` derivado de `Total FCA Bogota:
    $...` o suma. Sample 01: 5 líneas → 22. Totals_ok 0/5 → 5/5.
  * **`parsers/mystic.py`**: `re.I` en `_LINE_RE` y `_LINE_RE_NOCODE`
    + `[A-Za-z...]` en variety — desbloquea ART ROSES (FLORIFRUT,
    fmt heredado mystic) con variedad mixed-case (Mondial, Explorer,
    Brighton, Frutteto). ART ROSES: 0/5 OK → 5/5 OK (29 líneas).
  * **`parsers/golden.py`** (BENCHMARK): `price_m` admite coma de
    miles en total (`1,350.00`). Rescued 4→0, totals_ok 3/5→5/5.
  * **`parsers/otros.py → TessaParser`**: prefix opcional para farm
    code `TESSA-R1`/`TESSA-R2`; coma-en-total. Sample 02b 0→4 parsed,
    diff 100%→0%.
- Resultado: autoapprove **86.8% → 87.1%** (+0.3pp); ok 2652→2739;
  líneas totales 3118→3219 (+101); NO_PARSEA ~19→13. Golden 100%.

### Penúltimo bloque cerrado
- Fecha: 2026-04-17
- Paso: sesión 9l — ELITE matching + SAYONARA precio-correcto
- Qué se hizo:
  * **`src/parsers/auto_elite.py`**: defaults de talla por especie
    (ALSTRO=70, CARN=60). Las facturas ELITE no llevan CM y el catálogo
    asume 70cm para alstros.
  * **`src/matcher.py`**: fuzzy threshold 0.5 → 0.4 (el scoring filtra
    después; catálogos con variedades largas rinden similitud 40-50%
    aunque la variedad corta sea correcta).
  * **`src/parsers/sayonara.py`**: bug de Custom Pack mix. Líneas
    detalle usaban `price_per_stem=pack['price']` (0.95) en vez del
    `d['price_unit']` real (0.19) y `line_total=proporción`, disparando
    `total_mismatch` que capaba link a 0.70. Fix: price_unit real +
    line_total = stems × price_unit + bunches correcto. Normalizado
    `bunches` vs `spb` entre PACK_RE y PACK_RE_B.
- Resultado: ELITE 0 ok → 15 ok (auto 0% → 50%); SAYONARA auto 0 →
  38 (82.6%). Global autoapprove **79.6% → 80.4%** (+0.8pp). Golden
  100% mantenido.

### Penúltimo bloque cerrado
- Fecha: 2026-04-17
- Paso: sesión 9k — LATIN parser + refinado matcher
- Qué se hizo:
  * **`src/parsers/latin.py`**: Format B regex ampliado para aceptar
    coma decimal (`0,250` además de `0.250`). LATIN pasó de 91 líneas
    100% ambiguas a 314 líneas 306 ok.
  * **`src/matcher.py`**: quitado upper-clamp del score (permitir >1.0
    para desempatar brand_boost), brand_boost ahora exige `size_exact`
    (no `size_close`), tramo nuevo de required_margin=0.02 para scores
    ≥1.05.
- Resultado: autoapprove **68.9% → 79.6%** (+10.7pp), líneas ok
  2002→2453, tie_top2_margin 521→187. Golden 100% mantenido.

### Penúltimo bloque cerrado
- Fecha: 2026-04-17
- Paso: Fase 2 cerrada + brand boost aplicado
- Qué se hizo:
  * **Golden set revisado manualmente** por el operador. Los 5 JSONs
    (`alegria`, `fiorentina`, `golden_unknown`, `meaflos`, `mystic`)
    pasaron de `draft` → `reviewed`. `evaluate_golden.py` confirma
    100% parse + link accuracy sobre 88 líneas.
  * **Brand boost** (sesión 9j, commit `3855f7e`): en `src/matcher.py`
    los artículos con marca del proveedor (vía `brand_by_provider`) +
    variety/size match reciben `score=1.05`. `own_brands` se alimenta
    también de `brand_by_provider` para casos tipo PONDEROSA donde la
    key no coincide con la marca.
- Resultado: autoapprove **66.1% → 68.9%** (+2.8pp), golden 100%
  mantenido. Fase 2 y 3 cerradas empíricamente.

### Penúltimo bloque cerrado
- Fecha: 2026-04-16
- Paso: Fase 4 cerrada — Paso 3 del roadmap (taxonomía E1..E10)
- Qué se hizo (sesión 9):
  * `tools/evaluate_all.py` ampliado: penalties y match_statuses por
    proveedor y por muestra (antes solo global).
  * Nuevo `tools/classify_errors.py`: clasifica cada proveedor en
    E1..E10 con heurísticas automáticas. Output: `auto_learn_taxonomy.json`
    + tabla terminal con backlog priorizado.
  * Hallazgo principal: E7_SYNONYM_DRIFT (67/82) domina sobre parseo
    (E1+E3 ~31+26). La solución transversal más impactante es confirmar
    sinónimos (Paso 7) + golden set (Paso 2), no más parsers.
  * Baseline actualizada: 2644 líneas, 62.0% autoaprobables.
- Resultado: backlog priorizado listo para atacar por familia de error.
- Riesgos / pendientes: ninguno bloqueante.

### Penúltimo bloque cerrado
- Fecha: 2026-04-15
- Paso: Fase 1 cerrada — Paso 1 del roadmap (benchmark consolidado)

### Ante-penúltimo bloque cerrado
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
- Fecha: _(siguiente sesión)_
- Paso: por decidir entre **Shadow mode** (Fase 10) vs bajar NO_PARSEA
  restantes (20 proveedores) vs optimizar matcher.
- Estado: pendiente elección del operador.

### Próximo bloque recomendado
- Paso: **Shadow mode** (Fase 10)
- Motivo: la base estructural y empírica está cerrada (golden 100%,
  autoapprove ~69%). El siguiente salto requiere uso real para capturar
  los formatos/matches que el benchmark no exhibe.
- Dependencias: ninguna técnica. Implica empezar a procesar facturas
  reales en producción comparando propuesta vs decisión humana.

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
