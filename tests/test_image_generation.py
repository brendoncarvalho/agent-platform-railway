"""Image generation toolkit: storage, media references, session state and edits (fake backend)."""

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from agno.media.storage.local import LocalMediaStorage
from agno.run.base import RunContext

from app.image_generation import (
    SESSION_LAST_IMAGE_KEY,
    STORAGE_PREFIX,
    GeneratedImage,
    ImageGenerationTools,
    storage_key_for,
)
from app.media_samples import solid_color_png
from app.settings import ImageSettings

SETTINGS = ImageSettings(
    provider="openai",
    model="fake-image-model",
    size="1024x1024",
    quality=None,
    api_key=None,
    input_max_bytes=1024 * 1024,
    input_formats=("png", "jpeg", "webp"),
)


@dataclass
class FakeBackend:
    model: str = "fake-image-model"
    supports_edit: bool = True
    calls: list[tuple[str, str]] = field(default_factory=list)
    fail: bool = False

    def generate(self, prompt: str, *, size: str, quality: str | None) -> GeneratedImage:
        self.calls.append(("generate", prompt))
        if self.fail:
            raise RuntimeError("quota exceeded")
        return GeneratedImage(
            content=solid_color_png(16, 16, (0, 0, 255)), mime_type="image/png", revised_prompt="azul"
        )

    def edit(self, source: bytes, source_mime: str, prompt: str, *, size: str, quality: str | None) -> GeneratedImage:
        self.calls.append(("edit", prompt))
        assert source.startswith(b"\x89PNG"), "edit must receive the stored source image"
        return GeneratedImage(content=solid_color_png(16, 16, (0, 255, 0)), mime_type="image/png")


def _tools(
    media_dir: Path, backend: FakeBackend | None = None
) -> tuple[ImageGenerationTools, FakeBackend, LocalMediaStorage]:
    backend = backend or FakeBackend()
    storage = LocalMediaStorage(base_path=str(media_dir))
    return ImageGenerationTools(settings=SETTINGS, storage=storage, backend=backend), backend, storage


def _context(session_state: dict | None = None) -> RunContext:
    return RunContext(run_id="run-1", session_id="sess-1", user_id="user-1", session_state=session_state)


def test_toolkit_exposes_generate_and_edit(media_dir: Path):
    tools, _, _ = _tools(media_dir)
    assert set(tools.functions) == {"generate_image", "edit_image"}
    # run_context is injected by agno, never exposed to the model.
    for function in tools.functions.values():
        assert "run_context" not in (function.parameters or {}).get("properties", {})


def test_generate_image_persists_and_returns_media_reference(media_dir: Path):
    tools, backend, storage = _tools(media_dir)
    state: dict = {}

    result = tools.generate_image("um caminhão azul", run_context=_context(state))

    assert backend.calls == [("generate", "um caminhão azul")]
    assert result.images and len(result.images) == 1
    image = result.images[0]
    assert image.id and image.mime_type == "image/png" and image.format == "png"
    assert image.original_prompt == "um caminhão azul"
    assert image.revised_prompt == "azul"
    assert image.media_reference is not None
    assert image.media_reference.storage_backend == "local"
    assert image.media_reference.storage_key == storage_key_for(image.id)
    assert storage.exists(image.media_reference.storage_key)
    assert (media_dir / f"{STORAGE_PREFIX}{image.id}.png").read_bytes() == image.content
    assert state[SESSION_LAST_IMAGE_KEY] == image.id
    assert "Imagem gerada com sucesso" in result.content and image.id in result.content


def test_edit_image_defaults_to_last_generated_image(media_dir: Path):
    tools, backend, _ = _tools(media_dir)
    state: dict = {}
    generated = tools.generate_image("um caminhão azul", run_context=_context(state))
    assert generated.images
    first = generated.images[0]

    result = tools.edit_image("deixe o caminhão verde", run_context=_context(state))

    assert backend.calls[-1] == ("edit", "deixe o caminhão verde")
    assert result.images
    edited = result.images[0]
    assert edited.id != first.id
    assert edited.metadata and edited.metadata["parent_image_id"] == first.id
    assert state[SESSION_LAST_IMAGE_KEY] == edited.id
    assert "Imagem editada com sucesso" in result.content


def test_edit_image_with_explicit_id_and_unknown_id(media_dir: Path):
    tools, _, _ = _tools(media_dir)
    generated = tools.generate_image("logo", run_context=_context({}))
    assert generated.images
    first = generated.images[0]

    ok = tools.edit_image("fundo branco", image_id=first.id, run_context=_context({}))
    assert ok.images and ok.images[0].metadata
    assert ok.images[0].metadata["parent_image_id"] == first.id

    missing = tools.edit_image("fundo branco", image_id="deadbeef", run_context=_context({}))
    assert missing.images is None
    assert "Não encontrei a imagem" in missing.content


def test_edit_without_any_generated_image_explains(media_dir: Path):
    tools, _, _ = _tools(media_dir)
    result = tools.edit_image("mude a cor", run_context=_context({}))
    assert result.images is None
    assert "Nenhuma imagem foi gerada" in result.content


def test_edit_unsupported_by_backend(media_dir: Path):
    tools, _, _ = _tools(media_dir, FakeBackend(supports_edit=False))
    result = tools.edit_image("mude a cor", run_context=_context({}))
    assert "não suporta edição" in result.content


def test_backend_failure_becomes_tool_message(media_dir: Path):
    tools, _, _ = _tools(media_dir, FakeBackend(fail=True))
    result = tools.generate_image("qualquer coisa", run_context=_context({}))
    assert result.images is None
    assert "Falha ao gerar a imagem" in result.content and "quota exceeded" in result.content


def test_generate_without_run_context_still_works(media_dir: Path):
    tools, _, _ = _tools(media_dir)
    result = tools.generate_image("sem contexto")
    assert result.images and result.images[0].media_reference is not None


@pytest.mark.parametrize("mime,ext", [("image/png", ".png"), ("image/jpeg", ".jpg"), ("image/webp", ".webp")])
def test_storage_key_is_deterministic_and_path_safe(mime: str, ext: str):
    key = storage_key_for("abc123", mime)
    assert key == f"{STORAGE_PREFIX}abc123{ext}"
    assert "/" not in storage_key_for("../evil", mime)
