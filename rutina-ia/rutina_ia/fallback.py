"""Planificador determinista, sin IA.

Cumple dos funciones: que la aplicación siga siendo utilizable sin clave de
API, y que la suite de tests pueda ejercitar el validador y el exportador sin
llamar a la red. Construye la rutina a partir de plantillas de sesión por
patrón de movimiento y rellena cada hueco con el mejor candidato disponible.
"""

from __future__ import annotations

from .catalog import Catalog, Exercise
from .models import Block, Day, Profile, Routine, RoutineResult
from .programming import (
    _SECONDARY_TO_GROUP,
    MIN_REST,
    REP_RANGES,
    VOLUME_TARGETS,
    validate,
    weekly_sets,
)

# Un hueco de sesión: (rol, patrones aceptables por orden de preferencia, series)
Slot = tuple[str, tuple[str, ...], int]

FULL_BODY: list[Slot] = [
    ("principal", ("sentadilla", "zancada"), 4),
    ("secundario", ("empuje_horizontal", "empuje_vertical"), 3),
    # Tracción vertical y horizontal en la misma sesión: son planos distintos
    # y dejar fuera una de las dos desequilibra la espalda.
    ("secundario", ("traccion_vertical", "traccion_horizontal"), 3),
    ("accesorio", ("bisagra", "isquios_aislado"), 3),
    ("accesorio", ("traccion_horizontal", "hombro_aislado"), 2),
    ("core", ("core",), 3),
]

UPPER: list[Slot] = [
    ("principal", ("empuje_horizontal",), 4),
    ("secundario", ("traccion_vertical", "traccion_horizontal"), 4),
    ("secundario", ("empuje_vertical",), 3),
    ("accesorio", ("traccion_horizontal",), 3),
    ("accesorio", ("flexion_codo",), 3),
    ("accesorio", ("extension_codo",), 3),
]

LOWER: list[Slot] = [
    ("principal", ("sentadilla",), 4),
    ("secundario", ("bisagra",), 4),
    ("accesorio", ("zancada", "cuadriceps_aislado"), 3),
    ("accesorio", ("isquios_aislado", "bisagra"), 3),
    ("accesorio", ("gemelo",), 3),
    ("core", ("core",), 3),
]

PUSH: list[Slot] = [
    ("principal", ("empuje_horizontal",), 4),
    ("secundario", ("empuje_vertical",), 3),
    ("accesorio", ("empuje_horizontal",), 3),
    ("accesorio", ("hombro_aislado",), 3),
    ("accesorio", ("extension_codo",), 3),
]

PULL: list[Slot] = [
    ("principal", ("traccion_vertical",), 4),
    ("secundario", ("traccion_horizontal",), 4),
    ("accesorio", ("traccion_horizontal",), 3),
    ("accesorio", ("flexion_codo",), 3),
    ("core", ("core",), 3),
]

# Reparto de sesiones según los días disponibles. Con pocos días el cuerpo
# entero rinde más; a partir de cuatro conviene dividir para poder subir el
# volumen por sesión sin alargarla.
SPLITS: dict[int, list[tuple[str, list[Slot]]]] = {
    1: [("Día 1 — Cuerpo completo", FULL_BODY)],
    2: [
        ("Día 1 — Cuerpo completo A", FULL_BODY),
        ("Día 2 — Cuerpo completo B", FULL_BODY),
    ],
    3: [
        ("Día 1 — Cuerpo completo A", FULL_BODY),
        ("Día 2 — Cuerpo completo B", FULL_BODY),
        ("Día 3 — Cuerpo completo C", FULL_BODY),
    ],
    4: [
        ("Día 1 — Tren superior A", UPPER),
        ("Día 2 — Tren inferior A", LOWER),
        ("Día 3 — Tren superior B", UPPER),
        ("Día 4 — Tren inferior B", LOWER),
    ],
    5: [
        ("Día 1 — Tren superior", UPPER),
        ("Día 2 — Tren inferior", LOWER),
        ("Día 3 — Empuje", PUSH),
        ("Día 4 — Tracción", PULL),
        ("Día 5 — Tren inferior", LOWER),
    ],
    6: [
        ("Día 1 — Empuje A", PUSH),
        ("Día 2 — Tracción A", PULL),
        ("Día 3 — Pierna A", LOWER),
        ("Día 4 — Empuje B", PUSH),
        ("Día 5 — Tracción B", PULL),
        ("Día 6 — Pierna B", LOWER),
    ],
}

