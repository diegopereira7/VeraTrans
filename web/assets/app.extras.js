/**
 * VeraFact — Extras de UI
 * Se carga DESPUÉS de app.js. Añade features sin modificar el original:
 *   - Drawer lateral al clickar una línea de factura (detalle)
 *   - Facturas recientes en la pantalla de upload
 *   - Mini-gráfico de barras en Historial (últimos 30 días)
 *   - Empty states
 *   - KPIs calculados en frontend cuando falta endpoint
 */
(function() {
  'use strict';

  // ─── Helpers ──────────────────────────────────────────────────
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const fmt = (n) => (Number(n) || 0).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const pn = (id) => (window.PROVIDER_NAMES || {})[id] || ('ID:' + id);

  // ─── DRAWER DE LÍNEA ──────────────────────────────────────────
  function ensureDrawer() {
    if (document.getElementById('lineDrawer')) return;
    const overlay = document.createElement('div');
    overlay.id = 'lineDrawerOverlay';
    overlay.className = 'drawer-overlay';
    document.body.appendChild(overlay);

    const drawer = document.createElement('aside');
    drawer.id = 'lineDrawer';
    drawer.className = 'drawer';
    drawer.innerHTML = `
      <div class="drawer__head">
        <div>
          <div class="drawer__title" id="drawerTitle">Detalle de línea</div>
          <div class="drawer__sub" id="drawerSub"></div>
        </div>
        <button class="drawer__close" id="drawerClose" aria-label="Cerrar">✕</button>
      </div>
      <div class="drawer__body" id="drawerBody"></div>
    `;
    document.body.appendChild(drawer);

    const close = () => {
      drawer.classList.remove('is-open');
      overlay.classList.remove('is-open');
    };
    overlay.addEventListener('click', close);
    drawer.querySelector('#drawerClose').addEventListener('click', close);
    document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
  }

  function openLineDrawer(line, idx) {
    ensureDrawer();
    const drawer = document.getElementById('lineDrawer');
    const overlay = document.getElementById('lineDrawerOverlay');
    const body = document.getElementById('drawerBody');
    document.getElementById('drawerTitle').textContent = line.variety || '(sin variedad)';
    document.getElementById('drawerSub').textContent =
      [line.species, line.size ? line.size + 'cm' : null, line.stems_per_bunch ? line.stems_per_bunch + '/bunch' : null]
        .filter(Boolean).join(' · ');

    const pd = (window._priceDeltas || {})[line.articulo_id];
    const reasons = (line.match_reasons && line.match_reasons.length) ? line.match_reasons.join(' · ') : '';
    const penal = (line.match_penalties && line.match_penalties.length) ? line.match_penalties.join(' · ') : '';
    const errs = (line.validation_errors && line.validation_errors.length) ? line.validation_errors.join(' · ') : '';

    body.innerHTML = `
      <div class="drawer__section">
        <h4>Línea original</h4>
        <div class="drawer__raw">${esc(line.raw || '(sin raw)')}</div>
      </div>

      <div class="drawer__section">
        <h4>Datos extraídos</h4>
        <dl class="drawer__grid">
          <dt>Especie</dt><dd>${esc(line.species || '—')}</dd>
          <dt>Variedad</dt><dd>${esc(line.variety || '—')}</dd>
          <dt>Talla</dt><dd>${line.size || '—'}${line.size ? ' cm' : ''}</dd>
          <dt>SPB</dt><dd>${line.stems_per_bunch || '—'}</dd>
          <dt>Grade</dt><dd>${esc(line.grade || '—')}</dd>
          <dt>Tallos</dt><dd>${line.stems || '—'}</dd>
          <dt>Precio/tallo</dt><dd>${line.price_per_stem ? '$' + fmt(line.price_per_stem) : '—'}</dd>
          <dt>Total línea</dt><dd>${line.line_total ? '$' + fmt(line.line_total) : '—'}</dd>
        </dl>
      </div>

      <div class="drawer__section">
        <h4>Matching</h4>
        <dl class="drawer__grid">
          <dt>Estado</dt><dd>${esc(line.match_status || '—')}</dd>
          <dt>Método</dt><dd>${esc(line.match_method || '—')}</dd>
          <dt>Confianza</dt><dd>${typeof line.match_confidence === 'number' ? Math.round(line.match_confidence * 100) + '%' : '—'}</dd>
          <dt>Carril</dt><dd>${esc(line.review_lane || '—')}</dd>
          <dt>ID Artículo</dt><dd>${line.articulo_id || '—'}</dd>
          <dt>ID ERP</dt><dd>${esc(line.articulo_id_erp || '—')}</dd>
        </dl>
        ${line.articulo_name ? `
        <div style="margin-top:10px;padding:8px 10px;background:var(--primary-soft);border-radius:6px;font-size:12px;">
          <strong>${esc(line.articulo_name)}</strong>
        </div>` : ''}
      </div>

      ${reasons ? `
      <div class="drawer__section">
        <h4>Evidencia</h4>
        <div style="font-size:12px;color:var(--text);line-height:1.6">${esc(reasons)}</div>
      </div>` : ''}

      ${penal ? `
      <div class="drawer__section">
        <h4>Penalizaciones</h4>
        <div style="font-size:12px;color:var(--warn-700);line-height:1.6">${esc(penal)}</div>
      </div>` : ''}

      ${errs ? `
      <div class="drawer__section">
        <h4 style="color:var(--danger-700)">Errores de validación</h4>
        <div style="font-size:12px;color:var(--danger-700);line-height:1.6">${esc(errs)}</div>
      </div>` : ''}

      ${pd ? `
      <div class="drawer__section">
        <h4>Anomalía de precio</h4>
        <dl class="drawer__grid">
          <dt>Delta</dt><dd style="color:${pd.delta_pct >= 0 ? 'var(--danger-700)' : 'var(--ok-700)'}">${pd.delta_pct >= 0 ? '+' : ''}${pd.delta_pct}%</dd>
          <dt>Ref histórico</dt><dd>$${fmt(pd.price_ref)}</dd>
        </dl>
      </div>` : ''}
    `;

    drawer.classList.add('is-open');
    overlay.classList.add('is-open');

    // ── Asíncrono: candidatos sugeridos si línea sin match
    if (!line.articulo_id && line.variety) {
      const slot = document.createElement('div');
      slot.className = 'drawer__section';
      slot.innerHTML = '<h4>Candidatos sugeridos</h4><div style="font-size:12px;color:var(--text-muted)">Buscando…</div>';
      body.appendChild(slot);
      const params = new URLSearchParams({
        species: line.species || '', variety: line.variety || '',
        size: line.size || 0, spb: line.stems_per_bunch || 0,
        provider_id: window._currentProviderId || 0, limit: 5,
      });
      fetch('api.php?action=suggest_candidates&' + params.toString())
        .then(r => r.json())
        .then(d => {
          if (!d || !d.ok) { slot.querySelector('div').textContent = 'Endpoint no disponible'; return; }
          const cands = d.candidates || [];
          if (!cands.length) { slot.querySelector('div').textContent = 'Sin coincidencias.'; return; }
          slot.innerHTML = '<h4>Candidatos sugeridos</h4>' + cands.map(c => `
            <div class="cand-row" data-id-erp="${esc(c.articulo_id_erp)}" data-id="${c.articulo_id}" data-name="${esc(c.nombre)}" data-idx="${idx}">
              <div class="cand-row__top">
                <strong>${esc(c.nombre)}</strong>
                <span class="cand-row__score">${c.score}%</span>
              </div>
              <div class="cand-row__sub">
                <span>${esc(c.articulo_id_erp || 'sin erp')}</span>
                <button class="cand-row__use">Usar →</button>
              </div>
            </div>
          `).join('');
          slot.querySelectorAll('.cand-row__use').forEach(btn => {
            btn.addEventListener('click', (ev) => {
              ev.stopPropagation();
              const row = btn.closest('.cand-row');
              const idErp = row.dataset.idErp;
              const targetIdx = row.dataset.idx;
              // Rellenar input de artículo de esa fila + disparar change
              const inp = document.querySelector(`#linesTable tbody input.edit-art[data-idx="${targetIdx}"]`);
              if (inp) {
                inp.value = idErp;
                inp.dispatchEvent(new Event('change', { bubbles: true }));
              }
              document.getElementById('lineDrawerOverlay').click();
            });
          });
        })
        .catch(() => { slot.querySelector('div').textContent = 'Endpoint no disponible'; });
    }

    // ── Asíncrono: timeline de precio
    if (line.articulo_id) {
      const slot = document.createElement('div');
      slot.className = 'drawer__section';
      slot.innerHTML = '<h4>Histórico de precio (90d)</h4><div style="font-size:12px;color:var(--text-muted)">Cargando…</div>';
      body.appendChild(slot);
      fetch(`api.php?action=price_anomalies_timeline&articulo_id=${line.articulo_id}&days=90`)
        .then(r => r.json())
        .then(d => {
          if (!d || !d.ok) { slot.querySelector('div').textContent = 'Endpoint no disponible'; return; }
          const tl = d.timeline || [];
          if (!tl.length) { slot.querySelector('div').textContent = 'Sin historial suficiente.'; return; }
          const max = Math.max(...tl.map(p => p.price));
          const min = Math.min(...tl.map(p => p.price));
          const range = max - min || 1;
          const stats = d.stats || {};
          slot.innerHTML = `
            <h4>Histórico de precio (90d)</h4>
            <div class="price-chart">
              <div class="price-chart__bars">
                ${tl.map(p => {
                  const h = Math.round(((p.price - min) / range) * 100) + 4;
                  return `<div class="price-bar ${p.anomaly ? 'is-anom' : ''}" style="height:${h}%">
                    <span class="price-bar__tip">${p.date}<br>$${p.price.toFixed(3)}${p.anomaly ? ' ⚠ z='+p.z : ''}</span>
                  </div>`;
                }).join('')}
              </div>
              <div class="price-chart__foot">
                <span>${tl.length} datos · μ $${(stats.mean||0).toFixed(3)} · σ $${(stats.std||0).toFixed(3)}</span>
                <span>min $${min.toFixed(3)} — max $${max.toFixed(3)}</span>
              </div>
            </div>
          `;
        })
        .catch(() => { slot.querySelector('div').textContent = 'Endpoint no disponible'; });
    }
  }

  // Interceptar clicks en filas de #linesTable (solo en celdas no editables)
  document.addEventListener('click', (e) => {
    const tr = e.target.closest('#linesTable tbody tr');
    if (!tr) return;
    // Ignorar si clicó en input, button, o celda de acción
    if (e.target.closest('input, button, select, textarea, .line-delete, .line-confirm, .edit-input, .batch-line-save')) return;
    const idx = parseInt(tr.dataset.idx);
    if (isNaN(idx) || !window._flatLines || !window._flatLines[idx]) return;
    openLineDrawer(window._flatLines[idx], idx);
  });

  // ─── FACTURAS RECIENTES ───────────────────────────────────────
  async function loadRecentInvoices() {
    const dropZone = document.getElementById('dropZone');
    if (!dropZone) return;

    // Intentar endpoint dedicado, si no existe usar /history y tomar 5
    let recent = [];
    try {
      let r = await fetch('api.php?action=recent_invoices&limit=5');
      let d = await r.json();
      if (d && d.ok && Array.isArray(d.invoices)) {
        recent = d.invoices;
      } else {
        throw new Error('no endpoint');
      }
    } catch {
      try {
        const r = await fetch('api.php?action=history', { method: 'POST' });
        const d = await r.json();
        if (d && d.ok && Array.isArray(d.history)) {
          recent = d.history.slice(0, 5);
        }
      } catch {}
    }

    // Si la drop-zone ya tiene una strip, la borramos antes
    let strip = document.getElementById('recentStrip');
    if (strip) strip.remove();
    if (!recent.length) return;

    strip = document.createElement('div');
    strip.id = 'recentStrip';
    strip.className = 'recent-strip';
    strip.innerHTML = `
      <div class="recent-strip__head">Últimas facturas procesadas</div>
      <div class="recent-grid">
        ${recent.map(inv => {
          const sinMatch = inv.sin_match || 0;
          return `
          <div class="recent-card" data-pdf="${esc(inv.pdf || '')}" data-pdf-path="${esc(inv.pdf_path || '')}">
            <div class="recent-card__prov">${esc(inv.provider || '—')}</div>
            <div class="recent-card__inv">${esc(inv.invoice_key || inv.pdf || '')}</div>
            <div class="recent-card__meta">
              <span>${esc(inv.fecha || '')}</span>
              <span class="recent-card__total">$${fmt(inv.total_usd || 0)}</span>
            </div>
            <div class="recent-card__meta">
              <span>${inv.lineas || 0} líneas</span>
              <span class="recent-card__badge${sinMatch > 0 ? ' warn' : ''}">${sinMatch > 0 ? sinMatch + ' pend.' : 'OK'}</span>
            </div>
          </div>`;
        }).join('')}
      </div>
    `;
    // Insertar después del dropZone
    dropZone.parentNode.insertBefore(strip, dropZone.nextSibling);

    // Click en card → re-procesar
    strip.querySelectorAll('.recent-card').forEach(card => {
      card.addEventListener('click', async () => {
        const pdf = card.dataset.pdf;
        const pdfPath = card.dataset.pdfPath || '';
        if (!pdf) return;
        dropZone.classList.add('hidden');
        strip.classList.add('hidden');
        document.getElementById('processing').classList.remove('hidden');
        try {
          const r = await fetch('api.php?action=reprocess', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pdf, pdf_path: pdfPath }),
          });
          const d = await r.json();
          document.getElementById('processing').classList.add('hidden');
          if (!d.ok) {
            alert('Error: ' + (d.error || 'No se pudo reprocesar'));
            dropZone.classList.remove('hidden');
            strip.classList.remove('hidden');
            return;
          }
          // Delegar en renderResult existente
          if (typeof window.renderResult === 'function') {
            window.renderResult(d);
          } else {
            // renderResult no está expuesto globalmente; simular el flujo procesando un evento en el input
            // Alternativa: recargar directamente el resultSection manualmente
            location.reload();
          }
          document.getElementById('resultSection').classList.remove('hidden');
        } catch {
          document.getElementById('processing').classList.add('hidden');
          dropZone.classList.remove('hidden');
          strip.classList.remove('hidden');
          alert('Error de conexión');
        }
      });
    });
  }

  // Recargar recientes tras subir una factura
  const origReset = window.resetUpload;
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(loadRecentInvoices, 200);
    // Observar cuando se vuelve a la pestaña upload
    document.querySelectorAll('.nav-btn[data-tab="upload"]').forEach(b => {
      b.addEventListener('click', () => setTimeout(loadRecentInvoices, 100));
    });
    // Re-cargar recientes cuando pulsen "Procesar otra factura"
    const btnNew = document.getElementById('btnNewUpload');
    if (btnNew) btnNew.addEventListener('click', () => setTimeout(loadRecentInvoices, 200));
  });

  // ─── MINI-GRÁFICO DE HISTORIAL ────────────────────────────────
  function renderHistChart(history) {
    const tabHist = document.getElementById('tab-history');
    if (!tabHist) return;
    let chartEl = document.getElementById('histChart');

    // Agrupar por día (últimos 30)
    const today = new Date();
    const days = [];
    for (let i = 29; i >= 0; i--) {
      const d = new Date(today);
      d.setDate(d.getDate() - i);
      const key = d.toISOString().slice(0, 10);
      days.push({ key, label: d.getDate(), count: 0, withErr: 0 });
    }
    const idx = Object.fromEntries(days.map((d, i) => [d.key, i]));
    (history || []).forEach(h => {
      // fecha puede venir como "YYYY-MM-DD" o ISO
      const f = (h.fecha || '').slice(0, 10);
      if (f in idx) {
        days[idx[f]].count++;
        if ((h.sin_match || 0) > 0) days[idx[f]].withErr++;
      }
    });
    const maxCount = Math.max(1, ...days.map(d => d.count));
    const totalInvoices = days.reduce((s, d) => s + d.count, 0);
    const totalErr = days.reduce((s, d) => s + d.withErr, 0);

    if (!chartEl) {
      chartEl = document.createElement('div');
      chartEl.id = 'histChart';
      chartEl.className = 'hist-chart';
      // Insertar antes de la tabla de historial
      const tableWrap = tabHist.querySelector('.table-wrap');
      if (tableWrap) tabHist.insertBefore(chartEl, tableWrap);
      else tabHist.appendChild(chartEl);
    }
    chartEl.innerHTML = `
      <div class="hist-chart__head">
        <div class="hist-chart__title">Actividad · últimos 30 días</div>
        <div class="hist-chart__summary">
          <strong>${totalInvoices}</strong> facturas ·
          <strong style="color:var(--danger-700)">${totalErr}</strong> con revisión pendiente
        </div>
      </div>
      <div class="hist-chart__bars">
        ${days.map(d => {
          const h = Math.round((d.count / maxCount) * 100);
          const cls = d.withErr > 0 ? 'hist-bar has-err' : '';
          return `<div class="${cls || 'hist-bar'}" style="height:${h}%">
            <span class="hist-bar__tip">${d.key}<br>${d.count} factura${d.count!==1?'s':''}${d.withErr?' · '+d.withErr+' err':''}</span>
          </div>`;
        }).join('')}
      </div>
    `;
  }

  // Monkey-patch loadHistory via observer: detectar cuando la tabla se llena
  const histObserver = new MutationObserver(() => {
    const tbody = document.querySelector('#historyTable tbody');
    if (!tbody) return;
    // Sacar datos del DOM como fallback
    if (Array.isArray(window.historyData) && window.historyData.length) {
      renderHistChart(window.historyData);
    } else {
      // Fallback: parsear filas
      const rows = [...tbody.querySelectorAll('tr:not(.batch-lines-row)')];
      const parsed = rows.map(tr => {
        const cells = tr.querySelectorAll('td');
        return {
          fecha: cells[0]?.textContent.trim(),
          sin_match: parseInt(cells[6]?.textContent || '0', 10),
        };
      });
      if (parsed.length) renderHistChart(parsed);
    }
  });
  document.addEventListener('DOMContentLoaded', () => {
    const tbody = document.querySelector('#historyTable tbody');
    if (tbody) histObserver.observe(tbody, { childList: true });
  });

  // ─── EMPTY STATES ─────────────────────────────────────────────
  function ensureEmptyState(tbodyEl, title, desc, iconSvg) {
    if (!tbodyEl) return;
    const hasRows = tbodyEl.children.length > 0;
    const wrap = tbodyEl.closest('.table-wrap');
    if (!wrap) return;
    let empty = wrap.parentNode.querySelector('.empty-state[data-for="' + tbodyEl.id + '"]');

    if (hasRows) {
      if (empty) empty.remove();
      wrap.classList.remove('hidden');
      return;
    }

    wrap.classList.add('hidden');
    if (!empty) {
      empty = document.createElement('div');
      empty.className = 'empty-state';
      empty.dataset.for = tbodyEl.id || '';
      empty.innerHTML = `
        <div class="empty-state__icon">${iconSvg}</div>
        <div class="empty-state__title">${esc(title)}</div>
        <div class="empty-state__desc">${esc(desc)}</div>
      `;
      wrap.parentNode.insertBefore(empty, wrap);
    }
  }

  const ICON_HISTORY = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><polyline points="3 3 3 8 8 8"/><path d="M12 7v5l4 2"/></svg>';
  const ICON_SYN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>';

  // Observar cambios en tablas clave
  ['historyTable', 'synTable', 'learnedTable', 'pendingTable'].forEach(id => {
    const tbl = document.getElementById(id);
    if (!tbl) return;
    const tbody = tbl.querySelector('tbody');
    if (!tbody) return;
    if (!tbody.id) tbody.id = id + '_tbody';
    const icon = id === 'synTable' ? ICON_SYN : ICON_HISTORY;
    const label = id === 'historyTable' ? 'No hay facturas procesadas aún'
                : id === 'synTable' ? 'No hay sinónimos'
                : id === 'learnedTable' ? 'No hay parsers auto-generados'
                : 'No hay parsers pendientes';
    const desc = id === 'historyTable' ? 'Procesa tu primera factura desde la pestaña Procesar factura.'
                : id === 'synTable' ? 'Aún no has añadido ni auto-aprendido ningún mapeo.'
                : 'El pipeline crea entradas automáticamente cuando detecta patrones nuevos.';
    const obs = new MutationObserver(() => ensureEmptyState(tbody, label, desc, icon));
    obs.observe(tbody, { childList: true });
    // Primera ejecución tras un tick
    setTimeout(() => ensureEmptyState(tbody, label, desc, icon), 500);
  });

  // ─── Hover cursor hint en filas de línea ─────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    const style = document.createElement('style');
    style.textContent = '#linesTable tbody tr { cursor: pointer; } #linesTable tbody tr input, #linesTable tbody tr button { cursor: auto; }';
    document.head.appendChild(style);
  });

})();
