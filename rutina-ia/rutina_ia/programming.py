"""Reglas de programación y validador determinista.

Este módulo es el que decide si una rutina es aceptable, la genere quien la
genere. La IA propone; esto dispone. Los rangos siguen el consenso habitual
de la literatura de entrenamiento de fuerza (series semanales efectivas por
grupo, rangos de repetición por objetivo, RIR mínimo por nivel y descansos
suficientes entre series pesadas), y están todos en un único sitio para que
se puedan discutir y ajustar sin tocar el resto de la aplicación.
"""

from __future__ import annotations

from .catalog import Catalog, Exercise
from .models import Block, Issue, Profile, Routine

# ---------------------------------------------------------------------------
# Series semanales efectivas por grupo muscular
# ---------------------------------------------------------------------------
# (mínimo, máximo). Por debajo del mínimo el estímulo es insuficiente; por
# encima del máximo el riesgo de sobreuso crece más rápido que la adaptación,
# que es justo lo que queremos evitar.

_MAJOR = (
    "pecho",
    "dorsales",
    "espalda_alta",
    "cuadriceps",
    "isquios",
    "gluteos",
    "hombros",
)
# Grupos pequeños: no se exige mínimo (reciben trabajo indirecto de sobra),
# solo se vigila el techo.
_MINOR = ("biceps", "triceps", "gemelos")

# Core y antebrazos acumulan mucho volumen indirecto —cada sentadilla y cada
# agarre cuentan— y lo toleran bien, así que su techo es más alto.
_TOLERANT = ("core", "antebrazos")

VOLUME_TARGETS: dict[str, dict[str, tuple[int, int]]] = {
    "principiante": {
        **{group: (6, 14) for group in _MAJOR},
        **{group: (0, 14) for group in _MINOR},
        **{group: (0, 18) for group in _TOLERANT},
    },
    "intermedio": {
        **{group: (10, 20) for group in _MAJOR},
        **{group: (0, 18) for group in _MINOR},
        **{group: (0, 24) for group in _TOLERANT},
    },
    "avanzado": {
        **{group: (10, 24) for group in _MAJOR},
        **{group: (0, 22) for group in _MINOR},
        **{group: (0, 28) for group in _TOLERANT},
    },
}

# Rangos de repeticiones por objetivo y rol del ejercicio.
REP_RANGES: dict[str, dict[str, tuple[int, int]]] = {
    "fuerza": {
        "principal": (1, 6),
        "secundario": (4, 8),
        "accesorio": (6, 15),
        "core": (5, 20),
        "movilidad": (5, 60),
    },
    "fuerza_hipertrofia": {
        "principal": (3, 8),
        "secundario": (6, 12),
        "accesorio": (8, 15),
        "core": (5, 25),
        "movilidad": (5, 60),
    },
    "hipertrofia": {
        "principal": (5, 10),
        "secundario": (6, 15),
        "accesorio": (8, 20),
        "core": (5, 30),
        "movilidad": (5, 60),
    },
}

# Descanso mínimo en segundos. Un descanso corto en una serie pesada degrada
# la técnica antes que el músculo, y la técnica degradada es la vía principal
# de lesión en entrenamiento de fuerza.
MIN_REST = {
    "principal": 150,
    "secundario": 90,
    "accesorio": 45,
    "core": 30,
    "movilidad": 20,
}

# RIR mínimo permitido por nivel. El principiante no llega al fallo: no tiene
# aún el control técnico para hacerlo con seguridad.
MIN_RIR = {"principiante": 2, "intermedio": 1, "avanzado": 0}

# Frecuencia mínima semanal por grupo mayor cuando hay 3 o más días.
MIN_FREQUENCY_MAJOR = 2

# Segundos por repetición para estimar la duración de la sesión.
SECONDS_PER_REP = 4
WARMUP_SECONDS = 600

# Duración razonable de un isométrico (plancha, estiramiento mantenido).
MIN_HOLD_SECONDS = 10
MAX_HOLD_SECONDS = 120


def weekly_sets(routine: Routine, catalog: Catalog) -> dict[str, int]:
    """Series semanales por grupo muscular.

    Las series de un compuesto cuentan completas para el grupo objetivo y a
    la mitad para los sinergistas: un press de banca entrena tríceps, pero no
    tanto como una extensión de tríceps.
    """
    totals: dict[str, float] = {}
    for block in routine.all_blocks():
        exercise = catalog.get(block.exercise_id)
        if exercise is None:
            continue
        totals[exercise.muscle_group] = totals.get(exercise.muscle_group, 0) + block.sets
        if exercise.compound:
            for secondary in exercise.secondary_muscles:
                group = _SECONDARY_TO_GROUP.get(secondary)
                if group and group != exercise.muscle_group:
                    totals[group] = totals.get(group, 0) + block.sets * 0.5
    return {group: round(value) for group, value in totals.items()}


