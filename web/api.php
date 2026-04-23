<?php
/**
 * VeraBuy Traductor Web - API endpoint
 * Recibe un PDF vía POST y devuelve el resultado del procesamiento en JSON.
 */
require_once __DIR__ . '/config.php';
require_once __DIR__ . '/db_config.php';

// Constantes de importación masiva
define('BATCH_STATUS_DIR',  PROJECT_ROOT . '/batch_status');
define('BATCH_RESULTS_DIR', PROJECT_ROOT . '/batch_results');
define('BATCH_UPLOADS_DIR', PROJECT_ROOT . '/batch_uploads');
define('BATCH_SCRIPT',      PROJECT_ROOT . '/batch_process.py');
define('MAX_ZIP_SIZE',      100 * 1024 * 1024); // 100 MB
define('LEARNED_RULES_FILE', PROJECT_ROOT . '/learned_rules.json');
define('PENDING_REVIEW_FILE', PROJECT_ROOT . '/pending_review.json');
define('AUDIT_LOG_FILE', PROJECT_ROOT . '/audit_log.jsonl');
define('SHADOW_LOG_FILE', PROJECT_ROOT . '/shadow_log.jsonl');

header('Content-Type: application/json; charset=utf-8');

// VeraFact v2 — endpoints opcionales (recent_invoices / suggest_candidates / price_anomalies_timeline).
// Intercepta antes del switch; cada bloque hace exit si matchea.
require_once __DIR__ . '/api.extras.php';

// Batch status y download son GET; el resto POST
$action = $_GET['action'] ?? 'process';

if (in_array($action, ['batch_status', 'batch_download', 'learned_parsers', 'pending_review', 'lookup_article',
                        // v4: aliases y acciones nuevas que llegan vía GET
                        'learned', 'get_synonyms', 'history', 'history_detail'])) {
    if ($_SERVER['REQUEST_METHOD'] !== 'GET') {
        http_response_code(405);
        echo json_encode(['ok' => false, 'error' => 'Método no permitido']);
        exit;
    }
} else {
    if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
        http_response_code(405);
        echo json_encode(['ok' => false, 'error' => 'Método no permitido']);
        exit;
    }
}

switch ($action) {
    case 'process':
    case 'process_pdf':         // v4 alias
        handleProcess();
        break;
    case 'synonyms':
    case 'get_synonyms':        // v4 alias
        handleSynonyms();
        break;
    case 'history':
        handleHistory();
        break;
    case 'history_detail':      // v4 — detalle HTML de una factura
        handleHistoryDetail();
        break;
    case 'learned':             // v4 alias de learned_parsers
        handleLearnedParsers();
        break;
    case 'save_synonym':
        handleSaveSynonym();
        break;
    case 'confirm_match':
        handleConfirmMatch();
        break;
    case 'correct_match':
        handleCorrectMatch();
        break;
    case 'update_synonym':
        handleUpdateSynonym();
        break;
    case 'lookup_article':
        handleLookupArticle();
        break;
    case 'delete_synonym':
        handleDeleteSynonym();
        break;
    case 'reprocess':
        handleReprocess();
        break;
    case 'batch_upload':
        handleBatchUpload();
        break;
    case 'batch_upload_pdfs':
        handleBatchUploadPdfs();
        break;
    case 'batch_status':
        handleBatchStatus();
        break;
    case 'batch_download':
        handleBatchDownload();
        break;
    case 'learned_parsers':
        handleLearnedParsers();
        break;
    case 'pending_review':
        handlePendingReview();
        break;
    case 'toggle_parser':
        handleToggleParser();
        break;
    case 'generar_orden':
        handleGenerarOrden();
        break;
    default:
        http_response_code(400);
        echo json_encode(['ok' => false, 'error' => 'Acción no válida']);
}

/**
 * Procesar un PDF subido
 */

/**
 * v4: página HTML sencilla con la cabecera de historial + líneas de
 * una factura. Se invoca desde el link "Ver →" de la tabla de
 * historial (target="_blank"), por eso devuelve HTML, no JSON.
 */
