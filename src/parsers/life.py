from __future__ import annotations

import re

from src.models import InvoiceHeader, InvoiceLine


class LifeParser:
    """Life Flowers: two layout variants:

    Variant A (2026+): "HB 1 0.50 MARL Explorer 50CM 20 16 320 0.28 89.60"
    Variant B (2024):  Agrivaldani-style "1 - 1 BRUNA S.O 1 HALF EXPLORER 60 25 6 150 0.32 48.00"

    If variant A doesn't parse anything, falls back to AgrivaldaniParser.
    """
    def parse(self, text: str, pdata: dict):
        h = InvoiceHeader()
        h.provider_key = pdata['key']; h.provider_id = pdata['id']; h.provider_name = pdata['name']
        m = re.search(r'INVOICE\s+(\d+)', text, re.I); h.invoice_number = m.group(1) if m else ''
        m = re.search(r'Date\s*(\d{4}/\d{2}/\d{2})', text, re.I); h.date = m.group(1) if m else ''
        m = re.search(r'M\.?A\.?W\.?B[:\s]*([\d\-]+)', text, re.I)
        h.awb = re.sub(r'\s+', '', m.group(1)) if m else ''
        lines = []
        for ln in text.split('\n'):
            raw = ln.strip()
            if not raw:
                continue
            # Type 1: Box line. Captura opcionalmente el box_code (palabra
            # en MAYÚSCULAS, 3+ letras — MARL, CRISTIAN, MERCO) como
            # label separado del variety. Un token `[A-Z]{3,}` no casa
            # con nombres Capitalize (Explorer, Mondial) ni con
            # multi-palabra como "Pink Floyd", así que el code queda
            # claramente distinto del variety.
            # "HB 1 0.50 MARL Explorer 50CM 20 16 320 0.28 89.60"
            #                  ^^^^ code         ^^^^^^^^ variety
            pm = re.search(
                r'(?:HB|QB)\s+\d+\s+[\d.]+\s+'       # box_type + count + FBE
                r'(?:([A-Z]{3,})\s+)?'                # box_code opcional
                r'([A-Z][a-zA-Z\s.\-/&]+?)\s+'        # variety (Capitalize)
                r'(\d{2,3})CM\s+'                     # size
                r'(\d+)\s+(\d+)\s+(\d+)\s+'           # SPB, bunches, stems
                r'([\d.]+)',                          # price
                raw)
            if pm:
                label = (pm.group(1) or '').upper()
                var = pm.group(2).strip().upper()
                sz = int(pm.group(3)); spb = int(pm.group(4))
                bunches = int(pm.group(5)); stems = int(pm.group(6))
                price = float(pm.group(7))
                il = InvoiceLine(raw_description=raw, species='ROSES', variety=var,
                                 size=sz, stems_per_bunch=spb, bunches=bunches,
                                 stems=stems, price_per_stem=price,
                                 line_total=round(price * stems, 2),
                                 label=label)
                lines.append(il)
                continue

            # Type 2: Continuation line — code opcional al inicio si
            # aparece: "MARL Pink Floyd 50CM 20 8 160 0.28 44.80"
            # o sin code: "Pink Floyd 50CM 20 8 160 0.28 44.80"
            pm2 = re.search(
                r'^(?:([A-Z]{3,})\s+)?'              # box_code opcional
                r'([A-Z][a-zA-Z\s.\-/&]+?)\s+'       # variety
                r'(\d{2,3})CM\s+'                    # size
                r'(\d+)\s+(\d+)\s+(\d+)\s+'          # SPB, bunches, stems
                r'([\d.]+)',                         # price
                raw)
            if pm2:
                label = (pm2.group(1) or '').upper()
                var = pm2.group(2).strip().upper()
                sz = int(pm2.group(3)); spb = int(pm2.group(4))
                bunches = int(pm2.group(5)); stems = int(pm2.group(6))
                price = float(pm2.group(7))
                il = InvoiceLine(raw_description=raw, species='ROSES', variety=var,
                                 size=sz, stems_per_bunch=spb, bunches=bunches,
                                 stems=stems, price_per_stem=price,
                                 line_total=round(price * stems, 2),
                                 label=label)
                lines.append(il)

        # Fallback: si el formato A no parseó nada, intentar con AgrivaldaniParser
        # (Life Flowers usaba el template Agrivaldani en 2024)
        if not lines:
            from src.parsers.agrivaldani import AgrivaldaniParser
            return AgrivaldaniParser().parse(text, pdata)

        return h, lines
