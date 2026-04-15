# VeraBuy Traductor

Sistema de traducción de facturas PDF de proveedores de flores. Extrae líneas de producto, las vincula con artículos de la BD de VeraBuy, y mantiene un diccionario de sinónimos entrenado.

> **Documentación operativa**: este README cubre instalación y uso básico.
> Para entender el **estado real del pipeline** (arquitectura, convenciones,
> lecciones, historial) → [`CLAUDE.md`](CLAUDE.md).
> Para **planificar y seguir trabajo futuro** → [`docs/`](docs/README.md).

## Requisitos

- Python 3.12+
- WAMP (Apache + PHP) para la interfaz web
- Dependencias: `pip install -r requirements.txt`

## Instalación

```bash
git clone <repo>
cd verabuy-traductor
pip install -r requirements.txt
```

Para la interfaz web, crear symlink en WAMP:
```cmd
mklink /D C:\wamp64\www\verabuy C:\verabuy-traductor
```

Configurar la ruta de Python en `web/config.php`:
```php
define('PYTHON_BIN', 'C:/ruta/a/python.exe');
```

## Uso

### Modo CLI (entrenamiento interactivo)
```bash
python cli.py
```

### Modo Web
Abrir `http://localhost/verabuy/web/` y subir un PDF.

### Procesar un PDF desde consola
```bash
python procesar_pdf.py facturas/CANTIZA.pdf
```

## Estructura

```
src/
├── config.py          Constantes, rutas, proveedores, mapas de color
├── models.py          InvoiceHeader, InvoiceLine, excepciones
├── articulos.py       Carga e indexación de artículos desde dump SQL
├── sinonimos.py       Diccionario de sinónimos persistente
├── historial.py       Registro de facturas procesadas
├── matcher.py         Pipeline de matching (5 etapas) + postproceso
├── pdf.py             Extracción de texto PDF y detección de proveedor
└── parsers/           27 parsers específicos por proveedor
    ├── __init__.py    Registry FORMAT_PARSERS
    ├── cantiza.py     CantizaParser
    ├── colibri.py     ColibriParser
    ├── golden.py      GoldenParser
    ├── latin.py       LatinParser
    └── ...            (ver src/parsers/ para la lista completa)

cli.py                 Entry point CLI interactivo
procesar_pdf.py        Entry point web (JSON a stdout)
exportar_excel.py      Exportación a Excel
web/                   Frontend PHP/JS/CSS
```

## Tests

```bash
python -m pytest tests/ -v
```