function handleHistoryDetail(): void
{
    $invoiceKey = trim($_GET['invoice_key'] ?? '');
    $db = get_db();

    // Cambia el content-type: esta acción no es JSON.
    if (!headers_sent()) {
        header_remove('Content-Type');
        header('Content-Type: text/html; charset=utf-8');
    }

    $esc = fn($s) => htmlspecialchars((string)$s, ENT_QUOTES, 'UTF-8');

    if ($invoiceKey === '' || !$db) {
        http_response_code(400);
        echo "<!doctype html><meta charset='utf-8'><title>Factura no disponible</title>"
             . "<body style='font-family:system-ui;padding:40px;color:#555'>"
             . "<h1>Factura no disponible</h1><p>Falta <code>invoice_key</code> o la DB no responde.</p></body>";
        return;
    }

    $stmt = $db->prepare("SELECT numero_factura, pdf_nombre, proveedor, id_proveedor,
                                  total_usd, lineas, ok_count, sin_match, fecha_proceso
                           FROM historial WHERE numero_factura = ? LIMIT 1");
    $stmt->bind_param('s', $invoiceKey);
    $stmt->execute();
    $h = $stmt->get_result()->fetch_assoc();
    $stmt->close();

    if (!$h) {
        http_response_code(404);
        echo "<!doctype html><meta charset='utf-8'><title>404</title>"
             . "<body style='font-family:system-ui;padding:40px;color:#555'>"
             . "<h1>Factura no encontrada</h1><p><code>" . $esc($invoiceKey) . "</code></p></body>";
        return;
    }

    $stmt = $db->prepare("SELECT raw_description, especie, variedad, grado, talla,
                                  stems_per_bunch, stems, precio_stem, total_linea,
                                  label, box_type, id_articulo, nombre_articulo,
                                  match_status, match_method
                           FROM facturas_lineas
                           WHERE numero_factura = ?
                           ORDER BY id");
    $stmt->bind_param('s', $invoiceKey);
    $stmt->execute();
    $lines = $stmt->get_result()->fetch_all(MYSQLI_ASSOC);
    $stmt->close();

    $statusBadge = function(string $st) use ($esc): string {
        $color = match ($st) {
            'ok'               => '#1a7a3e',
            'ambiguous_match'  => '#a56c00',
            'sin_match'        => '#a51f1f',
            default            => '#666',
        };
        return "<span style='background:" . $color . "1a;color:" . $color
             . ";padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600'>"
             . $esc($st) . "</span>";
    };

    echo "<!doctype html><html lang='es'><head><meta charset='utf-8'>"
       . "<title>" . $esc($h['numero_factura']) . " — " . $esc($h['proveedor']) . "</title>"
       . "<style>"
       . "body{font-family:system-ui,-apple-system,Segoe UI,Roboto;margin:0;padding:24px 32px;"
       . "background:#f6f3ea;color:#222}"
       . ".meta{background:#fff;border:1px solid #e2dfd5;border-radius:8px;padding:16px 20px;"
       . "margin-bottom:16px;display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}"
       . ".meta div{font-size:12px;color:#888}.meta strong{display:block;font-size:15px;color:#222}"
       . "table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e2dfd5;border-radius:8px;overflow:hidden}"
       . "th,td{padding:8px 10px;border-bottom:1px solid #efeadc;text-align:left;font-size:12.5px;vertical-align:top}"
       . "th{background:#eeeadf;font-weight:600;text-transform:uppercase;letter-spacing:.5px;font-size:10.5px;color:#666}"
       . ".num{text-align:right;font-variant-numeric:tabular-nums}"
       . "tr:last-child td{border-bottom:0}"
       . "</style></head><body>"
       . "<h1 style='margin:0 0 12px'>" . $esc($h['numero_factura']) . "</h1>"
       . "<div class='meta'>"
       . "<div>Proveedor<strong>" . $esc($h['proveedor']) . "</strong></div>"
       . "<div>PDF<strong>" . $esc($h['pdf_nombre']) . "</strong></div>"
       . "<div>Fecha<strong>" . $esc($h['fecha_proceso']) . "</strong></div>"
       . "<div>Total USD<strong>$" . number_format((float)$h['total_usd'], 2) . "</strong></div>"
       . "<div>Líneas<strong>" . (int)$h['lineas'] . " · " . (int)$h['ok_count']
            . " ok · " . (int)$h['sin_match'] . " sin match</strong></div>"
       . "</div>"
       . "<table><thead><tr>"
       . "<th style='width:28px'>#</th><th>Descripción</th><th>Especie</th><th>Variedad</th>"
       . "<th class='num'>Talla</th><th class='num'>SPB</th><th class='num'>Tallos</th>"
       . "<th class='num'>Precio</th><th class='num'>Total</th>"
       . "<th>Artículo VeraBuy</th><th>Match</th></tr></thead><tbody>";

    foreach ($lines as $i => $l) {
        echo "<tr>"
           . "<td>" . ($i + 1) . "</td>"
           . "<td style='max-width:260px;color:#666'>" . $esc($l['raw_description']) . "</td>"
           . "<td>" . $esc($l['especie']) . "</td>"
           . "<td><strong>" . $esc($l['variedad']) . "</strong></td>"
           . "<td class='num'>" . (int)$l['talla'] . "</td>"
           . "<td class='num'>" . (int)$l['stems_per_bunch'] . "</td>"
           . "<td class='num'>" . (int)$l['stems'] . "</td>"
           . "<td class='num'>" . number_format((float)$l['precio_stem'], 3) . "</td>"
           . "<td class='num'>" . number_format((float)$l['total_linea'], 2) . "</td>"
           . "<td>" . ($l['id_articulo']
               ? "<strong>#" . (int)$l['id_articulo'] . "</strong> " . $esc($l['nombre_articulo'])
               : "<em style='color:#888'>—</em>") . "</td>"
           . "<td>" . $statusBadge($l['match_status'] ?? '') . "</td>"
           . "</tr>";
    }
    echo "</tbody></table></body></html>";
}

/**
 * Limpia PDFs subidos con más de N días de antigüedad.
 */
function _cleanOldUploads(int $days = 7): void
{
    $dir = UPLOAD_DIR;
    if (!is_dir($dir)) return;
    $cutoff = time() - ($days * 86400);
    foreach (glob($dir . '/*.pdf') as $file) {
        if (filemtime($file) < $cutoff) {
            @unlink($file);
        }
    }
}

/**
 * Limpia carpetas de batch (uploads + status + xlsx) con más de N días.
 *
 * Llamada al inicio de cada nuevo batch upload para que los PDFs procesados
 * queden disponibles ~1 día y la pestaña Historial pueda reprocesarlos. Se
 * borra el trío {batch_uploads/{id}/, batch_status/{id}.json,
 * batch_results/{id}.xlsx} cuando la carpeta de uploads supera el TTL.
 */
function _cleanOldBatches(int $days = 1): void
{
    if (!is_dir(BATCH_UPLOADS_DIR)) return;
    $cutoff = time() - ($days * 86400);

    foreach (glob(BATCH_UPLOADS_DIR . '/*', GLOB_ONLYDIR) as $dir) {
        if (filemtime($dir) >= $cutoff) continue;

        $batchId = basename($dir);
        // Borrar PDFs y carpeta
        foreach (glob($dir . '/*') as $f) {
            @unlink($f);
        }
        @rmdir($dir);
        // Borrar status y xlsx asociados
        @unlink(BATCH_STATUS_DIR  . '/' . $batchId . '.json');
        @unlink(BATCH_RESULTS_DIR . '/' . $batchId . '.xlsx');
    }
}

function handleProcess(): void
{
    // Asegurar que existe el directorio de uploads. Si no, move_uploaded_file
    // lanza un Warning de PHP que se convierte en HTML (Xdebug) y rompe el
    // JSON que espera el frontend.
    if (!is_dir(UPLOAD_DIR)) {
        @mkdir(UPLOAD_DIR, 0777, true);
    }

    _cleanOldUploads(1); // Borrar PDFs de hace más de 1 día

    if (!isset($_FILES['pdf']) || $_FILES['pdf']['error'] !== UPLOAD_ERR_OK) {
        $code = $_FILES['pdf']['error'] ?? -1;
        echo json_encode(['ok' => false, 'error' => "Error al subir archivo (código $code)"]);
        return;
    }

    $file = $_FILES['pdf'];

    // Validar tipo
    $finfo = finfo_open(FILEINFO_MIME_TYPE);
    $mime = finfo_file($finfo, $file['tmp_name']);
    finfo_close($finfo);

    if ($mime !== 'application/pdf') {
        echo json_encode(['ok' => false, 'error' => 'El archivo debe ser un PDF']);
        return;
    }

    // Validar tamaño
    if ($file['size'] > MAX_PDF_SIZE) {
        echo json_encode(['ok' => false, 'error' => 'El archivo excede el tamaño máximo (10 MB)']);
        return;
    }

    // Guardar con nombre seguro
    $safeName = preg_replace('/[^a-zA-Z0-9._-]/', '_', basename($file['name']));
    $dest = UPLOAD_DIR . '/' . time() . '_' . $safeName;

    if (!move_uploaded_file($file['tmp_name'], $dest)) {
        echo json_encode(['ok' => false, 'error' => 'Error al guardar el archivo']);
        return;
    }

    // Llamar al procesador Python
    // En Windows, escapeshellarg usa comillas dobles; construimos el comando
    // con la ruta absoluta al intérprete para evitar problemas de PATH en WAMP.
    $cmd = '"' . PYTHON_BIN . '" '
         . '"' . PROCESSOR_SCRIPT . '" '
         . '"' . $dest . '"'
         . ' 2>&1';

    $output = shell_exec($cmd);

    // Mantener el PDF para poder reprocesarlo desde el historial

    if ($output === null) {
        echo json_encode(['ok' => false, 'error' => 'Error al ejecutar el procesador Python']);
        return;
    }

    // Shadow mode: interceptar el resultado para loguear propuestas del
    // matcher antes de devolverlo al cliente. No modificamos el output —
    // el frontend sigue recibiendo el mismo JSON.
    $parsed = json_decode($output, true);
    if (is_array($parsed)) {
        _shadowLogProposals($parsed, $dest);
    }

    // v4: el app.js nuevo lee campos del header en la raíz (provider,
    // invoice_key, provider_id, fecha, total) y nombres distintos en las
    // líneas (total_line, confidence). El procesador Python emite el
    // formato histórico (header anidado + line_total + match_confidence).
    // Aquí añadimos aliases — aditivo, no pisa los originales.
    if (is_array($parsed) && !empty($parsed['ok'])) {
        $h = $parsed['header'] ?? [];
        $parsed['provider']    = $parsed['provider']    ?? ($h['provider_name']  ?? '');
        $parsed['provider_id'] = $parsed['provider_id'] ?? ($h['provider_id']    ?? 0);
        $parsed['invoice_key'] = $parsed['invoice_key'] ?? ($h['invoice_number'] ?? '');
        $parsed['fecha']       = $parsed['fecha']       ?? ($h['date']           ?? '');
        $parsed['total']       = $parsed['total']       ?? ($h['total']          ?? 0);
        $parsed['pdf']         = $parsed['pdf']         ?? basename($dest);

        if (isset($parsed['lines']) && is_array($parsed['lines'])) {
            foreach ($parsed['lines'] as &$line) {
                // Línea normal o mixed_parent — mapear campos que app.js v4
                // espera con otro nombre.
                if (isset($line['line_total']) && !isset($line['total_line'])) {
                    $line['total_line'] = $line['line_total'];
                }
                if (isset($line['match_confidence']) && !isset($line['confidence'])) {
                    $line['confidence'] = $line['match_confidence'];
                }
                // mixed_parent tiene children[]; aplica recursivo
                if (isset($line['children']) && is_array($line['children'])) {
                    foreach ($line['children'] as &$child) {
                        if (isset($child['line_total']) && !isset($child['total_line'])) {
                            $child['total_line'] = $child['line_total'];
                        }
                        if (isset($child['match_confidence']) && !isset($child['confidence'])) {
                            $child['confidence'] = $child['match_confidence'];
                        }
                    }
                    unset($child);
                }
            }
            unset($line);
        }

        echo json_encode($parsed, JSON_UNESCAPED_UNICODE);
        return;
    }

    // Sin parsing (ok=false, error, etc.) — devolvemos el output crudo.
    echo $output;
}

/**
 * Devolver sinónimos actuales (MySQL con fallback JSON)
 */
function handleSynonyms(): void
{
    $db = get_db();
    if ($db) {
        // El schema real usa nombres en español; aliasamos a los nombres que
        // espera el frontend (app.js). `raw` e `invoice` no existen en la
        // tabla — el frontend los usa solo para búsquedas de texto, así que
        // devolvemos cadenas vacías.
        $result = $db->query(
            "SELECT clave              AS `key`,
                    id_articulo        AS articulo_id,
                    nombre_articulo    AS articulo_name,
                    origen,
                    id_proveedor       AS provider_id,
                    especie            AS species,
                    nombre_factura     AS variety,
                    talla              AS size,
                    stems_per_bunch,
                    grado              AS grade,
                    ''                 AS raw,
                    ''                 AS invoice
             FROM sinonimos
             ORDER BY clave"
        );
        if ($result) {
            $list = $result->fetch_all(MYSQLI_ASSOC);
            // Convertir tipos numéricos
            foreach ($list as &$row) {
                $row['articulo_id'] = (int)$row['articulo_id'];
                $row['provider_id'] = (int)$row['provider_id'];
                $row['size'] = (int)$row['size'];
                $row['stems_per_bunch'] = (int)$row['stems_per_bunch'];
            }
            echo json_encode(['ok' => true, 'synonyms' => $list, 'total' => count($list)]);
            return;
        }
    }

    // Fallback a JSON
    if (!file_exists(SYNONYMS_FILE)) {
        echo json_encode(['ok' => true, 'synonyms' => []]);
        return;
    }
    $data = json_decode(file_get_contents(SYNONYMS_FILE), true);
    if ($data === null) {
        echo json_encode(['ok' => false, 'error' => 'Error al leer sinónimos']);
        return;
    }
    $list = [];
    foreach ($data as $key => $entry) {
        $entry['key'] = $key;
        $list[] = $entry;
    }
    echo json_encode(['ok' => true, 'synonyms' => $list, 'total' => count($list)]);
}

/**
 * Devolver historial de procesamiento (MySQL con fallback JSON)
 */
function handleHistory(): void
{
    $db = get_db();
    if ($db) {
        // Schema real en español; aliasamos a los nombres que espera app.js.
        $result = $db->query(
            "SELECT numero_factura                         AS invoice_key,
                    pdf_nombre                             AS pdf,
                    proveedor                              AS provider,
                    total_usd,
                    lineas,
                    ok_count                               AS ok,
                    sin_match,
                    DATE_FORMAT(fecha_proceso, '%Y-%m-%d %H:%i') AS fecha
             FROM historial
             ORDER BY fecha_proceso DESC"
        );
        if ($result) {
            $list = $result->fetch_all(MYSQLI_ASSOC);
            foreach ($list as &$row) {
                $row['total_usd'] = (float)$row['total_usd'];
                $row['lineas'] = (int)$row['lineas'];
                $row['ok'] = (int)$row['ok'];
                $row['sin_match'] = (int)$row['sin_match'];
            }
            echo json_encode(['ok' => true, 'history' => $list, 'total' => count($list)]);
            return;
        }
    }

    // Fallback JSON
    if (!file_exists(HISTORY_FILE)) {
        echo json_encode(['ok' => true, 'history' => []]);
        return;
    }
    $data = json_decode(file_get_contents(HISTORY_FILE), true);
    if ($data === null) {
        echo json_encode(['ok' => false, 'error' => 'Error al leer historial']);
        return;
    }
    $list = [];
    foreach ($data as $key => $entry) {
        $entry['invoice_key'] = $key;
        $list[] = $entry;
    }
    usort($list, fn($a, $b) => strcmp($b['fecha'] ?? '', $a['fecha'] ?? ''));
    echo json_encode(['ok' => true, 'history' => $list, 'total' => count($list)]);
}

/**
 * Guardar un sinónimo manual — MySQL + JSON dual-write
 */
function handleSaveSynonym(): void
{
    $input = json_decode(file_get_contents('php://input'), true);
    if (!$input || empty($input['key'])) {
        echo json_encode(['ok' => false, 'error' => 'Datos incompletos (falta key)']);
        return;
    }

    $key = $input['key'];

    // Resolución del artículo — política 10r: el frontend puede enviar
    // `articulo_id_erp` (preferido) o `q` (id_erp o referencia). Si solo
    // viene `articulo_id` (frontend legacy), lo interpretamos también
    // como id_erp para forzar consistencia — NUNCA como id autoincrement.
    $db = get_db();
    $artErpQuery = trim((string)($input['articulo_id_erp'] ?? $input['q'] ?? $input['articulo_id'] ?? ''));
    if ($artErpQuery === '') {
        echo json_encode(['ok' => false, 'error' => 'Falta articulo_id_erp o q']);
        return;
    }
    $row = _lookupArticleByErpOrRef($db, $artErpQuery);
    if (!$row) {
        echo json_encode([
            'ok' => false,
            'error' => "«$artErpQuery» no existe como id_erp ni referencia",
        ]);
        return;
    }
    $artId    = (int)$row['id'];
    $artIdErp = (string)($row['id_erp'] ?? '');
    $artName  = $input['articulo_name'] ?? $row['nombre'];

    // La clave viene en formato "provider_id|species|variety|size|spb|grade"
    // (mismo formato que SynonymStore._key en el lado Python). Se desempaca para
    // poblar las columnas NOT NULL del schema real (id_proveedor, nombre_factura,
    // especie, talla, stems_per_bunch, grado).
    $parts        = explode('|', $key);
    $provId       = isset($parts[0]) ? (int)$parts[0] : 0;
    $especie      = $parts[1] ?? '';
    $variety      = $parts[2] ?? '';
    $talla        = isset($parts[3]) ? (int)$parts[3] : 0;
    $spb          = isset($parts[4]) ? (int)$parts[4] : 0;
    $grado        = $parts[5] ?? '';

    // MySQL — el enum `origen` solo acepta manual/auto/auto-fuzzy, así que
    // 'manual-web' se mapea a 'manual'. El `id_articulo` guardado es el
    // autoincrement local (FK interna de la tabla sinónimos); lo que
    // el sistema usa como clave estable es `id_erp` del lado JSON.
    if ($db) {
        $stmt = $db->prepare(
            "INSERT INTO sinonimos
                (clave, id_proveedor, nombre_factura, especie, talla,
                 stems_per_bunch, grado, id_articulo, nombre_articulo, origen)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual')
             ON DUPLICATE KEY UPDATE
                id_articulo     = VALUES(id_articulo),
                nombre_articulo = VALUES(nombre_articulo),
                origen          = 'manual'"
        );
        $stmt->bind_param(
            'sissiisis',
            $key, $provId, $variety, $especie, $talla,
            $spb, $grado, $artId, $artName
        );
        $stmt->execute();
    }

    // JSON sync — includes id_erp (clave estable entre reimports, 10q/10r).
    _syncSynonymToJson($key, [
        'articulo_id' => $artId,
        'articulo_id_erp' => $artIdErp,
        'articulo_name' => $artName, 'origen' => 'manual-web',
        'provider_id' => (int)($input['provider_id'] ?? 0),
        'species' => $input['species'] ?? '', 'variety' => $input['variety'] ?? '',
        'size' => (int)($input['size'] ?? 0), 'stems_per_bunch' => (int)($input['stems_per_bunch'] ?? 0),
        'grade' => $input['grade'] ?? '',
    ]);

    // Shadow mode: save_synonym ≡ operador asigna artículo cuando el matcher no
    // propuso nada (sin_match/sin_parser, oldArtId=0). Se loguea como
    // decision=correct con proposed=0 para no perder cobertura real del matcher.
    // El input viene de batch-line-save con provider_id/species/variety/..., o
    // del formulario de sinónimos manual sin esos campos — en el segundo caso
    // se rellenan desde la propia clave.
    $shadowInput = $input + [
        'provider_id'     => $provId,
        'species'         => $especie,
        'variety'         => $variety,
        'size'            => $talla,
        'stems_per_bunch' => $spb,
        'grade'           => $grado,
    ];
    _shadowLogDecision('correct', $shadowInput, 0, $artId, $artName);

    echo json_encode(['ok' => true, 'message' => 'Sinónimo guardado']);
}

/**
 * Confirmar match — el operador acepta que el artículo asignado es correcto.
 * Promueve el sinónimo: aprendido_en_prueba → aprendido_confirmado.
 * Body JSON: { key: "provider_id|species|variety|size|spb|grade", articulo_id: int }
 */
function handleConfirmMatch(): void
{
    $input = json_decode(file_get_contents('php://input'), true);
    if (!$input || empty($input['key'])) {
        echo json_encode(['ok' => false, 'error' => 'Datos incompletos']);
        return;
    }
    $key = $input['key'];
    $artId = (int)($input['articulo_id'] ?? 0);

    $data = [];
    if (file_exists(SYNONYMS_FILE)) {
        $data = json_decode(file_get_contents(SYNONYMS_FILE), true) ?? [];
    }
    if (!isset($data[$key])) {
        echo json_encode(['ok' => false, 'error' => 'Sinónimo no encontrado']);
        return;
    }
    $entry = &$data[$key];
    // Solo confirmar si el articulo_id coincide
    if ($artId && (int)($entry['articulo_id'] ?? 0) !== $artId) {
        echo json_encode(['ok' => false, 'error' => 'articulo_id no coincide con el sinónimo']);
        return;
    }
    $entry['times_confirmed'] = (int)($entry['times_confirmed'] ?? 0) + 1;
    $entry['last_confirmed_at'] = date('c');
    // Ascenso de status
    $status = $entry['status'] ?? 'aprendido_en_prueba';
    if (in_array($status, ['aprendido_en_prueba', ''], true)) {
        $entry['status'] = 'aprendido_confirmado';
    }
    // Hidratar articulo_id_erp si la entry es vieja y no lo tiene todavía.
    // Sesión 10q: id_erp es la clave estable para preservar vínculos entre
    // reimports del dump del catálogo.
    if (empty($entry['articulo_id_erp']) && $artId > 0) {
        $db = get_db();
        $erp = _getArtIdErp($db, $artId);
        if ($erp !== '') {
            $entry['articulo_id_erp'] = $erp;
        }
    }
    // Persist
    $json = json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);
    $tmp = SYNONYMS_FILE . '.tmp';
    file_put_contents($tmp, $json);
    rename($tmp, SYNONYMS_FILE);

    // Shadow mode: el operador confirmó la propuesta. Decided = proposed.
    _shadowLogDecision('confirm', $input, $artId, $artId,
                       $entry['articulo_name'] ?? '');

    echo json_encode([
        'ok' => true,
        'message' => 'Match confirmado',
        'new_status' => $entry['status'],
        'times_confirmed' => $entry['times_confirmed'],
    ]);
}

/**
 * Corregir match — el operador cambia el artículo. Degrada el sinónimo
 * viejo y guarda el nuevo como manual-web.
 * Body JSON: { key, old_articulo_id, new_articulo_id, new_articulo_name,
 *              provider_id, species, variety, size, stems_per_bunch, grade }
 */
function handleCorrectMatch(): void
{
    $input = json_decode(file_get_contents('php://input'), true);
    if (!$input || empty($input['key'])) {
        echo json_encode(['ok' => false, 'error' => 'Datos incompletos (falta key)']);
        return;
    }
    $key       = $input['key'];
    $oldArtId  = (int)($input['old_articulo_id'] ?? 0);

    // Política 10r: el nuevo artículo se identifica SIEMPRE por id_erp
    // o referencia, nunca por id autoincrement. Aceptamos varios nombres
    // de campo por retrocompat.
    $db = get_db();
    $newErpQuery = trim((string)($input['new_articulo_id_erp']
                                 ?? $input['q']
                                 ?? $input['new_articulo_id'] ?? ''));
    if ($newErpQuery === '') {
        echo json_encode(['ok' => false, 'error' => 'Falta new_articulo_id_erp o q']);
        return;
    }
    $newRow = _lookupArticleByErpOrRef($db, $newErpQuery);
    if (!$newRow) {
        echo json_encode([
            'ok' => false,
            'error' => "«$newErpQuery» no existe como id_erp ni referencia",
        ]);
        return;
    }
    $newArtId    = (int)$newRow['id'];
    $newArtIdErp = (string)($newRow['id_erp'] ?? '');
    $newArtName  = $input['new_articulo_name'] ?? $newRow['nombre'];

    $data = [];
    if (file_exists(SYNONYMS_FILE)) {
        $data = json_decode(file_get_contents(SYNONYMS_FILE), true) ?? [];
    }

    // Degradar el sinónimo viejo si existe y coincide
    if (isset($data[$key]) && $oldArtId && (int)($data[$key]['articulo_id'] ?? 0) === $oldArtId) {
        $data[$key]['times_corrected'] = (int)($data[$key]['times_corrected'] ?? 0) + 1;
        if ((int)$data[$key]['times_corrected'] >= 2) {
            $data[$key]['status'] = 'rechazado';
        } else {
            $data[$key]['status'] = 'ambiguo';
        }
    }

    // MySQL sync para el nuevo
    $parts = explode('|', $key);
    $provId = isset($parts[0]) ? (int)$parts[0] : 0;
    $especie = $parts[1] ?? '';
    $variety = $parts[2] ?? '';
    $talla = isset($parts[3]) ? (int)$parts[3] : 0;
    $spb = isset($parts[4]) ? (int)$parts[4] : 0;
    $grado = $parts[5] ?? '';
    // `newArtId`/`newArtIdErp` ya están resueltos arriba desde el payload
    // por id_erp o referencia (política 10r).
    if ($db) {
        $stmt = $db->prepare(
            "INSERT INTO sinonimos
                (clave, id_proveedor, nombre_factura, especie, talla,
                 stems_per_bunch, grado, id_articulo, nombre_articulo, origen)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual')
             ON DUPLICATE KEY UPDATE
                id_articulo     = VALUES(id_articulo),
                nombre_articulo = VALUES(nombre_articulo),
                origen          = 'manual'"
        );
        $stmt->bind_param('sissiisis', $key, $provId, $variety, $especie, $talla, $spb, $grado, $newArtId, $newArtName);
        $stmt->execute();
    }

    // Guardar el sinónimo nuevo (sobreescribe el viejo con el artículo correcto)
    $data[$key] = array_merge($data[$key] ?? [], [
        'articulo_id'     => $newArtId,
        'articulo_id_erp' => $newArtIdErp,
        'articulo_name'   => $newArtName,
        'origen'          => 'manual-web',
        'provider_id'     => (int)($input['provider_id'] ?? 0),
        'species'         => $input['species'] ?? '',
        'variety'         => $input['variety'] ?? '',
        'size'            => (int)($input['size'] ?? 0),
        'stems_per_bunch' => (int)($input['stems_per_bunch'] ?? 0),
        'grade'           => $input['grade'] ?? '',
        'status'          => 'manual_confirmado',
        'times_confirmed' => 1,
        'last_confirmed_at' => date('c'),
    ]);

    // Persist JSON
    $json = json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);
    $tmp = SYNONYMS_FILE . '.tmp';
    file_put_contents($tmp, $json);
    rename($tmp, SYNONYMS_FILE);

    // Shadow mode: el operador corrigió. Decided ≠ proposed. Necesitamos
    // los campos de la línea para reconstruir contexto en el report.
    $shadowInput = array_merge($input, [
        'provider_id'     => $provId,
        'species'         => $especie,
        'variety'         => $variety,
        'size'            => $talla,
        'stems_per_bunch' => $spb,
        'grade'           => $grado,
    ]);
    _shadowLogDecision('correct', $shadowInput, $oldArtId, $newArtId, $newArtName);

    echo json_encode([
        'ok' => true,
        'message' => 'Match corregido',
        'new_articulo_id' => $newArtId,
        'new_articulo_name' => $newArtName,
    ]);
}

