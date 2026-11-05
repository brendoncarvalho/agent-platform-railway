"""End-to-end check of the Time TI against the local stub: delegation, image generation and edit.

Run the stub first (`python tests/e2e_stub/openai_stub.py 8099`), then this script with the same
environment as `e2e_check.py` plus `TI_TEAM_MEMORY=false` (see README).
"""

import json
import sys
from uuid import uuid4

import httpx

from agents.ti_team import ti_team as team
from app.image_generation import STORAGE_PREFIX

STUB = "http://127.0.0.1:8099"
session = f"e2e-team-{uuid4().hex[:8]}"
user = "e2e@pemill.com.br"
ok = True

# The leader is an OpenRouter model; agno pins its base URL, so point it at the stub here.
team.model.base_url = f"{STUB}/v1"  # type: ignore[union-attr]
for member in team.members if isinstance(team.members, list) else []:
    if getattr(getattr(member, "model", None), "provider", "") == "OpenRouter":
        member.model.base_url = f"{STUB}/v1"  # type: ignore[union-attr]


def check(label, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + label + (f" — {detail}" if detail else ""))


def seen():
    return httpx.get(f"{STUB}/_seen").json()


def generated_images(run):
    return [i for i in (run.images or []) if i.media_reference is not None]


# 1. Pedido de imagem ao time: o líder delega e o membro gera
r1 = team.run("Gere uma imagem de um moinho pendular", user_id=user, session_id=session, stream=False)
log = seen()
leader_calls = [s for s in log if "delegate_task_to_member" in s.get("tools", [])]
check("delegação: líder recebeu a ferramenta de delegação", bool(leader_calls))
check(
    "delegação: líder chamou delegate_task_to_member",
    "delegate_task_to_member" in {t.tool_name for t in (r1.tools or [])},
)
check("geração: provedor de imagem acionado pelo membro", any("images.generate" in s for s in log))
images = generated_images(r1)
check(
    "geração: imagem chega na resposta do time com media_reference", bool(images), f"{len(r1.images or [])} imagem(ns)"
)
first_key = images[0].media_reference.storage_key if images else ""
check("geração: chave no padrão do storage", first_key.startswith(STORAGE_PREFIX), first_key)
check("geração: status COMPLETED", "completed" in str(r1.status).lower(), str(r1.status))

# 2. Ajuste na mesma conversa: o membro edita a imagem gerada
r2 = team.run("Deixe o fundo amarelo", user_id=user, session_id=session, stream=False)
edits = [s for s in seen() if "images.edit" in s]
check(
    "edição: provedor recebeu a imagem gerada como fonte",
    bool(edits) and edits[-1]["source_is_png"],
    json.dumps(edits[-1], ensure_ascii=False) if edits else "membro não encontrou a imagem anterior",
)
check("edição: nova imagem na resposta do time", bool(generated_images(r2)))

# 3. Persistência: a sessão do time guarda as imagens por referência
sess = team.get_session(session_id=session)
assert sess is not None, "team session not found in the database"
team_runs = [run for run in sess.runs or [] if getattr(run, "parent_run_id", None) is None]
check(
    "persistência: 2 execuções do time na sessão",
    len(team_runs) == 2,
    f"{len(team_runs)} do time, {len(sess.runs or [])} no total",
)

print("\nSESSION", session, "KEY", first_key)
print("RESULT:", "ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