LOWER_PATTERNS = (
    "sentadilla",
    "zancada",
    "bisagra",
    "cuadriceps_aislado",
    "isquios_aislado",
    "gemelo",
)
UPPER_PATTERNS = (
    "empuje_horizontal",
    "empuje_vertical",
    "traccion_horizontal",
    "traccion_vertical",
    "flexion_codo",
    "extension_codo",
    "hombro_aislado",
)

FOCUS = {
    "principal": "levantamiento principal",
    "secundario": "trabajo compuesto complementario",
    "accesorio": "accesorio",
    "core": "core",
    "movilidad": "movilidad",
}


def _reps_for(goal: str, role: str) -> str:
    low, high = REP_RANGES[goal][role]
    # Un rango estrecho dentro del permitido: deja margen de progresión sin
    # rozar los extremos del validador.
    if role == "principal":
        return f"{low + 1}-{min(low + 3, high)}"
    return f"{low + 1}-{min(low + 4, high)}"


def _rir_for(experience: str, role: str) -> int:
    base = {"principiante": 3, "intermedio": 2, "avanzado": 1}[experience]
    return base if role in ("principal", "secundario") else max(base - 1, 0)


def _rest_for(role: str, goal: str) -> int:
    base = MIN_REST[role]
    if role == "principal":
        return 240 if goal == "fuerza" else 180
    if role == "secundario":
        return 150 if goal == "fuerza" else 120
    return max(base, 90)


def _pick(
    pool: dict[str, list[Exercise]],
    patterns: tuple[str, ...],
    used: set[str],
    role: str,
) -> Exercise | None:
    """Primer candidato no usado del primer patrón que tenga alguno.

    El rol decide la preferencia: un principal quiere el básico más pesado
    disponible, mientras que un accesorio quiere justo lo contrario. Un peso
    muerto a 3×10 al final de la sesión no es un accesorio, es una forma de
    acumular fatiga lumbar sin ganancia de fuerza a cambio.
    """
    for pattern in patterns:
        options = pool.get(pattern, [])
        # En igualdad de condiciones se prefiere un ejercicio cuyo patrón se
        # dedujo del nombre: los clasificados por heurística de músculo
        # objetivo aciertan menos y producen elecciones raras.
        if role == "principal":
            options = sorted(
                options, key=lambda e: (not e.primary_lift, not e.pattern_confident, e.name)
            )
        elif role in ("accesorio", "core", "movilidad"):
            options = sorted(
                options, key=lambda e: (e.primary_lift, not e.pattern_confident, e.name)
            )
        for exercise in options:
            if exercise.id not in used:
                return exercise
    # Si todo está usado, se repite el mejor disponible antes que dejar el
    # hueco vacío: repetir un básico es preferible a una sesión coja.
    for pattern in patterns:
        if pool.get(pattern):
            return pool[pattern][0]
    return None


# Prioridad de recorte cuando sobra volumen: se quita primero de lo que menos
# aporta a la ganancia de fuerza.
_TRIM_ORDER = {"movilidad": 0, "core": 1, "accesorio": 2, "secundario": 3, "principal": 4}
_MIN_SETS = 2
_MAX_SETS = 5


def _removable(day: Day, block: Block) -> bool:
    """¿Se puede quitar este bloque sin descoser la sesión?

    Los accesorios salen sin más. Un secundario solo sale si el día conserva
    otro trabajo pesado: la sesión tiene que seguir teniendo un ejercicio que
    justifique llamarla entrenamiento de fuerza.
    """
    if block.role in ("accesorio", "core", "movilidad"):
        return True
    if block.role != "secundario":
        return False
    heavy = [
        other
        for other in day.blocks
        if other is not block and other.role in ("principal", "secundario")
    ]
    return bool(heavy)


