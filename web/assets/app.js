/**
 * VeraBuy Traductor Web - Frontend
 */

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
        `;

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
            const synKey = `${window._currentProviderId}|${l.species||''}|${l.variety||''}|${l.size||0}|${l.stems_per_bunch||0}|${l.grade||''}`;
            return `
            <tr class="${l.match_status === 'sin_parser' ? 'row-sin-parser' : l.match_status !== 'ok' ? 'row-sin-match' : ''}" data-idx="${i}" data-syn-key="${esc(synKey)}">
                <td>${i+1}</td>
                <td title="${esc(l.raw)}">${esc((l.raw||'').substring(0, 55))}${(l.raw||'').length > 55 ? '...' : ''}</td>
                <td>${esc(l.species)}</td>
                <td><strong>${esc(l.variety)}</strong></td>
                <td><input class="edit-input edit-line" data-idx="${i}" data-field="size" type="number" value="${l.size||0}"/></td>
                <td><input class="edit-input edit-line" data-idx="${i}" data-field="stems_per_bunch" type="number" value="${l.stems_per_bunch||0}"/></td>
                <td><input class="edit-input edit-line" data-idx="${i}" data-field="stems" type="number" value="${l.stems||0}"/></td>
                <td><input class="edit-input edit-line" data-idx="${i}" data-field="price_per_stem" type="number" step="0.001" value="${num(l.price_per_stem||0)}"/></td>
                <td><input class="edit-input edit-line" data-idx="${i}" data-field="line_total" type="number" step="0.01" value="${num(l.line_total||0)}"/></td>
                <td>${l.articulo_id ? `<strong>${l.articulo_id}</strong> ${esc(l.articulo_name||'')}` : '<em>-</em>'}</td>
                <td>${matchBadge(l.match_status, l.match_method)}</td>
                <td style="white-space:nowrap"><input class="edit-input edit-art" data-idx="${i}" placeholder="ID o Fref" style="width:70px;display:inline-block" value="${l.articulo_id||''}"/><button class="btn-icon line-delete" data-idx="${i}" title="Eliminar línea" style="color:var(--danger);font-size:14px;vertical-align:middle">✕</button></td>
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

        // Article lookup on Enter or change in the art column
        document.querySelectorAll('.edit-art').forEach(input => {
            const handler = async () => {
                const val = input.value.trim();
                if (!val) return;
                const idx = parseInt(input.dataset.idx);
                const tr = input.closest('tr');
                try {
                    const r = await fetch(`api.php?action=lookup_article&id=${encodeURIComponent(val)}`);
                    const d = await r.json();
                    if (d.ok) {
                        window._flatLines[idx].articulo_id = d.id;
                        window._flatLines[idx].articulo_name = d.nombre;
                        window._flatLines[idx].match_status = 'ok';
                        tr.querySelectorAll('td')[9].innerHTML = `<strong>${d.id}</strong> ${esc(d.nombre)}`;
                        tr.querySelectorAll('td')[10].innerHTML = '<span class="badge badge-manual">manual-web</span>';
                        tr.classList.remove('row-sin-match');
                        input.value = d.id;
                        // Save synonym
                        const synKey = tr.dataset.synKey;
                        const line = window._flatLines[idx];
                        await fetch('api.php?action=save_synonym', {
                            method:'POST', headers:{'Content-Type':'application/json'},
                            body: JSON.stringify({key:synKey, articulo_id:d.id, articulo_name:d.nombre,
                                provider_id:window._currentProviderId, species:line.species,
                                variety:line.variety, size:line.size, stems_per_bunch:line.stems_per_bunch, grade:line.grade||''})
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

    // Editar línea sin match en la tabla de factura individual
    document.querySelector('#linesTable tbody').addEventListener('click', async e => {
        const saveBtn = e.target.closest('.batch-line-save');
        if (!saveBtn) return;
        const tr = saveBtn.closest('tr');
        const input = tr.querySelector('.batch-art-id');
        const artId = parseInt(input.value) || 0;
        if (!artId) { alert('Introduce un ID de artículo'); return; }
        const synKey = tr.dataset.synKey;
        try {
            const lookupResp = await fetch(`api.php?action=lookup_article&id=${artId}`);
            const lookupData = await lookupResp.json();
            if (!lookupData.ok) { alert(lookupData.error); return; }
            const saveResp = await fetch('api.php?action=save_synonym', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: synKey, articulo_id: artId, articulo_name: lookupData.nombre }),
            });
            const saveData = await saveResp.json();
            if (saveData.ok) {
                const cells = tr.querySelectorAll('td');
                // Artículo VeraBuy (penúltima-2)
                cells[cells.length - 3].innerHTML = `<strong>${artId}</strong> ${esc(lookupData.nombre)}`;
                // Match badge
                cells[cells.length - 2].innerHTML = '<span class="badge badge-manual">manual-web</span>';
                // Acción
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
        if (status === 'mixed_box') {
            return '<span class="badge badge-fuzzy" title="Caja mixta sin desglose">CAJA MIXTA</span>';
        }
        return '<span class="badge badge-sin-match">SIN MATCH</span>';
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
                            const key = `${providerId}|${l.species || ''}|${l.variety || ''}|${l.size || 0}|${l.stems_per_bunch || 0}|${l.grade || ''}`;
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
                                    <input type="number" class="edit-input batch-art-id" placeholder="ID" style="width:65px">
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

        // Guardar match (reutiliza la misma lógica que batch)
        const saveBtn = e.target.closest('.batch-line-save');
        if (saveBtn) {
            const tr = saveBtn.closest('tr');
            const input = tr.querySelector('.batch-art-id');
            const artId = parseInt(input.value) || 0;
            if (!artId) { alert('Introduce un ID de artículo'); return; }
            const synKey = tr.dataset.synKey;

            try {
                const lookupResp = await fetch(`api.php?action=lookup_article&id=${artId}`);
                const lookupData = await lookupResp.json();
                if (!lookupData.ok) { alert(lookupData.error); return; }

                const saveResp = await fetch('api.php?action=save_synonym', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ key: synKey, articulo_id: artId, articulo_name: lookupData.nombre }),
                });
                const saveData = await saveResp.json();
                if (saveData.ok) {
                    const cells = tr.querySelectorAll('td');
                    cells[5].textContent = artId;
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
                <div class="syn-detail-field"><label>Nuevo ID Artículo</label><input type="number" id="synNewArtId" placeholder="Escribir ID..."/></div>
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

    // Bind Enter key on new art ID field after detail opens
    function synBindEnterKey() {
        const input = document.getElementById('synNewArtId');
        if (!input) return;
        input.addEventListener('keydown', async (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                const id = input.value;
                if (!id) return;
                // Lookup + auto-save
                const r = await fetch(`api.php?action=lookup_article&id=${id}`);
                const d = await r.json();
                document.getElementById('synNewArtName').value = d.ok && d.nombre ? d.nombre : '(no encontrado)';
                if (d.ok && d.nombre) {
                    await synDoSave();
                }
            }
        });
    }

    // Detail actions (global scope for onclick)
    window.synDoLookup = async function() {
        const id = document.getElementById('synNewArtId').value;
        if (!id) return;
        const r = await fetch(`api.php?action=lookup_article&id=${id}`);
        const d = await r.json();
        document.getElementById('synNewArtName').value = d.ok && d.nombre ? d.nombre : '(no encontrado)';
    };

    window.synDoSave = async function() {
        const nid = parseInt(document.getElementById('synNewArtId').value);
        const nm = document.getElementById('synNewArtName').value;
        if (!nid || nm === '(no encontrado)') { alert('Busca un artículo válido primero'); return; }
        const body = { key: synActiveSyn.key, articulo_id: nid, articulo_name: nm,
            provider_id: synActiveSyn.provider_id, species: synActiveSyn.species,
            variety: synActiveSyn.variety, size: synActiveSyn.size,
            stems_per_bunch: synActiveSyn.stems_per_bunch, grade: synActiveSyn.grade || '' };
        const r = await fetch('api.php?action=save_synonym', {
            method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
        const d = await r.json();
        if (d.ok) { synActiveSyn.articulo_id = nid; synActiveSyn.articulo_name = nm;
            synActiveSyn.origen = 'manual-web'; synUpdateKPIs(); synRenderTable(); }
        else { alert(d.error || 'Error'); }
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
        const body = { key: synActiveSyn.key, articulo_id: synActiveSyn.articulo_id,
            articulo_name: synActiveSyn.articulo_name, provider_id: synActiveSyn.provider_id,
            species: synActiveSyn.species, variety: synActiveSyn.variety,
            size: synActiveSyn.size, stems_per_bunch: synActiveSyn.stems_per_bunch,
            grade: synActiveSyn.grade || '' };
        const r = await fetch('api.php?action=save_synonym', {
            method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
        const d = await r.json();
        if (d.ok) { synActiveSyn.origen = 'manual-web'; synUpdateKPIs(); synRenderTable(); }
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
    document.getElementById('synAddArticuloId').addEventListener('change', async () => {
        const id = parseInt(document.getElementById('synAddArticuloId').value) || 0;
        if (!id) return;
        try {
            const res = await fetch(`api.php?action=lookup_article&id=${id}`);
            const data = await res.json();
            if (data.ok) document.getElementById('synAddArticuloName').value = data.nombre;
        } catch (err) {}
    });
    document.getElementById('btnSynAddSave').addEventListener('click', async () => {
        const key = document.getElementById('synAddKey').value.trim();
        const artId = parseInt(document.getElementById('synAddArticuloId').value) || 0;
        const artName = document.getElementById('synAddArticuloName').value.trim();
        if (!key || !artId) { alert('Clave e ID artículo son obligatorios'); return; }
        try {
            const res = await fetch('api.php?action=save_synonym', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key, articulo_id: artId, articulo_name: artName }) });
            const data = await res.json();
            if (data.ok) {
                document.getElementById('synAddForm').classList.add('hidden');
                document.getElementById('synAddKey').value = '';
                document.getElementById('synAddArticuloId').value = '';
                document.getElementById('synAddArticuloName').value = '';
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
            <div class="stat-card primary">
                <div class="stat-value">$${Number(r.total_usd).toLocaleString('en-US', {minimumFractionDigits: 2})}</div>
                <div class="stat-label">Total USD</div>
            </div>
        `;

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
            let status, statusClass;
            if (!r.ok) {
                status = 'ERROR'; statusClass = 'badge badge-sin-match';
            } else if (r.sin_match > 0) {
                status = 'PARCIAL'; statusClass = 'badge badge-fuzzy';
            } else {
                status = 'OK'; statusClass = 'badge badge-ok';
            }
            const hasLines = r.ok && r.lines && r.lines.length > 0;
            const needsReview = r.ok && r.sin_match > 0;
            const rowId = `batch-lines-${i}`;

            let html = `
                <tr class="${!r.ok ? 'row-sin-match' : r.sin_match > 0 ? 'row-partial' : ''} ${hasLines ? 'batch-expandable' : ''}" data-target="${rowId}">
                    <td>${i + 1}</td>
                    <td>${hasLines ? '<span class="expand-arrow">&#9654;</span> ' : ''}${esc(r.pdf)}</td>
                    <td>${esc(r.provider || '-')}</td>
                    <td>${esc(r.invoice || '-')}</td>
                    <td>${esc(r.date || '-')}</td>
                    <td>${r.lineas || 0}</td>
                    <td>${r.ok_count || 0}</td>
                    <td>${r.sin_match || 0}</td>
                    <td>$${num(r.total_usd || 0)}</td>
                    <td><span class="${statusClass}">${status}</span>${!r.ok ? `<br><small>${esc(r.error)}</small>` : ''}</td>
                </tr>`;

            // Fila expandible con líneas de detalle
            if (hasLines) {
                html += `<tr id="${rowId}" class="batch-lines-row hidden">
                    <td colspan="10">
                        <div class="batch-lines-detail">
                            <table class="batch-lines-table">
                                <thead><tr>
                                    <th>Descripción</th><th>Variedad</th><th>Talla</th>
                                    <th>Tallos</th><th>Total</th>
                                    <th>ID Artículo</th><th>Nombre Artículo</th>
                                    <th>Match</th>${needsReview ? '<th>Acción</th>' : ''}
                                </tr></thead>
                                <tbody>${r.lines.map(l => _batchLineRow(l, r, needsReview)).join('')}</tbody>
                            </table>
                        </div>
                    </td>
                </tr>`;
            }
            return html;
        }).join('');
    }

    function _batchLineRow(l, invoiceResult, showActions) {
        const isBad = l.match_status !== 'ok';
        const cls = isBad ? 'row-sin-match' : '';
        const key = `${invoiceResult.provider_id || 0}|${l.species || ''}|${l.variety || ''}|${l.size || 0}|${l.stems_per_bunch || 0}|${l.grade || ''}`;
        return `
            <tr class="${cls}" data-syn-key="${esc(key)}" data-pdf="${esc(invoiceResult.pdf)}">
                <td title="${esc(l.raw || '')}">${esc((l.raw || '').substring(0, 50))}${(l.raw || '').length > 50 ? '...' : ''}</td>
                <td><strong>${esc(l.variety || '')}</strong></td>
                <td>${l.size || '-'}</td>
                <td>${l.stems || '-'}</td>
                <td>$${num(l.line_total || 0)}</td>
                <td>${l.articulo_id || '-'}</td>
                <td>${esc(l.articulo_name || '-')}</td>
                <td>${matchBadge(l.match_status || '', l.match_method || '')}</td>
                ${showActions && isBad ? `<td>
                    <input type="number" class="edit-input batch-art-id" placeholder="ID" style="width:65px">
                    <button class="btn-icon batch-line-save" title="Guardar">&#10003;</button>
                </td>` : (showActions ? '<td></td>' : '')}
            </tr>`;
    }

    // Expandir/colapsar líneas de factura
    document.querySelector('#batchTable tbody').addEventListener('click', e => {
        const expandRow = e.target.closest('.batch-expandable');
        if (expandRow && !e.target.closest('.batch-line-save') && !e.target.closest('input')) {
            const targetId = expandRow.dataset.target;
            const linesRow = document.getElementById(targetId);
            if (linesRow) {
                linesRow.classList.toggle('hidden');
                const arrow = expandRow.querySelector('.expand-arrow');
                if (arrow) arrow.innerHTML = linesRow.classList.contains('hidden') ? '&#9654;' : '&#9660;';
            }
        }

        // Guardar match desde línea de batch
        const saveBtn = e.target.closest('.batch-line-save');
        if (saveBtn) {
            const tr = saveBtn.closest('tr');
            const input = tr.querySelector('.batch-art-id');
            const artId = parseInt(input.value) || 0;
            if (!artId) { alert('Introduce un ID de artículo'); return; }
            const synKey = tr.dataset.synKey;
            const pdf = tr.dataset.pdf;

            // Lookup nombre del artículo y guardar sinónimo
            fetch(`api.php?action=lookup_article&id=${artId}`)
                .then(r => r.json())
                .then(data => {
                    if (!data.ok) { alert(data.error); return; }
                    return fetch('api.php?action=save_synonym', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ key: synKey, articulo_id: artId, articulo_name: data.nombre }),
                    });
                })
                .then(r => r ? r.json() : null)
                .then(data => {
                    if (data && data.ok) {
                        // Actualizar visualmente
                        const cells = tr.querySelectorAll('td');
                        cells[5].textContent = artId;
                        cells[6].textContent = '';
                        fetch(`api.php?action=lookup_article&id=${artId}`)
                            .then(r => r.json())
                            .then(d => { if (d.ok) cells[6].textContent = d.nombre; });
                        cells[7].innerHTML = '<span class="badge badge-manual">manual-web</span>';
                        tr.classList.remove('row-sin-match');
                        const actionCell = cells[cells.length - 1];
                        actionCell.innerHTML = '<span style="color:green">&#10003;</span>';
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
