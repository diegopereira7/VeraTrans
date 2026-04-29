#!/usr/bin/env python3
"""VeraBuy — Entrenador Universal de Traductores v2.0 (CLI).

Uso interactivo: python cli.py
"""
from __future__ import annotations

import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from datetime import datetime
from pathlib import Path

try:
    from tabulate import tabulate
except ImportError:
    print("Falta 'tabulate'. Ejecuta: pip install tabulate")
    input("Enter...")
    sys.exit(1)

from src.config import (
    CLIColors as C, BASE_DIR, PDF_DIR, EXPORT_DIR, FUZZY_THRESHOLD_RESOLVE,
    FILE_ENCODING,
)
from src.models import InvoiceLine
from src.articulos import ArticulosLoader
from src.sinonimos import SynonymStore
from src.historial import History
from src.matcher import Matcher, rescue_unparsed_lines, split_mixed_boxes, reclassify_assorted
from src.pdf import detect_provider
from src.parsers import FORMAT_PARSERS


def clear():
    os.system('cls' if sys.platform == 'win32' else 'clear')


def show_banner():
    print(f"""
  {C.BOLD}{C.CYAN}╔═══════════════════════════════════════════════════════╗
  ║     VERABUY — Entrenador Universal de Traductores   ║
  ╚═══════════════════════════════════════════════════════╝{C.RESET}""")


def find_pdfs() -> list[str]:
    pdfs = []
    for d in [BASE_DIR] + ([PDF_DIR] if PDF_DIR.exists() else []):
        for f in sorted(d.glob('*.pdf')):
            pdfs.append(str(f))
    return pdfs


def find_articulos_sql() -> str | None:
    for pat in ['articulos*.sql', '*articulos*.sql']:
        for f in sorted(BASE_DIR.glob(pat)):
            if f.stat().st_size > 100_000:
                return str(f)
    return None


def show_result(header, lines, syns):
    tok = sum(1 for l in lines if l.match_status == 'ok')
    tfail = sum(1 for l in lines if l.match_status == 'sin_match')
    tusd = sum(l.line_total for l in lines)
    print(f"\n  {C.BOLD}{header.provider_name} — {header.invoice_number}{C.RESET}"
          f"  |  {header.date}  |  AWB: {header.awb}")
    tbl = []
    for i, l in enumerate(lines, 1):
        st = (f"{C.OK}✓ {l.match_method}{C.RESET}" if l.match_status == 'ok'
              else f"{C.ERR}✗ SIN MATCH{C.RESET}")
        tbl.append([
            i, l.species[:4], l.variety[:20],
            f"{l.size}cm" if l.size else '-', l.stems_per_bunch, l.stems,
            f"${l.price_per_stem:.4f}" if l.price_per_stem else '-',
            f"${l.line_total:.2f}", l.label[:8], st,
        ])
    print()
    print(tabulate(tbl,
                   headers=['#', 'Sp', 'Variedad', 'Talla', 'St/B', 'Stems',
                            '$/St', 'Total', 'Label', 'Match'],
                   tablefmt='simple'))
    uniq = {l.match_key(): l for l in lines}
    uok = sum(1 for l in uniq.values() if l.match_status == 'ok')
    rate = (uok / len(uniq) * 100) if uniq else 0
    col = C.OK if rate >= 80 else C.WARN if rate >= 50 else C.ERR
    bar = f"{'█' * int(rate / 5)}{'░' * (20 - int(rate / 5))}"
    print(f"\n  {C.BOLD}Resumen:{C.RESET} {len(lines)} líneas | "
          f"{sum(l.stems for l in lines)} stems | ${tusd:,.2f}")
    print(f"  Match:  {col}{bar} {rate:.0f}%{C.RESET} ({tok} OK, {tfail} sin match)"
          f" | Sinónimos: {syns.count()}")
    return tok, tfail


