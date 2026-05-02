"""Async wrapper around the Obscura headless-browser CLI."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

from .settings import get_settings


class CrawlResult(BaseModel):
    url: str
    status: int
    content: str
    fetched_at: datetime


CrawlErrorReason = Literal["nonzero_exit", "timeout", "empty", "binary_missing"]


class CrawlError(Exception):
    def __init__(self, reason: CrawlErrorReason, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason: CrawlErrorReason = reason
        self.detail = detail


async def crawl(url: str, timeout_s: float | None = None) -> CrawlResult:
    """Render `url` with Obscura and return its HTML.

    Shells out to `obscura fetch <url> --dump html --wait-until load --stealth`.
    """
    settings = get_settings()
    binary = settings.OBSCURA_BIN
    deadline = timeout_s if timeout_s is not None else settings.OBSCURA_TIMEOUT_S

    try:
        proc = await asyncio.create_subprocess_exec(
            binary,
            "fetch",
            url,
            "--dump",
            "html",
            "--wait-until",
            "load",
            "--stealth",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        raise CrawlError("binary_missing", str(e)) from e

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=deadline)
    except asyncio.TimeoutError as e:
        proc.kill()
        await proc.wait()
        raise CrawlError("timeout", f"obscura did not return within {deadline}s") from e

    if proc.returncode != 0:
        raise CrawlError(
            "nonzero_exit",
            f"obscura exited {proc.returncode}: {stderr.decode(errors='replace').strip()}",
        )

    content = stdout.decode(errors="replace")
    if not content.strip():
        raise CrawlError("empty", "obscura returned empty stdout")

    return CrawlResult(
        url=url,
        status=200,
        content=content,
        fetched_at=datetime.now(UTC),
    )
