"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

from .log_setup import configure_logging, log_event, set_request_id
from .routers import analyze as analyze_router
from .routers import ask as ask_router
from .routers import crawl as crawl_router
from .routers import explore as explore_router

configure_logging()
logger = logging.getLogger("lease_crawler.http")


class RequestObservabilityMiddleware(BaseHTTPMiddleware):
    """Bind a request_id, log entry/exit with duration."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        rid = uuid.uuid4().hex[:12]
        set_request_id(rid)
        start = time.perf_counter()
        log_event(
            logger,
            "request.start",
            method=request.method,
            path=request.url.path,
            client=request.client.host if request.client else "-",
        )
        try:
            response = await call_next(request)
        except Exception as e:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            log_event(
                logger,
                "request.error",
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
                error=type(e).__name__,
                detail=str(e)[:200],
            )
            raise
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        log_event(
            logger,
            "request.end",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        # Surface the request_id to the caller so the agent can correlate.
        response.headers["x-request-id"] = rid
        return response


app = FastAPI(title="lease_crawler", version="0.1.0")
app.add_middleware(RequestObservabilityMiddleware)
app.include_router(crawl_router.router)
app.include_router(analyze_router.router)
app.include_router(ask_router.router)
app.include_router(explore_router.router)


@app.get("/health")
async def health() -> dict[str, bool]:
    """Liveness probe used by the agent and CI."""
    return {"ok": True}
