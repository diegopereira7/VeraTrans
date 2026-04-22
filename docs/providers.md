# Proveedores

Información consolidada por proveedor: estado global, parsers
aprendidos, colisiones conocidas, filtros de lote y ubicación de las
muestras de entrenamiento.

---

## Estado global

- **84 REGISTRADO_OK** — detectados y con parser funcional
- **0 REGISTRADO_STUB** — todos los stubs convertidos
- **Buckets en benchmark (sesión 10h)**: OK **79** · NO_PARSEA
  **3** (SAYONARA, CEAN GLOBAL, NATIVE BLOOMS) · TOTALES_MAL 0 ·
  NO_DETECTADO 1 (PONDEROSA)
- **8 LOGISTICA** — filtrados por SKIP_PATTERNS del batch:
  `ALLIANCE`, `DSV`, `EXCELE CARGA`, `LOGIZTIK`, `REAL CARGA`,
  `SAFTEC`, `VERALEZA` (la buyer), `FESO` (EXCELLENT CARGO SERVICE
  SAS, carguero)

## Parsers auto_*

| Parser | Proveedores que lo usan | Notas |
|---|---|---|
| `auto_farin` | FARIN | layout lineal simple |
| `auto_qualisa` | QUALISA, BELLAROSA | template SaaS compartido |
| `auto_agrinag` | AGRINAG | parent/sub-línea para mixed box |
| `auto_natuflor` | NATUFLOR | dual: colombiano + SaaS (delega en auto_agrinag) |
| `auto_campanario` | GREENGROWERS, EL CAMPANARIO | template Lasso; código "R14 ZAIRA"/"VERALEZA" antes de variety |
| `auto_floreloy` | FLORELOY | parent + data en líneas separadas |
| `auto_sanjorge` | SAN JORGE | decimal coma; marcador 'T' entre price y total |
| `auto_milagro` | MILAGRO | sub-líneas "Milagro" con stems reales; skip parents MIXED |
| `auto_mountain` | MOUNTAIN | usa `pdfplumber.extract_words()` con x-coords para mapear CM |
| `auto_native` | NATIVE BLOOMS | dual: roses + tropical foliage; heurística para decimal/miles con coma |
| `auto_sanfrancisco` | SAN FRANCISCO | Hydrangeas; size=60 default, spb=1 |
| `auto_zorro` | ZORRO | single-sample overfit acceptable; tolera OCR 'l'→'1', 'ASSORTEO'→'ASSORTED' |
| `auto_cean` | CEAN GLOBAL | factura electrónica COL; colores inglés→español via `translate_carnation_color` |
| `auto_elite` | ELITE | Alstroemeria parent + sub-líneas solo-stems heredando price |
| `auto_conejera` | FLORES LA CONEJERA | factura electrónica COL; translate_carnation_color para colores EN→ES |
| `auto_agrosanalfonso` | AGROSANALFONSO, GLAMOUR | template `I`-separado; GLAMOUR = marca comercial de AgroSanAlfonso |
| `auto_rosabella` | ROSABELLA | layout lineal simple; "ABC" abreviatura de "ASSORTED" |

## Colisiones y ambigüedades

- **PONDEROSA = VERDES LA ESTACION** (mismo negocio, dos NITs:
  900.408.822 y 900.428.540). Fusionados bajo `verdesestacion` en
  config, id=11748. Layout cambió recientemente —
  `VerdesEstacionParser` soporta variantes A (legacy) y B (actual).
- **STAMPSY / STAMPSYBOX** → mismo id=2220, mismo fmt=mystic.
- **MILAGRO** (original stub id 90025) renombrado a `milagro_old`; el
  real es `milagro_finca` id=2652 (EL MILAGRO DE LAS FLORES SAS).
- **UNIQUE** se desdobló: `unique` (id 90041, UNIQUE FLOWERS) y
  `unique_export` (id 7908, UNIQUE EXPORT SAS) — dos empresas
  distintas.
- **GLAMOUR** se detecta como "Agro San Alfonso" — es la marca
  comercial de esa finca (layout idéntico, correcto).

## SKIP_PATTERNS del batch

En [batch_process.py:297](../batch_process.py#L297) — filenames que
contienen estos substrings NO son tratados como facturas.
Logísticas/aduanas:

```python
'DUA', 'NYD', 'ALLIANCE', 'FULL', 'GUIA', 'PREALERT', 'PRE ALERT', 'REAL CARGA',
'SAFTEC', 'EXCELLENT', 'EXCELLENTE', 'BTOS', 'PARTE', 'CORRECTA', 'LINDA', 'SLU',
'DSV', 'LOGIZTIK', 'EXCELE', 'EXCELE CARGA',
```

**NO incluir `JORGE`** — falso positivo con el proveedor SAN JORGE.

## Carpeta de entrenamiento

Ruta del operador actual (Ángel Panadero):

```
C:\Users\diego.pereira\Desktop\DOC VERA\FACTURAS IMPORTACION\PROVEEDORES
```

Configurable vía variable de entorno `VERABUY_PROVIDERS_DIR` cuando el
pipeline lo soporte. Contiene subcarpeta por proveedor con 5 facturas
nuevas + 2 antiguas (para regresión). `marca_prov.txt` en la raíz
mapea `FOLDER_NAME|id_proveedor` (IDs de tabla `proveedores` en la BD
VeraBuy).

## Triage histórico (sesión 3)

Referencia histórica — la métrica actual vive en
[`../CLAUDE.md`](../CLAUDE.md) y se regenera con
`python tools/evaluate_all.py`.

Corriendo [tools/evaluate_all.py](../tools/evaluate_all.py) sobre las
82 carpetas (sesión 3, 2026-04-15):

- **OK (24)**: detectado + parseado + totales cuadran. No tocar.
- **TOTALES_MAL (22)**: parsea bien pero `header.total` no se extrae
  del PDF (muchos parsers no tienen regex de total de cabecera).
  Cosmético: la suma de líneas está bien, solo falla la validación
  cruzada. Impacto real bajo.
- **NO_PARSEA (36)**: alguna muestra retorna 0 líneas o <60% parse.
  Prioridad alta. Incluye CANTIZA (3/5), COLIBRI (5/5 pero totales
  mal), DAFLOR (3/5), GOLDEN (ok), MYSTIC (1/5), LATIN (3/5), etc.
  Requiere revisión caso por caso.
- **NO_DETECTADO (0)**: todos los patterns matchean.

Ver [`../auto_learn_report.json`](../auto_learn_report.json) para
detalle por proveedor y muestra (qué PDFs fallan, qué líneas rescata
el fallback).
