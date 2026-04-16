"""Parser auto-generado para GREENGROWERS + EL CAMPANARIO.

Ambas farms emiten facturas desde la misma oficina (staroses.com) con
template idéntico. Layout:

    BOX N° TB BOX CODE VARIETY (CM) BUNCHE STEMS PRICE FOB $
    1 H VERALEZA MONDIAL 50 14 350 0,30 105,00              ← GREENGROWERS
    1 H R 14 ZAIRA ABSOLUT IN PINK 70 1 25 0,35 8,75        ← EL CAMPANARIO
    H JOVI JESSIKA 60 2 50 0,35 17,50                       ← continuación

Tokens:
    [box_num] type code+ variety+ size bunches stems price total

Estrategia: parseamos los 5 números finales (size bunches stems price total)
como ancla, el prefijo se procesa por tokens. Decimal con coma (0,30).
"""
from __future__ import annotations

import re
from src.models import InvoiceHeader, InvoiceLine


# Línea completa — última parte anclada: size bunches stems price total
_TAIL_RE = re.compile(
    r'^(?P<prefix>.+?)\s+'
    r'(?P<size>\d{2,3})\s+'
    r'(?P<bunches>\d{1,3})\s+'
    r'(?P<stems>\d{1,5})\s+'
    r'(?P<price>\d+[.,]\d+)\s+'
    r'(?P<total>[\d.,]+)\s*$'
)

# Validación del prefix: debe empezar opcionalmente con box_num, luego H/F/Q/T,
# luego 1+ tokens código y 1+ tokens variedad.
_PREFIX_RE = re.compile(
    r'^(?:(?P<box_num>\d+)\s+)?'
    r'(?P<type>[HFQT])\s+'
    r'(?P<rest>[A-Z][A-Z0-9\s\-\'/]+)$'
)

# Tokens que consideramos parte del CÓDIGO (no variedad):
#   - Una letra R seguida de espacio o pegada a un número: R 14, R20
#   - Palabra totalmente en mayúsculas ≤6 chars y sin vocal intermedia común
#     (heurística para VERALEZA/JOVI/ZAIRA vs nombres de rosa)
_CODE_TOKEN_RE = re.compile(r'^(?:R\s*\d+|[A-Z]{2,8})$')

# Varieties conocidas como ancla (ayuda a separar code vs variety).
# No exhaustivo — complementa al heurístico.
_KNOWN_VARIETY_FIRST = {
    'MONDIAL', 'EXPLORER', 'FREEDOM', 'ATOMIC', 'BRIGHTON', 'FRUTTETO',
    'JESSIKA', 'ABSOLUT', 'ZAIRA', 'SILANTOI', 'BOULEVARD', 'VIOLET',
    'HIGH', 'MAGIC', 'SANTANA', 'SHIMMER', 'SWEET', 'PINK', 'SALMA',
    'VENDELA', 'HOT', 'TUTTI', 'MOMENTUM', 'QUICKSAND', 'QUEEN',
    'CANDLE', 'CAFE', 'NECTARINE', 'ESPERANCE', 'MOODY',
}


def _num(s: str) -> float:
    return float(s.replace('.', '').replace(',', '.')) if s else 0.0


def _int(s: str) -> int:
    return int(s.replace(',', '').replace('.', '')) if s else 0


def _split_code_variety(rest: str) -> tuple[str, str]:
    """Dado el texto entre tipo y size, separa código(s) de variedad.

    Estrategia: tokens iniciales que matcheen _CODE_TOKEN_RE son código,
    hasta que aparezca un token que esté en _KNOWN_VARIETY_FIRST o que
    sea claramente variedad (palabras largas, mixedcase). La variedad
    es todo lo que queda.

    Fallback si no hay ancla conocida: primer token = code, resto = variety.
    """
    tokens = rest.split()
    if not tokens:
        return '', ''

    # Caso 'R 14' / 'R20' al inicio → lo tratamos como un code_token
    code_end = 0
    i = 0
    while i < len(tokens) - 1:   # necesitamos dejar ≥1 token para variety
        t = tokens[i]
        # R seguido de número → combinar 'R' + 'NN' como un solo code
        if t == 'R' and i + 1 < len(tokens) and tokens[i + 1].isdigit():
            code_end = i + 2
            i += 2
            continue
        if _CODE_TOKEN_RE.match(t) and tokens[i + 1] not in _KNOWN_VARIETY_FIRST \
                and len(tokens) - (i + 1) >= 1:
            # Si el siguiente token es "code-like" también y tenemos ≥2 tokens
            # por delante, seguimos extendiendo el código.
            if i + 2 <= len(tokens) - 1 and _CODE_TOKEN_RE.match(tokens[i + 1]) \
                    and tokens[i + 1] in {'ZAIRA'}:
                code_end = i + 2
                i += 2
                continue
            code_end = i + 1
            i += 1
            continue
        break

    if code_end == 0:
        code_end = 1  # fallback: primer token = code

    code = ' '.join(tokens[:code_end])
    variety = ' '.join(tokens[code_end:])
    return code, variety


