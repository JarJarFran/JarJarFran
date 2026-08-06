"""El motor de suscripción, con el CLI de Claude Code simulado.

No se lanza el CLI de verdad. Lo que se comprueba es que se construye bien la
invocación (esquema, sesión, reanudación, herramientas bloqueadas) y que los
modos de fallo se traducen a mensajes que le sirvan de algo al usuario.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from rutina_ia import claude_code, engine
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
        equipment=["barbell", "dumbbell", "body weight"],
    )


class FakeCompleted:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class FakeCli:
    """Sustituye a `subprocess.run` y registra cada invocación."""

    def __init__(self, responses: list[FakeCompleted]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, command, **kwargs):
        self.calls.append({"command": command, "input": kwargs.get("input", "")})
        if not self._responses:
            raise AssertionError("El CLI se ha invocado más veces de las previstas")
        return self._responses.pop(0)


def _payload(catalog, exercise_name: str, sets: int = 4, rir: int = 2) -> dict:
    exercise = next(e for e in catalog.exercises if e.name == exercise_name)
    return {
        "title": "Rutina de prueba",
        "summary": "Resumen.",
        "goal": "fuerza",
        "weeks": 4,
        "progression": "Sube 2,5 kg cuando completes el rango.",
        "deload": "",
        "safety_notes": [],
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


def _ok(structured: dict | None) -> FakeCompleted:
    return FakeCompleted(
        stdout=json.dumps(
            {
                "is_error": False,
                "subtype": "success",
                "session_id": "sesion-de-prueba",
                "result": "",
                "structured_output": structured,
            }
        )
    )


def _use_cli(monkeypatch, cli: FakeCli) -> None:
    monkeypatch.setattr(claude_code, "available", lambda: True)
    monkeypatch.setattr(subprocess, "run", cli)


# ---------------------------------------------------------------------------
# Construcción de la invocación
# ---------------------------------------------------------------------------


def test_genera_pasando_el_esquema_y_el_prompt_por_stdin(monkeypatch, catalog, profile):
    cli = FakeCli([_ok(_payload(catalog, "barbell full squat"))])
    _use_cli(monkeypatch, cli)

    result = claude_code.generate_routine(profile, catalog)

    assert result.engine == "suscripcion"
    assert len(cli.calls) == 1

    command = cli.calls[0]["command"]
    assert command[0] == claude_code.CLAUDE_CODE_BIN
    assert "--print" in command
    assert "--output-format" in command and "json" in command

    # El esquema enviado al CLI es exactamente el mismo que usa la API.
    schema = json.loads(command[command.index("--json-schema") + 1])
    assert schema == engine.ROUTINE_SCHEMA

    # El encargo viaja por stdin, no en la línea de comandos.
    assert "PERFIL" in cli.calls[0]["input"]


def test_no_hereda_ajustes_ni_herramientas_del_usuario(monkeypatch, catalog, profile):
    cli = FakeCli([_ok(_payload(catalog, "barbell full squat"))])
    _use_cli(monkeypatch, cli)
    claude_code.generate_routine(profile, catalog)

    command = cli.calls[0]["command"]
    # Sin CLAUDE.md, hooks ni ajustes: la generación depende solo del prompt.
    assert command[command.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in command
    # Y sin acceso al disco ni a la red desde el modelo.
    blocked = {command[i + 1] for i, arg in enumerate(command) if arg == "--disallowedTools"}
    assert {"Bash", "Read", "Write", "Edit", "WebFetch"} <= blocked


def test_el_prompt_de_sistema_sustituye_al_de_claude_code(monkeypatch, catalog, profile):
    cli = FakeCli([_ok(_payload(catalog, "barbell full squat"))])
    _use_cli(monkeypatch, cli)
    claude_code.generate_routine(profile, catalog)

    command = cli.calls[0]["command"]
    system = command[command.index("--system-prompt") + 1]
    assert "preparador físico" in system


def test_la_reparacion_reanuda_la_misma_sesion(monkeypatch, catalog, profile):
    malo = _payload(catalog, "barbell full squat", rir=0)  # RIR_BAJO para intermedio
    bueno = _payload(catalog, "barbell full squat", rir=2)
    cli = FakeCli([_ok(malo), _ok(bueno)])
    _use_cli(monkeypatch, cli)

    result = claude_code.generate_routine(profile, catalog)

    assert result.repair_attempts == 1
    assert len(cli.calls) == 2

    primera, segunda = cli.calls
    # La primera crea la sesión; la segunda la reanuda con el mismo id.
    assert "--session-id" in primera["command"]
    assert "--resume" in segunda["command"]
    sesion = primera["command"][primera["command"].index("--session-id") + 1]
    assert segunda["command"][segunda["command"].index("--resume") + 1] == sesion
    # Y el segundo turno lleva el informe del validador.
    assert "RIR_BAJO" in segunda["input"]


def test_adaptacion_envia_la_rutina_actual(monkeypatch, catalog, profile):
    from rutina_ia.fallback import plan_routine

    actual = plan_routine(profile, catalog).routine
    cli = FakeCli([_ok(_payload(catalog, "barbell full squat"))])
    _use_cli(monkeypatch, cli)

    claude_code.adapt_routine(profile, catalog, actual, "quita la sentadilla")

    enviado = cli.calls[0]["input"]
    assert "quita la sentadilla" in enviado
    assert "RUTINA ACTUAL" in enviado


# ---------------------------------------------------------------------------
# Modos de fallo
# ---------------------------------------------------------------------------


def test_sin_cli_instalado_error_accionable(monkeypatch, catalog, profile):
    monkeypatch.setattr(claude_code, "available", lambda: False)
    with pytest.raises(engine.GenerationError, match="claude login"):
        claude_code.generate_routine(profile, catalog)


def test_sesion_no_iniciada_se_explica(monkeypatch, catalog, profile):
    cli = FakeCli([FakeCompleted(stderr="Error: not authenticated", returncode=1)])
    _use_cli(monkeypatch, cli)
    with pytest.raises(engine.GenerationError, match="claude login"):
        claude_code.generate_routine(profile, catalog)


def test_limite_de_uso_se_explica(monkeypatch, catalog, profile):
    cli = FakeCli([FakeCompleted(stderr="Usage limit reached", returncode=1)])
    _use_cli(monkeypatch, cli)
    with pytest.raises(engine.GenerationError, match="límite de uso"):
        claude_code.generate_routine(profile, catalog)


def test_timeout_se_explica(monkeypatch, catalog, profile):
    def lento(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=1)

    monkeypatch.setattr(claude_code, "available", lambda: True)
    monkeypatch.setattr(subprocess, "run", lento)
    with pytest.raises(engine.GenerationError, match="no respondió"):
        claude_code.generate_routine(profile, catalog)


def test_salida_no_json_se_explica(monkeypatch, catalog, profile):
    cli = FakeCli([FakeCompleted(stdout="esto no es json")])
    _use_cli(monkeypatch, cli)
    with pytest.raises(engine.GenerationError, match="no es JSON"):
        claude_code.generate_routine(profile, catalog)


def test_sin_salida_estructurada_se_reintenta(monkeypatch, catalog, profile):
    cli = FakeCli([_ok(None), _ok(_payload(catalog, "barbell full squat"))])
    _use_cli(monkeypatch, cli)

    claude_code.generate_routine(profile, catalog)

    assert len(cli.calls) == 2
    assert "No has devuelto la rutina" in cli.calls[1]["input"]


def test_la_lesion_sigue_bloqueando_por_este_motor(monkeypatch, catalog):
    """El filtro y el validador son los mismos, se use el motor que se use."""
    lesionado = Profile(
        experience="intermedio", days_per_week=1, equipment=["barbell"], injuries=["lumbar"]
    )
    payload = _payload(catalog, "barbell deadlift")
    cli = FakeCli([_ok(payload)] * (engine.MAX_REPAIR_ATTEMPTS + 1))
    _use_cli(monkeypatch, cli)

    result = claude_code.generate_routine(lesionado, catalog)

    assert any(issue.code == "LESION" for issue in result.issues)
