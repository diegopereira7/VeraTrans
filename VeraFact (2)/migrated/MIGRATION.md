# VeraFact — Migración v4 (rediseño completo app.js + MySQL real)

Esta guía reemplaza a las anteriores. Cubre el rediseño completo del UI
(header v2, tabla v2, drawer v2) y los endpoints extras adaptados a MySQL.

---

## 1) Estructura del paquete

```
migrated/
├── MIGRATION.md          ← este archivo
├── assets/
│   └── veraleza-logo.png
└── web/
    ├── index.php                    ← sidebar + vistas + contenedores v2
    ├── api.extras.php               ← endpoints contra MySQL (get_db)
    └── assets/
        ├── tokens.css               ← paleta Veraleza + tokens
        ├── style.css                ← stat-cards, progress bars, drawer v2, badges
        ├── app.js                   ← TODO el render v2 (header+tabla+drawer)
        └── app.extras.js            ← hook para extensiones futuras
```

---

## 2) Instalación

### a) Copiar archivos

Copia sobre tu proyecto actual respetando rutas:

```
cp -r migrated/web/assets/*.css  tu-proyecto/web/assets/
cp -r migrated/web/assets/*.js   tu-proyecto/web/assets/
cp    migrated/web/index.php     tu-proyecto/web/index.php   # revisa diff
cp    migrated/web/api.extras.php tu-proyecto/web/api.extras.php
cp    migrated/assets/veraleza-logo.png tu-proyecto/web/assets/
```

### b) Activar api.extras.php

Añade al **inicio del switch** de `web/api.php` (ANTES de `case 'process_pdf'` etc.):

```php
require_once __DIR__ . '/api.extras.php';
```

El archivo usa `define('VF_EXTRAS_LOADED', true)` para ser idempotente.
Se apoya en `get_db()` de `db_config.php` que tú ya tienes.

### c) Asegurar que el logo está donde toca

El index.php espera `assets/veraleza-logo.png`. Si está en otro sitio, ajusta la ruta en `<img src>`.

---

## 3) Endpoints nuevos (MySQL)

Todos responden `Content-Type: application/json; charset=utf-8`.

### GET `api.php?action=recent_invoices&limit=5`

Últimas N facturas del `historial`.

```json
{"ok": true, "invoices": [
  {"fecha":"2025-01-14 10:22:03","invoice_key":"F-12345","provider":"CANTIZA",
   "provider_id":2222,"pdf":"cant_12345.pdf","lineas":42,"ok":38,
   "sin_match":2,"total_usd":1234.56}
]}
```

### GET `api.php?action=suggest_candidates`

Params: `species, variety, size, spb, provider_id, limit` (1..20, def 5).

Pipeline:
1. EN→ES de especie (`ROSES`→`ROSA`, etc.).
2. Prefiltro SQL por `familia` + LIKE por primera palabra de `variedad` (max 500 filas).
3. Scoring en PHP sobre las 500:
   - 60 pts max: palabras de `variety` contra `nombre+variedad+color+marca`
   - 15 pts: familia coincide
   - 10 pts: `tamano` == size
   - 8 pts: `paquete` == spb
   - 7 pts: `id_proveedor` coincide
4. Descarta < 25 pts, ordena desc, top-N.

```json
{"ok":true,"candidates":[
  {"articulo_id":12345,"articulo_id_erp":"47195","referencia":"F004675002",
   "nombre":"ROSA EC FREEDOM 50CM 25U","familia":"ROSA","tamano":"50",
   "paquete":25,"score":92}
]}
```

### GET `api.php?action=price_anomalies_timeline&articulo_id=NNN&days=90`

Join `facturas_lineas` × `historial`. Filtra últimos N días. Calcula z-score.

```json
{"ok":true,"timeline":[
  {"date":"2024-12-03","price":0.4800,"invoice":"F-11090","anomaly":false,"z":0.31}
],"stats":{"mean":0.52,"std":0.06,"count":24,"min":0.42,"max":0.71}}
```

**Anomalía** = `|z| > 2`. En el UI se pinta rojo en el sparkline del drawer.

---

## 4) Qué renderiza el nuevo app.js

### `renderHeader()` (tab Procesar factura)

- **Cabecera**: proveedor + factura + fecha + PDF + botón "Ver PDF"
- **5 stat-cards grandes**: Líneas · Match OK · Revisar · Sin match · Total USD
- **Banner de atención amarillo** con contador y botón "Revisar ahora →"
- **Barra de búsqueda** (placeholder: descripción/variedad/artículo/id_erp)
- **Filter tabs**: Todas · Revisar · OK (con contadores)

### `renderTable()`

Una fila por línea de factura con:

- `#` numerado 01, 02, 03…
- Descripción (variedad grande + raw en monospace) — chip MIX si `box_type` matchea `/mix/i`
- Especie · Variedad · Talla · SPB · Tallos · Precio · Total
- **Columna "Artículo VeraBuy"**:
  - Badge circular OR./EST./STD. (derivado de `match_method`/`origin`)
  - Nombre + id_erp/referencia
  - **Input `id_erp` editable** debajo — al `change` llama `lookup_article` y revincula
- **Columna "Match"**:
  - Chip OK/Revisar/Sin match
  - **Progress bar de confianza** (verde ≥90, amber 70-89, gris <70)
- Acciones: ojo (drawer) / check (candidatos → drawer)

### Drawer v2 (click en fila o botones acción)

Cabecera con **número circular de fila** (01, 02…), título = variedad,
subtitle = especie · talla · SPB, botón cerrar.

**4 secciones apiladas** (scroll vertical):

