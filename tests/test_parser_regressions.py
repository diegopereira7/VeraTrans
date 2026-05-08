"""Tests de regresión para los fixes de parsers en sesiones 12g–12l.

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

Ejecución:
    python -m unittest tests.test_parser_regressions
    python -m unittest tests.test_parser_regressions.TestMeaflosParser
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

# Batches del operador con PDFs verificados. Cada test indica el PDF
# por nombre; el helper busca en todos los batches conocidos. Si un
# batch fue purgado, los tests asociados se skippean automáticamente.
_BATCH_DIRS = [
    _ROOT / 'batch_uploads' / '20260507144258_a5e9b107',  # 12o
    _ROOT / 'batch_uploads' / '20260427083117_229c58c3',  # 12g–12n
]
# Compat: BATCH apunta al primero existente para tests legacy que lo importan.
BATCH = next((b for b in _BATCH_DIRS if b.exists()), _BATCH_DIRS[0])


def _parse(pdf_name: str, batch_id: str | None = None):
    """Helper: ejecuta el parser para un PDF y devuelve (header, lines).

    Si `batch_id` se especifica, solo busca en ese batch (skip si no
    existe). Si no, busca en todos los batches conocidos.
    """
    if batch_id is not None:
        pdf_path = _ROOT / 'batch_uploads' / batch_id / pdf_name
        if not pdf_path.exists():
            raise unittest.SkipTest(f'Batch {batch_id} no disponible: {pdf_name}')
    else:
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


class TestMeaflosParser(unittest.TestCase):
    """Sesión 12h: `Garden Roses` + stems con punto miles."""

    def test_garden_roses_reconocido(self):
        """`Garden Roses - Country Home 50cm ...` debe parsearse.

        Antes de 12h el regex `Rosas?` no matcheaba `Roses` (s? no
        cubre alternation). Sin este fix, líneas Garden Roses se
        perdían silenciosas en MEAFLOS.
        """
        _, lines, _ = _parse('MEAFLOS.pdf')
        garden = [l for l in lines if 'COUNTRY' in l.variety.upper()
                  or 'CANDLELIGHT' in l.variety.upper()
                  or 'KAHALA' in l.variety.upper()]
        self.assertGreater(len(garden), 0,
                           '`Garden Roses` (Country Home/Candlelight/Kahala) '
                           'debe parsearse — fix 12h')

    def test_stems_con_separador_miles(self):
        """`Rosas - Mondial 50cm ... 1.200 ...` debe parsearse.

        Antes de 12h el regex `(\\d+)` para stems no aceptaba `1.200`
        (separador de miles con punto), perdiendo todas las líneas
        con ≥1000 stems.
        """
        _, lines, _ = _parse('MEAFLOS.pdf')
        big_lines = [l for l in lines if l.stems >= 1000]
        self.assertGreaterEqual(len(big_lines), 2,
                                'Líneas con ≥1000 stems debe haber '
                                '(MEAFLOS.pdf: Explorer 1500, Carrousel 1200, etc.)')

    def test_total_cuadra(self):
        """sum(lines) == header.total para todas las facturas MEAFLOS del batch."""
        for pdf_name, expected in [
            ('MEAFLOS.pdf', 7510.50),
            ('MEAFLOS_075.pdf', 4965.00),
            ('MEAFLOS_1.pdf', 1810.50),
        ]:
            with self.subTest(pdf=pdf_name):
                header, lines, _ = _parse(pdf_name)
                self.assertAlmostEqual(header.total, expected, places=2)
                sum_lines = round(sum(l.line_total for l in lines), 2)
                self.assertAlmostEqual(sum_lines, expected, places=2,
                                       msg=f'{pdf_name}: sum_lines debe '
                                           f'cuadrar al total impreso ${expected}')


class TestUmaParser(unittest.TestCase):
    """Sesión 12i: sub-líneas de mixed boxes sin prefijo `N hb XXX`."""

    def test_sublineas_heredan_btype(self):
        """Sub-líneas tipo `<COD> Brighton 60 cm Farm 50 25 2 ...` deben parsearse.

        Las sub-líneas comparten caja física con un parent y NO traen
        el prefijo `N hb XXX`. Antes de 12i se perdían 9 líneas en
        UMA.pdf (batch 12g) sumando $196.
        """
        header, lines, _ = _parse('UMA.pdf', batch_id='20260427083117_229c58c3')
        # UMA.pdf debe tener ≥20 líneas tras el fix de sub-líneas (antes: 14).
        self.assertGreaterEqual(len(lines), 20,
                                'Sub-líneas mixed-box deben capturarse — fix 12i')
        self.assertAlmostEqual(header.total, 3896.00, places=2)
        sum_lines = round(sum(l.line_total for l in lines), 2)
        self.assertAlmostEqual(sum_lines, 3896.00, places=2)


class TestGardaParser(unittest.TestCase):
    """Sesión 12i: variety con apóstrofes y dígitos."""

    def test_variety_con_apostrofe(self):
        """`Pink O'Hara` debe parsearse (apóstrofe en char class)."""
        _, lines, _ = _parse('GARDA1.pdf')
        ohara = [l for l in lines if "O'HARA" in l.variety.upper()
                 or 'O HARA' in l.variety.upper()]
        self.assertGreater(len(ohara), 0,
                           "Pink O'Hara debe parsearse — fix 12i")

    def test_variety_con_digitos(self):
        """`RM001` debe parsearse (dígitos en char class)."""
        _, lines, _ = _parse('GARDA1.pdf')
        rm = [l for l in lines if l.variety.upper().startswith('RM')
              and any(c.isdigit() for c in l.variety)]
        self.assertGreater(len(rm), 0,
                           'RM001 debe parsearse — fix 12i')

    def test_total_cuadra(self):
        """GARDA1.pdf: header.total = sum_lines = $998.75."""
        header, lines, _ = _parse('GARDA1.pdf')
        self.assertAlmostEqual(header.total, 998.75, places=2)
        sum_lines = round(sum(l.line_total for l in lines), 2)
        self.assertAlmostEqual(sum_lines, 998.75, places=2)


class TestVerdesEstacionParser(unittest.TestCase):
    """Sesión 12i: sub-líneas con variety colgada en línea anterior."""

    def test_sublineas_variety_colgada(self):
        """`MAYRA'S BRIDAL FRESH CUT` arriba + `40CM 25 25 CO ... $ 8,00` abajo.

        El _RE_C debe buscar variety en text_lines[i-1] y parsearla
        sin perder la línea de detalle. Antes de 12i se perdían 4
        líneas en PONDEROSA.pdf del batch 12g ($40 invisibles).
        """
        header, lines, _ = _parse('PONDEROSA.pdf', batch_id='20260427083117_229c58c3')
        # PONDEROSA debe tener al menos una variety MAYRA's Bridal o similar
        mayras = [l for l in lines if 'MAYRA' in l.variety.upper()]
        self.assertGreater(len(mayras), 0,
                           "Sub-líneas con variety MAYRA'S BRIDAL deben "
                           'capturarse — fix 12i')
        self.assertAlmostEqual(header.total, 3177.75, places=2)
        sum_lines = round(sum(l.line_total for l in lines), 2)
        self.assertAlmostEqual(sum_lines, 3177.75, places=2)


class TestTessaParser(unittest.TestCase):
    """Sesión 12j: bunches confundidos con spb."""

    def test_mondial_spb_25_no_10(self):
        """MONDIAL/EXPLORER 70cm en TESSA debe tener spb=25, no spb=10.

        Antes de 12j el regex asignaba `group(4)` (bunches) a spb.
        Con el fix, spb se calcula como `stems // bunches`.
        """
        _, lines, _ = _parse('TESSA.pdf')
        # No debe haber líneas MONDIAL/EXPLORER spb=10 (rosa estándar).
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


class TestFlorsaniParser(unittest.TestCase):
    """Sesión 12g: `Single Flowers` multi-invoice — `re.finditer` no `re.search`."""

    def test_multi_invoice_total(self):
        """VERALEZA_23-04.pdf trae 2 facturas concatenadas.

        Antes de 12g, `re.search` solo capturaba la primera sección
        Single Flowers ($432). El fix usa `re.finditer` para sumar
        todas (resultado: $2355.11 = $432 + $1923.11).
        """
        header, lines, _ = _parse('VERALEZA_23-04.pdf')
        # No comprobamos total exacto (depende del PDF real), solo
        # que no sea solo la primera sección.
        sum_lines = round(sum(l.line_total for l in lines), 2)
        # Si el fix está roto, h.total quedaría con la primera
        # sección y sum_lines tendría todas las líneas → mismatch.
        self.assertAlmostEqual(header.total, sum_lines, places=1,
                               msg='Multi-invoice: h.total debe sumar '
                                   'TODAS las secciones Single Flowers')


class TestPrestigeParser(unittest.TestCase):
    """Sesión 12g: total impreso `TOTAL A PAGAR` con normalización USD."""

    def test_total_impreso(self):
        """PRESTIGE.pdf: header.total = $87.50 (vs sum trivial) — batch 12g."""
        header, _, _ = _parse('PRESTIGE.pdf', batch_id='20260427083117_229c58c3')
        self.assertAlmostEqual(header.total, 87.50, places=2,
                               msg='`TOTAL A PAGAR` debe extraerse del texto, '
                                   'no quedarse en 0 (fix 12g)')


class TestNativeParser(unittest.TestCase):
    """Sesión 12g: `Total <pcs> <full> <stems> <total>` con espacios OCR."""

    def test_total_con_espacios_ocr(self):
        """NATIVE.pdf: `Total 5 2,5 1240 2 66,00` → $266 (espacios eliminados)."""
        header, _, _ = _parse('NATIVE.pdf')
        self.assertAlmostEqual(header.total, 266.00, places=2,
                               msg='`Total ... 2 66,00` (OCR roto) debe '
                                   'limpiarse a 266,00 (fix 12g)')


class TestMysticLabel(unittest.TestCase):
    """Sesión 12n: destino del PDF (CORUÑA, VNG, GAIA…) → InvoiceLine.label.

    El operador necesita el destino visible en la UI sin tener que mirar
    `raw_description`, para meter la línea en el ERP. El regex captura
    el primer token después de `btype` (columna destino del PDF) y se
    asigna a `label` salvo blacklist (`FR` es prefijo de variety, no
    destino).
    """

    def test_coruna_va_a_label(self):
        """MYSTIC1.pdf: 7 líneas con `H CORUÑA TNT Gyp...` → label=CORUÑA (batch 12n)."""
        _, lines, _ = _parse('MYSTIC1.pdf', batch_id='20260427083117_229c58c3')
        coruna = [l for l in lines if l.label == 'CORUÑA']
        self.assertGreaterEqual(len(coruna), 5,
                                'CORUÑA debe llenarse en label desde la '
                                'columna destino del PDF — fix 12n')

    def test_fr_no_va_a_label(self):
        """MYSTIC2.pdf: `25 H FR Gyp Natural Xlence...` → label vacío.

        FR es prefijo de variedad (operador confirmó), no destino.
        Está en _NOT_DESTINATIONS para que no contamine label.
        """
        _, lines, _ = _parse('MYSTIC2.pdf')
        fr_label = [l for l in lines if l.label == 'FR']
        self.assertEqual(len(fr_label), 0,
                         'FR no debe llenarse en label (es variety, no '
                         'destino) — fix 12n')


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
        # Las variedades deben estar limpias (sin X intercalada)
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
    línea se perdió silenciosa. Cubre 6 parsers que antes dejaban
    h.total=0.
    """
    CASES = [
        ('AGRIVALDANI.pdf', 64.0),     # TOTAL FOB <stems> <price> <total>
        ('LUXUS.pdf', 210.0),          # mismo formato
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
        # Sin keyword conocida: 0.0
        self.assertEqual(extract_printed_total('Box Total: 5'), 0.0)
        self.assertEqual(extract_printed_total(''), 0.0)
        self.assertEqual(extract_printed_total('No total here'), 0.0)


if __name__ == '__main__':
    unittest.main()