def resolve_unmatched(provider_id, lines, art, syns):
    seen = set()
    um = []
    for l in lines:
        if l.match_status != 'sin_match':
            continue
        k = l.match_key()
        if k not in seen:
            seen.add(k)
            um.append(l)
    if not um:
        print(f"\n  {C.OK}¡Todo con match!{C.RESET}")
        return 0
    print(f"\n  {C.BOLD}RESOLVER {len(um)} LÍNEAS SIN MATCH{C.RESET}")
    print(f"  {C.DIM}[nº] candidato | [id] artículo directo | [n] nuevo | [Enter] saltar | [q] terminar{C.RESET}")
    res = 0
    for i, l in enumerate(um, 1):
        print(f"\n  {C.CYAN}[{i}/{len(um)}]{C.RESET} {C.BOLD}{l.expected_name()}{C.RESET}"
              f"  {C.DIM}({l.species}, {l.label}, {l.farm}){C.RESET}")
        cands = art.fuzzy_search(l, threshold=FUZZY_THRESHOLD_RESOLVE)
        if cands:
            for j, c in enumerate(cands, 1):
                sc = C.OK if c['similitud'] >= 70 else C.WARN
                print(f"    {sc}{j}{C.RESET}. {c['nombre']} "
                      f"{C.DIM}(id={c['id']}, {c['similitud']}%){C.RESET}")
        else:
            print(f"    {C.DIM}Sin candidatos{C.RESET}")
        try:
            resp = input(f"  {C.MAG}→ {C.RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if resp.lower() == 'q':
            break
        elif resp == '':
            continue
        elif resp.lower() == 'n':
            syns.add(provider_id, l, 0, f"[NUEVO] {l.expected_name()}", 'pendiente')
            print(f"    {C.WARN}Marcado para alta{C.RESET}")
        else:
            try:
                idx = int(resp)
                if cands and 1 <= idx <= len(cands):
                    c = cands[idx - 1]
                    syns.add(provider_id, l, c['id'], c['nombre'], 'manual')
                    print(f"    {C.OK}✓ → {c['nombre']}{C.RESET}")
                    res += 1
                elif idx > 0:
                    a = art.articulos.get(idx)
                    if a:
                        syns.add(provider_id, l, a['id'], a['nombre'], 'manual')
                        print(f"    {C.OK}✓ → {a['nombre']}{C.RESET}")
                        res += 1
                    else:
                        print(f"    {C.ERR}id no encontrado{C.RESET}")
            except ValueError:
                pass
    return res


def auto_export(syns):
    if syns.count() == 0:
        return
    EXPORT_DIR.mkdir(exist_ok=True)
    with open(EXPORT_DIR / 'sinonimos_universal_LATEST.sql', 'w',
              encoding=FILE_ENCODING) as f:
        f.write(syns.export_sql())


def process_pdfs(pdfs, art, syns, hist, matcher):
    n = 0
    for pdf in pdfs:
        name = Path(pdf).name
        pdata = detect_provider(pdf)
        if not pdata:
            print(f"\n  {C.WARN}⚠ No reconocido:{C.RESET} {name}")
            continue
        # Propagar pdf_path para parsers que usan pdfplumber.extract_tables
        # (AlegriaParser → Tierra Verde, Olimpo, Ceres). Sin esto caen al
        # fallback de texto silenciosamente — lección sesión 12f.
        pdata['pdf_path'] = pdf
        fmt = pdata['fmt']
        parser = FORMAT_PARSERS.get(fmt)
        if not parser:
            print(f"\n  {C.WARN}⚠ Sin parser para formato '{fmt}':{C.RESET} {name}")
            continue
        try:
            header, lines = parser.parse(pdata['text'], pdata)
        except Exception as e:
            print(f"\n  {C.ERR}✗ Error parseando {name}: {e}{C.RESET}")
            continue
        lines = split_mixed_boxes(lines)
        rescued = rescue_unparsed_lines(pdata['text'], lines)
        if rescued:
            lines.extend(rescued)
            print(f"  {C.WARN}⚠ {len(rescued)} línea(s) rescatadas "
                  f"(no capturadas por el parser){C.RESET}")
        if not lines:
            print(f"\n  {C.WARN}⚠ Sin líneas extraídas:{C.RESET} {name}")
            continue
        pid = pdata['id']
        lines = matcher.match_all(pid, lines)
        lines = reclassify_assorted(lines)
        already = ' (ya)' if hist.was_processed(header.invoice_number or name) else ''
        print(f"\n  {C.CYAN}{'━' * 57}{C.RESET}\n"
              f"  {C.BOLD}📄 {name}{C.RESET}{C.DIM}{already}{C.RESET}")
        ok, fail = show_result(header, lines, syns)
        hist.add(header.invoice_number or name, name, pdata['name'],
                 header.total, len(lines), ok, fail)
        n += 1
        um = [l for l in lines if l.match_status == 'sin_match']
        if um:
            uu = set(l.match_key() for l in um)
            try:
                resp = input(f"\n  {C.MAG}¿Resolver {len(uu)} sin match? "
                             f"[S/n/q]: {C.RESET}").strip().lower()
            except (EOFError, KeyboardInterrupt):
                break
            if resp == 'q':
                break
            elif resp != 'n':
                r = resolve_unmatched(pid, lines, art, syns)
                if r > 0:
                    lines = matcher.match_all(pid, lines)
                    show_result(header, lines, syns)
                    hist.add(
                        header.invoice_number or name, name, pdata['name'],
                        header.total, len(lines),
                        sum(1 for l in lines if l.match_status == 'ok'),
                        sum(1 for l in lines if l.match_status == 'sin_match'),
                    )
    auto_export(syns)
    print(f"\n  {C.OK}Procesadas {n} facturas.{C.RESET}")


def show_stats(syns, hist):
    print(f"\n  {C.BOLD}ESTADÍSTICAS{C.RESET}\n  {'─' * 50}")
    print(f"  Sinónimos totales: {syns.count()}")
    if hist.entries:
        total_inv = len(hist.entries)
        total_ok = sum(v.get('ok', 0) for v in hist.entries.values())
        total_fail = sum(v.get('sin_match', 0) for v in hist.entries.values())
        total_usd = sum(v.get('total_usd', 0) for v in hist.entries.values())
        print(f"  Facturas: {total_inv}  |  Líneas OK: {total_ok}  |  "
              f"Sin match: {total_fail}  |  ${total_usd:,.2f}")


def setup():
    sql = find_articulos_sql()
    if not sql:
        print(f"\n  {C.WARN}No se encontró articulos*.sql{C.RESET}")
        try:
            sql = input(f"  {C.MAG}Ruta: {C.RESET}").strip().strip('"').strip("'")
        except (EOFError, KeyboardInterrupt):
            return None
        if not sql or not os.path.exists(sql):
            return None
    art = ArticulosLoader()
    print(f"  {C.DIM}Cargando {Path(sql).name}...{C.RESET}", end='', flush=True)
    n = art.load_from_sql(sql)
    rosas = len(art.rosas_ec)
    print(f" {C.OK}{n:,} artículos, {rosas} rosas EC{C.RESET}")
    return art


def main():
    clear()
    show_banner()
    print()
    art = setup()
    if not art:
        input("\n  No se cargaron artículos. Enter para salir...")
        return
    syns = SynonymStore()
    hist = History()
    matcher = Matcher(art, syns)
    pdfs = find_pdfs()
    detected = [(p, detect_provider(p)) for p in pdfs]
    known = [(p, d) for p, d in detected if d]
    unknown = [p for p, d in detected if not d]
    print(f"  {C.DIM}Sinónimos: {syns.count()} | PDFs detectados: "
          f"{len(known)}/{len(pdfs)}{C.RESET}")
    if unknown:
        print(f"  {C.WARN}Sin detectar ({len(unknown)}):{C.RESET}")
        for p in unknown[:5]:
            print(f"    {C.DIM}📄 {Path(p).name}{C.RESET}")
    provs_found = {}
    for p, d in known:
        provs_found[d['name']] = provs_found.get(d['name'], 0) + 1
    for pn, cnt in sorted(provs_found.items()):
        print(f"    {C.DIM}✓ {pn}: {cnt} PDF(s){C.RESET}")

    while True:
        print(f"\n  {C.BOLD}{'─' * 47}{C.RESET}\n  {C.BOLD}¿Qué quieres hacer?{C.RESET}\n")
        print(f"    {C.CYAN}1{C.RESET}  Procesar todos los PDFs")
        print(f"    {C.CYAN}2{C.RESET}  Procesar un proveedor concreto")
        print(f"    {C.CYAN}3{C.RESET}  Procesar un PDF concreto")
        print(f"    {C.CYAN}4{C.RESET}  Estadísticas e historial")
        print(f"    {C.CYAN}5{C.RESET}  Exportar SQL para la BD")
        print(f"    {C.CYAN}6{C.RESET}  Recargar artículos")
        print(f"    {C.CYAN}0{C.RESET}  Salir")
        try:
            ch = input(f"\n  {C.MAG}→ {C.RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if ch == '1':
            pdfs = find_pdfs()
            if not pdfs:
                print(f"\n  {C.WARN}No hay PDFs{C.RESET}")
            else:
                process_pdfs(pdfs, art, syns, hist, matcher)
        elif ch == '2':
            provs = {}
            for p in find_pdfs():
                d = detect_provider(p)
                if d:
                    provs.setdefault(d['name'], []).append(p)
            if not provs:
                print(f"\n  {C.WARN}Sin PDFs detectados{C.RESET}")
                continue
            print(f"\n  {C.BOLD}Proveedores:{C.RESET}")
            plist = sorted(provs.items())
            for i, (pn, fps) in enumerate(plist, 1):
                print(f"    {C.CYAN}{i}{C.RESET}. {pn} ({len(fps)} PDF)")
            try:
                r = input(f"\n  {C.MAG}Nº: {C.RESET}").strip()
            except (EOFError, KeyboardInterrupt):
                continue
            try:
                idx = int(r) - 1
                if 0 <= idx < len(plist):
                    process_pdfs(plist[idx][1], art, syns, hist, matcher)
            except ValueError:
                pass
        elif ch == '3':
            pdfs = find_pdfs()
            if not pdfs:
                continue
            print(f"\n  {C.BOLD}PDFs:{C.RESET}")
            for i, p in enumerate(pdfs, 1):
                print(f"    {C.CYAN}{i}{C.RESET}. {Path(p).name}")
            try:
                r = input(f"\n  {C.MAG}Nº: {C.RESET}").strip()
            except (EOFError, KeyboardInterrupt):
                continue
            try:
                idx = int(r) - 1
                if 0 <= idx < len(pdfs):
                    process_pdfs([pdfs[idx]], art, syns, hist, matcher)
            except ValueError:
                pass
        elif ch == '4':
            show_stats(syns, hist)
        elif ch == '5':
            EXPORT_DIR.mkdir(exist_ok=True)
            sql = syns.export_sql()
            ts = f"{datetime.now():%Y%m%d_%H%M}"
            for fp in [EXPORT_DIR / f"sinonimos_{ts}.sql",
                       EXPORT_DIR / 'sinonimos_universal_LATEST.sql']:
                with open(fp, 'w', encoding=FILE_ENCODING) as f:
                    f.write(sql)
            print(f"\n  {C.OK}Exportado → exportar/sinonimos_universal_LATEST.sql{C.RESET}")
        elif ch == '6':
            art = setup() or art
            matcher = Matcher(art, syns)
        elif ch == '0':
            break

    if syns.count() > 0:
        auto_export(syns)
        print(f"\n  {C.OK}Sinónimos guardados.{C.RESET}")
    print(f"\n  {C.DIM}¡Hasta luego!{C.RESET}\n")


if __name__ == '__main__':
    main()
