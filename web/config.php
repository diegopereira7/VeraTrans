<?php
/**
 * VeraBuy Traductor Web - Configuración
 */

// Ruta al directorio raíz del proyecto Python
define('PROJECT_ROOT', realpath(__DIR__ . '/..'));

// Ruta al ejecutable de Python
define('PYTHON_BIN', 'C:/Users/diego.pereira/AppData/Local/Python/pythoncore-3.14-64/python.exe');

// Ruta al procesador de PDFs
define('PROCESSOR_SCRIPT', PROJECT_ROOT . '/procesar_pdf.py');

// Directorio de subida de PDFs
define('UPLOAD_DIR', __DIR__ . '/uploads');

// Archivos JSON del proyecto
define('SYNONYMS_FILE', PROJECT_ROOT . '/sinonimos_universal.json');
define('HISTORY_FILE', PROJECT_ROOT . '/historial_universal.json');

// Tamaño máximo de PDF (10 MB)
define('MAX_PDF_SIZE', 10 * 1024 * 1024);

// Aumentar límites para importación masiva
@ini_set('upload_max_filesize', '200M');
@ini_set('post_max_size', '210M');
@ini_set('max_file_uploads', '200');
@ini_set('max_execution_time', '300');
