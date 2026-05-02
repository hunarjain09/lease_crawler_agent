"""GMI Cloud Claude Opus 4.7 inference for /analyze.

GMI's serverless `/chat/completions` is OpenAI-compatible, so we use the
`openai` SDK pointed at `GMI_LLM_BASE_URL` and authenticate with `GMI_API_KEY`.
"""

from __future__ import annotations

import json
import logging
import time
from functools import lru_cache
from typing import Any

from openai import AsyncOpenAI
from pydantic import ValidationError

from .extract import preprocess_for_analysis
from .log_setup import log_event
from .models import AnalyzeResponse, Leak, make_leak_id
from .settings import get_settings

logger = logging.getLogger("lease_crawler.inference")

SYSTEM_PROMPT = """You are a lease analyst. The user gives you the rendered \
content of an apartment / rental listing. Your job is to surface every \
"leak" -- anything in the listing that affects (a) total cost of occupancy, \
(b) lease flexibility, or (c) quality of life.

Examples of leaks: non-standard lease term (e.g. 14 months), furnished \
premium, parking fees, utilities not included, mandatory amenity fees, \
deposit size, short notice for availability, restrictive pet policies.

Return STRICT JSON in this exact shape and nothing else:
{
  "leaks": [
    {
      "id": "<short stable id, may be empty -- server fills it>",
      "source_url": "<echo of the source url provided, or empty>",
      "title": "<short label, e.g. 'Furnished premium'>",
      "severity": "low" | "med" | "high",
      "detail": "<one-sentence explanation citing concrete numbers>",
      "evidence": "<short verbatim quote from the listing, or null>"
    }
  ],
  "summary": "<2-3 sentence plain-English overview that names the base rent and lease term>"
}

Severity rubric:
- high: meaningfully changes total cost or makes the lease materially \
worse (e.g. 14-month term, large furnished premium, parking >$200/mo).
- med: notable but not deal-breaking (utility caps, amenity fees).
- low: informational (move-in date, short availability window).

Always include at least the base rent and the lease term as leaks if they \
appear in the content."""


@lru_cache(maxsize=1)
def _client() -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(
        base_url=settings.GMI_LLM_BASE_URL,
        api_key=settings.GMI_API_KEY or "missing-key",
        # GMI's per-minute quota is tight; the SDK respects Retry-After on 429.
        max_retries=5,
        timeout=60.0,
    )


def _build_user_message(content: str, context: list[Leak], source_url: str | None) -> str:
    """Compress the page content (units JSON or truncated HTML) before prompting.

    Without this, a 700KB Avalon page eats ~190K input tokens and trips GMI's
    per-minute quota; preprocess_for_analysis cuts this to <15K tokens.
    """
    payload, kind = preprocess_for_analysis(content)
    parts: list[str] = []
    if source_url:
        parts.append(f"Source URL: {source_url}")
    if context:
        ctx_dump = json.dumps([leak.model_dump() for leak in context], indent=2)
        parts.append(
            "Existing leaks already known for this user (avoid duplicates "
            "but you may refine):\n" + ctx_dump
        )
    parts.append(f"Listing content (kind={kind}):\n" + payload)
    return "\n\n".join(parts)


def _coerce_response(payload: dict[str, Any], source_url: str | None) -> AnalyzeResponse:
    """Validate model JSON, filling missing leak ids deterministically."""
    raw_leaks = payload.get("leaks") or []
    fixed: list[dict[str, Any]] = []
    for raw in raw_leaks:
        if not isinstance(raw, dict):
            continue
        leak = dict(raw)
        leak.setdefault("source_url", source_url or "")
        if not leak.get("source_url"):
            leak["source_url"] = source_url or ""
        title = str(leak.get("title", "")).strip()
        if not leak.get("id") and title:
            leak["id"] = make_leak_id(leak["source_url"], title)
        fixed.append(leak)
    summary = payload.get("summary") or ""
    return AnalyzeResponse.model_validate({"leaks": fixed, "summary": summary})