1. **Datos de la factura** — grid 2 cols (dt/dd): especie, variedad, talla, SPB, tallos, grado, precio, total, caja/label + descripción original en mono.
2. **Artículo vinculado** — tarjeta verde si hay match (nombre + ref + progress bar confianza), empty state si no.
3. **Candidatos sugeridos** (async, llama a `suggest_candidates`) — lista con nombre + meta (id_erp · familia · tamaño · SPB) + score % con barra + botón **Usar →** que revincula en sitio (sin cerrar drawer).
4. **Histórico de precio 90d** (async, llama a `price_anomalies_timeline`) — sparkline SVG con puntos en rojo para anomalías, tooltip por punto, stats min/max/media.

**Footer: 3 acciones**:

- **Ignorar línea** (secondary) — marca `match_status='ignored'`
- **Guardar sin match** (secondary) — llama `confirm_match` si hay `articulo_id`
- **Confirmar y guardar sinónimo** (primary) — llama `save_synonym` con `id_proveedor, nombre_factura, especie, talla, spb, id_articulo/id_articulo_erp`

Cierre por backdrop, botón X, o `Esc`.

---

## 5) Contratos respetados (no tocados)

app.js llama (GET salvo indicado) a:

- `process_pdf` (POST multipart) — flow principal de subida
- `lookup_article?id_erp=X` — al editar input id_erp por fila
- `suggest_candidates?...` — drawer sección 3
- `price_anomalies_timeline?articulo_id=&days=` — drawer sección 4
- `save_synonym` (POST JSON) — acción "Confirmar y guardar sinónimo"
- `confirm_match` (POST JSON) — acción "Guardar sin match"
- `correct_match` (POST JSON) — reservado, no invocado en UI todavía
- `generar_orden` (POST JSON) — botón "Generar Hoja de Orden"
- `history`, `history_detail` — tab Historial
- `get_synonyms` — tab Sinónimos
- `learned` — tab Auto-aprendizaje

El **normalizador de líneas** (`normalizeLines`) acepta **ambos** nombres de campo:
- inglés: `raw_description, species, variety, size, spb, stems, price_per_stem, total_line, articulo_id, articulo_id_erp, articulo_name, articulo_ref, match_status, match_method`
- español: `raw, especie, variedad, talla, paquete, tallos, precio_stem, total_linea, id_articulo, id_erp, nombre_articulo, referencia`

Así funciona sin importar cuál de los dos devuelva tu backend.

---

## 6) Campos opcionales reconocidos

Si tu backend los emite, el UI los aprovecha:

| Campo | Efecto |
|---|---|
| `origin` o `match_origin` | Badge OR./EST./STD. en tabla |
| `confidence` o `match_score` (0-1) | Progress bar de confianza |
| `box_type` con "mix" / "MIX" | Chip MIX en descripción |
| `is_mixed_child` / `es_hijo_mixto` | Excluye la línea del conteo de stat-cards |
| `group_key` | Reserva para agrupar hijos mixtos (tree-style) |
| `label` | Se muestra junto a `box_type` en drawer |
| `pdf_url` / `pdf_path` | Botón "Ver PDF" en cabecera |

Si no los emites, el UI degrada gracefully (sin crash, sin badges).

---

## 7) Diferencias con el pipeline viejo

| Antes | v4 |
|---|---|
| Tabla sin numeración | `#` en píldora gris 01/02… |
| Estado solo por chip | Chip + progress bar confianza |
| Métodos en texto | Badges circulares OR./EST./STD. |
| Edición artículo: solo drawer | Input `id_erp` inline por fila |
| Mixed box: fila plana | Chip MIX + preparado para tree |
| Stats en fila lineal | 5 stat-cards grandes + banner atención |
| Sin búsqueda en tabla | Input + filter tabs Todas/Revisar/OK |
| Drawer con lista de candidatos | Drawer con 4 secciones + 3 acciones pie |
| Candidatos JSON-based | MySQL: `articulos` + scoring real |
| Price history JSON | MySQL: join `facturas_lineas`+`historial` |

---

## 8) Checklist de migración

- [ ] `get_db()` disponible en `db_config.php`
- [ ] `require_once __DIR__ . '/api.extras.php';` añadido en `api.php`
- [ ] CSS copiados (`tokens.css`, `style.css`)
- [ ] `app.js` y `app.extras.js` copiados
- [ ] Logo en `web/assets/veraleza-logo.png`
- [ ] `index.php` sustituido (o fusionado con cuidado)
- [ ] Abrir `action=recent_invoices&limit=3` → devuelve JSON
- [ ] Abrir `action=suggest_candidates&species=ROSES&variety=FREEDOM&size=50` → devuelve candidatos
- [ ] Subir un PDF → ver stat-cards, tabla numerada, progress bars
- [ ] Click fila → drawer con 4 secciones
- [ ] Clicar "Usar →" en un candidato → línea queda vinculada
- [ ] Editar input `id_erp` de una fila → valida y revincula
- [ ] Filter tab "Revisar" → solo líneas con confianza <90%

---

## 9) Notas de performance

- `suggest_candidates` prefiltra a 500 filas por `familia` antes del scoring en PHP — sobre 44.751 artículos totales queda bajo 50ms típicos.
- Si notas lento, añade índice: `CREATE INDEX idx_familia ON articulos(familia);`
- Para `price_anomalies_timeline`, el join va por `numero_factura` — asegura que `historial.numero_factura` tiene su `UNIQUE KEY uq_factura` (ya lo tiene según tu schema).

---

## 10) Volver atrás

Para revertir solo la UI (sin tocar backend):
- Borra `api.extras.php` o comenta el `require_once` en `api.php`.
- Restaura `index.php`, `app.js`, `style.css`, `tokens.css` del backup previo.

El backend nunca se modifica — esta migración solo **añade** endpoints y reescribe la capa de presentación.
