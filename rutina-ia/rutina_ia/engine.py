"""Contrato común de los motores de generación y bucle de reparación.

Hay dos formas de hablar con Claude en esta aplicación:

- `ai.AnthropicEngine`, contra la API con clave propia (se factura por uso).
- `claude_code.ClaudeCodeEngine`, a través del CLI de Claude Code, que usa la
  sesión que ya tengas iniciada — incluida una suscripción Pro o Max.

Lo que no cambia entre ambos es lo importante: el esquema de salida, el
validador determinista y el bucle que devuelve los incumplimientos al modelo
para que los corrija. Eso vive aquí, y cada motor solo implementa `send`.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import ValidationError

from .catalog import Catalog
from .config import MAX_REPAIR_ATTEMPTS
from .models import Issue, Profile, Routine, RoutineResult
from .programming import blocking_issues, validate
from .prompts import build_repair_prompt

ROLES = ["principal", "secundario", "accesorio", "core", "movilidad"]

# Esquema de la rutina. Se usa tal cual como `input_schema` de la herramienta
# en la API y como `--json-schema` en el CLI de Claude Code, de modo que los
# dos motores están sujetos exactamente a la misma forma de salida.
ROUTINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Título breve de la rutina"},
        "summary": {
            "type": "string",
            "description": (
                "Dos o tres frases: qué estructura tiene la rutina y por qué "
                "encaja con este usuario."
            ),
        },
        "goal": {"type": "string", "enum": ["fuerza", "fuerza_hipertrofia", "hipertrofia"]},
        "weeks": {
            "type": "integer",
            "minimum": 1,
            "maximum": 16,
            "description": "Duración del bloque en semanas (4-8 es lo habitual)",
        },
        "progression": {
            "type": "string",
            "description": (
                "Cómo progresar semana a semana: qué subir, cuánto y bajo qué condición."
            ),
        },
        "deload": {
            "type": "string",
            "description": "Cuándo y cómo descargar. Cadena vacía si no aplica.",
        },
        "safety_notes": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Avisos concretos de seguridad para este usuario: técnica crítica, "
                "señales de alarma, adaptaciones por lesión."
            ),
        },
        "days": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Ej. «Día 1 — Empuje»"},
                    "focus": {"type": "string", "description": "Foco de la sesión"},
                    "blocks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "exercise_id": {
                                    "type": "string",
                                    "description": "Id exacto del catálogo de candidatos",
                                },
                                "sets": {"type": "integer", "minimum": 1, "maximum": 10},
                                "reps": {
                                    "type": "string",
                                    "description": "«5», «6-8» o «30 s» para isométricos",
                                },
                                "rir": {
                                    "type": "integer",
                                    "minimum": 0,
                                    "maximum": 5,
                                    "description": "Repeticiones en recámara",
                                },
                                "rest_seconds": {
                                    "type": "integer",
                                    "minimum": 20,
                                    "maximum": 600,
                                },
                                "role": {"type": "string", "enum": ROLES},
                                "notes": {
                                    "type": "string",
                                    "description": (
                                        "Indicación técnica breve. Cadena vacía si no "
                                        "hace falta."
                                    ),
                                },
                            },
                            "required": [
                                "exercise_id",
                                "sets",
                                "reps",
                                "rir",
                                "rest_seconds",
                                "role",
                                "notes",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["name", "focus", "blocks"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "title",
        "summary",
        "goal",
        "weeks",
        "progression",
        "deload",
        "safety_notes",
        "days",
    ],
    "additionalProperties": False,
}


class GenerationError(RuntimeError):
    """El motor no devolvió una rutina utilizable."""


class SchemaMismatch(Exception):
    """La rutina llegó con valores fuera de los límites del modelo de dominio.

    Es recuperable: se le devuelve el error al modelo igual que un fallo del
    validador, en vez de tumbar la petición entera.
    """

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class RoutineEngine(Protocol):
    """Conversación con un modelo que sabe emitir rutinas.

    `send` mantiene el hilo: la primera llamada lleva el encargo completo y
    las siguientes el informe de incumplimientos. Devuelve la rutina, o None
    si el modelo contestó sin emitirla.
    """

    name: str

    def send(self, message: str) -> Routine | None: ...


def parse_routine(payload: Any) -> Routine:
    """Valida el objeto emitido contra el modelo de dominio."""
    try:
        return Routine.model_validate(payload)
    except ValidationError as exc:
        raise SchemaMismatch(format_validation(exc)) from exc


def format_validation(exc: ValidationError) -> str:
    """Errores de Pydantic en el mismo formato que usa el validador."""
    return "\n".join(
        f"- [FORMATO] {'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in exc.errors()
    )


def issues_text(issues: list[Issue]) -> str:
    return "\n".join(f"- [{issue.code}] {issue.message}" for issue in issues)


NUDGE = (
    "No has devuelto la rutina. Emítela completa con el formato estructurado "
    "que se te ha indicado."
)


def run_with_repairs(
    engine: RoutineEngine,
    initial_prompt: str,
    profile: Profile,
    catalog: Catalog,
    engine_label: str,
) -> RoutineResult:
    """Genera, valida y, si hace falta, pide corrección al modelo.

    El presupuesto de reintentos cubre tres fallos distintos: que el modelo
    conteste sin emitir la rutina, que la emita con valores fuera de rango y
    que la emita bien formada pero incumpliendo las reglas de programación.
    Los tres se resuelven igual, devolviéndole el problema.
    """
    message = initial_prompt
    routine: Routine | None = None
    issues: list[Issue] = []

    for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
        last = attempt == MAX_REPAIR_ATTEMPTS

        try:
            candidate = engine.send(message)
        except SchemaMismatch as mismatch:
            if last:
                raise GenerationError(
                    "El modelo insiste en devolver valores fuera de rango:\n"
                    f"{mismatch.detail}"
                ) from mismatch
            message = build_repair_prompt(mismatch.detail)
            continue

        if candidate is None:
            if last:
                raise GenerationError("El modelo no ha llegado a emitir la rutina.")
            message = NUDGE
            continue

        routine = candidate
        issues = validate(routine, profile, catalog)
        blocking = blocking_issues(issues)
        if not blocking:
            return RoutineResult(
                routine=routine,
                issues=issues,
                engine=engine_label,
                repair_attempts=attempt,
            )
        if last:
            break
        message = build_repair_prompt(issues_text(blocking))

    assert routine is not None
    return RoutineResult(
        routine=routine,
        issues=issues,
        engine=engine_label,
        repair_attempts=MAX_REPAIR_ATTEMPTS,
    )
