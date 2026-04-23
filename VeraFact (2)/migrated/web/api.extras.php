<?php
/**
 * VeraFact — Endpoints adicionales (MySQL)
 *
 * Activar añadiendo al principio del switch de web/api.php:
 *     require_once __DIR__ . '/api.extras.php';
 *
 * Requisitos:
 *   - web/db_config.php con get_db(): ?mysqli  (ya existe en el proyecto)
 *   - Tablas: articulos, historial, facturas_lineas
 *
 * Endpoints:
 *   GET  api.php?action=recent_invoices&limit=5
 *   GET  api.php?action=suggest_candidates&species=&variety=&size=&spb=&provider_id=&limit=
 *   GET  api.php?action=price_anomalies_timeline&articulo_id=NNN&days=90
 */

// Evita doble-ejecución si se incluye dos veces
if (!defined('VF_EXTRAS_LOADED')) {
    define('VF_EXTRAS_LOADED', true);

    // db_config.php ya está cargado por api.php antes de llegar aquí
    // pero por seguridad:
    if (!function_exists('get_db')) {
        $cfg = __DIR__ . '/db_config.php';
        if (is_file($cfg)) require_once $cfg;
    }

    $VF_ACTION = $_GET['action'] ?? '';

    // ═══════════════════════════════════════════════════════════════
    // Helper: respuesta JSON y exit
    // ═══════════════════════════════════════════════════════════════
    $vf_json = function(array $data, int $status = 200) {
        if (!headers_sent()) {
            http_response_code($status);
            header('Content-Type: application/json; charset=utf-8');
        }
        echo json_encode($data, JSON_UNESCAPED_UNICODE);
        exit;
    };

    // ═══════════════════════════════════════════════════════════════
    // 1) RECENT INVOICES — últimas N facturas de la tabla historial
    // ═══════════════════════════════════════════════════════════════
    if ($VF_ACTION === 'recent_invoices') {
        $limit = (int)($_GET['limit'] ?? 5);
        if ($limit < 1 || $limit > 50) $limit = 5;

        $db = get_db();
        if (!$db) $vf_json(['ok' => false, 'error' => 'DB no disponible', 'invoices' => []], 503);

        $sql = "SELECT numero_factura, pdf_nombre, proveedor, id_proveedor,
                       total_usd, lineas, ok_count, sin_match, fecha_proceso
                FROM historial
                ORDER BY fecha_proceso DESC, id DESC
                LIMIT ?";
        $stmt = $db->prepare($sql);
        if (!$stmt) $vf_json(['ok' => false, 'error' => 'Query prepare falló: ' . $db->error], 500);
        $stmt->bind_param('i', $limit);
        $stmt->execute();
        $res = $stmt->get_result();

        $invoices = [];
        while ($row = $res->fetch_assoc()) {
            $invoices[] = [
                'fecha'       => $row['fecha_proceso'] ?: '',
                'invoice_key' => $row['numero_factura'] ?: '',
                'provider'    => $row['proveedor'] ?: '',
                'provider_id' => (int)$row['id_proveedor'],
                'pdf'         => $row['pdf_nombre'] ?: '',
                'lineas'      => (int)$row['lineas'],
                'ok'          => (int)$row['ok_count'],
                'sin_match'   => (int)$row['sin_match'],
                'total_usd'   => (float)$row['total_usd'],
            ];
        }
        $stmt->close();

        $vf_json(['ok' => true, 'invoices' => $invoices]);
    }

    // ═══════════════════════════════════════════════════════════════
    // 2) SUGGEST CANDIDATES — top-N del catálogo MySQL
    //
    // Pipeline:
    //   a) Traducir especie EN→ES (ROSES→ROSA, etc.)
    //   b) Prefiltro SQL por familia (si hay) + LIKE por variedad
    //      — limita a ~500 filas para no pasar scoring a 44k artículos
    //   c) Scoring en PHP sobre esas 500 filas (palabra a palabra +
    //      bonus especie/talla/SPB/color/marca si están)
    // ═══════════════════════════════════════════════════════════════
    if ($VF_ACTION === 'suggest_candidates') {
        $species    = trim((string)($_GET['species']    ?? ''));
        $variety    = trim((string)($_GET['variety']    ?? ''));
        $size       = (int)($_GET['size']      ?? 0);
        $spb        = (int)($_GET['spb']       ?? 0);
        $providerId = (int)($_GET['provider_id'] ?? 0);
        $limit      = (int)($_GET['limit']     ?? 5);
        if ($limit < 1 || $limit > 20) $limit = 5;

        if ($variety === '') $vf_json(['ok' => true, 'candidates' => []]);

        $db = get_db();
        if (!$db) $vf_json(['ok' => false, 'error' => 'DB no disponible', 'candidates' => []], 503);

        // Normalizador
        $norm = function($s) {
            $s = mb_strtoupper((string)$s, 'UTF-8');
            $s = preg_replace('/[^A-Z0-9 ]+/u', ' ', $s);
            $s = preg_replace('/\s+/', ' ', $s);
            return trim($s);
        };
        $nVar = $norm($variety);
        $nSpc = $norm($species);

        // Mapa EN → ES para familia (columna articulos.familia está en español)
        $spcMap = [
            'ROSES'         => 'ROSA',
            'CARNATIONS'    => 'CLAVEL',
            'HYDRANGEAS'    => 'HORTENSIA',
            'HYDRANGEA'     => 'HORTENSIA',
            'GYPSOPHILA'    => 'PANICULATA',
            'ALSTROEMERIA'  => 'ALSTROEMERIA',
            'CHRYSANTHEMUM' => 'CRISANTEMO',
            'CHRYSANTHEMUMS'=> 'CRISANTEMO',
        ];
        $familiaEs = $spcMap[$nSpc] ?? $nSpc;  // si ya viene en ES, se queda

        // Primera palabra significativa de la variedad para LIKE
        $words = array_values(array_filter(explode(' ', $nVar), fn($w) => strlen($w) >= 3));
        $likeToken = $words[0] ?? $nVar;

        // Prefiltro SQL
        $whereParts = [];
        $params = [];
        $types = '';

        if ($familiaEs !== '') {
            $whereParts[] = 'UPPER(familia) = ?';
            $params[] = $familiaEs;
            $types .= 's';
        }
        $whereParts[] = '(UPPER(nombre) LIKE ? OR UPPER(variedad) LIKE ?)';
        $likeParam = '%' . $likeToken . '%';
        $params[] = $likeParam;
        $params[] = $likeParam;
        $types .= 'ss';

        // Proveedor: bonus, no filtro duro — no lo metemos en WHERE
        $whereSql = $whereParts ? ('WHERE ' . implode(' AND ', $whereParts)) : '';

        $sql = "SELECT id, id_erp, referencia, nombre, familia, variedad,
                       tamano, paquete, color, marca, id_proveedor
                FROM articulos
                $whereSql
                LIMIT 500";

        $stmt = $db->prepare($sql);
        if (!$stmt) $vf_json(['ok' => false, 'error' => 'Query prepare falló: ' . $db->error], 500);
        if ($types) $stmt->bind_param($types, ...$params);
        $stmt->execute();
        $res = $stmt->get_result();

        // Scoring
        $scored = [];
        $vwords = array_values(array_filter(explode(' ', $nVar), fn($w) => strlen($w) >= 2));
        $vwCount = count($vwords);

        while ($row = $res->fetch_assoc()) {
            // Haystack: nombre + variedad + color + marca
            $hay = $norm(
                ($row['nombre']   ?? '') . ' ' .
                ($row['variedad'] ?? '') . ' ' .
                ($row['color']    ?? '') . ' ' .
                ($row['marca']    ?? '')
            );
            if ($hay === '') continue;

            $score = 0;

            // Palabras de variedad (60 pts max)
            if ($vwCount > 0) {
                $matched = 0;
                foreach ($vwords as $w) {
                    if (strpos($hay, $w) !== false) $matched++;
                }
                $score += ($matched / $vwCount) * 60;
            }

            // Bonus especie/familia (15 pts)
            if ($familiaEs !== '' && strcasecmp((string)$row['familia'], $familiaEs) === 0) {
                $score += 15;
            }

            // Bonus talla (10 pts) — articulos.tamano puede ser "50" o "50CM"
            if ($size > 0) {
                $tam = preg_replace('/[^0-9]/', '', (string)$row['tamano']);
                if ($tam !== '' && (int)$tam === $size) $score += 10;
            }

            // Bonus SPB (8 pts)
            if ($spb > 0 && (int)$row['paquete'] === $spb) {
                $score += 8;
            }

            // Bonus proveedor (7 pts)
            if ($providerId > 0 && (int)$row['id_proveedor'] === $providerId) {
                $score += 7;
            }

            if ($score < 25) continue;

            $scored[] = [
                'articulo_id'     => (int)$row['id'],
                'articulo_id_erp' => (string)($row['id_erp'] ?? ''),
                'referencia'      => (string)($row['referencia'] ?? ''),
                'nombre'          => (string)($row['nombre'] ?? ''),
                'familia'         => (string)($row['familia'] ?? ''),
                'tamano'          => (string)($row['tamano'] ?? ''),
                'paquete'         => (int)($row['paquete'] ?? 0),
                'score'           => (int)round($score),
            ];
        }
        $stmt->close();

        usort($scored, fn($a, $b) => $b['score'] - $a['score']);
        $candidates = array_slice($scored, 0, $limit);

        $vf_json(['ok' => true, 'candidates' => $candidates]);
    }

    // ═══════════════════════════════════════════════════════════════
    // 3) PRICE ANOMALIES TIMELINE — serie histórica de precio_stem
    //    de facturas_lineas cruzada con historial para la fecha
    // ═══════════════════════════════════════════════════════════════
    if ($VF_ACTION === 'price_anomalies_timeline') {
        $articuloId = (int)($_GET['articulo_id'] ?? 0);
        $days       = (int)($_GET['days'] ?? 90);
        if ($days < 7 || $days > 365) $days = 90;

        if ($articuloId <= 0) {
            $vf_json(['ok' => false, 'error' => 'articulo_id requerido'], 400);
        }

        $db = get_db();
        if (!$db) $vf_json(['ok' => false, 'error' => 'DB no disponible', 'timeline' => []], 503);

        $sql = "SELECT DATE(h.fecha_proceso) AS d,
                       fl.precio_stem        AS price,
                       h.numero_factura      AS invoice
                FROM facturas_lineas fl
                JOIN historial h ON h.numero_factura = fl.numero_factura
                WHERE fl.id_articulo = ?
                  AND h.fecha_proceso >= DATE_SUB(CURDATE(), INTERVAL ? DAY)
                ORDER BY h.fecha_proceso ASC";
        $stmt = $db->prepare($sql);
        if (!$stmt) $vf_json(['ok' => false, 'error' => 'Query prepare falló: ' . $db->error], 500);
        $stmt->bind_param('ii', $articuloId, $days);
        $stmt->execute();
        $res = $stmt->get_result();

        $series = [];
        while ($row = $res->fetch_assoc()) {
            $p = (float)$row['price'];
            if ($p <= 0) continue;
            $series[] = [
                'date'    => (string)$row['d'],
                'price'   => round($p, 4),
                'invoice' => (string)($row['invoice'] ?? ''),
            ];
        }
        $stmt->close();

        // Z-score
        $prices = array_column($series, 'price');
        $n = count($prices);
        $mean = $n ? array_sum($prices) / $n : 0;
        $var = 0;
        foreach ($prices as $p) $var += ($p - $mean) ** 2;
        $std = $n > 1 ? sqrt($var / ($n - 1)) : 0;

        $timeline = array_map(function($p) use ($mean, $std) {
            $z = $std > 0 ? abs(($p['price'] - $mean) / $std) : 0;
            return [
                'date'    => $p['date'],
                'price'   => $p['price'],
                'invoice' => $p['invoice'],
                'anomaly' => $z > 2.0,
                'z'       => round($z, 2),
            ];
        }, $series);

        $vf_json([
            'ok'       => true,
            'timeline' => $timeline,
            'stats'    => [
                'mean'  => round($mean, 4),
                'std'   => round($std, 4),
                'count' => $n,
                'min'   => $n ? min($prices) : 0,
                'max'   => $n ? max($prices) : 0,
            ],
        ]);
    }

} // VF_EXTRAS_LOADED
