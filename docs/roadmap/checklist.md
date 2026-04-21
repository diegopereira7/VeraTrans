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

### KPIs actuales (sesión 10e, `tools/evaluate_all.py`)
- Líneas totales procesadas: **3506**
- Líneas `ok`: **3084** · `ambiguous_match`: **168** · `autoapprovable`: **3020**
- **autoapprove_rate: 92.9%** de las líneas linkables (3020/3252)
- **Golden set: 100%** parse + link accuracy (997/997 líneas
  reviewed, 24 facturas, 13 proveedores)
- Buckets: OK 76 · NO_PARSEA 5 · TOTALES_MAL 1 (BRISSAS) ·
  NO_DETECTADO 1 (PONDEROSA)

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
- [ ] Procesar facturas reales en modo sombra
- [ ] Comparar propuesta del sistema vs decisión humana
- [ ] Capturar nuevos formatos y fallos reales
- [ ] Convertir correcciones en dataset útil
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
- [ ] 17. **Shadow mode** (Fase 10) — cuando se empiece a implantar
- [ ] 18. Revisar golden drafts (timana, benchmark, florifrut) y
      marcarlos reviewed
- [ ] 19. NO_PARSEA restantes (7): CANANVALLE, CEAN GLOBAL, DAFLOR,
      ELITE, NATIVE BLOOMS, SAYONARA, UNIQUE — mayoría son issues de
      match, no de parse
- [ ] 20. TOTALES_MAL (3): CANTIZA/MILAGRO/MILONGA — mejorar header
      extraction para samples con OCR corrupto

---

## Registro rápido de avances

### Último bloque cerrado
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