/**
 * Buscar nombre de artículo por ID — MySQL con fallback SQL dump
 */
function handleLookupArticle(): void
{
    // Aceptamos `q` (nombre canónico a partir de 10r). `id` queda como
    // alias por retrocompat del frontend, pero SIEMPRE se interpreta
    // como id_erp o referencia, nunca como id autoincrement.
    $q = trim($_GET['q'] ?? $_GET['id'] ?? '');
    if (!$q) {
        echo json_encode(['ok' => false, 'error' => 'id_erp o referencia no proporcionado']);
        return;
    }

    $db = get_db();
    if (!$db) {
        echo json_encode(['ok' => false, 'error' => 'Base de datos no disponible']);
        return;
    }

    // Política 10r: el id autoincrement NO es aceptado como input — se
    // renumera al reimportar el catálogo y genera asignaciones
    // equivocadas. Solo `id_erp` (estable entre reimports) o
    // `referencia` (F...).
    $row = _lookupArticleByErpOrRef($db, $q);
    if ($row) {
        echo json_encode([
            'ok'     => true,
            'id'     => (int)$row['id'],
            'id_erp' => (string)($row['id_erp'] ?? ''),
            'nombre' => $row['nombre'],
            'ref'    => $row['referencia'],
        ]);
        return;
    }
    echo json_encode([
        'ok' => false,
        'error' => "«$q» no existe como id_erp ni referencia. "
                 . "El id autoincrement no se acepta (sesión 10r).",
    ]);
}

