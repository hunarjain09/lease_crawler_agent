"""Route-level tests for POST /crawl with the crawler dependency stubbed."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from lease_crawler import crawler
from lease_crawler.crawler import CrawlError, CrawlResult
from lease_crawler.routers import crawl as crawl_router

pytestmark = pytest.mark.unit


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(crawl_router.router)
    return app


@pytest.mark.asyncio
async def test_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_crawl(url: str) -> CrawlResult:
        return CrawlResult(url=url, status=200, content="<html>ok</html>", fetched_at=datetime.now(UTC))

    monkeypatch.setattr(crawler, "crawl", fake_crawl)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as ac:
        r = await ac.post("/crawl", json={"url": "https://example.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["content"] == "<html>ok</html>"
    assert body["metadata"]["status"] == 200


@pytest.mark.asyncio
async def test_crawl_error_returns_502(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_crawl(url: str) -> CrawlResult:  # noqa: ARG001
        raise CrawlError("nonzero_exit", "boom")

    monkeypatch.setattr(crawler, "crawl", fake_crawl)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as ac:
        r = await ac.post("/crawl", json={"url": "https://example.com"})
    assert r.status_code == 502
    assert r.json()["detail"]["error"] == "nonzero_exit"


@pytest.mark.asyncio
async def test_invalid_url_returns_422() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as ac:
        r = await ac.post("/crawl", json={"url": "not a url"})
    assert r.status_code == 422
