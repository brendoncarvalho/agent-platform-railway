"""Browser tools against a real headless Chromium and a local test site.

The guard is replaced by a fake resolver: `site.test` is the "public" site (the local server)
and `intranet.test` plays an internal address that must never be reached — neither directly,
nor through a redirect, nor as an image inside a public page. Skipped where Chromium is not
installed (`playwright install --only-shell chromium`).
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from agno.run import RunContext
from agno.tools.function import ToolResult

from app.url_guard import BlockedUrlError
from app.web_browser import BrowserManager, BrowserSettings, BrowserTools, build_browser_tools

HOME = """<html><head><title>Loja Teste</title></head><body>
<h1>Bem-vindo</h1>
<a href="/produtos">Produtos</a>
<form action="/busca"><input name="q" placeholder="Buscar"><button type="submit">Ir</button></form>
<input type="password" name="senha" placeholder="Senha">
<div id="js"></div><script>document.getElementById('js').innerText = 'Renderizado por JavaScript';</script>
</body></html>"""
PRODUCTS = "<html><head><title>Produtos</title></head><body><h1>Moinho pendular MP-30</h1></body></html>"
WITH_IMAGE = (
    '<html><head><title>Imagem</title></head><body><img src="http://intranet.test:{port}/pixel">ok</body></html>'
)


class Site(BaseHTTPRequestHandler):
    hits: list[tuple[str, str]] = []  # (Host header, path)

    def log_message(self, *args):
        pass

    def do_GET(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        port = self.server.server_port  # type: ignore[attr-defined]
        Site.hits.append((host, self.path))
        if self.path == "/redirect-internal":
            self.send_response(302)
            self.send_header("Location", f"http://intranet.test:{port}/secret")
            self.end_headers()
            return
        if self.path.startswith("/busca"):
            body = f"<html><head><title>Busca</title></head><body>Resultado para {self.path}</body></html>"
        else:
            pages = {"/": HOME, "/produtos": PRODUCTS, "/imagem": WITH_IMAGE.format(port=port)}
            body = pages.get(self.path, "<html><body>segredo interno</body></html>")
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def fake_resolve(host: str) -> list[str]:
    if host == "site.test":
        return ["127.0.0.1"]
    raise BlockedUrlError(f"'{host}' é um endereço interno")


def fake_check(url: str) -> str:
    if "//site.test" in url or "/redirect-internal" in url:
        return url
    raise BlockedUrlError("Acesso bloqueado: endereço interno.")


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://site.test:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module")
def manager():
    settings = BrowserSettings(enabled=True, max_sessions=2, idle_seconds=300, max_steps=6, timeout=15, max_chars=20000)
    manager = BrowserManager(settings, resolve_host=fake_resolve, check_url=fake_check)
    probe = manager.submit(manager.run("probe", "probe", lambda session: _noop(), needs_page=False)).result(60)
    if isinstance(probe, str) and "navegador não" in probe:
        manager.close()
        pytest.skip("Chromium is not installed")
    yield manager
    manager.close()


async def _noop() -> str:
    return "ok"


@pytest.fixture
def tools(manager):
    Site.hits.clear()
    return BrowserTools(manager=manager)


def ctx(session: str, run: str = "run-1") -> RunContext:
    return RunContext(run_id=run, session_id=session)


def test_toolkit_registers_sync_and_async_tools(tools):
    names = {f"browser_{n}" for n in ("open", "click", "type", "scroll", "back", "read", "screenshot", "ask_user")}
    assert set(tools.functions) == names
    assert set(tools.async_functions) == names
    assert tools.async_functions["browser_open"].description == tools.functions["browser_open"].description


def test_open_click_back_and_read(tools, site):
    page = tools.browser_open(site + "/", run_context=ctx("a"))
    assert "Página: Loja Teste" in page
    assert "Renderizado por JavaScript" in page  # JavaScript ran
    assert "[1] link: Produtos" in page
    assert "campo de senha (bloqueado)" in page

    assert "Moinho pendular MP-30" in tools.browser_click(1, run_context=ctx("a"))
    assert "Página: Loja Teste" in tools.browser_back(run_context=ctx("a"))
    assert "Bem-vindo" in tools.browser_read(run_context=ctx("a"))


def test_type_in_search_and_refuse_password(tools, site):
    page = tools.browser_open(site + "/", run_context=ctx("b"))
    field = next(line for line in page.splitlines() if "Buscar" in line).split("]")[0].lstrip("[")
    secret = next(line for line in page.splitlines() if "senha" in line).split("]")[0].lstrip("[")

    assert "bloqueados" in tools.browser_type(int(secret), "hunter2", run_context=ctx("b"))
    result = tools.browser_type(int(field), "moinho", press_enter=True, run_context=ctx("b"))
    assert "Resultado para /busca?q=moinho" in result
    assert "não existe mais" in tools.browser_click(99, run_context=ctx("b"))


async def test_async_tools_and_screenshot(tools, site):
    assert "Loja Teste" in await tools.abrowser_open(site + "/", run_context=ctx("c"))
    assert "Página: Loja Teste" in await tools.abrowser_scroll("bottom", run_context=ctx("c"))
    assert "Direção inválida" in await tools.abrowser_scroll("sideways", run_context=ctx("c"))
    shot = await tools.abrowser_screenshot(run_context=ctx("c"))
    assert isinstance(shot, ToolResult) and shot.images
    assert (shot.images[0].content or b"")[:3] == b"\xff\xd8\xff"  # JPEG


def test_internal_addresses_are_never_reached(tools, site, manager):
    port = site.rsplit(":", 1)[1]
    assert "Acesso bloqueado" in tools.browser_open(f"http://intranet.test:{port}/secret", run_context=ctx("d"))

    # A public page that redirects to an internal one: the proxy refuses the second hop.
    redirected = tools.browser_open(site + "/redirect-internal", run_context=ctx("d"))
    assert "segredo interno" not in redirected
    assert "Não foi possível abrir" in redirected

    # A public page that embeds an internal image: the page loads, the image request is refused.
    assert "Página: Imagem" in tools.browser_open(site + "/imagem", run_context=ctx("d"))

    assert "intranet.test" in manager.proxy.blocked
    assert all(host == "site.test" for host, _ in Site.hits), Site.hits


def test_page_required_and_step_limit(tools, site):
    assert "Nenhuma página aberta" in tools.browser_read(run_context=ctx("e"))
    tools.browser_open(site + "/", run_context=ctx("e", "run-x"))
    results = [tools.browser_read(run_context=ctx("e", "run-x")) for _ in range(6)]
    assert "Limite de 6 ações" in results[-1]
    assert "Bem-vindo" in tools.browser_read(run_context=ctx("e", "run-y"))  # a new answer starts a new count


def test_sessions_are_isolated_and_capped(tools, site, manager):
    tools.browser_open(site + "/produtos", run_context=ctx("f1"))
    tools.browser_open(site + "/", run_context=ctx("f2"))
    assert "Moinho pendular MP-30" in tools.browser_read(run_context=ctx("f1"))
    tools.browser_open(site + "/", run_context=ctx("f3"))  # third session evicts the least recently used
    assert len(manager._sessions) <= 2


def test_switch_off(monkeypatch):
    assert isinstance(build_browser_tools(), BrowserTools)
    monkeypatch.setenv("BROWSER", "false")
    assert build_browser_tools() is None


# ---------------------------------------------------------------------------
# Live view: the session owner watches and operates the agent's browser
# ---------------------------------------------------------------------------
def user_ctx(session: str, user: str, run: str = "run-1") -> RunContext:
    return RunContext(run_id=run, session_id=session, user_id=user)


@pytest.fixture
def live(manager):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.browser_live import browser_live_router

    app = FastAPI()
    app.include_router(browser_live_router(manager))
    return TestClient(app)


def test_live_view_is_only_for_the_session_owner(tools, site, live):
    tools.browser_open(site + "/", run_context=user_ctx("live-1", "ana@pemill.com.br"))

    status = live.get("/browser/sessions/live-1", params={"user_id": "ana@pemill.com.br"}).json()
    assert status["open"] is True and status["title"] == "Loja Teste"
    assert (status["width"], status["height"]) == (1280, 800)

    frame = live.get("/browser/sessions/live-1/frame", params={"user_id": "ana@pemill.com.br"})
    assert frame.status_code == 200 and frame.headers["content-type"] == "image/jpeg"
    assert frame.content[:3] == b"\xff\xd8\xff" and frame.headers["cache-control"] == "no-store"

    # Another user, an unknown session and a missing user all look like "nothing open".
    assert live.get("/browser/sessions/live-1", params={"user_id": "outro@pemill.com.br"}).json() == {"open": False}
    assert live.get("/browser/sessions/live-1/frame", params={"user_id": "outro@pemill.com.br"}).status_code == 404
    assert live.get("/browser/sessions/nao-existe/frame", params={"user_id": "ana@pemill.com.br"}).status_code == 404
    assert live.get("/browser/sessions/live-1/frame").status_code == 422
    blocked = live.post(
        "/browser/sessions/live-1/input", params={"user_id": "outro@pemill.com.br"}, json={"type": "reload"}
    )
    assert blocked.status_code == 404


def test_live_view_never_starts_a_browser(live, manager):
    before = set(manager._sessions)
    assert live.get("/browser/sessions/fresh", params={"user_id": "ana@pemill.com.br"}).json() == {"open": False}
    assert set(manager._sessions) == before


def test_user_logs_in_through_the_live_view(tools, site, live, manager):
    ana = {"user_id": "ana@pemill.com.br"}
    context = user_ctx("live-2", "ana@pemill.com.br")
    page = tools.browser_open(site + "/", run_context=context)
    secret_ref = next(line for line in page.splitlines() if "senha" in line).split("]")[0].lstrip("[")

    handed_over = tools.browser_ask_user("O site pede a senha", run_context=context)
    assert "Navegador ao vivo" in handed_over
    assert live.get("/browser/sessions/live-2", params=ana).json()["waiting_for_user"] == "O site pede a senha"

    # The user clicks the password field in the picture and types; the agent never sees the text.
    box = manager.submit(
        manager._sessions["live-2"].page.locator(f'[data-pemill-ref="{secret_ref}"]').bounding_box()
    ).result(15)
    click = {"type": "click", "x": box["x"] + box["width"] / 2, "y": box["y"] + box["height"] / 2}
    assert live.post("/browser/sessions/live-2/input", params=ana, json=click).json()["ok"] is True
    assert live.post("/browser/sessions/live-2/input", params=ana, json={"type": "type", "text": "s3gredo"}).json()[
        "ok"
    ]
    assert live.post("/browser/sessions/live-2/input", params=ana, json={"type": "key", "key": "Tab"}).json()["ok"]

    typed = manager.submit(manager._sessions["live-2"].page.locator("input[type=password]").input_value()).result(15)
    assert typed == "s3gredo"
    assert "s3gredo" not in tools.browser_read(run_context=context)
    assert "s3gredo" not in tools.browser_scroll("top", run_context=context)

    assert live.post("/browser/sessions/live-2/input", params=ana, json={"type": "done"}).json()["ok"] is True
    assert live.get("/browser/sessions/live-2", params=ana).json()["waiting_for_user"] is None


def test_live_input_is_validated(tools, site, live):
    ana = {"user_id": "ana@pemill.com.br"}
    tools.browser_open(site + "/", run_context=user_ctx("live-3", "ana@pemill.com.br"))
    url = "/browser/sessions/live-3/input"
    assert live.post(url, params=ana, json={"type": "eval", "text": "alert(1)"}).status_code == 422
    assert live.post(url, params=ana, json={"type": "type", "text": "x" * 501}).status_code == 422
    assert live.post(url, params=ana, json={"type": "key", "key": "F12"}).json() == {"ok": False, "error": "key"}
    assert live.post(url, params=ana, json={"type": "scroll", "dy": 99999}).json()["ok"] is True
    assert live.post(url, params=ana, json={"type": "click", "x": -50, "y": 99999}).json()["ok"] is True
