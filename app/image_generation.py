"""
Image Generation Tools
======================

`ImageGenerationTools` is the toolkit the Assistente Pemill calls to create and refine images.

- `generate_image(prompt)` asks the configured provider (`IMAGE_PROVIDER`: `openrouter`
  (default), `openai` or `gemini`) for an image, saves it in the shared media storage and
  returns it as an agno `Image` so AgentOS and the UI can display it.
- `edit_image(prompt, image_id=None)` refines an image generated earlier in the same session.
  The last generated image id is kept in the session state, so the model can simply say
  "edit the last image". OpenRouter (reference image) and OpenAI support edits; Imagen does not.

Generated files are stored under a predictable key (`pemill-img-<id>.<ext>`) so later turns can
load them again without an extra index.
"""

import base64
import hashlib
import re
from dataclasses import dataclass
from io import BytesIO
from math import gcd
from os import getenv
from typing import Any, Protocol
from uuid import uuid4

import httpx
from agno.media import Image
from agno.media.reference import MediaReference
from agno.media.storage.base import MediaStorage
from agno.media.storage.utils import build_storage_key
from agno.run.base import RunContext
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import log_error, log_info

from app.image_input import MIME_BY_FORMAT, sniff_image_format
from app.settings import ImageSettings, image_settings

STORAGE_PREFIX = "pemill-img-"
SESSION_LAST_IMAGE_KEY = "pemill_last_image_id"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

TOOLKIT_INSTRUCTIONS = """\
Ferramentas de imagem:
- Use `generate_image` quando o usuário pedir para criar, desenhar, ilustrar ou gerar uma imagem.
  Escreva o prompt de forma detalhada (assunto, estilo, cores, enquadramento). Não gere imagens sem pedido.
- Use `edit_image` quando o usuário quiser ajustar, refinar ou alterar uma imagem gerada nesta conversa
  ("deixe o fundo azul", "adicione um logotipo"). Sem `image_id`, a última imagem gerada é usada.
- Depois de gerar ou editar, descreva brevemente o resultado; a imagem é exibida automaticamente.
  Não cole o `image_id` nem URLs internas na resposta, a menos que o usuário peça.
"""


@dataclass(frozen=True)
class GeneratedImage:
    """Raw output of an image backend."""

    content: bytes
    mime_type: str
    revised_prompt: str | None = None


class ImageBackend(Protocol):
    """Provider adapter used by the toolkit."""

    model: str
    supports_edit: bool

    def generate(self, prompt: str, *, size: str, quality: str | None) -> GeneratedImage: ...

    def edit(
        self, source: bytes, source_mime: str, prompt: str, *, size: str, quality: str | None
    ) -> GeneratedImage: ...


def _decode_response(data: Any, fallback_mime: str = "image/png") -> GeneratedImage:
    """Turn an OpenAI `ImagesResponse.data[0]` into bytes (b64 or URL download)."""
    content: bytes | None = None
    if getattr(data, "b64_json", None):
        content = base64.b64decode(data.b64_json)
    elif getattr(data, "url", None):
        response = httpx.get(data.url, timeout=60.0, follow_redirects=True)
        response.raise_for_status()
        content = response.content
    if not content:
        raise RuntimeError("the provider returned no image data")
    fmt = sniff_image_format(content)
    mime = MIME_BY_FORMAT.get(fmt or "", fallback_mime)
    return GeneratedImage(content=content, mime_type=mime, revised_prompt=getattr(data, "revised_prompt", None))


class OpenAIImageBackend:
    """OpenAI Images API (`gpt-image-*` and `dall-e-*`). Supports generation and edits."""

    supports_edit = True

    def __init__(self, model: str, api_key: str | None = None, base_url: str | None = None):
        from openai import OpenAI

        self.model = model
        self._client = OpenAI(api_key=api_key or getenv("OPENAI_API_KEY"), base_url=base_url)

    @property
    def _is_gpt_image(self) -> bool:
        return self.model.startswith("gpt-image")

    def _common_params(self, size: str, quality: str | None) -> dict[str, Any]:
        params: dict[str, Any] = {"model": self.model, "n": 1}
        if size and (size != "auto" or self._is_gpt_image):
            params["size"] = size
        if quality:
            params["quality"] = quality
        if not self._is_gpt_image:
            # gpt-image models always return base64; the dall-e family needs to be asked.
            params["response_format"] = "b64_json"
        return params

    def generate(self, prompt: str, *, size: str, quality: str | None) -> GeneratedImage:
        response = self._client.images.generate(prompt=prompt, **self._common_params(size, quality))
        if not response.data:
            raise RuntimeError("the provider returned no image data")
        return _decode_response(response.data[0])

    def edit(self, source: bytes, source_mime: str, prompt: str, *, size: str, quality: str | None) -> GeneratedImage:
        extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(source_mime, "png")
        response = self._client.images.edit(
            image=(f"source.{extension}", BytesIO(source), source_mime),
            prompt=prompt,
            **self._common_params(size, quality),
        )
        if not response.data:
            raise RuntimeError("the provider returned no image data")
        return _decode_response(response.data[0])


