from __future__ import annotations

import re

from src.models import InvoiceHeader, InvoiceLine


class LifeParser:
    """Life Flowers: two line types:
    1. Box line: "HB 1 0.50 MARL Explorer 50CM 20 16 320 0.28 89.60"
    2. Continuation: "Pink Floyd 50CM 20 8 160 0.28 44.80"

    The delegation (MARL, RODRIGO PEREIRA, etc.) appears between box prefix and variety.
    We capture DELEGATION + VARIETY together as the variety field, then the matcher's
    delegation stripping logic separates them for matching.
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
            # Type 1: Box line — capture everything between box prefix and NNcm
            # "HB 1 0.50 MARL Explorer 50CM 20 16 320 0.28 89.60"
            # → full_desc = "MARL Explorer"
            pm = re.search(
                r'(?:HB|QB)\s+\d+\s+[\d.]+\s+'   # box_type + count + FBE
                r'(.+?)\s+'                         # full description (delegation + variety)
                r'(\d{2,3})CM\s+'                   # size
                r'(\d+)\s+(\d+)\s+(\d+)\s+'         # SPB, bunches, stems
                r'([\d.]+)',                          # price
                raw)
            if pm:
                var = pm.group(1).strip().upper()
                sz = int(pm.group(2)); spb = int(pm.group(3))
                bunches = int(pm.group(4)); stems = int(pm.group(5))
                price = float(pm.group(6))
                il = InvoiceLine(raw_description=raw, species='ROSES', variety=var,
                                 size=sz, stems_per_bunch=spb, bunches=bunches,
                                 stems=stems, price_per_stem=price,
                                 line_total=round(price * stems, 2))
                lines.append(il)
                continue

            # Type 2: Continuation line — everything before NNcm is the variety
            # "Pink Floyd 50CM 20 8 160 0.28 44.80"
            pm2 = re.search(
                r'^([A-Z][a-zA-Z\s.\-/&]+?)\s+'    # variety
                r'(\d{2,3})CM\s+'                    # size
                r'(\d+)\s+(\d+)\s+(\d+)\s+'          # SPB, bunches, stems
                r'([\d.]+)',                           # price
                raw)
            if pm2:
                var = pm2.group(1).strip().upper()
                sz = int(pm2.group(2)); spb = int(pm2.group(3))
                bunches = int(pm2.group(4)); stems = int(pm2.group(5))
                price = float(pm2.group(6))
                il = InvoiceLine(raw_description=raw, species='ROSES', variety=var,
                                 size=sz, stems_per_bunch=spb, bunches=bunches,
                                 stems=stems, price_per_stem=price,
                                 line_total=round(price * stems, 2))
                lines.append(il)

        return h, lines
