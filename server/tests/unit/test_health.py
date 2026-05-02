"""Unit test for GET /health."""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.unit
async def test_health_ok(async_client: httpx.AsyncClient) -> None:
    response = await async_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
