"""
URL Guard
=========

Keeps the web tools (page reader and browser) on the public internet. A user, or a page the
agent is reading, could otherwise point them at `localhost`, the database container, a cloud
metadata endpoint or anything else reachable only from inside the server (SSRF).

`check_public_url` accepts a URL only when it is http(s), carries no credentials, names a
public-looking host and every address that host resolves to is globally routable. Callers
re-check on every redirect hop and, in the browser, on every request the page makes.

The browser goes further: all its traffic leaves through `app.guarded_proxy`, which connects
to the very address returned by `public_addresses`. The page reader checks the URL and lets
httpx resolve the name again, so a DNS record that changes between the two (DNS rebinding)
is not covered there.
"""

import ipaddress
import socket
import time
from collections.abc import Callable, Iterable
from threading import Lock
from urllib.parse import urlsplit

ALLOWED_SCHEMES = ("http", "https")
INTERNAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".intranet", ".corp", ".arpa")
CACHE_SECONDS = 60.0
CACHE_MAX_ENTRIES = 512

Resolver = Callable[[str], Iterable[str]]


class BlockedUrlError(ValueError):
    """The URL is not allowed; the message is safe to show to the model and the user."""


def _resolve(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _is_public_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])  # drop an IPv6 zone id
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = ip.ipv4_mapped or ip.sixtofour or (ip.teredo[1] if ip.teredo else None)
        if embedded is not None:
            return embedded.is_global
    return ip.is_global


_cache: dict[str, tuple[float, list[str]]] = {}
_cache_lock = Lock()


def public_addresses(host: str, resolver: Resolver = _resolve) -> list[str]:
    """Addresses of `host` when all of them are public; raises `BlockedUrlError` otherwise.

    The web tools connect to one of the returned addresses, so what was checked is what is
    reached. Allowed hosts are cached for a minute.
    """
    host = host.strip().rstrip(".").lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    use_cache = resolver is _resolve
    now = time.monotonic()
    if use_cache:
        with _cache_lock:
            cached = _cache.get(host)
            if cached and now - cached[0] < CACHE_SECONDS:
                return list(cached[1])

    try:
        ipaddress.ip_address(host)
        addresses: list[str] = [host]
    except ValueError:
        if not host or host == "localhost" or host.endswith(INTERNAL_SUFFIXES) or "." not in host:
            raise BlockedUrlError(f"'{host}' é um endereço interno") from None
        try:
            addresses = list(dict.fromkeys(resolver(host)))
        except OSError:
            addresses = []
        if not addresses:
            raise BlockedUrlError(f"não foi possível resolver o endereço '{host}'") from None
    if not all(_is_public_ip(address) for address in addresses):
        raise BlockedUrlError(f"'{host}' aponta para um endereço interno ou reservado")

    if use_cache:
        with _cache_lock:
            if len(_cache) >= CACHE_MAX_ENTRIES:
                _cache.clear()
            _cache[host] = (now, addresses)
    return addresses


def check_public_url(url: str, resolver: Resolver = _resolve) -> str:
    """Return the cleaned URL if it is a public http(s) address, else raise `BlockedUrlError`."""
    cleaned = (url or "").strip()
    try:
        parts = urlsplit(cleaned)
        host = (parts.hostname or "").rstrip(".").lower()
        _ = parts.port  # raises ValueError on a malformed port
    except ValueError:
        raise BlockedUrlError("URL inválida.") from None

    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise BlockedUrlError("Só são aceitas URLs http:// ou https://.")
    if not host:
        raise BlockedUrlError("URL inválida: falta o endereço do site.")
    if parts.username or parts.password:
        raise BlockedUrlError("URLs com usuário ou senha embutidos não são aceitas.")

    try:
        public_addresses(host, resolver)
    except BlockedUrlError as exc:
        raise BlockedUrlError(f"Acesso bloqueado: {exc}. Só sites públicos da internet podem ser abertos.") from None
    return cleaned


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