# Aspect ratios accepted by the OpenRouter Image API (providers clamp to their own subset).
_OPENROUTER_ASPECT_RATIOS = (
    "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "4:5", "5:4",
    "1:2", "2:1", "1:4", "4:1", "1:8", "8:1", "9:21", "21:9",
)  # fmt: skip
_OPENROUTER_TIER = re.compile(r"^(512|768|1k|1\.5k|2k|4k)$")


def openrouter_size_params(size: str | None) -> dict[str, str]:
    """Translate `IMAGE_SIZE` into OpenRouter Image API fields.

    Tiers (`1K`, `2K`...) go through as `size`; `WxH` becomes the closest supported
    `aspect_ratio` (pixel sizes are rejected by several providers); `a:b` is passed as is;
    empty or `auto` lets the provider choose.
    """
    value = (size or "").strip().lower()
    if not value or value == "auto":
        return {}
    if _OPENROUTER_TIER.match(value):
        return {"size": value.upper()}
    if ":" in value:
        return {"aspect_ratio": value}
    match = re.match(r"^(\d+)\s*x\s*(\d+)$", value)
    if not match:
        return {}
    width, height = int(match.group(1)), int(match.group(2))
    if width <= 0 or height <= 0:
        return {}
    divisor = gcd(width, height)
    exact = f"{width // divisor}:{height // divisor}"
    if exact in _OPENROUTER_ASPECT_RATIOS:
        return {"aspect_ratio": exact}
    target = width / height
    closest = min(_OPENROUTER_ASPECT_RATIOS, key=lambda r: abs(int(r.split(":")[0]) / int(r.split(":")[1]) - target))
    return {"aspect_ratio": closest}


class OpenRouterImageBackend:
    """OpenRouter Image API (`POST /images`): one key for every image model on OpenRouter.

    Generation sends the prompt; edits send the stored image as an `input_references` data
    URL. Works with the models listed at https://openrouter.ai/models?output_modalities=image.
    """

    supports_edit = True

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 180.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.model = model
        key = api_key or getenv("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError(
                "OPENROUTER_API_KEY not set (or IMAGE_API_KEY) — required for IMAGE_PROVIDER=openrouter."
            )
        self._client = httpx.Client(
            base_url=(base_url or getenv("OPENROUTER_BASE_URL") or OPENROUTER_BASE_URL).rstrip("/"),
            headers={"Authorization": f"Bearer {key}", "X-Title": "Pemill AgentOS"},
            timeout=timeout,
            transport=transport,
        )

    def _payload(self, prompt: str, size: str, quality: str | None) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": self.model, "prompt": prompt, "n": 1}
        payload.update(openrouter_size_params(size))
        if quality:
            payload["quality"] = quality
        return payload

    def _request(self, payload: dict[str, Any]) -> GeneratedImage:
        response = self._client.post("/images", json=payload)
        if response.status_code >= 400:
            try:
                detail = (response.json().get("error") or {}).get("message")
            except ValueError:
                detail = None
            raise RuntimeError(f"OpenRouter image API error {response.status_code}: {detail or response.text[:200]}")
        body = response.json()
        data = body.get("data") or []
        first = data[0] if data else {}
        if not first.get("b64_json"):
            raise RuntimeError("the provider returned no image data")
        content = base64.b64decode(first["b64_json"])
        fmt = sniff_image_format(content)
        mime = MIME_BY_FORMAT.get(fmt or "", first.get("media_type") or "image/png")
        return GeneratedImage(content=content, mime_type=mime, revised_prompt=first.get("revised_prompt"))

    def generate(self, prompt: str, *, size: str, quality: str | None) -> GeneratedImage:
        return self._request(self._payload(prompt, size, quality))

    def edit(self, source: bytes, source_mime: str, prompt: str, *, size: str, quality: str | None) -> GeneratedImage:
        payload = self._payload(prompt, size, quality)
        data_url = f"data:{source_mime};base64,{base64.b64encode(source).decode()}"
        payload["input_references"] = [{"type": "image_url", "image_url": {"url": data_url}}]
        return self._request(payload)


