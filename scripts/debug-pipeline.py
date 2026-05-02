#!/usr/bin/env python3
"""Debug a single URL + N questions through the full pipeline, showing
intermediate state at each stage so we can see WHERE data is lost.

Usage:
  uv run --project server scripts/debug-pipeline.py <URL>
  uv run --project server scripts/debug-pipeline.py <URL> "question 1" "question 2"

Run from repo root. Requires the server's deps to be sync'd (uv sync in server/).

Differs from scripts/test-pipeline.sh: this calls the Python modules directly
(no HTTP), so we can introspect what extract.py emitted, what GMI was sent,
and the token usage on every call.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

# Make the server package importable.
sys.path.insert(0, str(Path(__file__).parent.parent / "server" / "src"))

from lease_crawler import crawler, inference  # noqa: E402
from lease_crawler.extract import preprocess_for_analysis  # noqa: E402


def banner(title: str) -> None:
    bar = "=" * 78
    print(f"\n{bar}\n  {title}\n{bar}")


def show_payload_intel(payload: str, label: str) -> None:
    print(f"\n[{label}]")
    print(f"  size: {len(payload):,} chars (~{len(payload) // 4:,} tokens)")
    keys = {
        "$X,XXX rent": r"\$[1-9][\d,]+",
        "minRent/maxRent": r"minRent|maxRent",
        "1 bed / 1bd / 1BR": r"\b1[\s-]?(?:bed|bd|br)\b",
        "2 bed / 2bd / 2BR": r"\b2[\s-]?(?:bed|bd|br)\b",
        "studio": r"studio",
        "AVA / Avalon": r"\b(?:AVA|Avalon)\b",
        "communityName": r"communityName",
        "Fusion content blob": r"Fusion\s*=\s*Fusion",
    }
    for name, pat in keys.items():
        n = len(re.findall(pat, payload, re.I))
        marker = "✓" if n > 0 else "✗"
        print(f"  {marker} {name:30s} {n:5d} matches")


async def run(url: str, questions: list[str]) -> None:
    banner(f"DEBUG: {url}")

    # 1) CRAWL
    print("\n[1/3] CRAWL")
    print(f"  → {url}")
    crawled = await crawler.crawl(url)
    print(f"  ← status={crawled.status} backend={crawled.backend} bytes={len(crawled.content):,}")
    show_payload_intel(crawled.content, "raw HTML")

    # 2) EXTRACT (the interesting middle layer)
    print("\n[2/3] EXTRACT (preprocess_for_analysis)")
    payload, kind = preprocess_for_analysis(crawled.content)
    print(f"  kind={kind} (truncated_html means the units-JSON extractor MISSED)")
    show_payload_intel(payload, f"extracted payload ({kind})")

    # If we lost the Fusion blob, surface it
    if "Fusion" in crawled.content and "Fusion" not in payload[:5000]:
        print("  ⚠ Fusion CMS blob is NOT in the first 5KB of payload — likely truncated.")

    # 3) ANALYZE (full GMI call, returns the leak/summary structure)
    print("\n[3/3] ANALYZE → GMI")
    analyze_resp = await inference.analyze(content=crawled.content, context=[], source_url=url)
    print(f"  ← {len(analyze_resp.leaks)} leaks, summary {len(analyze_resp.summary)} chars")
    print(f"\nSUMMARY: {analyze_resp.summary}")
    print(f"\nLEAKS:")
    for leak in analyze_resp.leaks:
        print(f"  [{leak.severity}] {leak.title}")
        print(f"        {leak.detail[:140]}")

    # 4) ASK each question (with full leak context)
    if questions:
        history: list[dict[str, str]] = []
        banner(f"QUESTIONS ({len(questions)})")
        for i, q in enumerate(questions, 1):
            print(f"\nQ{i}: {q}")
            answer = await inference.ask(
                question=q,
                leaks=analyze_resp.leaks,
                summary=analyze_resp.summary,
                history=history,
            )
            print(f"A{i}: {answer}")
            history.append({"role": "user", "content": q})
            history.append({"role": "assistant", "content": answer})

    banner("DONE")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    url = sys.argv[1]
    questions = sys.argv[2:]
    asyncio.run(run(url, questions))


if __name__ == "__main__":
    main()
