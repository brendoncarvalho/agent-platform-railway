"""
Guarded Proxy
=============

A minimal HTTP forward proxy on 127.0.0.1 that the agent's browser is forced to use. Every
connection the browser opens — navigation, redirects, images, scripts, XHR, WebSockets — asks
this proxy first, and the proxy only connects to hosts that `app.url_guard` says are public.
It connects to the address it has just checked, so a DNS answer that changes afterwards
(DNS rebinding) cannot redirect the browser to an internal service.

Checking URLs inside the browser instead is not enough: Chromium follows redirects on its own,
without giving the request interceptor a second look.

Supports `CONNECT host:port` (https, wss) and plain `GET http://host/...` requests.
"""

import asyncio
from collections.abc import Callable
from urllib.parse import urlsplit

from agno.utils.log import log_debug

from app.url_guard import BlockedUrlError, public_addresses

HEAD_TIMEOUT = 15.0
CONNECT_TIMEOUT = 15.0
MAX_HEAD_BYTES = 64 * 1024
BLOCKED_HEADER = "X-Pemill-Blocked"  # lets the browser tool tell a refusal from a site's own 403
HOP_HEADERS = ("proxy-connection", "proxy-authorization", "connection", "keep-alive")

HostResolver = Callable[[str], list[str]]


def _split_host_port(target: str, default_port: int) -> tuple[str, int]:
    if target.startswith("["):  # [ipv6]:port
        host, _, rest = target[1:].partition("]")
        port = rest.lstrip(":")
    else:
        host, _, port = target.rpartition(":") if ":" in target else (target, "", "")
    return host, int(port) if port else default_port


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError, OSError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


class GuardedProxy:
    """Forward proxy that refuses every destination `resolve_host` does not approve."""

    def __init__(self, resolve_host: HostResolver = public_addresses):
        self._resolve_host = resolve_host
        self._server: asyncio.AbstractServer | None = None
        self.port: int = 0
        self.blocked: list[str] = []  # last refused hosts, for diagnostics and tests

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def start(self) -> None:
        if self._server is not None:
            return
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0, limit=MAX_HEAD_BYTES)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None

    async def _open_upstream(self, host: str, port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Connect to a checked address of `host`; raises `BlockedUrlError` for internal hosts."""
        addresses = await asyncio.to_thread(self._resolve_host, host)
        last_error: Exception = OSError(f"no address for {host}")
        for address in addresses[:4]:
            try:
                return await asyncio.wait_for(asyncio.open_connection(address, port), CONNECT_TIMEOUT)
            except (TimeoutError, OSError) as exc:
                last_error = exc
        raise last_error

    async def _refuse(self, writer: asyncio.StreamWriter, status: str, *, blocked: bool = False) -> None:
        marker = f"{BLOCKED_HEADER}: 1\r\n" if blocked else ""
        try:
            writer.write(f"HTTP/1.1 {status}\r\n{marker}Content-Length: 0\r\nConnection: close\r\n\r\n".encode())
            await writer.drain()
        except (ConnectionError, OSError):
            pass
        writer.close()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HEAD_TIMEOUT)
            request_line, *header_lines = head.decode("latin-1").rstrip("\r\n").split("\r\n")
            method, target, _version = request_line.split(" ", 2)
        except (TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError, OSError):
            writer.close()
            return

        try:
            if method.upper() == "CONNECT":
                host, port = _split_host_port(target, 443)
                forward = b""
            else:
                parts = urlsplit(target)
                if parts.scheme.lower() != "http" or not parts.hostname:
                    await self._refuse(writer, "400 Bad Request")
                    return
                host, port = parts.hostname, parts.port or 80
                path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
                kept = [line for line in header_lines if line.split(":", 1)[0].strip().lower() not in HOP_HEADERS]
                # One request per connection: a reused connection could otherwise reach another host unchecked.
                forward = "\r\n".join([f"{method} {path} HTTP/1.1", *kept, "Connection: close", "", ""]).encode(
                    "latin-1"
                )
        except ValueError:
            await self._refuse(writer, "400 Bad Request")
            return

        try:
            upstream_reader, upstream_writer = await self._open_upstream(host, port)
        except BlockedUrlError as exc:
            log_debug(f"guarded proxy blocked {host}:{port}: {exc}")
            self.blocked = [*self.blocked[-49:], host]
            await self._refuse(writer, "403 Forbidden", blocked=True)
            return
        except (TimeoutError, OSError):
            await self._refuse(writer, "502 Bad Gateway")
            return

        try:
            if forward:
                upstream_writer.write(forward)
                await upstream_writer.drain()
            else:
                writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                await writer.drain()
        except (ConnectionError, OSError):
            writer.close()
            upstream_writer.close()
            return
        await asyncio.gather(_pipe(reader, upstream_writer), _pipe(upstream_reader, writer))