/**
 * Resuelve un artículo por id_erp o referencia. Devuelve el row o null.
 */
function _lookupArticleByErpOrRef($db, string $q): ?array
{
    if (!$db || $q === '') {
        return null;
    }
    // 1) id_erp (string — la tabla admite valores numéricos o alfa).
    $stmt = $db->prepare(
        "SELECT id, id_erp, nombre, referencia FROM articulos WHERE id_erp = ? LIMIT 1"
    );
    $stmt->bind_param('s', $q);
    $stmt->execute();
    $res = $stmt->get_result();
    if ($row = $res->fetch_assoc()) {
        return $row;
    }
    // 2) referencia (F...) — comparación case-insensitive.
    $ref = strtoupper($q);
    $stmt = $db->prepare(
        "SELECT id, id_erp, nombre, referencia FROM articulos WHERE UPPER(referencia) = ? LIMIT 1"
    );
    $stmt->bind_param('s', $ref);
    $stmt->execute();
    $res = $stmt->get_result();
    if ($row = $res->fetch_assoc()) {
        return $row;
    }
    return null;
}

/**
 * Actualizar sinónimo — MySQL + JSON dual-write
 */
function handleUpdateSynonym(): void
{
    $input = json_decode(file_get_contents('php://input'), true);
    $origKey = $input['original_key'] ?? '';
    $newKey  = $input['new_key'] ?? '';
    $artId   = (int)($input['articulo_id'] ?? 0);
    $artName = $input['articulo_name'] ?? '';

    if (!$origKey || !$newKey || !$artId) {
        echo json_encode(['ok' => false, 'error' => 'Datos incompletos']);
        return;
    }

    // MySQL — desempaquetar la nueva clave para poblar columnas NOT NULL
    // (provider_id|species|variety|size|spb|grade)
    $parts   = explode('|', $newKey);
    $provId  = isset($parts[0]) ? (int)$parts[0] : 0;
    $especie = $parts[1] ?? '';
    $variety = $parts[2] ?? '';
    $talla   = isset($parts[3]) ? (int)$parts[3] : 0;
    $spb     = isset($parts[4]) ? (int)$parts[4] : 0;
    $grado   = $parts[5] ?? '';

    $db = get_db();
    if ($db) {
        if ($origKey !== $newKey) {
            // Cambiar clave: borrar vieja, insertar nueva
            $stmt = $db->prepare("DELETE FROM sinonimos WHERE clave = ?");
            $stmt->bind_param('s', $origKey);
            $stmt->execute();
        }
        $stmt = $db->prepare(
            "INSERT INTO sinonimos
                (clave, id_proveedor, nombre_factura, especie, talla,
                 stems_per_bunch, grado, id_articulo, nombre_articulo, origen)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual')
             ON DUPLICATE KEY UPDATE
                id_articulo     = VALUES(id_articulo),
                nombre_articulo = VALUES(nombre_articulo),
                origen          = 'manual'"
        );
        $stmt->bind_param(
            'sissiisis',
            $newKey, $provId, $variety, $especie, $talla,
            $spb, $grado, $artId, $artName
        );
        $stmt->execute();
    }

    // JSON sync
    $data = json_decode(file_get_contents(SYNONYMS_FILE), true) ?? [];
    if (isset($data[$origKey])) {
        $entry = $data[$origKey];
        $entry['articulo_id'] = $artId;
        $entry['articulo_name'] = $artName;
        $entry['origen'] = 'manual-web';
        if ($origKey !== $newKey) unset($data[$origKey]);
        $data[$newKey] = $entry;
        $json = json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);
        file_put_contents(SYNONYMS_FILE . '.tmp', $json);
        rename(SYNONYMS_FILE . '.tmp', SYNONYMS_FILE);
    }

    echo json_encode(['ok' => true, 'message' => 'Sinónimo actualizado']);
}

