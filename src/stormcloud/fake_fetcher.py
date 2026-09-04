import hashlib
from datetime import datetime, timezone
from fastapi import FastAPI
from .fetcher import FetchFailure, FetchRequest, FetchSuccess, canonicalize_url
from .nlp import normalize_text, segment_text

app = FastAPI(title="Stormcloud Fake Fetcher", version="1.0.0")

@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/health/ready")
async def ready() -> dict[str, str]:
    return {"status": "ready"}

@app.post("/v1/fetch", response_model=FetchSuccess | FetchFailure)
async def fetch(request: FetchRequest):
    if "fail-permanent" in request.url:
        return FetchFailure(request_id=request.request_id, code="FETCH_FAILED",
                            retryable=False, message="deterministic fixture failure")
    canonical = canonicalize_url(request.url)
    text = normalize_text(f"Deterministic test article for {canonical}.\n\nThis content is served by the Stormcloud fake fetcher.")
    segments = [segment.model_dump() for segment in segment_text(text)]
    return FetchSuccess(request_id=request.request_id, submitted_url=request.url,
                        final_url=canonical, canonical_url=canonical,
                        retrieved_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                        media_type="text/plain; charset=utf-8", normalized_text=text,
                        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
                        segments=segments, metadata={"title": "Fake article"})
