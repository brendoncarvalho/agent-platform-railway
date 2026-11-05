"""Web search wiring: env settings, result cap, fallback engine and failures reported as text.

No test reaches a search engine: `ddgs.DDGS` is replaced by a fake that records the calls.
"""

import importlib
import json

import pytest

import app.web_search as web_search
from app.web_search import PemillWebSearchTools, build_web_search_tools, web_search_settings


class FakeDDGS:
    """Stands in for `ddgs.DDGS`; `failing` lists the backends that raise."""

    calls: list[dict] = []
    failing: set[str] = set()

    def __init__(self, **kwargs):
        self.init_kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _run(self, kind: str, **kwargs):
        FakeDDGS.calls.append({"kind": kind, **kwargs})
        if kwargs["backend"] in FakeDDGS.failing:
            raise RuntimeError("No results found.")
        return [{"title": "Dólar hoje", "href": "https://example.com/dolar", "body": "Cotação"}]

    def text(self, **kwargs):
        return self._run("web", **kwargs)

    def news(self, **kwargs):
        return self._run("news", **kwargs)


@pytest.fixture
def fake_ddgs(monkeypatch):
    FakeDDGS.calls = []
    FakeDDGS.failing = set()
    monkeypatch.setattr("agno.tools.websearch.DDGS", FakeDDGS)
    return FakeDDGS


def test_defaults(monkeypatch):
    for name in ("WEB_SEARCH", "WEB_SEARCH_BACKEND", "WEB_SEARCH_REGION", "WEB_SEARCH_MAX_RESULTS"):
        monkeypatch.delenv(name, raising=False)
    settings = web_search_settings()
    assert settings.enabled is True
    assert (settings.backend, settings.region, settings.max_results) == ("google", "br-pt", 5)

    tools = build_web_search_tools()
    assert isinstance(tools, PemillWebSearchTools)
    assert set(tools.functions) == {"web_search", "search_news"}


def test_env_overrides_and_switch_off(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_BACKEND", " DuckDuckGo ")
    monkeypatch.setenv("WEB_SEARCH_REGION", "us-en")
    monkeypatch.setenv("WEB_SEARCH_MAX_RESULTS", "0")  # never below 1
    tools = build_web_search_tools()
    assert tools is not None
    assert (tools.backend, tools.region, tools.max_results) == ("duckduckgo", "us-en", 1)

    monkeypatch.setenv("WEB_SEARCH", "false")
    assert build_web_search_tools() is None


def test_search_uses_backend_region_and_caps_results(fake_ddgs):
    tools = PemillWebSearchTools(backend="google", region="br-pt", max_results=3)
    result = json.loads(tools.web_search("cotação do dólar", max_results=50))
    assert result[0]["href"] == "https://example.com/dolar"
    assert fake_ddgs.calls == [
        {"kind": "web", "query": "cotação do dólar", "max_results": 3, "backend": "google", "region": "br-pt"}
    ]


def test_news_search(fake_ddgs):
    tools = PemillWebSearchTools(backend="google", max_results=5)
    assert json.loads(tools.search_news("Pemill", max_results=2))
    assert fake_ddgs.calls[0]["kind"] == "news"
    assert fake_ddgs.calls[0]["max_results"] == 2


def test_falls_back_to_auto_and_restores_backend(fake_ddgs):
    fake_ddgs.failing = {"google"}
    tools = PemillWebSearchTools(backend="google", max_results=5)
    assert json.loads(tools.web_search("agno"))
    assert [call["backend"] for call in fake_ddgs.calls] == ["google", "auto"]
    assert tools.backend == "google"


def test_failure_is_reported_as_text(fake_ddgs):
    fake_ddgs.failing = {"google", "auto"}
    tools = PemillWebSearchTools(backend="google", max_results=5)
    message = tools.web_search("agno")
    assert "não retornou resultados" in message
    assert len(fake_ddgs.calls) == 2

    fake_ddgs.calls.clear()
    assert "não retornou resultados" in PemillWebSearchTools(backend="auto").search_news("agno")
    assert len(fake_ddgs.calls) == 1  # `auto` has no further fallback


def test_assistant_has_web_search_and_can_lose_it(monkeypatch):
    import agents.assistente_pemill as module

    def tool_names(agent):
        return {name for toolkit in agent.tools or [] for name in getattr(toolkit, "functions", {})}

    assert {"web_search", "search_news", "generate_image"} <= tool_names(module.assistente_pemill)
    assert "Pesquisa na web" in str(module.assistente_pemill.instructions)
    assert "pesquisa na web" in (module.assistente_pemill.role or "")

    monkeypatch.setenv("WEB_SEARCH", "false")
    reloaded = importlib.reload(module)
    try:
        names = tool_names(reloaded.assistente_pemill)
        assert "web_search" not in names and "generate_image" in names
    finally:
        monkeypatch.delenv("WEB_SEARCH")
        importlib.reload(module)


def test_registry_offers_web_search_to_portal_agents():
    from app.registry import registry

    assert any(isinstance(tool, web_search.PemillWebSearchTools) for tool in registry.tools or [])


def test_team_routes_web_research_to_the_assistant():
    from agents.ti_team import INSTRUCTIONS

    text = " ".join(INSTRUCTIONS).lower()
    assert "pesquisa na web" in text and "links das fontes" in text


def test_assistant_registry_and_team_have_the_page_tools():
    from agents.assistente_pemill import assistente_pemill
    from agents.ti_team import INSTRUCTIONS
    from app.registry import registry
    from app.web_browser import BrowserTools
    from app.web_reader import WebReaderTools

    tools = assistente_pemill.tools if isinstance(assistente_pemill.tools, list) else []
    names = {name for toolkit in tools for name in getattr(toolkit, "functions", {})}
    assert {"read_web_page", "browser_open", "browser_click", "browser_screenshot"} <= names
    assert "browser_open" in str(assistente_pemill.instructions)
    assert "navegador" in (assistente_pemill.description or "")
    for kind in (WebReaderTools, BrowserTools):
        assert any(isinstance(tool, kind) for tool in registry.tools or [])
    assert "navegador" in " ".join(INSTRUCTIONS).lower()
