"""Shadow mode — agregación y reporte de `shadow_log.jsonl`.

Shadow mode captura en `shadow_log.jsonl` dos tipos de entries mientras
el operador usa la UI web:

- `propuesta`: cada línea que el matcher devolvió con su articulo_id,
  confidence, reasons y penalties — ANTES de que el operador actuara.
- `decision`: cuando el operador confirma (✓) o corrige un artículo en la
  UI, se loguea proposed_articulo_id vs decided_articulo_id.

El cruce de ambos (por `synonym_key`) permite medir accuracy real en
producción, no en el benchmark. Complementa el golden set: el golden
responde "¿mi matcher clava lo que un humano revisaría?" sobre 997
líneas curadas; shadow responde "¿en la operación diaria, cuántas de mis
propuestas confirma el operador y cuántas corrige?".

Uso:
    python tools/shadow_report.py
    python tools/shadow_report.py --since 2026-04-01
    python tools/shadow_report.py --provider BRISSAS
    python tools/shadow_report.py --top-errors 20
    python tools/shadow_report.py --top-missing-articles 30
    python tools/shadow_report.py --verify-current
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SHADOW_LOG = Path(__file__).resolve().parent.parent / 'shadow_log.jsonl'


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _load_entries(since: datetime | None,
                  provider_filter: str) -> tuple[list[dict], list[dict]]:
    """Lee el log y devuelve (propuestas, decisiones) filtradas."""
    propuestas: list[dict] = []
    decisiones: list[dict] = []
    if not SHADOW_LOG.exists():
        return propuestas, decisiones

    with SHADOW_LOG.open('r', encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                e = json.loads(ln)
            except json.JSONDecodeError:
                continue
            ts = _parse_ts(e.get('ts', ''))
            if since and ts and ts < since:
                continue
            if provider_filter:
                pn = (e.get('provider_name') or '').upper()
                if provider_filter.upper() not in pn:
                    continue
            evento = e.get('evento', '')
            if evento == 'propuesta':
                propuestas.append(e)
            elif evento == 'decision':
                decisiones.append(e)
    return propuestas, decisiones


def _match_decisions(propuestas: list[dict],
                     decisiones: list[dict]) -> list[dict]:
    """Cruza decisiones con la última propuesta que compartió synonym_key.

    Cada decisión puede referirse a varias propuestas (el operador marcó
    una línea concreta, pero la key es compartida). Tomamos la propuesta
    más reciente ANTERIOR a la decisión. Si no hay, la decisión queda
    "huérfana" (no hay contexto de propuesta).
    """
    # Índice de propuestas por synonym_key en orden cronológico
    props_by_key: dict[str, list[dict]] = defaultdict(list)
    for p in propuestas:
        k = p.get('synonym_key')
        if k:
            props_by_key[k].append(p)
    for k in props_by_key:
        props_by_key[k].sort(key=lambda x: x.get('ts', ''))

    matched = []
    for d in decisiones:
        k = d.get('synonym_key', '')
        ts_d = d.get('ts', '')
        cands = props_by_key.get(k, [])
        prop = None
        for p in reversed(cands):
            if p.get('ts', '') <= ts_d:
                prop = p
                break
        matched.append({'decision': d, 'proposal': prop})
    return matched


def _print_global(propuestas: list[dict], decisiones: list[dict],
                  matched: list[dict]) -> None:
    print('='*70)
    print('SHADOW MODE — Resumen global')
    print('='*70)

    n_prop = len(propuestas)
    n_dec = len(decisiones)
    confirms = [m for m in matched if m['decision'].get('action') == 'confirm']
    corrects = [m for m in matched if m['decision'].get('action') == 'correct']
    # Un "rescate" es una corrección sobre sin_match: el matcher no propuso
    # nada (proposed_articulo_id=0 en la decision = save_synonym). No es un
    # error del matcher, es cobertura humana extra.
    rescues = [m for m in corrects
               if int(m['decision'].get('proposed_articulo_id') or 0) == 0]
    wrong = [m for m in corrects if m not in rescues]
    with_ctx = sum(1 for m in matched if m['proposal'])

    print(f'Propuestas logueadas:       {n_prop}')
    print(f'Decisiones logueadas:       {n_dec}')
    print(f'  - confirmaciones:         {len(confirms)}')
    print(f'  - correcciones matcher:   {len(wrong)}    (propuso artículo != correcto)')
    print(f'  - rescates sin_match:     {len(rescues)}    (matcher no propuso, operador asignó)')
    print(f'Con contexto de propuesta:  {with_ctx}/{n_dec}')
    print()

    # Accuracy "honesta" del matcher: excluir los rescates (el matcher no
    # tuvo oportunidad). Denominador = solo las veces que el matcher habló.
    n_spoke = len(confirms) + len(wrong)
    if n_spoke:
        accuracy = len(confirms) / n_spoke * 100
        print(f'Accuracy del matcher cuando propuso: {accuracy:.1f}%  '
              f'({len(confirms)}/{n_spoke})')
    if n_dec and not n_spoke:
        print('(solo hay rescates — matcher nunca tuvo propuesta para estas claves)')
    elif not n_dec:
        print('(aún no hay decisiones del operador — usa la UI confirm/correct)')


def _print_by_provider(matched: list[dict], top: int = 15) -> None:
    print()
    print('='*70)
    print(f'Accuracy por proveedor (top {top} por volumen)')
    print('='*70)
    by_prov = defaultdict(lambda: {'confirm': 0, 'correct': 0})
    for m in matched:
        d = m['decision']
        prov = (m['proposal'] or d).get('provider_name') or '(desconocido)'
        by_prov[prov][d.get('action', 'confirm')] += 1

    rows = []
    for prov, ct in by_prov.items():
        total = ct['confirm'] + ct['correct']
        acc = ct['confirm'] / total * 100 if total else 0
        rows.append((total, acc, prov, ct['confirm'], ct['correct']))
    rows.sort(key=lambda r: (-r[0], -r[1]))

    print(f'{"Proveedor":<25s} {"total":>6} {"conf":>6} {"corr":>6} {"acc":>6}')
    for total, acc, prov, c, x in rows[:top]:
        print(f'{prov[:25]:<25s} {total:>6} {c:>6} {x:>6} {acc:>5.1f}%')


def _print_top_errors(matched: list[dict], top: int) -> None:
    print()
    print('='*70)
    print(f'Top {top} correcciones — qué artículos propone mal el matcher')
    print('='*70)
    # Solo correcciones donde el matcher SÍ propuso algo distinto — los
    # rescates (proposed=0) no son errores del matcher y se listan aparte
    # en el backlog / sección de rescates.
    corrects = [m for m in matched
                if m['decision'].get('action') == 'correct'
                and int(m['decision'].get('proposed_articulo_id') or 0) != 0]
    errors = Counter()
    for m in corrects:
        p = m['proposal'] or m['decision']
        proposed_name = ''
        if m['proposal']:
            proposed_name = m['proposal'].get('proposed_articulo_name', '')
        key = (
            p.get('provider_name', ''),
            p.get('variety', ''),
            proposed_name,
            m['decision'].get('decided_articulo_name', ''),
        )
        errors[key] += 1

    if not corrects:
        print('(sin correcciones con propuesta — 0 errores de matcher)')
        return

    for (prov, var, proposed_name, decided_name), n in errors.most_common(top):
        print(f'[x{n}] [{prov[:20]:20s}] var={var!r}')
        print(f'       propuso : {proposed_name!r}')
        print(f'       correcto: {decided_name!r}')


def _build_matcher():
    """Carga artículos + sinónimos + matcher. Import diferido porque
    solo se usa con --verify-current (evita pagar el arranque de MySQL
    en runs normales)."""
    # Path fix para que src.* se importe desde la raíz del repo.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.articulos import ArticulosLoader
    from src.sinonimos import SynonymStore
    from src.matcher import Matcher
    loader = ArticulosLoader()
    loader.load_from_db()
    syn = SynonymStore('sinonimos_universal.json')
    return Matcher(loader, syn)


def _verify_current(pending: list[dict]) -> list[dict]:
    """Re-corre el matcher actual sobre cada entry pendiente y anota el
    resultado. Añade al dict del shadow:
      - `current_status`: el match_status que daría hoy el matcher
      - `current_art_id` / `current_art_name`
      - `current_link` / `current_margin`
      - `resolved_now`: bool — True si el matcher actual da `ok`
    """
    if not pending:
        return pending
    matcher = _build_matcher()
    # Import tras tener path configurado.
    from src.models import InvoiceLine

    for p in pending:
        try:
            pid = int(p.get('provider_id') or 0)
        except (TypeError, ValueError):
            pid = 0
        if not pid:
            p['current_status'] = '(sin provider_id)'
            p['resolved_now'] = False
            continue
        line = InvoiceLine(
            raw_description=p.get('variety', '') or '',
            species=p.get('species', '') or 'ROSES',
            variety=(p.get('variety') or '').upper(),
            size=int(p.get('size') or 0),
            stems_per_bunch=int(p.get('stems_per_bunch') or 0),
            grade=p.get('grade', '') or '',
        )
        try:
            matcher.match_line(pid, line)
        except Exception as exc:
            p['current_status'] = f'(error: {exc.__class__.__name__})'
            p['resolved_now'] = False
            continue
        p['current_status'] = line.match_status or ''
        p['current_art_id'] = line.articulo_id or 0
        p['current_art_name'] = line.articulo_name or ''
        p['current_link'] = float(line.link_confidence or 0.0)
        p['current_margin'] = float(line.candidate_margin or 0.0)
        p['resolved_now'] = (line.match_status == 'ok')
    return pending


def _print_pending_review(propuestas: list[dict], matched: list[dict],
                           top: int = 15,
                           verify_current: bool = False) -> None:
    """Líneas `ambiguous_match` o `sin_match` sin decisión humana todavía.

    Son el backlog operativo: el matcher las marcó para revisión y el
    operador aún no se ha pronunciado. Útil para priorizar colas.

    Con `verify_current=True` re-corremos el matcher actual sobre cada
    pendiente — si ya daría `ok`, lo marcamos como "resuelto por fix
    posterior" y queda fuera del backlog real. Esto evita que fixes
    ya aplicados (parser/matcher/sinónimo) sigan inflando el backlog
    con shadow entries viejas que nunca se reprocesaron.
    """
    print()
    print('='*70)
    print(f'Backlog pendiente de revisión humana (muestra {top})')
    print('='*70)

    # Keys con decisión ya tomada
    decided_keys = {m['decision'].get('synonym_key') for m in matched
                    if m['decision'].get('synonym_key')}

    # Dedup: nos quedamos con la propuesta más reciente por
    # (pdf, invoice, line_idx). Una misma línea puede aparecer N veces
    # si se reprocesó el PDF; solo el último intento refleja el estado
    # tras el que el operador todavía no decidió.
    latest_by_loc: dict[tuple, dict] = {}
    for p in propuestas:
        if p.get('match_status') not in ('ambiguous_match', 'sin_match'):
            continue
        if p.get('synonym_key') in decided_keys:
            continue
        loc = (p.get('pdf', ''), p.get('invoice', ''),
               int(p.get('line_idx') or -1))
        prev = latest_by_loc.get(loc)
        if prev is None or p.get('ts', '') > prev.get('ts', ''):
            latest_by_loc[loc] = p
    pending = list(latest_by_loc.values())

    if verify_current:
        print('(re-corriendo matcher actual sobre pendientes...)')
        _verify_current(pending)
        resolved = [p for p in pending if p.get('resolved_now')]
        real_pending = [p for p in pending if not p.get('resolved_now')]
        print(f'Total pendientes (dedup):     {len(pending)}')
        print(f'  Resueltos por fix posterior: {len(resolved)}  '
              f'(matcher actual daría ok)')
        print(f'  Pendientes reales:           {len(real_pending)}')
        if resolved:
            print()
            print('Resueltos (shadow stale — siguen aquí porque el lote que'
                  ' los generó nunca se reprocesó):')
            by_prov_res = Counter(p.get('provider_name', '') for p in resolved)
            for prov, n in by_prov_res.most_common(10):
                print(f'  {prov[:30]:<30s} {n}')

        pending = real_pending
        print()
        print(f'=== Pendientes reales (matcher actual sigue ambig/sin_match) ===')

    by_prov = Counter(p.get('provider_name', '') for p in pending)
    print(f'Total: {len(pending)}')
    for prov, n in by_prov.most_common(10):
        print(f'  {prov[:30]:<30s} {n}')

    print()
    print('Muestra (las N más recientes):')
    for p in sorted(pending, key=lambda x: x.get('ts', ''), reverse=True)[:top]:
        base = (f'  [{p.get("provider_name","")[:18]:18s}] '
                f'var={p.get("variety","")[:22]:<22s} '
                f'sz={p.get("size",0)} '
                f'sp={p.get("species","")[:3]} '
                f'status={p.get("match_status","")}  '
                f'propuso={p.get("proposed_articulo_id",0)}')
        if verify_current:
            cs = p.get('current_status') or '?'
            cid = p.get('current_art_id', 0)
            cl = p.get('current_link', 0.0)
            base += f'   ->  hoy: {cs} art={cid} link={cl:.2f}'
        print(base)


def _print_top_missing_articles(propuestas: list[dict],
                                 matched: list[dict],
                                 top: int) -> None:
    """Lista priorizada de artículos a dar de alta en el ERP.

    Combina tres señales, todas sobre (provider, variety, size, spb):

    1. **Rescates** — decisiones donde el operador asignó un artículo
       tras un `sin_match` del matcher (`proposed_articulo_id=0`). El
       matcher no encontró nada y el humano tuvo que buscar → o no
       había artículo en catálogo, o el que existe es un branded ajeno
       que no sirve. Alta prioridad.

    2. **Shadow `sin_match` sin decisión** — el matcher tampoco propuso
       pero el operador aún no se ha pronunciado. Backlog pendiente.

    3. **Ambiguous con foreign_brand en top1** — el mejor candidato del
       pool lleva marca ajena al proveedor. Señal de que falta un
       branded propio equivalente en el catálogo.

    Salida: frecuencia acumulada de cada (provider, variety, sz, spb).
    Los administrativos usan esta lista para priorizar altas en el ERP.
    """
    print()
    print('=' * 70)
    print(f'Artículos a dar de alta en ERP — top {top} por frecuencia')
    print('=' * 70)

    buckets: dict[tuple, dict] = defaultdict(lambda: {
        'rescues': 0, 'sin_match_pending': 0, 'foreign_only': 0,
        'last_proposed_name': '',
    })

    # Keys con decisión ya tomada (para excluir del backlog).
    decided_keys = {m['decision'].get('synonym_key') for m in matched
                    if m['decision'].get('synonym_key')}

    # (1) Rescates.
    for m in matched:
        d = m['decision']
        if d.get('action') != 'correct':
            continue
        if int(d.get('proposed_articulo_id') or 0) != 0:
            continue
        p = m['proposal'] or d
        key = (
            (p.get('provider_name') or '').strip(),
            (p.get('variety') or '').strip().upper(),
            int(p.get('size') or 0),
            int(p.get('stems_per_bunch') or 0),
        )
        buckets[key]['rescues'] += 1

    # (2) Shadow sin_match + (3) ambiguous con foreign_brand pendientes.
    for p in propuestas:
        if p.get('synonym_key') in decided_keys:
            continue
        status = p.get('match_status', '')
        key = (
            (p.get('provider_name') or '').strip(),
            (p.get('variety') or '').strip().upper(),
            int(p.get('size') or 0),
            int(p.get('stems_per_bunch') or 0),
        )
        if status == 'sin_match':
            buckets[key]['sin_match_pending'] += 1
        elif status == 'ambiguous_match':
            # Solo cuenta si el top1 tiene foreign_brand penalty (señal
            # clara de que no hay branded propio en el pool).
            pens = p.get('penalties') or []
            if any(str(x).startswith('foreign_brand') for x in pens):
                buckets[key]['foreign_only'] += 1
        proposed_name = p.get('proposed_articulo_name') or ''
        if proposed_name and not buckets[key]['last_proposed_name']:
            buckets[key]['last_proposed_name'] = proposed_name

    if not buckets:
        print('(sin datos — shadow_log.jsonl vacío o sin casos que cumplan'
              ' los criterios)')
        return

    # Score: pesa más los rescates (confirmados por operador) que el
    # backlog (pendiente) y el foreign_only (inferido del matcher).
    scored = []
    for key, stats in buckets.items():
        score = stats['rescues'] * 3 + stats['sin_match_pending'] * 1 \
            + stats['foreign_only'] * 1
        scored.append((score, key, stats))
    scored.sort(key=lambda x: -x[0])

    header = (
        f'{"Proveedor":<20s} {"Variedad":<28s} '
        f'{"sz":>4} {"spb":>4} '
        f'{"resc":>5} {"pend":>5} {"frgn":>5}   sugerencia'
    )
    print(header)
    print('-' * len(header))
    for score, (prov, variety, sz, spb), stats in scored[:top]:
        sug = stats['last_proposed_name'] or ''
        print(
            f'{prov[:20]:<20s} {variety[:28]:<28s} '
            f'{sz:>4} {spb:>4} '
            f'{stats["rescues"]:>5} {stats["sin_match_pending"]:>5} '
            f'{stats["foreign_only"]:>5}   {sug[:40]}'
        )

    shown_rescues = sum(s['rescues'] for _, _, s in scored[:top])
    shown_pending = sum(s['sin_match_pending'] for _, _, s in scored[:top])
    shown_foreign = sum(s['foreign_only'] for _, _, s in scored[:top])
    total_rescues = sum(s['rescues'] for _, _, s in scored)
    total_pending = sum(s['sin_match_pending'] for _, _, s in scored)
    total_foreign = sum(s['foreign_only'] for _, _, s in scored)
    print()
    print(f'Mostrados: rescates {shown_rescues}/{total_rescues}  '
          f'pendientes {shown_pending}/{total_pending}  '
          f'foreign_only {shown_foreign}/{total_foreign}')
    print('Score = 3×rescates + pendientes + foreign_only. '
          'Rescates pesan más (confirma acción humana).')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--since', default='',
                    help='ISO date (YYYY-MM-DD) para filtrar entries')
    ap.add_argument('--provider', default='',
                    help='Filtrar por nombre de proveedor (substring)')
    ap.add_argument('--top-errors', type=int, default=10,
                    help='Cuántos patrones de error mostrar')
    ap.add_argument('--top-missing-articles', type=int, default=0,
                    help='Lista priorizada de variedades a dar de alta '
                         'en ERP (rescates + sin_match pendientes + '
                         'ambiguous con foreign_brand). 0 = no mostrar.')
    ap.add_argument('--verify-current', action='store_true',
                    help='Re-corre el matcher actual sobre el backlog '
                         'pendiente y marca como "resuelto" las entries '
                         'que hoy darían ok (shadow stale vs pendiente '
                         'real). Paga arranque de ArticulosLoader.')
    args = ap.parse_args()

    since = None
    if args.since:
        try:
            since = datetime.fromisoformat(args.since)
        except ValueError:
            print(f'--since inválido: {args.since!r}', file=sys.stderr)
            sys.exit(2)

    propuestas, decisiones = _load_entries(since, args.provider)
    matched = _match_decisions(propuestas, decisiones)

    _print_global(propuestas, decisiones, matched)
    _print_by_provider(matched)
    _print_top_errors(matched, args.top_errors)
    _print_pending_review(propuestas, matched,
                          verify_current=args.verify_current)
    if args.top_missing_articles > 0:
        _print_top_missing_articles(propuestas, matched,
                                     args.top_missing_articles)


if __name__ == '__main__':
    main()
