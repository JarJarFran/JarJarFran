"""Carga y filtrado del catálogo de ejercicios.

El filtrado por lesión es determinista y se aplica *antes* de que el modelo
vea nada: un ejercicio contraindicado no llega al pool de candidatos, así que
la IA no puede prescribirlo aunque quisiera. Esa es la garantía dura de
seguridad; el prompt es solo la capa blanda encima.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .config import CATALOG_PATH, MEDIA_DIR
from .models import Profile

# Patrones que exigen material pesado: si el usuario no lo tiene, el
# planificador debe buscar alternativas de peso corporal.
BODYWEIGHT_EQUIPMENT = {"body weight", "assisted", "band", "resistance band"}


@dataclass(frozen=True)
class Exercise:
    id: str
    name: str
    body_part: str
    body_part_es: str
    target: str
    target_es: str
    muscle_group: str
    secondary_muscles: tuple[str, ...]
    equipment: str
    equipment_es: str
    pattern: str
    pattern_confident: bool
    compound: bool
    primary_lift: bool
    joints: tuple[str, ...]
    gif_url: str
    image_url: str
    attribution: str
    steps_es: tuple[str, ...]
    steps_en: tuple[str, ...]

    @property
    def media_name(self) -> str:
        """Nombre del fichero GIF, para localizarlo en la copia local."""
        return self.gif_url.rsplit("/", 1)[-1]

    @property
    def local_gif(self) -> Path | None:
        path = MEDIA_DIR / self.media_name
        return path if path.is_file() else None

    def gif_src(self) -> str:
        """URL a usar en la web: la copia local si existe, si no la remota."""
        return f"/media/{self.media_name}" if self.local_gif else self.gif_url

    @classmethod
    def from_dict(cls, raw: dict) -> "Exercise":
        return cls(
            id=raw["id"],
            name=raw["name"],
            body_part=raw["body_part"],
            body_part_es=raw["body_part_es"],
            target=raw["target"],
            target_es=raw["target_es"],
            muscle_group=raw["muscle_group"],
            secondary_muscles=tuple(raw["secondary_muscles"]),
            equipment=raw["equipment"],
            equipment_es=raw["equipment_es"],
            pattern=raw["pattern"],
            pattern_confident=raw["pattern_confident"],
            compound=raw["compound"],
            primary_lift=raw["primary_lift"],
            joints=tuple(raw["joints"]),
            gif_url=raw["gif_url"],
            image_url=raw["image_url"],
            attribution=raw["attribution"],
            steps_es=tuple(raw["steps_es"]),
            steps_en=tuple(raw["steps_en"]),
        )


class Catalog:
    """Índice en memoria sobre el catálogo de ejercicios."""

    def __init__(self, exercises: list[Exercise]):
        self.exercises = exercises
        self.by_id = {exercise.id: exercise for exercise in exercises}

    @classmethod
    def load(cls, path: Path | None = None) -> "Catalog":
        source = Path(path or CATALOG_PATH)
        if not source.exists():
            raise FileNotFoundError(
                f"No existe {source}. Genera el catálogo con "
                "`python scripts/build_catalog.py`."
            )
        raw = json.loads(source.read_text(encoding="utf-8"))
        return cls([Exercise.from_dict(item) for item in raw])

    def __len__(self) -> int:
        return len(self.exercises)

    def get(self, exercise_id: str) -> Exercise | None:
        return self.by_id.get(exercise_id)

    def equipment_options(self) -> list[tuple[str, str]]:
        """(clave, etiqueta en español) ordenado por número de ejercicios."""
        counts: dict[str, tuple[str, int]] = {}
        for exercise in self.exercises:
            label, count = counts.get(exercise.equipment, (exercise.equipment_es, 0))
            counts[exercise.equipment] = (label, count + 1)
        return [
            (key, label)
            for key, (label, _) in sorted(counts.items(), key=lambda kv: -kv[1][1])
        ]

    # ------------------------------------------------------------------
    # Filtrado
    # ------------------------------------------------------------------
    def candidates(self, profile: Profile, limit: int | None = None) -> list[Exercise]:
        """Ejercicios utilizables por este usuario, priorizados.

        Excluye por material no disponible y por articulación lesionada. El
        orden prioriza básicos con barra (el motor de la ganancia de fuerza)
        y luego reparte por patrón para que el modelo tenga variedad real en
        cada casillero de la sesión, no 80 curls y una sentadilla.
        """
        available = set(profile.equipment)
        blocked = set(profile.injuries)

        usable = [
            exercise
            for exercise in self.exercises
            if exercise.equipment in available
            and not blocked.intersection(exercise.joints)
            and exercise.pattern != "cardio"
            and exercise.muscle_group != "cardio"
        ]

        if limit is None:
            return usable

        # Reparto round-robin por patrón para no sesgar el pool.
        by_pattern: dict[str, list[Exercise]] = {}
        for exercise in usable:
            by_pattern.setdefault(exercise.pattern, []).append(exercise)
        for group in by_pattern.values():
            group.sort(key=lambda e: (not e.primary_lift, not e.compound, e.name))

        selected: list[Exercise] = []
        index = 0
        while len(selected) < limit:
            added = False
            for pattern in sorted(by_pattern):
                group = by_pattern[pattern]
                if index < len(group):
                    selected.append(group[index])
                    added = True
                    if len(selected) >= limit:
                        break
            if not added:
                break
            index += 1
        return selected

    def excluded_by_injury(self, profile: Profile) -> list[Exercise]:
        """Ejercicios descartados solo por la lesión (para poder explicarlo)."""
        blocked = set(profile.injuries)
        if not blocked:
            return []
        available = set(profile.equipment)
        return [
            exercise
            for exercise in self.exercises
            if exercise.equipment in available and blocked.intersection(exercise.joints)
        ]


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    """Catálogo compartido por proceso (2,4 MB, se carga una sola vez)."""
    return Catalog.load()
