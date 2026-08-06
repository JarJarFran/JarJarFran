"""Documento final y endpoints HTTP."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from rutina_ia.api import app
from rutina_ia.catalog import get_catalog
from rutina_ia.export import render_html, render_markdown
from rutina_ia.fallback import plan_routine
from rutina_ia.models import Profile


@pytest.fixture(scope="module")
def catalog():
    return get_catalog()


@pytest.fixture(scope="module")
def profile():
    return Profile(
        goal="fuerza",
        experience="intermedio",
        days_per_week=3,
        session_minutes=75,
        equipment=["barbell", "dumbbell", "body weight"],
    )


@pytest.fixture(scope="module")
def result(profile, catalog):
    return plan_routine(profile, catalog)


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Documento
# ---------------------------------------------------------------------------


def test_html_incluye_un_gif_por_ejercicio(result, profile, catalog):
    html = render_html(result, profile, catalog)
    for block in result.routine.all_blocks():
        exercise = catalog.get(block.exercise_id)
        assert exercise.gif_url in html


def test_html_conserva_la_atribucion(result, profile, catalog):
    html = render_html(result, profile, catalog)
    assert "Gym visual" in html
    assert "gymvisual.com" in html


def test_html_lleva_las_instrucciones_en_espanol(result, profile, catalog):
    html = render_html(result, profile, catalog)
    exercise = catalog.get(result.routine.days[0].blocks[0].exercise_id)
    assert exercise.steps_es[0][:40] in html


def test_sin_copia_local_el_html_enlaza_a_la_fuente(result, profile, catalog, tmp_path, monkeypatch):
    monkeypatch.setattr("rutina_ia.config.MEDIA_DIR", tmp_path / "vacio")
    monkeypatch.setattr("rutina_ia.catalog.MEDIA_DIR", tmp_path / "vacio")
    html = render_html(result, profile, catalog, embed_media=True)
    # Sin GIF descargados no hay nada que incrustar: se enlaza al original.
    assert "data:image/gif" not in html
    assert "raw.githubusercontent.com" in html


def test_con_copia_local_el_html_incrusta_los_gifs(result, profile, catalog, tmp_path, monkeypatch):
    """Un GIF descargado se incrusta como data URI y el documento vale sin red."""
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr("rutina_ia.catalog.MEDIA_DIR", media)

    exercise = catalog.get(result.routine.days[0].blocks[0].exercise_id)
    (media / exercise.media_name).write_bytes(b"GIF89a-falso")

    html = render_html(result, profile, catalog, embed_media=True)
    assert "data:image/gif;base64," in html
    assert exercise.gif_url not in html  # ese ya no se enlaza, va incrustado


def test_gif_src_prefiere_la_copia_local(catalog, tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr("rutina_ia.catalog.MEDIA_DIR", media)

    exercise = next(e for e in catalog.exercises if e.name == "barbell bench press")
    assert exercise.gif_src() == exercise.gif_url  # aún no descargado

    (media / exercise.media_name).write_bytes(b"GIF89a-falso")
    assert exercise.gif_src() == f"/media/{exercise.media_name}"


def test_markdown_enlaza_los_gifs(result, profile, catalog):
    markdown = render_markdown(result, profile, catalog)
    exercise = catalog.get(result.routine.days[0].blocks[0].exercise_id)
    assert f"![{exercise.name}]({exercise.gif_url})" in markdown
    assert "Gym visual" in markdown


def test_markdown_incluye_progresion_y_volumen(result, profile, catalog):
    markdown = render_markdown(result, profile, catalog)
    assert "## Progresión" in markdown
    assert "## Volumen semanal" in markdown


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["exercises"] == 1324


def test_options(client):
    payload = client.get("/api/options").json()
    assert payload["exercise_count"] == 1324
    assert {"value": "barbell", "label": "barra"} in payload["equipment"]
    assert "hombro" in payload["injuries"]


def test_index_sirve_la_pagina(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Rutina IA" in response.text


def test_generar_con_motor_determinista(client, profile):
    response = client.post(
        "/api/routines",
        json={"profile": profile.model_dump(), "engine": "determinista"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["engine"] == "determinista"
    assert len(payload["routine"]["days"]) == profile.days_per_week
    assert not [i for i in payload["issues"] if i["severity"] == "error"]


def test_generar_con_perfil_invalido(client):
    response = client.post(
        "/api/routines",
        json={"profile": {"days_per_week": 99}, "engine": "determinista"},
    )
    assert response.status_code == 422


def test_documento_html_por_api(client, profile, result):
    response = client.post(
        "/api/document.html",
        json={"profile": profile.model_dump(), "result": result.model_dump()},
    )
    assert response.status_code == 200
    assert "<!doctype html>" in response.text.lower()
    assert "Gym visual" in response.text


def test_documento_markdown_por_api(client, profile, result):
    response = client.post(
        "/api/document.md",
        json={"profile": profile.model_dump(), "result": result.model_dump()},
    )
    assert response.status_code == 200
    assert response.text.startswith("# ")


def test_detalle_de_ejercicio(client, catalog):
    press = next(e for e in catalog.exercises if e.name == "barbell bench press")
    payload = client.get(f"/api/exercises/{press.id}").json()
    assert payload["name"] == "barbell bench press"
    assert payload["gif_url"].endswith(".gif")
    assert payload["steps"]


def test_detalle_de_ejercicio_inexistente(client):
    assert client.get("/api/exercises/0000").status_code == 404


def test_adaptar_sin_ningun_motor_devuelve_400(client, profile, result):
    """Sin clave y sin Claude Code no hay forma de adaptar (conftest los quita)."""
    response = client.post(
        "/api/routines/adapt",
        json={
            "profile": profile.model_dump(),
            "routine": result.routine.model_dump(),
            "request": "quita el press de banca",
        },
    )
    assert response.status_code == 400
    assert "claude login" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Selección de motor
# ---------------------------------------------------------------------------


def test_options_reporta_los_motores(client):
    payload = client.get("/api/options").json()
    engines = payload["engines"]
    assert set(engines) == {"suscripcion", "api", "determinista"}
    # El conftest deja el entorno sin credenciales ni CLI.
    assert engines["suscripcion"]["available"] is False
    assert engines["api"]["available"] is False
    assert engines["determinista"]["available"] is True
    assert payload["active_engine"] == "determinista"


def test_auto_prefiere_la_suscripcion_a_la_api(monkeypatch):
    """Si tienes Claude Code, generar no debería gastarte saldo de API."""
    from rutina_ia.api import resolve_engine

    monkeypatch.setattr("rutina_ia.claude_code.available", lambda: True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-de-prueba")
    assert resolve_engine("auto") == "suscripcion"


def test_auto_cae_a_la_api_sin_claude_code(monkeypatch):
    from rutina_ia.api import resolve_engine

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-de-prueba")
    assert resolve_engine("auto") == "api"


def test_auto_cae_al_determinista_sin_nada(client):
    from rutina_ia.api import resolve_engine

    assert resolve_engine("auto") == "determinista"


def test_pedir_suscripcion_sin_cli_da_error_accionable(client, profile):
    response = client.post(
        "/api/routines",
        json={"profile": profile.model_dump(), "engine": "suscripcion"},
    )
    assert response.status_code == 400
    assert "claude login" in response.json()["detail"]


def test_motor_desconocido_se_rechaza(client, profile):
    response = client.post(
        "/api/routines",
        json={"profile": profile.model_dump(), "engine": "chatgpt"},
    )
    assert response.status_code == 400
    assert "Motor desconocido" in response.json()["detail"]


def test_variable_de_entorno_fija_el_motor(monkeypatch):
    """RUTINA_IA_ENGINE gana sobre la detección automática."""
    from rutina_ia import api, config

    monkeypatch.setattr(config, "DEFAULT_ENGINE", "determinista")
    monkeypatch.setattr("rutina_ia.claude_code.available", lambda: True)
    assert api.resolve_engine("auto") == "determinista"


def test_el_documento_nombra_el_motor_usado(result, profile, catalog):
    html = render_html(result, profile, catalog)
    assert "planificador determinista" in html

    result.engine = "suscripcion"
    assert "Claude (suscripción)" in render_html(result, profile, catalog)
    result.engine = "determinista"
