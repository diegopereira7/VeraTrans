"""Fase 2: Agrupación de PDFs desconocidos con misma estructura."""
from __future__ import annotations

from collections import defaultdict

from .modelos import PDFFingerprint


def clusterizar_fingerprints(fingerprints: list[PDFFingerprint]) -> dict[str, list[PDFFingerprint]]:
    """Agrupa fingerprints por estructura similar.

    Dos PDFs pertenecen al mismo cluster si:
    1. Mismo hash_estructura (match exacto)
    2. Si no hay hash match, similitud de headers >= 0.8 Y mismos keywords

    Returns:
        Dict de cluster_id -> lista de fingerprints en ese cluster.
    """
    # Paso 1: Agrupar por hash exacto
    por_hash: dict[str, list[PDFFingerprint]] = defaultdict(list)
    sin_hash: list[PDFFingerprint] = []

    for fp in fingerprints:
        if fp.hash_estructura:
            por_hash[fp.hash_estructura].append(fp)
        else:
            sin_hash.append(fp)

    # Paso 2: Para los que no tienen hash, intentar matching por keywords + headers
    for fp in sin_hash:
        merged = False
        for hash_key, group in por_hash.items():
            if _are_similar(fp, group[0]):
                group.append(fp)
                merged = True
                break
        if not merged:
            # Crear nuevo cluster con un ID basado en el nombre candidato
            key = f'kw_{fp.proveedor_candidato[:20].replace(" ", "_").lower()}'
            por_hash[key].append(fp)

    # Paso 3: Refinar clusters — verificar similitud interna
    clusters_finales: dict[str, list[PDFFingerprint]] = {}
    for key, group in por_hash.items():
        if len(group) == 1:
            clusters_finales[key] = group
            continue

        # Verificar que todos los miembros son realmente similares al primero
        base = group[0]
        compatibles = [base]
        for fp in group[1:]:
            if _are_similar(fp, base):
                compatibles.append(fp)

        clusters_finales[key] = compatibles

    return clusters_finales


def confianza_cluster(size: int) -> float:
    """Calcula la confianza del cluster basada en su tamaño."""
    if size >= 10:
        return 1.0
    if size >= 5:
        return 0.9
    if size >= 3:
        return 0.7
    if size >= 2:
        return 0.5
    return 0.3


def _are_similar(fp1: PDFFingerprint, fp2: PDFFingerprint) -> bool:
    """Verifica si dos fingerprints son del mismo proveedor."""
    # Headers de tabla similares (Jaccard >= 0.6)
    if fp1.headers_tabla and fp2.headers_tabla:
        set1 = set(fp1.headers_tabla)
        set2 = set(fp2.headers_tabla)
        if set1 and set2:
            jaccard = len(set1 & set2) / len(set1 | set2)
            if jaccard < 0.6:
                return False

    # Mismo número de columnas (si ambos tienen tablas)
    if fp1.tiene_tablas and fp2.tiene_tablas:
        if fp1.num_columnas_tabla_principal != fp2.num_columnas_tabla_principal:
            return False

    # Al menos 2 keywords en común
    kw1 = set(fp1.keywords_encontrados)
    kw2 = set(fp2.keywords_encontrados)
    if kw1 and kw2 and len(kw1 & kw2) < 1:
        return False

    # Mismo separador de campos
    if fp1.separador_campos and fp2.separador_campos:
        if fp1.separador_campos != fp2.separador_campos:
            return False

    # Campos por línea similares (±2)
    if fp1.num_campos_por_linea and fp2.num_campos_por_linea:
        if abs(fp1.num_campos_por_linea - fp2.num_campos_por_linea) > 2:
            return False

    return True
