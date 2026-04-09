# VeraBuy Traductor - Guia de Instalacion y Funcionamiento

## Que es

Sistema que traduce PDFs de facturas de proveedores de flores en articulos internos de VeraBuy.
Recibe un PDF, detecta el proveedor, parsea las lineas de la factura, normaliza los datos (especie, variedad, talla, tallos, precio) y hace match contra el catalogo de articulos de VeraBuy.

El operador revisa el resultado en la interfaz web, corrige lo que haga falta, y genera una hoja de orden que se guarda en MySQL.

---

## Requisitos

### Software

| Componente | Version minima | Notas |
|------------|---------------|-------|
| Python | 3.10+ | Con pip |
| WAMP (Apache + PHP + MySQL) | PHP 7.4+, MySQL 5.7+ | O cualquier stack Apache+PHP+MySQL |
| Navegador | Chrome/Edge moderno | |

### Dependencias Python

```
pip install -r requirements.txt
```

Contenido de `requirements.txt`:
- `pdfplumber` - Extraccion de texto de PDFs
- `tabulate` - Formateo de tablas (CLI)
- `openpyxl` - Exportacion a Excel
- `pymysql` - Conexion a MySQL desde Python

> **Nota**: `pymysql` no esta en requirements.txt, hay que agregarlo o instalarlo aparte:
> `pip install pymysql`

### php.ini (ajustes necesarios)

Para que la importacion masiva funcione, verificar estos valores en `php.ini`:

```ini
max_file_uploads = 500
upload_max_filesize = 50M
post_max_size = 256M
max_execution_time = 300
```

---

## Base de datos MySQL

### Conexion

La conexion se configura en dos sitios (deben coincidir):

**PHP** - `web/db_config.php`:
```php
define('DB_HOST', 'localhost');
define('DB_USER', 'root');
define('DB_PASS', '');
define('DB_NAME', 'verabuy');   // <-- Cambiar al nombre de BD real
define('DB_PORT', 3306);
```

**Python** - `src/db.py`:
```python
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '',
    'database': 'verabuy',      # <-- Debe coincidir con PHP
    'port': 3306,
}
```

### Tablas necesarias

El sistema usa estas tablas en MySQL:

| Tabla | Descripcion | Obligatoria |
|-------|-------------|-------------|
| `articulos` | Catalogo de articulos VeraBuy (id, nombre, especie, variedad, talla, etc.) | Si |
| `proveedores` | Registro de proveedores con sus IDs | Si |
| `sinonimos` | Diccionario de sinonimos (factura -> articulo) | Si |
| `historial` | Historial de facturas procesadas | Si |
| `hoja_orden` | Cabecera de ordenes generadas | Si |
| `ordenes` | Lineas de cada orden | Si |

> Las tablas `sinonimos` e `historial` tienen dual-write: se guardan en MySQL **y** en archivos JSON (`sinonimos_universal.json`, `historial_universal.json`) como fallback.

---

## Configuracion

### web/config.php

```php
// Ruta al ejecutable de Python - CAMBIAR segun entorno
define('PYTHON_BIN', 'C:/ruta/a/python.exe');

// Directorio de subida temporal de PDFs
define('UPLOAD_DIR', __DIR__ . '/uploads');
```

**Importante**: `PYTHON_BIN` debe apuntar al ejecutable de Python donde estan instaladas las dependencias.

### Directorios que se crean automaticamente

El sistema necesita estos directorios (los crea si no existen, pero verificar permisos):

```
web/uploads/          # PDFs subidos temporalmente (se borran cada 24h)
batch_status/         # Estado de procesamiento masivo
batch_results/        # Resultados Excel de lotes
batch_uploads/        # PDFs de importacion masiva
```

---

## Arquitectura

