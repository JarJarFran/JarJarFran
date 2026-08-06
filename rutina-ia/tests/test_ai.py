"""La capa de IA, con el cliente de Anthropic simulado.

No se llama a la red: lo que se comprueba aquí es el contrato alrededor del
modelo —extracción de la herramienta, bucle de reparación con el informe del
validador y manejo de rechazos—, que es la parte que puede romperse en
silencio.
"""

from __future__ import annotations

import types

import pytest

from rutina_ia import ai, engine
from rutina_ia.catalog import get_catalog
from rutina_ia.models import Profile


@pytest.fixture(scope="module")
def catalog():
    return get_catalog()


@pytest.fixture
def profile():
    return Profile(
        goal="fuerza",
        experience="intermedio",
        days_per_week=1,
        session_minutes=75,
        equipment=["barbell", "dumbbell", "body weight", "cable"],
    )


# ---------------------------------------------------------------------------
# Dobles de prueba
# ---------------------------------------------------------------------------


class FakeBlock:
    def __init__(self, type_, **kwargs):
        self.type = type_
        for key, value in kwargs.items():
            setattr(self, key, value)


class FakeMessage:
    def __init__(self, content, stop_reason="tool_use"):
        self.content = content
        self.stop_reason = stop_reason


class FakeStream:
    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get_final_message(self):
        return self._message


