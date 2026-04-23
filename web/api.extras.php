<?php
/**
 * VeraFact — Endpoints opcionales adicionales
 *
 * Para activar: añadir al final de web/api.php:
 *
 *     require_once __DIR__ . '/api.extras.php';
 *
 * Endpoints añadidos:
 *   GET  api.php?action=recent_invoices&limit=5
 *   GET  api.php?action=suggest_candidates&species=ROSES&variety=FREEDOM&size=50&spb=25&provider_id=2222&limit=5
 *   GET  api.php?action=price_anomalies_timeline&articulo_id=12345&days=90
 */

// ═══════════════════════════════════════════════════════════════
// 1) RECENT INVOICES
// ═══════════════════════════════════════════════════════════════
if (isset($_GET['action']) && $_GET['action'] === 'recent_invoices') {
    header('Content-Type: application/json; charset=utf-8');
    $limit = (int)($_GET['limit'] ?? 5);
    if ($limit < 1 || $limit > 50) $limit = 5;

    $paths = [
        __DIR__ . '/../datasets/invoice_history.json',
        __DIR__ . '/../data/invoice_history.json',
    ];
    $histFile = null;
    foreach ($paths as $p) if (is_file($p)) { $histFile = $p; break; }

    if (!$histFile) {
        echo json_encode(['ok' => true, 'invoices' => []]);
        exit;
    }

    $raw = @file_get_contents($histFile);
    $hist = json_decode($raw, true) ?: [];
    usort($hist, fn($a, $b) => strcmp($b['fecha'] ?? '', $a['fecha'] ?? ''));
    $out = array_slice($hist, 0, $limit);

    $invoices = array_map(fn($h) => [
        'fecha'       => $h['fecha'] ?? '',
        'invoice_key' => $h['invoice_key'] ?? '',
        'provider'    => $h['provider'] ?? '',
        'pdf'         => $h['pdf'] ?? '',
        'pdf_path'    => $h['pdf_path'] ?? '',
        'lineas'      => (int)($h['lineas'] ?? 0),
        'ok'          => (int)($h['ok'] ?? 0),
        'sin_match'   => (int)($h['sin_match'] ?? 0),
        'total_usd'   => (float)($h['total_usd'] ?? 0),
    ], $out);

    echo json_encode(['ok' => true, 'invoices' => $invoices]);
    exit;
}

