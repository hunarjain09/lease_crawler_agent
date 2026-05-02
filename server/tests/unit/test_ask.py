"""Unit tests for inference.ask + the /ask route, with respx-mocked GMI."""

from __future__ import annotations

import json
from typing import Any

import pytest
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from lease_crawler import inference
from lease_crawler.models import Leak
from lease_crawler.routers import ask as ask_router

pytestmark = pytest.mark.unit


def _gmi_completion(content: str) -> dict[str, Any]:
    return {
        "id": "cmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "anthropic/claude-opus-4.7",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _leak() -> Leak:
    return Leak(
        id="abc",
        source_url="https://avalon.example/sv",
        title="Furnished premium",
        severity="med",
        detail="Furnished is $4,696 vs unfurnished $3,415 -- a $1,281/mo premium.",
    )


@pytest.fixture(autouse=True)
def _clear_client_cache() -> None:
    inference._client.cache_clear()


@pytest.mark.asyncio
async def test_ask_returns_answer() -> None:
    with respx.mock(base_url="https://api.gmi-serving.com/v1") as router:
        route = router.post("/chat/completions").mock(
            return_value=Response(200, json=_gmi_completion("Base rent is $3,415."))
        )
        answer = await inference.ask(
            question="What's the rent?",
            leaks=[_leak()],
            summary="Avalon SV: $3,415/14mo.",
            history=[],
        )
    assert answer == "Base rent is $3,415."
    body = json.loads(route.calls[0].request.content)
    assert body["model"] == "anthropic/claude-opus-4.7"
    # leaks JSON appears in one of the system messages
    sys_msgs = [m["content"] for m in body["messages"] if m["role"] == "system"]
    assert any("Furnished premium" in m for m in sys_msgs)


@pytest.mark.asyncio
async def test_ask_uses_history() -> None:
    with respx.mock(base_url="https://api.gmi-serving.com/v1") as router:
        router.post("/chat/completions").mock(
            return_value=Response(200, json=_gmi_completion("Yes, $1,281/mo more."))
        )
        await inference.ask(
            question="Is furnished worth it?",
            leaks=[_leak()],
            summary="...",
            history=[
                {"role": "user", "content": "Tell me about Avalon SV."},
                {"role": "assistant", "content": "Base rent is $3,415 on a 14-mo term."},
            ],
        )
        body = json.loads(router.calls[0].request.content)
    roles = [m["role"] for m in body["messages"]]
    # system, system (context), user, assistant, user
    assert roles == ["system", "system", "user", "assistant", "user"]
    assert body["messages"][-1]["content"] == "Is furnished worth it?"


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(ask_router.router)
    return app


@pytest.mark.asyncio
async def test_ask_route_200(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_ask(**_kw: object) -> str:
        return "It's $3,415."

    monkeypatch.setattr(inference, "ask", fake_ask)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as ac:
        r = await ac.post(
            "/ask",
            json={
                "question": "What's the rent?",
                "leaks": [],
                "summary": "Avalon",
                "history": [],
            },
        )
    assert r.status_code == 200
    assert r.json() == {"answer": "It's $3,415."}


@pytest.mark.asyncio
async def test_ask_route_validates_question() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as ac:
        r = await ac.post("/ask", json={"question": "", "leaks": []})
    assert r.status_code == 422
