"""Tests de regresión para los fixes de parsers en sesiones 12o–12r.

Cada test es **invariante**: verifica un comportamiento que un fix
concreto añadió y debe mantenerse contra futuros cambios. Si un test
falla, sospecha que el regex se rompió por una "limpieza" estética o
una refactorización que asumía un comportamiento legacy.

Política:
  - Cada test cita la sesión que introdujo el fix.
  - Cada test usa un PDF real del `batch_uploads/<batch_id>/` del
    operador (no se mockea — los PDFs ya cubren los casos edge).
  - Sólo se prueba el parser, no el matcher (los IDs cambian al
    reimportar catálogo).

**Nota sesión 12r**: los tests de las sesiones 12g–12n se eliminaron
porque sus batches PDF fueron purgados; los fixes están protegidos por
el benchmark global (`tools/evaluate_all.py`) y el golden eval
(`tools/evaluate_golden.py`). Si en el futuro hace falta proteger
explícitamente algún fix antiguo contra regresiones, copia el PDF
relevante a `tests/fixtures/` y añade el test contra esa ruta fija.

Ejecución:
    python -m unittest tests.test_parser_regressions
    python -m unittest tests.test_parser_regressions.TestMonterosaParser
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.pdf import detect_provider  # noqa: E402
from src.parsers import FORMAT_PARSERS  # noqa: E402

# Batch del operador (sesiones 12o–12r). Si se purga, los tests
# skippean automáticamente.
_BATCH_DIRS = [
    _ROOT / 'batch_uploads' / '20260507144258_a5e9b107',  # 12o–12r
]
BATCH = next((b for b in _BATCH_DIRS if b.exists()), _BATCH_DIRS[0])


def _parse(pdf_name: str):
    """Helper: ejecuta el parser para un PDF y devuelve (header, lines, pdata).

    Busca el PDF en cualquiera de los batches conocidos. Skip si no
    está disponible.
    """
    pdf_path = next(
        (b / pdf_name for b in _BATCH_DIRS if (b / pdf_name).exists()),
        None,
    )
    if pdf_path is None:
        raise unittest.SkipTest(f'Sample no disponible: {pdf_name}')
    pdata = detect_provider(str(pdf_path))
    if not pdata:
        raise AssertionError(f'detect_provider devolvió None para {pdf_name}')
    pdata['pdf_path'] = str(pdf_path)
    parser = FORMAT_PARSERS.get(pdata['fmt'])
    if not parser:
        raise AssertionError(f'Sin parser para fmt={pdata["fmt"]}')
    header, lines = parser.parse(pdata['text'], pdata)
    return header, lines, pdata


class TestTessaParser(unittest.TestCase):
    """Sesión 12j: bunches confundidos con spb."""

    def test_mondial_spb_25_no_10(self):
        """MONDIAL/EXPLORER 70cm en TESSA debe tener spb=25, no spb=10.

        Antes de 12j el regex asignaba `group(4)` (bunches) a spb.
        Con el fix, spb se calcula como `stems // bunches`.
        """
        _, lines, _ = _parse('TESSA.pdf')
        anomalias = [l for l in lines
                     if l.species == 'ROSES'
                     and l.variety.upper() in ('MONDIAL', 'EXPLORER',
                                                'NECTARINE', 'FREEDOM')
                     and l.stems_per_bunch == 10]
        self.assertEqual(len(anomalias), 0,
                         f'Rosas estándar con spb=10 (rescates del operador): '
                         f'{[(l.variety, l.size) for l in anomalias]}')

    def test_bunches_poblados(self):
        """`InvoiceLine.bunches` debe estar poblado, no en 0."""
        _, lines, _ = _parse('TESSA.pdf')
        with_bunches = [l for l in lines if l.bunches > 0]
        self.assertGreater(len(with_bunches), 0,
                           'bunches debe estar poblado tras 12j '
                           '(antes quedaba en 0 por defecto)')


class TestMalimaLabel(unittest.TestCase):
    """Sesión 12n: MALIMA siempre exporta a EUROPA → label='EUROPA'."""

    def test_europa_va_a_label(self):
        """MALIMA.pdf: todas las líneas tienen label=EUROPA (hardcoded)."""
        _, lines, _ = _parse('MALIMA.pdf')
        self.assertGreater(len(lines), 0)
        for l in lines:
            self.assertEqual(l.label, 'EUROPA',
                             f'línea {l.variety[:30]}: label debe ser '
                             f'EUROPA, no {l.label!r}')


class TestMultifloraCarnationComma(unittest.TestCase):
    """Sesión 12o: total_units con coma de miles (3,220) en Multiflora."""

    def test_clavel_531(self):
        """MULTIFLORA.pdf: línea Clavel `7 Half tall 460 3,220 0.1650 531.30 3.50`.

        Antes el regex `(\\d+)\\s+(\\d+)` no aceptaba `3,220` y la
        línea de claveles ($531.30) se perdía silenciosa.
        """
        h, lines, _ = _parse('MULTIFLORA.pdf')
        carns = [l for l in lines if l.species == 'CARNATIONS']
        self.assertGreater(len(carns), 0,
                           'Clavel debe parsearse — fix 12o')
        self.assertAlmostEqual(h.total, 1376.10, places=2)
        sum_lines = round(sum(l.line_total for l in lines), 2)
        self.assertAlmostEqual(sum_lines, 1376.10, places=2)


class TestUniqueDS(unittest.TestCase):
    """Sesión 12o: D&S Export con espacios OCR + token BRAND vacío."""

    def test_total_cuadra(self):
        """D_S.pdf: precios `$ 0 .28` y totales `$ 2 24.0` con espacios."""
        h, lines, _ = _parse('D_S.pdf')
        self.assertEqual(len(lines), 3)
        self.assertAlmostEqual(h.total, 560.0, places=2)
        sum_lines = round(sum(l.line_total for l in lines), 2)
        self.assertAlmostEqual(sum_lines, 560.0, places=2,
                               msg='Espacios OCR en price/total deben '
                                   'limpiarse — fix 12o')


class TestMonterosaParser(unittest.TestCase):
    """Sesión 12o: formato Monterosas con parent + sub-líneas."""

    def test_lines_y_total(self):
        """MONTEROSA.pdf: 7 líneas, total $122.50."""
        h, lines, _ = _parse('MONTEROSA.pdf')
        self.assertEqual(len(lines), 7,
                         'Parent + 6 sub-líneas deben parsearse — fix 12o')
        self.assertAlmostEqual(h.total, 122.50, places=2)
        sum_lines = round(sum(l.line_total for l in lines), 2)
        self.assertAlmostEqual(sum_lines, 122.50, places=2)


class TestSecoreCarnation(unittest.TestCase):
    """Sesión 12o: Secore con CARNATION (sin `CM`)."""

    def test_carnation_parseado(self):
        """SECORE.pdf: `CARNATION BICOLOR PURPLE HYPNOSIS 375 1 HALF...`."""
        h, lines, _ = _parse('SECORE.pdf')
        self.assertEqual(len(lines), 1,
                         'Variante CARNATION debe parsearse — fix 12o')
        self.assertEqual(lines[0].species, 'CARNATIONS')
        self.assertAlmostEqual(h.total, 67.50, places=2)


class TestMilongaOCR(unittest.TestCase):
    """Sesión 12o: Milonga con X invasiva en variety + sub-líneas sin H/Q."""

    def test_x_invasiva(self):
        """MILONGA.pdf: `NenXa`, `BrigthoXn`, `MondiaXl` se limpian a `Nena`,
        `Brighton`, `Mondial` (X intercalada entre minúsculas).
        """
        _, lines, _ = _parse('MILONGA.pdf')
        varieties = {l.variety for l in lines}
        self.assertTrue(any('NENA' in v for v in varieties),
                        f'NENA debe aparecer (X invasiva limpia) — '
                        f'tenemos: {varieties}')
        self.assertTrue(any('MONDIAL' in v for v in varieties))

    def test_total_cuadra(self):
        """MILONGA.pdf: header.total = sum_lines = $1042.75."""
        h, lines, _ = _parse('MILONGA.pdf')
        self.assertAlmostEqual(h.total, 1042.75, places=2)
        sum_lines = round(sum(l.line_total for l in lines), 2)
        self.assertAlmostEqual(sum_lines, 1042.75, places=2,
                               msg='Sub-líneas Milonga sin H/Q deben '
                                   'capturarse — fix 12o')


class TestPrintedTotalExtraction(unittest.TestCase):
    """Sesión 12p: total impreso necesario para alertar líneas faltantes.

    El operador necesita que h.total siempre se extraiga del impreso
    (no derivado de sum(lines)) para que la UI marque "Parcial" si una
    línea se perdió silenciosa.
    """
    CASES = [
        ('AGRIVALDANI.pdf', 64.0),     # TOTAL FOB <stems> <price> <total>
        ('LUXUS.pdf', 210.0),
        ('COLIBRI.pdf', 6045.0),       # INVOICE TOTAL (Dólares)
        ('LIFE.pdf', 231.0),           # subtotal pre-Net Weight
        ('ROSELY.pdf', 128.0),         # TOTALS <stems> $ USD <total>
        ('ROSELY2.pdf', 66.0),
    ]

    def test_h_total_no_cero(self):
        """Cada parser debe extraer h.total > 0 del texto impreso."""
        for pdf, expected in self.CASES:
            with self.subTest(pdf=pdf):
                h, lines, _ = _parse(pdf)
                self.assertAlmostEqual(h.total, expected, places=2,
                                       msg=f'{pdf}: h.total debe ser '
                                           f'{expected}, no {h.total}')


class TestPrestigeStems(unittest.TestCase):
    """Sesión 12p: stems con punto de miles (1.000) en Prestige."""

    def test_mondial_1000_stems(self):
        """PRESTIGE.pdf: `MONDIAL ROSE 40 CM ROSA0687 4 250 1.000 $ 0,30 300,00`.

        Antes (\\d+) no aceptaba `1.000` y la línea MONDIAL ($300) se
        perdía silenciosa.
        """
        h, lines, _ = _parse('PRESTIGE.pdf')
        self.assertAlmostEqual(h.total, 435.0, places=2)
        sum_lines = round(sum(l.line_total for l in lines), 2)
        self.assertAlmostEqual(sum_lines, 435.0, places=2)
        self.assertEqual(len(lines), 2,
                         'Tanto VENDELA como MONDIAL deben capturarse')


class TestAposentosCarnationSingular(unittest.TestCase):
    """Sesión 12p: APOSENTOS con `CARNATION` (singular) además de `CARNATIONS`."""

    def test_carnation_special_capturado(self):
        """APOSENTOS.pdf: `CARNATION SPECIAL R14`, `CARNATION SPECIAL CASTILLO`
        deben parsearse (antes se exigía plural y se perdían $175).
        """
        h, lines, _ = _parse('APOSENTOS.pdf')
        self.assertAlmostEqual(h.total, 5260.0, places=2)
        sum_lines = round(sum(l.line_total for l in lines), 2)
        self.assertAlmostEqual(sum_lines, 5260.0, places=2,
                               msg='CARNATION (singular) debe parsearse '
                                   '— fix 12p')


class TestTessaSubLine(unittest.TestCase):
    """Sesión 12p: TessaParser pm2 setea last_btype para que pm4 funcione."""

    def test_pink_mondial_sublinea(self):
        """TESSA1.pdf: parent QB + sub-línea `60 2 50 $0.45 $22.50` deben
        sumar al total impreso $40 (antes pm2 no seteaba last_btype y
        pm4 nunca activaba — sub-línea perdida).
        """
        h, lines, _ = _parse('TESSA1.pdf')
        self.assertAlmostEqual(h.total, 40.0, places=2)
        sum_lines = round(sum(l.line_total for l in lines), 2)
        self.assertAlmostEqual(sum_lines, 40.0, places=2)
        self.assertEqual(len(lines), 2)


class TestEqrMixedBoxNoDoubleCount(unittest.TestCase):
    """Sesión 12p: EQR Garden Rose / Roses sub-líneas no doble cuentan."""

    def test_sum_cuadra_con_total_impreso(self):
        """EQR.pdf: parent `Roses Assorted Colors ... QB ... $35.00` + sub-líneas
        `Garden Rose Country Home ...` deben sumar exactamente al total
        impreso $128.75. Sub-líneas tienen line_total=0 (sus stems van al
        parent).
        """
        h, lines, _ = _parse('EQR.pdf')
        self.assertAlmostEqual(h.total, 128.75, places=2)
        sum_lines = round(sum(l.line_total for l in lines), 2)
        self.assertAlmostEqual(sum_lines, 128.75, places=2,
                               msg='Sub-líneas mixed-box deben tener '
                                   'line_total=0 — fix 12p')


class TestPrintedTotalHelper(unittest.TestCase):
    """Sesión 12q: helper compartido `extract_printed_total`.

    Usado por los 7 parsers `auto_*` sin sample para extraer el total
    preventivamente. Si el helper matchea un patrón equivocado en
    facturas reales, las assertions de aquí se romperán antes que el
    benchmark.
    """

    def test_formatos_comunes(self):
        from src.parsers._helpers import extract_printed_total
        cases = [
            ('TOTAL FOB 200 0.32 64.00', 64.0),
            ('TOTAL DUE USD 1,376.10', 1376.10),
            ('Total Value $5,260.00', 5260.0),
            ('INVOICE TOTAL (Dólares) 6,045.000', 6045.0),
            ('TOTAL A PAGAR 435,00', 435.0),
            ('Invoice Amount $40.00', 40.0),
            ('TOTALS 475 $ USD 128.00', 128.0),
            ('Amount Due $ 1,200.00', 1200.0),
            ('Total Invoice USD $7,510.50', 7510.50),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertAlmostEqual(extract_printed_total(text), expected,
                                       places=2,
                                       msg=f'No matcheó: {text!r}')

    def test_no_match_devuelve_cero(self):
        from src.parsers._helpers import extract_printed_total
        self.assertEqual(extract_printed_total('Box Total: 5'), 0.0)
        self.assertEqual(extract_printed_total(''), 0.0)
        self.assertEqual(extract_printed_total('No total here'), 0.0)


class TestSayonaraCDN(unittest.TestCase):
    """Sesión 12r: `Pom Europa/Asia Assorted CDN` en Sayonara.

    En SAYONARA 64955 una línea era "Pom Europa/Asia Assorted CDN x 40
    Bunch CO-..." que el parser saltaba porque `_TYPE_MAP` no incluía
    "CDN" suelto. Pérdida silenciosa de $152 (1 de 2 líneas).
    """

    def test_assorted_cdn_capturado(self):
        """SAYONARA 64955: las 2 líneas de la factura deben sumar $342."""
        # PDF en Desktop, no en batch_uploads. Skipear si no existe.
        pdf = Path(r'C:\Users\diego.pereira\Desktop\DOC VERA\FACTURAS IMPORTACION\FACTURAS YA PROCESADAS\SAYONARA\03 - V. 729-4465 5623 - SAYONARA 64955.pdf')
        if not pdf.exists():
            raise unittest.SkipTest('SAYONARA 64955 no disponible')
        pdata = detect_provider(str(pdf))
        h, lines = FORMAT_PARSERS['sayonara'].parse(pdata['text'], pdata)
        self.assertEqual(len(lines), 2,
                         'Tanto SP CUSHION como SP CDN deben parsearse')
        self.assertAlmostEqual(h.total, 342.0, places=2)
        sum_lines = round(sum(l.line_total for l in lines), 2)
        self.assertAlmostEqual(sum_lines, 342.0, places=2)


class TestNativeBloomsBouquet(unittest.TestCase):
    """Sesión 12r: NATIVE BLOOMS bouquets `HB N FBE Bouquet/Amazon/...`."""

    def test_bouquets_capturados(self):
        """NATIVE BLOOMS sample: 5 bouquets con total > 0."""
        pdf = Path(r'C:\Users\diego.pereira\Desktop\DOC VERA\FACTURAS IMPORTACION\FACTURAS YA PROCESADAS\NATIVE BLOOMS\03 - J. 729-4986 1442 (220) - NATIVE.pdf')
        if not pdf.exists():
            raise unittest.SkipTest('NATIVE BLOOMS sample no disponible')
        pdata = detect_provider(str(pdf))
        h, lines = FORMAT_PARSERS['auto_native'].parse(pdata['text'], pdata)
        self.assertGreaterEqual(len(lines), 4,
                                'Bouquet Round Mix + Amazon Box + Paradise Box '
                                '+ Mountain Box deben parsearse — fix 12r')
        for l in lines:
            self.assertGreater(l.line_total, 0,
                               f'{l.variety}: line_total debe ser > 0')


if __name__ == '__main__':
    unittest.main()
