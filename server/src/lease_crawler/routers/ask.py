"""POST /ask -- conversational Q&A grounded in known leaks + summary."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import inference
from ..models import Leak

router = APIRouter()


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    leaks: list[Leak] = []
    summary: str | None = None
    history: list[ChatTurn] = []


class AskResponse(BaseModel):
    answer: str


@router.post("/ask", response_model=AskResponse)
async def ask_route(req: AskRequest) -> AskResponse:
    answer = await inference.ask(
        question=req.question,
        leaks=req.leaks,
        summary=req.summary,
        history=[turn.model_dump() for turn in req.history],
    )
    return AskResponse(answer=answer)