```
verabuy-traductor/
|
|-- procesar_pdf.py          # Punto de entrada: recibe PDF, devuelve JSON
|-- batch_process.py         # Procesamiento masivo de multiples PDFs
|-- cli.py                   # Interfaz de linea de comandos (opcional)
|
|-- src/
|   |-- config.py            # Constantes, rutas, registro de proveedores (49 proveedores)
|   |-- pdf.py               # Extraccion de texto y deteccion de proveedor
|   |-- models.py            # Dataclasses: InvoiceLine, InvoiceHeader
|   |-- articulos.py         # Carga del catalogo de articulos desde MySQL/SQL
|   |-- sinonimos.py         # Diccionario de sinonimos (JSON + MySQL)
|   |-- matcher.py           # Motor de matching (7 etapas)
|   |-- historial.py         # Registro de facturas procesadas
|   |-- orden.py             # Generacion de hoja_orden + ordenes en MySQL
|   |-- db.py                # Capa de acceso a MySQL con fallback a JSON
|   |
|   |-- parsers/             # Un parser por proveedor o grupo de proveedores
|   |   |-- __init__.py      # Registro FORMAT_PARSERS
|   |   |-- otros.py         # 40 parsers de proveedores menores
|   |   |-- alegria.py       # Alegria, Latinafarms
|   |   |-- golden.py        # Golden Flowers, Benchmark
|   |   |-- colibri.py       # Colibri
|   |   |-- cantiza.py       # Cantiza
|   |   |-- latin.py         # Latin, con formatos A/B/C
|   |   |-- agrivaldani.py   # Agrivaldani
|   |   |-- life.py          # Life Flowers
|   |   |-- mystic.py        # Mystic Flowers
|   |   |-- sayonara.py      # Sayonara
|   |
|   |-- learner/             # Auto-aprendizaje de parsers (experimental)
|       |-- generador.py     # Generacion automatica de reglas
|       |-- validador.py     # Validacion de parsers generados
|       |-- ...
|
|-- web/
|   |-- index.php            # UI principal (single-page con tabs)
|   |-- api.php              # API REST que conecta JS <-> Python
|   |-- config.php           # Configuracion de rutas y limites
|   |-- db_config.php        # Configuracion de conexion MySQL para PHP
|   |-- assets/
|       |-- app.js           # Logica frontend (tabs, tablas, formularios)
|       |-- style.css        # Estilos (tema verde VeraBuy)
|
|-- sinonimos_universal.json # Diccionario de sinonimos (fallback JSON)
|-- historial_universal.json # Historial de procesamiento (fallback JSON)
|-- requirements.txt         # Dependencias Python
```

---

## Flujo de procesamiento

### Factura individual

```
Usuario sube PDF
       |
       v
  index.php (JS) ---POST---> api.php?action=process
       |                          |
       |                     Ejecuta: python procesar_pdf.py <pdf>
       |                          |
       |                     1. detect_provider() - identifica proveedor por texto
       |                     2. Parser del proveedor extrae lineas
       |                     3. Matcher busca articulo VeraBuy para cada linea:
       |                        a) Sinonimo existente (exacto)
       |                        b) Match por marca del proveedor
       |                        c) Match por nombre esperado
       |                        d) Auto-matching adicional
       |                        e) Fuzzy match (>90% similitud)
       |                        f) sin_match
       |                     4. Devuelve JSON con header + lines
       |                          |
       v                          v
  Muestra resultado <-------- JSON response
       |
  Usuario revisa y corrige:
    - Cambiar articulo (por ID o codigo F)
    - Editar talla, SPB, tallos, precio
    - Eliminar lineas no deseadas
       |
       v
  Click "Generar Hoja de Orden"
       |
       v
  api.php?action=generar_orden ---> MySQL: hoja_orden + ordenes
```

### Importacion masiva

```
Usuario sube ZIP / carpeta / multiples PDFs
       |
       v
  api.php?action=batch_upload ---> Guarda en batch_uploads/
       |
  Ejecuta: python batch_process.py <directorio> <batch_id>
       |
  Procesa cada PDF secuencialmente
  Escribe progreso en batch_status/<id>.json
       |
       v
  Frontend hace polling de batch_status
  Al terminar muestra tabla resumen con todas las facturas
```

---

## Tabs de la interfaz web

