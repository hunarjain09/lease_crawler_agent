"""Atomic tests for the httpx-backed crawler."""

from __future__ import annotations

import httpx
import pytest

from lease_crawler import crawler
from lease_crawler.crawler import CrawlError

pytestmark = pytest.mark.unit


def _patch_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:  # type: ignore[no-untyped-def]
    real_cls = httpx.AsyncClient  # capture before the patch

    def _factory(**_kw: object) -> httpx.AsyncClient:
        return real_cls(transport=httpx.MockTransport(handler), follow_redirects=True)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)


@pytest.mark.asyncio
async def test_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>$3,415</html>")

    _patch_client(monkeypatch, handler)
    result = await crawler.crawl("https://example.com")
    assert "$3,415" in result.content
    assert result.status == 200


@pytest.mark.asyncio
async def test_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="oops")

    _patch_client(monkeypatch, handler)
    with pytest.raises(CrawlError) as ei:
        await crawler.crawl("https://example.com")
    assert ei.value.reason == "http_error"


@pytest.mark.asyncio
async def test_empty_body(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="   \n")

    _patch_client(monkeypatch, handler)
    with pytest.raises(CrawlError) as ei:
        await crawler.crawl("https://example.com")
    assert ei.value.reason == "empty"


@pytest.mark.asyncio
async def test_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    _patch_client(monkeypatch, handler)
    with pytest.raises(CrawlError) as ei:
        await crawler.crawl("https://example.com", timeout_s=0.1)
    assert ei.value.reason == "timeout"


@pytest.mark.asyncio
async def test_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns", request=request)

    _patch_client(monkeypatch, handler)
    with pytest.raises(CrawlError) as ei:
        await crawler.crawl("https://example.com")
    assert ei.value.reason == "transport_error"
