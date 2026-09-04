import asyncio
import time
import uuid
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .api import router
from .config import get_settings
from .db import SessionLocal
from .grading_api import router as grading_router
from .observability import configure_logging, install_observability

settings = get_settings()
configure_logging(settings.log_level)
app = FastAPI(
    title="Stormcloud API",
    version="0.1.0",
    docs_url="/docs" if settings.public_docs else None,
    openapi_url="/openapi.json" if settings.public_docs else None,
)
app.include_router(router)
app.include_router(grading_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
    max_age=600,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)
install_observability(app)

_auth_attempts: dict[str, deque[float]] = defaultdict(deque)
_auth_rate_lock = asyncio.Lock()
_throttled_paths = {"/v1/auth/login", "/v1/auth/invitations/accept", "/v1/auth/accept-invite"}


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    if request.method == "POST" and request.url.path in _throttled_paths:
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        async with _auth_rate_lock:
            attempts = _auth_attempts[key]
            while attempts and attempts[0] <= now - 60:
                attempts.popleft()
            if len(attempts) >= settings.auth_rate_limit_per_minute:
                return JSONResponse(
                    status_code=429,
                    media_type="application/problem+json",
                    content={
                        "type": "https://stormcloud.local/problems/rate-limit",
                        "title": "Too many authentication attempts",
                        "status": 429,
                        "detail": "Try again in one minute",
                        "instance": request.url.path,
                    },
                    headers={"Retry-After": "60", "X-Request-ID": request.state.request_id},
                )
            attempts.append(now)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if settings.env.lower() == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.exception_handler(HTTPException)
async def http_problem(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        media_type="application/problem+json",
        content={
            "type": "about:blank",
            "title": "Request failed",
            "status": exc.status_code,
            "detail": str(exc.detail),
            "instance": request.url.path,
        },
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_problem(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        media_type="application/problem+json",
        content={
            "type": "https://stormcloud.local/problems/validation",
            "title": "Validation failed",
            "status": 422,
            "detail": "Request validation failed",
            "instance": request.url.path,
            "errors": jsonable_encoder(exc.errors()),
        },
    )


@app.get("/health/ready", include_in_schema=False)
def ready():
    with SessionLocal() as db:
        db.execute(text("select 1"))
    return {"status": "ready", "service": "api"}
