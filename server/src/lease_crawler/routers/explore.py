"""POST /explore -- agentic loop: crawl + analyze + N rounds of self-Q&A.

GMI generates its own follow-up questions about the listing, answers each,
and stops when it decides nothing else is worth asking (or it hits max_rounds).
Returns the final leaks + summary + exploration trail + a synthesis paragraph
suitable for iMessage delivery.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, HttpUrl

from .. import crawler, inference
from ..log_setup import log_event
from ..models import Leak

router = APIRouter()
logger = logging.getLogger("lease_crawler.explore")


class ExploreRequest(BaseModel):
    url: HttpUrl
    max_rounds: int = Field(default=10, ge=1, le=20)


class ExplorationTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ExploreResponse(BaseModel):
    leaks: list[Leak]
    summary: str
    exploration: list[ExplorationTurn]
    synthesis: str
    rounds_used: int


_PROPOSE_PROMPT = (
    "Based on the listing data and the prior Q&A history, what is the single "
    "most useful next question a renter would want answered? Reply with ONLY "
    "the question (no preamble, no quotes). If nothing else is worth asking "
    "or the prior answers exhaust the listing, reply with the literal word DONE."
)

_SYNTHESIS_PROMPT = (
    "Using the leaks, the original summary, and everything learned in the Q&A "
    "exploration above, write a single tight paragraph (3-5 sentences) for an "
    "iMessage reply. Lead with the base rent and lease term. Mention the most "
    "expensive surprise. Call out anything important the listing did NOT "
    "disclose (fees, deposits, etc.) so the renter knows what to ask. No "
    "bullet points, no markdown headers, plain prose."
)


@router.post("/explore", response_model=ExploreResponse)
async def explore_route(req: ExploreRequest) -> ExploreResponse:
    url = str(req.url)
    log_event(logger, "explore.start", url=url, max_rounds=req.max_rounds)

    # 1. Crawl
    try:
        crawled = await crawler.crawl(url)
    except crawler.CrawlError as e:
        raise HTTPException(status_code=502, detail={"error": e.reason, "message": e.detail}) from e

    # 2. Analyze
    analyze_resp = await inference.analyze(content=crawled.content, context=[], source_url=url)

    # 3. Loop: propose -> answer, until DONE or max_rounds.
    history: list[dict[str, str]] = []
    rounds_used = 0
    for round_idx in range(req.max_rounds):
        log_event(logger, "explore.propose", round=round_idx + 1, max=req.max_rounds)
        proposed = await inference.ask(
            question=_PROPOSE_PROMPT,
            leaks=analyze_resp.leaks,
            summary=analyze_resp.summary,
            history=history,
        )
        proposed = proposed.strip().strip('"').strip("'")
        if not proposed or proposed.upper().startswith("DONE"):
            log_event(logger, "explore.stop_done", round=round_idx + 1)
            break

        log_event(logger, "explore.answer", round=round_idx + 1, q_chars=len(proposed))
        answer = await inference.ask(
            question=proposed,
            leaks=analyze_resp.leaks,
            summary=analyze_resp.summary,
            history=history,
        )

        history.append({"role": "user", "content": proposed})
        history.append({"role": "assistant", "content": answer})
        rounds_used = round_idx + 1

    # 4. Synthesis: one final pass to write the iMessage-friendly summary.
    synthesis = await inference.ask(
        question=_SYNTHESIS_PROMPT,
        leaks=analyze_resp.leaks,
        summary=analyze_resp.summary,
        history=history,
    )

    log_event(
        logger,
        "explore.done",
        url=url,
        rounds_used=rounds_used,
        leaks=len(analyze_resp.leaks),
        synthesis_chars=len(synthesis),
    )

    return ExploreResponse(
        leaks=analyze_resp.leaks,
        summary=analyze_resp.summary,
        exploration=[ExplorationTurn(role=t["role"], content=t["content"]) for t in history],
        synthesis=synthesis,
        rounds_used=rounds_used,
    )
