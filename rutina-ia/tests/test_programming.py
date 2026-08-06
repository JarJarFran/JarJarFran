"""El validador determinista: lo que acepta y lo que rechaza."""

from __future__ import annotations

import pytest

from rutina_ia.catalog import get_catalog
from rutina_ia.fallback import plan_routine
from rutina_ia.models import Block, Day, Profile, Routine
from rutina_ia.programming import (
    blocking_issues,
    estimate_minutes,
    validate,
    weekly_sets,
)


@pytest.fixture(scope="module")
def catalog():
    return get_catalog()


@pytest.fixture
def profile():
    return Profile(
        goal="fuerza",
        experience="intermedio",
        days_per_week=3,
        session_minutes=75,
        equipment=["barbell", "dumbbell", "body weight", "cable"],
    )


def _routine_with(catalog, blocks: list[Block], days: int = 3) -> Routine:
    """Rutina mínima con `days` días; el primero lleva los bloques dados."""
    all_days = [Day(name="Día 1", blocks=blocks)]
    for index in range(2, days + 1):
        all_days.append(Day(name=f"Día {index}", blocks=list(blocks)))
    return Routine(
        title="t", summary="s", goal="fuerza", progression="p", days=all_days
    )


def _find(catalog, name: str) -> str:
    return next(e for e in catalog.exercises if e.name == name).id


# ---------------------------------------------------------------------------
# Errores que deben bloquear
# ---------------------------------------------------------------------------


def test_ejercicio_inexistente_es_error(catalog, profile):
    routine = _routine_with(
        catalog, [Block(exercise_id="9999", sets=3, reps="5", rir=2, rest_seconds=180)]
    )
    codes = {issue.code for issue in blocking_issues(validate(routine, profile, catalog))}
    assert "EJERCICIO_DESCONOCIDO" in codes


def test_material_no_disponible_es_error(catalog):
    sled = next(e for e in catalog.exercises if e.equipment == "sled machine")
    profile = Profile(equipment=["body weight"], days_per_week=1)
    routine = _routine_with(
        catalog,
        [Block(exercise_id=sled.id, sets=3, reps="5", rir=2, rest_seconds=180)],
        days=1,
    )
    codes = {issue.code for issue in blocking_issues(validate(routine, profile, catalog))}
    assert "MATERIAL_NO_DISPONIBLE" in codes


def test_ejercicio_contraindicado_es_error(catalog):
    press = _find(catalog, "barbell bench press")
    profile = Profile(equipment=["barbell"], injuries=["hombro"], days_per_week=1)
    routine = _routine_with(
        catalog,
        [Block(exercise_id=press, sets=3, reps="5", rir=2, rest_seconds=180)],
        days=1,
    )
    codes = {issue.code for issue in blocking_issues(validate(routine, profile, catalog))}
    assert "LESION" in codes


def test_rir_por_debajo_del_minimo_del_nivel_es_error(catalog):
    squat = _find(catalog, "barbell full squat")
    profile = Profile(
        experience="principiante", equipment=["barbell"], days_per_week=1
    )
    routine = _routine_with(
        catalog,
        [
            Block(
                exercise_id=squat,
                sets=3,
                reps="5",
                rir=0,  # principiante: mínimo 2
                rest_seconds=180,
                role="principal",
            )
        ],
        days=1,
    )
    codes = {issue.code for issue in blocking_issues(validate(routine, profile, catalog))}
    assert "RIR_BAJO" in codes


def test_numero_de_dias_incorrecto_es_error(catalog, profile):
    squat = _find(catalog, "barbell full squat")
    routine = _routine_with(
        catalog,
        [Block(exercise_id=squat, sets=3, reps="5", rir=2, rest_seconds=180)],
        days=2,  # el perfil pide 3
    )
    codes = {issue.code for issue in blocking_issues(validate(routine, profile, catalog))}
    assert "DIAS_INCORRECTOS" in codes