/**
 * Eliminar sinónimo — soft delete en MySQL + borrar de JSON
 */
function handleDeleteSynonym(): void
{
    $input = json_decode(file_get_contents('php://input'), true);
    $key = $input['key'] ?? '';

    if (!$key) {
        echo json_encode(['ok' => false, 'error' => 'Clave no proporcionada']);
        return;
    }

    // MySQL: hard delete (la tabla `sinonimos` no tiene columna `activo`).
    $db = get_db();
    if ($db) {
        $stmt = $db->prepare("DELETE FROM sinonimos WHERE clave = ?");
        $stmt->bind_param('s', $key);
        $stmt->execute();
    }

    // JSON: hard delete
    $data = json_decode(file_get_contents(SYNONYMS_FILE), true) ?? [];

    if (!isset($data[$key])) {
        echo json_encode(['ok' => false, 'error' => 'Sinónimo no encontrado']);
        return;
    }

    unset($data[$key]);

    $tmp = SYNONYMS_FILE . '.tmp';
    $json = json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);
    file_put_contents($tmp, $json);
    rename($tmp, SYNONYMS_FILE);

    echo json_encode(['ok' => true, 'message' => 'Sinónimo eliminado']);
}

/**
 * Reprocesar un PDF del historial y devolver las líneas
 */
