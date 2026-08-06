"""El catálogo y su filtrado por lesión/material."""

from __future__ import annotations

import pytest

from rutina_ia.catalog import get_catalog
from rutina_ia.models import Profile


@pytest.fixture(scope="module")
def catalog():
    return get_catalog()


def test_catalogo_completo(catalog):
    assert len(catalog) == 1324


def test_todo_ejercicio_tiene_gif_y_atribucion(catalog):
    for exercise in catalog.exercises:
        assert exercise.gif_url.startswith("https://raw.githubusercontent.com/")
        assert exercise.gif_url.endswith(".gif")
        assert "Gym visual" in exercise.attribution


def test_todo_ejercicio_tiene_instrucciones_en_espanol(catalog):
    vacios = [e.id for e in catalog.exercises if not e.steps_es]
    assert vacios == []


def test_filtro_de_material(catalog):
    profile = Profile(equipment=["body weight"])
    for exercise in catalog.candidates(profile):
        assert exercise.equipment == "body weight"


def test_filtro_de_lesion_excluye_la_articulacion(catalog):
    profile = Profile(
        equipment=["barbell", "dumbbell", "body weight", "cable"],
        injuries=["hombro"],
    )
    candidates = catalog.candidates(profile)
    assert candidates, "el filtro no debería vaciar el catálogo"
    for exercise in candidates:
        assert "hombro" not in exercise.joints


def test_press_de_banca_se_excluye_con_lesion_de_hombro(catalog):
    press = next(e for e in catalog.exercises if e.name == "barbell bench press")
    assert "hombro" in press.joints

    sano = Profile(equipment=["barbell"])
    lesionado = Profile(equipment=["barbell"], injuries=["hombro"])
    assert press.id in {e.id for e in catalog.candidates(sano)}
    assert press.id not in {e.id for e in catalog.candidates(lesionado)}


def test_peso_muerto_se_excluye_con_lesion_lumbar(catalog):
    deadlift = next(e for e in catalog.exercises if e.name == "barbell deadlift")
    assert "lumbar" in deadlift.joints
    lesionado = Profile(equipment=["barbell"], injuries=["lumbar"])
    assert deadlift.id not in {e.id for e in catalog.candidates(lesionado)}


def test_limite_reparte_entre_patrones(catalog):
    profile = Profile(equipment=["barbell", "dumbbell", "body weight", "cable"])
    subset = catalog.candidates(profile, limit=60)
    assert len(subset) == 60
    # Con reparto round-robin ningún patrón debería acaparar el pool.
    patrones = {e.pattern for e in subset}
    assert len(patrones) >= 8


def test_cardio_fuera_del_pool(catalog):
    profile = Profile(equipment=["body weight", "stationary bike", "elliptical machine"])
    for exercise in catalog.candidates(profile):
        assert exercise.pattern != "cardio"
        assert exercise.muscle_group != "cardio"