def _balance_volume(days: list[Day], profile: Profile, catalog: Catalog) -> None:
    """Ajusta series in-place hasta encajar el volumen semanal en su rango.

    Las plantillas están pensadas para una frecuencia media; con 5 o 6 días la
    misma sesión se repite y el volumen se dispara. En vez de mantener una
    plantilla distinta por combinación, se recorta (o se rellena) aquí, que es
    donde ya se conoce el reparto real.
    """
    targets = VOLUME_TARGETS[profile.experience]
    if not any(day.blocks for day in days):
        return

    def group_of(block: Block) -> str | None:
        exercise = catalog.get(block.exercise_id)
        return exercise.muscle_group if exercise else None

    def contributes(block: Block, group: str) -> int | None:
        """0 si el bloque carga el grupo directamente, 1 si de forma indirecta.

        El exceso de volumen a menudo viene del trabajo indirecto (los presses
        acumulan hombro, las tracciones acumulan bíceps), así que el recorte
        tiene que poder actuar también ahí; si no, se queda sin palancas.
        """
        exercise = catalog.get(block.exercise_id)
        if exercise is None:
            return None
        if exercise.muscle_group == group:
            return 0
        if exercise.compound and any(
            _SECONDARY_TO_GROUP.get(muscle) == group
            for muscle in exercise.secondary_muscles
        ):
            return 1
        return None

    def all_blocks() -> list[Block]:
        return [block for day in days for block in day.blocks]

    routine = Routine(
        title="", summary="", goal=profile.goal, progression="", days=days
    )

    # --- Recorte: primero series, luego ejercicios enteros ----------------
    for _ in range(300):
        totals = weekly_sets(routine, catalog)
        over = [
            (group, totals[group] - high)
            for group, (_, high) in targets.items()
            if totals.get(group, 0) > high
        ]
        if not over:
            break
        group = max(over, key=lambda item: item[1])[0]

        trimmable = [
            (directness, block)
            for block in all_blocks()
            if (directness := contributes(block, group)) is not None
            and block.sets > _MIN_SETS
        ]
        if trimmable:
            trimmable.sort(key=lambda item: (item[0], _TRIM_ORDER[item[1].role], -item[1].sets))
            trimmable[0][1].sets -= 1
            continue

        # Todo está ya en el mínimo de series: sobra un ejercicio. Se elimina
        # el accesorio menos relevante, nunca un principal ni un secundario,
        # y solo si el día no se queda demasiado corto.
        removable = [
            (contributes(block, group), day, block)
            for day in days
            for block in day.blocks
            if contributes(block, group) is not None
            and _removable(day, block)
            and len(day.blocks) > 2
        ]
        if not removable:
            break
        removable.sort(key=lambda item: (item[0], _TRIM_ORDER[item[2].role], item[2].sets))
        _, day, block = removable[0]
        day.blocks.remove(block)

    # --- Relleno: subir series de los grupos por debajo del mínimo --------
    for _ in range(300):
        totals = weekly_sets(routine, catalog)
        under = [
            (group, low - totals.get(group, 0))
            for group, (low, _) in targets.items()
            if low > 0 and 0 < totals.get(group, 0) < low
        ]
        if not under:
            break
        group = max(under, key=lambda item: item[1])[0]
        growable = [
            block
            for block in all_blocks()
            if group_of(block) == group and block.sets < _MAX_SETS
        ]
        if not growable:
            break
        growable.sort(key=lambda b: (-_TRIM_ORDER[b.role], b.sets))

        # Subir series aquí puede desbordar otro grupo por la vía indirecta
        # (un press que sube por pecho también sube hombros y tríceps). Solo
        # se acepta el incremento si no rompe ningún techo.
        applied = False
        for block in growable:
            block.sets += 1
            after = weekly_sets(routine, catalog)
            if any(after.get(g, 0) > high for g, (_, high) in targets.items()):
                block.sets -= 1
                continue
            applied = True
            break
        if not applied:
            break


class NoViablePlan(RuntimeError):
    """Las restricciones no dejan ejercicios suficientes para armar la rutina."""


