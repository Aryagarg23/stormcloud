import hashlib
import json
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, Field, model_validator

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


class FetchRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=128)
    url: str = Field(pattern=r"^https?://")


class FetchSegment(BaseModel):
    id: str
    kind: Literal["paragraph", "sentence"]
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str


class FetchSuccess(BaseModel):
    status: Literal["success"] = "success"
    request_id: str
    submitted_url: str
    final_url: str
    canonical_url: str
    retrieved_at: datetime
    media_type: str
    normalized_text: str
    content_sha256: str
    segments: list[FetchSegment]
    metadata: dict[str, Any] = Field(default_factory=dict)
    raw_content_base64: str | None = None
    raw_artifact_url: str | None = None
    raw_content_type: str | None = None

    @model_validator(mode="after")
    def validate_content(self):
        encoded = self.normalized_text.encode()
        if len(encoded) > MAX_DOCUMENT_BYTES:
            raise ValueError("normalized document exceeds maximum size")
        if hashlib.sha256(encoded).hexdigest() != self.content_sha256:
            raise ValueError("content_sha256 does not match normalized_text")
        seen: set[str] = set()
        for segment in self.segments:
            if segment.id in seen:
                raise ValueError("segment ids must be unique")
            seen.add(segment.id)
            if (
                segment.end > len(self.normalized_text)
                or self.normalized_text[segment.start : segment.end] != segment.text
            ):
                raise ValueError(f"invalid offsets for segment {segment.id}")
        return self


class FetchFailure(BaseModel):
    status: Literal["failure"] = "failure"
    request_id: str
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    retryable: bool
    message: str
    upstream_status: int | None = None


FetchResponse = FetchSuccess | FetchFailure


def canonicalize_url(url: str) -> str:
    parsed = urlsplit(url)
    scheme, host = parsed.scheme.lower(), (parsed.hostname or "").lower()
    port = parsed.port
    authority = (
        host
        if not port or (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
        else f"{host}:{port}"
    )
    return urlunsplit((scheme, authority, parsed.path or "/", parsed.query, ""))


class FetcherClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 60,
        token: str | None = None,
        max_response_bytes: int = 32 * 1024 * 1024,
        client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.token = token
        self.max_response_bytes = max_response_bytes
        self.client = client or httpx.AsyncClient()

    async def close(self) -> None:
        await self.client.aclose()

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        headers = {}
        if self.token:
            headers["X-Stormcloud-Internal-Token"] = self.token
        outbound = self.client.build_request(
            "POST",
            f"{self.base_url}/v1/fetch",
            json=request.model_dump(),
            headers=headers,
            timeout=self.timeout_seconds,
        )
        response = await self.client.send(outbound, stream=True)
        try:
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > self.max_response_bytes:
                    raise ValueError("fetcher response exceeds configured maximum")
                chunks.append(chunk)
            raw = json.loads(b"".join(chunks))
        finally:
            if response.is_error and raw.get("status") != "failure":
                response.raise_for_status()
            await response.aclose()
        if raw.get("request_id") != request.request_id:
            raise ValueError("fetcher response request_id mismatch")
        result = (
            FetchSuccess.model_validate(raw)
            if raw.get("status") == "success"
            else FetchFailure.model_validate(raw)
        )
        if (
            isinstance(result, FetchSuccess)
            and canonicalize_url(result.canonical_url) != result.canonical_url
        ):
            raise ValueError("fetcher canonical_url is not canonical")
        return result
