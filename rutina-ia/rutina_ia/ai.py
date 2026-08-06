"""Motor que habla con Claude a través de la API de Anthropic.

Requiere credenciales propias (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` o un
perfil de `ant auth login`) y se factura por uso. Si prefieres tirar de una
suscripción Pro o Max que ya tengas, usa `claude_code.py`.

La salida se fuerza mediante tool use en modo estricto: el modelo solo puede
devolver la rutina llamando a `emit_routine` con un esquema cerrado, así que no
hay que parsear prosa ni JSON suelto. El bucle de validación y reparación es
común a los dos motores y vive en `engine.py`.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic

from .catalog import Catalog, Exercise
from .config import EFFORT, MAX_CANDIDATES, MAX_TOKENS, MODEL
from .engine import (
    ROUTINE_SCHEMA,
    GenerationError,
    parse_routine,
    run_with_repairs,
)
from .models import Profile, Routine, RoutineResult
from .prompts import SYSTEM, build_adaptation_prompt, build_generation_prompt

EMIT_ROUTINE_TOOL: dict[str, Any] = {
    "name": "emit_routine",
    "description": (
        "Devuelve la rutina de entrenamiento completa. Es la única forma de "
        "entregar la rutina; no la escribas en texto libre."
    ),
    "strict": True,
    "input_schema": ROUTINE_SCHEMA,
}


class AnthropicEngine:
    """Conversación con la API, manteniendo el historial entre turnos."""

    name = "anthropic-api"

    def __init__(self, client: anthropic.Anthropic | None = None):
        self.client = client or anthropic.Anthropic()
        self.messages: list[dict[str, Any]] = []
        self._pending_tool_use_id: str | None = None

    def send(self, message: str) -> Routine | None:
        # Un mensaje de corrección tras una llamada a herramienta tiene que
        # viajar como tool_result, o la API rechaza el historial.
        if self._pending_tool_use_id is not None:
            self.messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": self._pending_tool_use_id,
                            "content": message,
                            "is_error": True,
                        }
                    ],
                }
            )
        else:
            self.messages.append({"role": "user", "content": message})

        # Streaming porque un `max_tokens` alto en no-streaming arriesga
        # timeout HTTP.
        with self.client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"effort": EFFORT},
            tools=[EMIT_ROUTINE_TOOL],
            messages=self.messages,
        ) as stream:
            response = stream.get_final_message()

        self.messages.append({"role": "assistant", "content": response.content})
        self._pending_tool_use_id = None

        for block in response.content:
            if block.type == "tool_use" and block.name == "emit_routine":
                self._pending_tool_use_id = block.id
                return parse_routine(block.input)

        if response.stop_reason == "refusal":
            raise GenerationError(
                "El modelo ha declinado la petición. Reformúlala evitando "
                "contenido médico o de diagnóstico."
            )
        return None


def _candidates(profile: Profile, catalog: Catalog) -> list[Exercise]:
    candidates = catalog.candidates(profile, limit=MAX_CANDIDATES)
    if not candidates:
        raise GenerationError(
            "No queda ningún ejercicio disponible con ese material y esas "
            "lesiones. Añade material o revisa las articulaciones marcadas."
        )
    return candidates


def generate_routine(profile: Profile, catalog: Catalog) -> RoutineResult:
    prompt = build_generation_prompt(profile, _candidates(profile, catalog))
    return run_with_repairs(AnthropicEngine(), prompt, profile, catalog, "api")


def adapt_routine(
    profile: Profile,
    catalog: Catalog,
    routine: Routine,
    request: str,
) -> RoutineResult:
    prompt = build_adaptation_prompt(
        profile,
        _candidates(profile, catalog),
        routine.model_dump_json(indent=1),
        request,
    )
    return run_with_repairs(AnthropicEngine(), prompt, profile, catalog, "api")


def routine_to_json(routine: Routine) -> str:
    return json.dumps(routine.model_dump(), ensure_ascii=False, indent=1)
