"""Sistema de auto-aprendizaje de parsers para proveedores nuevos."""
from __future__ import annotations

from .fingerprint import extraer_fingerprint
from .cluster import clusterizar_fingerprints
from .inferencia import inferir_reglas
from .validador import validar_reglas
from .generador import generar_parser, registrar_parser_aprendido
from .auditor import Auditor
from .modelos import PDFFingerprint, ExtractionRule, LearnedParser

__all__ = [
    'intentar_auto_parse',
    'aprender_de_batch',
]


def intentar_auto_parse(pdf_path: str, text: str) -> dict:
    """Intenta parsear un PDF de proveedor desconocido usando parsers aprendidos o aprendizaje en vivo.

    Se llama cuando detect_provider() retorna None.
    Retorna dict compatible con el formato de procesar_pdf.py.
    """
    from src.learned_parsers import LEARNED_PARSERS, find_learned_provider

    # Primero buscar en parsers ya aprendidos
    learned = find_learned_provider(text)
    if learned:
        parser = LEARNED_PARSERS[learned['fmt']]
        header, lines = parser.parse(text, learned)
        return {
            'ok': True,
            'auto_parsed': True,
            'learned_provider': learned['name'],
            'header': header,
            'lines': lines,
        }

    # No hay parser aprendido: registrar fingerprint para futuro clustering
    fp = extraer_fingerprint(pdf_path, text)
    if fp:
        from .auditor import Auditor
        auditor = Auditor()
        auditor.registrar_fingerprint(fp)

    return {
        'ok': False,
        'error': 'Proveedor no reconocido. Huella registrada para auto-aprendizaje.',
        'auto_learn_info': {
            'fingerprint_hash': fp.hash_estructura if fp else None,
            'proveedor_candidato': fp.proveedor_candidato if fp else None,
            'confianza_deteccion': fp.confianza_deteccion if fp else 0,
        },
    }


def aprender_de_batch(pdfs_sin_parser: list[dict]) -> list[dict]:
    """Ejecuta el ciclo completo de aprendizaje sobre PDFs que no tuvieron parser.

    Llamado al final de un batch masivo.
    Cada elemento es {'path': str, 'text': str, 'fingerprint': PDFFingerprint}.

    Retorna lista de parsers generados con su score.
    """
    auditor = Auditor()

    if len(pdfs_sin_parser) < 2:
        return []

    # Fase 1: Fingerprinting (ya hecho durante el batch)
    fingerprints = []
    for item in pdfs_sin_parser:
        fp = item.get('fingerprint')
        if not fp:
            fp = extraer_fingerprint(item['path'], item['text'])
        if fp:
            fp.pdf_path = item['path']
            fingerprints.append(fp)

    if len(fingerprints) < 2:
        return []

    # Fase 2: Clustering
    clusters = clusterizar_fingerprints(fingerprints)

    resultados = []
    for cluster_id, cluster_fps in clusters.items():
        if len(cluster_fps) < 2:
            continue

        # Fase 3: Inferencia
        reglas = inferir_reglas(cluster_fps)
        if not reglas:
            auditor.log_evento('inferencia_fallida', cluster_id=cluster_id,
                              razon='No se pudieron inferir reglas')
            continue

        # Fase 4: Validación
        score, detalles = validar_reglas(reglas, cluster_fps)

        # Fase 5: Generación (si score suficiente)
        nombre = cluster_fps[0].proveedor_candidato or f'auto_{cluster_id[:8]}'

        if score >= 0.85:
            # VERDE: parser activo en producción, sin revisión necesaria.
            parser_info = generar_parser(nombre, reglas, cluster_fps, score)
            registrar_parser_aprendido(parser_info)
            auditor.log_parser_generado(nombre, score, reglas, cluster_fps, detalles, 'VERDE')
            resultados.append({
                'nombre': nombre,
                'score': score,
                'decision': 'VERDE',
                'pdfs': [fp.pdf_path for fp in cluster_fps],
                'parser_info': parser_info,
            })
        elif score >= 0.50:
            # AMARILLO: parser activo PERO marcado para revisión.
            parser_info = generar_parser(nombre, reglas, cluster_fps, score)
            registrar_parser_aprendido(parser_info)
            auditor.log_parser_generado(nombre, score, reglas, cluster_fps, detalles, 'AMARILLO')
            auditor.registrar_pendiente(nombre, score, cluster_fps, reglas, detalles)
            resultados.append({
                'nombre': nombre,
                'score': score,
                'decision': 'AMARILLO',
                'pdfs': [fp.pdf_path for fp in cluster_fps],
            })
        elif score >= 0.25:
            # NARANJA: parser NO activado. Sólo se registra en pendientes
            # para que el usuario lo vea en la pestaña Auto-Aprendizaje y
            # decida si lo aprueba manualmente. Esto evita que un parser
            # poco confiable ensucie producción pero da feedback de que el
            # motor sí intentó aprender.
            auditor.log_parser_generado(nombre, score, reglas, cluster_fps, detalles, 'NARANJA')
            auditor.registrar_pendiente(nombre, score, cluster_fps, reglas, detalles)
            resultados.append({
                'nombre': nombre,
                'score': score,
                'decision': 'NARANJA',
                'pdfs': [fp.pdf_path for fp in cluster_fps],
            })
        else:
            auditor.log_parser_generado(nombre, score, reglas, cluster_fps, detalles, 'ROJO')
            resultados.append({
                'nombre': nombre,
                'score': score,
                'decision': 'ROJO',
                'pdfs': [fp.pdf_path for fp in cluster_fps],
            })

    return resultados
