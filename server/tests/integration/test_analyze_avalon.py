"""Integration test for /analyze against the real GMI endpoint, recorded once.

Runs from a VCR cassette in CI; only when explicitly recording (`--record-mode=once`
or `=new_episodes`) does it touch the real GMI Cloud API. The Authorization
header is filtered out so the cassette is safe to commit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from lease_crawler import inference

FIXTURE = Path(__file__).parent / "fixtures" / "avalon_silicon_valley_min.html"
SOURCE_URL = (
    "https://www.avaloncommunities.com/california/sunnyvale-apartments/avalon-silicon-valley/"
)


@pytest.fixture
def vcr_cassette_dir(request: pytest.FixtureRequest) -> str:
    """Pin cassettes to `tests/integration/cassettes/` (no per-module subdir)."""
    return str(Path(__file__).parent / "cassettes")


@pytest.fixture(scope="module")
def vcr_config() -> dict:
    """Sanitize cassettes: never persist API credentials."""
    return {
        "filter_headers": [
            ("authorization", "DUMMY"),
            ("Authorization", "DUMMY"),
            ("api-key", "DUMMY"),
            ("openai-organization", "DUMMY"),
            ("x-organization-id", "DUMMY"),
        ],
        "decode_compressed_response": True,
    }


@pytest.fixture(autouse=True)
def _reset_inference_client() -> None:
    inference._client.cache_clear()
    yield
    inference._client.cache_clear()


@pytest.mark.integration
@pytest.mark.vcr
async def test_analyze_avalon() -> None:
    content = FIXTURE.read_text(encoding="utf-8")
    result = await inference.analyze(content=content, context=[], source_url=SOURCE_URL)

    assert len(result.leaks) >= 3, f"expected >=3 leaks, got {len(result.leaks)}"

    # At least one leak about the furnished premium with severity med/high.
    furnished = [
        leak
        for leak in result.leaks
        if re.search(r"furnished", leak.title, re.IGNORECASE)
        and leak.severity in {"med", "high"}
    ]
    assert furnished, f"no furnished med/high leak in {[l.model_dump() for l in result.leaks]}"

    # Some leak references the 14-month lease term.
    lease_term = [
        leak
        for leak in result.leaks
        if re.search(r"14[-\s]?month|lease.*term", f"{leak.title} {leak.detail}", re.IGNORECASE)
    ]
    assert lease_term, "no leak referencing the 14-month lease term"

    # Summary mentions the base rent.
    assert "3,415" in result.summary or "3415" in result.summary
