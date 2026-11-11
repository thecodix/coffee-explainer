"""HTTP surface: POST /ask, GET /meta, GET /health.

Run: ``uvicorn coffee_api.app:app --port 8020`` with READER_DATABASE_URL and GROQ_API_KEY set.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings
from .data import Data
from .llm import GroqClient
from .pipeline import Pipeline
from .ratelimit import RateLimiter
from .schemas import AskRequest, AskResponse

LIMIT_MESSAGES = {
    "per_ip_per_minute": "Too many questions in a minute. Wait a moment and try again.",
    "per_ip_per_day": "You've reached today's question limit. The walkthrough and chaos mode still work.",
    "daily_quota": "The demo has used today's question budget. The walkthrough and chaos mode still work.",
}


def create_app(settings: Settings | None = None, pipeline: Pipeline | None = None, data: Data | None = None) -> FastAPI:
    settings = settings or Settings()
    state: dict = {"data": data, "pipeline": pipeline}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if state["pipeline"] is None:
            state["data"] = Data(settings.database_url, settings.embedding_model)
            state["data"].open()
            state["data"].embedder.embed(["warm-up"])  # load the model now, not on the first question
            state["pipeline"] = Pipeline(
                settings, GroqClient(settings.groq_api_key, settings.groq_base_url), state["data"]
            )
        yield
        if state["data"] is not None and data is None:
            state["data"].close()

    app = FastAPI(title="Ask the Coffee Observatory", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    limiter = RateLimiter(settings.per_ip_per_minute, settings.per_ip_per_day, settings.daily_quota)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "qa_enabled": settings.qa_enabled}

    @app.get("/meta")
    def meta() -> dict:
        info = state["data"].meta() if state["data"] is not None else {}
        return {**info, "qa_enabled": settings.qa_enabled, "questions_left_today": limiter.remaining_today}

    @app.post("/ask", response_model=AskResponse)
    def ask(body: AskRequest, request: Request):
        if not settings.qa_enabled:
            return JSONResponse(
                status_code=503,
                content=AskResponse(
                    status="disabled",
                    answer="Questions are paused right now. The walkthrough still works.",
                ).model_dump(),
            )
        # Behind Cloud Run's front end, uvicorn --proxy-headers sets request.client from X-Forwarded-For.
        ip = request.client.host if request.client else "unknown"
        if hit := limiter.check(ip):
            return JSONResponse(
                status_code=429, content=AskResponse(status="rate_limited", answer=LIMIT_MESSAGES[hit]).model_dump()
            )
        response = state["pipeline"].ask(body.question)
        if state["data"] is not None:
            response.data_version = state["data"].data_version()
        return response

    return app


app = create_app()
