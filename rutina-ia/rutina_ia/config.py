"""Configuración de la aplicación, leída del entorno."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = Path(os.getenv("RUTINA_IA_CATALOG", ROOT / "data" / "catalog.json"))

# Copia local opcional de los GIF (ver scripts/fetch_media.py). Si existe, la
# app la sirve desde /media y puede incrustar los GIF en el documento
# exportado; si no, se enlazan al repositorio original.
MEDIA_DIR = Path(os.getenv("RUTINA_IA_MEDIA", ROOT / "data" / "media"))

# Modelo por defecto. Opus 5 es el más capaz para razonar sobre restricciones
# combinadas (lesiones + material + volumen + tiempo de sesión).
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5")

# El esfuerzo alto compensa: una rutina mal periodizada cuesta más que unos
# cuantos tokens de razonamiento.
EFFORT = os.getenv("ANTHROPIC_EFFORT", "high")
MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "32000"))

# Número de reintentos con el informe de errores del validador antes de
# devolver la rutina con avisos.
MAX_REPAIR_ATTEMPTS = int(os.getenv("RUTINA_IA_MAX_REPAIRS", "2"))

# Cuántos ejercicios candidatos se envían al modelo. Suficiente para dar
# variedad sin inflar el prompt.
MAX_CANDIDATES = int(os.getenv("RUTINA_IA_MAX_CANDIDATES", "260"))


def has_api_key() -> bool:
    """La app funciona sin clave: cae al planificador determinista."""
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
