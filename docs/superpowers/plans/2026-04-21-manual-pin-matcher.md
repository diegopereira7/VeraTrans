# Manual-pin en matcher — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Garantizar que un sinónimo `manual_confirmado` gane por score contra cualquier candidato competidor en el matcher, cerrando el único mismatch conceptual restante del golden set (UMA XL ESPECIAL → 28205).

**Architecture:** Añadir un bloque "manual pin" en `src/matcher.py` justo antes del sort final. Cuando `manual_syn_locked` es True y el candidato ligado al sinónimo está en `viable`, se le asigna `score = max(score, 1.10, other_top + 0.05)` y reason `manual_pin`. Aditivo — no reemplaza syn_trust ni brand_boost.

**Tech Stack:** Python 3.11, tests de regresión vía `tools/evaluate_golden.py` y `tools/evaluate_all.py` (golden set como harness, no pytest).

**Spec:** [`docs/superpowers/specs/2026-04-21-manual-pin-matcher-design.md`](../specs/2026-04-21-manual-pin-matcher-design.md)

---

## File Structure

- **Modify**: `src/matcher.py` — añadir bloque manual-pin (~10 líneas entre la definición de `manual_syn_locked` y `viable.sort`)
- **Modify**: `CLAUDE.md` — actualizar Estado actual (golden 99.7 → 100%, última sesión) e Historial reciente (añadir sesión 9z; mover sesión 9x a `docs/sessions.md`)
- **Modify**: `docs/sessions.md` — anexar la sesión desplazada de CLAUDE.md

No se crean archivos nuevos ni se añaden tests unitarios. El golden set actúa como test de regresión.

---

### Task 1: Capturar baseline del golden

**Files:**
- Read: `golden/golden_eval_results.json` (se regenera al correr el comando)

- [ ] **Step 1: Ejecutar evaluación golden y capturar baseline**

Run:
```bash
python tools/evaluate_golden.py
```

Expected output (clave): línea con `link_accuracy: 0.9966` (o similar, 291/292) y `discrepancies` con una entrada:
```
gold_variety: GYPSOPHILA XL ESPECIAL
gold_articulo: 28205 (PANICULATA XLENCE TEÑIDA MIXTO 750GR 1U)
sys_articulo: 28188 (PANICULATA (GYPSOPHILA) MIXTO M-14 N)
```

- [ ] **Step 2: Anotar métricas baseline**

Registrar: `link_accuracy baseline = 0.9966 (291/292)`, 1 discrepancy en uma.

---

### Task 2: Aplicar el fix en matcher.py

**Files:**
- Modify: `src/matcher.py` — insertar bloque después de línea 843 (cierre de `manual_syn_locked`) y antes de línea 884 (sort final). La inserción va justo **antes** de `viable.sort(key=lambda c: c.score, reverse=True)`.

- [ ] **Step 1: Leer el contexto actual**

Leer `src/matcher.py` líneas 839-884 para confirmar que la estructura no ha cambiado desde el spec:
- Línea 839-843: `manual_syn_locked = (syn_entry is not None and ... )`
- Línea 846-882: bloque brand_boost
- Línea 884: `viable.sort(key=lambda c: c.score, reverse=True)`

- [ ] **Step 2: Insertar bloque manual-pin antes del sort final**

Ubicación: entre la línea `...append('brand_boost')` (actual 882) y `viable.sort(...)` (actual 884). Deja una línea en blanco antes y después del bloque.

Código exacto a insertar:

```python
        # Manual pin: si existe sinónimo manual_confirmado y el candidato
        # ligado está en viable, forzarlo a ganar. El operador ya decidió;
        # el matcher respeta esa decisión como verdad absoluta. Diferencia
        # con brand_boost: no requiere variety_match ni size_exact; basta
        # con que el sinónimo apunte a un articulo válido y ese candidato
        # siga en viable (el fix de sesión 9y garantiza que los vetos
        # duros no descarten a un manual_confirmado, solo lo penalizan).
        if manual_syn_locked:
            target_id = int(syn_entry['articulo_id'])
            pinned = next(
                (c for c in viable
                 if int(c.articulo.get('id') or 0) == target_id),
                None,
            )
            if pinned is not None:
                other_top = max(
                    (c.score for c in viable if c is not pinned),
                    default=0.0,
                )
                pinned.score = max(pinned.score, 1.10, other_top + 0.05)
                if 'manual_pin' not in pinned.reasons:
                    pinned.reasons.append('manual_pin')
```

