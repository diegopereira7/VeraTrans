/* ══════════════════════════════════════════════════════════════════════
   VeraFact — app.extras.js
   Extensiones que NO vienen en el app.js v4 del paquete de Claude Design:
     · Importación masiva (ZIP / Carpeta / PDFs) — 3 botones + drag-drop
     · Polling de progreso batch
     · Render de tabla de resultados con líneas expandibles
   Portado desde app.js.v3.bak. Se carga después de app.js y se auto-
   inicializa al DOMContentLoaded (o inmediatamente si ya está listo).
   ══════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    function init() {
        // Si el DOM no tiene el tab de batch (index.php antiguo), no hacer nada
        if (!document.getElementById('batchDropZone')) return;

        // ── Helpers locales (réplica de los del app.js v4) ─────────────
        const esc = s => String(s ?? '').replace(/[&<>"']/g, c => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
        ));
        const num = v => (v == null ? '0.00'
            : Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 5 }));
        const fmt$     = n => (n == null || isNaN(n)) ? '—' : '$' + Number(n).toFixed(2);
        const fmtPrice = n => (n == null || isNaN(n)) ? '—' : '$' + Number(n).toFixed(4);
        const fmtInt   = n => (n == null || isNaN(n)) ? '—' : Number(n).toLocaleString('es-ES');

        // Espejo de computeStatus / needsReview / computeOriginBadge del app.js v4
        const computeStatus = l => {
            const s = (l.match_status || '').toLowerCase();
            if (s === 'ok' || s === 'matched' || (l.articulo_id > 0 && !s)) return 'ok';
            if (s === 'sin_match' || s === 'no_match' || !l.articulo_id)    return 'sin_match';
            if (s === 'revisar' || s === 'pendiente' || s === 'review')     return 'revisar';
            return s || 'revisar';
        };
        const needsReview = l => {
            const st = computeStatus(l);
            if (st === 'sin_match') return true;
            if (st === 'revisar')   return true;
            const conf = l.confidence != null ? l.confidence : l.match_confidence;
            if (conf != null && conf < 0.90) return true;
            return false;
        };
        const computeOriginBadge = l => {
            const v = (l.origin || l.match_method || '').toUpperCase();
            if (!v || l.match_status === 'sin_match') return null;
            if (v.includes('EST') || v.includes('ESTIMATE') || v.includes('FUZZY')) return 'est';
            if (v.includes('STD') || v.includes('STANDARD')) return 'std';
            return 'or';
        };

        // ── Referencias DOM ────────────────────────────────────────────
        const batchDropZone    = document.getElementById('batchDropZone');
        const batchZipInput    = document.getElementById('batchZipInput');
        const batchFolderInput = document.getElementById('batchFolderInput');
        const batchPdfInput    = document.getElementById('batchPdfInput');
        const batchUploadZone  = document.getElementById('batch-upload-zone');
        const batchProgress    = document.getElementById('batch-progress');
        const batchResults     = document.getElementById('batch-results');

        let batchId = null;
        let batchPollingTimer = null;
        let batchAllResults = [];

        // ── Drag & drop ────────────────────────────────────────────────
        batchDropZone.addEventListener('dragover', e => {
            e.preventDefault();
            batchDropZone.classList.add('drag-over');
        });
        batchDropZone.addEventListener('dragleave', () => batchDropZone.classList.remove('drag-over'));
        batchDropZone.addEventListener('drop', e => {
            e.preventDefault();
            batchDropZone.classList.remove('drag-over');
            const files = [...e.dataTransfer.files];
            if (files.length === 1 && files[0].name.toLowerCase().endsWith('.zip')) {
                batchUploadZip(files[0]);
            } else {
                const pdfs = files.filter(f => f.name.toLowerCase().endsWith('.pdf'));
                if (pdfs.length > 0) batchUploadPdfs(pdfs);
                else alert('Arrastra archivos PDF o un ZIP');
            }
        });

        // ── Botones ────────────────────────────────────────────────────
        document.getElementById('btnSelectZip')?.addEventListener('click', e => {
            e.preventDefault(); e.stopPropagation(); batchZipInput.click();
        });
        batchZipInput?.addEventListener('change', () => {
            if (batchZipInput.files[0]) batchUploadZip(batchZipInput.files[0]);
        });

        document.getElementById('btnSelectFolder')?.addEventListener('click', e => {
            e.preventDefault(); e.stopPropagation(); batchFolderInput.click();
        });
        batchFolderInput?.addEventListener('change', () => {
            const pdfs = [...batchFolderInput.files].filter(f => f.name.toLowerCase().endsWith('.pdf'));
            if (pdfs.length > 0) batchUploadPdfs(pdfs);
            else alert('La carpeta no contiene archivos PDF');
        });

        document.getElementById('btnSelectPdfs')?.addEventListener('click', e => {
            e.preventDefault(); e.stopPropagation(); batchPdfInput.click();
        });
        batchPdfInput?.addEventListener('change', () => {
            const pdfs = [...batchPdfInput.files];
            if (pdfs.length > 0) batchUploadPdfs(pdfs);
        });

        // ── Upload de ZIP ──────────────────────────────────────────────
        async function batchUploadZip(file) {
            if (!file.name.toLowerCase().endsWith('.zip')) {
                alert('Selecciona un archivo .zip'); return;
            }
            batchUploadZone.classList.add('hidden');
            batchProgress.classList.remove('hidden');
            batchResults.classList.add('hidden');

            document.getElementById('batch-status-text').textContent = 'Subiendo ZIP...';
            document.getElementById('batch-progress-count').textContent = '';
            document.getElementById('batchProgressBar').style.width = '0%';
            document.getElementById('batch-current-pdf').textContent = file.name;
            document.getElementById('batch-ok-err').textContent = '';

            const form = new FormData();
            form.append('zip', file);
            try {
                const res = await fetch('api.php?action=batch_upload', { method: 'POST', body: form });
                const data = await res.json();
                if (!data.ok) { alert('Error: ' + data.error); batchReset(); return; }
                batchId = data.batch_id;
                document.getElementById('batch-status-text').textContent = 'Procesando...';
                document.getElementById('batch-progress-count').textContent = `0 / ${data.total_pdfs}`;
                batchPollingTimer = setInterval(batchPollStatus, 2000);
            } catch (err) {
                alert('Error de conexión: ' + err.message);
                batchReset();
            }
        }

        // ── Upload de PDFs sueltos / carpeta ───────────────────────────
        async function batchUploadPdfs(files) {
            batchUploadZone.classList.add('hidden');
            batchProgress.classList.remove('hidden');
            batchResults.classList.add('hidden');

            document.getElementById('batch-status-text').textContent = `Subiendo ${files.length} PDFs...`;
            document.getElementById('batch-progress-count').textContent = '';
            document.getElementById('batchProgressBar').style.width = '0%';
            document.getElementById('batch-current-pdf').textContent = '';
            document.getElementById('batch-ok-err').textContent = '';

            const form = new FormData();
            for (const f of files) form.append('pdfs[]', f);
            try {
                const res = await fetch('api.php?action=batch_upload_pdfs', { method: 'POST', body: form });
                const data = await res.json();
                if (!data.ok) { alert('Error: ' + data.error); batchReset(); return; }
                batchId = data.batch_id;
                document.getElementById('batch-status-text').textContent = 'Procesando...';
                document.getElementById('batch-progress-count').textContent = `0 / ${data.total_pdfs}`;
                batchPollingTimer = setInterval(batchPollStatus, 2000);
            } catch (err) {
                alert('Error de conexión: ' + err.message);
                batchReset();
            }
        }

        // ── Polling de estado ──────────────────────────────────────────
        async function batchPollStatus() {
            if (!batchId) return;
            try {
                const res = await fetch(`api.php?action=batch_status&batch_id=${batchId}`);
                const data = await res.json();
                if (!data.ok && data.error) {
                    clearInterval(batchPollingTimer);
                    alert('Error: ' + data.error);
                    batchReset(); return;
                }
                const pct = data.porcentaje || 0;
                document.getElementById('batchProgressBar').style.width = pct + '%';
                document.getElementById('batch-progress-count').textContent =
                    `${data.progreso || 0} / ${data.total || 0}`;
                document.getElementById('batch-current-pdf').textContent = data.actual || '';
                document.getElementById('batch-ok-err').textContent =
                    `OK: ${data.procesados_ok || 0} | Errores: ${data.con_error || 0}`;

                const statusMap = {
                    iniciando: 'Iniciando...',
                    cargando_datos: 'Cargando artículos y sinónimos...',
                    procesando: 'Procesando facturas...',
                    generando_excel: 'Generando Excel...',
                };
                document.getElementById('batch-status-text').textContent =
                    statusMap[data.estado] || data.estado;

                if (data.estado === 'completado') {
                    clearInterval(batchPollingTimer);
                    batchShowResults(data);
                } else if (data.estado === 'error') {
                    clearInterval(batchPollingTimer);
                    alert('Error en el procesamiento: ' + (data.error || 'desconocido'));
                    batchReset();
                }
            } catch (err) { /* silencio en polling */ }
        }

        // Aplana todas las líneas de todas las facturas en un único array
        // con `idx` global coherente. Poblar window.VeraFact.STATE.lines
        // con este flat permite que openDrawer() del app.js v4 encuentre
        // la línea correcta cuando se clicka desde el detalle del batch.
        function _populateFlatLines() {
            const flat = [];
            batchAllResults.forEach((inv, invIdx) => {
                if (!inv.lines) return;
                inv.lines.forEach((l, lineIdx) => {
                    l.idx = flat.length;            // idx global
                    l._batchInvoiceIdx = invIdx;
                    l._batchLineIdx    = lineIdx;
                    // Alias compatibles con normalizeLines del v4
                    l.total      = l.total      ?? l.total_line ?? l.line_total ?? l.total_linea;
                    l.confidence = l.confidence ?? l.match_confidence;
                    l.price      = l.price      ?? l.price_per_stem ?? l.precio_stem;
                    flat.push(l);
                });
            });
            if (window.VeraFact && window.VeraFact.STATE) {
                window.VeraFact.STATE.lines = flat;
            }
        }

        // ── Render de resultados ───────────────────────────────────────
        function batchShowResults(data) {
            batchProgress.classList.add('hidden');
            batchResults.classList.remove('hidden');

            const r = data.resumen || {};
            batchAllResults = data.resultados || [];
            _populateFlatLines();

            const tNeeds    = r.total_needs_review || 0;
            const tAnom     = r.total_anomalies    || 0;
            const tNoCuadra = r.total_no_cuadra    || 0;
            const tOmit     = r.omitidos           || 0;
            const summary = document.getElementById('batchSummary');
            if (summary) summary.innerHTML = `
                <div class="stat-card"><div class="stat-card__label">Facturas</div><div class="stat-card__value">${r.total_facturas || 0}</div></div>
                <div class="stat-card stat-card--ok"><div class="stat-card__label">Procesadas</div><div class="stat-card__value">${r.procesadas_ok || 0}</div></div>
                ${r.con_error > 0 ? `<div class="stat-card stat-card--err"><div class="stat-card__label">Con error</div><div class="stat-card__value">${r.con_error}</div></div>` : ''}
                ${tOmit > 0 ? `<div class="stat-card stat-card--warn"><div class="stat-card__label">Omitidos</div><div class="stat-card__value">${tOmit}</div></div>` : ''}
                <div class="stat-card stat-card--primary"><div class="stat-card__label">Líneas</div><div class="stat-card__value">${r.total_lineas || 0}</div></div>
                <div class="stat-card stat-card--ok"><div class="stat-card__label">Matcheadas</div><div class="stat-card__value">${r.total_ok || 0}</div></div>
                ${r.total_sin_match > 0 ? `<div class="stat-card stat-card--err"><div class="stat-card__label">Sin match</div><div class="stat-card__value">${r.total_sin_match}</div></div>` : ''}
                <div class="stat-card ${tNeeds > 0 ? 'stat-card--warn' : 'stat-card--ok'}"><div class="stat-card__label">A revisar</div><div class="stat-card__value">${tNeeds}</div></div>
                ${tNoCuadra > 0 ? `<div class="stat-card stat-card--err"><div class="stat-card__label">No cuadran</div><div class="stat-card__value">${tNoCuadra}</div></div>` : ''}
                ${tAnom > 0 ? `<div class="stat-card stat-card--err"><div class="stat-card__label">Precio anómalo</div><div class="stat-card__value">${tAnom}</div></div>` : ''}
                <div class="stat-card stat-card--primary"><div class="stat-card__label">Total USD</div><div class="stat-card__value">$${Number(r.total_usd || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}</div></div>
            `;

            const skippedDetails = document.getElementById('batchSkippedDetails');
            const skippedContent = document.getElementById('batchSkippedContent');
            const omitList = data.omitidos_detalle || [];
            const errList  = data.errores || [];
            if (skippedDetails && skippedContent) {
                if (omitList.length + errList.length > 0) {
                    let html = '';
                    if (omitList.length) {
                        html += `<div class="batch-skipped-section"><h4>Omitidos (${omitList.length})</h4><ul>${
                            omitList.map(o => `<li><code>${esc(o.pdf)}</code> — ${esc(o.motivo)}</li>`).join('')
                        }</ul></div>`;
                    }
                    if (errList.length) {
                        html += `<div class="batch-skipped-section"><h4>Con error (${errList.length})</h4><ul>${
                            errList.map(e => `<li><code>${esc(e.pdf)}</code> — ${esc(e.error)}</li>`).join('')
                        }</ul></div>`;
                    }
                    skippedContent.innerHTML = html;
                    skippedDetails.classList.remove('hidden');
                } else {
                    skippedDetails.classList.add('hidden');
                }
            }

            const selInvoice = document.getElementById('batchFilterInvoice');
            if (selInvoice) {
                selInvoice.innerHTML = '<option value="">Todas las facturas</option>' +
                    batchAllResults.filter(r => r.ok).map(r =>
                        `<option value="${esc(r.pdf)}">${esc(r.pdf)} — ${esc(r.provider)}</option>`
                    ).join('');
            }

            batchRenderTable(batchAllResults);
        }

        function batchRenderTable(list) {
            const tbody = document.querySelector('#batchTable tbody');
            if (!tbody) return;
            tbody.innerHTML = list.map((r, i) => {
                const needsRev = r.needs_review || 0;
                const val = r.validation || {};
                const rec = r.reconciliation || {};
                const noCuadra = val.header_ok === false;
                const anomalies = rec.anomalies || 0;
                let status, statusClass;
                if (!r.ok)                                             { status = 'ERROR';   statusClass = 'badge badge-sin-match'; }
                else if (r.sin_match > 0 || needsRev > 0 || noCuadra || anomalies > 0) { status = 'REVISAR'; statusClass = 'badge badge-fuzzy'; }
                else                                                   { status = 'OK';      statusClass = 'badge badge-ok'; }

                const hasLines = r.ok && r.lines && r.lines.length > 0;
                const rowId = `batch-lines-${i}`;

                let parentCls = '';
                if (!r.ok) parentCls = 'row-sin-match';
                else if (status === 'REVISAR') parentCls = 'row-low-conf';

                let html = `
                    <tr class="${parentCls} ${hasLines ? 'batch-expandable' : ''}" data-target="${rowId}">
                        <td>${i + 1}</td>
                        <td>${hasLines ? '<span class="expand-arrow">&#9654;</span> ' : ''}${esc(r.pdf)}</td>
                        <td>${esc(r.provider || '-')}</td>
                        <td>${esc(r.invoice || '-')}</td>
                        <td>${esc(r.date || '-')}</td>
                        <td>${r.lineas || 0}</td>
                        <td>${r.ok_count || 0}</td>
                        <td>${r.sin_match || 0}</td>
                        <td>${needsRev > 0 ? `<strong style="color:#d97706">${needsRev}</strong>` : '0'}</td>
                        <td>$${num(r.total_usd || 0)}</td>
                        <td><span class="${statusClass}">${status}</span>${!r.ok ? `<br><small>${esc(r.error)}</small>` : ''}</td>
                    </tr>`;

                if (hasLines) {
                    // Tabla expandible con la MISMA estructura que la tabla
                    // de "Procesar factura" del app.js v4 (12 columnas).
                    html += `<tr id="${rowId}" class="batch-lines-row hidden">
                        <td colspan="11" style="padding:0">
                            <div class="table-wrap" style="margin:0;border-radius:0;box-shadow:none;border:0;border-top:1px solid var(--line)">
                                <div class="table-scroll">
                                    <table class="t">
                                        <thead><tr>
                                            <th style="width:28px">#</th>
                                            <th>Descripción</th>
                                            <th style="width:90px">Especie</th>
                                            <th style="width:110px">Variedad</th>
                                            <th class="num" style="width:52px">Talla</th>
                                            <th class="num" style="width:42px">SPB</th>
                                            <th class="num" style="width:56px">Tallos</th>
                                            <th class="num" style="width:68px">Precio</th>
                                            <th class="num" style="width:78px">Total</th>
                                            <th>Artículo VeraBuy</th>
                                            <th style="width:110px">Match</th>
                                        </tr></thead>
                                        <tbody>${r.lines.map((l, li) => _batchLineRow(l, li + 1)).join('')}</tbody>
                                    </table>
                                </div>
                            </div>
                        </td>
                    </tr>`;
                }
                return html;
            }).join('');

            // Tras renderizar: enganchar hover/click/drawer/erp-input en
            // las filas de detalle (tabla interior).
            wireBatchLineEvents();
        }

        // Renderiza una línea con la MISMA estructura visual que
        // renderLineRow() del app.js v4: numeración, progress bar,
        // badge circular OR/EST, input id_erp, chip ok/revisar.
        function _batchLineRow(l, rowNum) {
            const st     = computeStatus(l);
            const review = needsReview(l);
            const badge  = computeOriginBadge(l);

            // Normalizar a los nombres de campo que usa el v4 (el backend
            // emite algunos con otro nombre; el adaptador en handleProcess
            // ya copia `total_line` y `confidence`, pero aquí venimos del
            // endpoint batch que no pasa por ese adaptador).
            const size  = l.size  ?? l.talla;
            const spb   = l.spb   ?? l.stems_per_bunch ?? l.paquete;
            const stems = l.stems ?? l.tallos;
            const price = l.price_per_stem ?? l.precio_stem ?? l.price;
            const total = l.total_line ?? l.line_total ?? l.total_linea ?? l.total;
            const conf  = l.confidence != null ? l.confidence : l.match_confidence;

            // Progress bar de confianza
            let confHtml;
            if (conf != null) {
                const pct = Math.round((conf || 0) * 100);
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
                        <div class="art-ref">${esc(l.articulo_id_erp || l.id_erp || l.articulo_ref || l.referencia || '#' + l.articulo_id)}</div>
                    </div>`;
            } else {
                artHtml = `<span class="art-empty">Sin vincular</span>`;
            }

            const badgeHtml = badge
                ? `<span class="origin-badge origin-badge--${badge}" title="${badge === 'or' ? 'Original' : badge === 'est' ? 'Estimado' : 'Estándar'}">${badge.toUpperCase()}</span>`
                : '';

            const chipHtml = st === 'ok' && !review
                ? `<span class="chip chip--ok">OK</span>`
                : st === 'sin_match'
                ? `<span class="chip chip--err">Sin match</span>`
                : `<span class="chip chip--warn">Revisar</span>`;

            const isMixed = l.box_type && /mix/i.test(l.box_type);
            const descHtml = `
                <div class="desc-cell">
                    ${isMixed ? '<span class="chip chip--info" style="margin-right:6px">MIX</span>' : ''}
                    <span class="desc-main">${esc(l.variety || (l.raw || '').slice(0, 40) || '—')}</span>
                    ${l.raw ? `<div class="desc-raw" title="${esc(l.raw)}">${esc(l.raw)}</div>` : ''}
                </div>`;

            const erpInput = `<input type="text" class="erp-input" data-row-idx="${l.idx}"
                value="${esc(l.articulo_id_erp || l.id_erp || '')}" placeholder="id_erp…"
                aria-label="id_erp fila ${rowNum}">`;

            return `
                <tr class="is-clickable" data-row-idx="${l.idx}">
                    <td><span class="line-num">${String(rowNum).padStart(2, '0')}</span></td>
                    <td>${descHtml}</td>
                    <td>${esc(l.species || l.especie || '—')}</td>
                    <td>${esc(l.variety || l.variedad || '—')}</td>
                    <td class="num">${size ?? '—'}</td>
                    <td class="num">${spb ?? '—'}</td>
                    <td class="num">${fmtInt(stems)}</td>
                    <td class="num">${fmtPrice(price)}</td>
                    <td class="num">${fmt$(total)}</td>
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

        // Engancha los mismos listeners que wireTableEvents() del app.js
        // v4 pero sobre el batch table — click → drawer, erp-input → lookup.
        function wireBatchLineEvents() {
            const scope = document.querySelector('#batchTable');
            if (!scope) return;

            scope.querySelectorAll('tr.is-clickable').forEach(tr => {
                if (tr.__bound) return;
                tr.__bound = true;
                tr.addEventListener('click', e => {
                    if (e.target.closest('input, button, a')) return;
                    const idx = Number(tr.dataset.rowIdx);
                    if (window.VeraFact && typeof window.VeraFact.openDrawer === 'function') {
                        window.VeraFact.openDrawer(idx);
                    }
                });
            });

            scope.querySelectorAll('.erp-input').forEach(inp => {
                if (inp.__bound) return;
                inp.__bound = true;
                inp.addEventListener('change', async () => {
                    const idx = Number(inp.dataset.rowIdx);
                    const val = inp.value.trim();
                    const lines = window.VeraFact && window.VeraFact.STATE && window.VeraFact.STATE.lines;
                    const line = lines && lines[idx];
                    if (!line) return;
                    if (!val) {
                        line.articulo_id_erp = '';
                        line.articulo_id = 0;
                        line.articulo_name = '';
                        line.match_status = 'sin_match';
                        _rerenderBatchPreservingOpen();
                        return;
                    }
                    try {
                        const r = await fetch(`api.php?action=lookup_article&id_erp=${encodeURIComponent(val)}`).then(x => x.json());
                        const art = r && r.ok && (r.articulo || r);   // algunos handlers devuelven los campos en raíz
                        if (r && r.ok && (art.id || art.articulo_id || art.nombre)) {
                            line.articulo_id     = art.id || art.articulo_id || 0;
                            line.articulo_id_erp = art.id_erp || val;
                            line.articulo_name   = art.nombre || art.name || '';
                            line.articulo_ref    = art.referencia || '';
                            line.match_status    = 'ok';
                            line.match_method    = 'manual-erp';
                            line.confidence      = 1.0;
                            line.origin          = 'OR';
                            _rerenderBatchPreservingOpen();
                        } else {
                            inp.style.borderColor = 'var(--err)';
                            setTimeout(() => inp.style.borderColor = '', 1200);
                        }
                    } catch (err) {
                        inp.style.borderColor = 'var(--err)';
                        setTimeout(() => inp.style.borderColor = '', 1200);
                    }
                });
            });
        }

        // Re-renderiza la tabla del batch preservando qué filas de factura
        // estaban expandidas. Se llama tras modificar una línea via erp-input.
        function _rerenderBatchPreservingOpen() {
            const open = [];
            document.querySelectorAll('#batchTable tbody tr.batch-lines-row').forEach(tr => {
                if (!tr.classList.contains('hidden')) open.push(tr.id);
            });
            batchRenderTable(batchAllResults);
            open.forEach(id => {
                const row = document.getElementById(id);
                if (row) row.classList.remove('hidden');
                const parent = document.querySelector(`#batchTable tr.batch-expandable[data-target="${id}"]`);
                if (parent) {
                    const arrow = parent.querySelector('.expand-arrow');
                    if (arrow) arrow.innerHTML = '&#9660;';
                }
            });
        }

        // ── Expandir/colapsar filas ────────────────────────────────────
        document.querySelector('#batchTable tbody')?.addEventListener('click', e => {
            // Si el click viene de una fila interior (detalle), dejar que
            // lo maneje su propio listener — no expandir/colapsar padre.
            if (e.target.closest('tr.is-clickable, .batch-lines-row input, .batch-lines-row button, .batch-lines-row a')) {
                return;
            }
            const expandRow = e.target.closest('.batch-expandable');
            if (expandRow) {
                const linesRow = document.getElementById(expandRow.dataset.target);
                if (linesRow) {
                    linesRow.classList.toggle('hidden');
                    const arrow = expandRow.querySelector('.expand-arrow');
                    if (arrow) arrow.innerHTML = linesRow.classList.contains('hidden') ? '&#9654;' : '&#9660;';
                }
            }
        });

        // ── Filtros ────────────────────────────────────────────────────
        function batchFilter() {
            const inv  = document.getElementById('batchFilterInvoice')?.value || '';
            const stat = document.getElementById('batchFilterStatus')?.value || '';
            const text = (document.getElementById('batchFilterText')?.value || '').toLowerCase();
            let filtered = batchAllResults;
            if (inv) filtered = filtered.filter(r => r.pdf === inv);
            if (stat) filtered = filtered.filter(r => {
                if (stat === 'ok')      return r.ok && r.sin_match === 0;
                if (stat === 'parcial') return r.ok && r.sin_match > 0;
                if (stat === 'error')   return !r.ok;
                return true;
            });
            if (text) filtered = filtered.filter(r =>
                (r.pdf || '').toLowerCase().includes(text) ||
                (r.provider || '').toLowerCase().includes(text) ||
                (r.invoice || '').toLowerCase().includes(text));
            batchRenderTable(filtered);
        }
        document.getElementById('batchFilterInvoice')?.addEventListener('change', batchFilter);
        document.getElementById('batchFilterStatus')?.addEventListener('change', batchFilter);
        document.getElementById('batchFilterText')?.addEventListener('input', batchFilter);

        // ── Botones resultado ──────────────────────────────────────────
        document.getElementById('btnBatchExcel')?.addEventListener('click', () => {
            if (batchId) window.location.href = `api.php?action=batch_download&batch_id=${batchId}`;
        });
        document.getElementById('btnBatchNew')?.addEventListener('click', () => batchReset());

        function batchReset() {
            batchId = null;
            if (batchPollingTimer) clearInterval(batchPollingTimer);
            batchPollingTimer = null;
            batchAllResults = [];
            batchUploadZone.classList.remove('hidden');
            batchProgress.classList.add('hidden');
            batchResults.classList.add('hidden');
            if (batchZipInput) batchZipInput.value = '';
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
