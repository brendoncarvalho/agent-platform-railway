"""
Image Input Guardrail
=====================

Validates the images a user sends to an agent (upload, URL, data URL or base64) before the
run reaches the model: only the configured formats (PNG, JPEG and WEBP by default) and only
up to the configured size (`IMAGE_INPUT_MAX_MB`). Remote URLs are downloaded once, checked
and handed to the model as bytes, so the provider never fetches an unchecked URL.
"""

import base64
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx
from agno.exceptions import CheckTrigger, InputCheckError
from agno.guardrails import BaseGuardrail
from agno.media import Image
from agno.run.agent import RunInput
from agno.run.team import TeamRunInput

from app.settings import image_settings

# Magic bytes → canonical format name.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"BM", "bmp"),
    (b"II*\x00", "tiff"),
    (b"MM\x00*", "tiff"),
)

MIME_BY_FORMAT: dict[str, str] = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
}

_FORMAT_ALIASES = {"jpg": "jpeg", "pjpeg": "jpeg"}


def normalize_format(value: str | None) -> str | None:
    """`image/jpeg`, `JPG`, `.jpeg` → `jpeg`."""
    if not value:
        return None
    fmt = value.strip().lower()
    if "/" in fmt:
        fmt = fmt.rsplit("/", 1)[-1]
    fmt = fmt.lstrip(".")
    return _FORMAT_ALIASES.get(fmt, fmt)


def sniff_image_format(data: bytes) -> str | None:
    """Detect the image format from its first bytes; None when it is not a known image."""
    for magic, fmt in _MAGIC:
        if data.startswith(magic):
            return fmt
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _looks_like_base64(data: bytes) -> bool:
    sample = data[:256].replace(b"\r", b"").replace(b"\n", b"")
    return bool(sample) and all(c in _BASE64_ALPHABET for c in sample)


_BASE64_ALPHABET = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")


def _format_mb(num_bytes: int) -> str:
    return f"{num_bytes / (1024 * 1024):.0f} MB"


