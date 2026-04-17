# Taxonomía de errores E1..E10

Clasificación de errores por familia, generada por
[tools/classify_errors.py](../tools/classify_errors.py) a partir de la
salida del benchmark. Permite atacar el backlog por **patrón
reutilizable** en vez de proveedor por proveedor.

---

## Categorías

| Código | Nombre | Qué es | Cómo arreglarlo |
|---|---|---|---|
| E1_PARSE_ZERO | Parseo cero | El parser no extrae ninguna línea de la muestra | Revisar regex / layout del parser |
| E2_PARSE_PARTIAL | Parseo parcial | Extrae algunas líneas pero rescue captura otras | Ampliar regex del parser |
| E3_LAYOUT_COORDS | Layout/coords | PDF nativo no parsea — problema de columnas | Usar `extract_words()` con x-coords |
| E4_OCR_BAD | OCR corrupto | OCR irrecuperable — tokens fragmentados | Aceptar techo; no forzar regex |
| E5_TOTAL_HEADER | Total cabecera | Suma de líneas OK pero `header.total` mal | Añadir regex de total o derivar |
| E6_MATCH_WRONG | Match incorrecto | Línea bien leída → artículo ERP incorrecto | Revisar sinónimos, marcas, vetos |
| E7_SYNONYM_DRIFT | Sinónimo débil | Sinónimo `aprendido_en_prueba` sin confirmar | Confirmar desde UI o batch |
| E8_AMBIGUOUS_LINK | Vínculo ambiguo | ≥2 candidatos plausibles con margen pequeño | Más features o golden set |
| E9_VALIDATION_FAIL | Validación | Incoherencias stems/bunches/totales | Revisar parser o reglas |
| E10_PROVIDER_COLLISION | Colisión fmt | ≥2 proveedores comparten fmt y uno falla | Separar parsers o añadir heurísticas |

## Cómo ejecutar

```bash
# Requiere auto_learn_report.json (generado por evaluate_all.py)
python tools/classify_errors.py

# Solo los 20 más prioritarios
python tools/classify_errors.py --top 20

# Con un report específico
python tools/classify_errors.py --report path/to/report.json
```

## Cómo leer la salida

La prioridad combina: severidad × peso de categoría + impacto en
líneas, descontado por `autoapprove_rate` (proveedores que ya van bien
bajan de prioridad). Un proveedor con 99% auto pero muchos
`weak_synonym` queda por debajo de uno con 0% auto y `match_wrong`.

Artefacto: `auto_learn_taxonomy.json` — un JSON por proveedor con:

- `dominant_category`: el error más prioritario
- `severity`: HIGH / MEDIUM / LOW
- `categories`: lista ordenada de todos los errores detectados
- `priority_score`: score numérico para ordenar el backlog

## Baseline de taxonomía (sesión 9, abril 2026)

Distribución por categoría (82 proveedores):

| Categoría | Total | HIGH | MED | LOW |
|---|---|---|---|---|
| E7_SYNONYM_DRIFT | 67 | 45 | 17 | 5 |
| E8_AMBIGUOUS_LINK | 61 | 45 | 13 | 3 |
| E6_MATCH_WRONG | 48 | 32 | 16 | 0 |
| E5_TOTAL_HEADER | 47 | 0 | 39 | 8 |
| E1_PARSE_ZERO | 31 | 3 | 28 | 0 |
| E3_LAYOUT_COORDS | 26 | 13 | 13 | 0 |
| E10_PROVIDER_COLLISION | 23 | 0 | 0 | 23 |
| E2_PARSE_PARTIAL | 21 | 10 | 5 | 6 |
| E9_VALIDATION_FAIL | 12 | 7 | 4 | 1 |
| E4_OCR_BAD | 0 | 0 | 0 | 0 |

**Conclusión clave**: el error dominante del sistema NO es de parseo
sino de **matching/sinónimos**: E7 (67 proveedores) + E8 (61) + E6
(48). La solución transversal más impactante es **confirmar sinónimos
en masa** (Paso 7 del roadmap) y **golden set** (Paso 2) para calibrar
umbrales. Los problemas de parseo (E1+E2+E3 = 47 proveedores
afectados) son el segundo frente.

## Top penalties globales (sesión 9 — referencia)

1. `weak_synonym` 1841 (→ E7_SYNONYM_DRIFT)
2. `tie_top2_margin` 521 (→ E8_AMBIGUOUS_LINK)
3. `low_evidence` 282 (→ E8_AMBIGUOUS_LINK)
4. `variety_no_overlap` 262 (→ E6_MATCH_WRONG)
5. `foreign_brand` 216 (→ E6_MATCH_WRONG)

Para los top penalties actuales ver `auto_learn_penalties_top.json` y
[`../CLAUDE.md`](../CLAUDE.md) en la sección "Estado actual".
