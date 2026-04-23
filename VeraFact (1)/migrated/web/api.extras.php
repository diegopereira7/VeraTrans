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
// 2) SUGGEST CANDIDATES
// Top-N artículos candidatos para una línea sin match, por similitud
// de nombre + match de especie/talla.
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

    // Cargar catálogo — ajusta la ruta según tu proyecto
    $catalogPaths = [
        __DIR__ . '/../datasets/articulos.json',
        __DIR__ . '/../data/articulos.json',
        __DIR__ . '/../datasets/catalog.json',
    ];
    $catalogFile = null;
    foreach ($catalogPaths as $p) if (is_file($p)) { $catalogFile = $p; break; }

    if (!$catalogFile) {
        echo json_encode(['ok' => false, 'error' => 'Catálogo no encontrado. Ajusta rutas en api.extras.php']);
        exit;
    }

    $catalog = json_decode(@file_get_contents($catalogFile), true) ?: [];
    // Normalizador simple
    $norm = function($s) {
        $s = mb_strtoupper($s ?? '', 'UTF-8');
        $s = preg_replace('/[^A-Z0-9 ]+/', ' ', $s);
        $s = preg_replace('/\s+/', ' ', $s);
        return trim($s);
    };
    $nVar = $norm($variety);
    $nSpc = $norm($species);

    // Scoring simple: coincidencia palabra a palabra del nombre +
    // bonus por especie + bonus por talla si aparece en el nombre
    $scored = [];
    foreach ($catalog as $art) {
        $name = $art['nombre'] ?? $art['name'] ?? '';
        $nName = $norm($name);
        if (!$nName) continue;

        $score = 0;
        // Similitud de variedad
        $vwords = array_filter(explode(' ', $nVar));
        $matched = 0;
        foreach ($vwords as $w) {
            if (strlen($w) >= 3 && strpos($nName, $w) !== false) $matched++;
        }
        if (count($vwords) > 0) $score += ($matched / count($vwords)) * 60;

        // Bonus especie
        if ($nSpc && strpos($nName, $nSpc) !== false) $score += 15;
        // Sinónimos comunes en ES/EN
        $spcSyn = ['ROSES' => 'ROSA', 'CARNATIONS' => 'CLAVEL', 'HYDRANGEAS' => 'HORTENSIA'];
        if ($nSpc && isset($spcSyn[$nSpc]) && strpos($nName, $spcSyn[$nSpc]) !== false) $score += 15;

        // Bonus talla
        if ($size > 0 && (strpos($nName, $size . 'CM') !== false || strpos($nName, ' ' . $size . ' ') !== false)) $score += 10;
        // Bonus SPB
        if ($spb > 0 && (strpos($nName, $spb . 'U') !== false || strpos($nName, $spb . 'T') !== false)) $score += 8;

        if ($score < 25) continue;

        $scored[] = [
            'articulo_id'     => $art['id'] ?? $art['articulo_id'] ?? 0,
            'articulo_id_erp' => $art['id_erp'] ?? $art['ref'] ?? '',
            'nombre'          => $name,
            'score'           => round($score),
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