class GeminiImageBackend:
    """Google Imagen through `google-genai`. Generation only."""

    supports_edit = False

    def __init__(self, model: str, api_key: str | None = None):
        try:
            from google import genai  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - depends on an optional dependency
            raise ImportError("IMAGE_PROVIDER=gemini requires google-genai: `pip install google-genai`.") from exc

        self.model = model
        self._client = genai.Client(api_key=api_key or getenv("GOOGLE_API_KEY"))

    def generate(self, prompt: str, *, size: str, quality: str | None) -> GeneratedImage:
        from google.genai import types  # type: ignore[import-not-found]

        response = self._client.models.generate_images(
            model=self.model,
            prompt=prompt,
            config=types.GenerateImagesConfig(number_of_images=1),
        )
        generated = (response.generated_images or [None])[0]
        image = getattr(generated, "image", None)
        if image is None or not image.image_bytes:
            raise RuntimeError("the provider returned no image data")
        return GeneratedImage(content=image.image_bytes, mime_type=image.mime_type or "image/png")

    def edit(self, source: bytes, source_mime: str, prompt: str, *, size: str, quality: str | None) -> GeneratedImage:
        raise NotImplementedError("Gemini/Imagen backend does not support image edits.")


def build_image_backend(settings: ImageSettings) -> ImageBackend:
    if settings.provider == "openrouter":
        return OpenRouterImageBackend(model=settings.model, api_key=settings.api_key)
    if settings.provider == "openai":
        return OpenAIImageBackend(model=settings.model, api_key=settings.api_key)
    if settings.provider == "gemini":
        return GeminiImageBackend(model=settings.model, api_key=settings.api_key)
    raise ValueError(f"Unsupported IMAGE_PROVIDER '{settings.provider}'.")


def storage_key_for(image_id: str, mime_type: str = "image/png") -> str:
    """Storage key of a generated image. `image_id` is a hex uuid, so the key is path-safe."""
    return build_storage_key(f"{STORAGE_PREFIX}{image_id}", mime_type=mime_type)


