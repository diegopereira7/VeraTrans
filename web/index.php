<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VeraBuy Traductor</title>
    <link rel="stylesheet" href="assets/style.css?v=<?= filemtime(__DIR__ . '/assets/style.css') ?>">
</head>
<body>
    <header>
        <h1>VeraBuy Traductor</h1>
        <nav>
            <button class="nav-btn active" data-tab="upload">Procesar Factura</button>
            <button class="nav-btn" data-tab="batch">Importación Masiva</button>
            <button class="nav-btn" data-tab="history">Historial</button>
            <button class="nav-btn" data-tab="synonyms">Sinónimos</button>
            <button class="nav-btn" data-tab="learned">Auto-Aprendizaje</button>
        </nav>
    </header>

    <main>
        <!-- TAB: Procesar Factura -->
        <section id="tab-upload" class="tab active">
            <div class="upload-zone" id="dropZone">
                <div class="upload-icon">&#128196;</div>
                <p>Arrastra un PDF aquí o haz clic para seleccionar</p>
                <input type="file" id="pdfInput" accept=".pdf" hidden>
                <button class="btn btn-primary" id="btnSelectFile">Seleccionar PDF</button>
            </div>

            <div id="processing" class="hidden">
                <div class="spinner"></div>
                <p>Procesando factura...</p>
            </div>

            <div id="resultSection" class="hidden">
                <!-- Cabecera de factura -->
                <div class="result-header" id="invoiceHeader"></div>

                <!-- Estadísticas -->
                <div class="stats-bar" id="statsBar"></div>

                <!-- Tabla de líneas -->
                <div class="table-container">
                    <table id="linesTable">
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>Descripción</th>
                                <th>Especie</th>
                                <th>Variedad</th>
                                <th>Talla</th>
                                <th>SPB</th>
                                <th>Tallos</th>
                                <th>Precio/T</th>
                                <th>Total</th>
                                <th>Artículo VeraBuy</th>
                                <th>Match</th>
                                <th>Acción</th>
                            </tr>
                        </thead>
                        <tbody></tbody>
                    </table>
                </div>

                <div style="display:flex;gap:12px;margin-top:16px;align-items:center">
                    <button class="btn btn-primary" id="btnGenerarOrden" style="font-size:15px;padding:12px 24px">Generar Hoja de Orden</button>
                    <button class="btn btn-secondary" id="btnNewUpload">Procesar otra factura</button>
                    <span id="ordenMsg" style="font-size:14px"></span>
                </div>
            </div>
        </section>

        <!-- TAB: Importación Masiva -->
        <section id="tab-batch" class="tab hidden">
            <!-- Estado 1: Subida -->
            <div id="batch-upload-zone">
                <h2>Importación Masiva de Facturas</h2>
                <div class="batch-drop-zone" id="batchDropZone">
                    <div class="upload-icon">&#128230;</div>
                    <p>Arrastra archivos <strong>PDF</strong>, una <strong>carpeta</strong> o un <strong>.zip</strong></p>
                    <p class="text-muted">o usa los botones para seleccionar</p>
                    <div class="batch-btn-group">
                        <button type="button" class="btn btn-primary" id="btnSelectZip">ZIP</button>
                        <button type="button" class="btn btn-primary" id="btnSelectFolder">Carpeta</button>
                        <button type="button" class="btn btn-primary" id="btnSelectPdfs">PDFs</button>
                    </div>
                </div>
            </div>

            <!-- Estado 2: Progreso -->
            <div id="batch-progress" class="hidden">
                <h2>Procesando Lote</h2>
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
                <h2>Resultados del Lote</h2>

                <!-- Tarjetas resumen -->
                <div class="batch-summary" id="batchSummary"></div>

                <!-- Detalle de omitidos/errores expandible -->
                <details id="batchSkippedDetails" class="batch-skipped hidden">
                    <summary>Ver archivos omitidos / con error</summary>
                    <div id="batchSkippedContent"></div>
                </details>

                <!-- Filtros -->
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

                <!-- Tabla de resultados -->
                <div class="table-container">
                    <table id="batchTable">
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>PDF</th>
                                <th>Proveedor</th>
                                <th>Factura</th>
                                <th>Fecha</th>
                                <th>Líneas</th>
                                <th>OK</th>
                                <th>Sin Match</th>
                                <th title="Líneas que necesitan revisión (sin match, baja confianza, o incoherencia de totales).">Revisar</th>
                                <th>Total USD</th>
                                <th>Estado</th>
                            </tr>
                        </thead>
                        <tbody></tbody>
                    </table>
                </div>

                <!-- Acciones -->
                <div class="batch-actions">
                    <button class="btn btn-primary" id="btnBatchExcel">Descargar Excel</button>
                    <button class="btn btn-secondary" id="btnBatchNew">Nueva Importación</button>
                </div>
            </div>
        </section>

        <!-- TAB: Historial -->
        <section id="tab-history" class="tab hidden">
            <h2>Historial de Procesamiento</h2>
            <div id="historyLoading" class="hidden">
                <div class="spinner"></div>
            </div>
            <div class="table-container">
                <table id="historyTable">
                    <thead>
                        <tr>
                            <th>Fecha</th>
                            <th>Factura</th>
                            <th>Proveedor</th>
                            <th>PDF</th>
                            <th>Líneas</th>
                            <th>OK</th>
                            <th>Sin Match</th>
                            <th>Total USD</th>
                            <th>Detalle</th>
                        </tr>
                    </thead>
                    <tbody></tbody>
                </table>
            </div>
        </section>

        <!-- TAB: Sinónimos (master-detail) -->
        <section id="tab-synonyms" class="tab hidden">
            <div class="syn-header">
                <h2>Diccionario de Sinónimos</h2>
                <button type="button" class="btn btn-primary" id="btnAddSynonym">+ Añadir sinónimo</button>
            </div>

            <!-- KPIs -->
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
                        <input type="text" id="synAddArticuloId" placeholder="id_erp (ej. 47195) o F000..." title="id_erp o referencia (F...). El id autoincrement no se acepta (sesión 10r).">
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
                <!-- MASTER: tabla -->
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
                        <button id="synClearFilters">Limpiar</button>
                        <span id="synCount"></span>
                    </div>
                    <div class="syn-tbl-wrap">
                        <table id="synTable">
                            <thead>
                                <tr>
                                    <th data-sort="provider_id">Proveedor</th>
                                    <th data-sort="variety">Variedad</th>
                                    <th data-sort="species">Especie</th>
                                    <th data-sort="size">Talla</th>
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

                <!-- DETAIL: panel lateral -->
                <div class="syn-detail" id="synDetailPane">
                    <div class="syn-detail-head">
                        <div>
                            <h3 id="synDetailTitle">Detalle</h3>
                            <p id="synDetailSub"></p>
                        </div>
                        <button id="synCloseDetail">✕ Cerrar</button>
                    </div>
                    <div class="syn-detail-body" id="synDetailBody"></div>
                </div>
            </div>
        </section>
        <!-- TAB: Auto-Aprendizaje -->
        <section id="tab-learned" class="tab hidden">
            <h2>Parsers Auto-Aprendidos</h2>
            <div id="learnedLoading" class="hidden"><div class="spinner"></div></div>

            <div id="learnedContent">
                <h3>Parsers Generados</h3>
                <div class="table-container">
                    <table id="learnedTable">
                        <thead>
                            <tr>
                                <th>Nombre</th>
                                <th>Especie</th>
                                <th>Score</th>
                                <th>Estado</th>
                                <th>Fecha</th>
                                <th>PDFs</th>
                                <th>Keywords</th>
                                <th>Activo</th>
                                <th>Acción</th>
                            </tr>
                        </thead>
                        <tbody></tbody>
                    </table>
                </div>

                <h3 style="margin-top: 24px;">Pendientes de Revisión</h3>
                <div class="table-container">
                    <table id="pendingTable">
                        <thead>
                            <tr>
                                <th>Proveedor</th>
                                <th>Score</th>
                                <th>Razón</th>
                                <th>PDFs</th>
                                <th>Fecha</th>
                                <th>Acción Sugerida</th>
                            </tr>
                        </thead>
                        <tbody></tbody>
                    </table>
                </div>
            </div>
        </section>
    </main>

    <footer>
        <p>VeraBuy Traductor v4.0 &mdash; Interfaz Web</p>
    </footer>

    <!-- Inputs ocultos para batch (fuera de tabs para evitar display:none issues) -->
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
</body>
</html>
