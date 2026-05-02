"""POST /crawl — render a URL with Obscura."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl

from .. import crawler

router = APIRouter()


class CrawlRequest(BaseModel):
    url: HttpUrl


class CrawlMetadata(BaseModel):
    url: str
    status: int
    fetched_at: datetime


class CrawlResponse(BaseModel):
    content: str
    metadata: CrawlMetadata


@router.post("/crawl", response_model=CrawlResponse)
async def crawl_route(req: CrawlRequest) -> CrawlResponse:
    try:
        result = await crawler.crawl(str(req.url))
    except crawler.CrawlError as e:
        raise HTTPException(status_code=502, detail={"error": e.reason, "message": e.detail}) from e

    return CrawlResponse(
        content=result.content,
        metadata=CrawlMetadata(url=result.url, status=result.status, fetched_at=result.fetched_at),
    )
