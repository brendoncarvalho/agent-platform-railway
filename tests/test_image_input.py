"""Image input validation: formats, size limits and content sources."""

import base64

import pytest
from agno.exceptions import InputCheckError
from agno.media import Image
from agno.run.agent import RunInput

from app.image_input import ImageInputGuardrail, normalize_format, sniff_image_format
from app.media_samples import minimal_gif, minimal_jpeg, minimal_webp, solid_color_png

ONE_MB = 1024 * 1024


def _run_input(*images: Image) -> RunInput:
    return RunInput(input_content="o que há nesta imagem?", images=list(images))


def test_sniff_detects_supported_formats():
    assert sniff_image_format(solid_color_png()) == "png"
    assert sniff_image_format(minimal_jpeg()) == "jpeg"
    assert sniff_image_format(minimal_webp()) == "webp"
    assert sniff_image_format(minimal_gif()) == "gif"
    assert sniff_image_format(b"not an image") is None


def test_normalize_format_accepts_mime_and_aliases():
    assert normalize_format("image/jpeg") == "jpeg"
    assert normalize_format("JPG") == "jpeg"
    assert normalize_format(".webp") == "webp"
    assert normalize_format(None) is None


@pytest.mark.parametrize("payload", [solid_color_png(), minimal_jpeg(), minimal_webp()])
def test_allowed_formats_pass_and_get_normalized(payload: bytes):
    guardrail = ImageInputGuardrail(max_bytes=ONE_MB, allowed_formats=("png", "jpg", "webp"))
    image = Image(content=payload)
    guardrail.check(_run_input(image))
    assert image.format in {"png", "jpeg", "webp"}
    assert image.mime_type == f"image/{image.format}"


def test_gif_is_rejected_with_pt_br_message():
    guardrail = ImageInputGuardrail(max_bytes=ONE_MB, allowed_formats=("png", "jpeg", "webp"))
    with pytest.raises(InputCheckError) as excinfo:
        guardrail.check(_run_input(Image(content=minimal_gif(), mime_type="image/gif")))
    assert "GIF" in str(excinfo.value)
    assert "PNG, JPEG, WEBP" in str(excinfo.value) or "JPEG" in str(excinfo.value)


def test_oversized_image_is_rejected():
    guardrail = ImageInputGuardrail(max_bytes=1024, allowed_formats=("png",))
    big = solid_color_png(64, 64) + b"\x00" * 2048
    with pytest.raises(InputCheckError) as excinfo:
        guardrail.check(_run_input(Image(content=big)))
    assert "tamanho máximo" in str(excinfo.value)


def test_non_image_bytes_are_rejected():
    guardrail = ImageInputGuardrail(max_bytes=ONE_MB, allowed_formats=("png",))
    with pytest.raises(InputCheckError):
        guardrail.check(_run_input(Image(content=b"%PDF-1.4 definitely not an image")))


def test_base64_string_content_is_accepted():
    guardrail = ImageInputGuardrail(max_bytes=ONE_MB, allowed_formats=("png",))
    encoded = base64.b64encode(solid_color_png()).decode()
    image = Image(content=encoded)  # agno normalizes base64 strings to bytes
    guardrail.check(_run_input(image))
    assert image.format == "png"


def test_data_url_is_decoded_and_validated():
    guardrail = ImageInputGuardrail(max_bytes=ONE_MB, allowed_formats=("png",))
    data_url = "data:image/png;base64," + base64.b64encode(solid_color_png()).decode()
    image = Image(url=data_url)
    guardrail.check(_run_input(image))
    assert image.format == "png"

    with pytest.raises(InputCheckError):
        guardrail.check(_run_input(Image(url="data:image/gif;base64," + base64.b64encode(minimal_gif()).decode())))


def test_remote_url_is_fetched_once_and_replaced_by_bytes(monkeypatch: pytest.MonkeyPatch):
    import httpx

    payload = solid_color_png()
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, content=payload, headers={"content-type": "image/png"})

    transport = httpx.MockTransport(handler)
    original_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: original_client(transport=transport, **kw))

    guardrail = ImageInputGuardrail(max_bytes=ONE_MB, allowed_formats=("png",))
    image = Image(url="https://example.com/foto.png")
    guardrail.check(_run_input(image))

    assert requests == ["https://example.com/foto.png"]
    assert image.content == payload
    assert image.url is None
    assert image.metadata == {"source_url": "https://example.com/foto.png"}


def test_filepath_is_read_and_validated(tmp_path):
    path = tmp_path / "amostra.webp"
    path.write_bytes(minimal_webp())
    guardrail = ImageInputGuardrail(max_bytes=ONE_MB, allowed_formats=("webp",))
    image = Image(filepath=path)
    guardrail.check(_run_input(image))
    assert image.mime_type == "image/webp"


@pytest.mark.asyncio
async def test_async_check_matches_sync_behaviour():
    guardrail = ImageInputGuardrail(max_bytes=ONE_MB, allowed_formats=("png",))
    await guardrail.async_check(_run_input(Image(content=solid_color_png())))
    with pytest.raises(InputCheckError):
        await guardrail.async_check(_run_input(Image(content=minimal_gif())))


def test_defaults_come_from_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("IMAGE_INPUT_MAX_MB", "3")
    monkeypatch.setenv("IMAGE_INPUT_FORMATS", "png, JPG")
    guardrail = ImageInputGuardrail()
    assert guardrail.max_bytes == 3 * ONE_MB
    assert guardrail.allowed_formats == frozenset({"png", "jpeg"})