| Tab | Funcion |
|-----|---------|
| **Procesar Factura** | Subir un PDF, ver resultado, editar lineas, generar orden |
| **Importacion Masiva** | Subir multiples PDFs (ZIP/carpeta), ver progreso y resultados |
| **Historial** | Tabla con todas las facturas procesadas |
| **Sinonimos** | Diccionario master-detail: buscar, filtrar, editar, anadir sinonimos |
| **Auto-Aprendizaje** | Parsers generados automaticamente (experimental) |

---

## Sistema de sinonimos

Los sinonimos son la memoria del sistema. Cuando una linea de factura se matchea con un articulo, se guarda un sinonimo con clave compuesta:

```
{provider_id}|{species}|{variety}|{size}|{stems_per_bunch}|{grade}
```

Ejemplo: `2222|ROSES|FREEDOM|50|25|`

La proxima vez que aparezca la misma combinacion del mismo proveedor, el match es instantaneo.

### Origenes de sinonimos

| Origen | Descripcion |
|--------|-------------|
| `manual` / `manual-web` | Creado por el usuario en la web |
| `revisado` | Confirmado manualmente tras revision |
| `auto-matching` | Generado automaticamente por el matcher |
| `auto-fuzzy` | Generado por similitud fuzzy (>90%) |
| `auto-marca` | Match por marca del proveedor |
| `auto-color-strip` | Match quitando prefijo de color |
| `auto-delegacion` | Delegado a otro proveedor |

---

## API endpoints (api.php)

| Accion | Metodo | Descripcion |
|--------|--------|-------------|
| `process` | POST | Procesar un PDF |
| `synonyms` | POST | Obtener todos los sinonimos |
| `save_synonym` | POST | Guardar/actualizar un sinonimo |
| `update_synonym` | POST | Actualizar sinonimo existente |
| `delete_synonym` | POST | Eliminar un sinonimo |
| `history` | POST | Obtener historial |
| `reprocess` | POST | Reprocesar una factura del historial |
| `lookup_article` | GET | Buscar articulo por ID o codigo F |
| `generar_orden` | POST | Crear hoja de orden + lineas |
| `batch_upload` | POST | Subir lote (ZIP) |
| `batch_upload_pdfs` | POST | Subir lote (PDFs sueltos) |
| `batch_status` | GET | Estado de procesamiento del lote |
| `batch_download` | GET | Descargar Excel de resultados |
| `learned_parsers` | GET | Listar parsers auto-aprendidos |
| `pending_review` | GET | Parsers pendientes de revision |
| `toggle_parser` | POST | Activar/desactivar parser aprendido |

---

## Proveedores soportados

El sistema tiene **49 parsers** que cubren proveedores como: Mongibello, Elite, Don Eusebio, Turflor, Unique, Ponderosa, Grupo Andes, Maxiflor, EQR, Vuelven, Colibri, Cantiza, Agrivaldani, Benchmark/Golden, Latin, Alegria, Life, Mystic, Sayonara, entre otros.

Cada proveedor tiene un `id` unico en `src/config.py` y uno o mas formatos de factura reconocidos.

---

## Herramientas auxiliares

| Script | Uso |
|--------|-----|
| `auditar_sinonimos.py` | Genera Excel para auditar sinonimos sospechosos |
| `importar_sinonimos.py` | Importa correcciones desde Excel auditado |
| `exportar_excel.py` | Exporta sinonimos e historial a Excel |
| `cli.py` | Interfaz de linea de comandos para procesar PDFs sin web |

---

## Notas para integracion en VeraBuy

1. **La carpeta `web/`** debe ser accesible via Apache (DocumentRoot o alias)
2. **Python debe ser accesible** desde el servidor web (la ruta se configura en `web/config.php`)
3. **La BD** puede ser la misma de VeraBuy; solo necesita las tablas listadas arriba
4. **Los JSON** (`sinonimos_universal.json`, `historial_universal.json`) deben tener permisos de escritura por el proceso PHP/Python
5. **Las facturas subidas** se borran automaticamente cada 24 horas (configurable en `api.php`)
6. **El tema visual** ya usa los colores de VeraBuy (verde #8e8b30, fondo #e5e2dc)
