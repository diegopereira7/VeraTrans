-- Sesión 12m: correcciones de catálogo de sinónimos
-- Aplicar en MySQL prod tras pull de sinonimos_universal.json

UPDATE sinonimos SET id_articulo = 33181, nombre_articulo = 'ROSA EC CARROUSEL BICOLOR 50CM 25U', origen = 'manual' WHERE clave = '442|ROSES|CAROUSEL|50|25|';
UPDATE sinonimos SET id_articulo = 32569, nombre_articulo = 'ROSA COL COLOR MIXTO 40CM 25U', origen = 'manual' WHERE clave = '281|ROSES|ASSORTED|40|25|';
UPDATE sinonimos SET id_articulo = 32571, nombre_articulo = 'ROSA COL COLOR MIXTO 60CM 25U', origen = 'manual' WHERE clave = '281|ROSES|ASSORTED|60|25|';
UPDATE sinonimos SET id_articulo = 32571, nombre_articulo = 'ROSA COL COLOR MIXTO 60CM 25U', origen = 'manual' WHERE clave = '281|ROSES|SPECIAL ASSTD|60|25|';

-- Eliminar sinónimo erróneo Mystic MISS PIGGY → MISS WHITE
DELETE FROM sinonimos WHERE clave = '442|ROSES|MISS PIGGY|50|25|';
