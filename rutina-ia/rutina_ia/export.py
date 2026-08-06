"""Generación del documento final de la rutina (HTML y Markdown).

El HTML es autocontenido salvo por los GIF, que se enlazan al repositorio
original del dataset. El material audiovisual es propiedad de Gym visual y se
redistribuye allí bajo permiso expreso a 180×180 con la atribución intacta;
enlazarlo en vez de copiarlo mantiene esa condición y evita incorporar al
repositorio material que no está cubierto por su licencia MIT.

Con `embed_media=True` y una copia local descargada (scripts/fetch_media.py)
los GIF se incrustan como data URI y el documento queda 100% autocontenido,
útil para consultarlo en el gimnasio sin cobertura.
"""

from __future__ import annotations

import base64
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .catalog import Catalog, Exercise
from .models import Profile, Routine, RoutineResult
from .programming import estimate_minutes, weekly_sets

TEMPLATES = Path(__file__).parent / "templates"

ATTRIBUTION = "© Gym visual — https://gymvisual.com/"
DATASET_URL = "https://github.com/hasaneyldrm/exercises-dataset"

# Cómo se nombra en el documento el motor que produjo la rutina.
ENGINE_LABELS = {
    "suscripcion": "Claude (suscripción)",
    "api": "Claude (API)",
    "determinista": "planificador determinista",
}

_env = Environment(
    loader=FileSystemLoader(TEMPLATES),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _gif_source(exercise: Exercise, embed: bool) -> str:
    """URL del GIF para el documento.

    Con `embed` y copia local disponible se incrusta como data URI, de modo
    que el HTML resultante se puede guardar, enviar por correo o abrir sin
    conexión y sigue mostrando las ejecuciones. Sin copia local se enlaza al
    repositorio original.
    """
    if embed and (path := exercise.local_gif) is not None:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:image/gif;base64,{encoded}"
    return exercise.gif_url


def _rows(routine: Routine, catalog: Catalog, embed: bool = False) -> list[dict]:
    """Días con sus bloques ya resueltos contra el catálogo."""
    days = []
    for day in routine.days:
        blocks = []
        for block in day.blocks:
            exercise = catalog.get(block.exercise_id)
            if exercise is None:
                continue
            blocks.append(
                {
                    "block": block,
                    "exercise": exercise,
                    "gif": _gif_source(exercise, embed),
                }
            )
        days.append(
            {
                "day": day,
                "blocks": blocks,
                "minutes": estimate_minutes(day.blocks, catalog),
            }
        )
    return days


def render_html(
    result: RoutineResult,
    profile: Profile,
    catalog: Catalog,
    embed_media: bool = False,
) -> str:
    template = _env.get_template("routine_doc.html")
    return template.render(
        routine=result.routine,
        issues=result.issues,
        engine=result.engine,
        engine_label=ENGINE_LABELS.get(result.engine, result.engine),
        profile=profile,
        days=_rows(result.routine, catalog, embed_media),
        volume=sorted(weekly_sets(result.routine, catalog).items()),
        attribution=ATTRIBUTION,
        dataset_url=DATASET_URL,
    )


def render_markdown(result: RoutineResult, profile: Profile, catalog: Catalog) -> str:
    routine = result.routine
    lines: list[str] = [f"# {routine.title}", "", routine.summary, ""]

    lines += [
        "## Perfil",
        "",
        f"- Objetivo: {routine.goal}",
        f"- Nivel: {profile.experience}",
        f"- Días por semana: {profile.days_per_week}",
        f"- Tiempo por sesión: {profile.session_minutes} min",
        f"- Material: {', '.join(profile.equipment)}",
        f"- Lesiones declaradas: {', '.join(profile.injuries) or 'ninguna'}",
        "",
    ]

    if routine.safety_notes:
        lines += ["## Seguridad", ""]
        lines += [f"- {note}" for note in routine.safety_notes]
        lines.append("")

    for entry in _rows(routine, catalog):
        day = entry["day"]
        lines += [
            f"## {day.name}",
            "",
            f"_{day.focus} · ~{entry['minutes']} min_",
            "",
            "| Ejercicio | Series × reps | RIR | Descanso | Rol |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in entry["blocks"]:
            block, exercise = item["block"], item["exercise"]
            lines.append(
                f"| {exercise.name} | {block.sets} × {block.reps} | {block.rir} | "
                f"{block.rest_seconds} s | {block.role} |"
            )
        lines.append("")
        for item in entry["blocks"]:
            block, exercise = item["block"], item["exercise"]
            lines += [
                f"### {exercise.name}",
                "",
                f"![{exercise.name}]({exercise.gif_url})",
                "",
                f"{exercise.body_part_es} · {exercise.target_es} · {exercise.equipment_es}",
                "",
            ]
            if block.notes:
                lines += [f"> {block.notes}", ""]
            lines += [f"{index}. {step}" for index, step in enumerate(exercise.steps_es, 1)]
            lines.append("")

    lines += ["## Progresión", "", routine.progression, ""]
    if routine.deload:
        lines += ["## Descarga", "", routine.deload, ""]

    volume = weekly_sets(routine, catalog)
    lines += ["## Volumen semanal (series efectivas)", "", "| Grupo | Series |", "| --- | --- |"]
    lines += [f"| {group} | {sets} |" for group, sets in sorted(volume.items())]
    lines.append("")

    if result.issues:
        lines += ["## Avisos del validador", ""]
        lines += [f"- **{issue.severity}** · {issue.code}: {issue.message}" for issue in result.issues]
        lines.append("")

    lines += [
        "---",
        "",
        f"GIF e imágenes: {ATTRIBUTION}. Datos de ejercicios: {DATASET_URL}.",
        "",
        "Este documento es material informativo de entrenamiento, no consejo "
        "médico. Ante dolor o lesión, consulta con un profesional sanitario.",
        "",
    ]
    return "\n".join(lines)


def exercise_media(exercise: Exercise) -> dict[str, str]:
    return {
        "gif_url": exercise.gif_url,
        "image_url": exercise.image_url,
        "attribution": exercise.attribution,
    }
