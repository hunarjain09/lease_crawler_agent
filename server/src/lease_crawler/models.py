"""Pydantic schemas shared across routes and inference."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, Field


def make_leak_id(source_url: str, title: str) -> str:
    """Stable 12-char hex id derived from (source_url, title).

    Used for deduplication in the agent's running state. The hash inputs are
    joined with a NUL byte so that "ab" + "c" and "a" + "bc" don't collide.
    """
    digest = hashlib.sha256(f"{source_url}\0{title}".encode("utf-8")).hexdigest()
    return digest[:12]


class Leak(BaseModel):
    id: str
    source_url: str
    title: str
    severity: Literal["low", "med", "high"]
    detail: str
    evidence: str | None = None


class AnalyzeRequest(BaseModel):
    content: str
    context: list[Leak] = Field(default_factory=list)


class AnalyzeResponse(BaseModel):
    leaks: list[Leak]
    summary: str
