"""
App Settings
============

Shared runtime objects for the platform.
"""

from os import getenv

from agno.models.openrouter import OpenRouter


def default_model(max_tokens: int | None = None) -> OpenRouter:
    """Fresh model instance per agent — avoids shared-state footguns.

    `max_tokens` raises the output cap for agents with long answers; left unset,
    agno's OpenRouter default (1024) applies.
    """
    model = OpenRouter(id=getenv("OPENROUTER_MODEL", "~openai/gpt-mini-latest"))
    if max_tokens is not None:
        model.max_tokens = max_tokens
    return model
