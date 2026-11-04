"""OpenRouter Image API backend: request shape, edits via reference image, size mapping and errors."""

import base64
import json

import httpx
import pytest

from app.image_generation import OpenRouterImageBackend, build_image_backend, openrouter_size_params
from app.media_samples import solid_color_png
from app.settings import ImageSettings

PNG = solid_color_png(8, 8, (10, 20, 200))


def _backend(handler, model: str = "google/gemini-2.5-flash-image") -> tuple[OpenRouterImageBackend, list[dict]]:
    requests: list[dict] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requests.append(
            {"url": str(request.url), "headers": dict(request.headers), "json": json.loads(request.content)}
        )
        return handler(request)

    backend = OpenRouterImageBackend(
        model=model, api_key="sk-or-test", base_url="https://stub.local/api/v1", transport=httpx.MockTransport(_handler)
    )
    return backend, requests


def _ok(_: httpx.Request) -> httpx.Response:
    data = [{"b64_json": base64.b64encode(PNG).decode(), "media_type": "image/png", "revised_prompt": "azul"}]
    return httpx.Response(200, json={"created": 1, "data": data, "usage": {"cost": 0.01}})


def test_generate_posts_to_images_endpoint_with_bearer_and_aspect_ratio():
    backend, requests = _backend(_ok)
    result = backend.generate("um caminhão azul", size="1536x1024", quality="high")

    assert result.content == PNG and result.mime_type == "image/png" and result.revised_prompt == "azul"
    assert requests[0]["url"] == "https://stub.local/api/v1/images"
    assert requests[0]["headers"]["authorization"] == "Bearer sk-or-test"
    assert requests[0]["json"] == {
        "model": "google/gemini-2.5-flash-image",
        "prompt": "um caminhão azul",
        "n": 1,
        "aspect_ratio": "3:2",
        "quality": "high",
    }


def test_edit_sends_source_as_reference_data_url():
    backend, requests = _backend(_ok)
    backend.edit(PNG, "image/png", "fundo amarelo", size="1024x1024", quality=None)

    payload = requests[0]["json"]
    assert payload["prompt"] == "fundo amarelo" and payload["aspect_ratio"] == "1:1" and "quality" not in payload
    reference = payload["input_references"][0]
    assert reference["type"] == "image_url"
    assert reference["image_url"]["url"] == f"data:image/png;base64,{base64.b64encode(PNG).decode()}"


def test_provider_error_message_is_surfaced():
    def _error(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "model not found", "code": 400}})

    backend, _ = _backend(_error)
    with pytest.raises(RuntimeError, match="400: model not found"):
        backend.generate("x", size="auto", quality=None)


def test_empty_response_is_an_error():
    backend, _ = _backend(lambda _: httpx.Response(200, json={"created": 1, "data": []}))
    with pytest.raises(RuntimeError, match="no image data"):
        backend.generate("x", size="auto", quality=None)


def test_requires_an_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        OpenRouterImageBackend(model="m")


@pytest.mark.parametrize(
    "size,expected",
    [
        ("", {}),
        ("auto", {}),
        ("1024x1024", {"aspect_ratio": "1:1"}),
        ("1536x1024", {"aspect_ratio": "3:2"}),
        ("1024x1536", {"aspect_ratio": "2:3"}),
        ("1792x1024", {"aspect_ratio": "16:9"}),  # 7:4 is not offered; closest supported ratio
        ("2K", {"size": "2K"}),
        ("1.5k", {"size": "1.5K"}),
        ("16:9", {"aspect_ratio": "16:9"}),
        ("garbage", {}),
    ],
)
def test_size_mapping(size: str, expected: dict):
    assert openrouter_size_params(size) == expected


def test_build_backend_picks_openrouter_by_default(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    settings = ImageSettings(
        provider="openrouter",
        model="openai/gpt-image-1",
        size="1024x1024",
        quality=None,
        api_key=None,
        input_max_bytes=1,
        input_formats=("png",),
    )
    backend = build_image_backend(settings)
    assert isinstance(backend, OpenRouterImageBackend) and backend.model == "openai/gpt-image-1"
    assert backend.supports_edit
