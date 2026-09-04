"""Runtime network hardening for the pinned tmep extractor."""

from __future__ import annotations

import asyncio
import contextvars
import importlib
import ipaddress
import os
import socket
import ssl
import sys
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver
from aiohttp.resolver import DefaultResolver

MAX_REDIRECTS = 5
ALLOWED_PORTS = {80, 443}
MAX_RESPONSE_BYTES = int(os.environ.get("EXTRACTOR_MAX_RESPONSE_BYTES", 20 * 1024 * 1024))


class UnsafeUrlError(ValueError):
    pass


class ResponseTooLargeError(ValueError):
    pass


@dataclass(frozen=True)
class RawCapture:
    url: str
    content_type: str
    body: bytes

@dataclass(frozen=True)
class BufferedResponse:
    status: int
    headers: dict[str, str]
    url: str
    body: bytes

    def _header(self, name: str) -> str:
        target = name.casefold()
        return next(
            (value for key, value in self.headers.items() if key.casefold() == target),
            "",
        )

    @property
    def content_type(self) -> str:
        return self._header("Content-Type").split(";", 1)[0].strip().lower()

    @property
    def charset(self) -> str | None:
        for item in self._header("Content-Type").split(";")[1:]:
            key, _, value = item.strip().partition("=")
            if key.casefold() == "charset" and value:
                return value.strip("\"'")
        return None

    async def read(self) -> bytes:
        return self.body

    async def text(self, encoding: str | None = None, errors: str = "strict") -> str:
        return self.body.decode(encoding or self.charset or "utf-8", errors=errors)

    async def json(self) -> object:
        import json

        return json.loads(await self.text(errors="replace"))



_capture: contextvars.ContextVar[RawCapture | None] = contextvars.ContextVar(
    "stormcloud_raw_capture", default=None
)


def begin_capture() -> None:
    _capture.set(None)


def get_capture() -> RawCapture | None:
    return _capture.get()


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global


def _parse_url(url: str) -> tuple[str, int]:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeUrlError("invalid URL") from exc
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeUrlError("only http and https URLs are allowed")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise UnsafeUrlError("URL must contain a public host and no credentials")
    effective_port = port or (443 if parsed.scheme == "https" else 80)
    if effective_port not in ALLOWED_PORTS:
        raise UnsafeUrlError("only ports 80 and 443 are allowed")
    return parsed.hostname, effective_port


async def validate_public_url(url: str) -> None:
    host, port = _parse_url(url)
    try:
        literal = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        literal = None
    if literal is not None:
        if not _is_public(str(literal)):
            raise UnsafeUrlError("private, loopback, link-local, and reserved addresses are forbidden")
        return
    loop = asyncio.get_running_loop()
    try:
        rows = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrlError("host could not be resolved") from exc
    addresses = {row[4][0] for row in rows}
    if not addresses or any(not _is_public(address) for address in addresses):
        raise UnsafeUrlError("host resolves to a non-public address")


class PublicOnlyResolver(AbstractResolver):
    """Re-check DNS results at connection time to prevent DNS rebinding."""

    def __init__(self) -> None:
        self._delegate = DefaultResolver()

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        rows = await self._delegate.resolve(host, port, family)
        if not rows or any(not _is_public(row["host"]) for row in rows):
            raise UnsafeUrlError("connection target resolved to a non-public address")
        return rows

    async def close(self) -> None:
        await self._delegate.close()


async def _bounded_body(response: aiohttp.ClientResponse) -> bytes:
    declared = response.content_length
    if declared is not None and declared > MAX_RESPONSE_BYTES:
        raise ResponseTooLargeError("upstream response exceeds configured maximum")
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.content.iter_chunked(64 * 1024):
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise ResponseTooLargeError("upstream response exceeds configured maximum")
        chunks.append(chunk)
    return b"".join(chunks)


async def secure_fetch(
    url: str, headers: dict | None = None, timeout: int = 30
) -> aiohttp.ClientResponse:
    upstream = importlib.import_module("tmep.extract")

    request_headers = upstream._make_session_headers()
    if headers:
        request_headers.update(headers)
    connector = aiohttp.TCPConnector(
        ssl=ssl.create_default_context(),
        resolver=PublicOnlyResolver(),
        ttl_dns_cache=0,
    )
    session = aiohttp.ClientSession(
        headers=request_headers,
        connector=connector,
        cookie_jar=aiohttp.CookieJar(),
        auto_decompress=True,
    )
    current = url
    try:
        for redirect_count in range(MAX_REDIRECTS + 1):
            await validate_public_url(current)
            response = await session.get(
                current,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=min(max(timeout, 1), 120)),
            )
            if response.status in {301, 302, 303, 307, 308} and response.headers.get("Location"):
                response.release()
                if redirect_count == MAX_REDIRECTS:
                    raise UnsafeUrlError("too many redirects")
                current = urljoin(str(response.url), response.headers["Location"])
                continue
            body = await _bounded_body(response)
            response_url = str(response.url)
            response_status = response.status
            response_headers = dict(response.headers)
            capture_content_type = response.headers.get(
                "Content-Type", "application/octet-stream"
            ).split(";", 1)[0]
            response.release()
            if get_capture() is None:
                _capture.set(
                    RawCapture(
                        url=response_url,
                        content_type=capture_content_type,
                        body=body,
                    )
                )
            return BufferedResponse(
                status=response_status,
                headers=response_headers,
                url=response_url,
                body=body,
            )
        raise UnsafeUrlError("too many redirects")
    finally:
        await session.close()


async def secure_fetch_bytes(
    url: str, headers: dict | None = None, timeout: int = 30
) -> tuple[bytes, int, dict[str, str]]:
    response = await secure_fetch(url, headers=headers, timeout=timeout)
    return await response.read(), response.status, dict(response.headers)


def install_security_guards() -> None:
    upstream = importlib.import_module("tmep.extract")

    upstream._get_ssl_ctx = ssl.create_default_context
    upstream._fetch = secure_fetch
    upstream._fetch_bytes = secure_fetch_bytes
    for handler in upstream._HANDLERS.values():
        module = sys.modules.get(handler.__module__)
        if module is not None and hasattr(module, "_fetch"):
            module._fetch = secure_fetch
