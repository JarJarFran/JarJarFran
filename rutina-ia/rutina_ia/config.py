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


# --- Motor de suscripción (CLI de Claude Code) -----------------------------
# Permite usar una suscripción Pro o Max en lugar de una clave de API. Requiere
# Claude Code instalado y con sesión iniciada en esta máquina.
CLAUDE_CODE_BIN = os.getenv("RUTINA_IA_CLAUDE_CODE_BIN", "claude")
CLAUDE_CODE_TIMEOUT = int(os.getenv("RUTINA_IA_CLAUDE_CODE_TIMEOUT", "420"))

# Motor por defecto cuando la petición pide "auto":
#   suscripcion → api → determinista, en ese orden de preferencia.
# Se puede fijar uno concreto con RUTINA_IA_ENGINE.
DEFAULT_ENGINE = os.getenv("RUTINA_IA_ENGINE", "auto")


def has_api_key() -> bool:
    """¿Hay credenciales de API con las que facturar por uso?"""
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
