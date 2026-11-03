"""End-to-end check of Assistente Pemill against the local OpenAI-compatible stub."""

import json
import sys
from uuid import uuid4

import httpx
from agno.media import Image

from agents.assistente_pemill import assistente_pemill as agent
from app.image_generation import SESSION_LAST_IMAGE_KEY
from app.media_samples import solid_color_png

STUB = "http://127.0.0.1:8099"
session = f"e2e-{uuid4().hex[:8]}"
user = "e2e@pemill.com.br"
ok = True


def check(label, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + label + (f" — {detail}" if detail else ""))


# 1. Conversa simples
r1 = agent.run("Olá! Quem é você?", user_id=user, session_id=session, stream=False)
check("conversa: resposta identifica a Pemill", "Pemill" in str(r1.content), str(r1.content)[:90])
check("conversa: status COMPLETED", "completed" in str(r1.status).lower(), str(r1.status))

# 2. Análise de imagem (PNG vermelho)
r2 = agent.run(
    "Qual é a cor predominante desta imagem?",
    images=[Image(content=solid_color_png(32, 32, (220, 20, 20)), format="png", mime_type="image/png")],
    user_id=user,
    session_id=session,
    stream=False,
)
seen = httpx.get(f"{STUB}/_seen").json()
check("imagem: modelo recebeu a imagem (image_url no payload)", any(s.get("has_image") for s in seen))
check("imagem: resposta descreve vermelho", "vermelho" in str(r2.content).lower(), str(r2.content)[:90])
check(
    "imagem: histórico incluído (>1 user msg no contexto)",
    seen[-1]["n_messages"] >= 3,
    f"{seen[-1]['n_messages']} msgs",
)

# 3. Geração de imagem
r3 = agent.run("Gere uma imagem de um caminhão azul", user_id=user, session_id=session, stream=False)
seen = httpx.get(f"{STUB}/_seen").json()
gen = [s for s in seen if "images.generate" in s]
tool_names = {t.tool_name for t in (r3.tools or [])}
check("geração: generate_image chamado", "generate_image" in tool_names, str(tool_names))
check("geração: provedor de imagem acionado", bool(gen), json.dumps(gen[-1], ensure_ascii=False) if gen else "")
check("geração: imagem anexada ao run output", bool(r3.images), f"{len(r3.images or [])} imagem(ns)")
img = r3.images[0] if r3.images else None
check(
    "geração: media_reference presente (storage persistente)",
    img is not None and img.media_reference is not None,
    img.media_reference.storage_key if img and img.media_reference else "",
)
check("geração: resposta final em pt-BR após a ferramenta", "Pronto" in str(r3.content), str(r3.content)[:90])

# 4. Edição da última imagem na mesma conversa
r4 = agent.run("Deixe o fundo amarelo", user_id=user, session_id=session, stream=False)
seen = httpx.get(f"{STUB}/_seen").json()
edits = [s for s in seen if "images.edit" in s]
tool_names = {t.tool_name for t in (r4.tools or [])}
check("edição: edit_image chamado", "edit_image" in tool_names, str(tool_names))
check(
    "edição: fonte enviada ao provedor é a imagem gerada (PNG)",
    bool(edits) and edits[-1]["source_is_png"],
    json.dumps(edits[-1], ensure_ascii=False) if edits else "",
)
img2 = r4.images[0] if r4.images else None
check("edição: resposta final após a ferramenta", "Pronto" in str(r4.content), str(r4.content)[:90])
check(
    "edição: nova imagem com parent_image_id",
    img2 is not None and (img2.metadata or {}).get("parent_image_id") == (img.id if img else None),
)

# 5. Persistência: sessão no Postgres com runs e estado
sess = agent.get_session(session_id=session)
assert sess is not None, "session not found in the database"
runs = sess.runs or []
check("persistência: 4 runs salvos na sessão", len(runs) == 4, f"{len(runs)} runs")
state = sess.session_data.get("session_state", {}) if sess.session_data else {}
check(
    "persistência: último image_id guardado no session_state",
    state.get(SESSION_LAST_IMAGE_KEY) == (img2.id if img2 else None),
)
stored = [i for run in runs for i in (getattr(run, "images", None) or [])]
check(
    "persistência: imagens dos runs salvas com media_reference (sem base64 no banco)",
    stored and all(i.media_reference is not None and i.content is None for i in stored),
    f"{len(stored)} imagens",
)

print("\nRESULT:", "ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
