"""FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI

from .routers import analyze as analyze_router
from .routers import crawl as crawl_router

app = FastAPI(title="lease_crawler", version="0.1.0")
app.include_router(crawl_router.router)
app.include_router(analyze_router.router)


@app.get("/health")
async def health() -> dict[str, bool]:
    """Liveness probe used by the agent and CI."""
    return {"ok": True}
