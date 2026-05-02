"""URL fetcher with two backends.

- ``httpx``: fast, single GET. Works for SSR sites (Avalon homepage, Craigslist).
- ``obscura``: real headless Chromium with stealth + auto-expand JS injection.
  Slower (3-15s) but bypasses anti-bot (Akamai/CF Bot Manager) and renders SPAs.

Backend selected by ``CRAWLER_BACKEND``: ``httpx`` | ``obscura`` | ``auto``
(default). ``auto`` tries httpx first and falls back to Obscura when:
  - httpx raises CrawlError (timeout/transport/http_error)
  - response body < ``OBSCURA_FALLBACK_MIN_BYTES`` (likely an SPA shell)

Callers always receive a :class:`CrawlResult` with ``content`` (rendered HTML)
and ``metadata``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel

from .log_setup import log_event
from .settings import get_settings

logger = logging.getLogger("lease_crawler.crawler")

_AUTO_EXPAND_JS = (Path(__file__).parent / "auto_expand.js").read_text(encoding="utf-8")


class CrawlResult(BaseModel):
    url: str
    status: int
    content: str
    fetched_at: datetime
    backend: str = "httpx"


CrawlErrorReason = Literal["http_error", "timeout", "empty", "transport_error", "obscura_failed"]


class CrawlError(Exception):
    def __init__(self, reason: CrawlErrorReason, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason: CrawlErrorReason = reason
        self.detail = detail


_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


async def crawl(url: str, timeout_s: float | None = None) -> CrawlResult:
    """Fetch ``url`` according to the configured ``CRAWLER_BACKEND``."""
    settings = get_settings()
    backend = (settings.CRAWLER_BACKEND or "auto").lower()

    if backend == "obscura":
        return await _obscura_crawl(url, timeout_s)

    if backend == "httpx":
        return await _httpx_crawl(url, timeout_s)

    # backend == "auto": httpx first, fall back to Obscura on failure or thin body.
    try:
        result = await _httpx_crawl(url, timeout_s)
    except CrawlError as e:
        if _can_fallback(settings) and e.reason in {"http_error", "transport_error", "timeout", "empty"}:
            log_event(logger, "crawl.fallback", url=url, from_backend="httpx", reason=e.reason)
            return await _obscura_crawl(url, timeout_s)
        raise

    if _can_fallback(settings) and len(result.content) < settings.OBSCURA_FALLBACK_MIN_BYTES:
        log_event(
            logger,
            "crawl.fallback",
            url=url,
            from_backend="httpx",
            reason="thin_body",
            httpx_bytes=len(result.content),
            threshold=settings.OBSCURA_FALLBACK_MIN_BYTES,
        )
        return await _obscura_crawl(url, timeout_s)

    return result


def _can_fallback(settings) -> bool:
    """True iff OBSCURA_BIN is configured and points at a real file."""
    return bool(settings.OBSCURA_BIN) and Path(settings.OBSCURA_BIN).exists()


async def _httpx_crawl(url: str, timeout_s: float | None = None) -> CrawlResult:
    """Plain HTTP GET with a Chrome UA. No JS, no cookies-acceptance."""
    settings = get_settings()
    deadline = timeout_s if timeout_s is not None else settings.OBSCURA_TIMEOUT_S

    log_event(logger, "crawl.start", backend="httpx", url=url, timeout_s=deadline)
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=deadline,
            headers={"User-Agent": _DEFAULT_UA, "Accept-Language": "en-US,en;q=0.9"},
        ) as client:
            r = await client.get(url)
    except httpx.TimeoutException as e:
        log_event(logger, "crawl.error", backend="httpx", url=url, reason="timeout", duration_ms=round((time.perf_counter() - started) * 1000, 1))
        raise CrawlError("timeout", f"GET {url} did not return within {deadline}s") from e
    except httpx.TransportError as e:
        log_event(logger, "crawl.error", backend="httpx", url=url, reason="transport_error", duration_ms=round((time.perf_counter() - started) * 1000, 1), detail=str(e)[:200])
        raise CrawlError("transport_error", str(e)) from e

    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    if r.status_code >= 400:
        log_event(logger, "crawl.error", backend="httpx", url=url, reason="http_error", status=r.status_code, duration_ms=duration_ms)
        raise CrawlError("http_error", f"GET {url} returned {r.status_code}")

    content = r.text
    if not content.strip():
        log_event(logger, "crawl.error", backend="httpx", url=url, reason="empty", status=r.status_code, duration_ms=duration_ms)
        raise CrawlError("empty", "response body was empty")

    log_event(logger, "crawl.done", backend="httpx", url=url, status=r.status_code, bytes=len(content), duration_ms=duration_ms)
    return CrawlResult(url=url, status=r.status_code, content=content, fetched_at=datetime.now(UTC), backend="httpx")


async def _obscura_crawl(url: str, timeout_s: float | None = None) -> CrawlResult:
    """Render with Obscura (real Chromium, stealth, auto-expand JS injection)."""
    settings = get_settings()
    deadline = timeout_s if timeout_s is not None else settings.OBSCURA_RUN_TIMEOUT_S

    if not settings.OBSCURA_BIN or not Path(settings.OBSCURA_BIN).exists():
        raise CrawlError("obscura_failed", f"OBSCURA_BIN not found: {settings.OBSCURA_BIN!r}")

    args = [
        "fetch", url,
        "--dump", "html",
        "--wait-until", "networkidle",
        "--wait", "20",
        "--stealth",
        "--user-agent", _DEFAULT_UA,
        "--eval", _AUTO_EXPAND_JS,
    ]
    log_event(logger, "crawl.start", backend="obscura", url=url, timeout_s=deadline)
    started = time.perf_counter()

    try:
        proc = await asyncio.create_subprocess_exec(
            settings.OBSCURA_BIN, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=deadline)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        log_event(logger, "crawl.error", backend="obscura", url=url, reason="timeout", duration_ms=round((time.perf_counter() - started) * 1000, 1))
        raise CrawlError("timeout", f"Obscura did not return within {deadline}s")

    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace")[:500]
        log_event(logger, "crawl.error", backend="obscura", url=url, reason="non_zero_exit", rc=proc.returncode, duration_ms=duration_ms, detail=err)
        raise CrawlError("obscura_failed", f"obscura rc={proc.returncode}: {err}")

    content = stdout.decode("utf-8", errors="replace")
    if not content.strip():
        log_event(logger, "crawl.error", backend="obscura", url=url, reason="empty", duration_ms=duration_ms)
        raise CrawlError("empty", "obscura returned empty body")

    # Best-effort: surface the auto_expand metadata if the markers landed.
    expanded_iters = "-"
    expanded_clicks = "-"
    for marker in ("data-auto-expand-iters=", "data-auto-expand-clicks="):
        idx = content.find(marker)
        if idx != -1:
            quote = content[idx + len(marker)]
            end = content.find(quote, idx + len(marker) + 1)
            if end != -1:
                value = content[idx + len(marker) + 1 : end]
                if marker.endswith("iters="):
                    expanded_iters = value
                else:
                    expanded_clicks = value

    log_event(
        logger,
        "crawl.done",
        backend="obscura",
        url=url,
        status=200,
        bytes=len(content),
        duration_ms=duration_ms,
        expand_iters=expanded_iters,
        expand_clicks=expanded_clicks,
    )
    return CrawlResult(url=url, status=200, content=content, fetched_at=datetime.now(UTC), backend="obscura")
