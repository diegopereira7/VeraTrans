"""Registry dinámico de parsers auto-generados.

Estos parsers se cargan desde learned_rules.json y tienen menor prioridad
que los parsers manuales en FORMAT_PARSERS.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from src.config import BASE_DIR
from src.models import InvoiceHeader, InvoiceLine

LEARNED_RULES_FILE = BASE_DIR / 'learned_rules.json'

# Registry global
LEARNED_PARSERS: dict[str, LearnedParserRunner] = {}
LEARNED_PROVIDERS: dict[str, dict] = {}


class LearnedParserRunner:
    """Ejecuta un parser auto-generado basado en reglas almacenadas."""

    def __init__(self, config: dict):
        self.config = config
        self.nombre = config.get('nombre', '')
        self.species = config.get('species', 'ROSES')
        self.origin = config.get('origin', 'EC')
        self.default_spb = config.get('default_spb', 25)
        self.default_size = config.get('default_size', 50)
        self.line_regex = config.get('line_regex', '')
        self.header_rules = config.get('header_rules', [])
        self.line_rules = config.get('line_rules', [])

    def parse(self, text: str, pdata: dict) -> tuple[InvoiceHeader, list[InvoiceLine]]:
        """Parsea un PDF usando las reglas aprendidas."""
        header = self._parse_header(text, pdata)
        lines = self._parse_lines(text)
        return header, lines

    def _parse_header(self, text: str, pdata: dict) -> InvoiceHeader:
        """Extrae campos del header usando reglas regex."""
        h = InvoiceHeader(
            provider_key=pdata.get('key', self.nombre),
            provider_id=pdata.get('id', 0),
            provider_name=pdata.get('name', self.nombre),
        )

        header_text = text[:3000]

        for rule in self.header_rules:
            pat = rule.get('patron_regex')
            campo = rule.get('campo_destino')
            if not pat or not campo:
                continue

            m = re.search(pat, header_text, re.IGNORECASE)
            if m:
                val = m.group(rule.get('grupo_captura', 1)).strip()
                if campo == 'invoice_number':
                    h.invoice_number = val
                elif campo == 'date':
                    h.date = val
                elif campo == 'awb':
                    h.awb = re.sub(r'\s', '', val)
                elif campo == 'total':
                    try:
                        h.total = float(val.replace(',', ''))
                    except ValueError:
                        pass

        return h

    def _parse_lines(self, text: str) -> list[InvoiceLine]:
        """Extrae líneas de producto."""
        lines_out: list[InvoiceLine] = []

        # Método 1: Regex de línea general
        if self.line_regex:
            pat = re.compile(self.line_regex, re.IGNORECASE | re.MULTILINE)
            for m in pat.finditer(text):
                line = self._match_to_line(m)
                if line:
                    lines_out.append(line)

        # Método 2: Si hay reglas de columna/posición, parsear líneas de datos
        if not lines_out and self.line_rules:
            lines_out = self._parse_by_position(text)

        return lines_out

    def _match_to_line(self, m: re.Match) -> InvoiceLine | None:
        """Convierte un match de regex a InvoiceLine."""
        groups = m.groups()
        if not groups:
            return None

        line = InvoiceLine(
            raw_description=m.group(0)[:120],
            species=self.species,
            origin=self.origin,
            stems_per_bunch=self.default_spb,
            size=self.default_size,
        )

        # Intentar asignar campos por posición de grupo
        for i, val in enumerate(groups):
            if val is None:
                continue
            val = val.strip()
            self._assign_field(line, val, i, len(groups))

        return line

    def _assign_field(self, line: InvoiceLine, val: str, idx: int, total: int):
        """Asigna un valor a un campo de InvoiceLine heurísticamente."""
        val_clean = val.replace(',', '').replace('$', '').strip()

        # Si es un box type
        if val.upper() in ('QB', 'HB', 'TB', 'HALF', 'QUARTER', 'FULL', 'H', 'Q'):
            line.box_type = val.upper()
            return

        # Si es un número decimal (precio)
        if re.match(r'^\d+\.\d+$', val_clean):
            fval = float(val_clean)
            if fval < 10 and not line.price_per_stem:
                line.price_per_stem = fval
            elif not line.line_total:
                line.line_total = fval
            return

        # Si es un entero
        if re.match(r'^\d+$', val_clean):
            ival = int(val_clean)
            if ival < 200 and not line.size and idx < total // 2:
                line.size = ival
            elif ival > 100 and not line.stems:
                line.stems = ival
            elif ival <= 100 and not line.stems_per_bunch:
                pass  # Keep default
            return

        # Si es texto (variety)
        if re.match(r'^[A-Z][A-Z\s.\-/]+$', val, re.IGNORECASE) and len(val) > 2:
            if not line.variety:
                line.variety = val.upper().strip()

    def _parse_by_position(self, text: str) -> list[InvoiceLine]:
        """Parsea usando reglas de posición de columna."""
        lines_out = []
        text_lines = text.split('\n')

        # Construir mapa de campo -> índice
        field_map = {}
        for rule in self.line_rules:
            idx = rule.get('indice_columna')
            campo = rule.get('campo_destino')
            if idx is not None and campo:
                field_map[idx] = campo

        if not field_map:
            return lines_out

        for text_line in text_lines:
            text_line = text_line.strip()
            if not text_line or len(text_line) < 10:
                continue

            # Debe tener al menos un precio para ser línea de datos
            if not re.search(r'\d+\.\d{2}', text_line):
                continue

            # Splitear en campos
            fields = [f.strip() for f in re.split(r'\s{2,}|\t', text_line) if f.strip()]
            if len(fields) < 3:
                continue

            line = InvoiceLine(
                raw_description=text_line[:120],
                species=self.species,
                origin=self.origin,
                stems_per_bunch=self.default_spb,
                size=self.default_size,
            )

            for idx, campo in field_map.items():
                if idx < len(fields):
                    val = fields[idx].strip()
                    _set_field(line, campo, val)

            if line.variety:
                lines_out.append(line)

        return lines_out


def _set_field(line: InvoiceLine, campo: str, val: str):
    """Asigna un valor a un campo específico de InvoiceLine."""
    val_clean = val.replace(',', '').replace('$', '').strip()

    if campo == 'variety':
        line.variety = val.upper().strip()
    elif campo == 'size':
        try:
            line.size = int(val_clean)
        except ValueError:
            pass
    elif campo == 'stems':
        try:
            line.stems = int(val_clean)
        except ValueError:
            pass
    elif campo == 'bunches':
        try:
            line.bunches = int(val_clean)
        except ValueError:
            pass
    elif campo == 'stems_per_bunch':
        try:
            line.stems_per_bunch = int(val_clean)
        except ValueError:
            pass
    elif campo == 'price_per_stem':
        try:
            line.price_per_stem = float(val_clean)
        except ValueError:
            pass
    elif campo == 'line_total':
        try:
            line.line_total = float(val_clean)
        except ValueError:
            pass
    elif campo == 'grade':
        line.grade = val.upper().strip()
    elif campo == 'label':
        line.label = val.strip()
    elif campo == 'farm':
        line.farm = val.strip()
    elif campo == 'box_type':
        line.box_type = val.upper().strip()


def find_learned_provider(text: str) -> dict | None:
    """Busca si el texto matchea algún proveedor aprendido."""
    text_lower = text.lower()
    for name, pdata in LEARNED_PROVIDERS.items():
        keywords = pdata.get('keywords', [])
        if keywords and all(kw.lower() in text_lower for kw in keywords[:3]):
            return pdata
    return None


def _reload_registry():
    """Recarga el registry desde learned_rules.json."""
    global LEARNED_PARSERS, LEARNED_PROVIDERS
    LEARNED_PARSERS.clear()
    LEARNED_PROVIDERS.clear()

    if not LEARNED_RULES_FILE.exists():
        return

    try:
        rules = json.loads(LEARNED_RULES_FILE.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return

    for name, config in rules.items():
        if not config.get('activo', True):
            continue

        LEARNED_PARSERS[name] = LearnedParserRunner(config)
        LEARNED_PROVIDERS[name] = {
            'id': config.get('provider_id', 0),
            'name': config.get('nombre', name),
            'fmt': name,
            'keywords': config.get('keywords', []),
            'key': name,
        }


# Cargar al importar
_reload_registry()
