"""FastAPI application entrypoint.

M0 surface: just `GET /health`. `/crawl`, `/analyze`, `/walkthrough` land in later milestones.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="lease_crawler", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, bool]:
    """Liveness probe used by the agent and CI."""
    return {"ok": True}
