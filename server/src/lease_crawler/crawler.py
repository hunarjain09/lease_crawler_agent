"""URL fetcher.

Default backend: ``httpx``. Many listing sites (e.g., Avalon) server-render
all the data we need, so a single GET is enough.

The crawler is interface-stable: callers receive a :class:`CrawlResult` with
``content`` and ``metadata``. If a future site needs JS execution we swap the
implementation behind ``CRAWLER_BACKEND`` without changing callers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import httpx
from pydantic import BaseModel

from .settings import get_settings


class CrawlResult(BaseModel):
    url: str
    status: int
    content: str
    fetched_at: datetime


CrawlErrorReason = Literal["http_error", "timeout", "empty", "transport_error"]


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
    """Fetch ``url`` and return its body.

    Single GET, follows redirects, sets a desktop-Chrome UA so server-rendered
    sites don't return a stripped-down mobile/SEO page.
    """
    settings = get_settings()
    deadline = timeout_s if timeout_s is not None else settings.OBSCURA_TIMEOUT_S

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=deadline,
            headers={"User-Agent": _DEFAULT_UA, "Accept-Language": "en-US,en;q=0.9"},
        ) as client:
            r = await client.get(url)
    except httpx.TimeoutException as e:
        raise CrawlError("timeout", f"GET {url} did not return within {deadline}s") from e
    except httpx.TransportError as e:
        raise CrawlError("transport_error", str(e)) from e

    if r.status_code >= 400:
        raise CrawlError("http_error", f"GET {url} returned {r.status_code}")

    content = r.text
    if not content.strip():
        raise CrawlError("empty", "response body was empty")

    return CrawlResult(
        url=url,
        status=r.status_code,
        content=content,
        fetched_at=datetime.now(UTC),
    )