// ═══════════════════════════════════════════════════════════════
// 2) SUGGEST CANDIDATES (MySQL)
// Top-N artículos candidatos para una línea sin match, por similitud
// de nombre + match de familia/talla/SPB. Consulta la tabla
// `articulos` del catálogo VeraBuy (~44k filas). Pre-filtra por
// familia (ROSA/CLAVEL/PANICULATA/…) y talla para traer ≤500 filas
// al scoring PHP.
// ═══════════════════════════════════════════════════════════════
if (isset($_GET['action']) && $_GET['action'] === 'suggest_candidates') {
    header('Content-Type: application/json; charset=utf-8');

    $species    = trim($_GET['species']    ?? '');
    $variety    = trim($_GET['variety']    ?? '');
    $size       = (int)($_GET['size']      ?? 0);
    $spb        = (int)($_GET['spb']       ?? 0);
    $providerId = (int)($_GET['provider_id'] ?? 0);
    $limit      = (int)($_GET['limit']     ?? 5);
    if ($limit < 1 || $limit > 20) $limit = 5;

    if (!$variety) {
        echo json_encode(['ok' => true, 'candidates' => []]);
        exit;
    }

    $db = get_db();
    if (!$db) {
        echo json_encode(['ok' => false, 'error' => 'DB no disponible']);
        exit;
    }

    // species (parser, inglés) → familia (catálogo, español)
    $SPC_TO_FAMILIA = [
        'ROSES'         => 'ROSA',
        'CARNATIONS'    => 'CLAVEL',
        'HYDRANGEAS'    => 'HORTENSIA',
        'GYPSOPHILA'    => 'PANICULATA',
        'ALSTROEMERIA'  => 'ALSTROEMERIA',
        'CHRYSANTHEMUM' => 'CRISANTEMO',
    ];
    $familia = $SPC_TO_FAMILIA[mb_strtoupper($species, 'UTF-8')] ?? '';

    $norm = function($s) {
        $s = mb_strtoupper($s ?? '', 'UTF-8');
        $s = preg_replace('/[^A-Z0-9 ]+/', ' ', $s);
        $s = preg_replace('/\s+/', ' ', $s);
        return trim($s);
    };
    $nVar = $norm($variety);

    // Pre-filtro SQL: LIKE del token principal de variety (clave del
    // matching), refinado con familia y/o talla cuando los hay. Si no
    // devuelve nada, fallback progresivo a filtros más laxos.
    $rows = [];
    $seen = [];
    $fetch = function(mysqli_stmt $stmt) use (&$rows, &$seen) {
        $stmt->execute();
        $res = $stmt->get_result();
        while ($r = $res->fetch_assoc()) {
            $id = (int)($r['id'] ?? 0);
            if ($id && !isset($seen[$id])) { $seen[$id] = 1; $rows[] = $r; }
        }
        $stmt->close();
    };
    $cols = "id, id_erp, referencia, nombre, familia, tamano, paquete, color, marca, variedad, id_proveedor";

    $tokens = array_values(array_filter(explode(' ', $nVar), fn($t) => strlen($t) >= 3));
    $mainTok = $tokens ? '%' . $tokens[0] . '%' : null;

    // 1) LIKE(token) + familia + talla exacta — el subconjunto más preciso
    if ($mainTok && $familia && $size > 0) {
        $sizeStr = (string)$size;
        $sizeCm  = $sizeStr . 'CM';
        $stmt = $db->prepare("SELECT $cols FROM articulos
            WHERE familia = ?
              AND (tamano = ? OR tamano = ?)
              AND (UPPER(nombre) LIKE ? OR UPPER(variedad) LIKE ?)
            LIMIT 200");
        $stmt->bind_param('sssss', $familia, $sizeStr, $sizeCm, $mainTok, $mainTok);
        $fetch($stmt);
    }
    // 2) LIKE(token) + familia (sin talla)
    if ($mainTok && $familia) {
        $stmt = $db->prepare("SELECT $cols FROM articulos
            WHERE familia = ?
              AND (UPPER(nombre) LIKE ? OR UPPER(variedad) LIKE ?)
            LIMIT 300");
        $stmt->bind_param('sss', $familia, $mainTok, $mainTok);
        $fetch($stmt);
    }
    // 3) LIKE(token) global (sin familia) — cubre typos de species
    if ($mainTok) {
        $stmt = $db->prepare("SELECT $cols FROM articulos
            WHERE UPPER(nombre) LIKE ? OR UPPER(variedad) LIKE ?
            LIMIT 300");
        $stmt->bind_param('ss', $mainTok, $mainTok);
        $fetch($stmt);
    }
    // 4) Fallback: familia + talla sin LIKE — por si variety es muy corta
    if (!$rows && $familia && $size > 0) {
        $sizeStr = (string)$size;
        $sizeCm  = $sizeStr . 'CM';
        $stmt = $db->prepare("SELECT $cols FROM articulos
            WHERE familia = ? AND (tamano = ? OR tamano = ?) LIMIT 300");
        $stmt->bind_param('sss', $familia, $sizeStr, $sizeCm);
        $fetch($stmt);
    }

    // Scoring en PHP. Busca tokens de variety contra el haystack
    // nombre+variedad+color (cubre nombres truncados y matches por
    // campo estructurado cuando el nombre canónico quedó cortado).
    $scored = [];
    $vWords = array_values(array_filter(explode(' ', $nVar), fn($t) => strlen($t) >= 3));
    foreach ($rows as $art) {
        $haystack = $norm(
            ($art['nombre'] ?? '')   . ' ' .
            ($art['variedad'] ?? '') . ' ' .
            ($art['color'] ?? '')
        );
        if (!$haystack) continue;

        $score = 0;
        $matched = 0;
        foreach ($vWords as $w) {
            if (strpos($haystack, $w) !== false) $matched++;
        }
        if (count($vWords) > 0) $score += ($matched / count($vWords)) * 60;

        if ($familia && strcasecmp($art['familia'] ?? '', $familia) === 0) $score += 15;

        if ($size > 0) {
            $tam = (string)($art['tamano'] ?? '');
            if ($tam === (string)$size || $tam === $size . 'CM') $score += 12;
        }
        if ($spb > 0 && (int)($art['paquete'] ?? 0) === $spb) $score += 10;

        if ($providerId > 0 && (int)($art['id_proveedor'] ?? 0) === $providerId) $score += 8;

        if ($score < 25) continue;

        $scored[] = [
            'articulo_id'     => (int)($art['id'] ?? 0),
            'articulo_id_erp' => (string)($art['id_erp'] ?? ''),
            'referencia'      => (string)($art['referencia'] ?? ''),
            'nombre'          => (string)($art['nombre'] ?? ''),
            'score'           => (int)round($score),
        ];
    }

    usort($scored, fn($a, $b) => $b['score'] - $a['score']);
    $candidates = array_slice($scored, 0, $limit);

    echo json_encode(['ok' => true, 'candidates' => $candidates]);
    exit;
}

// ═══════════════════════════════════════════════════════════════
// 3) PRICE ANOMALIES TIMELINE
// Serie histórica de precio para un articulo_id (últimos N días)
// Formato de salida: [{date:"YYYY-MM-DD", price:0.45, anomaly:false}, …]
// ═══════════════════════════════════════════════════════════════
if (isset($_GET['action']) && $_GET['action'] === 'price_anomalies_timeline') {
    header('Content-Type: application/json; charset=utf-8');

    $articuloId = (int)($_GET['articulo_id'] ?? 0);
    $days       = (int)($_GET['days'] ?? 90);
    if ($days < 7 || $days > 365) $days = 90;
    if (!$articuloId) {
        echo json_encode(['ok' => false, 'error' => 'articulo_id requerido']);
        exit;
    }

    // Buscar historial de precios (ajusta ruta según tu proyecto)
    $paths = [
        __DIR__ . '/../datasets/price_history.json',
        __DIR__ . '/../data/price_history.json',
    ];
    $file = null;
    foreach ($paths as $p) if (is_file($p)) { $file = $p; break; }

    // Fallback: extraer precios del invoice_history.json
    if (!$file) {
        $histPaths = [
            __DIR__ . '/../datasets/invoice_history.json',
            __DIR__ . '/../data/invoice_history.json',
        ];
        $histFile = null;
        foreach ($histPaths as $p) if (is_file($p)) { $histFile = $p; break; }

        if (!$histFile) {
            echo json_encode(['ok' => true, 'timeline' => [], 'note' => 'Sin datos históricos']);
            exit;
        }

        $hist = json_decode(@file_get_contents($histFile), true) ?: [];
        $series = [];
        foreach ($hist as $inv) {
            if (!isset($inv['lines'])) continue;
            foreach ($inv['lines'] as $l) {
                if (($l['articulo_id'] ?? 0) != $articuloId) continue;
                $series[] = [
                    'date'  => substr($inv['fecha'] ?? '', 0, 10),
                    'price' => round((float)($l['price_per_stem'] ?? 0), 4),
                ];
            }
        }
    } else {
        $series = json_decode(@file_get_contents($file), true) ?: [];
        $series = array_filter($series, fn($p) => ($p['articulo_id'] ?? 0) == $articuloId);
    }

    // Filtrar por ventana de días
    $cutoff = date('Y-m-d', strtotime("-$days days"));
    $series = array_filter($series, fn($p) => ($p['date'] ?? '') >= $cutoff);
    usort($series, fn($a, $b) => strcmp($a['date'] ?? '', $b['date'] ?? ''));

    // Detección de anomalía — z-score simple
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
            'price'   => round($p['price'], 4),
            'anomaly' => $z > 2.0,
            'z'       => round($z, 2),
        ];
    }, array_values($series));

    echo json_encode([
        'ok'       => true,
        'timeline' => $timeline,
        'stats'    => [
            'mean'  => round($mean, 4),
            'std'   => round($std, 4),
            'count' => $n,
        ],
    ]);
    exit;
}
