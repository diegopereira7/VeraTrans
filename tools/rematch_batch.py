"""Re-ejecuta el matcher sobre un batch ya procesado, sin re-extraer
los PDFs. Útil cuando se cambian reglas del matcher (regla de spray,
foreign_brand, etc.) y se quiere aplicarlas a un lote ya en disco.

Lee ``batch_status/{id}.json``, reconstruye un ``InvoiceLine`` por
cada línea (con los datos parseados que ya están guardados), corre
``Matcher.match_all`` en cada factura, y reescribe el JSON in-place
con las nuevas decisiones de matching.

NO toca:
  - Los datos extraídos del PDF (variety, size, stems, totales…).
  - El total / cabecera de la factura.
  - Las líneas eliminadas por el operador (``_deleted=True``).

SÍ actualiza:
  - ``articulo_id`` / ``articulo_name`` / ``match_status`` / etc.
  - ``ok_count`` / ``sin_match`` / ``needs_review`` del invoice.

Uso:
    python tools/rematch_batch.py <batch_id>
    python tools/rematch_batch.py batch_status/<batch_id>.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Permitir ejecutar como script desde la raíz del proyecto.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.articulos import ArticulosLoader  # noqa: E402
from src.config import HIST_FILE, PROVIDERS, SYNS_FILE  # noqa: E402
from src.matcher import Matcher  # noqa: E402
from src.models import InvoiceLine  # noqa: E402
from src.sinonimos import SynonymStore  # noqa: E402


def _resolve_batch_path(arg: str) -> Path:
    """Acepta tanto ``<batch_id>`` como una ruta directa al JSON."""
    p = Path(arg)
    if p.exists() and p.is_file():
        return p
    candidate = _ROOT / 'batch_status' / f'{arg}.json'
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f'No se encontró batch: {arg}')


def _line_from_json(raw: dict, provider_key: str) -> InvoiceLine:
    """Construye un ``InvoiceLine`` desde la entrada serializada.

    Acepta tanto los campos canónicos de Python como los aliases v4 que
    introduce el adapter de PHP (``total_line``, ``confidence``).
    """
    return InvoiceLine(
        raw_description=raw.get('raw_description') or raw.get('raw') or '',
        species=raw.get('species') or 'ROSES',
        variety=raw.get('variety') or '',
        grade=raw.get('grade') or '',
        origin=raw.get('origin') or 'EC',
        size=int(raw.get('size') or 0),
        stems_per_bunch=int(raw.get('stems_per_bunch')
                            or raw.get('spb') or 0),
        bunches=int(raw.get('bunches') or 0),
        stems=int(raw.get('stems') or 0),
        price_per_stem=float(raw.get('price_per_stem')
                             or raw.get('price') or 0),
        price_per_bunch=float(raw.get('price_per_bunch') or 0),
        line_total=float(raw.get('line_total')
                         or raw.get('total_line')
                         or raw.get('total') or 0),
        label=raw.get('label') or '',
        farm=raw.get('farm') or '',
        box_type=raw.get('box_type') or '',
        provider_key=provider_key,
        ocr_confidence=float(raw.get('ocr_confidence') or 1.0),
        extraction_confidence=float(raw.get('extraction_confidence') or 1.0),
        extraction_source=raw.get('extraction_source') or 'native',
    )


def _provider_key_for(pid: int) -> str:
    for k, p in PROVIDERS.items():
        if p.get('id') == pid:
            return k
    return ''


def _recompute_invoice_stats(inv: dict) -> None:
    """Recalcula contadores tras el rematch — espejo del helper PHP."""
    flagged = {'ambiguous_match', 'sin_match', 'sin_parser',
               'mixed_box', 'llm_extraido', 'pendiente'}
    ok = sin = needs = 0
    for l in inv.get('lines') or []:
        st = l.get('match_status') or ''
        if st == 'ok':
            ok += 1
        elif st == 'sin_match':
            sin += 1
        conf = float(l.get('confidence') or l.get('match_confidence') or 0)
        errs = l.get('validation_errors') or []
        flagged_status = st in flagged
        if (flagged_status
                or (isinstance(errs, list) and len(errs) > 0)
                or conf < 0.84):
            needs += 1
    inv['ok_count'] = ok
    inv['sin_match'] = sin
    inv['needs_review'] = needs


def rematch_file(path: Path) -> dict:
    """Re-procesa el matching del JSON apuntado y reescribe in-place.

    Devuelve un resumen ``{facturas, lineas, cambios}``.
    """
    with path.open('r', encoding='utf-8') as f:
        data = json.load(f)

    art = ArticulosLoader()
    art.load_from_db()
    syn = SynonymStore(str(SYNS_FILE))
    matcher = Matcher(art, syn)

    facturas = 0
    lineas = 0
    cambios = 0

    with syn.batch():
        for inv in data.get('resultados') or []:
            if not inv.get('ok'):
                continue
            raw_lines = inv.get('lines') or []
            if not raw_lines:
                continue

            facturas += 1
            provider_id = int(inv.get('provider_id') or 0)
            provider_key = _provider_key_for(provider_id)
            invoice_num = inv.get('invoice') or ''

            # Saltar líneas marcadas como borradas por la UI.
            keep_indices = [
                i for i, l in enumerate(raw_lines)
                if not l.get('_deleted')
            ]
            il_objs = [_line_from_json(raw_lines[i], provider_key)
                       for i in keep_indices]
            if not il_objs:
                continue

            matched = matcher.match_all(provider_id, il_objs,
                                        invoice=invoice_num)

            for keep_i, il in zip(keep_indices, matched):
                raw = raw_lines[keep_i]
                old_id = raw.get('articulo_id')
                # Sobrescribir solo campos del matcher; preservar el
                # resto (raw, totales, contexto del operador).
                raw['articulo_id'] = il.articulo_id
                raw['articulo_name'] = il.articulo_name
                raw['match_status'] = il.match_status
                raw['match_method'] = il.match_method
                raw['match_confidence'] = il.match_confidence
                raw['link_confidence'] = il.link_confidence
                raw['candidate_margin'] = il.candidate_margin
                raw['candidate_count'] = il.candidate_count
                raw['match_reasons'] = list(il.match_reasons)
                raw['match_penalties'] = list(il.match_penalties)
                raw['top_candidates'] = list(il.top_candidates)
                raw['origin'] = il.origin
                raw['validation_errors'] = list(il.validation_errors)
                raw['review_lane'] = il.review_lane
                # Aliases v4 que la UI lee directamente.
                raw['confidence'] = il.match_confidence
                lineas += 1
                if old_id != il.articulo_id:
                    cambios += 1

            _recompute_invoice_stats(inv)

    # Escritura atómica.
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    tmp.replace(path)

    return {'facturas': facturas, 'lineas': lineas, 'cambios': cambios}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print('Uso: python tools/rematch_batch.py <batch_id|ruta>',
              file=sys.stderr)
        return 2
    try:
        path = _resolve_batch_path(argv[1])
    except FileNotFoundError as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 1

    summary = rematch_file(path)
    print(json.dumps({'ok': True, **summary, 'path': str(path)},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
