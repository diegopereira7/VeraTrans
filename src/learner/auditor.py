"""Fase 6: Auditoría y logging del sistema de auto-aprendizaje."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.config import BASE_DIR
from .modelos import PDFFingerprint, ExtractionRule

AUDIT_LOG_FILE      = BASE_DIR / 'audit_log.jsonl'
FINGERPRINTS_FILE   = BASE_DIR / 'fingerprints.json'
PENDING_REVIEW_FILE = BASE_DIR / 'pending_review.json'


class Auditor:
    """Gestiona la auditoría del sistema de auto-aprendizaje."""

    def log_evento(self, evento: str, **kwargs):
        """Añade una entrada al log de auditoría (append-only)."""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'evento': evento,
            **kwargs,
        }
        with open(AUDIT_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + '\n')

    def registrar_fingerprint(self, fp: PDFFingerprint):
        """Guarda una fingerprint para futuro clustering."""
        fps = self._load_fingerprints()

        fps[fp.pdf_path] = {
            'hash_estructura': fp.hash_estructura,
            'proveedor_candidato': fp.proveedor_candidato,
            'keywords': fp.keywords_encontrados,
            'num_paginas': fp.num_paginas,
            'tiene_tablas': fp.tiene_tablas,
            'num_columnas': fp.num_columnas_tabla_principal,
            'headers': fp.headers_tabla,
            'confianza': fp.confianza_deteccion,
            'timestamp': datetime.now().isoformat(),
        }

        self._save_fingerprints(fps)

        self.log_evento('fingerprint_registrada',
                       pdf=fp.pdf_path,
                       hash=fp.hash_estructura,
                       proveedor=fp.proveedor_candidato,
                       confianza=fp.confianza_deteccion)

    def log_parser_generado(
        self,
        nombre: str,
        score: float,
        reglas: list[ExtractionRule],
        cluster_fps: list[PDFFingerprint],
        detalles: dict,
        decision: str,
    ):
        """Logea la generación de un parser."""
        self.log_evento(
            'parser_generado',
            proveedor=nombre,
            pdfs_analizados=[fp.pdf_path for fp in cluster_fps],
            fingerprint_hash=cluster_fps[0].hash_estructura if cluster_fps else '',
            reglas_inferidas=[{
                'campo': r.campo_destino,
                'tipo': r.tipo,
                'confianza': r.confianza,
                'patron': r.patron_regex,
            } for r in reglas],
            validacion=detalles,
            score_final=score,
            decision=decision,
        )

    def registrar_pendiente(
        self,
        nombre: str,
        score: float,
        cluster_fps: list[PDFFingerprint],
        reglas: list[ExtractionRule],
        detalles: dict,
    ):
        """Registra un parser para revisión humana.

        Se invoca tanto para AMARILLO (parser activo, revisar para promover
        a VERDE) como para NARANJA (parser no activo, revisar para aprobar
        manualmente).
        """
        # Inferir la decisión a partir del score (mismo umbral que en
        # src/learner/__init__.py: aprender_de_batch).
        if score >= 0.85:
            decision = 'VERDE'
        elif score >= 0.50:
            decision = 'AMARILLO'
        else:
            decision = 'NARANJA'

        pending = self._load_pending()

        pending['pendientes'] = pending.get('pendientes', [])
        pending['pendientes'].append({
            'proveedor': nombre,
            'score': round(score, 3),
            'decision': decision,
            'razon': _generate_reason(detalles),
            'pdfs': [fp.pdf_path for fp in cluster_fps],
            'reglas_propuestas': [{
                'campo': r.campo_destino,
                'tipo': r.tipo,
                'confianza': round(r.confianza, 3),
            } for r in reglas],
            'fecha': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'accion_sugerida': _suggest_action(detalles),
        })

        self._save_pending(pending)

    def get_audit_log(self, limit: int = 100) -> list[dict]:
        """Lee las últimas N entradas del log de auditoría."""
        if not AUDIT_LOG_FILE.exists():
            return []

        entries = []
        with open(AUDIT_LOG_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        return entries[-limit:]

    def get_pending_review(self) -> list[dict]:
        """Retorna la lista de parsers pendientes de revisión."""
        pending = self._load_pending()
        return pending.get('pendientes', [])

    def _load_fingerprints(self) -> dict:
        if FINGERPRINTS_FILE.exists():
            return json.loads(FINGERPRINTS_FILE.read_text(encoding='utf-8'))
        return {}

    def _save_fingerprints(self, data: dict):
        FINGERPRINTS_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding='utf-8',
        )

    def _load_pending(self) -> dict:
        if PENDING_REVIEW_FILE.exists():
            return json.loads(PENDING_REVIEW_FILE.read_text(encoding='utf-8'))
        return {'pendientes': []}

    def _save_pending(self, data: dict):
        PENDING_REVIEW_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding='utf-8',
        )


def _generate_reason(detalles: dict) -> str:
    """Genera una razón legible para el score AMARILLO."""
    parts = []
    if detalles.get('completitud', 1) < 0.7:
        parts.append('Campos obligatorios incompletos')
    if detalles.get('coherencia_numerica', 1) < 0.7:
        parts.append('Valores numéricos poco plausibles')
    if detalles.get('consistencia_cluster', 1) < 0.7:
        parts.append('Reglas inconsistentes entre PDFs')
    if detalles.get('confianza_reglas', 1) < 0.7:
        parts.append('Confianza baja en reglas inferidas')
    if detalles.get('confianza_cluster', 1) < 0.7:
        parts.append('Pocos PDFs de ejemplo')
    return '. '.join(parts) if parts else 'Score general bajo'


def _suggest_action(detalles: dict) -> str:
    """Sugiere acción para mejorar el score."""
    if detalles.get('confianza_cluster', 1) < 0.7:
        return 'Añadir más facturas de este proveedor para mejorar la confianza'
    if detalles.get('completitud', 1) < 0.7:
        return 'Verificar manualmente que el formato de factura contiene los campos necesarios'
    if detalles.get('coherencia_numerica', 1) < 0.7:
        return 'Revisar que los valores numéricos extraídos son correctos'
    return 'Revisar las reglas inferidas y ajustar manualmente si es necesario'
