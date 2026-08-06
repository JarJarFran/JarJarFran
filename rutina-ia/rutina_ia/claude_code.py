"""Motor que habla con Claude a través del CLI de Claude Code.

Es el puente para usar una suscripción Claude Pro o Max en vez de una clave de
API: Claude Code ya guarda la sesión iniciada con `claude login`, y este motor
se apoya en ella. No hay tokens que extraer ni credenciales que manipular —
se invoca el CLI y él resuelve su propia autenticación, que es justo la forma
soportada de hacer esto.

Consecuencias de usar esta vía, para que no sorprendan:

- Requiere Claude Code instalado y con sesión iniciada **en la misma máquina**
  que ejecuta el servidor. Sirve para uso local o personal; no es una forma de
  montar un servicio multiusuario con una sola suscripción, que además
  incumpliría las condiciones de la suscripción.
- El consumo va contra los límites de tu plan, no contra saldo de API. Si
  agotas la ventana de uso, las peticiones fallan hasta que se renueve.
- El parámetro `effort` no está expuesto en el CLI, así que el control fino de
  profundidad de razonamiento solo existe en el motor de API.

La salida se fuerza con `--json-schema`, el mismo esquema que usa la
herramienta en el motor de API, y la corrección de errores reanuda la sesión
con `--resume`. El validador determinista se aplica idéntico en los dos casos.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from functools import lru_cache

from .catalog import Catalog
from .config import CLAUDE_CODE_BIN, CLAUDE_CODE_TIMEOUT, MODEL
from .engine import (
    ROUTINE_SCHEMA,
    GenerationError,
    parse_routine,
    run_with_repairs,
)
from .models import Profile, Routine, RoutineResult
from .prompts import SYSTEM, build_adaptation_prompt, build_generation_prompt

# La app solo necesita que el modelo razone y devuelva datos. Se le quitan las
# herramientas de disco, shell y red: no tiene nada que hacer en el sistema de
# ficheros del usuario, y un prompt inyectado a través del campo de notas
# tampoco.
BLOCKED_TOOLS = (
    "Bash",
    "Read",
    "Write",
    "Edit",
    "NotebookEdit",
    "WebSearch",
    "WebFetch",
    "Task",
    "Glob",
    "Grep",
)


def available() -> bool:
    """¿Hay un CLI de Claude Code utilizable en esta máquina?"""
    return shutil.which(CLAUDE_CODE_BIN) is not None


@lru_cache(maxsize=1)
def version() -> str | None:
    """Versión del CLI. Cacheada: lanzar un proceso por petición es absurdo."""
    if not available():
        return None
    try:
        completed = subprocess.run(
            [CLAUDE_CODE_BIN, "--version"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


class ClaudeCodeEngine:
    """Conversación con Claude Code, una invocación del CLI por turno.

    El CLI no mantiene un proceso vivo entre turnos: cada llamada arranca de
    cero y recupera el hilo por id de sesión. El primer turno lo crea con
    `--session-id` y los siguientes lo reanudan con `--resume`.
    """

    name = "claude-code"

    def __init__(self, model: str = MODEL, timeout: int = CLAUDE_CODE_TIMEOUT):
        self.model = model
        self.timeout = timeout
        self.session_id = str(uuid.uuid4())
        self._started = False

    def _command(self) -> list[str]:
        command = [
            CLAUDE_CODE_BIN,
            "--print",
            "--output-format", "json",
            "--json-schema", json.dumps(ROUTINE_SCHEMA),
            "--model", self.model,
            # El prompt de la app sustituye al de Claude Code: aquí no
            # queremos un agente de programación, queremos un preparador.
            "--system-prompt", SYSTEM,
            # Sin CLAUDE.md, hooks ni ajustes del usuario: la generación tiene
            # que depender solo de lo que este código envía, o deja de ser
            # reproducible.
            "--setting-sources", "",
            "--strict-mcp-config",
        ]
        for tool in BLOCKED_TOOLS:
            command += ["--disallowedTools", tool]

        if self._started:
            command += ["--resume", self.session_id]
        else:
            command += ["--session-id", self.session_id]
        return command

    def send(self, message: str) -> Routine | None:
        try:
            completed = subprocess.run(
                self._command(),
                input=message,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise GenerationError(
                f"Claude Code no respondió en {self.timeout} s. Sube "
                "RUTINA_IA_CLAUDE_CODE_TIMEOUT si tu máquina va justa."
            ) from exc
        except OSError as exc:
            raise GenerationError(f"No se pudo ejecutar «{CLAUDE_CODE_BIN}»: {exc}") from exc

        self._started = True

        if completed.returncode != 0:
            raise GenerationError(_explain_failure(completed.returncode, completed.stderr))

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise GenerationError(
                "Claude Code devolvió una salida que no es JSON. "
                f"Primeros caracteres: {completed.stdout[:200]!r}"
            ) from exc

        if payload.get("is_error"):
            raise GenerationError(
                "Claude Code terminó con error: "
                f"{payload.get('result') or payload.get('subtype') or 'sin detalle'}"
            )

        structured = payload.get("structured_output")
        if structured is None:
            # Contestó, pero sin emitir la rutina. El bucle de reparación
            # sabe insistir.
            return None
        return parse_routine(structured)


def _explain_failure(code: int, stderr: str) -> str:
    detail = stderr.strip().splitlines()
    tail = detail[-1] if detail else "sin salida de error"
    lowered = stderr.lower()
    if "login" in lowered or "authenticat" in lowered or "unauthor" in lowered:
        return (
            "Claude Code no tiene sesión iniciada. Ejecuta `claude login` en "
            f"esta máquina y vuelve a intentarlo. Detalle: {tail}"
        )
    if "rate limit" in lowered or "usage limit" in lowered:
        return (
            "Has agotado el límite de uso de tu plan. Espera a que se renueve "
            f"la ventana o usa el motor de API. Detalle: {tail}"
        )
    return f"Claude Code falló (código {code}): {tail}"


def _engine(model: str | None = None) -> ClaudeCodeEngine:
    if not available():
        raise GenerationError(
            f"No se encontró el ejecutable «{CLAUDE_CODE_BIN}». Instala Claude "
            "Code e inicia sesión con `claude login`, o configura "
            "ANTHROPIC_API_KEY para usar el motor de API."
        )
    return ClaudeCodeEngine(model=model or MODEL)


def _candidates(profile: Profile, catalog: Catalog):
    candidates = catalog.candidates(profile, limit=_max_candidates())
    if not candidates:
        raise GenerationError(
            "No queda ningún ejercicio disponible con ese material y esas "
            "lesiones. Añade material o revisa las articulaciones marcadas."
        )
    return candidates


def _max_candidates() -> int:
    from .config import MAX_CANDIDATES

    return MAX_CANDIDATES


def generate_routine(profile: Profile, catalog: Catalog) -> RoutineResult:
    prompt = build_generation_prompt(profile, _candidates(profile, catalog))
    return run_with_repairs(_engine(), prompt, profile, catalog, "suscripcion")


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
    return run_with_repairs(_engine(), prompt, profile, catalog, "suscripcion")
