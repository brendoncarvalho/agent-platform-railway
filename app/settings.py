"""
App Settings
============

Shared runtime configuration for the platform: model factories, image/media settings and
small env helpers. Every value comes from environment variables with the defaults documented
in `example.env` — API keys never live in code.
"""

import inspect
from dataclasses import dataclass
from functools import wraps
from os import getenv
from pathlib import Path
from typing import Any

from agno.models.base import Model
from agno.models.openrouter import OpenRouter

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_OPENROUTER_MODEL = "~openai/gpt-mini-latest"

# Output cap for OpenRouter models that do not set their own. agno's default is 1024, which
# truncates long answers (e.g. a JSON transcription) in the middle.
DEFAULT_OPENROUTER_MAX_TOKENS = 8192

# Extra OpenRouter models offered in AgentOS Studio, next to the default one.
STUDIO_MODEL_IDS = (
    "google/gemini-3.8-flash",
    "anthropic/claude-sonnet-5.5",
    "openai/gpt-5.6-terra",
)

# Chat model used when CHAT_MODEL_ID is not set, per provider. All of them accept images.
CHAT_MODEL_DEFAULTS: dict[str, str] = {
    "openrouter": DEFAULT_OPENROUTER_MODEL,
    "openai": "gpt-5-mini",
    "google": "gemini-2.5-flash",
    "anthropic": "claude-sonnet-4-5",
}

# Image generation model used when IMAGE_MODEL is not set, per provider.
# openrouter: any model at https://openrouter.ai/models?output_modalities=image (edits via reference image).
IMAGE_MODEL_DEFAULTS: dict[str, str] = {
    "openrouter": "google/gemini-2.5-flash-image",
    "openai": "gpt-image-1",
    "gemini": "imagen-4.0-generate-001",
}
DEFAULT_IMAGE_PROVIDER = "openrouter"


# ---------------------------------------------------------------------------
# Env helpers
# ---------------------------------------------------------------------------
def env_flag(name: str, default: bool) -> bool:
    """Read a boolean env var, accepting 1/true/yes/on (any casing) as true."""
    value = getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def env_int(name: str, default: int) -> int:
    """Read an integer env var; malformed or empty values fall back to the default."""
    value = getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_list(name: str, default: str) -> tuple[str, ...]:
    """Read a comma-separated env var as a tuple of lower-case, stripped items."""
    raw = getenv(name) or default
    return tuple(item.strip().lower() for item in raw.split(",") if item.strip())


# ---------------------------------------------------------------------------
# Chat models
# ---------------------------------------------------------------------------
def openrouter_max_tokens() -> int:
    """Platform output cap for OpenRouter models (`OPENROUTER_MAX_TOKENS`)."""
    return max(1, env_int("OPENROUTER_MAX_TOKENS", DEFAULT_OPENROUTER_MAX_TOKENS))


def apply_openrouter_output_cap() -> None:
    """Make every `OpenRouter` model built without `max_tokens` use the platform cap.

    Agents created from the portal/Studio are stored as components whose model is just a
    `provider:id` string; agno rebuilds it as `OpenRouter(id=...)` with its own default
    (1024 output tokens) and the component config has no field to change that. Wrapping the
    constructor is the one place that covers those agents as well as the ones in code.
    An explicit `max_tokens` (argument or later assignment) always wins. Idempotent.
    """
    original = OpenRouter.__init__
    if getattr(original, "_pemill_output_cap", False):
        return
    # Position of `max_tokens` among the constructor arguments (after `self`), to leave
    # alone the unlikely call that passes it positionally.
    position = list(inspect.signature(original).parameters).index("max_tokens") - 1

    @wraps(original)
    def __init__(self: OpenRouter, *args: Any, **kwargs: Any) -> None:
        if "max_tokens" not in kwargs and len(args) <= position:
            kwargs["max_tokens"] = openrouter_max_tokens()
        original(self, *args, **kwargs)

    __init__._pemill_output_cap = True  # type: ignore[attr-defined]
    OpenRouter.__init__ = __init__  # type: ignore[method-assign]


# Applied on import: every module that builds a model imports this one first.
apply_openrouter_output_cap()


