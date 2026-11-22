"""FastAPI entry point for taskboard26-api."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from . import __version__
from .logging_config import configure_logging
from .metrics import MetricsMiddleware
from .task_store import StorageUnavailableError, close_task_store, get_task_store
from .tasks_api import StoreDep, validation_exception_handler
from .tasks_api import router as tasks_router
from .tracing import configure_tracing, tracing_enabled

configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
if tracing_enabled():
    configure_tracing()

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Create the schema at startup (never failing the start); close on shutdown."""
    if not os.environ.get("DATABASE_URL"):
        logger.error("database_url_missing")
    try:
        get_task_store().ensure_schema()
    except StorageUnavailableError:
        logger.warning("storage_unavailable_at_startup")
    try:
        yield
    finally:
        close_task_store()


app = FastAPI(title="taskboard26-api", version=__version__, lifespan=lifespan)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_middleware(MetricsMiddleware)
if tracing_enabled():
    FastAPIInstrumentor.instrument_app(app)
app.include_router(tasks_router)


class HealthResponse(BaseModel):
    status: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe — returns 200 as long as the process is responding."""
    return HealthResponse(status="ok")


@app.get(
    "/ready",
    response_model=HealthResponse,
    responses={503: {"description": "Storage unavailable"}},
)
def ready(store: StoreDep) -> HealthResponse | JSONResponse:
    """Readiness probe: 200 when the storage answers, otherwise 503."""
    if store.ping():
        return HealthResponse(status="ready")
    return JSONResponse(status_code=503, content={"status": "unavailable"})


@app.get("/ping")
def ping() -> dict[str, str]:
    """Simple ping endpoint."""
    return {"pong": "taskboard26-api"}


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus scrape endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
