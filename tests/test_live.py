"""
Live tests — call the real model providers and the database.

Run with real keys and a reachable Postgres:

    PEMILL_LIVE_TESTS=1 python -m pytest tests/test_live.py -v

Each test uses a fresh session id so nothing leaks between runs.
"""

from uuid import uuid4

import pytest
from agno.media import Image

from app.media_samples import solid_color_png

pytestmark = pytest.mark.live


@pytest.fixture
def agent():
    from agents.assistente_pemill import assistente_pemill

    return assistente_pemill


def test_conversa_simples_em_portugues(agent):
    response = agent.run(
        "Olá! Quem é você?",
        user_id="pytest-live",
        session_id=f"pytest-{uuid4().hex}",
    )
    content = str(response.content)
    assert "Pemill" in content
    assert any(word in content.lower() for word in ("assistente", "ajudar", "posso"))


def test_analise_de_imagem(agent):
    response = agent.run(
        "Qual é a cor predominante desta imagem? Responda em uma frase.",
        images=[Image(content=solid_color_png(64, 64, (220, 20, 20)), format="png", mime_type="image/png")],
        user_id="pytest-live",
        session_id=f"pytest-{uuid4().hex}",
    )
    assert "vermelh" in str(response.content).lower()


def test_pedido_de_geracao_de_imagem(agent):
    response = agent.run(
        "Gere uma imagem simples de um círculo azul em fundo branco.",
        user_id="pytest-live",
        session_id=f"pytest-{uuid4().hex}",
    )
    tool_names = {tool.tool_name for tool in response.tools or []}
    assert "generate_image" in tool_names
    assert response.images, "the generated image must be attached to the run output"
    assert response.images[0].media_reference is not None