function handleReprocess(): void
{
    $input = json_decode(file_get_contents('php://input'), true);
    $pdfName = $input['pdf'] ?? '';
    $pdfPathDirect = $input['pdf_path'] ?? '';

    if (!$pdfName && !$pdfPathDirect) {
        echo json_encode(['ok' => false, 'error' => 'Nombre de PDF no proporcionado']);
        return;
    }

    // Si tenemos ruta directa del historial, usarla primero
    $pdfPath = null;
    if ($pdfPathDirect && file_exists($pdfPathDirect)) {
        $pdfPath = $pdfPathDirect;
    }

    // Buscar por nombre en múltiples ubicaciones
    if (!$pdfPath && $pdfName) {
        $searchDirs = [
            PROJECT_ROOT . '/facturas/',
            UPLOAD_DIR . '/',
        ];
        foreach ([PROJECT_ROOT . '/batch_uploads', PROJECT_ROOT . '/facturas_test'] as $dir) {
            if (is_dir($dir)) {
                $iter = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($dir));
                foreach ($iter as $file) {
                    if ($file->getFilename() === $pdfName) {
                        $searchDirs[] = $file->getPath() . '/';
                        break;
                    }
                }
            }
        }
        foreach ($searchDirs as $dir) {
            $candidate = $dir . $pdfName;
            if (file_exists($candidate)) {
                $pdfPath = $candidate;
                break;
            }
        }
    }

    if (!$pdfPath) {
        echo json_encode(['ok' => false, 'error' => "PDF no encontrado: $pdfName"]);
        return;
    }

    // Llamar a procesar_pdf.py
    $cmd = '"' . PYTHON_BIN . '" '
         . '"' . PROCESSOR_SCRIPT . '" '
         . '"' . $pdfPath . '"'
         . ' 2>&1';
    $output = shell_exec($cmd);

    if ($output === null) {
        echo json_encode(['ok' => false, 'error' => 'Error al ejecutar el procesador Python']);
        return;
    }

    echo $output;
}

/**
 * Sincroniza un sinónimo al fichero JSON (para compatibilidad con Python)
 */
function _syncSynonymToJson(string $key, array $entry): void
{
    $data = [];
    if (file_exists(SYNONYMS_FILE)) {
        $data = json_decode(file_get_contents(SYNONYMS_FILE), true) ?? [];
    }
    $data[$key] = $entry;
    $json = json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);
    $tmp = SYNONYMS_FILE . '.tmp';
    file_put_contents($tmp, $json);
    rename($tmp, SYNONYMS_FILE);
}

/**
 * Busca el `id_erp` (clave estable del ERP externo) de un artículo
 * dado su id autoincrement.
 *
 * Se usa al guardar sinónimos para almacenar también `articulo_id_erp`,
 * necesario para preservar el vínculo sinónimo↔artículo tras un
 * reimport del dump que reasigne los ids autoincrement. Ver sesión 10q.
 */
function _getArtIdErp($db, int $artId): string
{
    if (!$db || $artId <= 0) {
        return '';
    }
    try {
        $stmt = $db->prepare("SELECT id_erp FROM articulos WHERE id = ?");
        $stmt->bind_param('i', $artId);
        $stmt->execute();
        $res = $stmt->get_result();
        if ($row = $res->fetch_assoc()) {
            return (string)($row['id_erp'] ?? '');
        }
    } catch (Throwable $e) {
        // silencioso: nunca rompe flujo principal
    }
    return '';
}

// ── Importación Masiva ──────────────────────────────────────────────────────

/**
 * Subir ZIP con PDFs y lanzar procesamiento en background
 */
function handleBatchUpload(): void
{
    _cleanOldBatches(1); // Borrar batches de hace más de 1 día

    // Verificar que no hay batch en curso
    $running = _findRunningBatch();
    if ($running) {
        echo json_encode([
            'ok' => false,
            'error' => 'Ya hay un lote en proceso. Espera a que termine.',
            'batch_id' => $running,
        ]);
        return;
    }

    if (!isset($_FILES['zip']) || $_FILES['zip']['error'] !== UPLOAD_ERR_OK) {
        $code = $_FILES['zip']['error'] ?? -1;
        echo json_encode(['ok' => false, 'error' => "Error al subir archivo (código $code)"]);
        return;
    }

    $file = $_FILES['zip'];

    // Validar tipo
    $finfo = finfo_open(FILEINFO_MIME_TYPE);
    $mime = finfo_file($finfo, $file['tmp_name']);
    finfo_close($finfo);

    if (!in_array($mime, ['application/zip', 'application/x-zip-compressed', 'application/octet-stream'])) {
        echo json_encode(['ok' => false, 'error' => "El archivo debe ser un ZIP (recibido: $mime)"]);
        return;
    }

    if ($file['size'] > MAX_ZIP_SIZE) {
        echo json_encode(['ok' => false, 'error' => 'El ZIP excede el tamaño máximo (100 MB)']);
        return;
    }

    // Generar batch ID
    $batchId = date('YmdHis') . '_' . bin2hex(random_bytes(4));

    // Descomprimir ZIP
    $extractDir = BATCH_UPLOADS_DIR . '/' . $batchId;
    @mkdir($extractDir, 0777, true);

    $zip = new ZipArchive();
    if ($zip->open($file['tmp_name']) !== true) {
        echo json_encode(['ok' => false, 'error' => 'No se pudo abrir el archivo ZIP']);
        @rmdir($extractDir);
        return;
    }

    // Extraer solo PDFs (evitar archivos peligrosos)
    $pdfCount = 0;
    for ($i = 0; $i < $zip->numFiles; $i++) {
        $name = $zip->getNameIndex($i);
        // Ignorar directorios y archivos no-PDF
        if (substr($name, -1) === '/' || strtolower(pathinfo($name, PATHINFO_EXTENSION)) !== 'pdf') {
            continue;
        }
        // Usar solo el basename (evitar path traversal)
        $safeName = preg_replace('/[^a-zA-Z0-9._-]/', '_', basename($name));
        // Evitar colisiones
        $dest = $extractDir . '/' . $safeName;
        if (file_exists($dest)) {
            $safeName = pathinfo($safeName, PATHINFO_FILENAME) . '_' . $i . '.pdf';
            $dest = $extractDir . '/' . $safeName;
        }
        // Extraer a memoria y guardar
        $content = $zip->getFromIndex($i);
        if ($content !== false) {
            file_put_contents($dest, $content);
            $pdfCount++;
        }
    }
    $zip->close();

    if ($pdfCount === 0) {
        // Limpiar
        array_map('unlink', glob($extractDir . '/*'));
        @rmdir($extractDir);
        echo json_encode(['ok' => false, 'error' => 'El ZIP no contiene archivos PDF']);
        return;
    }

    // Lanzar Python en background
    $cmd = '"' . PYTHON_BIN . '" '
         . '"' . BATCH_SCRIPT . '" '
         . '"' . $extractDir . '" '
         . '--batch-id ' . $batchId;

    // Windows: start /B para background
    $bgCmd = 'start /B cmd /C "' . $cmd . ' > nul 2>&1"';
    pclose(popen($bgCmd, 'r'));

    echo json_encode([
        'ok'        => true,
        'batch_id'  => $batchId,
        'total_pdfs' => $pdfCount,
    ]);
}

/**
 * Subir PDFs sueltos (desde carpeta o selección múltiple) y lanzar procesamiento
 */
