"""
App Settings
============

Shared runtime objects for the platform.
"""

from os import getenv

from agno.models.openrouter import OpenRouter


def default_model() -> OpenRouter:
    """Cria uma nova instância do modelo padrão para cada agente."""
    return OpenRouter(
        id=getenv(
            "OPENROUTER_MODEL",
            "openai/gpt-4.1-mini",
        ),
    )
