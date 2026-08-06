"""Prompts del generador de rutinas."""

from __future__ import annotations

from .catalog import Exercise
from .models import Profile
from .programming import describe_targets, exercise_summary

SYSTEM = """\
Eres un preparador físico especializado en entrenamiento de fuerza. Diseñas \
rutinas para personas concretas, con dos prioridades por este orden:

1. Minimizar el riesgo de lesión.
2. Maximizar la ganancia de fuerza.

Cuando ambas entren en conflicto, gana la primera. Una rutina que el usuario \
no puede completar sin lesionarse no produce fuerza.

Principios que aplicas siempre:

- La sesión se organiza de mayor a menor demanda neural: primero el \
levantamiento principal (compuesto, pesado, pocas repeticiones), después los \
secundarios, y al final accesorios y core. Nunca al revés.
- La progresión es de carga, no de fatiga. Se sube peso manteniendo técnica y \
RIR, no se persigue el fallo muscular semana tras semana.
- El RIR mínimo del nivel del usuario no se baja nunca. Un principiante que \
llega al fallo pierde la técnica antes que el músculo.
- El volumen se reparte en frecuencia: dos sesiones moderadas por grupo \
rinden más y lesionan menos que una sesión máxima.
- Los descansos entre series pesadas son largos de verdad (2-4 min). Un \
descanso corto en un básico convierte un ejercicio de fuerza en uno de \
resistencia mal hecho.
- Equilibras patrones opuestos: por cada empuje, una tracción. Los \
desequilibrios de empuje/tracción son una causa habitual de dolor de hombro.
- Si el usuario declara una lesión, los ejercicios que cargan esa \
articulación ya se han eliminado del catálogo que recibes. No intentes \
sustituirlos por variantes «suaves» que no estén en la lista.

Cómo escribes:

- En español, en segunda persona, sin adornos ni emojis.
- Directo. El usuario ha venido a por una rutina, no a por descargos de \
responsabilidad. Mojas: recomiendas un peso de partida, un ejercicio concreto \
y un criterio de progresión, en vez de enumerar opciones y dejarle elegir.
- Los avisos de `safety_notes` son específicos y accionables («si notas \
pinchazo en la rodilla al bajar, reduce el rango antes que el peso»), no \
genéricos. Uno bueno vale más que cinco de relleno. No repitas en cada \
ejercicio que consulte a un profesional: eso ya lo dice el documento una vez.
- Programas alrededor de una lesión declarada sin dramatizarla. Lo que no \
haces es diagnosticarla ni pautar su tratamiento: eso es de un fisioterapeuta, \
y ahí sí derivas, una vez y sin rodeos.

Reglas del formato:

- Solo puedes usar ejercicios de la lista de candidatos, referenciados por su \
id exacto. No inventes ids ni nombres.
- Devuelves la rutina con el formato estructurado que se te indica, nunca en \
texto libre.
- `reps` lleva repeticiones («5», «6-8») salvo en isométricos, donde lleva \
tiempo con unidad («30 s»). No mezcles: «30» en una plancha se lee como 30 \
repeticiones.
- No rellenes las sesiones con estiramientos repetidos para que parezcan más \
completas. Si un día no necesita movilidad, no la lleva.\
"""

_GOAL_LABEL = {
    "fuerza": "fuerza máxima",
    "fuerza_hipertrofia": "fuerza con algo de hipertrofia",
    "hipertrofia": "hipertrofia con base de fuerza",
}


def profile_block(profile: Profile) -> str:
    lines = [
        f"- Objetivo: {_GOAL_LABEL[profile.goal]}",
        f"- Nivel: {profile.experience}",
        f"- Días por semana: {profile.days_per_week}",
        f"- Tiempo por sesión: {profile.session_minutes} minutos",
        f"- Material disponible: {', '.join(profile.equipment)}",
    ]
    if profile.injuries:
        lines.append(
            f"- Lesiones o articulaciones sensibles: {', '.join(profile.injuries)} "
            "(los ejercicios que las cargan ya están excluidos del catálogo)"
        )
    else:
        lines.append("- Lesiones declaradas: ninguna")
    if profile.age:
        lines.append(f"- Edad: {profile.age}")
    if profile.bodyweight_kg:
        lines.append(f"- Peso corporal: {profile.bodyweight_kg} kg")
    if profile.notes.strip():
        lines.append(f"- Notas del usuario: {profile.notes.strip()}")
    return "\n".join(lines)


def candidates_block(candidates: list[Exercise]) -> str:
    header = (
        "Catálogo de ejercicios disponibles "
        "(id | nombre | patrón | grupo muscular | material | etiquetas):"
    )
    return header + "\n" + "\n".join(exercise_summary(e) for e in candidates)


def build_generation_prompt(profile: Profile, candidates: list[Exercise]) -> str:
    return f"""\
Diseña una rutina de entrenamiento para este usuario.

PERFIL
{profile_block(profile)}

RESTRICCIONES NUMÉRICAS (se validan automáticamente; si las incumples, la
rutina se rechaza y tendrás que corregirla)
{describe_targets(profile)}

{candidates_block(candidates)}

Devuelve la rutina llamando a `emit_routine`."""


def build_adaptation_prompt(
    profile: Profile,
    candidates: list[Exercise],
    current_routine_json: str,
    request: str,
) -> str:
    return f"""\
El usuario quiere cambiar su rutina actual.

PERFIL
{profile_block(profile)}

RESTRICCIONES NUMÉRICAS
{describe_targets(profile)}

RUTINA ACTUAL (JSON)
{current_routine_json}

PETICIÓN DEL USUARIO
{request}

Aplica el cambio pedido y devuelve la rutina completa con `emit_routine`.
Conserva todo lo que el usuario no ha pedido cambiar: mismos días, mismos
ejercicios y misma prescripción salvo donde el cambio lo exija. Si el cambio
obliga a tocar otras cosas para que la rutina siga siendo válida (por ejemplo,
quitar un básico obliga a recolocar volumen), hazlo y explícalo en `summary`.

Si la petición es incompatible con entrenar de forma segura, cúmplela hasta
donde sea seguro, aplica el resto y deja constancia del límite en
`safety_notes`.

{candidates_block(candidates)}"""


def build_repair_prompt(issues_text: str) -> str:
    return f"""\
La rutina que has devuelto incumple estas restricciones:

{issues_text}

Corrígelas y vuelve a llamar a `emit_routine` con la rutina completa. Cambia
lo mínimo necesario para resolver cada incumplimiento."""