function handleBatchUploadPdfs(): void
{
    _cleanOldBatches(1); // Borrar batches de hace más de 1 día

    // Verificar que no hay batch en curso
    $running = _findRunningBatch();
    if ($running) {
        echo json_encode([
            'ok' => false,
            'error' => 'Ya hay un lote en proceso. Espera a que termine.',
            'batch_id' => $running,
        ]);
        return;
    }

    if (!isset($_FILES['pdfs']) || !is_array($_FILES['pdfs']['name'])) {
        echo json_encode(['ok' => false, 'error' => 'No se recibieron archivos PDF']);
        return;
    }

    $batchId = date('YmdHis') . '_' . bin2hex(random_bytes(4));
    $extractDir = BATCH_UPLOADS_DIR . '/' . $batchId;
    @mkdir($extractDir, 0777, true);

    $pdfCount = 0;
    $fileCount = count($_FILES['pdfs']['name']);

    for ($i = 0; $i < $fileCount; $i++) {
        if ($_FILES['pdfs']['error'][$i] !== UPLOAD_ERR_OK) continue;

        $name = $_FILES['pdfs']['name'][$i];
        if (strtolower(pathinfo($name, PATHINFO_EXTENSION)) !== 'pdf') continue;

        $safeName = preg_replace('/[^a-zA-Z0-9._-]/', '_', basename($name));
        $dest = $extractDir . '/' . $safeName;

        // Evitar colisiones
        if (file_exists($dest)) {
            $safeName = pathinfo($safeName, PATHINFO_FILENAME) . '_' . $i . '.pdf';
            $dest = $extractDir . '/' . $safeName;
        }

        if (move_uploaded_file($_FILES['pdfs']['tmp_name'][$i], $dest)) {
            $pdfCount++;
        }
    }

    if ($pdfCount === 0) {
        array_map('unlink', glob($extractDir . '/*'));
        @rmdir($extractDir);
        echo json_encode(['ok' => false, 'error' => 'No se recibieron archivos PDF válidos']);
        return;
    }

    // Lanzar Python en background
    $cmd = '"' . PYTHON_BIN . '" '
         . '"' . BATCH_SCRIPT . '" '
         . '"' . $extractDir . '" '
         . '--batch-id ' . $batchId;

    $bgCmd = 'start /B cmd /C "' . $cmd . ' > nul 2>&1"';
    pclose(popen($bgCmd, 'r'));

    echo json_encode([
        'ok'        => true,
        'batch_id'  => $batchId,
        'total_pdfs' => $pdfCount,
    ]);
}

/**
 * Consultar estado de un batch
 */
function handleBatchStatus(): void
{
    $batchId = $_GET['batch_id'] ?? '';
    if (!preg_match('/^[a-zA-Z0-9_]+$/', $batchId)) {
        echo json_encode(['ok' => false, 'error' => 'batch_id inválido']);
        return;
    }

    $statusFile = BATCH_STATUS_DIR . '/' . $batchId . '.json';

    if (!file_exists($statusFile)) {
        // Puede que Python aún no haya escrito el primer status
        echo json_encode([
            'ok' => true,
            'estado' => 'iniciando',
            'progreso' => 0, 'total' => 0, 'porcentaje' => 0,
            'actual' => 'Iniciando procesamiento...',
            'procesados_ok' => 0, 'con_error' => 0,
        ]);
        return;
    }

    $content = @file_get_contents($statusFile);
    if ($content === false) {
        echo json_encode(['ok' => false, 'error' => 'Error al leer estado']);
        return;
    }

    $data = json_decode($content, true);
    if ($data === null) {
        echo json_encode(['ok' => true, 'estado' => 'iniciando', 'progreso' => 0, 'total' => 0, 'porcentaje' => 0]);
        return;
    }

    $data['ok'] = true;
    echo json_encode($data, JSON_UNESCAPED_UNICODE);
}

/**
 * Descargar Excel de resultados de un batch
 */
function handleBatchDownload(): void
{
    $batchId = $_GET['batch_id'] ?? '';
    if (!preg_match('/^[a-zA-Z0-9_]+$/', $batchId)) {
        http_response_code(400);
        echo json_encode(['ok' => false, 'error' => 'batch_id inválido']);
        return;
    }

    $excelFile = BATCH_RESULTS_DIR . '/' . $batchId . '.xlsx';

    if (!file_exists($excelFile)) {
        http_response_code(404);
        echo json_encode(['ok' => false, 'error' => 'Excel no encontrado']);
        return;
    }

    header('Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
    header('Content-Disposition: attachment; filename="verabuy_batch_' . $batchId . '.xlsx"');
    header('Content-Length: ' . filesize($excelFile));
    readfile($excelFile);
    exit;
}

/**
 * Buscar si hay algún batch en curso (no completado ni error)
 */
function _findRunningBatch(): ?string
{
    $files = glob(BATCH_STATUS_DIR . '/*.json');
    foreach ($files as $f) {
        $content = @file_get_contents($f);
        if ($content === false) continue;
        $data = json_decode($content, true);
        if ($data && isset($data['estado']) && !in_array($data['estado'], ['completado', 'error'])) {
            // Verificar que no sea un zombie (>30 min sin actualizar)
            if (isset($data['timestamp'])) {
                $ts = strtotime($data['timestamp']);
                if ($ts && (time() - $ts) > 1800) {
                    continue; // Zombie, ignorar
                }
            }
            return pathinfo($f, PATHINFO_FILENAME);
        }
    }
    return null;
}

// ── Auto-Aprendizaje ────────────────────────────────────────────────────────

/**
 * Lista de parsers aprendidos
 */
function handleLearnedParsers(): void
{
    if (!file_exists(LEARNED_RULES_FILE)) {
        echo json_encode(['ok' => true, 'parsers' => [], 'total' => 0]);
        return;
    }

    $data = json_decode(file_get_contents(LEARNED_RULES_FILE), true);
    if ($data === null) {
        echo json_encode(['ok' => true, 'parsers' => [], 'total' => 0]);
        return;
    }

    $list = [];
    foreach ($data as $name => $config) {
        $list[] = [
            'nombre'       => $name,
            'species'      => $config['species'] ?? '',
            'score'        => $config['score'] ?? 0,
            'decision'     => $config['decision'] ?? '',
            'fecha'        => $config['fecha_generacion'] ?? '',
            'num_pdfs'     => $config['num_pdfs_analizados'] ?? 0,
            'activo'       => $config['activo'] ?? true,
            'keywords'     => $config['keywords'] ?? [],
        ];
    }

    echo json_encode(['ok' => true, 'parsers' => $list, 'total' => count($list)]);
}

/**
 * Pendientes de revisión
 */
function handlePendingReview(): void
{
    if (!file_exists(PENDING_REVIEW_FILE)) {
        echo json_encode(['ok' => true, 'pendientes' => []]);
        return;
    }

    $data = json_decode(file_get_contents(PENDING_REVIEW_FILE), true);
    echo json_encode(['ok' => true, 'pendientes' => $data['pendientes'] ?? []]);
}

/**
 * Activar/desactivar un parser aprendido
 */
function handleToggleParser(): void
{
    $input = json_decode(file_get_contents('php://input'), true);
    $name = $input['nombre'] ?? '';

    if (!$name || !file_exists(LEARNED_RULES_FILE)) {
        echo json_encode(['ok' => false, 'error' => 'Parser no encontrado']);
        return;
    }

    $data = json_decode(file_get_contents(LEARNED_RULES_FILE), true);
    if (!isset($data[$name])) {
        echo json_encode(['ok' => false, 'error' => 'Parser no encontrado']);
        return;
    }

    $data[$name]['activo'] = !($data[$name]['activo'] ?? true);
    $json = json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);
    file_put_contents(LEARNED_RULES_FILE, $json);

    $state = $data[$name]['activo'] ? 'activado' : 'desactivado';
    echo json_encode(['ok' => true, 'message' => "Parser $name $state", 'activo' => $data[$name]['activo']]);
}

/**
 * Generar hoja de orden + órdenes a partir de datos revisados por el usuario
 */