class ImageInputGuardrail(BaseGuardrail):
    """Rejects images that are too large or not in an allowed format.

    Raises `InputCheckError` (pt-BR message) so AgentOS answers the request with a clear
    validation error instead of sending the image to the model.
    """

    def __init__(
        self,
        max_bytes: int | None = None,
        allowed_formats: Iterable[str] | None = None,
        fetch_timeout: float = 20.0,
    ):
        settings = image_settings()
        self.max_bytes = max_bytes if max_bytes is not None else settings.input_max_bytes
        formats = allowed_formats if allowed_formats is not None else settings.input_formats
        self.allowed_formats = frozenset(normalize_format(f) or "" for f in formats) - {""}
        self.fetch_timeout = fetch_timeout

    # -- BaseGuardrail -----------------------------------------------------
    def check(self, run_input: RunInput | TeamRunInput) -> None:
        for image in run_input.images or []:
            data = self._load_content(image)
            self._validate(image, data)

    async def async_check(self, run_input: RunInput | TeamRunInput) -> None:
        for image in run_input.images or []:
            data = await self._aload_content(image)
            self._validate(image, data)

    # -- Loading -----------------------------------------------------------
    def _load_content(self, image: Image) -> bytes | None:
        if image.content is not None:
            data = self._as_bytes(image.content)
            if data is not image.content:
                image.content = data  # hand the model the decoded bytes
            return data
        if image.filepath:
            return self._read_file(Path(str(image.filepath)))
        if image.url:
            if image.url.startswith("data:"):
                return self._decode_data_url(image.url)
            with httpx.Client(timeout=self.fetch_timeout, follow_redirects=True) as client:
                with client.stream("GET", image.url) as response:
                    response.raise_for_status()
                    self._check_content_length(response.headers.get("content-length"))
                    data = self._collect(response.iter_bytes())
            self._replace_url_with_content(image, data)
            return data
        return None

    async def _aload_content(self, image: Image) -> bytes | None:
        is_remote_url = bool(image.url) and not str(image.url).startswith("data:")
        if is_remote_url and image.content is None and not image.filepath:
            async with httpx.AsyncClient(timeout=self.fetch_timeout, follow_redirects=True) as client:
                async with client.stream("GET", str(image.url)) as response:
                    response.raise_for_status()
                    self._check_content_length(response.headers.get("content-length"))
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > self.max_bytes:
                            raise self._too_large()
                        chunks.append(chunk)
                    data = b"".join(chunks)
            self._replace_url_with_content(image, data)
            return data
        return self._load_content(image)

    def _as_bytes(self, content: Any) -> bytes:
        if isinstance(content, bytes):
            # agno keeps a base64 *string* as its UTF-8 bytes; recover the real image bytes.
            if sniff_image_format(content) is None and _looks_like_base64(content):
                try:
                    decoded = base64.b64decode(content, validate=True)
                except Exception:
                    return content
                if sniff_image_format(decoded) is not None:
                    return decoded
            return content
        if isinstance(content, str):
            try:
                return base64.b64decode(content, validate=True)
            except Exception as exc:
                raise InputCheckError(
                    "Não foi possível ler a imagem enviada (conteúdo base64 inválido).",
                    check_trigger=CheckTrigger.VALIDATION_FAILED,
                ) from exc
        raise InputCheckError(
            "Não foi possível ler a imagem enviada (conteúdo desconhecido).",
            check_trigger=CheckTrigger.VALIDATION_FAILED,
        )

    def _read_file(self, path: Path) -> bytes:
        try:
            if path.stat().st_size > self.max_bytes:
                raise self._too_large()
            return path.read_bytes()
        except OSError as exc:
            raise InputCheckError(
                f"Não foi possível ler o arquivo de imagem '{path.name}'.",
                check_trigger=CheckTrigger.VALIDATION_FAILED,
            ) from exc

    def _decode_data_url(self, url: str) -> bytes:
        header, _, payload = url.partition(",")
        if ";base64" not in header or not payload:
            raise InputCheckError(
                "A imagem em data URL precisa estar codificada em base64.",
                check_trigger=CheckTrigger.VALIDATION_FAILED,
            )
        # 4 base64 chars encode 3 bytes: refuse before decoding when clearly too large.
        if len(payload) * 3 // 4 > self.max_bytes:
            raise self._too_large()
        return self._as_bytes(payload)

    def _check_content_length(self, header: str | None) -> None:
        if header and header.isdigit() and int(header) > self.max_bytes:
            raise self._too_large()

    def _collect(self, chunks: Iterable[bytes]) -> bytes:
        collected: list[bytes] = []
        total = 0
        for chunk in chunks:
            total += len(chunk)
            if total > self.max_bytes:
                raise self._too_large()
            collected.append(chunk)
        return b"".join(collected)

    @staticmethod
    def _replace_url_with_content(image: Image, data: bytes) -> None:
        """Hand the model the validated bytes instead of the URL, keeping the origin in metadata."""
        metadata = dict(image.metadata or {})
        metadata.setdefault("source_url", image.url)
        image.metadata = metadata
        image.content = data
        image.url = None

    # -- Validation --------------------------------------------------------
    def _validate(self, image: Image, data: bytes | None) -> None:
        if data is None:
            return  # nothing to inspect (empty media object)
        if len(data) > self.max_bytes:
            raise self._too_large()
        fmt = sniff_image_format(data) or normalize_format(image.mime_type) or normalize_format(image.format)
        if fmt is None:
            raise InputCheckError(
                "O arquivo enviado não parece ser uma imagem válida. " + self._allowed_hint(),
                check_trigger=CheckTrigger.VALIDATION_FAILED,
            )
        if fmt not in self.allowed_formats:
            raise InputCheckError(
                f"Formato de imagem não suportado ({fmt.upper()}). " + self._allowed_hint(),
                check_trigger=CheckTrigger.VALIDATION_FAILED,
            )
        # Normalize the declared type so the model provider receives a consistent mime type.
        image.format = fmt
        image.mime_type = MIME_BY_FORMAT.get(fmt, image.mime_type)

    def _allowed_hint(self) -> str:
        allowed = ", ".join(sorted(f.upper() for f in self.allowed_formats))
        return f"Envie uma imagem em {allowed} com até {_format_mb(self.max_bytes)}."

    def _too_large(self) -> InputCheckError:
        return InputCheckError(
            f"A imagem excede o tamanho máximo permitido de {_format_mb(self.max_bytes)}.",
            check_trigger=CheckTrigger.VALIDATION_FAILED,
        )
