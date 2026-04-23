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


def _print_pending_review(propuestas: list[dict], matched: list[dict],
                           top: int = 15) -> None:
    """Líneas `ambiguous_match` o `sin_match` sin decisión humana todavía.

    Son el backlog operativo: el matcher las marcó para revisión y el
    operador aún no se ha pronunciado. Útil para priorizar colas.
    """
    print()
    print('='*70)
    print(f'Backlog pendiente de revisión humana (muestra {top})')
    print('='*70)

    # Keys con decisión ya tomada
    decided_keys = {m['decision'].get('synonym_key') for m in matched
                    if m['decision'].get('synonym_key')}

    pending = [p for p in propuestas
               if p.get('match_status') in ('ambiguous_match', 'sin_match')
               and p.get('synonym_key') not in decided_keys]

    by_prov = Counter(p.get('provider_name', '') for p in pending)
    print(f'Total pendientes: {len(pending)}')
    for prov, n in by_prov.most_common(10):
        print(f'  {prov[:30]:<30s} {n}')

    print()
    print('Muestra (las N más recientes):')
    for p in sorted(pending, key=lambda x: x.get('ts', ''), reverse=True)[:top]:
        print(f'  [{p.get("provider_name","")[:18]:18s}] '
              f'var={p.get("variety",""):<20s} '
              f'sz={p.get("size",0)} '
              f'sp={p.get("species","")[:3]} '
              f'status={p.get("match_status","")}  '
              f'propuso={p.get("proposed_articulo_id",0)}')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--since', default='',
                    help='ISO date (YYYY-MM-DD) para filtrar entries')
    ap.add_argument('--provider', default='',
                    help='Filtrar por nombre de proveedor (substring)')
    ap.add_argument('--top-errors', type=int, default=10,
                    help='Cuántos patrones de error mostrar')
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
    _print_pending_review(propuestas, matched)


if __name__ == '__main__':
    main()
