"""POST /analyze -- run GMI inference over crawled listing content.

Wired into `main.py` at merge time:

    from lease_crawler.routers import analyze as analyze_router
    app.include_router(analyze_router.router)
"""

from __future__ import annotations

from fastapi import APIRouter

from .. import inference
from ..models import AnalyzeRequest, AnalyzeResponse

router = APIRouter()


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_endpoint(req: AnalyzeRequest) -> AnalyzeResponse:
    return await inference.analyze(content=req.content, context=req.context)
