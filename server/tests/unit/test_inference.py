"""Unit tests for `inference.analyze` against a mocked GMI endpoint.

We mock the OpenAI-compatible `/chat/completions` route with respx so no
network is touched.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from lease_crawler import inference
from lease_crawler.inference import analyze
from lease_crawler.models import Leak

GMI_URL = "https://api.gmi-serving.com/v1/chat/completions"


def _completion(content: str) -> dict:
    return {
        "id": "chatcmpl-test",
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
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


@pytest.fixture(autouse=True)
def _reset_inference_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test gets a fresh AsyncOpenAI client bound to a known fake key."""
    monkeypatch.setenv("GMI_API_KEY", "test-key")
    inference._client.cache_clear()
    yield
    inference._client.cache_clear()


@pytest.mark.unit
async def test_analyze_happy_path() -> None:
    payload = {
        "leaks": [
            {
                "id": "deadbeef0001",
                "source_url": "https://example.com/listing",
                "title": "Base rent",
                "severity": "med",
                "detail": "$3,415/mo on a 14-month term.",
                "evidence": "$3,415 / 14-mo",
            }
        ],
        "summary": "Base rent $3,415 on a 14-month lease.",
    }
    with respx.mock(assert_all_called=True) as mock:
        mock.post(GMI_URL).mock(
            return_value=httpx.Response(200, json=_completion(json.dumps(payload)))
        )
        result = await analyze(content="<html>...</html>", context=[], source_url="https://example.com/listing")
    assert len(result.leaks) == 1
    assert result.leaks[0].title == "Base rent"
    assert result.summary.startswith("Base rent $3,415")


@pytest.mark.unit
async def test_analyze_retries_once_on_malformed_json() -> None:
    bad = "not-json {{"
    good = json.dumps({"leaks": [], "summary": "ok"})
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(GMI_URL).mock(
            side_effect=[
                httpx.Response(200, json=_completion(bad)),
                httpx.Response(200, json=_completion(good)),
            ]
        )
        result = await analyze(content="x", context=[])
    assert route.call_count == 2
    assert result.summary == "ok"
    assert result.leaks == []


@pytest.mark.unit
async def test_analyze_raises_after_second_failure() -> None:
    bad = "still-not-json"
    with respx.mock(assert_all_called=True) as mock:
        mock.post(GMI_URL).mock(
            side_effect=[
                httpx.Response(200, json=_completion(bad)),
                httpx.Response(200, json=_completion(bad)),
            ]
        )
        with pytest.raises(RuntimeError, match="failed to return valid JSON"):
            await analyze(content="x", context=[])


@pytest.mark.unit
async def test_analyze_fills_missing_leak_ids() -> None:
    payload = {
        "leaks": [
            {
                "source_url": "",
                "title": "Furnished premium",
                "severity": "high",
                "detail": "$1,281/mo extra for furnished.",
            }
        ],
        "summary": "s",
    }
    source_url = "https://example.com/listing"
    with respx.mock() as mock:
        mock.post(GMI_URL).mock(
            return_value=httpx.Response(200, json=_completion(json.dumps(payload)))
        )
        result = await analyze(content="x", context=[], source_url=source_url)
    leak = result.leaks[0]
    assert len(leak.id) == 12
    assert leak.source_url == source_url


@pytest.mark.unit
async def test_analyze_includes_context_in_prompt() -> None:
    """When context is passed, it should appear in the user message body."""
    payload = {"leaks": [], "summary": "s"}
    captured: dict[str, object] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_completion(json.dumps(payload)))

    ctx = [
        Leak(
            id="abc123",
            source_url="https://example.com",
            title="Prior leak",
            severity="low",
            detail="...",
        )
    ]
    with respx.mock() as mock:
        mock.post(GMI_URL).mock(side_effect=_handler)
        await analyze(content="x", context=ctx)

    body = captured["body"]
    assert isinstance(body, dict)
    user_msg = next(m for m in body["messages"] if m["role"] == "user")
    assert "Prior leak" in user_msg["content"]