# El campo `secondary_muscles` del dataset usa un vocabulario distinto al de
# `target`; esta tabla lo normaliza a los grupos del validador.
_SECONDARY_TO_GROUP = {
    "shoulders": "hombros",
    "deltoids": "hombros",
    "rear deltoids": "hombros",
    "rotator cuff": "hombros",
    "chest": "pecho",
    "triceps": "triceps",
    "biceps": "biceps",
    "brachialis": "biceps",
    "forearms": "antebrazos",
    "quadriceps": "cuadriceps",
    "hamstrings": "isquios",
    "glutes": "gluteos",
    "calves": "gemelos",
    "core": "core",
    "obliques": "core",
    "abdominals": "core",
    "hip flexors": "core",
    "lower back": "espalda_alta",
    "upper back": "espalda_alta",
    "back": "espalda_alta",
    "lats": "dorsales",
    "latissimus dorsi": "dorsales",
    "rhomboids": "espalda_alta",
    "trapezius": "espalda_alta",
    "traps": "espalda_alta",
}


def weekly_frequency(routine: Routine, catalog: Catalog) -> dict[str, int]:
    """Número de días por semana en que se entrena cada grupo directamente."""
    seen: dict[str, set[int]] = {}
    for index, day in enumerate(routine.days):
        for block in day.blocks:
            exercise = catalog.get(block.exercise_id)
            if exercise is None:
                continue
            seen.setdefault(exercise.muscle_group, set()).add(index)
    return {group: len(days) for group, days in seen.items()}


def estimate_minutes(day_blocks: list[Block], catalog: Catalog) -> int:
    """Duración estimada de una sesión, calentamiento incluido."""
    seconds = WARMUP_SECONDS
    for block in day_blocks:
        # Un isométrico dura lo que dice; una serie de repeticiones, lo que
        # tarden esas repeticiones.
        hold = block.seconds()
        if hold is not None:
            work = hold
        else:
            work = min(block.max_reps() or 10, 30) * SECONDS_PER_REP
        seconds += block.sets * (work + block.rest_seconds)
    return round(seconds / 60)


