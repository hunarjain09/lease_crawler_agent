"""Pre-process raw page content before sending it to the LLM.

Many listing sites (Avalon and others built on similar platforms) embed a
clean ``"units": [...]`` JSON blob in the page. Extracting it gives the model
structured data instead of 700 KB of raw HTML, which:
  - keeps prompts under rate-limit budgets
  - improves answer quality (no parsing through markup)
  - reduces latency

Falls back to a length-capped slice of the original content if no structured
blob is found, so non-Avalon sites still get analyzed.
"""

from __future__ import annotations

import re

_UNITS_KEY = re.compile(r'"units"\s*:\s*\[')
_MAX_FALLBACK_CHARS = 60_000  # ~15K tokens — fits well under TPM caps


def _extract_balanced_array(text: str, start: int) -> str | None:
    """Return the JSON array starting at ``start`` (which must point to ``[``)."""
    if start >= len(text) or text[start] != "[":
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def extract_units_json(html: str) -> str | None:
    """Find ``"units":[ ... ]`` and return the array as a JSON string."""
    m = _UNITS_KEY.search(html)
    if not m:
        return None
    return _extract_balanced_array(html, m.end() - 1)


def preprocess_for_analysis(content: str) -> tuple[str, str]:
    """Return ``(payload, kind)`` ready for the LLM prompt.

    ``kind`` is one of ``"units_json"`` (structured blob) or ``"truncated_html"``
    (length-capped fallback). The caller should mention ``kind`` in the prompt
    so the model knows what shape to expect.
    """
    units = extract_units_json(content)
    if units is not None:
        return units, "units_json"
    if len(content) > _MAX_FALLBACK_CHARS:
        return content[:_MAX_FALLBACK_CHARS], "truncated_html"
    return content, "truncated_html"
