"""API HTTP y servidor de la aplicación.

El servidor es deliberadamente sin estado: el cliente conserva la rutina y la
reenvía en cada petición de adaptación o exportación. Así no hace falta base
de datos ni sesiones, y cualquier rutina exportada se puede reproducir con
solo su JSON.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import claude_code, config
from .catalog import get_catalog
from .engine import GenerationError
from .export import render_html, render_markdown
from .fallback import NoViablePlan, plan_routine
from .models import JOINTS, Profile, Routine, RoutineResult

STATIC = Path(__file__).parent / "static"
TEMPLATES = Path(__file__).parent / "templates"

app = FastAPI(
    title="Rutina IA",
    description="Generador de rutinas de fuerza asistido por IA",
    version="1.0.0",
)
app.mount("/static", StaticFiles(directory=STATIC), name="static")

# Copia local de los GIF, si se ha descargado (ver scripts/fetch_media.py).
if config.MEDIA_DIR.is_dir():
    app.mount("/media", StaticFiles(directory=config.MEDIA_DIR), name="media")


# ---------------------------------------------------------------------------
# Esquemas de petición
# ---------------------------------------------------------------------------


ENGINE_CHOICES = ("auto", "suscripcion", "api", "determinista")


class GenerateRequest(BaseModel):
    profile: Profile
    engine: str = Field(
        "auto", description="auto | suscripcion | api | determinista"
    )


class AdaptRequest(BaseModel):
    profile: Profile
    routine: Routine
    request: str = Field(min_length=1, max_length=2000)
    engine: str = Field("auto", description="auto | suscripcion | api")


class DocumentRequest(BaseModel):
    profile: Profile
    result: RoutineResult


# ---------------------------------------------------------------------------
# Motor de generación
# ---------------------------------------------------------------------------


def resolve_engine(requested: str) -> str:
    """Traduce el motor pedido al que se va a usar de verdad.

    «auto» prefiere la suscripción a la clave de API: si tienes Claude Code
    con sesión iniciada, generar una rutina no debería costarte saldo aparte.
    """
    if requested not in ENGINE_CHOICES:
        raise HTTPException(
            status_code=400,
            detail=f"Motor desconocido «{requested}». Opciones: {', '.join(ENGINE_CHOICES)}.",
        )

    if requested == "auto" and config.DEFAULT_ENGINE != "auto":
        requested = config.DEFAULT_ENGINE

    if requested == "suscripcion":
        if not claude_code.available():
            raise HTTPException(
                status_code=400,
                detail=(
                    "No se encontró el ejecutable de Claude Code en esta máquina. "
                    "Instálalo e inicia sesión con `claude login`, o usa el motor "
                    "«api» con ANTHROPIC_API_KEY."
                ),
            )
        return "suscripcion"

    if requested == "api":
        if not config.has_api_key():
            raise HTTPException(
                status_code=400,
                detail=(
                    "No hay credenciales de API configuradas. Define "
                    "ANTHROPIC_API_KEY, usa el motor «suscripcion» o el determinista."
                ),
            )
        return "api"

    if requested == "determinista":
        return "determinista"

    # auto: suscripción primero, API después, plantillas como último recurso.
    if claude_code.available():
        return "suscripcion"
    if config.has_api_key():
        return "api"
    return "determinista"


def _model_backend(engine: str):
    """Módulo que implementa `generate_routine` y `adapt_routine`."""
    if engine == "suscripcion":
        return claude_code
    # Import perezoso: sin clave configurada la app no debe requerir el SDK.
    from . import ai

    return ai


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (TEMPLATES / "index.html").read_text(encoding="utf-8")


@app.get("/api/options")
def options() -> dict:
    catalog = get_catalog()
    return {
        "equipment": [
            {"value": value, "label": label} for value, label in catalog.equipment_options()
        ],
        "injuries": list(JOINTS),
        "goals": [
            {"value": "fuerza", "label": "Fuerza máxima"},
            {"value": "fuerza_hipertrofia", "label": "Fuerza + hipertrofia"},
            {"value": "hipertrofia", "label": "Hipertrofia con base de fuerza"},
        ],
        "experience": ["principiante", "intermedio", "avanzado"],
        "exercise_count": len(catalog),
        "local_media": config.MEDIA_DIR.is_dir(),
        "engines": {
            "suscripcion": {
                "available": claude_code.available(),
                "label": "Suscripción (Claude Code)",
                "detail": claude_code.version(),
            },
            "api": {
                "available": config.has_api_key(),
                "label": "API de Anthropic",
                "detail": config.MODEL if config.has_api_key() else None,
            },
            "determinista": {
                "available": True,
                "label": "Planificador determinista",
                "detail": "sin modelo, plantillas locales",
            },
        },
        "active_engine": resolve_engine("auto"),
        "model": config.MODEL,
    }


@app.post("/api/routines", response_model=RoutineResult)
def create_routine(payload: GenerateRequest) -> RoutineResult:
    catalog = get_catalog()
    engine = resolve_engine(payload.engine)

    if engine == "determinista":
        try:
            return plan_routine(payload.profile, catalog)
        except NoViablePlan as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        return _model_backend(engine).generate_routine(payload.profile, catalog)
    except GenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/routines/adapt", response_model=RoutineResult)
def adapt(payload: AdaptRequest) -> RoutineResult:
    engine = resolve_engine(payload.engine)
    if engine == "determinista":
        raise HTTPException(
            status_code=400,
            detail=(
                "Adaptar una rutina requiere un modelo. Inicia sesión en Claude "
                "Code (`claude login`) para usar tu suscripción, define "
                "ANTHROPIC_API_KEY, o regenera la rutina cambiando el perfil."
            ),
        )

    try:
        return _model_backend(engine).adapt_routine(
            payload.profile, get_catalog(), payload.routine, payload.request
        )
    except GenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/document.html", response_class=HTMLResponse)
def document_html(payload: DocumentRequest, embed: bool = False) -> str:
    """Documento imprimible. Con `?embed=1` incrusta los GIF descargados."""
    return render_html(payload.result, payload.profile, get_catalog(), embed_media=embed)


@app.post("/api/document.md", response_class=PlainTextResponse)
def document_markdown(payload: DocumentRequest) -> str:
    return render_markdown(payload.result, payload.profile, get_catalog())


@app.get("/api/exercises/{exercise_id}")
def exercise_detail(exercise_id: str) -> dict:
    exercise = get_catalog().get(exercise_id)
    if exercise is None:
        raise HTTPException(status_code=404, detail="Ejercicio no encontrado")
    return {
        "id": exercise.id,
        "name": exercise.name,
        "body_part": exercise.body_part_es,
        "target": exercise.target_es,
        "equipment": exercise.equipment_es,
        "pattern": exercise.pattern,
        "joints": list(exercise.joints),
        "gif_url": exercise.gif_src(),
        "image_url": exercise.image_url,
        "attribution": exercise.attribution,
        "steps": list(exercise.steps_es),
    }


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "exercises": len(get_catalog())}
