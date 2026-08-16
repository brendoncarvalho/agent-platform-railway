"""
App Settings
============

Shared runtime objects for the platform.
"""

from os import getenv

from agno.models.openrouter import OpenRouter


def default_model() -> OpenRouter:
    """Fresh model instance per agent — avoids shared-state footguns."""
    return OpenRouter(id=getenv("OPENROUTER_MODEL", "~openai/gpt-mini-latest"))