async def analyze(
    content: str,
    context: list[Leak] | None = None,
    source_url: str | None = None,
) -> AnalyzeResponse:
    """Call GMI Cloud and return the parsed AnalyzeResponse.

    On JSON parse / schema failure, retries exactly once with the parser
    error appended to the user message. A second failure raises.
    """
    settings = get_settings()
    context = list(context or [])
    user_message = _build_user_message(content, context, source_url)
    log_event(
        logger,
        "analyze.start",
        content_chars=len(content),
        user_msg_chars=len(user_message),
        context_leaks=len(context),
        source_url=source_url or "-",
        model=settings.GMI_LLM_MODEL,
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    client = _client()
    last_error: Exception | None = None
    for attempt in range(2):
        log_event(logger, "analyze.gmi_call", attempt=attempt + 1, model=settings.GMI_LLM_MODEL)
        call_start = time.perf_counter()
        completion = await client.chat.completions.create(
            model=settings.GMI_LLM_MODEL,
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=4096,
        )
        call_ms = round((time.perf_counter() - call_start) * 1000, 1)
        raw = completion.choices[0].message.content or ""
        usage = getattr(completion, "usage", None)
        log_event(
            logger,
            "analyze.gmi_response",
            attempt=attempt + 1,
            duration_ms=call_ms,
            output_chars=len(raw),
            tokens_in=getattr(usage, "prompt_tokens", "-") if usage else "-",
            tokens_out=getattr(usage, "completion_tokens", "-") if usage else "-",
        )
        try:
            payload = json.loads(raw)
            response = _coerce_response(payload, source_url)
            log_event(
                logger,
                "analyze.done",
                attempt=attempt + 1,
                leaks=len(response.leaks),
                summary_chars=len(response.summary),
            )
            return response
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            last_error = exc
            log_event(
                logger,
                "analyze.parse_error",
                attempt=attempt + 1,
                error=type(exc).__name__,
                detail=str(exc)[:200],
            )
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous response failed to parse with: "
                        f"{type(exc).__name__}: {exc}. Re-emit ONLY valid "
                        "JSON matching the schema; no prose, no code fence."
                    ),
                }
            )
            continue

    log_event(logger, "analyze.failed", error=type(last_error).__name__ if last_error else "unknown")
    raise RuntimeError(f"GMI inference failed to return valid JSON after retry: {last_error}")


ASK_SYSTEM_PROMPT = """You are a friendly assistant helping the user evaluate \
apartment listings they've shared. The user has discussed one or more rental \
properties; you have the structured leak findings (cost / flexibility / \
quality-of-life issues) and a short summary for each. You also have the \
running chat history.

Answer the user's latest question concisely and concretely. Cite specific \
numbers (rent, lease term, fees, square footage) whenever they appear in the \
known data. If the user asks something the data doesn't cover, say so plainly \
rather than inventing detail. Keep replies tight: 1-3 short sentences for \
factual asks, a short bulleted list when comparing units."""


async def ask(
    question: str,
    leaks: list[Leak] | None = None,
    summary: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> str:
    """Single-shot Q&A grounded in the user's known leaks + summary.

    `history` is the running chat in `[{"role": "user"|"assistant", "content": "..."}]`
    form (most recent last). The latest user `question` is appended on top.
    """
    settings = get_settings()
    leaks = list(leaks or [])
    history = list(history or [])

    log_event(
        logger,
        "ask.start",
        question_chars=len(question),
        context_leaks=len(leaks),
        history_turns=len(history),
        summary_chars=len(summary or ""),
        model=settings.GMI_LLM_MODEL,
    )

    context_blob = json.dumps(
        {
            "summary": summary or "",
            "leaks": [leak.model_dump() for leak in leaks],
        },
        indent=2,
    )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": ASK_SYSTEM_PROMPT},
        {
            "role": "system",
            "content": "Known apartment data (JSON):\n" + context_blob,
        },
        *history,
        {"role": "user", "content": question},
    ]

    client = _client()
    call_start = time.perf_counter()
    completion = await client.chat.completions.create(
        model=settings.GMI_LLM_MODEL,
        messages=messages,
        max_tokens=1024,
    )
    call_ms = round((time.perf_counter() - call_start) * 1000, 1)
    answer = (completion.choices[0].message.content or "").strip()
    usage = getattr(completion, "usage", None)
    log_event(
        logger,
        "ask.done",
        duration_ms=call_ms,
        answer_chars=len(answer),
        tokens_in=getattr(usage, "prompt_tokens", "-") if usage else "-",
        tokens_out=getattr(usage, "completion_tokens", "-") if usage else "-",
    )
    return answer
