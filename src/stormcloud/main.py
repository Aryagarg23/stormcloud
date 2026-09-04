import time
import uuid
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from .api import router
from .config import get_settings
from .db import SessionLocal
from .observability import configure_logging, install_observability

settings = get_settings()
configure_logging(settings.log_level)
app = FastAPI(title="Stormcloud API", version="0.1.0", docs_url="/docs",
              openapi_url="/openapi.json")
app.include_router(router)
install_observability(app)

@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response

@app.exception_handler(HTTPException)
async def http_problem(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, media_type="application/problem+json",
        content={"type": "about:blank", "title": "Request failed",
                 "status": exc.status_code, "detail": str(exc.detail),
                 "instance": request.url.path}, headers=exc.headers)

@app.exception_handler(RequestValidationError)
async def validation_problem(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, media_type="application/problem+json",
        content={"type": "https://stormcloud.local/problems/validation",
                 "title": "Validation failed", "status": 422,
                 "detail": "Request validation failed", "instance": request.url.path,
                 "errors": exc.errors()})

@app.get("/health/ready", include_in_schema=False)
def ready():
    with SessionLocal() as db:
        db.execute(text("select 1"))
    return {"status": "ready", "service": "api"}
