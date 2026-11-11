"""Shapes the models must return, and the API's own request and response."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RouterDecision(BaseModel):
    intent: Literal["sql", "rag", "both", "out_of_scope"]
    sql_question: str | None = Field(None, description="The part answerable from the tables, rephrased.")
    rag_question: str | None = Field(None, description="The part answerable from descriptive cards, rephrased.")


class SqlDraft(BaseModel):
    sql: str
    explanation: str = ""


class ModelAnswer(BaseModel):
    answer: str
    caveats: list[str] = Field(default_factory=list)


class AskRequest(BaseModel):
    question: str = Field(min_length=1)


class Source(BaseModel):
    kind: Literal["sql", "document"]
    title: str
    detail: str | None = None
    url: str | None = None


class Step(BaseModel):
    """One step of the request, in the order it ran. The explainer replays these (v2)."""

    name: str
    status: Literal["ok", "fallback", "failed", "skipped", "blocked"]
    ms: int
    detail: dict = Field(default_factory=dict)


class AskResponse(BaseModel):
    status: Literal["ok", "degraded", "blocked", "out_of_scope", "rate_limited", "disabled"]
    answer: str
    caveats: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    intent: str | None = None
    data_version: str | None = None
    steps: list[Step] = Field(default_factory=list)
