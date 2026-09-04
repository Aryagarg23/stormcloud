import hashlib

import httpx
import pytest
from pydantic import ValidationError

from stormcloud.fetcher import (
    FetcherClient,
    FetchFailure,
    FetchRequest,
    FetchSuccess,
    canonicalize_url,
)


def successful_payload(request_id: str) -> dict:
    text = "First sentence. Second sentence!"
    return {
        "status": "success",
        "request_id": request_id,
        "submitted_url": "https://Example.COM:443/story#ignored",
        "final_url": "https://example.com/story",
        "canonical_url": "https://example.com/story",
        "retrieved_at": "2026-09-04T12:00:00Z",
        "media_type": "text/plain; charset=utf-8",
        "normalized_text": text,
        "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "segments": [
            {
                "id": "s-1",
                "kind": "sentence",
                "start": 0,
                "end": 15,
                "text": "First sentence.",
            },
            {
                "id": "s-2",
                "kind": "sentence",
                "start": 16,
                "end": 32,
                "text": "Second sentence!",
            },
        ],
        "metadata": {"title": "Contract fixture"},
        "raw_content_base64": "PGh0bWw+PC9odG1sPg==",
        "raw_content_type": "text/html",
    }


@pytest.mark.asyncio
async def test_fetcher_sends_internal_token_and_validates_contract():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Stormcloud-Internal-Token"] == "x" * 32
        return httpx.Response(200, json=successful_payload("req-1"))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = FetcherClient("http://source-extractor:8090", token="x" * 32, client=http)
        result = await client.fetch(
            FetchRequest(request_id="req-1", url="https://example.com/story")
        )
    assert isinstance(result, FetchSuccess)
    assert result.raw_content_type == "text/html"


@pytest.mark.asyncio
async def test_fetcher_preserves_structured_failure():
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "status": "failure",
                "request_id": "req-2",
                "code": "SOURCE_BLOCKED",
                "retryable": False,
                "message": "body was not delivered",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = FetcherClient("http://source-extractor:8090", token="x" * 32, client=http)
        result = await client.fetch(
            FetchRequest(request_id="req-2", url="https://example.com/paywall")
        )
    assert isinstance(result, FetchFailure)
    assert result.retryable is False


def test_contract_rejects_inexact_offsets_and_noncanonical_urls():
    body = successful_payload("req-3")
    body["segments"][0]["text"] = "wrong"
    with pytest.raises(ValidationError):
        FetchSuccess.model_validate(body)
    assert canonicalize_url("HTTPS://Example.COM:443/path#x") == "https://example.com/path"
