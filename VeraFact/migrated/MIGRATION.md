# Migración VeraFact — Rediseño UI (Sidebar + Paleta Veraleza)

Este paquete contiene la nueva capa visual del frontend **sin modificar la lógica ni los endpoints**. Solo cambia `index.php` (estructura) y los estilos. `app.js` queda idéntico al original.

## Contenido

```
migrated/web/
├── index.php              ← REEMPLAZA el tuyo
├── assets/
│   ├── tokens.css         ← NUEVO (variables CSS)
│   ├── style.css          ← REEMPLAZA el tuyo
│   ├── app.js             ← Copia idéntica del original (por seguridad)
│   └── veraleza-logo.png  ← Copia (ya existente)
```

Lo que NO toco (quedan tus archivos tal cual):
- `api.php`, `config.php`
- `src/` (backend Python)
- Todo lo demás

---

## Qué cambia visualmente

| Antes | Después |
|---|---|
| Header horizontal con 5 tabs | **Sidebar izquierdo** fijo, 2 secciones (Procesamiento / Diccionario) |
| Paleta oliva + azules random en gradientes | **Paleta Veraleza consistente**: oliva `#8e8b30`, crema `#eeeadf`, tierra, sin azules |
| Tabla líneas 13px padding 8-12px | Tabla **más compacta y legible**: 12.5px, padding ajustado, franjas de estado con barra lateral en vez de fondos pastel |
| Fuente system default | **Inter + JetBrains Mono** para números |
| `.row-*` con fondos pastel fuertes | Fondos suaves + **accent bar** lateral por estado (error / warn / rescue / mixed) |
| Badges grandes con emojis de color | Badges tierra, padding reducido, jerarquía clara |
| Spinner azul | Spinner oliva coherente |
| Sin tipografía monoespaciada para números | **Tabular nums** en cifras, precios, totales |
| Header factura inputs con borde duro | Inputs que se "revelan" al hover/focus — lectura más limpia |

---

## Despliegue (paso a paso)

### 1. Haz backup
```bash
cp web/index.php       web/index.php.bak
cp web/assets/style.css web/assets/style.css.bak
```

### 2. Copia los archivos del paquete
```bash
cp migrated/web/index.php           web/index.php
cp migrated/web/assets/tokens.css   web/assets/tokens.css
cp migrated/web/assets/style.css    web/assets/style.css
# app.js no necesita copiarse (es idéntico), pero no estorba
```

### 3. Limpia caché del navegador
Ctrl+Shift+R en el navegador, o abre en modo incógnito. El `?v=filemtime()` en los `<link>` debería forzarlo automáticamente.

### 4. Verifica
- [ ] El sidebar aparece con logo Veraleza + 5 items
- [ ] Click en cada tab cambia la vista sin recargar
- [ ] Subir un PDF procesa y muestra resultado con nuevos estilos
- [ ] Historial carga y se ve bien
- [ ] Sinónimos carga la tabla master
- [ ] Importación masiva: drop-zone, progreso, resultados
- [ ] Auto-aprendizaje: tabla de parsers

---

## Rollback

Si algo falla:
```bash
cp web/index.php.bak        web/index.php
cp web/assets/style.css.bak web/assets/style.css
rm web/assets/tokens.css
```

Listo. Sin pérdida de datos porque no se tocó nada de backend.

---

## Nota técnica

El `app.js` original sigue funcionando **sin un solo cambio** porque:

- Los **IDs clave** (`#tab-upload`, `#tab-batch`, `#tab-history`, `#tab-synonyms`, `#tab-learned`, `#linesTable`, `#invoiceHeader`, `#statsBar`, `#batchTable`, `#historyTable`, `#synTable`, `#learnedTable`, `#pendingTable`, etc.) **no cambiaron**.
- Las **clases funcionales** (`.nav-btn`, `.tab`, `.active`, `.hidden`, `.badge`, `.badge-ok`, `.badge-sin-match`, `.badge-fuzzy`, `.badge-manual`, `.row-sin-match`, `.row-low-conf`, `.row-has-error`, `.row-rescue`, `.row-ambiguous`, `.row-sin-parser`, `.row-mixed-parent`, `.row-mixed-child`, `.edit-input`, `.edit-line`, `.edit-art`, `.edit-header`, `.conf-dot`, `.dot-err`, `.dot-price`, `.batch-skipped`, `.color-variety`, `.badge-label`, `.mixed-desc`) **están todas soportadas** en el nuevo CSS.
- Los **inputs ocultos** (`batchZipInput`, `batchFolderInput`, `batchPdfInput`) siguen en el DOM.
- El bloque PHP que inyecta `window.PROVIDER_NAMES` se conserva intacto.

### Estructura DOM comparada

| Antes | Ahora |
|---|---|
| `<header class="main-header">…<nav>.nav-btn</nav></header>` | `<aside class="sidebar">…<nav>.nav-btn.nav-item</nav></aside>` |
| `<main>` | `<main class="main">` |
| `<section class="tab" id="tab-upload">` | Igual |
| `<h2>Procesar Factura</h2>` dentro del tab | `<div class="pageheader"><h1>Procesar factura</h1><p>…subtítulo…</p></div>` |

El único cambio de clase que sí afecta: las tablas ahora también responden a `.t` (opcional). El selector `table` solo sigue funcionando igual.

---

## Personalización rápida

Todos los tokens están en `assets/tokens.css`. Si quieres cambiar el acento:

```css
:root {
  --primary:      var(--olive-500);  /* cambia a #006a6a para ir salvia-azul */
  --primary-dark: var(--olive-600);
  --primary-soft: var(--olive-100);
}
```

O jugar con la densidad de tabla en `style.css`:

```css
table.t td { padding: 8px 8px; }  /* original */
/* pon 6px 6px para más compacto */
/* pon 10px 12px para más aire */
```

---

## Próximos pasos sugeridos (no incluidos en este paquete)

1. **Sinónimos master-detail real**: el HTML ya trae `#synDetailPane`, pero `app.js` actual aún no lo usa. Cuando quieras, te paso el patch de `loadSynonyms` + `renderSynonyms` para click-a-fila → detalle en el panel derecho.
2. **Dot badges compactos** para la columna Match de la tabla de líneas: sustituir badges de texto por círculos con iniciales (`F` fuzzy, `M` manual…) para ganar ancho.
3. **Modo oscuro**: tokens.css ya está estructurado para soportar un `[data-theme="dark"]` override.

Pídemelos cuando estén las prioridades claras.