def _choose_template(
    profile: Profile, pool: dict[str, list[Exercise]]
) -> list[tuple[str, list[Slot]]]:
    """Reparto de sesiones compatible con los ejercicios que quedan.

    Una división superior/inferior no tiene sentido si una lesión ha vaciado
    todos los patrones de tren inferior: produciría días sin un solo
    ejercicio. En ese caso se repite la sesión que sí es viable.
    """
    days = min(max(profile.days_per_week, 1), 6)
    has_lower = any(pool.get(pattern) for pattern in LOWER_PATTERNS)
    has_upper = any(pool.get(pattern) for pattern in UPPER_PATTERNS)

    if not has_lower and not has_upper:
        raise NoViablePlan(
            "Con ese material y esas lesiones no quedan ejercicios suficientes "
            "para construir una rutina. Añade material o revisa las "
            "articulaciones marcadas."
        )
    if not has_lower:
        return [(f"Día {i + 1} — Tren superior", UPPER) for i in range(days)]
    if not has_upper:
        return [(f"Día {i + 1} — Tren inferior", LOWER) for i in range(days)]
    return SPLITS[days]


def plan_routine(profile: Profile, catalog: Catalog) -> RoutineResult:
    candidates = catalog.candidates(profile)
    pool: dict[str, list[Exercise]] = {}
    for exercise in candidates:
        pool.setdefault(exercise.pattern, []).append(exercise)
    for group in pool.values():
        group.sort(key=lambda e: (not e.primary_lift, not e.compound, e.name))

    template = _choose_template(profile, pool)
    used: set[str] = set()
    days: list[Day] = []

    for day_name, slots in template:
        blocks: list[Block] = []
        for role, patterns, sets in slots:
            exercise = _pick(pool, patterns, used, role)
            if exercise is None:
                continue
            used.add(exercise.id)
            blocks.append(
                Block(
                    exercise_id=exercise.id,
                    sets=sets,
                    reps=_reps_for(profile.goal, role),
                    rir=_rir_for(profile.experience, role),
                    rest_seconds=_rest_for(role, profile.goal),
                    role=role,
                    notes="",
                )
            )
        days.append(
            Day(
                name=day_name,
                focus=", ".join(sorted({FOCUS[block.role] for block in blocks})),
                blocks=blocks,
            )
        )

    _balance_volume(days, profile, catalog)

    routine = Routine(
        title=f"Rutina de {profile.goal.replace('_', ' + ')} · {profile.days_per_week} días",
        summary=(
            "Rutina generada con el planificador determinista (sin IA). Sigue una "
            "plantilla estándar de fuerza: compuesto pesado al inicio de cada "
            "sesión y accesorios después, con el volumen semanal dentro del rango "
            f"recomendado para nivel {profile.experience}."
        ),
        goal=profile.goal,
        weeks=4,
        progression=(
            "Semana a semana, sube el peso del levantamiento principal cuando "
            "completes todas las series en el extremo alto del rango de "
            "repeticiones manteniendo el RIR indicado. Incrementos de 2,5 kg en "
            "tren superior y 5 kg en tren inferior. Si fallas el rango dos "
            "sesiones seguidas, mantén el peso."
        ),
        deload=(
            "En la semana 5, reduce las series a la mitad manteniendo el peso. "
            "Sirve para disipar fatiga acumulada antes del siguiente bloque."
        ),
        safety_notes=_safety_notes(profile),
        days=days,
    )

    return RoutineResult(
        routine=routine,
        issues=validate(routine, profile, catalog),
        engine="determinista",
    )


def _safety_notes(profile: Profile) -> list[str]:
    notes = [
        "Calienta 8-10 minutos antes de cada sesión y haz 2 series de "
        "aproximación progresiva antes de la primera serie efectiva del "
        "levantamiento principal.",
        "Detén la serie si la técnica se rompe, aunque queden repeticiones. "
        "El fallo técnico llega antes que el muscular y es la vía habitual de "
        "lesión.",
    ]
    if profile.injuries:
        notes.append(
            "Se han excluido del catálogo los ejercicios que cargan: "
            f"{', '.join(profile.injuries)}. Si aparece dolor articular durante "
            "un ejercicio permitido, interrúmpelo y consulta con un "
            "fisioterapeuta antes de retomarlo."
        )
    if profile.experience == "principiante":
        notes.append(
            "Durante las primeras semanas prioriza aprender el patrón sobre "
            "añadir peso. La progresión de carga viene después de la técnica."
        )
    return notes
