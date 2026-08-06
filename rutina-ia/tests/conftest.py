"""Configuración común de la suite.

Regla de la suite: ningún test toca la red ni lanza el CLI de Claude Code. Los
motores se prueban con dobles; lo que se verifica es el contrato alrededor del
modelo, no el modelo. Sin esta barrera, un test que resuelva el motor «auto» en
una máquina con Claude Code instalado se pondría a generar rutinas de verdad y
la suite pasaría de un segundo a varios minutos.
"""

from __future__ import annotations

import subprocess

import pytest


@pytest.fixture(autouse=True)
def sin_subprocesos(monkeypatch, request):
    """Corta cualquier `subprocess.run` que no haya sido explícitamente falseado.

    Los tests que sí quieren simular el CLI aplican su propio monkeypatch
    encima, que gana por ser posterior.
    """
    if "permite_subprocesos" in request.keywords:
        return

    def bloqueado(*args, **kwargs):
        raise AssertionError(
            "Un test ha intentado lanzar un subproceso "
            f"({args[0] if args else kwargs.get('args')}). Falséalo con "
            "monkeypatch o marca el test con @pytest.mark.permite_subprocesos."
        )

    monkeypatch.setattr(subprocess, "run", bloqueado)


@pytest.fixture(autouse=True)
def sin_credenciales(monkeypatch):
    """Entorno neutro: ni clave de API ni CLI disponible salvo que el test los ponga."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr("rutina_ia.claude_code.available", lambda: False)
    monkeypatch.setattr("rutina_ia.claude_code.version", lambda: None)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "permite_subprocesos: el test puede lanzar subprocesos reales"
    )