class ImageGenerationTools(Toolkit):
    """Generate and refine images, persisting them in the shared media storage."""

    def __init__(
        self,
        settings: ImageSettings | None = None,
        storage: MediaStorage | None = None,
        backend: ImageBackend | None = None,
    ):
        self._settings = settings
        self._storage = storage
        self._backend = backend
        super().__init__(
            name="pemill_image_tools",
            tools=[self.generate_image, self.edit_image],
            instructions=TOOLKIT_INSTRUCTIONS,
            add_instructions=True,
        )

    # Lazy so importing the agent never needs API keys or the storage directory.
    @property
    def settings(self) -> ImageSettings:
        if self._settings is None:
            self._settings = image_settings()
        return self._settings

    @property
    def storage(self) -> MediaStorage:
        if self._storage is None:
            from app.media_storage import get_media_storage

            self._storage = get_media_storage()
        return self._storage

    @property
    def backend(self) -> ImageBackend:
        if self._backend is None:
            self._backend = build_image_backend(self.settings)
        return self._backend

    # -- Tools -------------------------------------------------------------
    def generate_image(self, prompt: str, run_context: RunContext | None = None) -> ToolResult:
        """Gera uma nova imagem a partir de uma descrição textual.

        Args:
            prompt: Descrição detalhada da imagem desejada (assunto, estilo, cores, composição).
        """
        try:
            generated = self.backend.generate(prompt, size=self.settings.size, quality=self.settings.quality)
        except Exception as exc:
            log_error(f"image generation failed ({self.settings.provider}/{self.settings.model}): {exc}")
            return ToolResult(content=f"Falha ao gerar a imagem: {exc}")
        return self._store(generated, prompt, run_context, message="Imagem gerada com sucesso")

    def edit_image(self, prompt: str, image_id: str | None = None, run_context: RunContext | None = None) -> ToolResult:
        """Edita ou refina uma imagem gerada anteriormente nesta conversa.

        Args:
            prompt: O que deve mudar na imagem (ex.: "troque o fundo por um céu ao pôr do sol").
            image_id: Identificador da imagem a editar. Omita para editar a última imagem gerada.
        """
        if not self.backend.supports_edit:
            return ToolResult(
                content=(
                    f"O provedor de imagens configurado ({self.settings.provider}) não suporta edição. "
                    "Gere uma nova imagem com generate_image descrevendo o resultado completo desejado."
                )
            )

        image_id = (image_id or "").strip() or self._last_image_id(run_context)
        if not image_id:
            return ToolResult(content="Nenhuma imagem foi gerada nesta conversa ainda. Use generate_image primeiro.")

        source, source_mime = self._load_generated(image_id)
        if source is None:
            return ToolResult(content=f"Não encontrei a imagem '{image_id}' nesta conversa. Gere uma nova imagem.")

        try:
            generated = self.backend.edit(
                source, source_mime, prompt, size=self.settings.size, quality=self.settings.quality
            )
        except Exception as exc:
            log_error(f"image edit failed ({self.settings.provider}/{self.settings.model}): {exc}")
            return ToolResult(content=f"Falha ao editar a imagem: {exc}")
        return self._store(generated, prompt, run_context, message="Imagem editada com sucesso", parent_id=image_id)

    # -- Helpers -----------------------------------------------------------
    @staticmethod
    def _last_image_id(run_context: RunContext | None) -> str | None:
        if run_context is None or not isinstance(run_context.session_state, dict):
            return None
        value = run_context.session_state.get(SESSION_LAST_IMAGE_KEY)
        return str(value) if value else None

    def _load_generated(self, image_id: str) -> tuple[bytes | None, str]:
        for mime in ("image/png", "image/jpeg", "image/webp"):
            key = storage_key_for(image_id, mime)
            try:
                if not self.storage.exists(key):
                    continue
                return self.storage.download(key), mime
            except Exception as exc:
                log_error(f"could not load generated image {key}: {exc}")
                return None, mime
        return None, "image/png"

    def _store(
        self,
        generated: GeneratedImage,
        prompt: str,
        run_context: RunContext | None,
        *,
        message: str,
        parent_id: str | None = None,
    ) -> ToolResult:
        image_id = uuid4().hex
        fmt = sniff_image_format(generated.content) or "png"
        mime_type = MIME_BY_FORMAT.get(fmt, generated.mime_type)
        metadata: dict[str, Any] = {"prompt": prompt, "provider": self.settings.provider, "model": self.settings.model}
        if parent_id:
            metadata["parent_image_id"] = parent_id

        try:
            storage_key = self.storage.upload(
                f"{STORAGE_PREFIX}{image_id}", generated.content, mime_type=mime_type, metadata=metadata
            )
            url = self.storage.get_url(storage_key)
        except Exception as exc:
            log_error(f"could not persist generated image: {exc}")
            return ToolResult(content=f"A imagem foi gerada, mas não pôde ser salva no storage: {exc}")

        reference = MediaReference(
            media_id=image_id,
            storage_key=storage_key,
            storage_backend=getattr(self.storage, "backend_name", "local"),
            bucket=getattr(self.storage, "bucket", None),
            region=getattr(self.storage, "region", None),
            url=url,
            mime_type=mime_type,
            size=len(generated.content),
            content_hash=hashlib.sha256(generated.content).hexdigest(),
            media_type="image",
            metadata=metadata,
        )
        image = Image(
            id=image_id,
            content=generated.content,
            url=url,
            format=fmt,
            mime_type=mime_type,
            original_prompt=prompt,
            revised_prompt=generated.revised_prompt,
            media_reference=reference,
            metadata=metadata,
        )

        if run_context is not None and isinstance(run_context.session_state, dict):
            run_context.session_state[SESSION_LAST_IMAGE_KEY] = image_id
        log_info(f"{message}: {storage_key}")

        content = f"{message}. image_id: {image_id}."
        if url:
            content += f" URL: {url}."
        content += (
            " A imagem já está anexada à resposta. Para ajustá-la, chame edit_image (sem image_id usa esta imagem)."
        )
        return ToolResult(content=content, images=[image])
