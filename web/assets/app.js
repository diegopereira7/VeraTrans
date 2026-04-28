/* ══════════════════════════════════════════════════════════════════════
   VeraFact — app.js (v2)
   ──────────────────────────────────────────────────────────────────────
   - Pipeline: upload → /api.php?action=process_pdf → renderResult
   - renderResult: header (stat-cards + banner + filters) + tabla numerada
     con progress bars, badges OR./EST., tree-style mixed, input id_erp
   - Drawer v2: 3 secciones (datos / vinculado / candidatos) + 3 acciones
   - Tabs: upload, batch, history, synonyms, learned
   ══════════════════════════════════════════════════════════════════════ */

/* global PROVIDER_NAMES */
(() => {
'use strict';

// ══════════════════════════════════════════════════════════════════════
// Estado global
// ══════════════════════════════════════════════════════════════════════
const STATE = {
    currentResult: null,   // respuesta cruda del /process_pdf
    lines: [],             // líneas normalizadas [{idx, raw, species, variety, size, spb, stems, price, total, match, confidence, box_type, group_key, is_mixed_child, ...}]
    filter: 'all',         // 'all' | 'review' | 'ok'
    search: '',
    provider_id: null,
    invoice_key: '',
};

const API = 'api.php';

// ══════════════════════════════════════════════════════════════════════
// Utils
// ══════════════════════════════════════════════════════════════════════
const $  = (s, el=document) => el.querySelector(s);
const $$ = (s, el=document) => Array.from(el.querySelectorAll(s));
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt$ = n => (n==null||isNaN(n)) ? '—' : '$' + Number(n).toFixed(2);
const fmtPrice = n => (n==null||isNaN(n)) ? '—' : '$' + Number(n).toFixed(4);
const fmtInt = n => (n==null||isNaN(n)) ? '—' : Number(n).toLocaleString('es-ES');
const debounce = (fn, ms=200) => {
    let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
};
const providerName = id => (window.PROVIDER_NAMES?.[id]) || `Proveedor ${id}`;

async function apiGet(action, params={}) {
    const qs = new URLSearchParams({ action, ...params }).toString();
    const r = await fetch(`${API}?${qs}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
}
async function apiPost(action, body) {
    const r = await fetch(`${API}?action=${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {})
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
}

// ══════════════════════════════════════════════════════════════════════
// Tabs / navegación
// ══════════════════════════════════════════════════════════════════════
const TAB_STORAGE_KEY = 'verafact.activeTab';

function activateTab(tab) {
    const validTabs = ['upload', 'batch', 'history', 'synonyms', 'learned'];
    if (!validTabs.includes(tab)) tab = 'upload';
    $$('.nav-btn').forEach(b => b.classList.toggle('is-active', b.dataset.tab === tab));
    $$('.tab').forEach(s => {
        const isActive = s.id === `tab-${tab}`;
        s.classList.toggle('active', isActive);
        s.classList.toggle('hidden', !isActive);
    });
    try { localStorage.setItem(TAB_STORAGE_KEY, tab); } catch (e) {}
    // Lazy load
    if (tab === 'history')  loadHistory();
    if (tab === 'synonyms') loadSynonyms();
    if (tab === 'learned')  loadLearned();
}

function initTabs() {
    $$('.nav-btn').forEach(btn => {
        btn.addEventListener('click', () => activateTab(btn.dataset.tab));
    });
    // Restore last tab on page load.
    let saved = 'upload';
    try { saved = localStorage.getItem(TAB_STORAGE_KEY) || 'upload'; } catch (e) {}
    activateTab(saved);
}

// ══════════════════════════════════════════════════════════════════════
// Upload
// ══════════════════════════════════════════════════════════════════════
function initUpload() {
    const drop  = $('#dropZone');
    const input = $('#pdfInput');
    $('#btnSelectFile')?.addEventListener('click', () => input.click());
    input?.addEventListener('change', e => {
        if (e.target.files[0]) uploadPdf(e.target.files[0]);
    });
    drop?.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('drag-over'); });
    drop?.addEventListener('dragleave', () => drop.classList.remove('drag-over'));
    drop?.addEventListener('drop', e => {
        e.preventDefault(); drop.classList.remove('drag-over');
        if (e.dataTransfer.files[0]) uploadPdf(e.dataTransfer.files[0]);
    });
    $('#btnNewUpload')?.addEventListener('click', resetUpload);
    $('#btnGenerarOrden')?.addEventListener('click', generarOrden);
}
function resetUpload() {
    $('#resultSection').classList.add('hidden');
    $('#dropZone').classList.remove('hidden');
    $('#pdfInput').value = '';
    STATE.currentResult = null; STATE.lines = [];
}
async function uploadPdf(file) {
    $('#dropZone').classList.add('hidden');
    $('#processing').classList.remove('hidden');
    $('#resultSection').classList.add('hidden');
    const fd = new FormData();
    fd.append('pdf', file);
    try {
        const r = await fetch(`${API}?action=process_pdf`, { method: 'POST', body: fd });
        const data = await r.json();
        $('#processing').classList.add('hidden');
        if (!data.ok) {
            alert('Error: ' + (data.error || 'desconocido'));
            $('#dropZone').classList.remove('hidden');
            return;
        }
        STATE.currentResult = data;
        STATE.provider_id   = data.provider_id || data.id_proveedor || null;
        STATE.invoice_key   = data.invoice_key || data.numero_factura || '';
        STATE.lines         = normalizeLines(data.lines || data.lineas || []);
        $('#resultSection').classList.remove('hidden');
        renderResult();
    } catch (e) {
        $('#processing').classList.add('hidden');
        $('#dropZone').classList.remove('hidden');
        alert('Error de red: ' + e.message);
    }
}

// ══════════════════════════════════════════════════════════════════════
// Normalización de líneas (unifica nombres del backend)
// ══════════════════════════════════════════════════════════════════════
function normalizeLines(raw) {
    return raw.map((l, i) => ({
        idx:            i,
        raw:            l.raw_description || l.raw || l.descripcion_original || '',
        species:        l.species || l.especie || '',
        variety:        l.variety || l.variedad || '',
        size:           l.size ?? l.talla ?? null,
        spb:            l.spb ?? l.stems_per_bunch ?? l.paquete ?? null,
        stems:          l.stems ?? l.tallos ?? null,
        grade:          l.grade || l.grado || '',
        price:          l.price_per_stem ?? l.precio_stem ?? l.price ?? null,
        total:          l.total_line ?? l.total ?? l.total_linea ?? null,
        box_type:       l.box_type || l.caja || '',
        label:          l.label || '',
        articulo_id:    l.articulo_id || l.id_articulo || 0,
        articulo_id_erp:l.articulo_id_erp || l.id_erp || '',
        articulo_name:  l.articulo_name || l.nombre_articulo || '',
        articulo_ref:   l.articulo_ref || l.referencia || '',
        match_status:   l.match_status || 'pendiente',
        match_method:   l.match_method || '',
        confidence:     (typeof l.confidence === 'number') ? l.confidence
                        : (typeof l.match_score === 'number') ? l.match_score : null,
        origin:         l.origin || l.match_origin || '',   // OR / EST / STD
        group_key:      l.group_key || '',                   // para mixed box
        is_mixed_child: !!(l.is_mixed_child || l.es_hijo_mixto),
        _raw_line:      l,
    }));
}

// ══════════════════════════════════════════════════════════════════════
// Render principal — ORQUESTA header + tabla
// ══════════════════════════════════════════════════════════════════════
function renderResult() {
    renderHeader();
    renderTable();
}

// ── Badge de origen (OR/EST/STD) — deriva del match_method u origin ────
function computeOriginBadge(line) {
    const v = (line.origin || line.match_method || '').toUpperCase();
    if (!v || line.match_status === 'sin_match') return null;
    if (v.includes('EST') || v.includes('ESTIMATE') || v.includes('FUZZY')) return 'est';
    if (v.includes('STD') || v.includes('STANDARD')) return 'std';
    // por defecto: es un match "original" (tabla directa / id_erp / sinónimo)
    return 'or';
}

// ── Status derivado ───────────────────────────────────────────────────
function computeStatus(line) {
    const s = (line.match_status || '').toLowerCase();
    if (s === 'ok' || s === 'matched' || (line.articulo_id > 0 && !s)) return 'ok';
    if (s === 'sin_match' || s === 'no_match' || !line.articulo_id) return 'sin_match';
    if (s === 'revisar' || s === 'pendiente' || s === 'review') return 'revisar';
    return s || 'revisar';
}
// Una línea procede de un matching estimado (fuzzy / hint) si su
// match_method u origin contienen 'fuzzy', 'estimate' o 'est'. Estos
// matches se proponen aunque el solapamiento literal no sea total —
// el operador debería revisarlos antes de aceptarlos como sinónimo.
function _isFuzzyOrigin(line) {
    const m = String(line.match_method || '').toUpperCase();
    const o = String(line.origin       || '').toUpperCase();
    const txt = m + ' ' + o;
    return /\bFUZZY\b|\bESTIMATE\b|\bEST\b|AUTO-FUZZY/.test(txt);
}

function needsReview(line) {
    const st = computeStatus(line);
    // Regla alineada con computeStats: cualquier status que NO sea
    // `ok` confiable es review (cubre sin_match, revisar/pendiente,
    // ambiguous_match, llm_extraido, sin_parser, etc.). Para `ok` el
    // gate es la confianza. Umbral 0.85 (no 0.90) para aceptar
    // sinónimos `aprendido_confirmado` (trust 0.85, conf ~0.846) sin
    // mandarlos a revisar — sí lo eran sinónimos auto-aprendidos pero
    // con ≥2 hits independientes confirmando la decisión.
    if (st !== 'ok') return true;
    if (line.confidence != null && line.confidence < 0.84) return true;
    // Matches por estimación/fuzzy también deben revisarse aunque
    // el matcher haya devuelto `ok` con confianza alta — la
    // evidencia es indirecta. La confirmación del operador (✓) o
    // del buscador limpia el match_method a 'sinónimo'/'manual-web'.
    if (_isFuzzyOrigin(line)) return true;
    return false;
}

// ══════════════════════════════════════════════════════════════════════
// renderHeader — stat-cards grandes + banner atención + buscador + tabs
// ══════════════════════════════════════════════════════════════════════
function renderHeader() {
    const r = STATE.currentResult;
    if (!r) return;
    const lines = STATE.lines;

    const stats = computeStats(lines);
    const provider = r.provider || r.proveedor || providerName(STATE.provider_id);
    const invoice  = STATE.invoice_key || '—';
    const fecha    = r.fecha || r.invoice_date || '';
    const pdfUrl   = r.pdf_url || r.pdf_path || '';

    const header = $('#invoiceHeader');
    header.innerHTML = `
        <div class="invoice-strip">
            <div class="invoice-strip__icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="13" y2="17"/></svg>
            </div>
            <div class="invoice-strip__fields">
                <div class="invoice-strip__field">
                    <span class="invoice-strip__label">Proveedor</span>
                    <strong>${esc(provider)}</strong>
                </div>
                <div class="invoice-strip__field">
                    <span class="invoice-strip__label">Nº Factura</span>
                    <strong>${esc(invoice)}</strong>
                </div>
                <div class="invoice-strip__field">
                    <span class="invoice-strip__label">Fecha</span>
                    <strong>${esc(fecha || '—')}</strong>
                </div>
                <div class="invoice-strip__field">
                    <span class="invoice-strip__label">Divisa</span>
                    <strong>USD</strong>
                </div>
                ${r.pdf ? `<div class="invoice-strip__field">
                    <span class="invoice-strip__label">PDF</span>
                    <strong>${esc(r.pdf)}</strong>
                </div>` : ''}
            </div>
            ${pdfUrl ? `<a id="viewPdfBtn" class="invoice-strip__action" href="${esc(pdfUrl)}" target="_blank" rel="noopener">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                Ver PDF</a>` : ''}
        </div>

        <div class="stats-strip">
            <div class="stats-strip__cell">
                <div class="stats-strip__label">Líneas</div>
                <div class="stats-strip__value">${stats.total}</div>
            </div>
            <div class="stats-strip__cell">
                <div class="stats-strip__label">Match OK</div>
                <div class="stats-strip__value stats-strip__value--ok">${stats.ok}</div>
            </div>
            <div class="stats-strip__cell">
                <div class="stats-strip__label">Revisar</div>
                <div class="stats-strip__value stats-strip__value--warn">${stats.review}</div>
            </div>
            <div class="stats-strip__cell">
                <div class="stats-strip__label">Sin match</div>
                <div class="stats-strip__value stats-strip__value--err">${stats.sin}</div>
            </div>
            <div class="stats-strip__cell">
                <div class="stats-strip__label">Total factura</div>
                <div class="stats-strip__value">${fmt$(stats.total_usd)}</div>
            </div>
        </div>

        <div id="attentionBanner" class="${stats.review + stats.sin > 0 ? '' : 'hidden'}">
            <div class="attention-banner">
                <svg class="attention-banner__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                <div class="attention-banner__text">
                    <strong>${stats.review + stats.sin} línea${stats.review+stats.sin===1?'':'s'} requiere${stats.review+stats.sin===1?'':'n'} tu atención.</strong>
                    ${stats.sin > 0 ? ` ${stats.sin} sin vincular` : ''}${stats.sin > 0 && stats.review > 0 ? ' y' : ''}${stats.review > 0 ? ` ${stats.review} con confianza baja` : ''}.
                </div>
                <button class="attention-banner__action" id="btnFilterReview">Revisar ahora →</button>
            </div>
        </div>

        <div class="filters-bar">
            <div class="search-input">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                <input type="text" id="searchInput" placeholder="Buscar descripción, variedad, artículo, id_erp..." value="${esc(STATE.search)}">
            </div>
            <div class="filter-tabs" id="filtersBar">
                <button class="filter-tab ${STATE.filter==='all'?'is-active':''}" data-filter="all">Todas <span class="filter-tab__count">${stats.total}</span></button>
                <button class="filter-tab ${STATE.filter==='review'?'is-active':''}" data-filter="review">Revisar <span class="filter-tab__count">${stats.review + stats.sin}</span></button>
                <button class="filter-tab ${STATE.filter==='ok'?'is-active':''}" data-filter="ok">OK <span class="filter-tab__count">${stats.ok}</span></button>
            </div>
        </div>
    `;
    // Vaciar stats-bar legacy
    const sb = $('#statsBar'); if (sb) sb.innerHTML = '';

    // Listeners header
    $('#searchInput')?.addEventListener('input', debounce(e => {
        STATE.search = e.target.value.trim().toLowerCase();
        renderTable();
    }, 180));
    $$('.filter-tab').forEach(b => b.addEventListener('click', () => {
        STATE.filter = b.dataset.filter;
        renderHeader(); renderTable();
    }));
    $('#btnFilterReview')?.addEventListener('click', () => {
        STATE.filter = 'review';
        renderHeader(); renderTable();
    });
}

function computeStats(lines) {
    let ok=0, sin=0, review=0, stems=0, total=0;
    for (const l of lines) {
        if (l.is_mixed_child) continue;  // no contar hijos mezclados
        const st = computeStatus(l);
        if (st === 'ok' && !needsReview(l)) ok++;
        else if (st === 'sin_match') sin++;
        else review++;
        stems += Number(l.stems || 0);
        total += Number(l.total || 0);
    }
    return {
        total: lines.filter(l => !l.is_mixed_child).length,
        ok, sin, review, stems, total_usd: total
    };
}

// ══════════════════════════════════════════════════════════════════════
// renderTable — numeración, progress bars, badges OR./EST., tree mixed, input id_erp
// ══════════════════════════════════════════════════════════════════════
function renderTable() {
    const tbody = $('#linesTable tbody');
    if (!tbody) return;
    const lines = filterLines(STATE.lines);

    if (!lines.length) {
        tbody.innerHTML = `<tr><td colspan="12" style="padding:30px;text-align:center;color:var(--ink-muted)">
            ${STATE.search || STATE.filter !== 'all' ? 'Sin resultados para el filtro actual' : 'No hay líneas'}
        </td></tr>`;
        return;
    }

    // Agrupar por group_key para render tree-style en mixed box
    const rows = [];
    const grouped = new Map();   // key -> parent line
    for (const l of lines) {
        if (l.group_key && l.box_type && /mix/i.test(l.box_type)) {
            if (!grouped.has(l.group_key)) grouped.set(l.group_key, l);
        }
    }

    lines.forEach((l, visibleIdx) => {
        rows.push(renderLineRow(l, visibleIdx + 1));
    });

    tbody.innerHTML = rows.join('');
    wireTableEvents();
}

function filterLines(lines) {
    return lines.filter(l => {
        if (STATE.filter === 'ok') {
            if (computeStatus(l) !== 'ok' || needsReview(l)) return false;
        } else if (STATE.filter === 'review') {
            if (!needsReview(l)) return false;
        }
        if (STATE.search) {
            const hay = [
                l.raw, l.species, l.variety, l.grade, l.articulo_name,
                l.articulo_ref, l.articulo_id_erp, l.box_type, l.label
            ].join(' ').toLowerCase();
            if (!hay.includes(STATE.search)) return false;
        }
        return true;
    });
}

// ── Una fila ─────────────────────────────────────────────────────────
function renderLineRow(l, rowNum) {
    const st = computeStatus(l);
    const review = needsReview(l);
    const badge = computeOriginBadge(l);

    // Progress bar de confianza
    let confHtml = '';
    if (l.confidence != null) {
        const pct = Math.round((l.confidence || 0) * 100);
        const cls = pct >= 90 ? 'high' : pct >= 70 ? 'mid' : 'low';
        confHtml = `
            <div class="conf" title="${esc(l.match_method || '')}">
                <div class="conf__bar"><div class="conf__fill conf__fill--${cls}" style="width:${pct}%"></div></div>
                <span class="conf__pct">${pct}%</span>
            </div>`;
    } else {
        confHtml = `<span class="muted">—</span>`;
    }

    // Artículo vinculado
    let artHtml;
    if (l.articulo_id && l.articulo_name) {
        artHtml = `
            <div class="art-cell">
                <div class="art-name" title="${esc(l.articulo_name)}">${esc(l.articulo_name)}</div>
                <div class="art-ref">${esc(l.articulo_id_erp || l.articulo_ref || '#' + l.articulo_id)}</div>
            </div>`;
    } else {
        artHtml = `<span class="art-empty">Sin vincular</span>`;
    }

    // Badge circular OR/EST/STD
    const badgeHtml = badge
        ? `<span class="origin-badge origin-badge--${badge}" title="${badge==='or'?'Original':badge==='est'?'Estimado':'Estándar'}">${badge.toUpperCase()}</span>`
        : '';

    // Chip de estado
    const chipHtml = st === 'ok' && !review
        ? `<span class="chip chip--ok">OK</span>`
        : st === 'sin_match'
        ? `<span class="chip chip--err">Sin match</span>`
        : `<span class="chip chip--warn">Revisar</span>`;

    // Tree-style para mixed box — si es hijo, indentamos
    const isMixed = l.box_type && /mix/i.test(l.box_type);
    const descHtml = `
        <div class="desc-cell">
            ${isMixed ? '<span class="chip chip--info" style="margin-right:6px">MIX</span>' : ''}
            <span class="desc-main">${esc(l.variety || l.raw?.slice(0, 40) || '—')}</span>
            ${l.raw ? `<div class="desc-raw" title="${esc(l.raw)}">${esc(l.raw)}</div>` : ''}
        </div>`;

    // Input id_erp editable + ✓ guardar sinónimo / ✕ eliminar línea
    const erpInput = `
        <div class="erp-actions">
            <input type="text" class="erp-input" data-row-idx="${l.idx}"
                value="${esc(l.articulo_id_erp || '')}" placeholder="id_erp…"
                aria-label="id_erp fila ${rowNum}">
            <button class="icon-btn icon-btn--ok line-save" data-row-idx="${l.idx}" title="Confirmar y guardar">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
            </button>
            <button class="icon-btn icon-btn--err line-delete" data-row-idx="${l.idx}" title="Eliminar línea">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
        </div>`;

    return `
        <tr class="is-clickable" data-row-idx="${l.idx}">
            <td><span class="line-num">${String(rowNum).padStart(2,'0')}</span></td>
            <td>${descHtml}</td>
            <td>${esc(l.species || '—')}${l.grade ? ` <span class="grade-pill">${esc(l.grade)}</span>` : ''}</td>
            <td>${esc(l.variety || '—')}</td>
            <td class="num">${l.size ?? '—'}</td>
            <td class="num">${l.spb ?? '—'}</td>
            <td class="num">
                <input type="number" class="num-input line-stems" data-row-idx="${l.idx}"
                       value="${l.stems ?? ''}" step="1" min="0" inputmode="numeric"
                       aria-label="Tallos fila ${rowNum}">
            </td>
            <td class="num">
                <div class="money-cell">
                    <span class="money-prefix">$</span>
                    <input type="number" class="num-input line-price" data-row-idx="${l.idx}"
                           value="${l.price ?? ''}" step="0.0001" min="0" inputmode="decimal"
                           aria-label="Precio fila ${rowNum}">
                </div>
            </td>
            <td class="num">
                <div class="money-cell">
                    <span class="money-prefix">$</span>
                    <input type="number" class="num-input line-total" data-row-idx="${l.idx}"
                           value="${l.total ?? ''}" step="0.01" min="0" inputmode="decimal"
                           aria-label="Total fila ${rowNum}">
                </div>
            </td>
            <td class="dest-cell">
                <input type="text" class="text-input line-label" data-row-idx="${l.idx}"
                       value="${esc(l.label || '')}" maxlength="64"
                       aria-label="Destino fila ${rowNum}" placeholder="—">
            </td>
            <td>
                <div style="display:flex;align-items:center;gap:8px">
                    ${badgeHtml}
                    ${artHtml}
                </div>
                <div style="margin-top:4px">${erpInput}</div>
            </td>
            <td>
                ${chipHtml}
                <div style="margin-top:4px">${confHtml}</div>
            </td>
        </tr>`;
}

function wireTableEvents() {
    const tbody = $('#linesTable tbody');
    if (!tbody) return;

    tbody.querySelectorAll('tr.is-clickable').forEach(tr => {
        // Track si el mousedown arrancó dentro de un input/botón/enlace.
        // Si sí, el click subsiguiente (que puede caer fuera del input
        // por drag-select) NO debe abrir el drawer.
        let mouseDownInInteractive = false;
        tr.addEventListener('mousedown', e => {
            mouseDownInInteractive = !!e.target.closest('input, button, a, .erp-actions');
        });
        tr.addEventListener('click', e => {
            if (mouseDownInInteractive) { mouseDownInInteractive = false; return; }
            if (e.target.closest('input, button, a, .erp-actions')) return;
            // Si hay texto seleccionado (drag-select), no abrir drawer.
            const sel = window.getSelection && window.getSelection();
            if (sel && !sel.isCollapsed && sel.toString().length > 0) return;
            const idx = Number(tr.dataset.rowIdx);
            openDrawer(idx);
        });
    });
    tbody.querySelectorAll('.erp-input').forEach(inp => {
        // Guarda en cada blur/Enter si el valor cambió respecto al que
        // ya tiene la línea. Usar saveLineArticle persiste (confirm /
        // correct / save_synonym según el estado previo) y patchea
        // batch_status. Previene que el operador teclee y refresque
        // pensando que basta con el blur.
        inp.__lastSavedVal = (inp.value || '').trim();

        const persistFromInput = async () => {
            const idx  = Number(inp.dataset.rowIdx);
            const line = STATE.lines[idx];
            if (!line) return;
            const val = (inp.value || '').trim();
            if (val === inp.__lastSavedVal) return;
            // Vacío: limpia vínculo localmente. No persistimos "borrado"
            // porque no hay endpoint para desvincular un sinónimo desde
            // la UI de línea; se hace con la ✕.
            if (!val) {
                line.articulo_id_erp = '';
                line.articulo_id     = 0;
                line.articulo_name   = '';
                inp.__lastSavedVal   = '';
                renderResult();
                return;
            }
            inp.__lastSavedVal = val;
            const ok = await saveLineArticle(line, val, (line._providerId || STATE.provider_id || 0), inp);
            if (!ok) {
                inp.style.borderColor = 'var(--err)';
                setTimeout(() => inp.style.borderColor = '', 1200);
            }
        };
        inp.addEventListener('change', persistFromInput);
        inp.addEventListener('keydown', e => {
            if (e.key === 'Enter') {
                e.preventDefault();
                inp.blur();   // dispara change
            }
        });
        // Auto-save 800ms tras la última pulsación — para que escribir
        // un id_erp y olvidarse de Enter/blur no descarte la corrección.
        let _typingTimer = null;
        inp.addEventListener('input', () => {
            if (_typingTimer) clearTimeout(_typingTimer);
            _typingTimer = setTimeout(() => {
                if ((inp.value || '').trim() !== inp.__lastSavedVal) {
                    persistFromInput();
                }
            }, 800);
        });
    });

    // ✓ Guardar sinónimo (tick verde)
    tbody.querySelectorAll('.line-save').forEach(btn => {
        btn.addEventListener('click', async e => {
            e.stopPropagation();
            const idx = Number(btn.dataset.rowIdx);
            const line = STATE.lines[idx];
            if (!line) return;
            const input = btn.closest('tr').querySelector('.erp-input');
            let val = (input?.value || '').trim();
            // Si el operador pulsa ✓ sin escribir nada pero la línea ya
            // tiene un artículo matcheado, confirmamos ese match (el
            // helper detectará old_id_erp == new_id_erp → confirm_match).
            if (!val) {
                if (line.articulo_id_erp) {
                    val = String(line.articulo_id_erp);
                } else {
                    alert('Introduce un id_erp o referencia');
                    return;
                }
            }
            await saveLineArticle(line, val, (line._providerId || STATE.provider_id || 0), btn);
        });
    });

    // ✕ Eliminar línea (marcado local, re-render)
    tbody.querySelectorAll('.line-delete').forEach(btn => {
        btn.addEventListener('click', e => {
            e.stopPropagation();
            const idx = Number(btn.dataset.rowIdx);
            const line = STATE.lines[idx];
            if (!line) return;
            if (!confirm(`¿Eliminar la línea "${line.variety || line.raw?.slice(0, 30) || ''}"?`)) return;
            line._deleted = true;
            STATE.lines = STATE.lines.filter(l => !l._deleted);
            renderResult();
        });
    });

    // Editables: tallos / precio / total. Persisten contra
    // batch_status si la línea viene de un lote, y siempre actualizan
    // el modelo en memoria para que la generación de orden use los
    // valores corregidos por el operador.
    _wireNumericLineEditor(tbody, '.line-stems', 'stems');
    _wireNumericLineEditor(tbody, '.line-price', 'price');
    _wireNumericLineEditor(tbody, '.line-total', 'total');
    _wireTextLineEditor(tbody, '.line-label', 'label');
}

function _wireNumericLineEditor(scope, selector, fieldKey) {
    scope.querySelectorAll(selector).forEach(inp => {
        inp.__lastVal = inp.value;
        const persist = async () => {
            const idx  = Number(inp.dataset.rowIdx);
            const line = STATE.lines[idx];
            if (!line) return;
            if (inp.value === inp.__lastVal) return;
            inp.__lastVal = inp.value;
            const num = inp.value === '' ? null : Number(inp.value);
            if (num !== null && !isFinite(num)) {
                inp.style.borderColor = 'var(--err)';
                setTimeout(() => inp.style.borderColor = '', 1200);
                return;
            }
            line[fieldKey] = num;
            // Mantener sincronizados los aliases que usa el backend /
            // generación de orden.
            if (fieldKey === 'price')  { line.price_per_stem = num; }
            if (fieldKey === 'total')  { line.line_total     = num; line.total_line = num; }
            if (fieldKey === 'stems')  { line.stems          = num; }

            // Si cambia precio o tallos, recalcular total = precio × tallos
            // (a menos que el operador haya editado total directamente —
            // ese carril se respeta porque pasa por fieldKey='total').
            // El total de cabecera se actualiza vía renderHeader() al final.
            if (fieldKey === 'price' || fieldKey === 'stems') {
                const stemsN = Number(line.stems || 0);
                const priceN = Number(line.price ?? line.price_per_stem ?? 0);
                if (stemsN > 0 && priceN >= 0) {
                    const newTotal = +(stemsN * priceN).toFixed(2);
                    line.total      = newTotal;
                    line.line_total = newTotal;
                    line.total_line = newTotal;
                    // Reflejar en el input de total de la misma fila
                    const tr = inp.closest('tr');
                    const totalInp = tr && tr.querySelector('.line-total');
                    if (totalInp) {
                        totalInp.value = newTotal;
                        totalInp.__lastVal = String(newTotal);
                    }
                }
            }
            // Refrescar el "Total factura" del header tras cualquier
            // cambio numérico que afecte la suma.
            if (typeof renderHeader === 'function') {
                try { renderHeader(); } catch (e) {}
            }

            // Persistir si la línea proviene de un batch. Sin batch
            // (procesar factura), el cambio queda en memoria y se
            // refleja al generar la hoja de orden.
            let batchId = null;
            try { batchId = localStorage.getItem('verafact.lastBatchId'); } catch (e) {}
            if (batchId && line._batchInvoiceIdx !== undefined && line._batchLineIdx !== undefined) {
                try {
                    await apiPost('update_line_fields', {
                        batch_id:    batchId,
                        invoice_idx: line._batchInvoiceIdx,
                        line_idx:    line._batchLineIdx,
                        fields: {
                            stems:        line.stems,
                            price:        line.price,
                            line_total:   line.line_total,
                            total_line:   line.line_total,
                            total:        line.line_total,
                            price_per_stem: line.price,
                        },
                    });
                    if (window.VeraFact && typeof window.VeraFact.refreshBatchAfterLineChange === 'function') {
                        window.VeraFact.refreshBatchAfterLineChange(line);
                    }
                } catch (err) {
                    inp.style.borderColor = 'var(--err)';
                    setTimeout(() => inp.style.borderColor = '', 1200);
                }
            }
        };
        inp.addEventListener('change', persist);
        inp.addEventListener('keydown', e => {
            if (e.key === 'Enter') { e.preventDefault(); inp.blur(); }
        });
        // El click en el input no debe abrir el drawer.
        inp.addEventListener('click', e => e.stopPropagation());
    });
}

// Editor de texto para campos como `label` (destino/box-id). Mismo
// patrón que _wireNumericLineEditor pero sin coerción a número:
// trim + uppercase para mantener el formato del catálogo (MARL,
// ASTURIAS, R15...). Persiste a batch_status si la línea proviene de
// un batch.
function _wireTextLineEditor(scope, selector, fieldKey) {
    scope.querySelectorAll(selector).forEach(inp => {
        inp.__lastVal = inp.value;
        const persist = async () => {
            const idx  = Number(inp.dataset.rowIdx);
            const line = STATE.lines[idx];
            if (!line) return;
            const cleaned = (inp.value || '').trim().toUpperCase().slice(0, 64);
            if (inp.value !== cleaned) inp.value = cleaned;
            if (cleaned === inp.__lastVal) return;
            inp.__lastVal = cleaned;
            line[fieldKey] = cleaned;

            let batchId = null;
            try { batchId = localStorage.getItem('verafact.lastBatchId'); } catch (e) {}
            if (batchId && line._batchInvoiceIdx !== undefined && line._batchLineIdx !== undefined) {
                try {
                    await apiPost('update_line_fields', {
                        batch_id:    batchId,
                        invoice_idx: line._batchInvoiceIdx,
                        line_idx:    line._batchLineIdx,
                        fields: { [fieldKey]: cleaned },
                    });
                    if (window.VeraFact && typeof window.VeraFact.refreshBatchAfterLineChange === 'function') {
                        window.VeraFact.refreshBatchAfterLineChange(line);
                    }
                } catch (err) {
                    inp.style.borderColor = 'var(--err)';
                    setTimeout(() => inp.style.borderColor = '', 1200);
                }
            }
        };
        inp.addEventListener('change', persist);
        inp.addEventListener('keydown', e => {
            if (e.key === 'Enter') { e.preventDefault(); inp.blur(); }
        });
        inp.addEventListener('click', e => e.stopPropagation());
    });
}

// Helper común usado por app.js y app.extras.js. Resuelve el id_erp
// introducido por el operador, elige el action correcto (confirm /
// correct / save) según el estado previo de la línea, y actualiza la
// línea in-place. btnForFeedback es opcional — si se pasa, se pinta
// un flash verde al éxito.
async function saveLineArticle(line, userQuery, providerId, btnForFeedback) {
    const oldArtId    = line.articulo_id || 0;
    const oldArtIdErp = line.articulo_id_erp || '';
    try {
        const r = await apiGet('lookup_article', { q: userQuery });
        const art = r && r.ok && (r.articulo || r);
        if (!r || !r.ok || !(art && (art.id || art.articulo_id || art.nombre))) {
            alert(r?.error || 'Artículo no encontrado');
            return false;
        }
        const newArtId    = art.id || art.articulo_id || 0;
        const newArtIdErp = art.id_erp || userQuery;
        const name        = art.nombre || art.name || '';
        const synKey      = `${providerId}|${line.species || ''}|${_normalizeVariety(line.variety)}|${line.size || 0}|${line.spb || line.stems_per_bunch || 0}|${(line.grade || '').toUpperCase()}`;

        let action, body;
        if (oldArtIdErp && oldArtIdErp === newArtIdErp) {
            action = 'confirm_match';
            body = { key: synKey, articulo_id: newArtId, articulo_id_erp: newArtIdErp };
        } else if (oldArtId > 0) {
            action = 'correct_match';
            body = {
                key: synKey, provider_id: providerId,
                species: line.species || '', variety: line.variety || '',
                size: line.size || 0,
                stems_per_bunch: line.spb || line.stems_per_bunch || 0,
                grade: line.grade || '',
                old_articulo_id: oldArtId,
                new_articulo_id: newArtId,
                new_articulo_id_erp: newArtIdErp,
                new_articulo_name: name,
            };
        } else {
            action = 'save_synonym';
            body = {
                key: synKey, provider_id: providerId,
                species: line.species || '', variety: line.variety || '',
                size: line.size || 0,
                stems_per_bunch: line.spb || line.stems_per_bunch || 0,
                grade: line.grade || '',
                articulo_id: newArtId,
                articulo_id_erp: newArtIdErp,
                articulo_name: name,
            };
        }

        // Contexto del batch (si la línea proviene de una factura batch):
        // el backend patchea batch_status/{id}.json para que al refrescar
        // la página se recupere el estado corregido, no el original del
        // pipeline Python.
        let batchId = null;
        try { batchId = localStorage.getItem('verafact.lastBatchId'); } catch (e) {}
        if (batchId && line._batchInvoiceIdx !== undefined && line._batchLineIdx !== undefined) {
            body.batch_id     = batchId;
            body.invoice_idx  = line._batchInvoiceIdx;
            body.line_idx     = line._batchLineIdx;
        }

        const resp = await apiPost(action, body);
        if (resp && resp.ok) {
            line.articulo_id       = newArtId;
            line.articulo_id_erp   = newArtIdErp;
            line.articulo_name     = name;
            line.match_status      = 'ok';
            line.match_method      = action === 'confirm_match' ? 'sinónimo' : 'manual-web';
            line.match_confidence  = 1.0;
            line.confidence        = 1.0;
            line.link_confidence   = 1.0;
            line.origin            = 'OR';
            line.review_lane       = 'auto';
            line.validation_errors = [];
            if (btnForFeedback) {
                const orig = btnForFeedback.innerHTML;
                btnForFeedback.style.color = 'var(--ok)';
                setTimeout(() => { btnForFeedback.style.color = ''; renderResult(); }, 500);
            } else {
                renderResult();
            }
            return true;
        }
        alert('Error: ' + (resp?.error || 'desconocido'));
        return false;
    } catch (err) {
        alert('Error de conexión: ' + err.message);
        return false;
    }
}

function _normalizeVariety(v) {
    return String(v ?? '').toUpperCase().replace(/[^A-Z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim();
}

// ══════════════════════════════════════════════════════════════════════
// DRAWER v2 — 3 secciones + 3 acciones
// ══════════════════════════════════════════════════════════════════════
let _drawerLine = null;

function ensureDrawerDom() {
    if ($('#drawerBackdrop')) return;
    const html = `
        <div id="drawerBackdrop" class="drawer-backdrop"></div>
        <aside id="drawer" class="drawer" role="dialog" aria-hidden="true">
            <div class="drawer__head">
                <div class="drawer__head-num" id="drawerNum">—</div>
                <div class="drawer__head-title">
                    <h2 id="drawerTitle">Línea</h2>
                    <p id="drawerSub"></p>
                </div>
                <button class="drawer__close" id="drawerClose" aria-label="Cerrar">
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
            </div>
            <div class="drawer__body" id="drawerBody"></div>
            <div class="drawer__actions" id="drawerActions"></div>
        </aside>`;
    document.body.insertAdjacentHTML('beforeend', html);
    $('#drawerBackdrop').addEventListener('click', closeDrawer);
    $('#drawerClose').addEventListener('click', closeDrawer);
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') closeDrawer();
    });
}

function openDrawer(rowIdx) {
    ensureDrawerDom();
    const line = STATE.lines[rowIdx];
    if (!line) return;
    _drawerLine = line;

    $('#drawerNum').textContent = String(rowIdx + 1).padStart(2, '0');
    $('#drawerTitle').textContent = line.variety || line.raw?.slice(0, 50) || 'Línea';
    $('#drawerSub').textContent   = [line.species, line.size && line.size + 'cm', line.spb && line.spb + 'SPB']
                                     .filter(Boolean).join(' · ');

    $('#drawerBody').innerHTML = renderDrawerBody(line);
    $('#drawerActions').innerHTML = renderDrawerActions(line);
    wireDrawerEvents(line);

    $('#drawer').classList.add('is-open');
    $('#drawerBackdrop').classList.add('is-open');
    $('#drawer').setAttribute('aria-hidden', 'false');

    // Cargar candidatos y timeline async
    loadCandidatesInDrawer(line);
    loadPriceTimelineInDrawer(line);
}

function closeDrawer() {
    $('#drawer')?.classList.remove('is-open');
    $('#drawerBackdrop')?.classList.remove('is-open');
    $('#drawer')?.setAttribute('aria-hidden', 'true');
    _drawerLine = null;
}

function renderDrawerBody(line) {
    const st = computeStatus(line);
    const review = needsReview(line);
    return `
        <!-- Sección 1: Datos factura -->
        <div class="drawer-section">
            <div class="drawer-section__head">
                <h3>Datos de la factura</h3>
            </div>
            <dl class="data-grid">
                <dt>Especie</dt><dd>${esc(line.species || '—')}</dd>
                <dt>Variedad</dt><dd>${esc(line.variety || '—')}</dd>
                <dt>Talla</dt><dd>${line.size ?? '—'}</dd>
                <dt>SPB</dt><dd>${line.spb ?? '—'}</dd>
                <dt>Tallos</dt><dd>${fmtInt(line.stems)}</dd>
                <dt>Grado</dt><dd>${esc(line.grade || '—')}</dd>
                <dt>Precio/tallo</dt><dd>${fmtPrice(line.price)}</dd>
                <dt>Total</dt><dd><strong>${fmt$(line.total)}</strong></dd>
                ${line.box_type ? `<dt>Caja</dt><dd>${esc(line.box_type)}${line.label ? ' · ' + esc(line.label) : ''}</dd>` : ''}
                ${line.raw ? `<dt style="grid-column:1/-1">Descripción original</dt>
                              <dd class="mono" style="grid-column:1/-1;font-size:12px;color:var(--ink-muted)">${esc(line.raw)}</dd>` : ''}
            </dl>
        </div>

        <!-- Sección 2: Artículo vinculado -->
        <div class="drawer-section">
            <div class="drawer-section__head">
                <h3>Artículo vinculado</h3>
                ${line.match_method ? `<span class="drawer-section__badge">${esc(line.match_method)}</span>` : ''}
            </div>
            ${line.articulo_id && line.articulo_name ? `
                <div class="linked-article">
                    <div class="linked-article__icon">
                        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                    </div>
                    <div class="linked-article__body">
                        <div class="linked-article__name">${esc(line.articulo_name)}</div>
                        <div class="linked-article__ref">${esc(line.articulo_id_erp || line.articulo_ref || '#' + line.articulo_id)}</div>
                    </div>
                </div>
                ${line.confidence != null ? `<div style="margin-top:10px;display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--ink-muted)">
                    <span>Confianza:</span>
                    <div class="conf" style="flex:1;max-width:200px">
                        <div class="conf__bar"><div class="conf__fill conf__fill--${Math.round(line.confidence*100) >= 90 ? 'high' : Math.round(line.confidence*100) >= 70 ? 'mid' : 'low'}" style="width:${Math.round(line.confidence*100)}%"></div></div>
                        <span class="conf__pct">${Math.round(line.confidence*100)}%</span>
                    </div>
                </div>` : ''}
            ` : `
                <div class="linked-article__empty">Esta línea no tiene artículo vinculado aún.</div>
            `}
        </div>

        <!-- Sección 3a: Buscar artículo en el catálogo -->
        <div class="drawer-section" id="searchSection">
            <div class="drawer-section__head">
                <h3>Buscar en catálogo</h3>
                <span class="drawer-section__badge" id="searchBadge">—</span>
            </div>
            <div class="article-search">
                <input type="text" id="articleSearchInput"
                       class="article-search__input"
                       placeholder="Nombre, id_erp o referencia…"
                       autocomplete="off" spellcheck="false">
                <div class="article-search__results" id="articleSearchResults"></div>
            </div>
        </div>

        <!-- Sección 3b: Candidatos sugeridos -->
        <div class="drawer-section" id="candidatesSection">
            <div class="drawer-section__head">
                <h3>Candidatos sugeridos</h3>
                <span class="drawer-section__badge" id="candidatesBadge">cargando…</span>
            </div>
            <div class="candidates-list" id="candidatesList">
                <div class="drawer-empty">Buscando candidatos…</div>
            </div>
        </div>

        <!-- Sección extra: Histórico de precios -->
        <div class="drawer-section" id="priceSection">
            <div class="drawer-section__head">
                <h3>Histórico de precio (90d)</h3>
                <span class="drawer-section__badge" id="priceBadge">—</span>
            </div>
            <div id="priceTimelineWrap">
                <div class="drawer-empty">Sin datos todavía</div>
            </div>
        </div>
    `;
}

function renderDrawerActions(line) {
    return `
        <button class="btn btn-secondary" id="drawerActIgnore">Ignorar línea</button>
        <button class="btn btn-secondary" id="drawerActSave">Guardar sin match</button>
        <button class="btn btn-primary" id="drawerActConfirm">Confirmar y guardar sinónimo</button>
    `;
}

function wireDrawerEvents(line) {
    // Buscador de artículos en el catálogo.
    wireArticleSearch(line);

    $('#drawerActIgnore')?.addEventListener('click', async () => {
        line.match_status = 'ignored';
        closeDrawer();
        renderResult();
    });
    $('#drawerActSave')?.addEventListener('click', async () => {
        try {
            if (line.articulo_id) {
                await apiPost('confirm_match', { idx: line.idx, articulo_id: line.articulo_id });
            }
        } catch (e) { /* silencioso */ }
        closeDrawer();
        renderResult();
    });
    $('#drawerActConfirm')?.addEventListener('click', async () => {
        if (!line.articulo_id && !line.articulo_id_erp) {
            alert('Primero vincula un artículo (usa un candidato o escribe el id_erp)');
            return;
        }
        try {
            await apiPost('save_synonym', {
                id_proveedor:      STATE.provider_id,
                nombre_factura:    line.variety || line.raw,
                especie:           line.species,
                talla:             line.size,
                spb:               line.spb,
                id_articulo:       line.articulo_id || null,
                id_articulo_erp:   line.articulo_id_erp || null,
            });
            line.match_method = 'manual';
            line.origin = 'OR';
        } catch (e) {
            alert('Error guardando sinónimo: ' + e.message);
            return;
        }
        closeDrawer();
        renderResult();
    });
}

// ══════════════════════════════════════════════════════════════════════
// Buscador de artículos (drawer) — debounced, pega contra search_articulos
// ══════════════════════════════════════════════════════════════════════
let _searchDebounce = null;
function wireArticleSearch(line) {
    const input   = $('#articleSearchInput');
    const results = $('#articleSearchResults');
    const badge   = $('#searchBadge');
    if (!input || !results) return;
    input.focus();

    const doSearch = async (q) => {
        q = q.trim();
        if (q.length < 2) {
            results.innerHTML = '';
            if (badge) badge.textContent = '—';
            return;
        }
        if (badge) badge.textContent = '…';
        try {
            const r = await apiGet('search_articulos', { q, limit: 500 });
            if (!r.ok) {
                results.innerHTML = `<div class="drawer-empty">${esc(r.error || 'Error')}</div>`;
                if (badge) badge.textContent = 'err';
                return;
            }
            const list = r.results || [];
            if (!list.length) {
                results.innerHTML = `<div class="drawer-empty">Sin coincidencias</div>`;
                if (badge) badge.textContent = '0';
                return;
            }
            if (badge) badge.textContent = list.length;
            results.innerHTML = list.map(a => {
                const meta = [
                    a.tamano ? a.tamano + 'cm' : null,
                    a.paquete ? a.paquete + 'U' : null,
                    a.marca || null,
                    a.familia || null,
                ].filter(Boolean).join(' · ');
                const code = a.id_erp || a.referencia || ('#' + a.id);
                return `
                    <div class="search-result" data-id="${a.id}" data-erp="${esc(a.id_erp || '')}"
                         data-ref="${esc(a.referencia || '')}" data-name="${esc(a.nombre)}">
                        <div class="search-result__main">
                            <div class="search-result__name" title="${esc(a.nombre)}">${esc(a.nombre)}</div>
                            <div class="search-result__meta">
                                <span class="mono">${esc(code)}</span>
                                ${a.referencia && a.referencia !== code ? `<span class="mono">${esc(a.referencia)}</span>` : ''}
                                ${meta ? `<span>${esc(meta)}</span>` : ''}
                            </div>
                        </div>
                        <button class="search-result__use" title="Asignar este artículo">
                            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                        </button>
                    </div>`;
            }).join('');

            results.querySelectorAll('.search-result').forEach(el => {
                el.addEventListener('click', async () => {
                    const idErp = el.dataset.erp;
                    const ref   = el.dataset.ref;
                    const query = idErp || ref || el.dataset.id;
                    if (!query) return;
                    // Persistir vía saveLineArticle: decide confirm/correct/save
                    // y patchea batch_status si corresponde.
                    const providerId = (line._providerId || STATE.provider_id || 0);
                    const ok = await saveLineArticle(line, query, providerId, el);
                    if (ok) {
                        // Refrescar secciones del drawer con la nueva info.
                        $('#drawerBody').innerHTML = renderDrawerBody(line);
                        wireDrawerEvents(line);
                        loadCandidatesInDrawer(line);
                        loadPriceTimelineInDrawer(line);
                        // Si la línea viene de un batch, refrescar también la
                        // tabla del lote (pill Parcial/OK, contadores).
                        if (window.VeraFact && typeof window.VeraFact.refreshBatchAfterLineChange === 'function') {
                            window.VeraFact.refreshBatchAfterLineChange(line);
                        }
                    }
                });
            });
        } catch (e) {
            results.innerHTML = `<div class="drawer-empty">Error de red</div>`;
            if (badge) badge.textContent = 'err';
        }
    };

    input.addEventListener('input', () => {
        clearTimeout(_searchDebounce);
        const q = input.value;
        _searchDebounce = setTimeout(() => doSearch(q), 220);
    });
    input.addEventListener('keydown', e => {
        if (e.key === 'Enter') {
            clearTimeout(_searchDebounce);
            doSearch(input.value);
        }
    });
}

async function loadCandidatesInDrawer(line) {
    const list = $('#candidatesList');
    const badge = $('#candidatesBadge');
    if (!list) return;
    try {
        const r = await apiGet('suggest_candidates', {
            species: line.species || '',
            variety: line.variety || '',
            size:    line.size || 0,
            spb:     line.spb || 0,
            provider_id: (line._providerId || STATE.provider_id || 0),
            limit:   5
        });
        if (!r.ok) {
            list.innerHTML = `<div class="drawer-empty">Endpoint no disponible</div>`;
            badge && (badge.textContent = 'error');
            return;
        }
        const cands = r.candidates || [];
        if (!cands.length) {
            list.innerHTML = `<div class="drawer-empty">Sin candidatos sugeridos</div>`;
            badge && (badge.textContent = '0');
            return;
        }
        badge && (badge.textContent = cands.length);
        list.innerHTML = cands.map(c => `
            <div class="candidate">
                <div class="candidate__body">
                    <div class="candidate__name" title="${esc(c.nombre)}">${esc(c.nombre)}</div>
                    <div class="candidate__meta">
                        <span class="mono">${esc(c.articulo_id_erp || c.referencia || '#' + c.articulo_id)}</span>
                        ${c.familia ? `<span>${esc(c.familia)}</span>` : ''}
                        ${c.tamano ? `<span>${esc(c.tamano)}cm</span>` : ''}
                        ${c.paquete ? `<span>${c.paquete} SPB</span>` : ''}
                    </div>
                </div>
                <div class="candidate__score">
                    <div class="candidate__score-val">${c.score}%</div>
                    <div class="candidate__score-bar"><span style="width:${Math.min(c.score, 100)}%"></span></div>
                </div>
                <button class="candidate__use" data-cand-id="${c.articulo_id}" data-cand-erp="${esc(c.articulo_id_erp || '')}" data-cand-name="${esc(c.nombre)}" data-cand-ref="${esc(c.referencia || '')}">Usar →</button>
            </div>
        `).join('');
        list.querySelectorAll('.candidate__use').forEach(btn => {
            btn.addEventListener('click', async () => {
                const erp = btn.dataset.candErp || '';
                const ref = btn.dataset.candRef || '';
                const id  = btn.dataset.candId  || '';
                // Persistir vía id_erp/ref (política 10q/10r). Si no
                // tenemos ninguno de los dos, usamos el id local como
                // último recurso — lookup_article lo rechazará y se
                // verá el error arriba.
                const query = erp || ref || id;
                if (!query) return;
                const providerId = (line._providerId || STATE.provider_id || 0);
                const ok = await saveLineArticle(line, query, providerId, btn);
                if (ok) {
                    $('#drawerBody').innerHTML = renderDrawerBody(line);
                    wireDrawerEvents(line);
                    loadCandidatesInDrawer(line);
                    loadPriceTimelineInDrawer(line);
                    if (window.VeraFact && typeof window.VeraFact.refreshBatchAfterLineChange === 'function') {
                        window.VeraFact.refreshBatchAfterLineChange(line);
                    }
                }
            });
        });
    } catch (e) {
        list.innerHTML = `<div class="drawer-empty">Error de red</div>`;
        badge && (badge.textContent = 'error');
    }
}

async function loadPriceTimelineInDrawer(line) {
    const wrap = $('#priceTimelineWrap');
    const badge = $('#priceBadge');
    if (!wrap || !line.articulo_id) {
        if (wrap) wrap.innerHTML = `<div class="drawer-empty">Vincula un artículo para ver histórico</div>`;
        if (badge) badge.textContent = '—';
        return;
    }
    try {
        const r = await apiGet('price_anomalies_timeline', { articulo_id: line.articulo_id, days: 90 });
        if (!r.ok || !r.timeline || !r.timeline.length) {
            wrap.innerHTML = `<div class="drawer-empty">Sin precios históricos</div>`;
            badge.textContent = '0';
            return;
        }
        const tl = r.timeline;
        const anomalies = tl.filter(p => p.anomaly).length;
        badge.textContent = `${tl.length} pts`;

        // Mini svg sparkline
        const W = 560, H = 56;
        const prices = tl.map(p => p.price);
        const min = Math.min(...prices), max = Math.max(...prices);
        const range = (max - min) || 1;
        const pts = tl.map((p, i) => {
            const x = (i / Math.max(1, tl.length - 1)) * (W - 8) + 4;
            const y = H - 6 - ((p.price - min) / range) * (H - 14);
            return { x, y, p };
        });
        const path = pts.map((pt, i) => (i === 0 ? 'M' : 'L') + pt.x.toFixed(1) + ',' + pt.y.toFixed(1)).join(' ');
        const dots = pts.map(pt => `<circle cx="${pt.x.toFixed(1)}" cy="${pt.y.toFixed(1)}" r="${pt.p.anomaly ? 3.5 : 2}" fill="${pt.p.anomaly ? 'var(--err)' : 'var(--brand)'}"><title>${pt.p.date}: $${pt.p.price.toFixed(4)}${pt.p.anomaly ? ' (anomalía z=' + pt.p.z + ')' : ''}</title></circle>`).join('');

        wrap.innerHTML = `
            <div class="price-timeline">
                <div class="price-timeline__chart">
                    <svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" preserveAspectRatio="none">
                        <path d="${path}" fill="none" stroke="var(--brand)" stroke-width="1.6"/>
                        ${dots}
                    </svg>
                </div>
                <div class="price-timeline__stats">
                    <span>min ${fmtPrice(min)} · max ${fmtPrice(max)} · media ${fmtPrice(r.stats?.mean)}</span>
                    ${anomalies > 0 ? `<span class="anomaly-count">${anomalies} anomalía${anomalies===1?'':'s'}</span>` : '<span>sin anomalías</span>'}
                </div>
            </div>
        `;
    } catch (e) {
        wrap.innerHTML = `<div class="drawer-empty">Endpoint no disponible</div>`;
        badge.textContent = 'error';
    }
}

// ══════════════════════════════════════════════════════════════════════
// Generar hoja de orden
// ══════════════════════════════════════════════════════════════════════
async function generarOrden() {
    const msg = $('#ordenMsg');
    msg.textContent = 'Generando...'; msg.className = 'page-actions__msg';
    try {
        const r = await apiPost('generar_orden', {
            invoice_key: STATE.invoice_key,
            provider_id: STATE.provider_id,
            lines: STATE.lines.map(l => ({
                idx: l.idx, articulo_id: l.articulo_id, articulo_id_erp: l.articulo_id_erp,
                stems: l.stems, price: l.price,
                line_total: l.total ?? l.line_total,
                total: l.total ?? l.line_total,
                box_type: l.box_type,
            })),
        });
        if (r.ok) {
            msg.textContent = '✓ Hoja de orden generada' + (r.id ? ' (ID ' + r.id + ')' : '');
            msg.className = 'page-actions__msg is-ok';
        } else {
            msg.textContent = 'Error: ' + (r.error || 'desconocido');
            msg.className = 'page-actions__msg is-err';
        }
    } catch (e) {
        msg.textContent = 'Error de red: ' + e.message;
        msg.className = 'page-actions__msg is-err';
    }
}

// ══════════════════════════════════════════════════════════════════════
// HISTORIAL
// ══════════════════════════════════════════════════════════════════════
async function loadHistory() {
    const tbody = $('#historyTable tbody');
    if (!tbody) return;
    $('#historyLoading')?.classList.remove('hidden');
    try {
        const r = await apiGet('history');
        const rows = r.invoices || r.historial || r.history || [];
        $('#historyLoading')?.classList.add('hidden');
        if (!rows.length) {
            tbody.innerHTML = `<tr><td colspan="8" style="padding:24px;text-align:center;color:var(--ink-muted)">Sin facturas procesadas</td></tr>`;
            return;
        }
        tbody.innerHTML = rows.map(h => `
            <tr>
                <td>${esc((h.fecha || h.fecha_proceso || '').slice(0, 10))}</td>
                <td class="mono">${esc(h.invoice_key || h.numero_factura || '—')}</td>
                <td>${esc(h.provider || h.proveedor || '—')}</td>
                <td><span class="muted">${esc(h.pdf || h.pdf_nombre || '')}</span></td>
                <td class="num">${fmtInt(h.lineas)}</td>
                <td class="num"><span class="chip chip--ok">${fmtInt(h.ok || h.ok_count)}</span></td>
                <td class="num">${h.sin_match > 0 ? `<span class="chip chip--err">${h.sin_match}</span>` : '—'}</td>
                <td class="num">${fmt$(h.total_usd)}</td>
            </tr>
        `).join('');
    } catch (e) {
        $('#historyLoading')?.classList.add('hidden');
        tbody.innerHTML = `<tr><td colspan="9" style="padding:24px;text-align:center;color:var(--err)">Error: ${esc(e.message)}</td></tr>`;
    }
}

// ══════════════════════════════════════════════════════════════════════
// SINÓNIMOS (simplified — delega a api.extras.js si existe)
// ══════════════════════════════════════════════════════════════════════
let _synCache = null;
async function loadSynonyms() {
    if (window.__synLoaderExtras) return window.__synLoaderExtras();   // hook app.extras.js
    const tbody = $('#synTable tbody');
    if (!tbody) return;
    $('#synLoading')?.classList.remove('hidden');
    try {
        const r = await apiGet('get_synonyms');
        $('#synLoading')?.classList.add('hidden');
        const syns = r.synonyms || r.sinonimos || [];
        _synCache = syns;
        renderSynonyms(syns);
    } catch (e) {
        $('#synLoading')?.classList.add('hidden');
        tbody.innerHTML = `<tr><td colspan="7" style="padding:20px;color:var(--err)">Error: ${esc(e.message)}</td></tr>`;
    }
}

function renderSynonyms(syns) {
    const tbody = $('#synTable tbody');
    if (!tbody) return;
    const f = ($('#synFilter')?.value || '').toLowerCase();
    const fo = $('#synOriginFilter')?.value || '';
    const fs = $('#synSpeciesFilter')?.value || '';
    const filtered = syns.filter(s => {
        if (f && !JSON.stringify(s).toLowerCase().includes(f)) return false;
        if (fo && (s.origen || s.origin) !== fo) return false;
        if (fs && (s.species || s.especie) !== fs) return false;
        return true;
    });
    $('#synCount').textContent = `${filtered.length} / ${syns.length}`;
    tbody.innerHTML = filtered.slice(0, 500).map(s => `
        <tr>
            <td>${esc(providerName(s.provider_id || s.id_proveedor))}</td>
            <td>${esc(s.variety || s.variedad || '—')}</td>
            <td>${esc(s.species || s.especie || '—')}</td>
            <td class="num">${s.size ?? s.talla ?? '—'}</td>
            <td>${esc(s.articulo_name || s.nombre_articulo || '—')}</td>
            <td><span class="chip chip--neutral">${esc(s.origen || s.origin || '—')}</span></td>
            <td class="mono"><span class="muted">${esc(s.invoice || s.factura || '')}</span></td>
        </tr>
    `).join('');
    // KPIs
    $('#synKpiTotal').textContent = syns.length;
    $('#synKpiRevisado').textContent = syns.filter(s => /manual|revisado/.test(s.origen||s.origin||'')).length;
    $('#synKpiAutoFuzzy').textContent = syns.filter(s => /auto-fuzzy/.test(s.origen||s.origin||'')).length;
    $('#synKpiProviders').textContent = new Set(syns.map(s => s.provider_id || s.id_proveedor)).size;
}

function initSynonymsFilters() {
    ['#synFilter', '#synOriginFilter', '#synSpeciesFilter'].forEach(sel => {
        $(sel)?.addEventListener('input', () => _synCache && renderSynonyms(_synCache));
    });
    $('#synClearFilters')?.addEventListener('click', () => {
        ['#synFilter','#synOriginFilter','#synSpeciesFilter'].forEach(s => { const el=$(s); if(el) el.value=''; });
        if (_synCache) renderSynonyms(_synCache);
    });
}

// ══════════════════════════════════════════════════════════════════════
// APRENDIZAJE
// ══════════════════════════════════════════════════════════════════════
async function loadLearned() {
    try {
        const r = await apiGet('learned');
        const parsers = r.parsers || [];
        const pending = r.pending || [];
        $('#learnedTable tbody').innerHTML = parsers.map(p => `
            <tr>
                <td>${esc(p.name || p.nombre)}</td>
                <td>${esc(p.species || '—')}</td>
                <td class="num">${p.score ?? '—'}</td>
                <td><span class="chip chip--${p.active ? 'ok' : 'neutral'}">${p.active ? 'Activo' : 'Inactivo'}</span></td>
                <td><span class="muted">${esc(p.created || p.fecha || '')}</span></td>
                <td class="num">${p.pdfs ?? '—'}</td>
                <td class="muted">${esc((p.keywords || []).join(', ')).slice(0, 60)}</td>
                <td>${p.active ? '✓' : '—'}</td>
                <td><button class="btn btn-ghost btn-sm">Editar</button></td>
            </tr>
        `).join('') || `<tr><td colspan="9" style="padding:20px;color:var(--ink-muted)">Sin parsers</td></tr>`;
        $('#pendingTable tbody').innerHTML = pending.map(p => `
            <tr>
                <td>${esc(p.provider || providerName(p.provider_id))}</td>
                <td class="num">${p.score ?? '—'}</td>
                <td>${esc(p.reason || p.razon || '—')}</td>
                <td class="num">${p.pdfs ?? '—'}</td>
                <td class="muted">${esc(p.date || p.fecha || '')}</td>
                <td><span class="chip chip--warn">${esc(p.action || 'Revisar')}</span></td>
            </tr>
        `).join('') || `<tr><td colspan="6" style="padding:20px;color:var(--ink-muted)">Sin pendientes</td></tr>`;
    } catch (e) { /* silencioso */ }
}

// ══════════════════════════════════════════════════════════════════════
// Init
// ══════════════════════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    initUpload();
    initSynonymsFilters();
    ensureDrawerDom();
});

// Expose para app.extras.js / debug
window.VeraFact = { STATE, renderResult, openDrawer, closeDrawer, apiGet, apiPost, saveLineArticle, activateTab };

})();
