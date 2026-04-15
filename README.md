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

Para el árbol completo y actualizado (módulos `src/`, parsers por
proveedor, pipeline end-to-end, convenciones), consulta
[`CLAUDE.md`](CLAUDE.md) → sección *"Cómo está organizado el código"*.
Se mantiene siempre al día porque forma parte del protocolo de cada
sesión de trabajo.

Entry points principales:
- `cli.py` — CLI interactivo
- `procesar_pdf.py` — procesamiento individual (JSON a stdout)
- `batch_process.py` — procesamiento masivo (Excel consolidado)
- `web/` — frontend PHP+JS

## Tests

```bash
python -m pytest tests/ -v
```

## Documentación

- [`CLAUDE.md`](CLAUDE.md) — estado real del código, arquitectura,
  convenciones, lecciones aprendidas, historial de sesiones.
- [`SETUP.md`](SETUP.md) — instalación detallada.
- [`docs/`](docs/README.md) — documentación operativa (roadmap,
  checklist, futuros manuales y golden set).
