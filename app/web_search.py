"""
Web Search
==========

Web and news search for the agents, built on agno's `WebSearchTools` (the `ddgs` meta-search
library: no API key, results scraped from the chosen search engine).

Configuration (see `example.env`):
- WEB_SEARCH — turns the tools on/off (default on).
- WEB_SEARCH_BACKEND — search engine: google (default), duckduckgo, bing, brave, auto...
- WEB_SEARCH_REGION — region/language of the results (default br-pt).
- WEB_SEARCH_MAX_RESULTS — cap on results per search (default 5).
- WEB_SEARCH_TIMEOUT — seconds to wait for the search engine (default 15).
"""

from dataclasses import dataclass
from os import getenv

from agno.tools.websearch import WebSearchTools
from agno.utils.log import log_warning

from app.settings import env_flag, env_int

DEFAULT_BACKEND = "google"
FALLBACK_BACKEND = "auto"
DEFAULT_REGION = "br-pt"


@dataclass(frozen=True)
class WebSearchSettings:
    enabled: bool
    backend: str
    region: str
    max_results: int
    timeout: int


def web_search_settings() -> WebSearchSettings:
    return WebSearchSettings(
        enabled=env_flag("WEB_SEARCH", True),
        backend=(getenv("WEB_SEARCH_BACKEND") or DEFAULT_BACKEND).strip().lower(),
        region=(getenv("WEB_SEARCH_REGION") or DEFAULT_REGION).strip().lower(),
        max_results=max(1, env_int("WEB_SEARCH_MAX_RESULTS", 5)),
        timeout=max(1, env_int("WEB_SEARCH_TIMEOUT", 15)),
    )


class PemillWebSearchTools(WebSearchTools):
    """`WebSearchTools` with a result cap, a fallback engine and failures reported as text.

    Scraped engines block or change now and then. Instead of raising (which ends the tool call
    with a stack trace for the model), a failed search retries once on `FALLBACK_BACKEND` and,
    if that also fails, returns a short message the model can relay to the user.
    """

    def __init__(self, max_results: int = 5, **kwargs):
        self.max_results = max_results
        super().__init__(**kwargs)

    def _search(self, kind: str, query: str, max_results: int) -> str:
        search = WebSearchTools.web_search if kind == "web" else WebSearchTools.search_news
        limit = max(1, min(max_results, self.max_results))
        configured = self.backend
        backends = [configured] if configured == FALLBACK_BACKEND else [configured, FALLBACK_BACKEND]
        try:
            for backend in backends:
                self.backend = backend
                try:
                    return search(self, query, limit)
                except Exception as exc:  # ddgs raises on blocks, timeouts and empty result pages
                    log_warning(f"Web search ({kind}) failed on backend '{backend}': {exc}")
        finally:
            self.backend = configured
        return (
            "A busca na web não retornou resultados agora (sem resultados ou buscador indisponível). "
            "Avise o usuário e, se fizer sentido, tente de novo com outros termos."
        )

    def web_search(self, query: str, max_results: int = 5) -> str:
        """Pesquisa na web e devolve título, link e resumo de cada resultado.

        Use para fatos atuais ou que podem ter mudado: notícias, cotações, preços, versões de
        software, documentação, legislação, eventos e qualquer dado posterior ao seu conhecimento.

        Args:
            query (str): Termos da busca, como o usuário digitaria em um buscador.
            max_results (int): Quantidade máxima de resultados. Padrão 5.

        Returns:
            Lista JSON com `title`, `href` e `body` de cada resultado, ou um aviso se a busca falhar.
        """
        return self._search("web", query, max_results)

    def search_news(self, query: str, max_results: int = 5) -> str:
        """Busca notícias recentes sobre um assunto.

        Args:
            query (str): Assunto da notícia.
            max_results (int): Quantidade máxima de notícias. Padrão 5.

        Returns:
            Lista JSON com data, título, fonte, link e resumo de cada notícia, ou um aviso se a busca falhar.
        """
        return self._search("news", query, max_results)


def build_web_search_tools() -> PemillWebSearchTools | None:
    """Web search toolkit for an agent, or `None` when `WEB_SEARCH` is off."""
    settings = web_search_settings()
    if not settings.enabled:
        return None
    return PemillWebSearchTools(
        backend=settings.backend,
        region=settings.region,
        timeout=settings.timeout,
        max_results=settings.max_results,
    )
