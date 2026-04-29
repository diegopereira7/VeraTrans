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

# Batch del operador con los PDFs verificados en sesiones 12g–12l.
BATCH = _ROOT / 'batch_uploads' / '20260427083117_229c58c3'


def _parse(pdf_name: str):
    """Helper: ejecuta el parser para un PDF y devuelve (header, lines)."""
    pdf_path = BATCH / pdf_name
    if not pdf_path.exists():
        raise unittest.SkipTest(f'Sample no disponible: {pdf_path}')
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
        UMA.pdf sumando $196.
        """
        header, lines, _ = _parse('UMA.pdf')
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
        líneas en PONDEROSA.pdf ($40 invisibles).
        """
        header, lines, _ = _parse('PONDEROSA.pdf')
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
        """PRESTIGE.pdf: header.total = $87.50 (vs sum trivial)."""
        header, _, _ = _parse('PRESTIGE.pdf')
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


if __name__ == '__main__':
    unittest.main()