function handleGenerarOrden(): void
{
    $input = json_decode(file_get_contents('php://input'), true);
    if (!$input) {
        echo json_encode(['ok' => false, 'error' => 'Datos no proporcionados']);
        return;
    }

    $header = $input['header'] ?? [];
    $lines = $input['lines'] ?? [];

    if (empty($header['invoice_number'])) {
        echo json_encode(['ok' => false, 'error' => 'Número de factura requerido']);
        return;
    }

    $db = get_db();
    if (!$db) {
        echo json_encode(['ok' => false, 'error' => 'Base de datos no disponible']);
        return;
    }

    $invoice = $header['invoice_number'];
    $providerId = (int)($header['provider_id'] ?? 0);
    $awb = $header['awb'] ?? '';

    // Verificar si ya existe
    $stmt = $db->prepare("SELECT id FROM hoja_orden WHERE ref_albaran_proveedor = ? AND id_proveedor = ?");
    $stmt->bind_param('si', $invoice, $providerId);
    $stmt->execute();
    if ($stmt->get_result()->fetch_assoc()) {
        echo json_encode(['ok' => false, 'error' => "Ya existe una hoja de orden para factura $invoice"]);
        return;
    }

    // Crear hoja de orden
    $stmt = $db->prepare("INSERT INTO hoja_orden (ref_albaran_proveedor, id_proveedor, vuelo, tipo_producto, serie, creador_id) VALUES (?, ?, ?, 'Flor', 'CO', 1)");
    $stmt->bind_param('sis', $invoice, $providerId, $awb);
    $stmt->execute();
    $hojaId = $db->insert_id;

    // Crear líneas de orden
    $ordenesCount = 0;
    $stmt = $db->prepare("INSERT INTO ordenes (id_hoja_orden, unidades, cantidad_cajas, cantidad_paquetes_caja, precio_compra, lote, creador_id) VALUES (?, ?, ?, ?, ?, ?, 1)");

    foreach ($lines as $line) {
        $artId = (int)($line['articulo_id'] ?? 0);
        if (!$artId) continue; // Skip lines without article match

        $stems = (int)($line['stems'] ?? 0);
        $spb = (int)($line['stems_per_bunch'] ?? 0);
        $bunches = (int)($line['bunches'] ?? 0);
        if ($bunches == 0 && $spb > 0 && $stems > 0) {
            $bunches = intdiv($stems, $spb);
        }
        $total = round((float)($line['line_total'] ?? 0), 2);
        $lote = (string)$artId;

        $stmt->bind_param('iiidsi', $hojaId, $stems, $bunches, $spb, $total, $lote);
        $stmt->execute();
        $ordenesCount++;
    }

    echo json_encode([
        'ok' => true,
        'hoja_id' => $hojaId,
        'ordenes_count' => $ordenesCount,
        'message' => "Hoja de orden #$hojaId creada con $ordenesCount líneas",
    ]);
}

/* ==========================================================================
 * Shadow mode: captura de propuestas y decisiones para análisis offline.
 *
 * El formato es una línea JSON por entry en `shadow_log.jsonl`. Dos tipos:
 *   - "propuesta": una por línea de factura, con lo que el matcher sugirió
 *     ANTES de que el operador tocara nada. Clave `synonym_key` para cruzar
 *     con futuras decisiones.
 *   - "decision": confirm/correct del operador. Lleva `proposed_articulo_id`
 *     y `decided_articulo_id` para medir accuracy real en producción.
 *
 * `tools/shadow_report.py` agrega ambos tipos y produce KPIs de shadow mode.
 * ========================================================================== */

/**
 * Canonicaliza la variedad para construir la synonym_key: colapsa
 * puntuación y caracteres no alfanuméricos a espacios y compacta.
 * DEBE coincidir con `normalize_variety_key` en `src/models.py` y
 * `_normalizeVariety` en `web/assets/app.js`.
 */
function _normalizeVarietyKey(string $variety): string
{
    $v = mb_strtoupper($variety);
    $v = preg_replace('/[^A-Z0-9 ]+/u', ' ', $v);
    $v = preg_replace('/\s+/u', ' ', $v);
    return trim($v);
}

/**
 * Construye la synonym_key igual que `SynonymStore._key` en Python:
 *   <provider_id>|<species>|<normalize(variety)>|<size>|<spb>|<grade.upper>
 */
function _shadowSynKey(int $providerId, array $line): string
{
    $species = $line['species'] ?? '';
    $variety = _normalizeVarietyKey($line['variety'] ?? '');
    $size    = (int)($line['size'] ?? 0);
    $spb     = (int)($line['stems_per_bunch'] ?? 0);
    $grade   = strtoupper($line['grade'] ?? '');
    return "{$providerId}|{$species}|{$variety}|{$size}|{$spb}|{$grade}";
}

/**
 * Añade una entry al shadow log. Silencioso en error — nunca debe romper
 * la respuesta al cliente.
 */
function _shadowLogAppend(array $entry): void
{
    $entry['ts'] = date('c');
    $line = json_encode($entry, JSON_UNESCAPED_UNICODE);
    if ($line === false) {
        return;
    }
    @file_put_contents(SHADOW_LOG_FILE, $line . "\n", FILE_APPEND | LOCK_EX);
}

/**
 * Escribe una entry "propuesta" por cada línea con articulo_id en el
 * resultado del procesador. Ignora padres de mixed_box (sin articulo_id
 * propio) y líneas sin match.
 */
function _shadowLogProposals(array $result, string $pdfName): void
{
    if (empty($result['ok'])) {
        return;
    }
    $header = $result['header'] ?? [];
    $providerId = (int)($header['provider_id'] ?? 0);
    $invoice    = $header['invoice_number'] ?? '';
    $lines      = $result['lines'] ?? [];

    // Aplanar: si hay mixed_parent, logueamos sus hijas (cada una es una
    // propuesta independiente). El padre es solo agregado de la UI.
    $flat = [];
    foreach ($lines as $l) {
        if (($l['row_type'] ?? '') === 'mixed_parent' && !empty($l['children'])) {
            foreach ($l['children'] as $child) {
                $flat[] = $child;
            }
        } else {
            $flat[] = $l;
        }
    }

    foreach ($flat as $idx => $l) {
        $artId = (int)($l['articulo_id'] ?? 0);
        if (!$artId) {
            // Sin propuesta del matcher: no hay nada que shadowear. Igual
            // logueamos un entry para saber que hubo un sin_match/sin_parser
            // y poder analizar el pipeline completo.
        }
        _shadowLogAppend([
            'evento'                => 'propuesta',
            'pdf'                   => basename($pdfName),
            'invoice'               => $invoice,
            'provider_id'           => $providerId,
            'provider_name'         => $header['provider_name'] ?? '',
            'line_idx'              => $idx,
            'synonym_key'           => _shadowSynKey($providerId, $l),
            'species'               => $l['species'] ?? '',
            'variety'               => $l['variety'] ?? '',
            'size'                  => (int)($l['size'] ?? 0),
            'stems_per_bunch'       => (int)($l['stems_per_bunch'] ?? 0),
            'grade'                 => $l['grade'] ?? '',
            'proposed_articulo_id'  => $artId,
            'proposed_articulo_name'=> $l['articulo_name'] ?? '',
            'match_status'          => $l['match_status'] ?? '',
            'match_method'          => $l['match_method'] ?? '',
            'link_confidence'       => (float)($l['link_confidence'] ?? 0),
            'match_confidence'      => (float)($l['match_confidence'] ?? 0),
            'candidate_margin'      => (float)($l['candidate_margin'] ?? 0),
            'review_lane'           => $l['review_lane'] ?? '',
            'reasons'               => $l['match_reasons'] ?? [],
            'penalties'             => $l['match_penalties'] ?? [],
        ]);
    }
}

/**
 * Escribe una entry "decision" cuando el operador confirma o corrige.
 */
function _shadowLogDecision(string $action, array $input,
                            int $proposedArtId, int $decidedArtId,
                            string $decidedArtName = ''): void
{
    _shadowLogAppend([
        'evento'                => 'decision',
        'action'                => $action,
        'synonym_key'           => $input['key'] ?? '',
        'proposed_articulo_id'  => $proposedArtId,
        'decided_articulo_id'   => $decidedArtId,
        'decided_articulo_name' => $decidedArtName,
        'provider_id'           => (int)($input['provider_id'] ?? 0),
        'species'               => $input['species'] ?? '',
        'variety'               => $input['variety'] ?? '',
        'size'                  => (int)($input['size'] ?? 0),
        'stems_per_bunch'       => (int)($input['stems_per_bunch'] ?? 0),
        'grade'                 => $input['grade'] ?? '',
    ]);
}
