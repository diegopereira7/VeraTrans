# Manual-pin en matcher — diseño

**Fecha**: 2026-04-21
**Autor**: sesión con Claude
**Status**: aprobado (pendiente de implementación)

## Problema

El matcher ignora la decisión explícita del operador en casos donde un candidato
competidor obtiene score bruto más alto que el candidato ligado a un sinónimo
`manual_confirmado`.

### Caso concreto: UMA 18222 línea "Gyp XL Especial 80 cm /750gr"

- **Variety post-parser**: `GYPSOPHILA XL ESPECIAL`, size=80, spb=25
- **Sinónimo existente** (`sinonimos_universal.json:48455`):
  - key: `440|GYPSOPHILA|GYPSOPHILA XL ESPECIAL|80|25|`
  - articulo_id: `28205` "PANICULATA XLENCE TEÑIDA MIXTO 750GR 1U"
  - status: `manual_confirmado`, times_confirmed: 2
- **Matcher elige**: `28188` "PANICULATA (GYPSOPHILA) MIXTO M-14 N" (genérico)
- **Resultado**: `ambiguous_match`, link_confidence 0.532

### Diagnóstico (raíz)

En [src/matcher.py:395-399](../../../src/matcher.py), el `syn_trust` de un
`manual_confirmado` aporta solo `+0.25 × 0.98 = +0.245` al score del candidato
ligado. Es un **bonus, no un pin**.

Para 28188:
- `variety_match` (comparte "MIXTO") + fuzzy hint + method prior
- Puede superar `score_base_28205 + 0.245`

Los fixes de sesión 9y cubren dos puntos:
1. `brand_boost` skip cuando manual_confirmado
2. `hard_vetoes` no descartan manual_confirmado (solo penalizan)

Pero ninguno **fuerza la victoria** del candidato manual.

## Solución

Pin explícito para `manual_confirmado`: cuando el sinónimo está lockeado y el
candidato ligado está en `viable`, forzarlo a ganar por score.

### Ubicación

[src/matcher.py](../../../src/matcher.py), justo antes del sort final (actual
línea 884: `viable.sort(key=lambda c: c.score, reverse=True)`).

### Código

```python
# Manual pin: si existe sinónimo manual_confirmado y el candidato
# ligado está en viable, forzarlo a ganar. El operador ya decidió;
# el matcher respeta esa decisión como verdad absoluta. Diferencia
# con brand_boost: no requiere variety_match ni size_exact; basta
# con que el sinónimo exista y apunte a un articulo válido.
if manual_syn_locked:
    target_id = int(syn_entry['articulo_id'])
    pinned = next(
        (c for c in viable if int(c.articulo.get('id') or 0) == target_id),
        None,
    )
    if pinned is not None:
        other_top = max(
            (c.score for c in viable if c is not pinned), default=0.0
        )
        pinned.score = max(pinned.score, 1.10, other_top + 0.05)
        if 'manual_pin' not in pinned.reasons:
            pinned.reasons.append('manual_pin')
```

La variable `manual_syn_locked` ya existe en línea 839-843 y no se redefine.

### Propiedades

- `score ≥ 1.10` y `score ≥ second + 0.05` → cumple `required_margin = 0.02`
  del tramo ≥1.05 → cae en rama `ok`, no `ambiguous_match`.
- Respeta todos los caminos previos (vetos, brand_boost skip, scoring). Solo
  añade un paso final de promoción.
- Si el candidato ligado no está en `viable` (edge case), no hace nada — no
  cambia el comportamiento actual.

### Lo que NO hace (por diseño)

- No crea el candidato si no existe en `viable`. El fix 9y garantiza que un
  sinónimo manual_confirmado siempre entre (con penalty si hay vetos), así
  que el candidato debería estar. Si por alguna otra razón no está, el fix
  no intenta "inventarlo".
- No modifica el syn_trust existente. Coexiste con el bonus +0.245 (que sigue
  siendo relevante para `aprendido_confirmado` y otros status).
- No extiende el comportamiento a status menores (`aprendido_confirmado`,
  `aprendido_en_prueba`). Esos siguen compitiendo por score.

## Validación

Antes de aplicar:

```bash
python tools/evaluate_golden.py
# Baseline esperado: link_accuracy 99.7% (291/292), 1 mismatch (UMA XL ESPECIAL)
```

Después de aplicar:

```bash
python tools/evaluate_golden.py
# Objetivo: link_accuracy 100% (292/292), 0 mismatches

python tools/evaluate_all.py
# Objetivo: autoapprove ≥ 91.1% (no debería bajar)
```

### Criterios de aceptación

1. Golden link_accuracy pasa de 99.7% a **100%**.
2. Autoapprove global ≥ 91.1% (tolerancia ±0.3pp por ruido).
3. Ningún proveedor reviewed del golden baja su link_accuracy individual.

### Riesgos

- **Riesgo aceptado**: un `manual_confirmado` mal asignado por el operador
  nunca sería contradicho por el matcher. Es el contrato deseado: "manual =
  verdad". El operador puede corregir borrando/reasignando el sinónimo.
- **Riesgo bajo**: si el candidato manual tenía score legítimamente bajo
  (p.ej. variety muy distinta), el pin lo eleva artificialmente. Se mitiga
  porque el operador ya vio la línea y aceptó el vínculo — es una decisión
  informada, no heurística.

## Alcance

- **Líneas modificadas**: ~10 en `src/matcher.py`
- **Archivos nuevos**: ninguno
- **Archivos tocados**: `src/matcher.py`, `CLAUDE.md` (estado + historial),
  `docs/sessions.md` (si aplica mover sesión antigua)
- **Tests afectados**: `tools/evaluate_golden.py`, `tools/evaluate_all.py`
  (no son tests unitarios; son evaluaciones de regresión)

## Referencias

- CLAUDE.md § "Matching: scoring por evidencia"
- CLAUDE.md § "Historial reciente" sesión 9y (fix hard_vetoes manual_confirmado)
- CLAUDE.md § "Historial reciente" sesión 9x (fixes manual_confirmado
  brand_boost + sinonimos.add)
- [src/matcher.py](../../../src/matcher.py) líneas 790-884
- [golden/uma_18222.json](../../../golden/uma_18222.json) línea 31-46
- [sinonimos_universal.json](../../../sinonimos_universal.json) entrada
  `440|GYPSOPHILA|GYPSOPHILA XL ESPECIAL|80|25|`
