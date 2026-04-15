# Documentación — VeraBuy Traductor

Índice corto para navegar la documentación del repo. Los tres documentos
maestros viven fuera de esta carpeta (raíz) porque CLAUDE.md tiene que
auto-cargarse y README.md/SETUP.md son los puntos de entrada habituales
de cualquier repo. Lo que vive bajo `docs/` es estrictamente seguimiento
y planificación.

## Qué mirar según necesidad

| Necesito… | Fichero | Dónde |
|---|---|---|
| Entender qué es el proyecto y cómo arrancarlo | [`README.md`](../README.md) | raíz |
| Instalar/configurar entorno (Windows + WAMP + OCR) | [`SETUP.md`](../SETUP.md) | raíz |
| Saber el **estado real del código** ahora mismo (arquitectura, pipeline, convenciones, lecciones, historial de sesiones) | [`CLAUDE.md`](../CLAUDE.md) | raíz |
| Saber **qué hacer a continuación** con prompts ejecutables | [`roadmap/roadmap.md`](roadmap/roadmap.md) | `docs/roadmap/` |
| Ver **por dónde voy** de un vistazo | [`roadmap/checklist.md`](roadmap/checklist.md) | `docs/roadmap/` |

## División de responsabilidades

- **`CLAUDE.md`** = fuente de verdad del presente. Se auto-carga en cada
  sesión de Claude Code. Cualquier cambio de código obliga a
  actualizarlo en el mismo turno.
- **`docs/roadmap/roadmap.md`** = plan a 12 pasos con prompts
  ejecutables. No describe lo que ya hay, sino lo que falta.
- **`docs/roadmap/checklist.md`** = tablero visual corto. Checkboxes,
  próximo bloque activo, registro de últimas sesiones cerradas.

## Flujo de trabajo recomendado

1. **Retomar** → `checklist.md` (estado rápido) + "Historial de sesiones"
   de `CLAUDE.md`.
2. **Planificar bloque** → `roadmap.md` (prompt del paso correspondiente).
3. **Antes de ejecutar** → releer secciones afectadas de `CLAUDE.md`.
4. **Ejecutar** → un solo prompt en Claude Code, cerrar turno dejando
   código + validación + `CLAUDE.md` actualizado.
5. **Cerrar bloque** → marcar `[x]` en `checklist.md`, rellenar
   "Registro rápido de avances".

## Regla de sincronización

Si pasan días entre sesiones, primero compara las cifras de "Estado
rápido actual" (`checklist.md`) con el último historial de sesiones de
`CLAUDE.md`. Si hay desfase, actualiza `checklist.md` y `roadmap.md`
**antes** de ejecutar nada.
