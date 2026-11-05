"""Page reader: extraction, limits and the guard on every redirect hop. httpx is mocked."""

import httpx

from app.url_guard import BlockedUrlError
from app.web_reader import EMPTY_PAGE_HINT, WebReaderTools, build_web_reader_tools, clip

ARTICLE = """<html><head><title>Moinho pendular</title></head><body>
<nav><a href="/">Início</a><a href="/contato">Contato</a></nav>
<article><h1>Moinho pendular</h1>
<p>O moinho pendular é usado na moagem fina de minerais não metálicos, como calcário e caulim.</p>
<p>A classificação do produto é feita por um separador dinâmico instalado sobre a câmara de moagem.</p>
</article><footer>Rodapé do site</footer></body></html>"""


def guard(url: str) -> str:
    if "internal" in url or "127.0.0.1" in url:
        raise BlockedUrlError("Acesso bloqueado: endereço interno.")
    return url


def reader(handler, **kwargs) -> WebReaderTools:
    return WebReaderTools(transport=httpx.MockTransport(handler), check_url=guard, **kwargs)


def html(body: str, status: int = 200, **headers) -> httpx.Response:
    return httpx.Response(status, headers={"content-type": "text/html; charset=utf-8", **headers}, text=body)


def test_reads_title_and_main_text():
    result = reader(lambda request: html(ARTICLE)).read_web_page("https://site.test/moinho")
    assert result.startswith("URL: https://site.test/moinho\nTítulo: Moinho pendular")
    assert "moagem fina de minerais" in result
    assert "Rodapé do site" not in result


async def test_async_variant_is_registered_and_works():
    tools = reader(lambda request: html(ARTICLE))
    assert set(tools.functions) == {"read_web_page"}
    assert set(tools.async_functions) == {"read_web_page"}
    assert tools.async_functions["read_web_page"].description == tools.functions["read_web_page"].description
    assert "separador dinâmico" in await tools.aread_web_page("https://site.test/moinho")


def test_follows_redirects_and_reports_the_final_url():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        return html(ARTICLE)

    assert reader(handler).read_web_page("https://site.test/old").startswith("URL: https://site.test/new")


def test_redirect_to_an_internal_address_is_blocked():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://internal.test/admin"})

    result = reader(handler).read_web_page("https://site.test/go")
    assert "Acesso bloqueado" in result
    assert seen == ["https://site.test/go"]  # the internal address was never requested


def test_blocked_url_never_leaves_the_server():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return html(ARTICLE)

    result = reader(handler).read_web_page("http://127.0.0.1/")
    assert "Acesso bloqueado" in result and not seen


def test_redirect_loop_gives_up():
    result = reader(lambda request: httpx.Response(302, headers={"location": "/again"})).read_web_page(
        "https://site.test/loop"
    )
    assert "redirecionamentos demais" in result


def test_errors_and_unsupported_content_are_reported_as_text():
    assert "erro HTTP 404" in reader(lambda request: html("nope", 404)).read_web_page("https://site.test/x")

    pdf = httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.7")
    assert "application/pdf" in reader(lambda request: pdf).read_web_page("https://site.test/x.pdf")

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    assert "não respondeu" in reader(timeout).read_web_page("https://site.test/slow")


def test_javascript_only_page_points_to_the_browser():
    shell = (
        "<html><head><title>App</title></head><body><div id='root'></div><script src='/app.js'></script></body></html>"
    )
    assert reader(lambda request: html(shell)).read_web_page("https://site.test/app") == EMPTY_PAGE_HINT


def test_long_pages_are_cut():
    paragraphs = "".join(f"<p>Parágrafo número {i} sobre moagem de minerais e classificação.</p>" for i in range(400))
    page = f"<html><body><article><h1>Longo</h1>{paragraphs}</article></body></html>"
    result = reader(lambda request: html(page), max_chars=1000).read_web_page("https://site.test/longo")
    assert "[Texto cortado em 1000 de" in result
    assert len(result) < 1300
    assert clip("curto", 1000) == "curto"


def test_plain_text_is_returned_as_is():
    response = httpx.Response(200, headers={"content-type": "text/plain"}, text="linha 1\nlinha 2")
    assert reader(lambda request: response).read_web_page("https://site.test/a.txt").endswith("linha 1\nlinha 2")


def test_switch_off(monkeypatch):
    assert isinstance(build_web_reader_tools(), WebReaderTools)
    monkeypatch.setenv("WEB_READER", "false")
    assert build_web_reader_tools() is None