_INVOICE_RE = re.compile(r'INVOICE\s*#?\s*(\S+)', re.I)
_DATE_RE    = re.compile(r'Date\s*:\s*(\d{1,2}/\d{1,2}/\d{2,4})', re.I)
_AWB_RE     = re.compile(r'A\.W\.B\.\s*N[°º]?\s*:\s*(\S+)', re.I)
_HAWB_RE    = re.compile(r'H\.A\.W\.B\.\s*N[°º]?\s*:\s*(\S+)', re.I)
_TOTAL_RE   = re.compile(r'Total\s+Invoice:\s*\$?\s*([\d.,]+)', re.I)


class AutoParser:
    fmt_key = 'auto_campanario'

    def parse(self, text: str, provider_data: dict) -> tuple[InvoiceHeader, list[InvoiceLine]]:
        header = InvoiceHeader(
            provider_id=provider_data.get('id', 0),
            provider_name=provider_data.get('name', ''),
            provider_key=provider_data.get('key', ''),
        )
        m = _INVOICE_RE.search(text)
        if m:
            header.invoice_number = m.group(1).strip()
        m = _DATE_RE.search(text)
        if m:
            header.date = m.group(1)
        m = _AWB_RE.search(text)
        if m:
            header.awb = m.group(1)
        m = _HAWB_RE.search(text)
        if m:
            header.hawb = m.group(1)
        m = _TOTAL_RE.search(text)
        if m:
            # Total Invoice usa formato USD (punto decimal), no europeo
            header.total = float(m.group(1).replace(',', ''))

        lines: list[InvoiceLine] = []
        last_box_type = ''
        for raw in text.split('\n'):
            s = raw.strip()
            if not s or len(s) < 15:
                continue
            # Saltar líneas de cabecera / ruido
            up = s.upper()
            if up.startswith(('TOTAL', 'BOX N', 'LENGTH', '(CM)', 'NAME AND',
                              'TOTAL FULL', 'INVOICE', 'CUSTOMER', 'PAGE ',
                              'A.W.B', 'H.A.W.B', 'D.A.E', 'CALLE', 'PHONE',
                              'FARM', 'SHIPPER', 'AIRLINE', 'ORIGIN', 'COUNTRY')):
                continue

            m = _TAIL_RE.match(s)
            if not m:
                continue
            prefix = m.group('prefix').strip()
            mp = _PREFIX_RE.match(prefix)
            if not mp:
                continue
            box_type_raw = mp.group('type').upper()
            last_box_type = box_type_raw

            code, variety = _split_code_variety(mp.group('rest'))
            if not variety or len(variety) < 3:
                continue

            lines.append(InvoiceLine(
                raw_description=s[:120],
                species='ROSES',
                variety=variety.upper(),
                origin='EC',      # Lasso, Ecuador
                size=int(m.group('size')),
                stems_per_bunch=0,  # no viene en la factura → se derivará por species default
                bunches=int(m.group('bunches')),
                stems=int(m.group('stems')),
                price_per_stem=_num(m.group('price')),
                line_total=_num(m.group('total')),
                box_type=f'{box_type_raw}B',  # H → HB, Q → QB, F → FB, T → TB
                label=code,
                provider_key=provider_data.get('key', ''),
            ))

        if not header.total and lines:
            header.total = round(sum(l.line_total for l in lines), 2)
        return header, lines
