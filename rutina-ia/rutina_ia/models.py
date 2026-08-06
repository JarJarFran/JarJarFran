"""Modelos de dominio: perfil del usuario y rutina generada."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Goal = Literal["fuerza", "fuerza_hipertrofia", "hipertrofia"]
Experience = Literal["principiante", "intermedio", "avanzado"]

# Articulaciones que el usuario puede marcar como lesionadas o sensibles.
JOINTS = ("hombro", "lumbar", "rodilla", "codo", "muneca", "cadera", "cuello")
Joint = Literal["hombro", "lumbar", "rodilla", "codo", "muneca", "cadera", "cuello"]


class Profile(BaseModel):
    """Lo que el usuario declara sobre sí mismo y sus condicionantes."""

    goal: Goal = "fuerza"
    experience: Experience = "principiante"
    days_per_week: int = Field(3, ge=1, le=6)
    session_minutes: int = Field(60, ge=20, le=150)
    equipment: list[str] = Field(default_factory=lambda: ["body weight"])
    injuries: list[Joint] = Field(default_factory=list)
    age: int | None = Field(None, ge=12, le=100)
    bodyweight_kg: float | None = Field(None, ge=25, le=250)
    notes: str = ""

    @field_validator("equipment")
    @classmethod
    def _non_empty_equipment(cls, value: list[str]) -> list[str]:
        return value or ["body weight"]


class Block(BaseModel):
    """Un ejercicio dentro de un día, con su prescripción."""

    exercise_id: str
    sets: int = Field(ge=1, le=10)
    reps: str  # "5", "6-8", "30 s" — texto porque hay isométricos y tiempos
    rir: int = Field(ge=0, le=5, description="Repeticiones en recámara")
    rest_seconds: int = Field(ge=20, le=600)
    role: Literal["principal", "secundario", "accesorio", "core", "movilidad"] = "accesorio"
    notes: str = ""

    def is_timed(self) -> bool:
        """¿La prescripción es una duración y no un número de repeticiones?

        Planchas y estiramientos se prescriben en segundos («30 s»). Compararlos
        contra un rango de repeticiones no significa nada: 30 segundos de
        plancha no son 30 repeticiones de nada.
        """
        lowered = self.reps.lower()
        return any(unit in lowered for unit in ("s", "seg", "min", "'", '"'))

    def _numbers(self) -> list[int]:
        return [int(part) for part in "".join(
            c if c.isdigit() else " " for c in self.reps
        ).split()]

    def min_reps(self) -> int | None:
        """Extremo inferior del rango de repeticiones, si es numérico."""
        numbers = self._numbers()
        return numbers[0] if numbers else None

    def max_reps(self) -> int | None:
        numbers = self._numbers()
        return numbers[-1] if numbers else None

    def seconds(self) -> int | None:
        """Duración en segundos de un bloque isométrico."""
        if not self.is_timed():
            return None
        numbers = self._numbers()
        if not numbers:
            return None
        value = numbers[-1]
        return value * 60 if "min" in self.reps.lower() else value


class Day(BaseModel):
    name: str
    focus: str = ""
    blocks: list[Block]


class Routine(BaseModel):
    """Rutina completa devuelta por el generador."""

    title: str
    summary: str
    goal: Goal
    weeks: int = Field(4, ge=1, le=16)
    progression: str
    deload: str = ""
    safety_notes: list[str] = Field(default_factory=list)
    days: list[Day]

    def all_blocks(self) -> list[Block]:
        return [block for day in self.days for block in day.blocks]


class Issue(BaseModel):
    """Un incumplimiento detectado por el validador determinista."""

    severity: Literal["error", "aviso"]
    code: str
    message: str


# Cómo se generó la rutina:
#   api          — API de Anthropic con clave propia, facturada por uso
#   suscripcion  — CLI de Claude Code, con la sesión que ya tenga el usuario
#   determinista — plantillas locales, sin modelo
Engine = Literal["api", "suscripcion", "determinista"]


class RoutineResult(BaseModel):
    """Rutina + trazabilidad de cómo se produjo."""

    routine: Routine
    issues: list[Issue] = Field(default_factory=list)
    engine: Engine = "api"
    repair_attempts: int = 0
