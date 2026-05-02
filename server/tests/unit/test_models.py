"""Unit tests for pydantic models and helpers."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from lease_crawler.models import AnalyzeRequest, AnalyzeResponse, Leak, make_leak_id


@pytest.mark.unit
def test_make_leak_id_is_deterministic() -> None:
    a = make_leak_id("https://example.com/x", "Furnished premium")
    b = make_leak_id("https://example.com/x", "Furnished premium")
    assert a == b
    assert len(a) == 12
    assert all(c in "0123456789abcdef" for c in a)


@pytest.mark.unit
def test_make_leak_id_changes_on_input() -> None:
    a = make_leak_id("https://example.com/x", "Furnished premium")
    b = make_leak_id("https://example.com/y", "Furnished premium")
    c = make_leak_id("https://example.com/x", "14-month lease term")
    assert a != b
    assert a != c


@pytest.mark.unit
def test_make_leak_id_no_boundary_collision() -> None:
    # NUL separator prevents (ab,c) vs (a,bc) collisions.
    assert make_leak_id("ab", "c") != make_leak_id("a", "bc")


@pytest.mark.unit
def test_leak_severity_validation() -> None:
    leak = Leak(
        id="abc123",
        source_url="https://example.com",
        title="Rent",
        severity="high",
        detail="$3,415/mo",
    )
    assert leak.evidence is None
    with pytest.raises(ValidationError):
        Leak(
            id="abc123",
            source_url="https://example.com",
            title="Rent",
            severity="critical",  # type: ignore[arg-type]
            detail="$3,415/mo",
        )


@pytest.mark.unit
def test_analyze_request_defaults() -> None:
    req = AnalyzeRequest(content="hi")
    assert req.context == []


@pytest.mark.unit
def test_analyze_response_roundtrip() -> None:
    resp = AnalyzeResponse(
        leaks=[
            Leak(
                id=make_leak_id("u", "t"),
                source_url="u",
                title="t",
                severity="med",
                detail="d",
            )
        ],
        summary="s",
    )
    dumped = resp.model_dump()
    again = AnalyzeResponse.model_validate(dumped)
    assert again == resp