def test_exceso_de_volumen_es_error(catalog, profile):
    squat = _find(catalog, "barbell full squat")
    routine = _routine_with(
        catalog,
        [
            Block(
                exercise_id=squat, sets=10, reps="5", rir=2, rest_seconds=180,
                role="principal",
            )
        ],
        days=3,  # 30 series semanales de cuádriceps
    )
    codes = {issue.code for issue in blocking_issues(validate(routine, profile, catalog))}
    assert "VOLUMEN_ALTO" in codes


# ---------------------------------------------------------------------------
# Avisos que no bloquean
# ---------------------------------------------------------------------------


def test_descanso_corto_es_solo_aviso(catalog, profile):
    squat = _find(catalog, "barbell full squat")
    routine = _routine_with(
        catalog,
        [
            Block(
                exercise_id=squat, sets=3, reps="5", rir=2, rest_seconds=30,
                role="principal",
            )
        ],
    )
    issues = validate(routine, profile, catalog)
    corto = [i for i in issues if i.code == "DESCANSO_CORTO"]
    assert corto and all(i.severity == "aviso" for i in corto)


def test_no_avisa_de_volumen_bajo_en_grupos_no_entrenables(catalog):
    """Con la rodilla lesionada no hay cuádriceps que entrenar: no es un aviso útil."""
    profile = Profile(equipment=["body weight"], injuries=["rodilla"], days_per_week=1)
    pushup = _find(catalog, "push-up")
    routine = _routine_with(
        catalog,
        [Block(exercise_id=pushup, sets=3, reps="8-10", rir=2, rest_seconds=90)],
        days=1,
    )
    bajos = {
        issue.message.split(":")[0]
        for issue in validate(routine, profile, catalog)
        if issue.code == "VOLUMEN_BAJO"
    }
    assert "cuadriceps" not in bajos


# ---------------------------------------------------------------------------
# Cálculos auxiliares
# ---------------------------------------------------------------------------


def test_compuesto_reparte_volumen_a_sinergistas(catalog):
    press = _find(catalog, "barbell bench press")
    routine = _routine_with(
        catalog,
        [Block(exercise_id=press, sets=4, reps="5", rir=2, rest_seconds=180)],
        days=1,
    )
    volume = weekly_sets(routine, catalog)
    assert volume["pecho"] == 4
    # Tríceps y hombros son sinergistas: media serie por serie del compuesto.
    assert volume["triceps"] == 2
    assert volume["hombros"] == 2


def test_estimacion_de_duracion_incluye_calentamiento(catalog):
    squat = _find(catalog, "barbell full squat")
    blocks = [
        Block(exercise_id=squat, sets=4, reps="5", rir=2, rest_seconds=180, role="principal")
    ]
    # 10 min de calentamiento + 4 × (5 reps × 4 s + 180 s) = 10 + 13,3 min
    assert 22 <= estimate_minutes(blocks, catalog) <= 25


# ---------------------------------------------------------------------------
# El planificador determinista respeta su propio validador
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("days", [1, 2, 3, 4, 5, 6])
@pytest.mark.parametrize("experience", ["principiante", "intermedio", "avanzado"])
def test_planificador_no_produce_errores(catalog, days, experience):
    profile = Profile(
        goal="fuerza",
        experience=experience,
        days_per_week=days,
        session_minutes=75,
        equipment=["barbell", "dumbbell", "body weight", "cable", "leverage machine"],
    )
    result = plan_routine(profile, catalog)
    assert len(result.routine.days) == days
    assert blocking_issues(result.issues) == []


@pytest.mark.parametrize(
    "injuries",
    [["hombro"], ["lumbar"], ["rodilla"], ["lumbar", "rodilla"], ["hombro", "codo", "muneca"]],
)
def test_planificador_respeta_las_lesiones(catalog, injuries):
    profile = Profile(
        experience="intermedio",
        days_per_week=4,
        equipment=["barbell", "dumbbell", "body weight", "cable"],
        injuries=injuries,
    )
    result = plan_routine(profile, catalog)
    assert blocking_issues(result.issues) == []
    for block in result.routine.all_blocks():
        exercise = catalog.get(block.exercise_id)
        assert not set(injuries).intersection(exercise.joints)
