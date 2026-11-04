"""Minimal OpenAI-compatible stub: chat completions with tool calls + image generation/edit.

Lets the full agno pipeline (vision input, tool calling, media storage, session state) run
end to end without real API keys. Behaviour is keyed on the user's text.
"""

import base64
import json
import struct
import sys
import time
import uuid
import zlib

from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import JSONResponse

app = FastAPI()
SEEN: list[dict] = []  # every chat request, for assertions


def png(rgb=(0, 0, 255), size=16) -> bytes:
    def chunk(tag, payload):
        return (
            struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    raw = (b"\x00" + bytes(rgb) * size) * size
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _text_of(msg) -> str:
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _has_image(msg) -> bool:
    c = msg.get("content")
    return isinstance(c, list) and any(isinstance(p, dict) and p.get("type") == "image_url" for p in c)


def completion(content=None, tool_calls=None):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex[:12],
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "stub",
        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if tool_calls else "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    }


def tool_call(name, args):
    return [
        {
            "id": "call_" + uuid.uuid4().hex[:8],
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)},
        }
    ]


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    tools = [t["function"]["name"] for t in body.get("tools", []) if t.get("type") == "function"]
    SEEN.append(
        {
            "tools": tools,
            "n_messages": len(messages),
            "has_image": any(_has_image(m) for m in messages),
            "roles": [m.get("role") for m in messages][-4:],
        }
    )
    if body.get("stream"):
        return JSONResponse({"error": "stub does not stream"}, status_code=400)

    last_user: dict = next((m for m in reversed(messages) if m.get("role") == "user"), {})
    text = _text_of(last_user).lower()

    tool_after_user = [m for m in messages[-3:] if m.get("role") == "tool"]
    if tool_after_user:
        return completion(f"Pronto! {_text_of(tool_after_user[-1])[:80]} Quer algum ajuste?")
    if _has_image(last_user):
        return completion("A imagem mostra um quadrado vermelho sólido, sem outros elementos visíveis.")
    if "deixe" in text or "troque" in text:
        return completion(tool_calls=tool_call("edit_image", {"prompt": _text_of(last_user)}))
    if "gere" in text or "crie" in text:
        return completion(
            tool_calls=tool_call("generate_image", {"prompt": "ícone de caminhão azul, fundo branco, estilo flat"})
        )
    return completion(
        "Olá! Sou o Assistente Pemill, o assistente virtual da Pemill. Posso ajudar com dúvidas, textos e imagens."
    )


@app.post("/v1/images/generations")
async def generations(request: Request):
    body = await request.json()
    SEEN.append({"images.generate": body.get("model"), "prompt": body.get("prompt")})
    return {
        "created": int(time.time()),
        "data": [{"b64_json": base64.b64encode(png((0, 0, 255))).decode(), "revised_prompt": body.get("prompt")}],
    }


@app.post("/v1/images/edits")
async def edits(request: Request):
    form = await request.form()
    image = form.get("image")
    source = await image.read() if isinstance(image, UploadFile) else b""
    SEEN.append(
        {
            "images.edit": form.get("model"),
            "prompt": form.get("prompt"),
            "source_is_png": source.startswith(b"\x89PNG"),
            "source_len": len(source),
        }
    )
    return {"created": int(time.time()), "data": [{"b64_json": base64.b64encode(png((255, 255, 0))).decode()}]}


@app.get("/_seen")
async def seen():
    return SEEN


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8099, log_level="warning")