def default_model(max_tokens: int | None = None, id: str | None = None) -> OpenRouter:
    """Fresh OpenRouter model instance per agent — avoids shared-state footguns.

    `max_tokens` sets the output cap for this agent; left unset, the platform cap
    (`OPENROUTER_MAX_TOKENS`, default 8192) applies. `id` picks another OpenRouter model;
    left unset, `OPENROUTER_MODEL` (or the platform default) applies.
    """
    model = OpenRouter(id=id or getenv("OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODEL)
    if max_tokens is not None:
        model.max_tokens = max_tokens
    return model


def chat_model(provider: str | None = None, id: str | None = None, max_tokens: int | None = None) -> Model:
    """Provider-aware chat model factory driven by `CHAT_MODEL_PROVIDER` / `CHAT_MODEL_ID`.

    Supported providers: `openrouter` (default, key `OPENROUTER_API_KEY`), `openai`
    (`OPENAI_API_KEY`), `google` (`GOOGLE_API_KEY`, needs `google-genai`) and `anthropic`
    (`ANTHROPIC_API_KEY`, needs `anthropic`). Imports are lazy so optional SDKs are only
    required when their provider is selected.
    """
    provider = (provider or getenv("CHAT_MODEL_PROVIDER") or "openrouter").strip().lower()
    model_id = id or (getenv("CHAT_MODEL_ID") or "").strip() or None

    model: Model
    if provider == "openrouter":
        model = OpenRouter(id=model_id or getenv("OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODEL)
    elif provider == "openai":
        from agno.models.openai import OpenAIChat

        model = OpenAIChat(id=model_id or CHAT_MODEL_DEFAULTS["openai"])
    elif provider == "google":
        from agno.models.google import Gemini

        model = Gemini(id=model_id or CHAT_MODEL_DEFAULTS["google"])
    elif provider == "anthropic":
        from agno.models.anthropic import Claude

        model = Claude(id=model_id or CHAT_MODEL_DEFAULTS["anthropic"])
    else:
        raise ValueError(
            f"CHAT_MODEL_PROVIDER='{provider}' is not supported. Use one of: {', '.join(CHAT_MODEL_DEFAULTS)}."
        )

    if max_tokens is not None and hasattr(model, "max_tokens"):
        model.max_tokens = max_tokens
    return model


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ImageSettings:
    """Image generation settings and image input limits (see `example.env`)."""

    provider: str
    model: str
    size: str
    quality: str | None
    api_key: str | None
    input_max_bytes: int
    input_formats: tuple[str, ...]

    @property
    def input_max_mb(self) -> float:
        return self.input_max_bytes / (1024 * 1024)


def image_settings() -> ImageSettings:
    provider = (getenv("IMAGE_PROVIDER") or DEFAULT_IMAGE_PROVIDER).strip().lower()
    if provider not in IMAGE_MODEL_DEFAULTS:
        raise ValueError(
            f"IMAGE_PROVIDER='{provider}' is not supported. Use one of: {', '.join(IMAGE_MODEL_DEFAULTS)}."
        )
    quality = (getenv("IMAGE_QUALITY") or "auto").strip().lower()
    return ImageSettings(
        provider=provider,
        model=(getenv("IMAGE_MODEL") or "").strip() or IMAGE_MODEL_DEFAULTS[provider],
        size=(getenv("IMAGE_SIZE") or "1024x1024").strip().lower(),
        quality=None if quality in ("", "auto") else quality,
        api_key=(getenv("IMAGE_API_KEY") or "").strip() or None,
        input_max_bytes=env_int("IMAGE_INPUT_MAX_MB", 10) * 1024 * 1024,
        input_formats=env_list("IMAGE_INPUT_FORMATS", "png,jpeg,webp"),
    )


# ---------------------------------------------------------------------------
# Media storage (uploaded and generated images)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MediaStorageSettings:
    """Where agno persists run media. `local` (default) or `s3`."""

    backend: str
    local_dir: Path
    s3_bucket: str | None
    s3_prefix: str
    s3_region: str | None
    s3_endpoint_url: str | None


def media_storage_settings() -> MediaStorageSettings:
    backend = (getenv("MEDIA_STORAGE") or "local").strip().lower()
    if backend not in ("local", "s3"):
        raise ValueError(f"MEDIA_STORAGE='{backend}' is not supported. Use 'local' or 's3'.")
    local_dir = Path(getenv("MEDIA_STORAGE_DIR") or "storage/media")
    if not local_dir.is_absolute():
        local_dir = REPO_ROOT / local_dir
    return MediaStorageSettings(
        backend=backend,
        local_dir=local_dir,
        s3_bucket=(getenv("MEDIA_S3_BUCKET") or "").strip() or None,
        s3_prefix=getenv("MEDIA_S3_PREFIX") or "pemill/media/",
        s3_region=(getenv("MEDIA_S3_REGION") or getenv("AWS_REGION") or "").strip() or None,
        s3_endpoint_url=(getenv("MEDIA_S3_ENDPOINT_URL") or "").strip() or None,
    )
