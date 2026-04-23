# Migración VeraFact — Rediseño UI (v2)

Rediseño visual + features nuevos. Todo retrocompatible con `app.js` y `api.php` existentes.

## Contenido

```
migrated/
├── MIGRATION.md
└── web/
    ├── index.php              ← REEMPLAZA el tuyo (sidebar + nuevas estructuras)
    ├── api.extras.php         ← OPCIONAL — añade endpoint recent_invoices
    └── assets/
        ├── tokens.css         ← NUEVO (variables CSS — paleta Veraleza)
        ├── style.css          ← REEMPLAZA el tuyo
        ├── app.js             ← Copia idéntica del original (referencia)
        ├── app.extras.js      ← NUEVO — drawer, recientes, gráfico, empty states
        └── veraleza-logo.png
```

## Qué obtienes

### Visual
- Sidebar vertical fijo con logo Veraleza + 5 items agrupados (Procesamiento / Diccionario)
- Paleta Veraleza consistente: oliva, crema, tierra (sin azules random)
- Tipografía Inter + JetBrains Mono (tabular nums para cifras)
- Tabla líneas más compacta, con accent bars laterales por estado
- Spinner oliva, badges tierra, inputs que se "revelan" al hover

### Features nuevos (vía `app.extras.js`)
- **Drawer lateral** al clickar cualquier fila de la tabla de líneas → muestra raw, extracción, matching, evidencia, penalizaciones, errores, anomalía de precio
- **Facturas recientes** en la pantalla de upload (5 últimas, click → re-procesa)
- **Mini-gráfico de 30 días** en Historial (barras con hover-tooltip)
- **Empty states** ilustrados en tablas vacías
- **Master-detail en Sinónimos** — ya existía en tu `app.js` pero faltaba el CSS para que el panel derecho apareciera correctamente. Ahora funciona: click a fila → detalle editable

## Despliegue

```bash
# 1. Backup
cp web/index.php web/index.php.bak
cp web/assets/style.css web/assets/style.css.bak

# 2. Copia
cp migrated/web/index.php           web/index.php
cp migrated/web/assets/tokens.css   web/assets/tokens.css
cp migrated/web/assets/style.css    web/assets/style.css
cp migrated/web/assets/app.extras.js web/assets/app.extras.js

# 3. (Opcional) Endpoint facturas recientes
cp migrated/web/api.extras.php      web/api.extras.php
# Y al FINAL de web/api.php añade una línea:
#   require_once __DIR__ . '/api.extras.php';
# Si no lo haces, `app.extras.js` cae automáticamente a usar /history como fallback.

# 4. Hard refresh en navegador (Ctrl+Shift+R)
```

## Rollback

```bash
cp web/index.php.bak        web/index.php
cp web/assets/style.css.bak web/assets/style.css
rm web/assets/tokens.css web/assets/app.extras.js web/api.extras.php
# Y revertir el require_once en api.php si lo añadiste
```

## Compatibilidad

- **No toca** `app.js`, `api.php`, `config.php`, `src/`
- Todos los IDs y clases que el `app.js` usa siguen existiendo en el nuevo HTML
- Las funciones `synOpenDetail`, `synCloseDetail`, etc. (ya en tu `app.js`) ahora encuentran el `#synDetailPane` en el HTML y funcionan
- El drawer de línea usa `window._flatLines[idx]` que `renderResult()` ya popula
- Si `api.extras.php` no se activa, facturas recientes usa `/history` como fallback

## Personalización

Tokens en `assets/tokens.css`:
```css
:root {
  --primary:      var(--olive-500);   /* cambia para acentuar distinto */
  --bg:           #eeeadf;             /* fondo app */
}
```

## Endpoints extra (en `api.extras.php`)

Todos son opcionales — si no los activas, `app.extras.js` muestra "Endpoint no disponible" en lugar de romper.

| Endpoint | Qué hace | UI que lo usa |
|---|---|---|
| `GET ?action=recent_invoices&limit=5` | Últimas N facturas del historial | Cards en pantalla de upload |
| `GET ?action=suggest_candidates&species=&variety=&size=&spb=&provider_id=&limit=5` | Top-N artículos del catálogo por similitud de nombre + especie + talla (scoring simple) | Drawer de línea cuando no hay match — click "Usar →" rellena el input |
| `GET ?action=price_anomalies_timeline&articulo_id=X&days=90` | Serie de precios del artículo con detección z-score>2 | Drawer de línea cuando hay articulo_id — mini-gráfico de barras |

### Rutas a ajustar

`api.extras.php` busca datos en estas rutas (edita si tu proyecto usa otras):

```php
// Invoice history
__DIR__ . '/../datasets/invoice_history.json'
__DIR__ . '/../data/invoice_history.json'

// Catálogo de artículos (para candidatos)
__DIR__ . '/../datasets/articulos.json'
__DIR__ . '/../data/articulos.json'
__DIR__ . '/../datasets/catalog.json'

// Historial de precios (opcional, usa invoice_history como fallback)
__DIR__ . '/../datasets/price_history.json'
__DIR__ . '/../data/price_history.json'
```

### Cómo activar

Al final de tu `web/api.php` añade:
```php
require_once __DIR__ . '/api.extras.php';
```

Si algún endpoint no encaja con tu backend real (p.ej. tienes una DB en lugar de JSON), usa los archivos como plantilla y reimpleméntalos contra tu modelo. La interfaz JSON de salida está documentada en el docstring de cada bloque.
