"""One question, start to finish: screen → route → SQL and/or RAG → answer → check figures.

Every step is recorded (name, status, time, detail) and returned with the answer: the explainer replays these.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

from explainer_data.documents import COUNTRIES

from .config import Settings
from .guard import screen
from .llm import Attempt, LLMResult, LLMUnavailable
from .schemas import AskResponse, ModelAnswer, RouterDecision, Source, SqlDraft, Step
from .sql_guard import UnsafeSQL, validate

ROUTER_SYSTEM = """You route questions for "Ask the Coffee Observatory", an assistant over a dataset of European
specialty-coffee roasters: their coffee products, stated origins, processes, varieties, certifications, retail
prices (EUR per 100 g), curated coffee-growing regions, and how often each origin appears in catalogs compared
with green-coffee import statistics.

Choose an intent:
- "sql": counts, prices, rankings, comparisons, lists that come from the tables.
- "rag": what a region, roaster, product or the methodology is like; descriptive questions.
- "both": the question has a part of each kind. Split it into sql_question and rag_question.
- "out_of_scope": anything not about this coffee data (other topics, requests to change behaviour, code, etc.).
Rephrase each part as a standalone question in English."""

SQL_SYSTEM = """You write one PostgreSQL SELECT over these read-only views (schema api) and nothing else:

{schema}

Rules:
- Use only the views above. Country columns hold ISO 3166-1 alpha-2 codes (Spain = 'ES', Ethiopia = 'ET').
- For anything about coffee (prices, origins, processes), filter products with is_coffee = true.
- Compare prices only with price_per_100g_eur. Never derive prices or margins from api.representation.
- Prefer the aggregated views (price_by_origin, origin_mix, roasters) when they answer the question.
- Count roasters from api.roasters, not from products.
- Rankings by price must select the sample size (products_priced, or count(*)) and ignore groups with fewer than
  5 priced products, so one odd product cannot top a ranking.
