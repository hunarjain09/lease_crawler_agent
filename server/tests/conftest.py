"""Shared pytest fixtures.

Unit tests must not touch the network: we drive FastAPI in-process via httpx's
ASGITransport so requests never leave the test runner.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest_asyncio

from lease_crawler.main import app


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator[httpx.AsyncClient]:
    """Async HTTP client bound to the FastAPI app via ASGI (no sockets)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
