"""Pre-process raw page content before sending it to the LLM.

Many listing sites embed structured data in the page that's far more useful
to the model than 700 KB of raw HTML. Extracting it:
  - keeps prompts under rate-limit budgets
  - improves answer quality (no parsing through markup)
  - reduces latency

Three extractors, in order of preference:
  1. ``"units":[...]`` JSON blob — per-listing pages (Avalon Silicon Valley etc.)
  2. Fusion CMS communities — overview / search pages where a 126KB
     ``window.Fusion`` blob holds per-community pricing (AvalonBay's SF page,
     etc.). We pull the smallest balanced JSON object containing each
     ``"communityName"`` key.
  3. Length-capped HTML slice — generic fallback for non-Avalon sites.
"""

from __future__ import annotations

import json
import re

_UNITS_KEY = re.compile(r'"units"\s*:\s*\[')
_FUSION_MARKER = '"communityName"'
_SCRIPT_BLOCK_RE = re.compile(r"<script[^>]*>(.*?)</script>", re.S)
_MAX_FALLBACK_CHARS = 60_000  # ~15K tokens — fits well under TPM caps
_MAX_FUSION_CHARS = 60_000  # cap the fusion JSON dump too — defensive


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


def extract_fusion_communities(html: str) -> str | None:
    """Find per-community records in a Fusion CMS data blob.

    Walks the largest ``<script>`` block that contains ``"communityName"``,
    finds the smallest balanced ``{...}`` enclosing each ``"communityName"``
    key, parses each as JSON, and returns a compact JSON array.

    Returns ``None`` when no Fusion-style blob is present (so the caller can
    fall back to truncation).
    """
    # Prefer the largest <script> block that contains our marker.
    candidates = [m.group(1) for m in _SCRIPT_BLOCK_RE.finditer(html) if _FUSION_MARKER in m.group(1)]
    if not candidates:
        return None
    blob = max(candidates, key=len)

    # Locate every "communityName" position in the blob.
    marker_positions = [m.start() for m in re.finditer(re.escape(_FUSION_MARKER), blob)]
    if not marker_positions:
        return None
    marker_positions_set = set(marker_positions)

    # Forward walk: track open-brace positions in a stack. On each close,
    # check which markers fall inside the just-closed range; record the
    # SMALLEST enclosing range per marker.
    smallest: dict[int, tuple[int, int]] = {}
    stack: list[int] = []
    in_str = False
    escape = False
    sorted_markers = sorted(marker_positions)

    for i, ch in enumerate(blob):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            start = stack.pop()
            end = i + 1
            # Find markers inside [start, end). Bisect for speed.
            lo = _bisect_left(sorted_markers, start)
            hi = _bisect_left(sorted_markers, end)
            for mpos in sorted_markers[lo:hi]:
                cur = smallest.get(mpos)
                if cur is None or (end - start) < (cur[1] - cur[0]):
                    smallest[mpos] = (start, end)

    if not smallest:
        return None

    # Dedupe ranges (multiple markers in the same record map to one range).
    unique_ranges = sorted(set(smallest.values()))

    communities: list[dict] = []
    for start, end in unique_ranges:
        try:
            obj = json.loads(blob[start:end])
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict) and "communityName" in obj:
            communities.append(obj)

    if not communities:
        return None

    payload = json.dumps(communities, separators=(",", ":"))
    if len(payload) > _MAX_FUSION_CHARS:
        # Aggressive cap: drop big optional fields and re-emit, then truncate
        # by community count if still too big.
        slim = [_slim_community(c) for c in communities]
        payload = json.dumps(slim, separators=(",", ":"))
        while len(payload) > _MAX_FUSION_CHARS and len(slim) > 1:
            slim.pop()
            payload = json.dumps(slim, separators=(",", ":"))
    return payload


def _bisect_left(arr: list[int], target: int) -> int:
    """Stdlib bisect inlined to avoid the import. Returns the leftmost insertion point."""
    lo, hi = 0, len(arr)
    while lo < hi:
        mid = (lo + hi) // 2
        if arr[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    return lo


# Fields worth keeping when we have to slim records to fit under the size cap.
# These cover both the Avalon "unit" shape (per-unit records on overview pages)
# AND the generic community shape some sites use. Add new field names as we
# encounter them — being conservative drops too much data.
_SLIM_KEEP = {
    # identity
    "unitId", "unitName", "propertyId", "communityId", "communityName", "id",
    # location
    "address", "addressLine1", "city", "state", "zip", "url", "name",
    # unit characteristics
    "bedroomNumber", "bathroomNumber", "squareFeet",
    "beds", "baths", "sqft", "bedrooms",
    # pricing — Avalon's startingAtPrices*Unfurnished/Furnished is the gold
    "startingAtPricesUnfurnished", "startingAtPricesFurnished",
    "minRent", "maxRent", "priceRange", "pricingDescription",
    # availability
    "availableDateUnfurnished", "availableDateFurnished",
    "availability", "availableFrom",
    # promotions are useful context for "leak" extraction
    "promotions",
    # generic
    "communityCode",
}


def _slim_community(obj: dict) -> dict:
    """Drop bulky narrative/marketing fields, keep pricing-relevant ones."""
    out: dict = {}
    for k, v in obj.items():
        if k in _SLIM_KEEP:
            out[k] = v
    return out


def preprocess_for_analysis(content: str) -> tuple[str, str]:
    """Return ``(payload, kind)`` ready for the LLM prompt.

    ``kind`` is one of:
      - ``"units_json"``: per-listing units array (Avalon Silicon Valley shape)
      - ``"fusion_communities"``: per-community pricing JSON (Avalon SF overview)
      - ``"truncated_html"``: generic length-capped fallback

    Caller should mention ``kind`` in the prompt so the model knows the shape.
    """
    units = extract_units_json(content)
    if units is not None:
        return units, "units_json"
    fusion = extract_fusion_communities(content)
    if fusion is not None:
        return fusion, "fusion_communities"
    if len(content) > _MAX_FALLBACK_CHARS:
        return content[:_MAX_FALLBACK_CHARS], "truncated_html"
    return content, "truncated_html"