Usa `Edit` con:
- `old_string`: las últimas líneas existentes antes del sort:
  ```
                  if 'brand_boost' not in c.reasons:
                      c.reasons.append('brand_boost')

          viable.sort(key=lambda c: c.score, reverse=True)
  ```
- `new_string`: igual pero con el bloque manual-pin insertado entre `c.reasons.append('brand_boost')` y `viable.sort(...)` (una línea en blanco arriba y abajo del nuevo bloque).

- [ ] **Step 3: Verificar que Python parsea el archivo sin errores**

Run:
```bash
python -c "import src.matcher; print('OK')"
```

Expected: `OK`. Si sale `IndentationError` o `SyntaxError`, revisa la indentación del bloque insertado (debe estar al mismo nivel que `own_brands_norm = ...` en línea 845).

---

### Task 3: Verificar golden pasa a 100%

**Files:**
- Read: `golden/golden_eval_results.json` (regenerado)

- [ ] **Step 1: Ejecutar evaluación golden**

Run:
```bash
python tools/evaluate_golden.py
```

Expected: `link_accuracy: 1.0 (292/292)`, `discrepancies: []` para uma y el resto de proveedores.

- [ ] **Step 2: Confirmar que la entrada uma XL ESPECIAL ya no aparece en discrepancies**

Leer `golden/golden_eval_results.json` y buscar `"GYPSOPHILA XL ESPECIAL"`. Expected: sin match (0 ocurrencias).

- [ ] **Step 3: Si no es 100%, diagnosticar**

Si sigue en 99.7% o baja:
- Verificar que el bloque se insertó en el lugar correcto (después de brand_boost, antes de sort).
- Verificar que `manual_syn_locked` efectivamente evalúa a True para el caso uma (imprimir desde un script temporal o añadir `print(manual_syn_locked, syn_entry)` temporalmente).
- Verificar que el candidato 28205 **está** en `viable` (si no, el fix 9y no lo dejó entrar y hay que revisar `_hard_vetoes` + branch source='synonym').

Si no es 100%, detener e investigar antes de seguir.

---

### Task 4: Verificar autoapprove global no regresa

**Files:**
- Read: salida de `evaluate_all.py`

- [ ] **Step 1: Ejecutar evaluación global**

Run:
```bash
python tools/evaluate_all.py
```

Expected (criterio): `autoapprove ≥ 0.908` (baseline 91.1% con tolerancia ±0.3pp). El número objetivo real es ≈0.911 sin cambio o ligeramente superior.

- [ ] **Step 2: Anotar el autoapprove nuevo**

Registrar el valor. Si baja más de 0.3pp respecto al baseline (91.1%), detener e investigar qué líneas cambiaron de estado.

---

### Task 5: Actualizar CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` — secciones "Última actualización", "Estado actual", "Historial reciente"

- [ ] **Step 1: Actualizar fecha y estado**

Editar header de CLAUDE.md:
- Cambiar `**Última actualización:** 2026-04-20 (sesión 9y)` → `**Última actualización:** 2026-04-21 (sesión 9z)`
- Cambiar `Golden 292/292 reviewed (link 99.7%)` → `Golden 292/292 reviewed (link 100%)`

Editar sección "Estado actual":
- Cambiar `**Autoapprove global:** 91.1%` por el valor real medido en Task 4.
- Cambiar `**Link accuracy 99.7% (291/292)**` → `**Link accuracy 100% (292/292)**`
- Eliminar la línea `— solo 1 mismatch conceptual: uma GYPSOPHILA XL ESPECIAL (gramaje 750GR vs genérico).`
- Reemplazar `- **Última sesión:** 9y (2026-04-20) ...` por resumen de sesión 9z (ver Step 3 siguiente).

