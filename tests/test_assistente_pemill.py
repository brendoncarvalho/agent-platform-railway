"""Assistente Pemill wiring: configuration, registration in AgentOS and absence of template agents."""

from pathlib import Path

import yaml

from app.image_generation import ImageGenerationTools
from app.image_input import ImageInputGuardrail

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_IDS = {"agent-builder", "platform-manager", "general-chat", "web-search", "code-search"}
TEMPLATE_WORKFLOWS = {"deployment-check", "run-evals"}


def test_agent_configuration():
    from agents.assistente_pemill import assistente_pemill as agent

    assert agent.id == "assistente-pemill"
    assert agent.name == "Assistente Pemill"
    assert agent.markdown is True
    assert agent.add_history_to_context is True
    assert agent.num_history_runs and agent.num_history_runs > 0
    assert agent.db is not None
    assert agent.media_storage is not None
    assert agent.learning is not None  # memory enabled by default

    instructions = str(agent.instructions)
    assert "Pemill" in instructions
    assert "português do Brasil" in instructions

    tools = agent.tools or []
    assert isinstance(tools, list)
    assert any(isinstance(tool, ImageGenerationTools) for tool in tools)
    assert any(isinstance(hook, ImageInputGuardrail) for hook in agent.pre_hooks or [])
    tool_names = {name for toolkit in tools for name in getattr(toolkit, "functions", {})}
    assert {"generate_image", "edit_image"} <= tool_names


def test_memory_can_be_disabled_by_env(monkeypatch):
    import importlib

    import agents.assistente_pemill as module

    monkeypatch.setenv("ASSISTENTE_PEMILL_MEMORY", "false")
    monkeypatch.setenv("ASSISTENTE_PEMILL_HISTORY_RUNS", "3")
    reloaded = importlib.reload(module)
    try:
        assert reloaded.assistente_pemill.learning is None
        assert reloaded.assistente_pemill.num_history_runs == 3
    finally:
        monkeypatch.delenv("ASSISTENTE_PEMILL_MEMORY")
        monkeypatch.delenv("ASSISTENTE_PEMILL_HISTORY_RUNS")
        importlib.reload(module)


def test_registered_in_agentos_without_template_components():
    from app.main import agent_os

    agent_ids = {agent.id for agent in agent_os.agents or []}
    team_ids = {team.id for team in agent_os.teams or []}
    workflow_ids = {workflow.id for workflow in agent_os.workflows or []}

    assert "assistente-pemill" in agent_ids
    assert agent_ids.isdisjoint(TEMPLATE_IDS)
    assert workflow_ids.isdisjoint(TEMPLATE_WORKFLOWS)
    assert "ti-team" in team_ids
    assert agent_os.media_storage is not None


def test_config_manifest_matches_registered_components():
    from app.main import agent_os

    manifest = yaml.safe_load((REPO_ROOT / "app" / "config.yaml").read_text(encoding="utf-8"))["manifest"]
    registered = {a.id for a in agent_os.agents or []} | {t.id for t in agent_os.teams or []}
    assert set(manifest) == registered
    assert "imagens" in manifest["assistente-pemill"]["description"]


def test_template_files_are_gone():
    for name in ("agent_builder", "platform_manager", "general_chat", "web_search", "code_search"):
        assert not (REPO_ROOT / "agents" / f"{name}.py").exists(), name
    assert not (REPO_ROOT / "workflows").exists()
    assert not (REPO_ROOT / "app" / "schedules.py").exists()
    assert not (REPO_ROOT / "app" / "web_tools.py").exists()


def test_chat_model_factory_respects_env(monkeypatch):
    from app.settings import chat_model

    monkeypatch.setenv("CHAT_MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("CHAT_MODEL_ID", "openai/gpt-4o-mini")
    model = chat_model(max_tokens=512)
    assert type(model).__name__ == "OpenRouter"
    assert model.id == "openai/gpt-4o-mini"
    assert getattr(model, "max_tokens") == 512

    monkeypatch.setenv("CHAT_MODEL_PROVIDER", "openai")
    monkeypatch.delenv("CHAT_MODEL_ID")
    model = chat_model()
    assert type(model).__name__ == "OpenAIChat"

    monkeypatch.setenv("CHAT_MODEL_PROVIDER", "nope")
    try:
        chat_model()
    except ValueError as exc:
        assert "CHAT_MODEL_PROVIDER" in str(exc)
    else:
        raise AssertionError("unsupported provider must raise")


def test_image_settings_defaults_and_overrides(monkeypatch):
    from app.settings import image_settings

    monkeypatch.delenv("IMAGE_PROVIDER", raising=False)
    monkeypatch.delenv("IMAGE_MODEL", raising=False)
    settings = image_settings()
    assert settings.provider == "openai" and settings.model == "gpt-image-1"
    assert settings.size == "1024x1024" and settings.quality is None

    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")
    monkeypatch.setenv("IMAGE_QUALITY", "high")
    monkeypatch.setenv("IMAGE_INPUT_MAX_MB", "4")
    settings = image_settings()
    assert settings.provider == "gemini" and settings.model.startswith("imagen")
    assert settings.quality == "high" and settings.input_max_mb == 4
