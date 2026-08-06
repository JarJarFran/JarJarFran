"""Construye `data/catalog.json` a partir del dataset de ejercicios.

Fuente: https://github.com/hasaneyldrm/exercises-dataset

El dataset original pesa ~17 MB porque incluye instrucciones en 10 idiomas.
Aquí se recorta a español + inglés y se enriquece con la información que la
capa de programación necesita: patrón de movimiento, articulaciones expuestas
y si el ejercicio es compuesto o de aislamiento.

Los GIF y las imágenes NO se copian al repositorio: se referencian por URL a
la fuente original, conservando la atribución `© Gym visual` que exige la
licencia del material audiovisual (ver NOTICE del dataset original).

Uso:
    python scripts/build_catalog.py                      # descarga el JSON
    python scripts/build_catalog.py --source ruta.json   # usa un clon local
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

RAW_BASE = "https://raw.githubusercontent.com/hasaneyldrm/exercises-dataset/main"
SOURCE_URL = f"{RAW_BASE}/data/exercises.json"
ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "catalog.json"

# --------------------------------------------------------------------------
# Clasificación de patrones de movimiento
# --------------------------------------------------------------------------
# El orden importa: la primera regla que casa gana. Las reglas más específicas
# van primero (p. ej. "hack squat" antes que la regla genérica de "squat").

PATTERN_RULES: list[tuple[str, str]] = [
    # (patrón, expresión regular sobre el nombre en minúsculas)
    ("cardio", r"\b(run|bike|elliptical|stepmill|ski|rowing machine|jump rope|walk)\b"),
    ("movilidad", r"\b(stretch|mobility|foam roll|roller)\b"),
    ("bisagra", r"\b(deadlift|good morning|hyperextension|back extension|swing|romanian|rdl|pull through|hip thrust|glute bridge|bridge)\b"),
    ("zancada", r"\b(lunge|split squat|step-up|step up|bulgarian)\b"),
    ("sentadilla", r"\b(squat|leg press|hack|sissy)\b"),
    ("empuje_vertical", r"\b(overhead press|military|shoulder press|push press|jerk|handstand)\b"),
    ("empuje_horizontal", r"\b(bench press|chest press|push-up|push up|dip|fly|flye|pec deck|chest fly)\b"),
    ("traccion_vertical", r"\b(pull-up|pull up|chin-up|chin up|pulldown|lat pull|pullover|muscle up)\b"),
    ("traccion_horizontal", r"\b(row|rowing|face pull|inverted row|rear delt)\b"),
    ("gemelo", r"\b(calf|toe raise|soleus)\b"),
    ("core", r"\b(crunch|sit-up|sit up|plank|russian twist|leg raise|knee raise|hanging|ab |abs|rollout|rollerout|wood ?chop|dead bug|hollow)\b"),
    ("acarreo", r"\b(carry|farmer|walk with)\b"),
    ("flexion_codo", r"\b(curl)\b"),
    ("extension_codo", r"\b(triceps|tricep|pushdown|kickback|skull|extension.*(triceps|arm)|close-grip bench)\b"),
    ("hombro_aislado", r"\b(lateral raise|front raise|reverse fly|shrug|upright row|delt raise|raise)\b"),
    ("cuadriceps_aislado", r"\b(leg extension|knee extension)\b"),
    ("isquios_aislado", r"\b(leg curl|hamstring curl)\b"),
    ("antebrazo", r"\b(wrist|forearm|grip)\b"),
    ("cuello", r"\b(neck)\b"),
]

# Cuando ninguna regla de nombre casa, se infiere el patrón por el músculo
# objetivo. Cubre las variantes con nomenclatura poco estándar del dataset
# ("dumbbell incline hammer press", "cable rear drive", ...).
TARGET_FALLBACK: dict[str, str] = {
    "pectorals": "empuje_horizontal",
    "serratus anterior": "core",
    "triceps": "extension_codo",
    "biceps": "flexion_codo",
    "forearms": "antebrazo",
    "lats": "traccion_vertical",
    "upper back": "traccion_horizontal",
    "traps": "hombro_aislado",
    "glutes": "bisagra",
    "spine": "bisagra",
    "hamstrings": "isquios_aislado",
    "quads": "cuadriceps_aislado",
    "calves": "gemelo",
    "abs": "core",
    "adductors": "cadera_aislado",
    "abductors": "cadera_aislado",
    "cardiovascular system": "cardio",
    "levator scapulae": "cuello",
}

# Patrones considerados básicos/compuestos: son los que sostienen la ganancia
# de fuerza y por eso el programador los coloca al principio de la sesión.
COMPOUND_PATTERNS = {
    "sentadilla",
    "bisagra",
    "zancada",
    "empuje_horizontal",
    "empuje_vertical",
    "traccion_horizontal",
    "traccion_vertical",
    "acarreo",
}

# Ejercicios que sirven como "levantamiento principal" para fuerza: barra o
# peso corporal cargable, patrón compuesto y bilateral.
PRIMARY_EQUIPMENT = {"barbell", "olympic barbell", "trap bar", "ez barbell", "body weight", "weighted", "smith machine"}

# --------------------------------------------------------------------------
# Articulaciones expuestas -> se usa para filtrar por lesión declarada
# --------------------------------------------------------------------------

JOINT_RULES: dict[str, list[str]] = {
    "hombro": [
        r"\b(overhead|military|shoulder press|behind (the )?neck|upright row|dip|bench press|fly|flye|pec deck|lateral raise|front raise|snatch|jerk|clean|push press|handstand|pullover)\b",
    ],
    "lumbar": [
        r"\b(deadlift|good morning|bent[- ]over|bent over row|squat|hyperextension|back extension|clean|snatch|jerk|russian twist|sit-up|sit up|romanian|stiff leg|superman)\b",
    ],
    "rodilla": [
        r"\b(squat|lunge|leg press|leg extension|step-up|step up|jump|sissy|hack|split squat|pistol|box jump)\b",
    ],
    "codo": [
        r"\b(skull|triceps extension|tricep extension|dip|close-grip|pushdown|kickback|curl|preacher)\b",
    ],
    "muneca": [
        r"\b(wrist|front squat|clean|snatch|push-up|push up|handstand|reverse curl|planche|zottman)\b",
    ],
    "cadera": [
        r"\b(squat|deadlift|lunge|hip thrust|good morning|abduction|adduction|swing|bridge|split squat)\b",
    ],
    "cuello": [r"\b(neck|behind (the )?neck|shrug)\b"],
}

# Además de por nombre, ciertas partes del cuerpo implican la articulación.
BODY_PART_JOINTS: dict[str, list[str]] = {
    "shoulders": ["hombro"],
    "chest": ["hombro"],
    "back": ["lumbar"],
    "waist": ["lumbar"],
    "upper legs": ["rodilla", "cadera"],
    "lower legs": ["rodilla"],
    "upper arms": ["codo"],
    "lower arms": ["codo", "muneca"],
    "neck": ["cuello"],
}

# --------------------------------------------------------------------------
# Traducciones de metadatos (los nombres se dejan en inglés: son el estándar
# de gimnasio y así el usuario puede buscar el ejercicio en cualquier fuente)
# --------------------------------------------------------------------------

BODY_PART_ES = {
    "back": "espalda",
    "cardio": "cardio",
    "chest": "pecho",
    "lower arms": "antebrazos",
    "lower legs": "pantorrillas",
    "neck": "cuello",
    "shoulders": "hombros",
    "upper arms": "brazos",
    "upper legs": "piernas",
    "waist": "core",
}

TARGET_ES = {
    "abs": "abdominales",
    "abductors": "abductores",
    "adductors": "aductores",
    "biceps": "bíceps",
    "calves": "gemelos",
    "cardiovascular system": "sistema cardiovascular",
    "delts": "deltoides",
    "forearms": "antebrazos",
    "glutes": "glúteos",
    "hamstrings": "isquiotibiales",
    "lats": "dorsales",
    "levator scapulae": "elevador de la escápula",
    "pectorals": "pectorales",
    "quads": "cuádriceps",
    "serratus anterior": "serrato anterior",
    "spine": "erectores espinales",
    "traps": "trapecios",
    "triceps": "tríceps",
    "upper back": "espalda alta",
}

EQUIPMENT_ES = {
    "assisted": "asistido",
    "band": "banda elástica",
    "barbell": "barra",
    "body weight": "peso corporal",
    "bosu ball": "bosu",
    "cable": "polea",
    "dumbbell": "mancuernas",
    "elliptical machine": "elíptica",
    "ez barbell": "barra Z",
    "hammer": "martillo",
    "kettlebell": "kettlebell",
    "leverage machine": "máquina de palanca",
    "medicine ball": "balón medicinal",
    "olympic barbell": "barra olímpica",
    "resistance band": "banda de resistencia",
    "roller": "rodillo",
    "rope": "cuerda",
    "skierg machine": "skierg",
    "sled machine": "trineo",
    "smith machine": "multipower",
    "stability ball": "fitball",
    "stationary bike": "bicicleta estática",
    "stepmill machine": "escaladora",
    "tire": "neumático",
    "trap bar": "barra hexagonal",
    "upper body ergometer": "ergómetro de brazos",
    "weighted": "lastre",
    "wheel roller": "rueda abdominal",
}

# Grupos musculares canónicos usados por el validador de volumen semanal.
MUSCLE_GROUPS = {
    "pecho": {"pectorals", "serratus anterior"},
    # Dorsales y espalda alta se cuentan por separado: una sesión de tracción
    # normal acumula series en ambos, y agruparlos dispara falsos positivos de
    # exceso de volumen.
    "dorsales": {"lats"},
    "espalda_alta": {"upper back", "traps", "spine"},
    "hombros": {"delts", "levator scapulae"},
    "biceps": {"biceps"},
    "triceps": {"triceps"},
    "cuadriceps": {"quads"},
    "isquios": {"hamstrings"},
    "gluteos": {"glutes", "abductors", "adductors"},
    "gemelos": {"calves"},
    "core": {"abs"},
    "antebrazos": {"forearms"},
    "cardio": {"cardiovascular system"},
}
TARGET_TO_GROUP = {t: g for g, targets in MUSCLE_GROUPS.items() for t in targets}


def classify_pattern(name: str, body_part: str, target: str) -> tuple[str, bool]:
    """Devuelve (patrón, nombrado).

    `nombrado` es True cuando el patrón se dedujo del propio nombre del
    ejercicio y no de una heurística por músculo objetivo. Solo los patrones
    nombrados pueden actuar como levantamiento principal: para el resto la
    clasificación es demasiado laxa para construir la parte pesada de la
    sesión sobre ella.
    """
    lowered = name.lower()
    for pattern, regex in PATTERN_RULES:
        if re.search(regex, lowered):
            return pattern, True
    if body_part == "cardio":
        return "cardio", True
    if target == "delts":
        return ("empuje_vertical" if re.search(r"\bpress\b", lowered) else "hombro_aislado"), False
    return TARGET_FALLBACK.get(target, "otro"), False


def detect_joints(name: str, body_part: str) -> list[str]:
    lowered = name.lower()
    joints: set[str] = set(BODY_PART_JOINTS.get(body_part, []))
    for joint, regexes in JOINT_RULES.items():
        if any(re.search(rx, lowered) for rx in regexes):
            joints.add(joint)
    return sorted(joints)


def load_source(source: str | None) -> list[dict]:
    if source:
        return json.loads(Path(source).read_text(encoding="utf-8"))
    print(f"Descargando {SOURCE_URL} ...", file=sys.stderr)
    with urllib.request.urlopen(SOURCE_URL) as response:  # noqa: S310 - URL fija
        return json.loads(response.read().decode("utf-8"))


def build(raw: list[dict]) -> list[dict]:
    catalog = []
    for item in raw:
        name = item["name"]
        body_part = item["body_part"]
        target = item["target"]
        pattern, named = classify_pattern(name, body_part, target)
        equipment = item["equipment"]

        catalog.append(
            {
                "id": item["id"],
                "name": name,
                "body_part": body_part,
                "body_part_es": BODY_PART_ES.get(body_part, body_part),
                "target": target,
                "target_es": TARGET_ES.get(target, target),
                "muscle_group": TARGET_TO_GROUP.get(target, "otro"),
                "secondary_muscles": item["secondary_muscles"],
                "equipment": equipment,
                "equipment_es": EQUIPMENT_ES.get(equipment, equipment),
                "pattern": pattern,
                # True cuando el patrón se dedujo del nombre del ejercicio y
                # no de una heurística por músculo objetivo. El planificador
                # lo usa para preferir clasificaciones fiables.
                "pattern_confident": named,
                "compound": pattern in COMPOUND_PATTERNS,
                "primary_lift": named and pattern in COMPOUND_PATTERNS and equipment in PRIMARY_EQUIPMENT,
                "joints": detect_joints(name, body_part),
                "gif_url": f"{RAW_BASE}/{item['gif_url']}",
                "image_url": f"{RAW_BASE}/{item['image']}",
                "attribution": item["attribution"],
                "steps_es": item["instruction_steps"]["es"],
                "steps_en": item["instruction_steps"]["en"],
            }
        )
    catalog.sort(key=lambda e: e["id"])
    return catalog


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="Ruta local a exercises.json (por defecto se descarga)")
    parser.add_argument("--out", default=str(OUT_PATH), help="Fichero de salida")
    args = parser.parse_args()

    raw = load_source(args.source)
    catalog = build(raw)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8")

    patterns: dict[str, int] = {}
    for entry in catalog:
        patterns[entry["pattern"]] = patterns.get(entry["pattern"], 0) + 1
    print(f"{len(catalog)} ejercicios -> {out} ({out.stat().st_size / 1e6:.1f} MB)")
    for pattern, count in sorted(patterns.items(), key=lambda kv: -kv[1]):
        print(f"  {pattern:24} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
