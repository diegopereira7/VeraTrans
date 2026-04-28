<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VeraFact — VeraBuy Traductor</title>

    <!-- Fuentes -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">

    <!-- Tokens (variables CSS) — carga ANTES -->
    <link rel="stylesheet" href="assets/tokens.css?v=<?= filemtime(__DIR__ . '/assets/tokens.css') ?>">
    <!-- Estilos principales -->
    <link rel="stylesheet" href="assets/style.css?v=<?= filemtime(__DIR__ . '/assets/style.css') ?>">
</head>
<body>
    <div class="app">

        <!-- ══════════ SIDEBAR ══════════ -->
        <aside class="sidebar">
            <div class="sidebar__brand">
                <img src="assets/veraleza-logo.png" alt="Veraleza">
                <div class="brand-text">
                    <div class="brand-sub">VeraFact</div>
                </div>
            </div>

            <nav class="sidebar__nav" id="nav">
                <div class="nav-section">Procesamiento</div>

                <button class="nav-btn nav-item is-active" data-tab="upload">
                    <span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="13" y2="17"/></svg></span>
                    <span class="nav-label">Procesar factura</span>
                </button>

                <button class="nav-btn nav-item" data-tab="batch">
                    <span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg></span>
                    <span class="nav-label">Importación masiva</span>
                </button>

                <button class="nav-btn nav-item" data-tab="history">
                    <span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><polyline points="3 3 3 8 8 8"/><path d="M12 7v5l4 2"/></svg></span>
                    <span class="nav-label">Historial</span>
                </button>

                <div class="nav-section">Diccionario</div>

                <button class="nav-btn nav-item" data-tab="synonyms">
                    <span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg></span>
                    <span class="nav-label">Sinónimos</span>
                </button>

                <button class="nav-btn nav-item" data-tab="learned">
                    <span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9.5 2a3.5 3.5 0 0 0-3.5 3.5A2.5 2.5 0 0 0 4 8a2.5 2.5 0 0 0 1 4.9v1.6A3.5 3.5 0 0 0 8.5 18M14.5 2A3.5 3.5 0 0 1 18 5.5 2.5 2.5 0 0 1 20 8a2.5 2.5 0 0 1-1 4.9v1.6A3.5 3.5 0 0 1 15.5 18"/><path d="M9.5 2v18M14.5 2v18"/></svg></span>
                    <span class="nav-label">Auto-aprendizaje</span>
                </button>
            </nav>

            <div class="sidebar__foot">
                <div class="status-dot"></div>
                <span>Pipeline v4.0</span>
            </div>
        </aside>

        <!-- ══════════ MAIN ══════════ -->
        <main class="main">

            <!-- ───── TAB: Procesar Factura ───── -->
            <section id="tab-upload" class="tab view active">
                <div class="pageheader">
                    <div class="pageheader__title">
                        <h1>Procesar factura</h1>
                        <p>Sube un PDF de proveedor y revisa el matching antes de generar la hoja de orden.</p>
                    </div>
                </div>

                <div class="upload-zone" id="dropZone">
                    <div class="upload-icon">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                    </div>
                    <div class="upload-title">Arrastra un PDF o haz clic para subir</div>
                    <p>Soporta CANTIZA, FLORALOJA, HOJA VERDE, NEVADO, TAMBO y otros 40+ proveedores</p>
                    <input type="file" id="pdfInput" accept=".pdf" hidden>
                    <button class="btn btn-primary" id="btnSelectFile">Seleccionar PDF</button>
                </div>

                <div id="processing" class="hidden">
                    <div class="spinner"></div>
                    <p>Procesando factura...</p>
                </div>

                <div id="resultSection" class="hidden">
                    <!-- Cabecera v2: stat-cards + banner atención + búsqueda + tabs -->
                    <div class="result-header" id="invoiceHeader"></div>

                    <!-- Legacy (app.js lo deja vacío pero conservamos el hueco) -->
                    <div class="stats-bar" id="statsBar"></div>

                    <!-- Tabla de líneas v2 (numeración, progress bars, badges OR./EST., tree mixed, id_erp) -->
                    <div class="table-wrap">
                        <div class="table-scroll">
                            <table class="t" id="linesTable">
                                <thead>
                                    <tr>
                                        <th style="width:28px">#</th>
                                        <th>Descripción</th>
                                        <th style="width:90px">Especie</th>
                                        <th style="width:110px">Variedad</th>
                                        <th class="num" style="width:52px">Talla</th>
                                        <th class="num" style="width:42px">SPB</th>
                                        <th class="num" style="width:56px">Tallos</th>
                                        <th class="num" style="width:88px">Precio</th>
                                        <th class="num" style="width:92px">Total</th>
                                        <th style="width:90px">Destino</th>
                                        <th>Artículo VeraBuy</th>
                                        <th style="width:90px">Match</th>
                                    </tr>
                                </thead>
                                <tbody></tbody>
                            </table>
                        </div>
                    </div>

                    <div class="page-actions">
                        <button class="btn btn-primary" id="btnGenerarOrden">Generar Hoja de Orden</button>
                        <button class="btn btn-secondary" id="btnNewUpload">Procesar otra factura</button>
                        <span id="ordenMsg" class="page-actions__msg"></span>
                    </div>
                </div>
            </section>

            <!-- ───── TAB: Importación Masiva ───── -->
            <section id="tab-batch" class="tab view hidden">
                <div class="pageheader">
                    <div class="pageheader__title">
                        <h1>Importación masiva</h1>
                        <p>Procesa decenas de PDFs a la vez: ZIP, carpeta o selección múltiple.</p>
                    </div>
                </div>

                <!-- Estado 1: Subida -->
                <div id="batch-upload-zone">
                    <div class="batch-drop-zone" id="batchDropZone">
                        <div class="upload-icon">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 8v13H3V8"/><path d="M1 3h22v5H1z"/><path d="M10 12h4"/></svg>
                        </div>
                        <div class="upload-title">Arrastra archivos PDF, una carpeta o un .zip</div>
                        <p>o usa los botones para seleccionar</p>
                        <div class="batch-btn-group">
                            <button type="button" class="btn btn-primary" id="btnSelectZip">ZIP</button>
                            <button type="button" class="btn btn-primary" id="btnSelectFolder">Carpeta</button>
                            <button type="button" class="btn btn-primary" id="btnSelectPdfs">PDFs</button>
                        </div>
                    </div>
                </div>

                <!-- Estado 2: Progreso -->
                <div id="batch-progress" class="hidden">
                    <div class="batch-progress-card">
                        <div class="batch-progress-header">
                            <span id="batch-status-text">Iniciando...</span>
                            <span id="batch-progress-count"></span>
                        </div>
                        <div class="batch-progress-bar-wrap">
                            <div class="batch-progress-bar" id="batchProgressBar" style="width: 0%"></div>
                        </div>
                        <div class="batch-progress-detail">
                            <span id="batch-current-pdf"></span>
                            <span id="batch-ok-err"></span>
                        </div>
                    </div>
                </div>

                <!-- Estado 3: Resultados -->
                <div id="batch-results" class="hidden">
                    <h2 class="section-title">Resultados del lote</h2>

                    <div class="batch-summary" id="batchSummary"></div>

                    <details id="batchSkippedDetails" class="batch-skipped hidden">
                        <summary>Ver archivos omitidos / con error</summary>
                        <div id="batchSkippedContent"></div>
                    </details>

                    <div class="filters">
                        <select id="batchFilterInvoice">
                            <option value="">Todas las facturas</option>
                        </select>
                        <select id="batchFilterStatus">
                            <option value="">Todos los estados</option>
                            <option value="ok">OK</option>
                            <option value="parcial">Parcial</option>
                            <option value="error">Error</option>
                        </select>
                        <input type="text" id="batchFilterText" placeholder="Buscar proveedor, factura...">
                    </div>

                    <div class="table-wrap">
                        <div class="table-scroll">
                            <table class="t" id="batchTable">
                                <thead>
                                    <tr>
                                        <th>#</th>
                                        <th>PDF</th>
                                        <th>Proveedor</th>
                                        <th>Factura</th>
                                        <th>Fecha</th>
                                        <th class="num">Líneas</th>
                                        <th class="num">OK</th>
                                        <th class="num">Sin Match</th>
                                        <th class="num" title="Líneas que necesitan revisión">Revisar</th>
                                        <th class="num">Total USD</th>
                                        <th>Estado</th>
                                    </tr>
                                </thead>
                                <tbody></tbody>
                            </table>
                        </div>
                    </div>

                    <div class="page-actions">
                        <button class="btn btn-primary" id="btnBatchExcel">Descargar Excel</button>
                        <button class="btn btn-secondary" id="btnBatchRematch" title="Vuelve a ejecutar el matcher sobre las líneas del lote (no re-extrae los PDFs). Útil si han cambiado reglas del matcher.">Re-procesar matches</button>
                        <button class="btn btn-secondary" id="btnBatchNew">Nueva importación</button>
                        <span id="batchActionMsg" class="page-actions__msg"></span>
                    </div>
                </div>
            </section>

            <!-- ───── TAB: Historial ───── -->
            <section id="tab-history" class="tab view hidden">
                <div class="pageheader">
                    <div class="pageheader__title">
                        <h1>Historial</h1>
                        <p>Todas las facturas procesadas.</p>
                    </div>
                </div>

                <div id="historyLoading" class="hidden">
                    <div class="spinner"></div>
                </div>

                <div class="table-wrap">
                    <div class="table-scroll">
                        <table class="t" id="historyTable">
                            <thead>
                                <tr>
                                    <th>Fecha</th>
                                    <th>Factura</th>
                                    <th>Proveedor</th>
                                    <th>PDF</th>
                                    <th class="num">Líneas</th>
                                    <th class="num">OK</th>
                                    <th class="num">Sin Match</th>
                                    <th class="num">Total USD</th>
                                </tr>
                            </thead>
                            <tbody></tbody>
                        </table>
                    </div>
                </div>
            </section>

            <!-- ───── TAB: Sinónimos (master-detail) ───── -->
            <section id="tab-synonyms" class="tab view hidden">
                <div class="pageheader">
                    <div class="pageheader__title">
                        <h1>Diccionario de sinónimos</h1>
                        <p>Mapeo de claves variedad→artículo ERP. Filtra, busca y añade.</p>
                    </div>
                    <div class="pageheader__actions">
                        <button type="button" class="btn btn-primary" id="btnAddSynonym">+ Añadir sinónimo</button>
                    </div>
                </div>

                <div class="syn-kpis">
                    <div class="syn-kpi"><h4>Total</h4><strong id="synKpiTotal">-</strong></div>
                    <div class="syn-kpi"><h4>Revisados / Manual</h4><strong id="synKpiRevisado">-</strong></div>
                    <div class="syn-kpi"><h4>Auto-fuzzy</h4><strong id="synKpiAutoFuzzy">-</strong></div>
                    <div class="syn-kpi"><h4>Proveedores</h4><strong id="synKpiProviders">-</strong></div>
                </div>

                <div id="synLoading" class="hidden"><div class="spinner"></div></div>

                <!-- Formulario añadir sinónimo (oculto) -->
                <div id="synAddForm" class="syn-add-form hidden">
                    <h3>Añadir sinónimo manual</h3>
                    <div class="syn-form-grid">
                        <label>Clave (provider|species|variety|size|spb|grade)
                            <input type="text" id="synAddKey" placeholder="2222|ROSES|FREEDOM|50|25|">
                        </label>
                        <label>id_erp o referencia del artículo
                            <input type="text" id="synAddArticuloId" placeholder="id_erp (ej. 47195) o F000...">
                        </label>
                        <label>Nombre Artículo
                            <input type="text" id="synAddArticuloName" placeholder="ROSA EC FREEDOM 50CM 25U">
                        </label>
                    </div>
                    <div class="syn-form-actions">
                        <button type="button" class="btn btn-primary" id="btnSynAddSave">Guardar</button>
                        <button type="button" class="btn btn-secondary" id="btnSynAddCancel">Cancelar</button>
                    </div>
                </div>

                <!-- Master-Detail workspace -->
                <div class="syn-workspace" id="synWorkspace">
                    <div class="syn-master">
                        <div class="syn-toolbar">
                            <input type="text" id="synFilter" placeholder="Buscar variedad, proveedor, artículo, factura...">
                            <select id="synOriginFilter">
                                <option value="">Todos orígenes</option>
                                <option value="auto-fuzzy">auto-fuzzy</option>
                                <option value="auto-marca">auto-marca</option>
                                <option value="auto-matching">auto-matching</option>
                                <option value="auto-color-strip">auto-color-strip</option>
                                <option value="auto-delegacion">auto-delegacion</option>
                                <option value="auto">auto</option>
                                <option value="manual">manual</option>
                                <option value="manual-web">manual-web</option>
                                <option value="revisado">revisado</option>
                            </select>
                            <select id="synSpeciesFilter">
                                <option value="">Todas especies</option>
                                <option value="ROSES">ROSES</option>
                                <option value="CARNATIONS">CARNATIONS</option>
                                <option value="HYDRANGEAS">HYDRANGEAS</option>
                                <option value="ALSTROEMERIA">ALSTROEMERIA</option>
                                <option value="CHRYSANTHEMUM">CHRYSANTHEMUM</option>
                                <option value="GYPSOPHILA">GYPSOPHILA</option>
                            </select>
                            <button id="synClearFilters" class="btn btn-ghost">Limpiar</button>
                            <span id="synCount"></span>
                        </div>
                        <div class="syn-tbl-wrap table-wrap">
                            <table class="t" id="synTable">
                                <thead>
                                    <tr>
                                        <th data-sort="provider_id">Proveedor</th>
                                        <th data-sort="variety">Variedad</th>
                                        <th data-sort="species">Especie</th>
                                        <th data-sort="size" class="num">Talla</th>
                                        <th data-sort="articulo_name">Artículo VeraBuy</th>
                                        <th data-sort="origen">Origen</th>
                                        <th data-sort="invoice">Factura</th>
                                    </tr>
                                </thead>
                                <tbody></tbody>
                            </table>
                        </div>
                        <div class="syn-tbl-info" id="synTableInfo"></div>
                    </div>

                    <div class="syn-detail" id="synDetailPane">
                        <div class="syn-detail-head">
                            <div>
                                <h3 id="synDetailTitle">Detalle</h3>
                                <p id="synDetailSub"></p>
                            </div>
                            <button id="synCloseDetail" class="btn btn-ghost btn-sm">✕ Cerrar</button>
                        </div>
                        <div class="syn-detail-body" id="synDetailBody"></div>
                    </div>
                </div>
            </section>

            <!-- ───── TAB: Auto-Aprendizaje ───── -->
            <section id="tab-learned" class="tab view hidden">
                <div class="pageheader">
                    <div class="pageheader__title">
                        <h1>Auto-aprendizaje</h1>
                        <p>Parsers generados automáticamente y pendientes de revisión.</p>
                    </div>
                </div>

                <div id="learnedLoading" class="hidden"><div class="spinner"></div></div>

                <div id="learnedContent">
                    <h3 class="section-title">Parsers generados</h3>
                    <div class="table-wrap">
                        <div class="table-scroll">
                            <table class="t" id="learnedTable">
                                <thead>
                                    <tr>
                                        <th>Nombre</th>
                                        <th>Especie</th>
                                        <th class="num">Score</th>
                                        <th>Estado</th>
                                        <th>Fecha</th>
                                        <th class="num">PDFs</th>
                                        <th>Keywords</th>
                                        <th>Activo</th>
                                        <th>Acción</th>
                                    </tr>
                                </thead>
                                <tbody></tbody>
                            </table>
                        </div>
                    </div>

                    <h3 class="section-title" style="margin-top:24px">Pendientes de revisión</h3>
                    <div class="table-wrap">
                        <div class="table-scroll">
                            <table class="t" id="pendingTable">
                                <thead>
                                    <tr>
                                        <th>Proveedor</th>
                                        <th class="num">Score</th>
                                        <th>Razón</th>
                                        <th class="num">PDFs</th>
                                        <th>Fecha</th>
                                        <th>Acción sugerida</th>
                                    </tr>
                                </thead>
                                <tbody></tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </section>

        </main>
    </div>

    <!-- Inputs ocultos para batch -->
    <input type="file" id="batchZipInput" accept=".zip" style="position:fixed;top:-9999px;left:-9999px">
    <input type="file" id="batchFolderInput" webkitdirectory style="position:fixed;top:-9999px;left:-9999px">
    <input type="file" id="batchPdfInput" accept=".pdf" multiple style="position:fixed;top:-9999px;left:-9999px">

    <script>
    <?php
    // Provider ID → name map for JS
    require_once __DIR__ . '/config.php';
    $configPy = file_get_contents(PROJECT_ROOT . '/src/config.py');
    preg_match_all("/'id':\s*(\d+),\s*'name':\s*'([^']+)'/", $configPy, $matches, PREG_SET_ORDER);
    $provs = [];
    foreach ($matches as $m) $provs[(int)$m[1]] = $m[2];
    echo "window.PROVIDER_NAMES=" . json_encode($provs, JSON_UNESCAPED_UNICODE) . ";\n";
    ?>
    </script>
    <script src="assets/app.js?v=<?= filemtime(__DIR__ . '/assets/app.js') ?>"></script>
    <script src="assets/app.extras.js?v=<?= filemtime(__DIR__ . '/assets/app.extras.js') ?>"></script>
</body>
</html>
