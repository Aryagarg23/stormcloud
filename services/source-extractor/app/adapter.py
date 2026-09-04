"""Private adapter from tmep's API to the stable Stormcloud fetch contract."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from aiohttp import web
from secure_fetch import (
    UnsafeUrlError,
    begin_capture,
    get_capture,
    install_security_guards,
    validate_public_url,
)

install_security_guards()

from tmep.extract import extract as upstream_extract  # noqa: E402

MAX_BODY_BYTES = 16 * 1024
MAX_NORMALIZED_BYTES = int(
    os.environ.get("EXTRACTOR_MAX_NORMALIZED_BYTES", 10 * 1024 * 1024)
)
MAX_RAW_CAPTURE_BYTES = int(
    os.environ.get("EXTRACTOR_MAX_RAW_CAPTURE_BYTES", 8 * 1024 * 1024)
)
SENTENCE_RE = re.compile(r"[^.!?\n]+(?:[.!?]+(?=\s|$)|$)", re.MULTILINE)


def _canonicalize(url: str) -> str:
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    port = parsed.port
    authority = host
    if ":" in host and not host.startswith("["):
        authority = f"[{host}]"
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        authority = f"{authority}:{port}"
    return urlunsplit((scheme, authority, parsed.path or "/", parsed.query, ""))


def _normalize(value: str) -> str:
    lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    normalized: list[str] = []
    blank = False
    for line in lines:
        clean = re.sub(r"[ \t\f\v]+", " ", line).strip()
        if clean:
            normalized.append(clean)
            blank = False
        elif normalized and not blank:
            normalized.append("")
            blank = True
    return "\n".join(normalized).strip()


def _segment_id(kind: str, start: int, end: int, text: str) -> str:
    payload = f"{kind}:{start}:{end}:{text}".encode()
    return f"{kind[:1]}-{hashlib.sha256(payload).hexdigest()[:20]}"


def _segments(text: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    cursor = 0
    for paragraph in text.split("\n\n"):
        start = text.find(paragraph, cursor)
        if start < 0:
            continue
        end = start + len(paragraph)
        cursor = end
        if paragraph:
            result.append(
                {
                    "id": _segment_id("paragraph", start, end, paragraph),
                    "kind": "paragraph",
                    "start": start,
                    "end": end,
                    "text": paragraph,
                }
            )
    for match in SENTENCE_RE.finditer(text):
        raw = match.group(0)
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw) - len(raw.rstrip())
        start = match.start() + leading
        end = match.end() - trailing
        if end <= start:
            continue
        sentence = text[start:end]
        result.append(
            {
                "id": _segment_id("sentence", start, end, sentence),
                "kind": "sentence",
                "start": start,
                "end": end,
                "text": sentence,
            }
        )
    result.sort(key=lambda row: (row["start"], row["end"], row["kind"]))
    return result


def _failure(
    request_id: str, code: str, message: str, *, retryable: bool, status: int | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "failure",
        "request_id": request_id,
        "code": code,
        "retryable": retryable,
        "message": message[:2048],
    }
    if status is not None:
        payload["upstream_status"] = status
    return payload


def _authorized(request: web.Request) -> bool:
    configured = request.app["internal_token"]
    supplied = request.headers.get("X-Stormcloud-Internal-Token", "")
    return bool(supplied) and hmac.compare_digest(supplied, configured)


async def _live(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def _ready(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "status": "ready",
            "upstream": "tmep",
            "upstream_commit": request.app["upstream_commit"],
        }
    )


async def _fetch(request: web.Request) -> web.Response:
    if not _authorized(request):
        return web.json_response(
            _failure("", "UNAUTHORIZED", "missing or invalid internal token", retryable=False),
            status=401,
        )
    if request.content_length is not None and request.content_length > MAX_BODY_BYTES:
        return web.json_response(
            _failure("", "REQUEST_TOO_LARGE", "request body is too large", retryable=False),
            status=413,
        )
    try:
        payload = await request.json()
    except Exception:
        return web.json_response(
            _failure("", "INVALID_REQUEST", "request body must be valid JSON", retryable=False),
            status=400,
        )
    if not isinstance(payload, dict):
        return web.json_response(
            _failure("", "INVALID_REQUEST", "request body must be an object", retryable=False),
            status=400,
        )
    request_id = payload.get("request_id")
    url = payload.get("url")
    if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
        return web.json_response(
            _failure("", "INVALID_REQUEST", "request_id must contain 1-128 characters", retryable=False),
            status=400,
        )
    if not isinstance(url, str) or len(url) > 4096:
        return web.json_response(
            _failure(request_id, "INVALID_URL", "url must be a string of at most 4096 characters", retryable=False),
            status=400,
        )
    try:
        await validate_public_url(url)
    except UnsafeUrlError as exc:
        return web.json_response(
            _failure(request_id, "UNSAFE_URL", str(exc), retryable=False), status=400
        )

    begin_capture()
    try:
        extracted = await upstream_extract(url)
    except UnsafeUrlError as exc:
        return web.json_response(
            _failure(request_id, "UNSAFE_REDIRECT", str(exc), retryable=False), status=400
        )
    except Exception as exc:
        return web.json_response(
            _failure(request_id, "EXTRACTOR_UNAVAILABLE", str(exc), retryable=True), status=502
        )

    if extracted.error and not (extracted.text or extracted.transcript):
        blocked = extracted.metadata.get("extraction_status") == "blocked"
        return web.json_response(
            _failure(
                request_id,
                "SOURCE_BLOCKED" if blocked else "EXTRACTOR_ERROR",
                extracted.error,
                retryable=not blocked,
            )
        )

    components = [part for part in (extracted.text, extracted.transcript) if part]
    text = _normalize("\n\n".join(dict.fromkeys(components)))
    if not text:
        return web.json_response(
            _failure(
                request_id,
                "NO_USABLE_TEXT",
                extracted.error or "extractor returned no usable text",
                retryable=False,
            )
        )
    if len(text.encode("utf-8")) > MAX_NORMALIZED_BYTES:
        return web.json_response(
            _failure(
                request_id,
                "DOCUMENT_TOO_LARGE",
                "normalized document exceeds configured maximum",
                retryable=False,
            )
        )

    capture = get_capture()
    final_url = capture.url if capture else extracted.metadata.get("final_url", extracted.url or url)
    canonical_url = _canonicalize(final_url)
    metadata = {
        "title": extracted.title,
        "author": extracted.author,
        "published": extracted.published,
        "description": extracted.description,
        "source_media_type": str(getattr(extracted.media_type, "value", extracted.media_type)),
        "images": extracted.images,
        "videos": extracted.videos,
        "audio": extracted.audio,
        "thumbnails": extracted.thumbnails,
        "duration": extracted.duration,
        "channel": extracted.channel,
        "channel_url": extracted.channel_url,
        "extractor_metadata": extracted.metadata,
        "extractor_error": extracted.error,
        "raw_capture_available": bool(capture and len(capture.body) <= MAX_RAW_CAPTURE_BYTES),
    }
    response: dict[str, Any] = {
        "status": "success",
        "request_id": request_id,
        "submitted_url": url,
        "final_url": final_url,
        "canonical_url": canonical_url,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "media_type": "text/plain; charset=utf-8",
        "normalized_text": text,
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "segments": _segments(text),
        "metadata": metadata,
    }
    if capture and len(capture.body) <= MAX_RAW_CAPTURE_BYTES:
        response["raw_content_base64"] = base64.b64encode(capture.body).decode("ascii")
        response["raw_content_type"] = capture.content_type
    return web.json_response(response)


def create_app(*, internal_token: str | None = None) -> web.Application:
    token = internal_token or os.environ.get("EXTRACTOR_INTERNAL_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("EXTRACTOR_INTERNAL_TOKEN must contain at least 32 characters")
    app = web.Application(client_max_size=MAX_BODY_BYTES)
    app["internal_token"] = token
    app["upstream_commit"] = os.environ.get("SOURCE_EXTRACTOR_COMMIT", "unknown")
    app.router.add_get("/health/live", _live)
    app.router.add_get("/health/ready", _ready)
    app.router.add_post("/v1/fetch", _fetch)
    return app


def main() -> None:
    port = int(os.environ.get("PORT", "8090"))
    web.run_app(create_app(), host="0.0.0.0", port=port, print=None)


if __name__ == "__main__":
    main()
