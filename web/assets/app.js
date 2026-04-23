/**
 * VeraBuy Traductor Web - Frontend
 */

// Canonicaliza la variedad para construir la synonym_key. DEBE coincidir
// con `normalize_variety_key` en `src/models.py` y `_normalizeVarietyKey`
// en `web/api.php` — si divergen se crean sinónimos duplicados fantasmas
// (MANDARIN. X-PRESSION vs MANDARIN X-PRESSION como claves distintas).
function _normalizeVariety(v) {
    return ((v || '').toUpperCase()
        .replace(/[^A-Z0-9 ]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim());
}

// Evita que la rueda del ratón cambie el valor de inputs type=number cuando
// están enfocados. En la vista batch el usuario teclea el ID del artículo y
// al hacer scroll para bajar por la lista, si el input aún tenía foco el
// número se incrementaba/decrementaba accidentalmente.
document.addEventListener('wheel', (e) => {
    if (e.target && e.target.type === 'number' && document.activeElement === e.target) {
        e.target.blur();
    }
}, { passive: true });

document.addEventListener('DOMContentLoaded', () => {
    // --- Navigation ---
    const navBtns = document.querySelectorAll('.nav-btn');
    const tabs = document.querySelectorAll('.tab');

    navBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const target = btn.dataset.tab;
            navBtns.forEach(b => b.classList.remove('active'));
            tabs.forEach(t => {
                t.classList.remove('active');
                t.classList.add('hidden');
            });
            btn.classList.add('active');
            const tab = document.getElementById('tab-' + target);
            tab.classList.remove('hidden');
            tab.classList.add('active');

            // Load data on tab switch
            if (target === 'history') loadHistory();
            if (target === 'synonyms') loadSynonyms();
            if (target === 'learned') loadLearnedParsers();
        });
    });

    // --- File Upload ---
    const dropZone = document.getElementById('dropZone');
    const pdfInput = document.getElementById('pdfInput');
    const btnSelect = document.getElementById('btnSelectFile');
    const processing = document.getElementById('processing');
    const resultSection = document.getElementById('resultSection');
    const btnNewUpload = document.getElementById('btnNewUpload');

    btnSelect.addEventListener('click', (e) => {
        e.stopPropagation();
        pdfInput.click();
    });

    dropZone.addEventListener('click', () => pdfInput.click());

    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('dragover');
    });

    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('dragover');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        const files = e.dataTransfer.files;
        if (files.length > 0 && files[0].type === 'application/pdf') {
            processFile(files[0]);
        }
    });

    pdfInput.addEventListener('change', () => {
        if (pdfInput.files.length > 0) {
            processFile(pdfInput.files[0]);
        }
    });

    btnNewUpload.addEventListener('click', resetUpload);

    // Generar Hoja de Orden
    document.getElementById('btnGenerarOrden').addEventListener('click', async () => {
        if (!window._invoiceData || !window._flatLines) {
            alert('No hay factura procesada'); return;
        }
        const header = window._invoiceData.header;
        const lines = window._flatLines.filter(l => !l._deleted).map(l => ({
            articulo_id: l.articulo_id || 0,
            stems: l.stems || 0,
            stems_per_bunch: l.stems_per_bunch || 0,
            bunches: l.bunches || 0,
            line_total: l.line_total || 0,
            match_status: l.match_status || '',
        }));
        const withArt = lines.filter(l => l.articulo_id > 0);
        if (withArt.length === 0) {
            alert('No hay líneas con artículo asignado para generar orden'); return;
        }
        const sinMatch = lines.length - withArt.length;
        if (sinMatch > 0) {
            if (!confirm(`Hay ${sinMatch} líneas sin artículo que no se incluirán en la orden. ¿Continuar?`)) return;
        }
        try {
            const resp = await fetch('api.php?action=generar_orden', {
                method: 'POST', headers: {'Content-Type':'application/json'},
                body: JSON.stringify({ header, lines })
            });
            const data = await resp.json();
            const msg = document.getElementById('ordenMsg');
            if (data.ok) {
                msg.innerHTML = `<span style="color:var(--success);font-weight:600">✓ ${data.message}</span>`;
                document.getElementById('btnGenerarOrden').disabled = true;
                document.getElementById('btnGenerarOrden').textContent = 'Orden Generada';
            } else {
                msg.innerHTML = `<span style="color:var(--danger)">${esc(data.error)}</span>`;
            }
        } catch(e) {
            alert('Error de conexión');
        }
    });

    function resetUpload() {
        pdfInput.value = '';
        dropZone.classList.remove('hidden');
        processing.classList.add('hidden');
        resultSection.classList.add('hidden');
        // Reset order button
        const btn = document.getElementById('btnGenerarOrden');
        btn.disabled = false;
        btn.textContent = 'Generar Hoja de Orden';
        document.getElementById('ordenMsg').innerHTML = '';
        window._invoiceData = null;
        window._flatLines = null;
    }

    async function processFile(file) {
        dropZone.classList.add('hidden');
        processing.classList.remove('hidden');
        resultSection.classList.add('hidden');

        const formData = new FormData();
        formData.append('pdf', file);

        try {
            const resp = await fetch('api.php?action=process', {
                method: 'POST',
                body: formData
            });
            const data = await resp.json();

            processing.classList.add('hidden');

            if (!data.ok) {
                alert('Error: ' + (data.error || 'Error desconocido'));
                resetUpload();
                return;
            }

            renderResult(data);
            resultSection.classList.remove('hidden');
        } catch (err) {
            processing.classList.add('hidden');
            alert('Error de conexión: ' + err.message);
            resetUpload();
        }
    }

    // --- Render Invoice Result ---
    // Store current invoice data for editing
    window._invoiceData = null;

    function renderResult(data) {
        window._invoiceData = data;
        const h = data.header;

        // Editable header
        document.getElementById('invoiceHeader').innerHTML = `
            <div class="field">
                <span class="field-label">Proveedor</span>
                <input class="field-value edit-header" data-field="provider_name" value="${esc(h.provider_name)}"/>
            </div>
            <div class="field">
                <span class="field-label">Factura</span>
                <input class="field-value edit-header" data-field="invoice_number" value="${esc(h.invoice_number)}"/>
            </div>
            <div class="field">
                <span class="field-label">Fecha</span>
                <input class="field-value edit-header" data-field="date" value="${esc(h.date)}"/>
            </div>
            <div class="field">
                <span class="field-label">AWB</span>
                <input class="field-value edit-header" data-field="awb" value="${esc(h.awb)}"/>
            </div>
            <div class="field">
                <span class="field-label">Total USD</span>
                <input class="field-value edit-header" data-field="total" type="number" step="0.01" value="${h.total}"/>
            </div>
            <div class="field">
                <span class="field-label">ID Proveedor</span>
                <input class="field-value edit-header" data-field="provider_id" type="number" value="${h.provider_id}"/>
            </div>
        `;

        // Sync header edits back to data
        document.querySelectorAll('.edit-header').forEach(input => {
            input.addEventListener('change', () => {
                const field = input.dataset.field;
                const val = input.type === 'number' ? parseFloat(input.value) || 0 : input.value;
                window._invoiceData.header[field] = val;
            });
        });

        const s = data.stats;
        const sinParser = s.sin_parser || 0;
        const needsReview = s.needs_review || 0;
        const ambiguous = s.ambiguous || 0;
        // Contar carriles de revisión
        // Contar carriles: se calcula sobre data.lines (flat) ya que flatLines aún no existe
        const allLines = [];
        (data.lines || []).forEach(l => {
            if (l.children) l.children.forEach(c => allLines.push(c));
            else allLines.push(l);
        });
        const laneAuto = allLines.filter(l => l.review_lane === 'auto').length;
        const laneQuick = allLines.filter(l => l.review_lane === 'quick').length;
        const laneFull = allLines.filter(l => l.review_lane === 'full').length;
        const ocrConf = typeof s.ocr_confidence === 'number' ? s.ocr_confidence : 1.0;
        const extConf = typeof s.extraction_confidence === 'number' ? s.extraction_confidence : ocrConf;
        const extSource = s.extraction_source || 'native';
        const extEngine = s.extraction_engine || '';
        const extDegraded = s.extraction_degraded === true;
        const val = data.validation || {};
        const rec = data.reconciliation || {};
        const headerOk = val.header_ok !== false;
        const headerDiff = val.header_diff || 0;
        const anomalies = rec.anomalies || 0;
        document.getElementById('statsBar').innerHTML = `
            <div class="stat-card">
                <div class="stat-value">${s.total_lineas}</div>
                <div class="stat-label">Total Líneas</div>
            </div>
            <div class="stat-card success">
                <div class="stat-value">${s.ok}</div>
                <div class="stat-label">Matcheadas</div>
            </div>
            <div class="stat-card ${s.sin_match > 0 ? 'danger' : 'success'}">
                <div class="stat-value">${s.sin_match}</div>
                <div class="stat-label">Sin Match</div>
            </div>
            ${sinParser > 0 ? `
            <div class="stat-card warning">
                <div class="stat-value">${sinParser}</div>
                <div class="stat-label">No Parseadas</div>
            </div>` : ''}
            ${ambiguous > 0 ? `
            <div class="stat-card warning"
                 title="Líneas leídas razonablemente pero con varios candidatos plausibles o evidencia insuficiente. Requieren confirmación humana antes de auto-vincular.">
                <div class="stat-value">${ambiguous}</div>
                <div class="stat-label">Ambiguas</div>
            </div>` : ''}
            <div class="stat-card ${needsReview > 0 ? 'warning' : 'success'}"
                 title="Líneas con confianza < 80%. Revisa estas antes de generar la orden.">
                <div class="stat-value">${needsReview}</div>
                <div class="stat-label">A Revisar</div>
            </div>
            <div class="stat-card success"
                 title="Carriles: Auto=${laneAuto} (sin revisión) · Quick=${laneQuick} (revisión rápida) · Full=${laneFull} (revisión completa)">
                <div class="stat-value">${laneAuto}/${allLines.length}</div>
                <div class="stat-label">Auto ${allLines.length ? Math.round(laneAuto/allLines.length*100) : 0}%</div>
            </div>
            <div class="stat-card ${headerOk ? 'success' : 'danger'}"
                 title="Suma de líneas vs total de factura.${headerDiff ? ' Diferencia: ' + headerDiff.toFixed(2) + ' USD' : ''}">
                <div class="stat-value">${headerOk ? '✓' : (headerDiff >= 0 ? '+' : '') + headerDiff.toFixed(2)}</div>
                <div class="stat-label">Totales</div>
            </div>
            ${anomalies > 0 ? `
            <div class="stat-card danger"
                 title="Precios con desviación >15% respecto al histórico del proveedor.">
                <div class="stat-value">${anomalies}</div>
                <div class="stat-label">Precio Anómalo</div>
            </div>` : ''}
            ${extSource !== 'native' ? `
            <div class="stat-card ${extConf < 0.75 || extDegraded ? 'warning' : ''}"
                 title="Fuente de la extracción: ${extSource}${extEngine ? ' (' + extEngine + ')' : ''}. Confianza agregada ${Math.round(extConf * 100)}%${extDegraded ? ' — alguna página quedó degradada.' : '.'}">
                <div class="stat-value">${Math.round(extConf * 100)}%</div>
                <div class="stat-label">Extracción ${extSource === 'ocr' ? 'OCR' : extSource === 'mixed' ? 'Mixta' : extSource}</div>
            </div>` : ''}
        `;

        // Guardar deltas de precio para mostrar en tooltips por línea.
        window._priceDeltas = {};
        (rec.deltas || []).forEach(d => {
            if (d.articulo_id) window._priceDeltas[d.articulo_id] = d;
        });

        window._currentProviderId = data.header.provider_id || 0;

        // Flatten lines for editing (expand mixed parent children)
        const flatLines = [];
        data.lines.forEach(l => {
            if (l.row_type === 'mixed_parent' && l.children) {
                l.children.forEach(c => flatLines.push(c));
            } else if (!l.row_type) {
                flatLines.push(l);
            }
        });
        window._flatLines = flatLines;

        const tbody = document.querySelector('#linesTable tbody');
        tbody.innerHTML = flatLines.map((l, i) => {
            const synKey = `${window._currentProviderId}|${l.species||''}|${_normalizeVariety(l.variety)}|${l.size||0}|${l.stems_per_bunch||0}|${(l.grade||'').toUpperCase()}`;
            // Clase de fila: sin_parser > rescue > ambiguous > sin_match > validation errors > low confidence
            const hasErrors = l.validation_errors && l.validation_errors.length > 0;
            const needsRev = l.needs_review === true;
            const isRescue = l.extraction_source === 'rescue';
            const isAmbiguous = l.match_status === 'ambiguous_match';
            const priceDelta = window._priceDeltas && l.articulo_id ? window._priceDeltas[l.articulo_id] : null;
            let rowClass = '';
            if (l.match_status === 'sin_parser') rowClass = 'row-sin-parser';
            else if (isRescue) rowClass = 'row-rescue';
            else if (isAmbiguous) rowClass = 'row-ambiguous';
            else if (l.match_status !== 'ok' && l.match_status !== 'mixed_box') rowClass = 'row-sin-match';
            else if (hasErrors) rowClass = 'row-has-error';
            else if (needsRev) rowClass = 'row-low-conf';
            // Tooltip de razones/penalizaciones del scoring por evidencia
            const reasonsTxt = (l.match_reasons && l.match_reasons.length ? 'Evidencia: ' + l.match_reasons.join(', ') : '')
                + (l.match_penalties && l.match_penalties.length ? ' | Penalizaciones: ' + l.match_penalties.join(', ') : '')
                + (typeof l.candidate_margin === 'number' ? ' | margen top1-top2: ' + l.candidate_margin.toFixed(2) : '');
            return `
            <tr class="${rowClass}" data-idx="${i}" data-syn-key="${esc(synKey)}"${reasonsTxt ? ' title="' + esc(reasonsTxt) + '"' : ''}>
                <td>${i+1}${confDot(l, priceDelta, hasErrors)}</td>
                <td title="${esc(l.raw)}">${esc((l.raw||'').substring(0, 55))}${(l.raw||'').length > 55 ? '...' : ''}</td>
                <td>${esc(l.species)}</td>
                <td><strong>${esc(l.variety)}</strong></td>
                <td><input class="edit-input edit-line" data-idx="${i}" data-field="size" type="number" value="${l.size||0}"/></td>
                <td><input class="edit-input edit-line" data-idx="${i}" data-field="stems_per_bunch" type="number" value="${l.stems_per_bunch||0}"/></td>
                <td><input class="edit-input edit-line" data-idx="${i}" data-field="stems" type="number" value="${l.stems||0}"/></td>
                <td><input class="edit-input edit-line" data-idx="${i}" data-field="price_per_stem" type="number" step="0.001" value="${num(l.price_per_stem||0)}"/></td>
                <td><input class="edit-input edit-line" data-idx="${i}" data-field="line_total" type="number" step="0.01" value="${num(l.line_total||0)}"/></td>
                <td>${l.articulo_id ? `<strong>${l.articulo_id}</strong> ${esc(l.articulo_name||'')}` : '<em>-</em>'}</td>
                <td>${matchBadge(l.match_status, l.match_method)}${confBadge(l.match_confidence)}${laneBadge(l.review_lane)}</td>
                <td style="white-space:nowrap"><input class="edit-input edit-art" data-idx="${i}" placeholder="id_erp/ref" title="id_erp o referencia (F...)" style="width:95px;display:inline-block" value="${l.articulo_id_erp||''}"/>${l.articulo_id ? `<button class="btn-icon line-confirm" data-idx="${i}" title="Confirmar match correcto" style="color:var(--success);font-size:14px;vertical-align:middle">✓</button>` : ''}<button class="btn-icon line-delete" data-idx="${i}" title="Eliminar línea" style="color:var(--danger);font-size:14px;vertical-align:middle">✕</button></td>
            </tr>`;
        }).join('');

        // Sync line edits
        document.querySelectorAll('.edit-line').forEach(input => {
            input.addEventListener('change', () => {
                const idx = parseInt(input.dataset.idx);
                const field = input.dataset.field;
                window._flatLines[idx][field] = input.type === 'number' ? parseFloat(input.value) || 0 : input.value;
            });
        });

        // Delete line button
        document.querySelectorAll('.line-delete').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.idx);
                const tr = btn.closest('tr');
                tr.remove();
                window._flatLines[idx]._deleted = true;
            });
        });

        // Confirm match button (✓)
        document.querySelectorAll('.line-confirm').forEach(btn => {
            btn.addEventListener('click', async () => {
                const idx = parseInt(btn.dataset.idx);
                const tr = btn.closest('tr');
                const synKey = tr.dataset.synKey;
                const line = window._flatLines[idx];
                if (!line.articulo_id) return;
                try {
                    const r = await fetch('api.php?action=confirm_match', {
                        method: 'POST', headers: {'Content-Type':'application/json'},
                        body: JSON.stringify({ key: synKey, articulo_id: line.articulo_id })
                    });
                    const d = await r.json();
                    if (d.ok) {
                        btn.textContent = '✓✓';
                        btn.style.color = '#2d8a4e';
                        btn.title = `Confirmado (${d.times_confirmed}x) — ${d.new_status}`;
                        btn.disabled = true;
                    }
                } catch(e) { /* silent */ }
            });
        });

        // Article lookup on Enter or change in the art column. Input =
        // id_erp o referencia; el id autoincrement no se acepta (10r).
        document.querySelectorAll('.edit-art').forEach(input => {
            const handler = async () => {
                const val = input.value.trim();
                if (!val) return;
                const idx = parseInt(input.dataset.idx);
                const tr = input.closest('tr');
                try {
                    const r = await fetch(`api.php?action=lookup_article&q=${encodeURIComponent(val)}`);
                    const d = await r.json();
                    if (d.ok) {
                        const line = window._flatLines[idx];
                        const synKey = tr.dataset.synKey;
                        const oldArtId = line.articulo_id || 0;
                        const oldArtIdErp = line.articulo_id_erp || '';
                        line.articulo_id = d.id;
                        line.articulo_id_erp = d.id_erp || '';
                        line.articulo_name = d.nombre;
                        line.match_status = 'ok';
                        tr.querySelectorAll('td')[9].innerHTML = `<strong>${d.id}</strong> ${esc(d.nombre)}`;
                        tr.querySelectorAll('td')[10].innerHTML = '<span class="badge badge-manual">manual-web</span>';
                        tr.classList.remove('row-sin-match');
                        input.value = d.id_erp || '';
                        // Correct (degrada sinónimo viejo) o save (nuevo)
                        const changed = oldArtIdErp && oldArtIdErp !== d.id_erp;
                        const action = changed ? 'correct_match' : 'save_synonym';
                        const body = changed
                            ? { key:synKey,
                                old_articulo_id:oldArtId,
                                new_articulo_id_erp: d.id_erp,
                                new_articulo_id: d.id,
                                new_articulo_name:d.nombre,
                                provider_id:window._currentProviderId, species:line.species,
                                variety:line.variety, size:line.size, stems_per_bunch:line.stems_per_bunch, grade:line.grade||'' }
                            : { key:synKey,
                                articulo_id_erp: d.id_erp,
                                articulo_id: d.id,
                                articulo_name: d.nombre,
                                provider_id:window._currentProviderId, species:line.species,
                                variety:line.variety, size:line.size, stems_per_bunch:line.stems_per_bunch, grade:line.grade||'' };
                        await fetch(`api.php?action=${action}`, {
                            method:'POST', headers:{'Content-Type':'application/json'},
                            body: JSON.stringify(body)
                        });
                    } else {
                        tr.querySelectorAll('td')[9].innerHTML = `<em style="color:var(--danger)">${esc(d.error)}</em>`;
                    }
                } catch(e) { /* silent */ }
            };
            input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); handler(); }});
            input.addEventListener('change', handler);
        });
    }

    // Enter key en inputs de artículo ID (inline edit) → auto-save
    document.addEventListener('keydown', e => {
        if (e.key === 'Enter' && e.target.classList.contains('batch-art-id')) {
            e.preventDefault();
            const saveBtn = e.target.closest('tr').querySelector('.batch-line-save');
            if (saveBtn) saveBtn.click();
        }
    });

    // Editar línea sin match en la tabla de factura individual.
    // Input = id_erp o referencia; el id autoincrement queda prohibido (10r).
    document.querySelector('#linesTable tbody').addEventListener('click', async e => {
        const saveBtn = e.target.closest('.batch-line-save');
        if (!saveBtn) return;
        const tr = saveBtn.closest('tr');
        const input = tr.querySelector('.batch-art-id');
        const userQuery = (input.value || '').trim();
        if (!userQuery) { alert('Introduce un id_erp o referencia'); return; }
        const synKey = tr.dataset.synKey;
        try {
            const lookupResp = await fetch(`api.php?action=lookup_article&q=${encodeURIComponent(userQuery)}`);
            const lookupData = await lookupResp.json();
            if (!lookupData.ok) { alert(lookupData.error); return; }
            const saveResp = await fetch('api.php?action=save_synonym', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    key: synKey,
                    articulo_id_erp: lookupData.id_erp,
                    articulo_id: lookupData.id,
                    articulo_name: lookupData.nombre,
                }),
            });
            const saveData = await saveResp.json();
            if (saveData.ok) {
                const cells = tr.querySelectorAll('td');
                cells[cells.length - 3].innerHTML = `<strong>${lookupData.id}</strong> ${esc(lookupData.nombre)}`;
                cells[cells.length - 2].innerHTML = '<span class="badge badge-manual">manual-web</span>';
                cells[cells.length - 1].innerHTML = '<span style="color:green">&#10003;</span>';
                tr.classList.remove('row-sin-match');
            } else {
                alert('Error: ' + saveData.error);
            }
        } catch (err) { alert('Error de conexión'); }
    });

    function matchBadge(status, method) {
        if (status === 'ok') {
            return `<span class="badge badge-ok" title="${esc(method)}">${esc(method)}</span>`;
        }
        if (status === 'sin_parser') {
            return '<span class="badge badge-sin-parser">NO PARSEADO</span>';
        }
        if (status === 'llm_extraido') {
            return '<span class="badge badge-fuzzy" title="Extraído por LLM — revisar manualmente">LLM</span>';
        }
        if (status === 'mixed_box') {
            return '<span class="badge badge-fuzzy" title="Caja mixta sin desglose">CAJA MIXTA</span>';
        }
        return '<span class="badge badge-sin-match">SIN MATCH</span>';
    }

    // Badge de confianza (solo si < 80% — sobre el badge principal añade porcentaje).
    function confBadge(conf) {
        if (typeof conf !== 'number' || conf <= 0 || conf >= 0.80) return '';
        const cls = conf < 0.60 ? 'badge-sin-match' : 'badge-fuzzy';
        return ` <span class="badge ${cls}" title="Confianza del match: ${Math.round(conf * 100)}%. Revisar manualmente.">${Math.round(conf * 100)}%</span>`;
    }

    // Badge de carril de revisión
    function laneBadge(lane) {
        if (lane === 'auto') return ' <span class="badge badge-ok" title="Autoaprobable — no necesita revisión">AUTO</span>';
        if (lane === 'quick') return ' <span class="badge badge-fuzzy" title="Revisión rápida — razonablemente bueno">QUICK</span>';
        if (lane === 'full') return ' <span class="badge badge-sin-match" title="Revisión completa — problema claro">FULL</span>';
        return '';
    }

    // Dot de estado junto al índice: rojo si errores, naranja si low conf, azul si delta precio.
    function confDot(l, priceDelta, hasErrors) {
        const dots = [];
        if (hasErrors) {
            const tip = l.validation_errors.join(' · ');
            dots.push(`<span class="conf-dot dot-err" title="${esc(tip)}">!</span>`);
        }
        if (priceDelta) {
            const sign = priceDelta.delta_pct >= 0 ? '+' : '';
            const tip = `Precio ${sign}${priceDelta.delta_pct}% vs histórico (ref ${priceDelta.price_ref})`;
            dots.push(`<span class="conf-dot dot-price" title="${esc(tip)}">$</span>`);
        }
        return dots.length ? ' ' + dots.join('') : '';
    }

    // --- History Tab ---
    let historyData = [];

    async function loadHistory() {
        const loading = document.getElementById('historyLoading');
        loading.classList.remove('hidden');

        try {
            const resp = await fetch('api.php?action=history', { method: 'POST' });
            const data = await resp.json();
            loading.classList.add('hidden');
            if (!data.ok) return;
            historyData = data.history;
            renderHistory();
        } catch (err) {
            loading.classList.add('hidden');
        }
    }

    function renderHistory() {
        const tbody = document.querySelector('#historyTable tbody');
        tbody.innerHTML = historyData.map((h, i) => {
            const hasPdf = !!(h.pdf);
            const needsReview = (h.sin_match || 0) > 0;
            const detailId = `hist-detail-${i}`;
            return `
                <tr class="${needsReview ? 'row-sin-match' : ''}" data-idx="${i}">
                    <td>${esc(h.fecha || '')}</td>
                    <td>${esc(h.invoice_key || '')}</td>
                    <td>${esc(h.provider || '')}</td>
                    <td>${esc(h.pdf || '')}</td>
                    <td>${h.lineas || 0}</td>
                    <td>${h.ok || 0}</td>
                    <td>${h.sin_match || 0}</td>
                    <td>$${num(h.total_usd || 0)}</td>
                    <td>${hasPdf ? `<button class="btn btn-sm btn-secondary hist-expand" data-pdf="${esc(h.pdf)}" data-pdf-path="${esc(h.pdf_path || '')}" data-detail="${detailId}">Ver líneas</button>` : '-'}</td>
                </tr>
                <tr id="${detailId}" class="batch-lines-row hidden">
                    <td colspan="9">
                        <div class="batch-lines-detail">
                            <div class="hist-detail-loading"><div class="spinner"></div> Reprocesando...</div>
                        </div>
                    </td>
                </tr>`;
        }).join('');
    }

    // Expandir historial: reprocesar PDF y mostrar líneas
    document.querySelector('#historyTable tbody').addEventListener('click', async e => {
        const expandBtn = e.target.closest('.hist-expand');
        if (expandBtn) {
            const detailId = expandBtn.dataset.detail;
            const detailRow = document.getElementById(detailId);
            if (!detailRow) return;

            // Toggle
            if (!detailRow.classList.contains('hidden') && detailRow.dataset.loaded) {
                detailRow.classList.add('hidden');
                expandBtn.textContent = 'Ver líneas';
                return;
            }

            detailRow.classList.remove('hidden');
            expandBtn.textContent = 'Ocultar';

            // Si ya está cargado, no reprocesar
            if (detailRow.dataset.loaded) return;

            // Reprocesar el PDF
            const pdf = expandBtn.dataset.pdf;
            const pdfPath = expandBtn.dataset.pdfPath || '';
            try {
                const resp = await fetch('api.php?action=reprocess', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ pdf, pdf_path: pdfPath }),
                });
                const data = await resp.json();
                detailRow.dataset.loaded = '1';

                if (!data.ok) {
                    const isNotFound = (data.error || '').includes('no encontrado');
                    detailRow.querySelector('.batch-lines-detail').innerHTML = isNotFound
                        ? `<p style="color:var(--text-muted)">PDF ya no disponible. Sube la factura en "Procesar Factura" para ver las líneas actualizadas.</p>`
                        : `<p style="color:var(--danger)">Error: ${esc(data.error)}</p>`;
                    return;
                }

                // Actualizar conteos de la fila padre con datos reales del reprocesado
                const parentRow = detailRow.previousElementSibling;
                if (parentRow && data.stats) {
                    const cells = parentRow.querySelectorAll('td');
                    cells[4].textContent = data.stats.total_lineas || 0;
                    cells[5].textContent = data.stats.ok || 0;
                    cells[6].textContent = data.stats.sin_match || 0;
                    if (data.stats.sin_match > 0) {
                        parentRow.classList.add('row-sin-match');
                    } else {
                        parentRow.classList.remove('row-sin-match');
                    }
                }

                const lines = data.lines || [];
                const needsReview = lines.some(l => l.match_status !== 'ok' && !l.row_type);
                const providerId = data.header?.provider_id || 0;

                detailRow.querySelector('.batch-lines-detail').innerHTML = `
                    <table class="batch-lines-table">
                        <thead><tr>
                            <th>Descripción</th><th>Variedad</th><th>Talla</th>
                            <th>Tallos</th><th>Total</th>
                            <th>ID Artículo</th><th>Nombre Artículo</th>
                            <th>Match</th>${needsReview ? '<th>Acción</th>' : ''}
                        </tr></thead>
                        <tbody>${lines.filter(l => !l.row_type).map(l => {
                            const isBad = l.match_status !== 'ok';
                            const key = `${providerId}|${l.species || ''}|${_normalizeVariety(l.variety)}|${l.size || 0}|${l.stems_per_bunch || 0}|${(l.grade || '').toUpperCase()}`;
                            return `<tr class="${isBad ? 'row-sin-match' : ''}" data-syn-key="${esc(key)}" data-pdf="${esc(pdf)}">
                                <td title="${esc(l.raw || '')}">${esc((l.raw || '').substring(0, 50))}${(l.raw||'').length > 50 ? '...' : ''}</td>
                                <td><strong>${esc(l.variety || '')}</strong></td>
                                <td>${l.size || '-'}</td>
                                <td>${l.stems || '-'}</td>
                                <td>$${num(l.line_total || 0)}</td>
                                <td>${l.articulo_id || '-'}</td>
                                <td>${esc(l.articulo_name || '-')}</td>
                                <td>${matchBadge(l.match_status || '', l.match_method || '')}</td>
                                ${needsReview && isBad ? `<td>
                                    <input type="text" class="edit-input batch-art-id" placeholder="id_erp/ref" title="id_erp o referencia (F...)" style="width:90px">
                                    <button class="btn-icon batch-line-save" title="Guardar">&#10003;</button>
                                </td>` : (needsReview ? '<td></td>' : '')}
                            </tr>`;
                        }).join('')}</tbody>
                    </table>`;
            } catch (err) {
                detailRow.querySelector('.batch-lines-detail').innerHTML =
                    `<p style="color:var(--danger)">Error de conexión</p>`;
            }
        }

        // Guardar match (reutiliza la misma lógica que batch). Input =
        // id_erp o referencia (nunca id autoincrement — política 10r).
        const saveBtn = e.target.closest('.batch-line-save');
        if (saveBtn) {
            const tr = saveBtn.closest('tr');
            const input = tr.querySelector('.batch-art-id');
            const userQuery = (input.value || '').trim();
            if (!userQuery) { alert('Introduce un id_erp o referencia'); return; }
            const synKey = tr.dataset.synKey;

            try {
                const lookupResp = await fetch(`api.php?action=lookup_article&q=${encodeURIComponent(userQuery)}`);
                const lookupData = await lookupResp.json();
                if (!lookupData.ok) { alert(lookupData.error); return; }

                const saveResp = await fetch('api.php?action=save_synonym', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        key: synKey,
                        articulo_id_erp: lookupData.id_erp,
                        articulo_id: lookupData.id,
                        articulo_name: lookupData.nombre,
                    }),
                });
                const saveData = await saveResp.json();
                if (saveData.ok) {
                    const cells = tr.querySelectorAll('td');
                    cells[5].textContent = lookupData.id;
                    cells[6].textContent = lookupData.nombre;
                    cells[7].innerHTML = '<span class="badge badge-manual">manual-web</span>';
                    tr.classList.remove('row-sin-match');
                    cells[cells.length - 1].innerHTML = '<span style="color:green">&#10003;</span>';
                } else {
                    alert('Error: ' + saveData.error);
                }
            } catch (err) { alert('Error de conexión'); }
        }
    });

    // --- Synonyms Tab ---
    // === SINÓNIMOS — MASTER-DETAIL ===
    let allSynonyms = [];
    let synActiveRow = null;
    let synActiveSyn = null;
    let synSortField = 'variety';
    let synSortAsc = true;
    const pn = id => (window.PROVIDER_NAMES || {})[id] || ('ID:'+id);

    async function loadSynonyms() {
        document.getElementById('synLoading').classList.remove('hidden');
        try {
            const resp = await fetch('api.php?action=synonyms', { method: 'POST' });
            const data = await resp.json();
            document.getElementById('synLoading').classList.add('hidden');
            if (!data.ok) return;
            allSynonyms = data.synonyms;
            synUpdateKPIs();
            synRenderTable();
        } catch (err) {
            document.getElementById('synLoading').classList.add('hidden');
        }
    }

    function synUpdateKPIs() {
        document.getElementById('synKpiTotal').textContent = allSynonyms.length;
        document.getElementById('synKpiRevisado').textContent = allSynonyms.filter(s => ['manual','manual-web','revisado','manual-batch'].includes(s.origen)).length;
        document.getElementById('synKpiAutoFuzzy').textContent = allSynonyms.filter(s => s.origen === 'auto-fuzzy').length;
        document.getElementById('synKpiProviders').textContent = new Set(allSynonyms.map(s => s.provider_id)).size;
    }

    function synOriginBadge(origin) {
        const cls = ['manual','manual-web','revisado','manual-batch'].includes(origin) ? 'badge-manual' :
                    origin.includes('fuzzy') ? 'badge-fuzzy' :
                    origin.includes('marca') ? 'badge-marca' : 'badge-auto';
        return `<span class="badge ${cls}">${esc(origin)}</span>`;
    }

    function synRenderTable() {
        const q = document.getElementById('synFilter').value.trim().toLowerCase();
        const fo = document.getElementById('synOriginFilter').value;
        const fs = document.getElementById('synSpeciesFilter').value;
        const filtered = allSynonyms.filter(s => {
            if (fo && s.origen !== fo) return false;
            if (fs && s.species !== fs) return false;
            if (q) {
                const hay = [s.variety, s.articulo_name, pn(s.provider_id), s.invoice||'', s.raw||'']
                    .some(f => (f||'').toLowerCase().includes(q));
                if (!hay) return false;
            }
            return true;
        });
        const tbody = document.querySelector('#synTable tbody');
        tbody.innerHTML = '';
        filtered.forEach(s => {
            const tr = document.createElement('tr');
            tr.dataset.key = s.key;
            tr.innerHTML = `
                <td>${pn(s.provider_id)}</td>
                <td><strong>${esc(s.variety)}</strong></td>
                <td>${s.species}</td>
                <td>${s.size || '-'}</td>
                <td title="${esc(s.articulo_name)}">${esc(s.articulo_name)}</td>
                <td>${synOriginBadge(s.origen || '')}</td>
                <td>${esc(s.invoice || '')}</td>`;
            tr.addEventListener('click', () => synOpenDetail(s, tr));
            tbody.appendChild(tr);
        });
        document.getElementById('synCount').textContent = `${filtered.length} de ${allSynonyms.length}`;
        document.getElementById('synTableInfo').textContent = `${filtered.length} resultados`;
    }

    function synOpenDetail(syn, row) {
        if (synActiveRow) synActiveRow.classList.remove('row-active');
        synActiveRow = row; synActiveSyn = syn;
        row.classList.add('row-active');
        document.getElementById('synWorkspace').classList.add('detail-open');
        document.getElementById('synDetailTitle').textContent = syn.variety;
        document.getElementById('synDetailSub').textContent = `${pn(syn.provider_id)} — ${syn.species}`;
        document.getElementById('synDetailBody').innerHTML = `
            <div class="syn-detail-grid">
                <div class="syn-detail-field"><label>Proveedor</label><input readonly value="${esc(pn(syn.provider_id))} (${syn.provider_id})"/></div>
                <div class="syn-detail-field"><label>Factura</label><input readonly value="${esc(syn.invoice||'—')}"/></div>
                <div class="syn-detail-field"><label>Variedad</label><input readonly value="${esc(syn.variety)}"/></div>
                <div class="syn-detail-field"><label>Especie</label><input readonly value="${syn.species}"/></div>
                <div class="syn-detail-field"><label>Talla</label><input readonly value="${syn.size||'—'}"/></div>
                <div class="syn-detail-field"><label>SPB</label><input readonly value="${syn.stems_per_bunch||'—'}"/></div>
                <div class="syn-detail-field"><label>Origen</label><input readonly value="${syn.origen}"/></div>
                <div class="syn-detail-field"><label>Grade</label><input readonly value="${syn.grade||'—'}"/></div>
                <div class="syn-detail-field full"><label>Línea raw factura</label><textarea readonly rows="2">${esc(syn.raw||'')}</textarea></div>
            </div>
            <hr style="border-color:var(--border);margin:12px 0"/>
            <div class="syn-detail-grid">
                <div class="syn-detail-field"><label>ID Artículo actual</label><input readonly value="${syn.articulo_id}"/></div>
                <div class="syn-detail-field full"><label>Artículo actual</label><input readonly value="${esc(syn.articulo_name)}"/></div>
                <div class="syn-detail-field"><label>Nuevo artículo (id_erp o ref)</label><input type="text" id="synNewArtId" placeholder="id_erp o F000..." title="id_erp o referencia (F...). El id autoincrement no se acepta."/></div>
                <div class="syn-detail-field"><label>Nombre (auto)</label><input id="synNewArtName" readonly placeholder="Se rellena al buscar"/></div>
            </div>
            <div class="syn-detail-actions">
                <button class="syn-btn-lookup" onclick="synDoLookup()">Buscar</button>
                <button class="syn-btn-del" onclick="synDoDelete()">Borrar</button>
                <button class="syn-btn-ok" onclick="synDoMarkOk()">Marcar OK</button>
                <button class="syn-btn-save" onclick="synDoSave()">Guardar cambio</button>
            </div>`;
        synBindEnterKey();
    }

    function synCloseDetail() {
        if (synActiveRow) synActiveRow.classList.remove('row-active');
        synActiveRow = null; synActiveSyn = null;
        document.getElementById('synWorkspace').classList.remove('detail-open');
    }

    // Bind Enter key on new art ID field after detail opens.
    // El input acepta id_erp o referencia — NUNCA id autoincrement (10r).
    function synBindEnterKey() {
        const input = document.getElementById('synNewArtId');
        if (!input) return;
        input.addEventListener('keydown', async (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                const q = (input.value || '').trim();
                if (!q) return;
                const r = await fetch(`api.php?action=lookup_article&q=${encodeURIComponent(q)}`);
                const d = await r.json();
                document.getElementById('synNewArtName').value = d.ok && d.nombre ? d.nombre : '(no encontrado)';
                // Cache del lookup — lo usará synDoSave.
                input.dataset.resolvedIdErp = d.ok ? (d.id_erp || '') : '';
                input.dataset.resolvedId = d.ok ? (d.id || '') : '';
                if (d.ok && d.nombre) {
                    await synDoSave();
                }
            }
        });
    }

    // Detail actions (global scope for onclick)
    window.synDoLookup = async function() {
        const input = document.getElementById('synNewArtId');
        const q = (input.value || '').trim();
        if (!q) return;
        const r = await fetch(`api.php?action=lookup_article&q=${encodeURIComponent(q)}`);
        const d = await r.json();
        document.getElementById('synNewArtName').value = d.ok && d.nombre ? d.nombre : '(no encontrado)';
        input.dataset.resolvedIdErp = d.ok ? (d.id_erp || '') : '';
        input.dataset.resolvedId = d.ok ? (d.id || '') : '';
    };

    window.synDoSave = async function() {
        const input = document.getElementById('synNewArtId');
        const q = (input.value || '').trim();
        if (!q) { alert('Introduce un id_erp o referencia'); return; }
        // Usar el lookup cacheado si existe, si no lanzar uno nuevo.
        let idErp = input.dataset.resolvedIdErp || '';
        let nid = parseInt(input.dataset.resolvedId || '0', 10) || 0;
        let nm = document.getElementById('synNewArtName').value;
        if (!idErp || nm === '(no encontrado)' || !nm) {
            const r = await fetch(`api.php?action=lookup_article&q=${encodeURIComponent(q)}`);
            const d = await r.json();
            if (!d.ok) { alert(d.error || 'Artículo no encontrado'); return; }
            idErp = d.id_erp || '';
            nid = d.id;
            nm = d.nombre;
            document.getElementById('synNewArtName').value = nm;
        }
        const oldArtId = synActiveSyn.articulo_id || 0;
        const body = { key: synActiveSyn.key, old_articulo_id: oldArtId,
            new_articulo_id_erp: idErp,
            new_articulo_id: nid,
            new_articulo_name: nm,
            provider_id: synActiveSyn.provider_id, species: synActiveSyn.species,
            variety: synActiveSyn.variety, size: synActiveSyn.size,
            stems_per_bunch: synActiveSyn.stems_per_bunch, grade: synActiveSyn.grade || '' };
        const r = await fetch('api.php?action=correct_match', {
            method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
        const d = await r.json();
        if (d.ok) {
            synActiveSyn.articulo_id = nid;
            synActiveSyn.articulo_id_erp = idErp;
            synActiveSyn.articulo_name = nm;
            synActiveSyn.origen = 'manual-web'; synUpdateKPIs(); synRenderTable();
        } else { alert(d.error || 'Error'); }
    };

    window.synDoDelete = async function() {
        if (!confirm('¿Eliminar sinónimo?')) return;
        const r = await fetch('api.php?action=delete_synonym', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ key: synActiveSyn.key }) });
        const d = await r.json();
        if (d.ok) { allSynonyms = allSynonyms.filter(s => s.key !== synActiveSyn.key);
            synCloseDetail(); synUpdateKPIs(); synRenderTable(); }
        else { alert(d.error || 'Error'); }
    };

    window.synDoMarkOk = async function() {
        const body = { key: synActiveSyn.key, articulo_id: synActiveSyn.articulo_id };
        const r = await fetch('api.php?action=confirm_match', {
            method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
        const d = await r.json();
        if (d.ok) { synActiveSyn.status = d.new_status; synActiveSyn.times_confirmed = d.times_confirmed;
            synUpdateKPIs(); synRenderTable(); }
        else { alert(d.error || 'Error'); }
    };

    // Sort
    document.querySelectorAll('#synTable th[data-sort]').forEach(th => {
        th.addEventListener('click', () => {
            const f = th.dataset.sort;
            if (synSortField === f) synSortAsc = !synSortAsc;
            else { synSortField = f; synSortAsc = true; }
            allSynonyms.sort((a, b) => {
                let va = a[f] ?? '', vb = b[f] ?? '';
                if (typeof va === 'number') return synSortAsc ? va - vb : vb - va;
                va = String(va).toLowerCase(); vb = String(vb).toLowerCase();
                return synSortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
            });
            synRenderTable();
        });
    });

    // Filters
    document.getElementById('synFilter').addEventListener('input', synRenderTable);
    document.getElementById('synOriginFilter').addEventListener('change', synRenderTable);
    document.getElementById('synSpeciesFilter').addEventListener('change', synRenderTable);
    document.getElementById('synClearFilters').addEventListener('click', () => {
        document.getElementById('synFilter').value = '';
        document.getElementById('synOriginFilter').value = '';
        document.getElementById('synSpeciesFilter').value = '';
        synRenderTable();
    });
    document.getElementById('synCloseDetail').addEventListener('click', synCloseDetail);

    // --- Add synonym ---
    document.getElementById('btnAddSynonym').addEventListener('click', () => {
        document.getElementById('synAddForm').classList.toggle('hidden');
    });
    document.getElementById('btnSynAddCancel').addEventListener('click', () => {
        document.getElementById('synAddForm').classList.add('hidden');
    });
    // Formulario de alta manual de sinónimo. El input `synAddArticuloId`
    // acepta id_erp o referencia (política 10r).
    document.getElementById('synAddArticuloId').addEventListener('change', async () => {
        const input = document.getElementById('synAddArticuloId');
        const q = (input.value || '').trim();
        if (!q) return;
        try {
            const res = await fetch(`api.php?action=lookup_article&q=${encodeURIComponent(q)}`);
            const data = await res.json();
            if (data.ok) {
                document.getElementById('synAddArticuloName').value = data.nombre;
                input.dataset.resolvedIdErp = data.id_erp || '';
                input.dataset.resolvedId = data.id || '';
            } else {
                document.getElementById('synAddArticuloName').value = '(no encontrado)';
                input.dataset.resolvedIdErp = '';
                input.dataset.resolvedId = '';
            }
        } catch (err) {}
    });
    document.getElementById('btnSynAddSave').addEventListener('click', async () => {
        const key = document.getElementById('synAddKey').value.trim();
        const input = document.getElementById('synAddArticuloId');
        const q = (input.value || '').trim();
        const artName = document.getElementById('synAddArticuloName').value.trim();
        if (!key || !q) { alert('Clave e id_erp/referencia son obligatorios'); return; }
        let idErp = input.dataset.resolvedIdErp || '';
        let artId = parseInt(input.dataset.resolvedId || '0', 10) || 0;
        if (!idErp || !artId) {
            // Resolver ahora si no se cacheó
            try {
                const res = await fetch(`api.php?action=lookup_article&q=${encodeURIComponent(q)}`);
                const d = await res.json();
                if (!d.ok) { alert(d.error || 'Artículo no encontrado'); return; }
                idErp = d.id_erp || '';
                artId = d.id;
            } catch (err) { alert('Error de conexión'); return; }
        }
        try {
            const res = await fetch('api.php?action=save_synonym', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key,
                    articulo_id_erp: idErp,
                    articulo_id: artId,
                    articulo_name: artName }) });
            const data = await res.json();
            if (data.ok) {
                document.getElementById('synAddForm').classList.add('hidden');
                document.getElementById('synAddKey').value = '';
                document.getElementById('synAddArticuloId').value = '';
                document.getElementById('synAddArticuloName').value = '';
                input.dataset.resolvedIdErp = '';
                input.dataset.resolvedId = '';
                loadSynonyms();
            } else { alert('Error: ' + data.error); }
        } catch (err) { alert('Error de conexión'); }
    });

    // --- Utilities ---
    function esc(str) {
        const div = document.createElement('div');
        div.textContent = str || '';
        return div.innerHTML;
    }

    function num(val) {
        if (val === null || val === undefined) return '0.00';
        return Number(val).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 5 });
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // IMPORTACIÓN MASIVA
    // ═══════════════════════════════════════════════════════════════════════════

    const batchDropZone   = document.getElementById('batchDropZone');
    const batchZipInput   = document.getElementById('batchZipInput');
    const batchFolderInput = document.getElementById('batchFolderInput');
    const batchPdfInput   = document.getElementById('batchPdfInput');
    const batchUploadZone = document.getElementById('batch-upload-zone');
    const batchProgress   = document.getElementById('batch-progress');
    const batchResults    = document.getElementById('batch-results');

    let batchId = null;
    let batchPollingTimer = null;
    let batchAllResults = [];

    // Drag & drop — acepta ZIP, PDFs sueltos o carpetas
    if (batchDropZone) {
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
                if (pdfs.length > 0) {
                    batchUploadPdfs(pdfs);
                } else {
                    alert('Arrastra archivos PDF o un ZIP');
                }
            }
        });
    }

    // Botón ZIP
    document.getElementById('btnSelectZip').addEventListener('click', e => {
        e.preventDefault();
        e.stopPropagation();
        batchZipInput.click();
    });
    batchZipInput.addEventListener('change', () => {
        if (batchZipInput.files[0]) batchUploadZip(batchZipInput.files[0]);
    });

    // Botón Carpeta
    document.getElementById('btnSelectFolder').addEventListener('click', e => {
        e.preventDefault();
        e.stopPropagation();
        batchFolderInput.click();
    });
    batchFolderInput.addEventListener('change', () => {
        const pdfs = [...batchFolderInput.files].filter(f => f.name.toLowerCase().endsWith('.pdf'));
        if (pdfs.length > 0) {
            batchUploadPdfs(pdfs);
        } else {
            alert('La carpeta no contiene archivos PDF');
        }
    });

    // Botón PDFs sueltos
    document.getElementById('btnSelectPdfs').addEventListener('click', e => {
        e.preventDefault();
        e.stopPropagation();
        batchPdfInput.click();
    });
    batchPdfInput.addEventListener('change', () => {
        const pdfs = [...batchPdfInput.files];
        if (pdfs.length > 0) batchUploadPdfs(pdfs);
    });

    async function batchUploadZip(file) {
        if (!file.name.toLowerCase().endsWith('.zip')) {
            alert('Selecciona un archivo .zip');
            return;
        }

        // Mostrar progreso
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

            if (!data.ok) {
                alert('Error: ' + data.error);
                batchReset();
                return;
            }

            batchId = data.batch_id;
            document.getElementById('batch-status-text').textContent = 'Procesando...';
            document.getElementById('batch-progress-count').textContent = `0 / ${data.total_pdfs}`;

            // Iniciar polling
            batchPollingTimer = setInterval(batchPollStatus, 2000);

        } catch (err) {
            alert('Error de conexión: ' + err.message);
            batchReset();
        }
    }

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
        for (const f of files) {
            form.append('pdfs[]', f);
        }

        try {
            const res = await fetch('api.php?action=batch_upload_pdfs', { method: 'POST', body: form });
            const data = await res.json();

            if (!data.ok) {
                alert('Error: ' + data.error);
                batchReset();
                return;
            }

            batchId = data.batch_id;
            document.getElementById('batch-status-text').textContent = 'Procesando...';
            document.getElementById('batch-progress-count').textContent = `0 / ${data.total_pdfs}`;

            batchPollingTimer = setInterval(batchPollStatus, 2000);

        } catch (err) {
            alert('Error de conexión: ' + err.message);
            batchReset();
        }
    }

    async function batchPollStatus() {
        if (!batchId) return;

        try {
            const res = await fetch(`api.php?action=batch_status&batch_id=${batchId}`);
            const data = await res.json();

            if (!data.ok && data.error) {
                clearInterval(batchPollingTimer);
                alert('Error: ' + data.error);
                batchReset();
                return;
            }

            // Actualizar barra
            const pct = data.porcentaje || 0;
            document.getElementById('batchProgressBar').style.width = pct + '%';
            document.getElementById('batch-progress-count').textContent =
                `${data.progreso || 0} / ${data.total || 0}`;
            document.getElementById('batch-current-pdf').textContent = data.actual || '';
            document.getElementById('batch-ok-err').textContent =
                `OK: ${data.procesados_ok || 0} | Errores: ${data.con_error || 0}`;

            const statusMap = {
                'iniciando': 'Iniciando...',
                'cargando_datos': 'Cargando artículos y sinónimos...',
                'procesando': 'Procesando facturas...',
                'generando_excel': 'Generando Excel...',
            };
            document.getElementById('batch-status-text').textContent =
                statusMap[data.estado] || data.estado;

            // ¿Completado?
            if (data.estado === 'completado') {
                clearInterval(batchPollingTimer);
                batchShowResults(data);
            } else if (data.estado === 'error') {
                clearInterval(batchPollingTimer);
                alert('Error en el procesamiento: ' + (data.error || 'desconocido'));
                batchReset();
            }

        } catch (err) {
            // Silenciar errores de red durante polling
        }
    }

    function batchShowResults(data) {
        batchProgress.classList.add('hidden');
        batchResults.classList.remove('hidden');

        const r = data.resumen;
        batchAllResults = data.resultados || [];

        // Tarjetas resumen
        const tNeeds = r.total_needs_review || 0;
        const tAnom  = r.total_anomalies || 0;
        const tNoCuadra = r.total_no_cuadra || 0;
        const tOmit  = r.omitidos || 0;
        document.getElementById('batchSummary').innerHTML = `
            <div class="stat-card success">
                <div class="stat-value">${r.total_facturas}</div>
                <div class="stat-label">Facturas</div>
            </div>
            <div class="stat-card success">
                <div class="stat-value">${r.procesadas_ok}</div>
                <div class="stat-label">Procesadas</div>
            </div>
            ${r.con_error > 0 ? `<div class="stat-card danger">
                <div class="stat-value">${r.con_error}</div>
                <div class="stat-label">Con Error</div>
            </div>` : ''}
            ${tOmit > 0 ? `<div class="stat-card warning"
                 title="Documentos descartados por nombre (no son facturas de proveedor): DUA, guías, manifiestos, pre-alertas…">
                <div class="stat-value">${tOmit}</div>
                <div class="stat-label">Omitidos</div>
            </div>` : ''}
            <div class="stat-card primary">
                <div class="stat-value">${r.total_lineas}</div>
                <div class="stat-label">Líneas</div>
            </div>
            <div class="stat-card success">
                <div class="stat-value">${r.total_ok}</div>
                <div class="stat-label">Matcheadas</div>
            </div>
            ${r.total_sin_match > 0 ? `<div class="stat-card danger">
                <div class="stat-value">${r.total_sin_match}</div>
                <div class="stat-label">Sin Match</div>
            </div>` : ''}
            <div class="stat-card ${tNeeds > 0 ? 'warning' : 'success'}"
                 title="Líneas que requieren revisión manual (sin match, confianza baja o errores de validación).">
                <div class="stat-value">${tNeeds}</div>
                <div class="stat-label">A Revisar</div>
            </div>
            ${tNoCuadra > 0 ? `<div class="stat-card danger"
                 title="Facturas donde la suma de líneas NO cuadra con el total declarado en cabecera (±1%).">
                <div class="stat-value">${tNoCuadra}</div>
                <div class="stat-label">No Cuadran</div>
            </div>` : ''}
            ${tAnom > 0 ? `<div class="stat-card danger"
                 title="Precios con desviación >15% respecto al histórico del proveedor.">
                <div class="stat-value">${tAnom}</div>
                <div class="stat-label">Precio Anómalo</div>
            </div>` : ''}
            <div class="stat-card primary">
                <div class="stat-value">$${Number(r.total_usd).toLocaleString('en-US', {minimumFractionDigits: 2})}</div>
                <div class="stat-label">Total USD</div>
            </div>
        `;

        // Desglose expandible de archivos omitidos y con error. Explica por
        // qué solo se procesa 1 de 7 cuando el resto son DUAs, guías, etc.
        const skippedDetails = document.getElementById('batchSkippedDetails');
        const skippedContent = document.getElementById('batchSkippedContent');
        const omitList = data.omitidos_detalle || [];
        const errList  = data.errores || [];
        if ((omitList.length + errList.length) > 0) {
            let html = '';
            if (omitList.length > 0) {
                html += `<div class="batch-skipped-section">
                    <h4>Omitidos (${omitList.length}) — no se consideran facturas</h4>
                    <ul>${omitList.map(o =>
                        `<li><code>${esc(o.pdf)}</code> — ${esc(o.motivo)}</li>`
                    ).join('')}</ul>
                    <p class="batch-skipped-hint">El filtro automático descarta documentos cuyo nombre indica que son guías, DUAs, pre-alertas, manifiestos de carga, etc. Si crees que algún archivo se filtró por error, renómbralo antes de subirlo.</p>
                </div>`;
            }
            if (errList.length > 0) {
                html += `<div class="batch-skipped-section">
                    <h4>Con error (${errList.length})</h4>
                    <ul>${errList.map(e =>
                        `<li><code>${esc(e.pdf)}</code> — ${esc(e.error)}</li>`
                    ).join('')}</ul>
                </div>`;
            }
            skippedContent.innerHTML = html;
            skippedDetails.classList.remove('hidden');
        } else {
            skippedDetails.classList.add('hidden');
        }

        // Llenar filtro de facturas
        const sel = document.getElementById('batchFilterInvoice');
        sel.innerHTML = '<option value="">Todas las facturas</option>';
        batchAllResults.forEach(r => {
            if (r.ok) {
                sel.innerHTML += `<option value="${esc(r.pdf)}">${esc(r.pdf)} — ${esc(r.provider)}</option>`;
            }
        });

        batchRenderTable(batchAllResults);
    }

    function batchRenderTable(list) {
        const tbody = document.querySelector('#batchTable tbody');
        tbody.innerHTML = list.map((r, i) => {
            const needsRev = r.needs_review || 0;
            const val = r.validation || {};
            const rec = r.reconciliation || {};
            const noCuadra = val.header_ok === false;
            const anomalies = rec.anomalies || 0;
            let status, statusClass;
            if (!r.ok) {
                status = 'ERROR'; statusClass = 'badge badge-sin-match';
            } else if (r.sin_match > 0 || needsRev > 0 || noCuadra || anomalies > 0) {
                status = 'REVISAR'; statusClass = 'badge badge-fuzzy';
            } else {
                status = 'OK'; statusClass = 'badge badge-ok';
            }
            const hasLines = r.ok && r.lines && r.lines.length > 0;
            const showActions = hasLines;
            const rowId = `batch-lines-${i}`;

            // Fila padre: roja si error, ámbar si necesita revisión, verde limpia si OK
            let parentCls = '';
            if (!r.ok) parentCls = 'row-sin-match';
            else if (status === 'REVISAR') parentCls = 'row-low-conf';

            // Mini avisos junto al total si algo no cuadra
            const totalWarn = [];
            if (noCuadra && val.header_diff) {
                const sign = val.header_diff >= 0 ? '+' : '';
                totalWarn.push(`<span class="conf-dot dot-err" title="Suma líneas - total cabecera = ${sign}${val.header_diff.toFixed(2)} USD">!</span>`);
            }
            if (anomalies > 0) {
                totalWarn.push(`<span class="conf-dot dot-price" title="${anomalies} precio(s) con desviación >15% vs histórico">$</span>`);
            }

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
                    <td>$${num(r.total_usd || 0)} ${totalWarn.join('')}</td>
                    <td><span class="${statusClass}">${status}</span>${!r.ok ? `<br><small>${esc(r.error)}</small>` : ''}</td>
                </tr>`;

            // Fila expandible con líneas de detalle
            if (hasLines) {
                html += `<tr id="${rowId}" class="batch-lines-row hidden">
                    <td colspan="11">
                        <div class="batch-lines-detail">
                            <table class="batch-lines-table">
                                <thead><tr>
                                    <th>Descripción</th><th>Variedad</th><th>Talla</th>
                                    <th>Tallos</th><th>Total</th>
                                    <th>ID Artículo</th><th>Nombre Artículo</th>
                                    <th>Match</th>${showActions ? '<th>Acción</th>' : ''}
                                </tr></thead>
                                <tbody>${r.lines.map((l, li) => _batchLineRow(l, r, showActions, i, li)).join('')}</tbody>
                            </table>
                        </div>
                    </td>
                </tr>`;
            }
            return html;
        }).join('');
    }

    function _batchLineRow(l, invoiceResult, showActions, invoiceIdx, lineIdx) {
        const hasErrors = l.validation_errors && l.validation_errors.length > 0;
        const needsRev = l.needs_review === true;
        let cls = '';
        if (l.match_status === 'sin_parser') cls = 'row-sin-parser';
        else if (l.match_status !== 'ok') cls = 'row-sin-match';
        else if (hasErrors) cls = 'row-has-error';
        else if (needsRev) cls = 'row-low-conf';
        const key = `${invoiceResult.provider_id || 0}|${l.species || ''}|${_normalizeVariety(l.variety)}|${l.size || 0}|${l.stems_per_bunch || 0}|${(l.grade || '').toUpperCase()}`;
        const currentId = l.articulo_id ? l.articulo_id : '';
        // El input al operador se prellena con id_erp (clave estable);
        // el id local nunca se muestra como input en ese campo.
        const currentIdErp = l.articulo_id_erp || '';
        // Dot de error si hay errores de validación en la línea
        const errDot = hasErrors
            ? ` <span class="conf-dot dot-err" title="${esc(l.validation_errors.join(' · '))}">!</span>`
            : '';
        return `
            <tr class="${cls}" data-syn-key="${esc(key)}" data-pdf="${esc(invoiceResult.pdf)}" data-invoice-idx="${invoiceIdx}" data-line-idx="${lineIdx}">
                <td title="${esc(l.raw || '')}">${esc((l.raw || '').substring(0, 50))}${(l.raw || '').length > 50 ? '...' : ''}${errDot}</td>
                <td><strong>${esc(l.variety || '')}</strong></td>
                <td>${l.size || '-'}</td>
                <td>${l.stems || '-'}</td>
                <td>$${num(l.line_total || 0)}</td>
                <td>${l.articulo_id || '-'}</td>
                <td>${esc(l.articulo_name || '-')}</td>
                <td>${matchBadge(l.match_status || '', l.match_method || '')}${confBadge(l.match_confidence)}</td>
                ${showActions ? `<td style="white-space:nowrap">
                    <input type="text" class="edit-input batch-art-id" placeholder="id_erp/ref" title="id_erp o referencia (F...). El id autoincrement NO se acepta." style="width:90px" value="${currentIdErp || ''}">
                    <button class="btn-icon batch-line-save" title="Guardar">&#10003;</button>
                    <button class="btn-icon batch-line-delete" title="Eliminar línea" style="color:var(--danger);font-size:14px;vertical-align:middle">&#10005;</button>
                </td>` : ''}
            </tr>`;
    }

    // Recalcula los contadores (lineas/ok/sin_match) de la fila padre de una
    // factura tras añadir o eliminar líneas en su detalle.
    function _batchRecalcInvoiceCounts(invoiceIdx) {
        const r = batchAllResults[invoiceIdx];
        if (!r || !r.lines) return;
        const live = r.lines.filter(l => !l._deleted);
        r.lineas    = live.length;
        r.ok_count  = live.filter(l => l.match_status === 'ok').length;
        r.sin_match = live.length - r.ok_count;
        // Actualizar las celdas correspondientes en la fila padre del DOM
        const parentRow = document.querySelector(`#batchTable tbody tr[data-target="batch-lines-${invoiceIdx}"]`);
        if (parentRow) {
            const cells = parentRow.querySelectorAll('td');
            // [0]=#, [1]=pdf, [2]=prov, [3]=invoice, [4]=date,
            // [5]=lineas, [6]=ok, [7]=sin_match, [8]=revisar, [9]=total, [10]=estado
            cells[5].textContent = r.lineas;
            cells[6].textContent = r.ok_count;
            cells[7].textContent = r.sin_match;
        }
    }

    // Expandir/colapsar líneas de factura
    document.querySelector('#batchTable tbody').addEventListener('click', e => {
        const expandRow = e.target.closest('.batch-expandable');
        if (expandRow
                && !e.target.closest('.batch-line-save')
                && !e.target.closest('.batch-line-delete')
                && !e.target.closest('input')) {
            const targetId = expandRow.dataset.target;
            const linesRow = document.getElementById(targetId);
            if (linesRow) {
                linesRow.classList.toggle('hidden');
                const arrow = expandRow.querySelector('.expand-arrow');
                if (arrow) arrow.innerHTML = linesRow.classList.contains('hidden') ? '&#9654;' : '&#9660;';
            }
        }

        // Eliminar línea de batch
        const delBtn = e.target.closest('.batch-line-delete');
        if (delBtn) {
            const tr = delBtn.closest('tr');
            const invoiceIdx = parseInt(tr.dataset.invoiceIdx);
            const lineIdx    = parseInt(tr.dataset.lineIdx);
            if (!Number.isNaN(invoiceIdx) && !Number.isNaN(lineIdx)
                    && batchAllResults[invoiceIdx]
                    && batchAllResults[invoiceIdx].lines[lineIdx]) {
                batchAllResults[invoiceIdx].lines[lineIdx]._deleted = true;
            }
            tr.remove();
            _batchRecalcInvoiceCounts(invoiceIdx);
            return;
        }

        // Guardar match desde línea de batch.
        // POLÍTICA 10r: el input del operador es id_erp o referencia
        // (nunca id autoincrement — se renumera al reimportar el
        // catálogo y causa asignaciones erróneas). El backend resuelve
        // el id local internamente.
        //
        // Enruta según la comparación con el artículo previo:
        //   - mismo id_erp              → confirm_match
        //   - había propuesta y cambia  → correct_match (shadow: correct)
        //   - no había propuesta        → save_synonym (shadow: rescue)
        const saveBtn = e.target.closest('.batch-line-save');
        if (saveBtn) {
            const tr = saveBtn.closest('tr');
            const input = tr.querySelector('.batch-art-id');
            const userQuery = (input.value || '').trim();
            if (!userQuery) { alert('Introduce un id_erp o referencia (ej. F000636001)'); return; }
            const synKey = tr.dataset.synKey;
            const pdf = tr.dataset.pdf;
            const invoiceIdx = parseInt(tr.dataset.invoiceIdx);
            const lineIdx = parseInt(tr.dataset.lineIdx);
            const line = batchAllResults[invoiceIdx] && batchAllResults[invoiceIdx].lines && batchAllResults[invoiceIdx].lines[lineIdx];
            const oldArtIdErp = line ? (line.articulo_id_erp || '') : '';
            const providerId = batchAllResults[invoiceIdx] && batchAllResults[invoiceIdx].provider_id || 0;

            // Resolver el input (id_erp|ref) → artículo completo. Esto
            // valida la existencia y captura id_erp/id/nombre de un solo
            // golpe; luego elegimos action según coincida o no con el
            // artículo previo.
            fetch(`api.php?action=lookup_article&q=${encodeURIComponent(userQuery)}`)
                .then(r => r.json())
                .then(data => {
                    if (!data.ok) { alert(data.error); return null; }
                    const newArtId = data.id;
                    const newArtIdErp = data.id_erp || '';
                    const name = data.nombre;

                    // Caso rápido: mismo artículo que el propuesto → confirm.
                    if (oldArtIdErp && oldArtIdErp === newArtIdErp) {
                        return fetch('api.php?action=confirm_match', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                key: synKey,
                                articulo_id: newArtId,
                                articulo_id_erp: newArtIdErp,
                            }),
                        }).then(r => r.json()).then(resp => ({ resp, name, newArtId, newArtIdErp, action: 'confirm' }));
                    }

                    const baseBody = {
                        key: synKey, provider_id: providerId,
                        species: line && line.species || '',
                        variety: line && line.variety || '',
                        size: line && line.size || 0,
                        stems_per_bunch: line && line.stems_per_bunch || 0,
                        grade: line && line.grade || '',
                    };
                    let action, body;
                    if (oldArtIdErp && oldArtIdErp !== newArtIdErp) {
                        action = 'correct_match';
                        body = { ...baseBody,
                            old_articulo_id: line ? (line.articulo_id || 0) : 0,
                            new_articulo_id_erp: newArtIdErp,
                            new_articulo_id: newArtId,
                            new_articulo_name: name };
                    } else {
                        action = 'save_synonym';
                        body = { ...baseBody,
                            articulo_id_erp: newArtIdErp,
                            articulo_id: newArtId,
                            articulo_name: name };
                    }
                    return fetch(`api.php?action=${action}`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body),
                    }).then(r => r.json()).then(resp => ({ resp, name, newArtId, newArtIdErp, action }));
                })
                .then(result => {
                    if (!result) return;
                    const { resp: data, name, newArtId, newArtIdErp, action } = result;
                    if (data && data.ok) {
                        // Feedback visual distinto para confirm vs correct/save.
                        const orig = saveBtn.innerHTML;
                        if (action === 'confirm') {
                            saveBtn.innerHTML = '<span style="color:green">&#10003;&#10003;</span>';
                            saveBtn.title = `Confirmado (${data.times_confirmed}x)`;
                        } else {
                            saveBtn.innerHTML = '<span style="color:green">&#10003;</span>';
                            // Actualizar celdas — preserva el input por si
                            // hay que volver a corregir.
                            const cells = tr.querySelectorAll('td');
                            cells[5].textContent = newArtId;
                            cells[6].textContent = name;
                            cells[7].innerHTML = '<span class="badge badge-manual">manual-web</span>';
                            tr.classList.remove('row-sin-match');
                            if (line) {
                                line.articulo_id = newArtId;
                                line.articulo_id_erp = newArtIdErp;
                                line.articulo_name = name;
                                line.match_status = 'ok';
                            }
                        }
                        saveBtn.disabled = true;
                        setTimeout(() => {
                            saveBtn.innerHTML = orig;
                            saveBtn.disabled = false;
                            saveBtn.title = 'Guardar';
                        }, 1200);
                    } else if (data) {
                        alert('Error: ' + data.error);
                    }
                })
                .catch(err => alert('Error de conexión'));
        }
    });

    // Filtros batch
    function batchFilter() {
        const invFilter  = document.getElementById('batchFilterInvoice').value;
        const statFilter = document.getElementById('batchFilterStatus').value;
        const textFilter = document.getElementById('batchFilterText').value.toLowerCase();

        let filtered = batchAllResults;

        if (invFilter) {
            filtered = filtered.filter(r => r.pdf === invFilter);
        }
        if (statFilter) {
            filtered = filtered.filter(r => {
                if (statFilter === 'ok') return r.ok && r.sin_match === 0;
                if (statFilter === 'parcial') return r.ok && r.sin_match > 0;
                if (statFilter === 'error') return !r.ok;
                return true;
            });
        }
        if (textFilter) {
            filtered = filtered.filter(r =>
                (r.pdf || '').toLowerCase().includes(textFilter) ||
                (r.provider || '').toLowerCase().includes(textFilter) ||
                (r.invoice || '').toLowerCase().includes(textFilter)
            );
        }

        batchRenderTable(filtered);
    }

    document.getElementById('batchFilterInvoice').addEventListener('change', batchFilter);
    document.getElementById('batchFilterStatus').addEventListener('change', batchFilter);
    document.getElementById('batchFilterText').addEventListener('input', batchFilter);

    // Botones
    document.getElementById('btnBatchExcel').addEventListener('click', () => {
        if (batchId) {
            window.location.href = `api.php?action=batch_download&batch_id=${batchId}`;
        }
    });

    document.getElementById('btnBatchNew').addEventListener('click', () => {
        batchReset();
    });

    function batchReset() {
        batchId = null;
        if (batchPollingTimer) clearInterval(batchPollingTimer);
        batchPollingTimer = null;
        batchAllResults = [];
        batchUploadZone.classList.remove('hidden');
        batchProgress.classList.add('hidden');
        batchResults.classList.add('hidden');
        batchZipInput.value = '';
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // AUTO-APRENDIZAJE
    // ═══════════════════════════════════════════════════════════════════════════

    async function loadLearnedParsers() {
        try {
            const [parsersRes, pendingRes] = await Promise.all([
                fetch('api.php?action=learned_parsers').then(r => r.json()),
                fetch('api.php?action=pending_review').then(r => r.json()),
            ]);

            if (parsersRes.ok) renderLearnedTable(parsersRes.parsers || []);
            if (pendingRes.ok) renderPendingTable(pendingRes.pendientes || []);
        } catch (err) {
            console.error('Error cargando parsers aprendidos:', err);
        }
    }

    function renderLearnedTable(parsers) {
        const tbody = document.querySelector('#learnedTable tbody');
        if (!parsers.length) {
            tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--text-muted)">No hay parsers auto-generados todavía</td></tr>';
            return;
        }
        tbody.innerHTML = parsers.map(p => {
            const scorePct = Math.round(p.score * 100);
            const decBadge = p.decision === 'VERDE'
                ? '<span class="badge badge-ok">VERDE</span>'
                : '<span class="badge badge-fuzzy">AMARILLO</span>';
            return `
                <tr>
                    <td><strong>${esc(p.nombre)}</strong></td>
                    <td>${esc(p.species)}</td>
                    <td>${scorePct}%</td>
                    <td>${decBadge}</td>
                    <td>${esc(p.fecha)}</td>
                    <td>${p.num_pdfs}</td>
                    <td><small>${esc((p.keywords || []).join(', '))}</small></td>
                    <td>${p.activo ? '<span class="badge badge-ok">Sí</span>' : '<span class="badge badge-sin-match">No</span>'}</td>
                    <td><button class="btn btn-secondary btn-sm" onclick="toggleParser('${esc(p.nombre)}')">${p.activo ? 'Desactivar' : 'Activar'}</button></td>
                </tr>`;
        }).join('');
    }

    function renderPendingTable(pending) {
        const tbody = document.querySelector('#pendingTable tbody');
        if (!pending.length) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted)">No hay revisiones pendientes</td></tr>';
            return;
        }
        tbody.innerHTML = pending.map(p => `
            <tr class="row-partial">
                <td><strong>${esc(p.proveedor)}</strong></td>
                <td>${Math.round(p.score * 100)}%</td>
                <td>${esc(p.razon)}</td>
                <td>${(p.pdfs || []).length}</td>
                <td>${esc(p.fecha)}</td>
                <td><em>${esc(p.accion_sugerida)}</em></td>
            </tr>`).join('');
    }

    // Expose globally for onclick
    window.toggleParser = async function(nombre) {
        try {
            const res = await fetch('api.php?action=toggle_parser', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({nombre}),
            });
            const data = await res.json();
            if (data.ok) {
                loadLearnedParsers();
            } else {
                alert('Error: ' + data.error);
            }
        } catch (err) {
            alert('Error de conexión');
        }
    };
});
