"""Clasificador de errores por taxonomía E1..E10 sobre la salida del benchmark.

Lee `auto_learn_report.json` (generado por `evaluate_all.py`) y asigna a cada
proveedor con problemas su categoría dominante de error, una severidad y una
prioridad de backlog.

Taxonomía adoptada (de docs/roadmap/checklist.md):

  E1_PARSE_ZERO       — el parser no extrae ninguna línea
  E2_PARSE_PARTIAL    — extrae algunas líneas pero se deja otras (rescue alto)
  E3_LAYOUT_COORDS    — problema de columnas/coords, necesita extract_words
  E4_OCR_BAD          — OCR corrupto irrecuperable con regex
  E5_TOTAL_HEADER     — suma de líneas bien, pero header.total mal extraído
  E6_MATCH_WRONG      — artículo ERP incorrecto con línea bien leída
  E7_SYNONYM_DRIFT    — sinónimo aprendido que ya no encaja
  E8_AMBIGUOUS_LINK   — varios candidatos plausibles con margen pequeño
  E9_VALIDATION_FAIL  — stems vs bunches×spb incoherentes, total_mismatch
  E10_PROVIDER_COLLISION — dos proveedores comparten fmt y se confunden

Outputs:
  - auto_learn_taxonomy.json  — por proveedor, con categorías + severidad + prioridad
  - stdout: tabla resumen + backlog priorizado

Uso:
    python tools/classify_errors.py
    python tools/classify_errors.py --report auto_learn_report.json
    python tools/classify_errors.py --top 20
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPORT_DEFAULT = Path(__file__).resolve().parent.parent / 'auto_learn_report.json'
OUT_TAXONOMY = Path(__file__).resolve().parent.parent / 'auto_learn_taxonomy.json'

# ─── Config de proveedores (para detectar fmt compartido → E10) ────────────
try:
    from src.config import PROVIDERS
except ImportError:
    PROVIDERS = {}


# ─── Severidad: HIGH > MEDIUM > LOW ───────────────────────────────────────
_SEV_ORDER = {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1}


def _fmt_sharing_map() -> dict[str, list[str]]:
    """Mapa fmt → lista de provider_keys que lo usan."""
    fmt_map: dict[str, list[str]] = defaultdict(list)
    for key, pdata in PROVIDERS.items():
        fmt = pdata.get('fmt', 'unknown')
        if fmt != 'unknown':
            fmt_map[fmt].append(key)
    return dict(fmt_map)


def _classify_provider(prov: dict, fmt_sharing: dict[str, list[str]]) -> list[dict]:
    """Clasifica un proveedor en 0..N categorías de error, cada una con severidad.

    Devuelve lista de dicts con: category, severity, reason, impact (líneas afectadas).
    """
    findings: list[dict] = []
    n = prov.get('samples', 0)
    if n == 0:
        return findings

    detected = prov.get('detected', 0)
    parsed_any = prov.get('parsed_any', 0)
    totals_ok = prov.get('totals_ok', 0)
    total_parsed = prov.get('total_parsed', 0)
    total_rescued = prov.get('total_rescued', 0)
    ok_lines = prov.get('ok_lines', 0)
    ambig_lines = prov.get('ambiguous_lines', 0)
    sinm_lines = prov.get('sin_match_lines', 0)
    sinp_lines = prov.get('sin_parser_lines', 0)
    valerrs = prov.get('validation_errors_lines', 0)
    needs_review = prov.get('needs_review_lines', 0)
    penalties = prov.get('penalties', {})
    verdict = prov.get('verdict', '')
    folder = prov.get('folder', '')

    # Extraer info de muestras individuales para heurísticas finas
    samples_raw = prov.get('samples_raw', [])
    zero_parse_samples = sum(1 for s in samples_raw if s.get('parsed_lines', 0) == 0
                             and not s.get('error', '').startswith('no detectado'))
    ocr_samples = sum(1 for s in samples_raw
                      if s.get('extraction_source') in ('ocr', 'mixed'))
    degraded_samples = sum(1 for s in samples_raw if s.get('extraction_degraded'))
    low_ext_conf = [s for s in samples_raw
                    if s.get('extraction_confidence', 1.0) < 0.70]

    # ─── E1_PARSE_ZERO ─────────────────────────────────────────────────
    if zero_parse_samples > 0:
        sev = 'HIGH' if zero_parse_samples >= n * 0.5 else 'MEDIUM'
        findings.append({
            'category': 'E1_PARSE_ZERO',
            'severity': sev,
            'reason': f'{zero_parse_samples}/{n} muestras sin ninguna línea parseada',
            'impact': zero_parse_samples,
        })

    # ─── E2_PARSE_PARTIAL ──────────────────────────────────────────────
    if total_rescued > 0 and total_parsed > 0:
        rescue_ratio = total_rescued / (total_parsed + total_rescued)
        if rescue_ratio > 0.30:
            sev = 'HIGH'
        elif rescue_ratio > 0.10:
            sev = 'MEDIUM'
        else:
            sev = 'LOW'
        findings.append({
            'category': 'E2_PARSE_PARTIAL',
            'severity': sev,
            'reason': f'{total_rescued} líneas rescatadas vs {total_parsed} parseadas '
                      f'(ratio {rescue_ratio:.0%})',
            'impact': total_rescued,
        })

    # ─── E3_LAYOUT_COORDS ──────────────────────────────────────────────
    # Heurística: muestras nativas (no OCR) que no parsean → probable layout
    native_zero = sum(1 for s in samples_raw
                      if s.get('parsed_lines', 0) == 0
                      and s.get('extraction_source') in ('native', '')
                      and not s.get('error', '').startswith('no detectado'))
    if native_zero > 0:
        findings.append({
            'category': 'E3_LAYOUT_COORDS',
            'severity': 'HIGH' if native_zero >= 2 else 'MEDIUM',
            'reason': f'{native_zero} muestras nativas sin parsear — probable problema '
                      f'de layout/columnas',
            'impact': native_zero,
        })

    # ─── E4_OCR_BAD ────────────────────────────────────────────────────
    if low_ext_conf or degraded_samples > 0:
        # Muestras OCR con baja confianza y que fallan en parseo
        ocr_failures = sum(1 for s in samples_raw
                           if s.get('extraction_source') in ('ocr', 'mixed')
                           and (s.get('parsed_lines', 0) == 0
                                or s.get('extraction_confidence', 1.0) < 0.60))
        if ocr_failures > 0:
            findings.append({
                'category': 'E4_OCR_BAD',
                'severity': 'HIGH' if ocr_failures >= 2 else 'MEDIUM',
                'reason': f'{ocr_failures} muestras OCR con baja confianza o sin parsear',
                'impact': ocr_failures,
            })

    # ─── E5_TOTAL_HEADER ───────────────────────────────────────────────
    totals_bad = n - totals_ok
    if totals_bad > 0 and parsed_any > 0:
        # Solo si parsea algo pero el total no cuadra
        parsed_but_bad_total = sum(1 for s in samples_raw
                                   if s.get('parsed_lines', 0) > 0
                                   and not s.get('header_ok'))
        if parsed_but_bad_total > 0:
            sev = 'LOW' if parsed_but_bad_total <= n * 0.3 else 'MEDIUM'
            findings.append({
                'category': 'E5_TOTAL_HEADER',
                'severity': sev,
                'reason': f'{parsed_but_bad_total}/{parsed_any} muestras parseadas '
                          f'con header.total incorrecto',
                'impact': parsed_but_bad_total,
            })

    # ─── E6_MATCH_WRONG ────────────────────────────────────────────────
    # Señales: foreign_brand + variety_no_overlap (solo en líneas que matchearon)
    fb = penalties.get('foreign_brand', 0)
    vno = penalties.get('variety_no_overlap', 0)
    match_wrong_signals = fb + vno
    if match_wrong_signals >= 2:
        sev = 'HIGH' if match_wrong_signals >= 5 else ('MEDIUM' if match_wrong_signals >= 2 else 'LOW')
        parts = []
        if fb: parts.append(f'foreign_brand={fb}')
        if vno: parts.append(f'variety_no_overlap={vno}')
        findings.append({
            'category': 'E6_MATCH_WRONG',
            'severity': sev,
            'reason': f'{match_wrong_signals} líneas con señales de match incorrecto '
                      f'({", ".join(parts)})',
            'impact': match_wrong_signals,
        })

    # ─── E7_SYNONYM_DRIFT ──────────────────────────────────────────────
    # Solo reportar si el ratio de weak_synonym sobre líneas totales es
    # significativo — prácticamente todos los proveedores tienen alguno
    # porque los sinónimos empiezan como aprendido_en_prueba.
    ws = penalties.get('weak_synonym', 0)
    ws_ratio = ws / total_parsed if total_parsed else 0
    if ws >= 3 and ws_ratio >= 0.20:
        sev = 'HIGH' if ws >= 10 else ('MEDIUM' if ws >= 5 else 'LOW')
        findings.append({
            'category': 'E7_SYNONYM_DRIFT',
            'severity': sev,
            'reason': f'{ws}/{total_parsed} líneas con sinónimo débil '
                      f'({ws_ratio:.0%} del total)',
            'impact': ws,
        })

    # ─── E8_AMBIGUOUS_LINK ─────────────────────────────────────────────
    tie = penalties.get('tie_top2_margin', 0)
    low_ev = penalties.get('low_evidence', 0)
    if ambig_lines >= 2 or (tie + low_ev) >= 3:
        sev = 'HIGH' if ambig_lines >= 5 else ('MEDIUM' if ambig_lines >= 2 else 'LOW')
        parts = []
        if ambig_lines: parts.append(f'ambiguous_match={ambig_lines}')
        if tie: parts.append(f'tie_top2_margin={tie}')
        if low_ev: parts.append(f'low_evidence={low_ev}')
        findings.append({
            'category': 'E8_AMBIGUOUS_LINK',
            'severity': sev,
            'reason': f'{ambig_lines} líneas ambiguas ({", ".join(parts)})',
            'impact': ambig_lines,
        })

    # ─── E9_VALIDATION_FAIL ────────────────────────────────────────────
    if valerrs > 0:
        sev = 'HIGH' if valerrs >= 5 else ('MEDIUM' if valerrs >= 2 else 'LOW')
        findings.append({
            'category': 'E9_VALIDATION_FAIL',
            'severity': sev,
            'reason': f'{valerrs} líneas con errores de validación cruzada',
            'impact': valerrs,
        })

    # ─── E10_PROVIDER_COLLISION ────────────────────────────────────────
    # Buscar si el fmt lo comparten ≥2 providers con problemas
    fmt_key = None
    for s in samples_raw:
        if s.get('fmt'):
            fmt_key = s['fmt']
            break
    if fmt_key and fmt_key in fmt_sharing:
        siblings = fmt_sharing[fmt_key]
        if len(siblings) >= 2:
            # Solo marcar si el proveedor tiene problemas (no si está OK)
            if verdict != 'OK' or sinm_lines > 0:
                findings.append({
                    'category': 'E10_PROVIDER_COLLISION',
                    'severity': 'LOW',
                    'reason': f'Comparte fmt="{fmt_key}" con '
                              f'{", ".join(s for s in siblings if s != folder.lower())}',
                    'impact': 0,
                })

    return findings


def _priority_score(finding: dict, autoapprove_rate: float = 0.0,
                     total_lines: int = 0) -> float:
    """Score de prioridad para ordenar el backlog. Mayor = más urgente.

    Se pondera por:
      - severidad × peso de categoría
      - impacto en líneas afectadas
      - penalización si el proveedor ya tiene alta tasa de autoaprobación
        (weak_synonym en un proveedor al 99% auto no es urgente)
    """
    sev = _SEV_ORDER.get(finding['severity'], 0)
    impact = finding.get('impact', 0)
    # Peso por categoría: parseo > matching > validación > cosmético
    cat_weight = {
        'E1_PARSE_ZERO': 10,
        'E2_PARSE_PARTIAL': 7,
        'E3_LAYOUT_COORDS': 8,
        'E4_OCR_BAD': 6,
        'E5_TOTAL_HEADER': 2,
        'E6_MATCH_WRONG': 9,
        'E7_SYNONYM_DRIFT': 5,
        'E8_AMBIGUOUS_LINK': 4,
        'E9_VALIDATION_FAIL': 3,
        'E10_PROVIDER_COLLISION': 1,
    }.get(finding['category'], 1)
    base = sev * cat_weight + impact * 0.5
    # Descuento por autoaprobación alta: si ya va bien, baja prioridad
    # Proveedores con auto ≥ 85% pierden hasta el 60% de la prioridad
    if autoapprove_rate >= 0.85:
        base *= 0.4
    elif autoapprove_rate >= 0.70:
        base *= 0.7
    return base


def classify_all(report: list[dict]) -> list[dict]:
    """Clasifica todos los proveedores del reporte y devuelve taxonomía."""
    fmt_sharing = _fmt_sharing_map()
    taxonomy = []

    for prov in report:
        findings = _classify_provider(prov, fmt_sharing)
        if not findings:
            taxonomy.append({
                'folder': prov['folder'],
                'verdict': prov.get('verdict', ''),
                'dominant_category': 'CLEAN',
                'severity': 'NONE',
                'categories': [],
                'priority_score': 0,
                'total_lines': prov.get('total_parsed', 0),
                'autoapprove_rate': prov.get('autoapprove_rate', 0),
            })
            continue

        auto_rate = prov.get('autoapprove_rate', 0)
        tl = prov.get('total_parsed', 0)
        # Ordenar findings por prioridad
        findings.sort(key=lambda f: _priority_score(f, auto_rate, tl),
                      reverse=True)
        dominant = findings[0]

        taxonomy.append({
            'folder': prov['folder'],
            'verdict': prov.get('verdict', ''),
            'dominant_category': dominant['category'],
            'severity': dominant['severity'],
            'categories': findings,
            'priority_score': round(
                _priority_score(dominant, auto_rate, tl), 1),
            'total_lines': tl,
            'autoapprove_rate': auto_rate,
        })

    # Ordenar por prioridad global
    taxonomy.sort(key=lambda t: t['priority_score'], reverse=True)
    return taxonomy


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--report', type=Path, default=REPORT_DEFAULT,
                    help='Ruta al JSON del benchmark (default: auto_learn_report.json)')
    ap.add_argument('--top', type=int, default=0,
                    help='Mostrar solo los N proveedores más prioritarios (0 = todos)')
    args = ap.parse_args()

    if not args.report.exists():
        print(f'ERROR: no existe {args.report}. Ejecuta primero:\n'
              f'  python tools/evaluate_all.py', file=sys.stderr)
        sys.exit(1)

    report = json.loads(args.report.read_text(encoding='utf-8'))
    taxonomy = classify_all(report)

    # Guardar JSON
    OUT_TAXONOMY.write_text(
        json.dumps(taxonomy, ensure_ascii=False, indent=2, default=str),
        encoding='utf-8')

    # ─── Resumen por categoría ──────────────────────────────────────────
    cat_counter: Counter = Counter()
    cat_sev: dict[str, Counter] = defaultdict(Counter)
    for t in taxonomy:
        for f in t['categories']:
            cat_counter[f['category']] += 1
            cat_sev[f['category']][f['severity']] += 1

    print('=' * 75)
    print('TAXONOMÍA DE ERRORES E1..E10 — Resumen global')
    print('=' * 75)
    print(f'\nProveedores analizados: {len(taxonomy)}')
    clean = sum(1 for t in taxonomy if t['dominant_category'] == 'CLEAN')
    print(f'Proveedores sin problemas (CLEAN): {clean}')
    print(f'Proveedores con problemas: {len(taxonomy) - clean}')

    print('\n── Distribución por categoría ──')
    print(f'{"Categoría":<25} {"Total":>5} {"HIGH":>5} {"MED":>5} {"LOW":>5}')
    print('─' * 50)
    for cat in ['E1_PARSE_ZERO', 'E2_PARSE_PARTIAL', 'E3_LAYOUT_COORDS',
                'E4_OCR_BAD', 'E5_TOTAL_HEADER', 'E6_MATCH_WRONG',
                'E7_SYNONYM_DRIFT', 'E8_AMBIGUOUS_LINK',
                'E9_VALIDATION_FAIL', 'E10_PROVIDER_COLLISION']:
        total = cat_counter.get(cat, 0)
        if total == 0:
            continue
        h = cat_sev[cat].get('HIGH', 0)
        m = cat_sev[cat].get('MEDIUM', 0)
        lo = cat_sev[cat].get('LOW', 0)
        print(f'{cat:<25} {total:>5} {h:>5} {m:>5} {lo:>5}')

    # ─── Backlog priorizado ────────────────────────────────────────────
    problematic = [t for t in taxonomy if t['dominant_category'] != 'CLEAN']
    if args.top:
        problematic = problematic[:args.top]

    print(f'\n{"=" * 75}')
    print(f'BACKLOG PRIORIZADO — Top {len(problematic)} proveedores')
    print('=' * 75)
    print(f'{"#":>3} {"Proveedor":<22} {"Prio":>5} {"Sev":<6} '
          f'{"Categoría dominante":<25} {"Líneas":>6} {"Auto%":>6}')
    print('─' * 80)
    for i, t in enumerate(problematic, 1):
        print(f'{i:>3} {t["folder"]:<22} {t["priority_score"]:>5.0f} '
              f'{t["severity"]:<6} {t["dominant_category"]:<25} '
              f'{t["total_lines"]:>6} {t["autoapprove_rate"]*100:>5.1f}%')

    # ─── Detalle de los top-10 ─────────────────────────────────────────
    top_detail = problematic[:10]
    if top_detail:
        print(f'\n{"=" * 75}')
        print('DETALLE — Top 10')
        print('=' * 75)
        for t in top_detail:
            print(f'\n  {t["folder"]} (verdict={t["verdict"]}, '
                  f'lines={t["total_lines"]}, auto={t["autoapprove_rate"]*100:.0f}%)')
            for f in t['categories']:
                marker = '>>>' if f is t['categories'][0] else '   '
                print(f'    {marker} [{f["severity"]}] {f["category"]}: {f["reason"]}')

    print(f'\nArtefacto: {OUT_TAXONOMY.name}')


if __name__ == '__main__':
    main()