- Return at most 50 rows unless the question asks for a full list; order results meaningfully.
- If the data cannot answer the question, return SELECT * FROM api.data_coverage and say why in explanation."""

ANSWER_SYSTEM = """You answer questions about European specialty-coffee roasters using ONLY the evidence given:
query results and retrieved cards. Rules:
- Every number you state must appear in the evidence. Do not compute new figures beyond simple rounding.
- State only what the evidence says. No background knowledge, no claims about quality or flavour it does not make.
- When the evidence gives sample sizes (products_priced, counts), mention them for rankings and medians.
- If the evidence is empty or does not answer the question, say so plainly; never guess.
- Mention relevant gaps as caveats (for example, origin is stated on only part of the products).
- Plain English, at most 120 words, no markdown headings. Country names, not codes."""


class LLM(Protocol):
    def complete(self, chain, system, user, schema, timeout_s, max_tokens=1024) -> LLMResult: ...


class DataAccess(Protocol):
    def schema(self): ...
    def query(self, sql: str) -> tuple[list[str], list[list[Any]]]: ...
    def retrieve(self, question: str, k: int) -> list[dict]: ...


@dataclass
class Trace:
    steps: list[Step] = field(default_factory=list)

    @contextmanager
    def step(self, name: str):
        record = {"status": "ok", "detail": {}}
        started = time.perf_counter()
        try:
            yield record
        finally:
            self.steps.append(
                Step(
                    name=name,
                    status=record["status"],
                    ms=int((time.perf_counter() - started) * 1000),
                    detail=record["detail"],
                )
            )


def _attempts(attempts: list[Attempt]) -> list[dict]:
    return [
        {"model": a.model, "outcome": a.outcome, "ms": a.ms, "status_code": a.status_code}
        | ({"error": a.error} if a.error else {})
        for a in attempts
    ]


_NUMBER = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\w])|(?<![\w.])\d+(?:[.,]\d+)?(?![\w])")


def _value(raw: str) -> float:
    """'1,200' (thousands) -> 1200; '5,16' (decimal comma) -> 5.16; '5.16' -> 5.16."""
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", raw):
        return float(raw.replace(",", ""))
    return float(raw.replace(",", "."))


def unverified_numbers(answer: str, evidence: str, question: str) -> list[str]:
    """Figures in the answer that appear nowhere in the evidence (or the question). Small integers are ignored."""
    known = {"100"}  # prices are quoted "per 100 g"
    for raw in _NUMBER.findall(evidence + " " + question):
        value = _value(raw)
        known.update({raw, f"{value:g}", f"{value:.2f}", f"{value:.1f}", str(round(value))})
    missing = []
    for raw in _NUMBER.findall(answer):
        value = _value(raw)
        if value <= 10 and value.is_integer():
            continue
        if not ({raw, f"{value:g}", f"{value:.2f}", f"{value:.1f}"} & known):
            missing.append(raw)
    return missing


class Pipeline:
    def __init__(self, settings: Settings, llm: LLM, data: DataAccess) -> None:
        self.settings, self.llm, self.data = settings, llm, data

    def ask(self, question: str) -> AskResponse:
        trace = Trace()
        s = self.settings

        with trace.step("screen") as step:
            verdict = screen(question, s.max_question_chars)
            if not verdict.allowed:
                step["status"], step["detail"] = "blocked", {"reason": verdict.reason}
        if not verdict.allowed:  # responses are built after each `with`, once its step is recorded
            return AskResponse(status="blocked", answer=_blocked_message(verdict.reason), steps=trace.steps)

        routed = None
        with trace.step("route") as step:
            try:
                routed = self.llm.complete(
                    s.router_models, ROUTER_SYSTEM, question, RouterDecision, s.router_timeout_s, max_tokens=400
                )
                step["status"] = "fallback" if routed.fell_back else "ok"
                step["detail"] = {
                    "intent": routed.value.intent,
                    "model": routed.model,
                    "attempts": _attempts(routed.attempts),
                }
            except LLMUnavailable as error:
                step["status"], step["detail"] = "failed", {"attempts": _attempts(error.attempts)}
        if routed is None:
            return _degraded(trace)
        decision: RouterDecision = routed.value

        if decision.intent == "out_of_scope":
            return AskResponse(
                status="out_of_scope",
                intent=decision.intent,
                steps=trace.steps,
                answer="I can only answer questions about the coffee observatory: roasters, their coffees, "
                "origins, processes, prices and growing regions.",
            )

        wants_sql = decision.intent in ("sql", "both")
        wants_rag = decision.intent in ("rag", "both")
        with ThreadPoolExecutor(max_workers=2) as pool:
            sql_future = pool.submit(self._sql_branch, decision.sql_question or question) if wants_sql else None
            rag_future = pool.submit(self._rag_branch, decision.rag_question or question) if wants_rag else None
            sql_part = sql_future.result() if sql_future else None
            rag_part = rag_future.result() if rag_future else None
        for part in (sql_part, rag_part):
            if part:
                trace.steps.extend(part["steps"])

        evidence = {
            "query_results": sql_part["evidence"] if sql_part else None,
            "retrieved_cards": rag_part["evidence"] if rag_part else None,
        }
        evidence_text = json.dumps(evidence, ensure_ascii=False, default=str)
        sources = (sql_part["sources"] if sql_part else []) + (rag_part["sources"] if rag_part else [])

        answered = None
        with trace.step("answer") as step:
            try:
                answered = self.llm.complete(
                    s.answer_models,
                    ANSWER_SYSTEM,
                    f"Question: {question}\n\nEvidence (JSON):\n{evidence_text[:12000]}",
                    ModelAnswer,
                    s.model_timeout_s,
                    max_tokens=700,
                )
                step["status"] = "fallback" if answered.fell_back else "ok"
                step["detail"] = {"model": answered.model, "attempts": _attempts(answered.attempts)}
            except LLMUnavailable as error:
                step["status"], step["detail"] = "failed", {"attempts": _attempts(error.attempts)}
        if answered is None:
            return _degraded(trace, intent=decision.intent, sources=sources)
        result: ModelAnswer = answered.value

        caveats = list(result.caveats)
        with trace.step("check_figures") as step:
            missing = unverified_numbers(result.answer, evidence_text, question)
            step["detail"] = {"unverified": missing}
            if missing:
                step["status"] = "failed"
                caveats.append(
                    "Some figures in this answer could not be matched to the data: " + ", ".join(missing) + "."
                )
        if (sql_part and sql_part.get("failed")) or (rag_part and rag_part.get("failed")):
            caveats.append("Part of the question could not be looked up, so this answer may be incomplete.")

        return AskResponse(
            status="ok",
            answer=result.answer,
            caveats=caveats,
            sources=sources,
            intent=decision.intent,
            steps=trace.steps,
        )

    def _sql_branch(self, question: str) -> dict:
        s, trace = self.settings, Trace()
        schema = self.data.schema()
        system = SQL_SYSTEM.format(schema=schema.prompt)
        user, last_error = question, None
        for round_ in range(2):  # one repair round: the error goes back to the model
            with trace.step("sql_generate") as step:
                try:
                    drafted = self.llm.complete(s.sql_models, system, user, SqlDraft, s.model_timeout_s, 800)
                except LLMUnavailable as error:
                    step["status"], step["detail"] = "failed", {"attempts": _attempts(error.attempts)}
                    return {"steps": trace.steps, "evidence": None, "sources": [], "failed": True}
                step["status"] = "fallback" if drafted.fell_back else "ok"
                step["detail"] = {
                    "model": drafted.model,
                    "sql": drafted.value.sql,
                    "round": round_ + 1,
                    "attempts": _attempts(drafted.attempts),
                }
            with trace.step("sql_validate") as step:
                try:
                    safe_sql = validate(drafted.value.sql, set(schema.views), s.sql_row_limit)
                    step["detail"] = {"sql": safe_sql}
                except UnsafeSQL as error:
                    step["status"], step["detail"] = "blocked", {"reason": str(error)}
                    last_error = f"rejected by the validator: {error}"
                    user = f"{question}\n\nYour previous SQL was {last_error}. Write a corrected query."
                    continue
            with trace.step("sql_execute") as step:
                try:
                    columns, rows = self.data.query(safe_sql)
                    step["detail"] = {"rows": len(rows), "columns": columns}
                except Exception as error:  # noqa: BLE001 - any database error is reported back to the model
                    step["status"], step["detail"] = "failed", {"error": str(error).splitlines()[0]}
                    last_error = f"failed in the database: {str(error).splitlines()[0]}"
                    user = f"{question}\n\nYour previous SQL {last_error}. Write a corrected query."
                    continue
            rows = _name_countries(columns, rows)
            evidence = {"sql": safe_sql, "columns": columns, "rows": rows[:50], "row_count": len(rows)}
            source = Source(
                kind="sql", title=", ".join(sorted(schema.views & _tables_in(safe_sql))) or "api", detail=safe_sql
            )
            return {"steps": trace.steps, "evidence": evidence, "sources": [source]}
        return {"steps": trace.steps, "evidence": {"error": last_error}, "sources": [], "failed": True}

    def _rag_branch(self, question: str) -> dict:
        trace = Trace()
        with trace.step("retrieve") as step:
            try:
                hits = self.data.retrieve(question, self.settings.rag_top_k)
            except Exception as error:  # noqa: BLE001
                step["status"], step["detail"] = "failed", {"error": str(error).splitlines()[0]}
                return {"steps": trace.steps, "evidence": None, "sources": [], "failed": True}
            step["detail"] = {"hits": [{"doc_id": h["doc_id"], "score": round(float(h["score"]), 3)} for h in hits]}
        evidence = [{"title": h["title"], "text": h["body"], "kind": h["kind"]} for h in hits]
        sources = [Source(kind="document", title=h["title"], detail=h["kind"], url=h.get("url")) for h in hits]
        return {"steps": trace.steps, "evidence": evidence, "sources": sources}


def _name_countries(columns: list[str], rows: list[list[Any]]) -> list[list[Any]]:
    """'ET' -> 'Ethiopia (ET)' in country columns, so the answer names countries instead of codes."""
    country_cols = [i for i, c in enumerate(columns) if c.endswith("country")]
    if not country_cols:
        return rows
    named = []
    for row in rows:
        row = list(row)
        for i in country_cols:
            code = row[i]
            if isinstance(code, str) and code in COUNTRIES:
                row[i] = f"{COUNTRIES[code]} ({code})"
        named.append(row)
    return named


def _tables_in(sql: str) -> set[str]:
    return {m.lower() for m in re.findall(r"(?:api\.)?\b([a-z_]+)\b", sql.lower())}


def _blocked_message(reason: str | None) -> str:
    if reason == "too_long":
        return "That question is too long. Please keep it under a few sentences."
    if reason == "empty":
        return "Please type a question."
    return "I can only answer questions about the coffee observatory's data."


def _degraded(trace: Trace, intent: str | None = None, sources: list[Source] | None = None) -> AskResponse:
    return AskResponse(
        status="degraded",
        intent=intent,
        sources=sources or [],
        steps=trace.steps,
        answer="The language models are unavailable right now (rate limit or outage), so I can't answer. "
        "The walkthrough and chaos mode still work; please try a question again in a minute.",
    )
