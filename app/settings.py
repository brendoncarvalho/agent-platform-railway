"""
App Settings
============

Shared runtime objects for the platform.
"""

from os import getenv

from agno.models.openrouter import OpenRouter

# Extra OpenRouter models offered in AgentOS Studio, next to the default one.
STUDIO_MODEL_IDS = (
    "google/gemini-3.8-flash",
    "anthropic/claude-sonnet-5.5",
    "openai/gpt-5.6-terra",
)


def default_model(max_tokens: int | None = None, id: str | None = None) -> OpenRouter:
    """Fresh model instance per agent — avoids shared-state footguns.

    `max_tokens` raises the output cap for agents with long answers; left unset,
    agno's OpenRouter default (1024) applies. `id` picks another OpenRouter model;
    left unset, `OPENROUTER_MODEL` (or the platform default) applies.
    """
    model = OpenRouter(id=id or getenv("OPENROUTER_MODEL", "~openai/gpt-mini-latest"))
    if max_tokens is not None:
        model.max_tokens = max_tokens
    return model
