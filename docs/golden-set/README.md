# Golden set — VeraBuy Traductor

Carpeta reservada para el **corpus de verdad-terreno** que medirá la
*accuracy real* del sistema (parseo correcto + linking ERP correcto),
no solo `parsed_any` o `totals_ok` como hace el benchmark actual.

## Estado

**Vacía a propósito.** Esta carpeta se rellena cuando se ejecute el
**Paso 2 del [`roadmap`](../roadmap/roadmap.md)** ("Crear un golden
set revisado manualmente"). El prompt del paso 2 debe dejar:

- estructura definitiva de esta carpeta (formato JSON, naming, etc.)
- un helper para bootstrapear anotaciones desde la salida actual
- un comparador (`tools/validate_against_golden.py` o similar)
- al menos 1 factura anotada como ejemplo completo

Hasta entonces solo existe este README para que no se confunda con
una carpeta olvidada.

## Qué irá aquí (esperado)

Una estructura tipo:

```
docs/golden-set/
├── README.md
├── facturas/
│   ├── MYSTIC/
│   │   ├── 01-MYSTIC2.pdf          (symlink o copia del PDF)
│   │   └── 01-MYSTIC2.gold.json    (anotaciones: proveedor, líneas,
│   │                                variety/size/origin/articulo_id
│   │                                esperados por cada línea)
│   └── ...
└── tools/                           (si conviene, scripts locales
                                     de esta carpeta)
```

## Convenciones tentativas

- Formato JSON (no YAML) por coherencia con el resto del repo.
- Número mínimo objetivo: 2–3 facturas por proveedor de alto volumen.
- Prioridad: proveedores con mayor `NO_PARSEA` o mayor riesgo de
  falso positivo semántico en el matching.
- Nunca commitear PDFs reales con datos sensibles — usar copias
  anonimizadas si hace falta.

## Cómo se usará

Una vez existan anotaciones, el comparador debería devolver, por
factura:

- `parse_accuracy_per_field` (variety, size, stems, price, total…)
- `link_accuracy` (artículo_id coincide con anotación)
- `full_match_rate` (línea completamente correcta)
- `top_discrepancies` para priorizar el siguiente parser a arreglar

Esa salida alimenta la Fase 2 del [`checklist`](../roadmap/checklist.md)
y cualquier auditoría posterior del matcher (cierre del Paso 6).
