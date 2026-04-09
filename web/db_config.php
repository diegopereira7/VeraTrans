<?php
/**
 * Configuración de conexión a MySQL/MariaDB.
 */

define('DB_HOST', 'localhost');
define('DB_USER', 'root');
define('DB_PASS', '');
define('DB_NAME', 'traductor-verabuy');
define('DB_PORT', 3306);

function get_db(): ?mysqli
{
    static $conn = null;
    if ($conn !== null && $conn->ping()) return $conn;

    try {
        $conn = new mysqli(DB_HOST, DB_USER, DB_PASS, DB_NAME, DB_PORT);
        if ($conn->connect_error) {
            $conn = null;
            return null;
        }
        $conn->set_charset('utf8mb4');
        return $conn;
    } catch (Exception $e) {
        return null;
    }
}
