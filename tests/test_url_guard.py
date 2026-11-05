"""URL guard: only public http(s) addresses pass. No test resolves a real name."""

import pytest

from app.url_guard import BlockedUrlError, check_public_url, public_addresses

PUBLIC = {"example.com": ["93.184.216.34"], "dual.example.com": ["93.184.216.34", "2606:2800:220:1::1"]}
TRAPS = {"rebind.example.com": ["93.184.216.34", "10.0.0.7"], "metadata.example.com": ["169.254.169.254"]}


def resolver(host: str) -> list[str]:
    table = {**PUBLIC, **TRAPS}
    if host not in table:
        raise OSError("unknown host")
    return table[host]


@pytest.mark.parametrize(
    "url",
    ["https://example.com/a?b=1", "http://example.com:8080/", " https://dual.example.com ", "https://93.184.216.34/"],
)
def test_public_urls_pass(url):
    assert check_public_url(url, resolver) == url.strip()


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/health",
        "http://127.0.0.1/",
        "http://10.1.2.3/admin",
        "http://172.16.0.1/",
        "http://192.168.0.10/",
        "http://100.64.0.1/",  # carrier-grade NAT
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[fe80::1]/",
        "http://[fd00::1]/",
        "http://[::ffff:10.0.0.1]/",  # IPv4-mapped private address
        "http://agentos-db:5432/",  # docker service name
        "http://printer.local/",
        "http://api.internal/",
        "http://rebind.example.com/",  # one public and one private address
        "http://metadata.example.com/",
        "http://unknown.example.org/",  # does not resolve
        "http://2130706433/",  # 127.0.0.1 written as an integer
    ],
)
def test_internal_addresses_are_blocked(url):
    with pytest.raises(BlockedUrlError):
        check_public_url(url, resolver)


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "ftp://example.com/", "javascript:alert(1)", "example.com", "", "http://", "http://a:b@x"],
)
def test_other_schemes_and_malformed_urls_are_blocked(url):
    with pytest.raises(BlockedUrlError):
        check_public_url(url, resolver)


def test_credentials_in_url_are_blocked():
    with pytest.raises(BlockedUrlError, match="usuário ou senha"):
        check_public_url("https://user:secret@example.com/", resolver)


def test_public_addresses_returns_what_was_checked():
    assert public_addresses("Example.com.", resolver) == ["93.184.216.34"]
    assert public_addresses("[2606:2800:220:1::1]", resolver) == ["2606:2800:220:1::1"]
    with pytest.raises(BlockedUrlError):
        public_addresses("rebind.example.com", resolver)