class FakeClient:
    """Devuelve una respuesta preparada por llamada y registra las peticiones."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[list] = []
        self.messages = types.SimpleNamespace(stream=self._stream)

    def _stream(self, **kwargs):
        # Copia: el motor sigue añadiendo a la misma lista tras la llamada, y
        # el test quiere ver el historial tal y como se envió.
        self.calls.append(list(kwargs["messages"]))
        return FakeStream(self._responses.pop(0))


def _routine_payload(catalog, exercise_name: str, sets: int = 4, rir: int = 2) -> dict:
    exercise = next(e for e in catalog.exercises if e.name == exercise_name)
    return {
        "title": "Rutina de prueba",
        "summary": "Resumen.",
        "goal": "fuerza",
        "weeks": 4,
        "progression": "Sube 2,5 kg cuando completes todas las series.",
        "deload": "",
        "safety_notes": ["Calienta antes de entrenar."],
        "days": [
            {
                "name": "Día 1",
                "focus": "cuerpo completo",
                "blocks": [
                    {
                        "exercise_id": exercise.id,
                        "sets": sets,
                        "reps": "5",
                        "rir": rir,
                        "rest_seconds": 210,
                        "role": "principal",
                        "notes": "",
                    }
                ],
            }
        ],
    }


def _tool_message(payload: dict, tool_use_id: str = "toolu_1") -> FakeMessage:
    return FakeMessage(
        [FakeBlock("tool_use", id=tool_use_id, name="emit_routine", input=payload)]
    )


def use_client(monkeypatch, client: FakeClient) -> None:
    """Hace que el motor de API use el cliente falso en lugar de uno real."""
    # La clase real se captura antes de parchear: si se resolviera dentro del
    # lambda, se encontraría a sí misma.
    real = ai.AnthropicEngine
    monkeypatch.setattr(ai, "AnthropicEngine", lambda: real(client=client))


# ---------------------------------------------------------------------------
# Esquema de la herramienta
# ---------------------------------------------------------------------------


def test_esquema_estricto_cierra_todos_los_objetos():
    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for item in node:
                check(item)

    assert ai.EMIT_ROUTINE_TOOL["strict"] is True
    check(ai.EMIT_ROUTINE_TOOL["input_schema"])


# ---------------------------------------------------------------------------
# Generación
# ---------------------------------------------------------------------------


def test_generacion_valida_a_la_primera(monkeypatch, catalog, profile):
    client = FakeClient([_tool_message(_routine_payload(catalog, "barbell full squat"))])
    use_client(monkeypatch, client)

    result = ai.generate_routine(profile, catalog)

    assert result.engine == "api"
    assert result.repair_attempts == 0
    assert len(client.calls) == 1
    assert result.routine.days[0].blocks[0].sets == 4


def test_bucle_de_reparacion_devuelve_los_errores_al_modelo(monkeypatch, catalog, profile):
    # Primera respuesta: RIR 0 con un perfil intermedio -> RIR_BAJO (error).
    malo = _routine_payload(catalog, "barbell full squat", rir=0)
    bueno = _routine_payload(catalog, "barbell full squat", rir=2)
    client = FakeClient([_tool_message(malo), _tool_message(bueno)])
    use_client(monkeypatch, client)

    result = ai.generate_routine(profile, catalog)

    assert result.repair_attempts == 1
    assert len(client.calls) == 2
    assert result.routine.days[0].blocks[0].rir == 2

    # La segunda llamada debe incluir el tool_result con el informe de errores.
    segunda = client.calls[1]
    tool_result = segunda[-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["is_error"] is True
    assert tool_result["tool_use_id"] == "toolu_1"
    assert "RIR_BAJO" in tool_result["content"]


def test_se_agotan_los_reintentos_y_se_devuelve_con_avisos(monkeypatch, catalog, profile):
    malo = _routine_payload(catalog, "barbell full squat", rir=0)
    client = FakeClient([_tool_message(malo)] * (engine.MAX_REPAIR_ATTEMPTS + 1))
    use_client(monkeypatch, client)

    result = ai.generate_routine(profile, catalog)

    assert result.repair_attempts == engine.MAX_REPAIR_ATTEMPTS
    assert any(issue.code == "RIR_BAJO" for issue in result.issues)


def test_valores_fuera_de_rango_se_devuelven_para_correccion(monkeypatch, catalog, profile):
    """12 series no las admite el modelo de dominio: hay que pedir corrección."""
    malo = _routine_payload(catalog, "barbell full squat", sets=12)
    bueno = _routine_payload(catalog, "barbell full squat", sets=4)
    client = FakeClient([_tool_message(malo), _tool_message(bueno)])
    use_client(monkeypatch, client)

    result = ai.generate_routine(profile, catalog)

    assert len(client.calls) == 2
    tool_result = client.calls[1][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert "FORMATO" in tool_result["content"]
    assert result.routine.days[0].blocks[0].sets == 4


def test_valores_fuera_de_rango_persistentes_dan_error_claro(monkeypatch, catalog, profile):
    malo = _routine_payload(catalog, "barbell full squat", sets=12)
    client = FakeClient([_tool_message(malo)] * (engine.MAX_REPAIR_ATTEMPTS + 1))
    use_client(monkeypatch, client)

    with pytest.raises(engine.GenerationError, match="fuera de rango"):
        ai.generate_routine(profile, catalog)


def test_ejercicio_contraindicado_se_rechaza_aunque_lo_proponga_el_modelo(
    monkeypatch, catalog
):
    """La lesión se filtra antes de generar; el validador es la segunda barrera."""
    profile = Profile(
        experience="intermedio",
        days_per_week=1,
        equipment=["barbell"],
        injuries=["lumbar"],
    )
    payload = _routine_payload(catalog, "barbell deadlift")
    client = FakeClient([_tool_message(payload)] * (engine.MAX_REPAIR_ATTEMPTS + 1))
    use_client(monkeypatch, client)

    result = ai.generate_routine(profile, catalog)

    assert any(issue.code == "LESION" for issue in result.issues)


def test_respuesta_sin_herramienta_se_reintenta(monkeypatch, catalog, profile):
    texto = FakeMessage([FakeBlock("text", text="Aquí tienes tu rutina...")], "end_turn")
    bueno = _tool_message(_routine_payload(catalog, "barbell full squat"))
    client = FakeClient([texto, bueno])
    use_client(monkeypatch, client)

    result = ai.generate_routine(profile, catalog)

    assert len(client.calls) == 2
    assert "No has devuelto la rutina" in client.calls[1][-1]["content"]


def test_rechazo_del_modelo_es_error_explicito(monkeypatch, catalog, profile):
    client = FakeClient([FakeMessage([], stop_reason="refusal")])
    use_client(monkeypatch, client)

    with pytest.raises(engine.GenerationError, match="declinado"):
        ai.generate_routine(profile, catalog)


def test_sin_candidatos_error_util(monkeypatch, catalog):
    profile = Profile(
        equipment=["barbell"],
        injuries=["hombro", "lumbar", "rodilla", "codo", "muneca", "cadera", "cuello"],
    )
    with pytest.raises(engine.GenerationError, match="No queda ningún ejercicio"):
        ai.generate_routine(profile, catalog)


# ---------------------------------------------------------------------------
# Adaptación
# ---------------------------------------------------------------------------


def test_adaptacion_envia_la_rutina_actual_y_la_peticion(monkeypatch, catalog, profile):
    from rutina_ia.fallback import plan_routine

    actual = plan_routine(profile, catalog).routine
    client = FakeClient([_tool_message(_routine_payload(catalog, "barbell full squat"))])
    use_client(monkeypatch, client)

    ai.adapt_routine(profile, catalog, actual, "quita la sentadilla, me molesta la rodilla")

    prompt = client.calls[0][0]["content"]
    assert "quita la sentadilla" in prompt
    assert actual.days[0].blocks[0].exercise_id in prompt
    assert "RUTINA ACTUAL" in prompt


def test_el_prompt_solo_ofrece_ejercicios_permitidos(monkeypatch, catalog):
    profile = Profile(
        experience="intermedio",
        days_per_week=1,
        equipment=["barbell", "dumbbell", "body weight"],
        injuries=["hombro"],
    )
    client = FakeClient(
        [_tool_message(_routine_payload(catalog, "barbell full squat"))]
        * (engine.MAX_REPAIR_ATTEMPTS + 1)
    )
    use_client(monkeypatch, client)

    ai.generate_routine(profile, catalog)

    prompt = client.calls[0][0]["content"]
    press = next(e for e in catalog.exercises if e.name == "barbell bench press")
    assert f"{press.id} | {press.name}" not in prompt