Editar sección "Próximos pasos posibles":
- Eliminar el ítem 1 "Resolver el mismatch conceptual restante" (ya hecho).
- Renumerar los siguientes (Shadow mode pasa a ser #1).

- [ ] **Step 2: Mover sesión 9x a docs/sessions.md**

En CLAUDE.md, "Historial reciente" debe mantener solo 2 sesiones. Cortar el bloque completo `### 2026-04-20 — sesión 9x: respeto manual_confirmado...` (desde el encabezado hasta antes del siguiente `###` o del separador final) y pegarlo en `docs/sessions.md` al principio de su lista cronológica.

- [ ] **Step 3: Añadir sesión 9z al principio del Historial reciente**

Formato:

```markdown
### 2026-04-21 — sesión 9z: manual-pin cierra mismatch UMA XL ESPECIAL (golden 100%)

Último mismatch conceptual del golden: UMA 18222 línea "Gyp XL
Especial 80 cm /750gr" apuntaba a 28188 "PANICULATA (GYPSOPHILA)
MIXTO M-14 N" (genérico) cuando el gold era 28205 "PANICULATA
XLENCE TEÑIDA MIXTO 750GR 1U". Existía sinónimo `manual_confirmado`
con key exacta `440|GYPSOPHILA|GYPSOPHILA XL ESPECIAL|80|25|` → 28205
(`sinonimos_universal.json:48455`, times_confirmed=2) pero el
matcher lo ignoraba: el syn_trust solo aporta +0.245 al score, no
fuerza la victoria.

Fix en [src/matcher.py](src/matcher.py) (bloque nuevo antes del
sort final): si `manual_syn_locked` y el candidato ligado está en
viable, `score = max(score, 1.10, other_top + 0.05)` + reason
`manual_pin`. Complementa los fixes de 9y (hard_vetoes) y 9x
(brand_boost skip, sinonimos.add no-clobber): ahora `manual_confirmado`
es pin absoluto al final del scoring.

Impacto: golden link 99.7 → **100%** (292/292). Autoapprove [VALOR_MEDIDO] (baseline 91.1%).
```

Reemplazar `[VALOR_MEDIDO]` con el valor real de Task 4.

- [ ] **Step 4: Verificar que CLAUDE.md mantiene solo 2 sesiones en Historial reciente**

Tras los cambios, "Historial reciente" debe contener: sesión 9z (nueva) + sesión 9y. La sesión 9x debe haber sido movida a `docs/sessions.md`.

---

### Task 6: Commit

- [ ] **Step 1: Revisar cambios**

Run:
```bash
git status
git diff src/matcher.py CLAUDE.md docs/sessions.md
```

Expected: cambios solo en los 3 archivos. Sin archivos untracked relevantes (golden_eval_results.json se regenera en cada evaluación, puede o no incluirse).

- [ ] **Step 2: Hacer commit**

Run:
```bash
git add src/matcher.py CLAUDE.md docs/sessions.md
git commit -m "$(cat <<'EOF'
Sesion 9z: manual-pin cierra mismatch UMA XL ESPECIAL (golden 99.7->100%)

manual_confirmado ahora es pin absoluto al final del scoring:
score = max(score, 1.10, other_top + 0.05) cuando el candidato
ligado esta en viable. Respeta la decision explicita del operador
por encima de cualquier score bruto competidor.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Verificar commit**

Run:
```bash
git log -1 --stat
```

Expected: 1 commit con los 3 archivos modificados.

---

## Self-Review

**Spec coverage:**
- "Pin explícito para manual_confirmado" → Task 2 ✓
- "score ≥ 1.10 y score ≥ second + 0.05" → Task 2 Step 2 ✓
- "variable manual_syn_locked ya existe" → Task 2 Step 2 (usa la existente, no la redefine) ✓
- "Validación: evaluate_golden.py antes/después" → Tasks 1 y 3 ✓
- "Validación: evaluate_all.py autoapprove" → Task 4 ✓
- "Criterios de aceptación: 100%, autoapprove ≥ 91.1% ±0.3pp" → Task 3 + Task 4 ✓
- "CLAUDE.md estado + historial" → Task 5 ✓

**Placeholder scan:**
- `[VALOR_MEDIDO]` en Task 5 Step 3 es un placeholder **intencional** — el valor real solo existe tras ejecutar Task 4. Las instrucciones de sustitución son explícitas.
- No hay TBD/TODO/"implement later" en ningún step.

**Type consistency:**
- `manual_syn_locked` (bool) — coherente entre Task 2 y el código ya existente.
- `syn_entry['articulo_id']` (int) — casteado explícitamente a int en el nuevo bloque.
- `c.articulo.get('id')` → casteado a int para comparación. Consistente con el patrón existente del archivo (líneas 842, otros `int(..., 0) or 0`).
