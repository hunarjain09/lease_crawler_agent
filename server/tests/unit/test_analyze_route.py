"""Unit tests for the /analyze route.

We mount the analyze router on a fresh FastAPI app (so the test does not
depend on `main.py` being wired yet -- that wiring lands at merge time).
The `inference.analyze` callable is monkey-patched so no network is hit.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from lease_crawler import inference
from lease_crawler.models import AnalyzeResponse, Leak, make_leak_id
from lease_crawler.routers import analyze as analyze_router


@pytest_asyncio.fixture
async def analyze_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    canned = AnalyzeResponse(
        leaks=[
            Leak(
                id=make_leak_id("https://example.com", "Base rent"),
                source_url="https://example.com",
                title="Base rent",
                severity="med",
                detail="$3,415",
            )
        ],
        summary="ok",
    )

    async def fake_analyze(*_args: Any, **_kwargs: Any) -> AnalyzeResponse:
        return canned

    monkeypatch.setattr(inference, "analyze", fake_analyze)

    app = FastAPI()
    app.include_router(analyze_router.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.unit
async def test_analyze_route_ok(analyze_client: httpx.AsyncClient) -> None:
    response = await analyze_client.post("/analyze", json={"content": "x", "context": []})
    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == "ok"
    assert len(body["leaks"]) == 1


@pytest.mark.unit
async def test_analyze_route_validation_422(analyze_client: httpx.AsyncClient) -> None:
    response = await analyze_client.post("/analyze", json={"context": []})  # missing content
    assert response.status_code == 422
