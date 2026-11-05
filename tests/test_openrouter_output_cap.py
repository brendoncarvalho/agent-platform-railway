"""Platform output cap for OpenRouter models, including the ones agno builds from a `provider:id` string."""

from agno.models.openrouter import OpenRouter
from agno.models.utils import get_model

from app.settings import (
    DEFAULT_OPENROUTER_MAX_TOKENS,
    apply_openrouter_output_cap,
    default_model,
    openrouter_max_tokens,
)


def test_default_cap_replaces_agno_1024(monkeypatch):
    monkeypatch.delenv("OPENROUTER_MAX_TOKENS", raising=False)
    assert openrouter_max_tokens() == DEFAULT_OPENROUTER_MAX_TOKENS == 8192
    assert OpenRouter(id="anthropic/claude-sonnet-5.5").max_tokens == 8192
    assert default_model().max_tokens == 8192


def test_portal_agents_built_from_model_string_get_the_cap(monkeypatch):
    # The portal stores `provider:id`; agno rebuilds the model with no other argument.
    monkeypatch.setenv("OPENROUTER_MAX_TOKENS", "6000")
    model = get_model("openrouter:anthropic/claude-sonnet-5.5")
    assert isinstance(model, OpenRouter)
    assert model.id == "anthropic/claude-sonnet-5.5" and model.max_tokens == 6000


def test_explicit_max_tokens_wins(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MAX_TOKENS", "6000")
    assert OpenRouter(id="m", max_tokens=1024).max_tokens == 1024
    assert default_model(max_tokens=2048).max_tokens == 2048


def test_invalid_env_falls_back_and_apply_is_idempotent(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MAX_TOKENS", "muito")
    assert openrouter_max_tokens() == 8192
    monkeypatch.setenv("OPENROUTER_MAX_TOKENS", "0")
    assert openrouter_max_tokens() == 1

    wrapped = OpenRouter.__init__
    apply_openrouter_output_cap()
    assert OpenRouter.__init__ is wrapped