def validate(routine: Routine, profile: Profile, catalog: Catalog) -> list[Issue]:
    """Comprueba la rutina contra el perfil. Lista vacía = rutina aceptable."""
    issues: list[Issue] = []
    available = set(profile.equipment)
    blocked = set(profile.injuries)
    rep_ranges = REP_RANGES[profile.goal]
    min_rir = MIN_RIR[profile.experience]

    # --- Estructura -------------------------------------------------------
    if len(routine.days) != profile.days_per_week:
        issues.append(
            Issue(
                severity="error",
                code="DIAS_INCORRECTOS",
                message=(
                    f"La rutina tiene {len(routine.days)} días y se pidieron "
                    f"{profile.days_per_week}."
                ),
            )
        )

    for day in routine.days:
        if not day.blocks:
            issues.append(
                Issue(
                    severity="error",
                    code="DIA_VACIO",
                    message=f"El día «{day.name}» no tiene ningún ejercicio.",
                )
            )

    # --- Por ejercicio ----------------------------------------------------
    for day in routine.days:
        for block in day.blocks:
            exercise = catalog.get(block.exercise_id)
            if exercise is None:
                issues.append(
                    Issue(
                        severity="error",
                        code="EJERCICIO_DESCONOCIDO",
                        message=(
                            f"«{day.name}»: el id {block.exercise_id} no existe en "
                            "el catálogo."
                        ),
                    )
                )
                continue

            if exercise.equipment not in available:
                issues.append(
                    Issue(
                        severity="error",
                        code="MATERIAL_NO_DISPONIBLE",
                        message=(
                            f"«{exercise.name}» requiere {exercise.equipment_es}, que "
                            "no está entre el material disponible."
                        ),
                    )
                )

            conflicting = blocked.intersection(exercise.joints)
            if conflicting:
                issues.append(
                    Issue(
                        severity="error",
                        code="LESION",
                        message=(
                            f"«{exercise.name}» carga {', '.join(sorted(conflicting))}, "
                            "articulación marcada como lesionada."
                        ),
                    )
                )

            if block.is_timed():
                # Isométrico: se comprueba la duración, no el rango de reps.
                seconds = block.seconds()
                if seconds is not None and not (
                    MIN_HOLD_SECONDS <= seconds <= MAX_HOLD_SECONDS
                ):
                    issues.append(
                        Issue(
                            severity="aviso",
                            code="DURACION_ISOMETRICA",
                            message=(
                                f"«{exercise.name}» se mantiene {block.reps}; lo útil "
                                f"está entre {MIN_HOLD_SECONDS} y {MAX_HOLD_SECONDS} s."
                            ),
                        )
                    )
            else:
                low, high = rep_ranges[block.role]
                block_min, block_max = block.min_reps(), block.max_reps()
                if block_min is not None and (
                    block_min < low or (block_max or block_min) > high
                ):
                    issues.append(
                        Issue(
                            severity="aviso",
                            code="REPS_FUERA_RANGO",
                            message=(
                                f"«{exercise.name}» prescribe {block.reps} repeticiones "
                                f"como {block.role}; para objetivo {profile.goal} el "
                                f"rango es {low}-{high}."
                            ),
                        )
                    )

            if block.rir < min_rir:
                issues.append(
                    Issue(
                        severity="error",
                        code="RIR_BAJO",
                        message=(
                            f"«{exercise.name}» pide RIR {block.rir}; el mínimo para "
                            f"nivel {profile.experience} es {min_rir} para no "
                            "comprometer la técnica."
                        ),
                    )
                )

            if block.rest_seconds < MIN_REST[block.role]:
                issues.append(
                    Issue(
                        severity="aviso",
                        code="DESCANSO_CORTO",
                        message=(
                            f"«{exercise.name}» descansa {block.rest_seconds} s siendo "
                            f"{block.role}; mínimo recomendado {MIN_REST[block.role]} s."
                        ),
                    )
                )

    # --- Volumen y frecuencia --------------------------------------------
    targets = VOLUME_TARGETS[profile.experience]
    totals = weekly_sets(routine, catalog)
    # Un grupo sin ningún ejercicio disponible (por lesión o falta de
    # material) no puede entrenarse: avisar de que le falta volumen sería
    # ruido, no información.
    trainable = {exercise.muscle_group for exercise in catalog.candidates(profile)}
    for group, (low, high) in targets.items():
        total = totals.get(group, 0)
        if total > high:
            issues.append(
                Issue(
                    severity="error",
                    code="VOLUMEN_ALTO",
                    message=(
                        f"{group}: {total} series semanales, por encima del máximo "
                        f"({high}). Exceso de volumen = riesgo de sobreuso."
                    ),
                )
            )
        elif total < low and group in trainable:
            issues.append(
                Issue(
                    severity="aviso",
                    code="VOLUMEN_BAJO",
                    message=(
                        f"{group}: {total} series semanales, por debajo del mínimo "
                        f"efectivo ({low})."
                    ),
                )
            )

    if profile.days_per_week >= 3:
        frequency = weekly_frequency(routine, catalog)
        for group in _MAJOR:
            if targets[group][0] > 0 and 0 < frequency.get(group, 0) < MIN_FREQUENCY_MAJOR:
                issues.append(
                    Issue(
                        severity="aviso",
                        code="FRECUENCIA_BAJA",
                        message=(
                            f"{group} se entrena {frequency.get(group, 0)} día(s) por "
                            f"semana; con {profile.days_per_week} días conviene "
                            f"repartirlo en {MIN_FREQUENCY_MAJOR}."
                        ),
                    )
                )

    # --- Duración y básicos ----------------------------------------------
    limit = profile.session_minutes * 1.15
    for day in routine.days:
        minutes = estimate_minutes(day.blocks, catalog)
        if minutes > limit:
            issues.append(
                Issue(
                    severity="aviso",
                    code="DURACION_EXCEDIDA",
                    message=(
                        f"«{day.name}» dura ~{minutes} min estimados frente a los "
                        f"{profile.session_minutes} min disponibles."
                    ),
                )
            )

    if profile.goal in ("fuerza", "fuerza_hipertrofia"):
        for day in routine.days:
            has_compound = any(
                (exercise := catalog.get(block.exercise_id)) is not None
                and exercise.compound
                and block.role in ("principal", "secundario")
                for block in day.blocks
            )
            if day.blocks and not has_compound:
                issues.append(
                    Issue(
                        severity="aviso",
                        code="SIN_BASICO",
                        message=(
                            f"«{day.name}» no incluye ningún ejercicio compuesto como "
                            "principal o secundario; la ganancia de fuerza se apoya "
                            "en ellos."
                        ),
                    )
                )

    return issues


def blocking_issues(issues: list[Issue]) -> list[Issue]:
    return [issue for issue in issues if issue.severity == "error"]


def describe_targets(profile: Profile) -> str:
    """Resumen legible de los objetivos numéricos, para el prompt."""
    targets = VOLUME_TARGETS[profile.experience]
    ranges = REP_RANGES[profile.goal]
    volume = ", ".join(f"{group} {low}-{high}" for group, (low, high) in targets.items())
    reps = ", ".join(f"{role} {low}-{high}" for role, (low, high) in ranges.items())
    rest = ", ".join(f"{role} ≥{seconds}s" for role, seconds in MIN_REST.items())
    return (
        f"Series semanales por grupo: {volume}.\n"
        f"Repeticiones por rol (objetivo {profile.goal}): {reps}.\n"
        f"Descanso mínimo: {rest}.\n"
        f"RIR mínimo para nivel {profile.experience}: {MIN_RIR[profile.experience]}."
    )


def exercise_summary(exercise: Exercise) -> str:
    """Línea compacta de un ejercicio para el pool de candidatos del prompt."""
    tags = []
    if exercise.primary_lift:
        tags.append("BÁSICO")
    elif exercise.compound:
        tags.append("compuesto")
    if exercise.joints:
        tags.append("carga:" + "/".join(exercise.joints))
    suffix = f" [{'; '.join(tags)}]" if tags else ""
    return (
        f"{exercise.id} | {exercise.name} | {exercise.pattern} | "
        f"{exercise.muscle_group} | {exercise.equipment}{suffix}"
    )
