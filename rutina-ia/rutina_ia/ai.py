"""Generación y adaptación de rutinas con la API de Claude.

La salida se fuerza mediante tool use en modo estricto: el modelo solo puede
devolver la rutina llamando a `emit_routine` con un esquema cerrado, así que
no hay que parsear prosa ni JSON suelto. Después, la rutina pasa por el
validador determinista de `programming.py`; si falla, se devuelve al modelo el
informe de errores para que la corrija (hasta `MAX_REPAIR_ATTEMPTS` veces).
"""

from __future__ import annotations

import json
from typing import Any

import anthropic
from pydantic import ValidationError

from .catalog import Catalog, Exercise
from .config import EFFORT, MAX_CANDIDATES, MAX_REPAIR_ATTEMPTS, MAX_TOKENS, MODEL
from .models import Issue, Profile, Routine, RoutineResult
from .programming import blocking_issues, validate
from .prompts import (
    SYSTEM,
    build_adaptation_prompt,
    build_generation_prompt,
    build_repair_prompt,
)

ROLES = ["principal", "secundario", "accesorio", "core", "movilidad"]

EMIT_ROUTINE_TOOL: dict[str, Any] = {
    "name": "emit_routine",
    "description": (
        "Devuelve la rutina de entrenamiento completa. Es la única forma de "
        "entregar la rutina; no la escribas en texto libre."
    ),
    "strict": True,
    "input_schema": {
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
                    "Cómo progresar semana a semana: qué subir, cuánto y bajo qué "
                    "condición."
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
                    "Avisos concretos de seguridad para este usuario: técnica "
                    "crítica, señales de alarma, adaptaciones por lesión."
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
                                    "sets": {
                                        "type": "integer",
                                        "minimum": 1,
                                        "maximum": 10,
                                    },
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
                                            "Indicación técnica breve. Cadena vacía si "
                                            "no hace falta."
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
    },
}


class GenerationError(RuntimeError):
    """El modelo no devolvió una rutina utilizable."""


class SchemaMismatch(Exception):
    """La herramienta se llamó con valores fuera de los límites del modelo.

    Es recuperable: se le devuelve el error al modelo igual que un fallo del
    validador, en vez de tumbar la petición entera.
    """

    def __init__(self, detail: str, tool_use_id: str):
        super().__init__(detail)
        self.detail = detail
        self.tool_use_id = tool_use_id


def _client() -> anthropic.Anthropic:
    # Sin argumentos: resuelve ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN o el
    # perfil de `ant auth login`, en ese orden.
    return anthropic.Anthropic()


def _extract_routine(message: anthropic.types.Message) -> Routine | None:
    """Rutina emitida por la herramienta, o None si el modelo no la llamó."""
    for block in message.content:
        if block.type == "tool_use" and block.name == "emit_routine":
            try:
                return Routine.model_validate(block.input)
            except ValidationError as exc:
                raise SchemaMismatch(_format_validation(exc), block.id) from exc
    if message.stop_reason == "refusal":
        raise GenerationError(
            "El modelo ha declinado la petición. Reformúlala evitando contenido "
            "médico o de diagnóstico."
        )
    return None


def _issues_text(issues: list[Issue]) -> str:
    return "\n".join(f"- [{issue.code}] {issue.message}" for issue in issues)


def _format_validation(exc: ValidationError) -> str:
    """Errores de Pydantic en el mismo formato que usa el validador."""
    return "\n".join(
        f"- [FORMATO] {'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in exc.errors()
    )


def _call(client: anthropic.Anthropic, messages: list[dict[str, Any]]) -> anthropic.types.Message:
    # Streaming porque un `max_tokens` alto en no-streaming arriesga timeout HTTP.
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM,
        thinking={"type": "adaptive"},
        output_config={"effort": EFFORT},
        tools=[EMIT_ROUTINE_TOOL],
        messages=messages,
    ) as stream:
        return stream.get_final_message()


def _tool_use_id(message: anthropic.types.Message) -> str | None:
    for block in message.content:
        if block.type == "tool_use":
            return block.id
    return None


def _run_with_repairs(
    initial_prompt: str,
    profile: Profile,
    catalog: Catalog,
) -> RoutineResult:
    """Genera, valida y, si hace falta, pide corrección al modelo.

    El presupuesto de reintentos cubre dos fallos distintos: que el modelo
    conteste en texto sin llamar a la herramienta, y que la rutina emitida
    incumpla el validador. Ambos se resuelven devolviéndole el problema.
    """
    client = _client()
    messages: list[dict[str, Any]] = [{"role": "user", "content": initial_prompt}]

    routine: Routine | None = None
    issues: list[Issue] = []

    for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
        message = _call(client, messages)

        try:
            candidate = _extract_routine(message)
        except SchemaMismatch as mismatch:
            if attempt == MAX_REPAIR_ATTEMPTS:
                raise GenerationError(
                    f"El modelo insiste en devolver valores fuera de rango:\n"
                    f"{mismatch.detail}"
                ) from mismatch
            messages.append({"role": "assistant", "content": message.content})
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": mismatch.tool_use_id,
                            "content": build_repair_prompt(mismatch.detail),
                            "is_error": True,
                        }
                    ],
                }
            )
            continue

        if candidate is None:
            if attempt == MAX_REPAIR_ATTEMPTS:
                raise GenerationError(
                    "El modelo no ha llegado a emitir la rutina con `emit_routine` "
                    f"(stop_reason={message.stop_reason})."
                )
            messages.append({"role": "assistant", "content": message.content})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "No has llamado a `emit_routine`. Devuelve la rutina "
                        "completa usando esa herramienta."
                    ),
                }
            )
            continue

        routine = candidate
        issues = validate(routine, profile, catalog)
        blocking = blocking_issues(issues)
        if not blocking:
            return RoutineResult(
                routine=routine, issues=issues, engine="ia", repair_attempts=attempt
            )
        if attempt == MAX_REPAIR_ATTEMPTS:
            break

        tool_use_id = _tool_use_id(message)
        messages.append({"role": "assistant", "content": message.content})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": build_repair_prompt(_issues_text(blocking)),
                        "is_error": True,
                    }
                ],
            }
        )

    assert routine is not None
    return RoutineResult(
        routine=routine, issues=issues, engine="ia", repair_attempts=MAX_REPAIR_ATTEMPTS
    )


def generate_routine(profile: Profile, catalog: Catalog) -> RoutineResult:
    candidates = _candidates(profile, catalog)
    prompt = build_generation_prompt(profile, candidates)
    return _run_with_repairs(prompt, profile, catalog)


def adapt_routine(
    profile: Profile,
    catalog: Catalog,
    routine: Routine,
    request: str,
) -> RoutineResult:
    candidates = _candidates(profile, catalog)
    prompt = build_adaptation_prompt(
        profile,
        candidates,
        routine.model_dump_json(indent=1),
        request,
    )
    return _run_with_repairs(prompt, profile, catalog)


def _candidates(profile: Profile, catalog: Catalog) -> list[Exercise]:
    candidates = catalog.candidates(profile, limit=MAX_CANDIDATES)
    if not candidates:
        raise GenerationError(
            "No queda ningún ejercicio disponible con ese material y esas "
            "lesiones. Añade material o revisa las articulaciones marcadas."
        )
    return candidates


def routine_to_json(routine: Routine) -> str:
    return json.dumps(routine.model_dump(), ensure_ascii=False, indent=1)
