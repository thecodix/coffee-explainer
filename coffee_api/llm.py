"""Groq chat completions with a fallback chain and validated JSON output.

For each model in the chain: call it, parse the JSON, validate it with the Pydantic schema. A 429, a 5xx, a
timeout or a network error moves on to the next model at once; an answer that fails validation is retried once on
the same model, then moves on. If every model fails, ``LLMUnavailable`` carries every attempt, so the API can
answer with a typed ``degraded`` response and the explainer can show what happened.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import httpx
from pydantic import BaseModel, ValidationError


@dataclass
class Attempt:
    model: str
    outcome: str  # ok | rate_limited | server_error | timeout | network_error | invalid_output | client_error
    ms: int
    status_code: int | None = None
    error: str | None = None


@dataclass
class LLMResult[T: BaseModel]:
    value: T
    model: str
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def fell_back(self) -> bool:
        return len(self.attempts) > 1


class LLMUnavailable(Exception):
    def __init__(self, attempts: list[Attempt]) -> None:
        super().__init__("every model in the chain failed")
        self.attempts = attempts


class GroqClient:
    def __init__(self, api_key: str, base_url: str, http: httpx.Client | None = None) -> None:
        self._http = http or httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"})

    def complete[T: BaseModel](
        self,
        chain: tuple[str, ...],
        system: str,
        user: str,
        schema: type[T],
        timeout_s: float,
        max_tokens: int = 1024,
    ) -> LLMResult[T]:
        attempts: list[Attempt] = []
        for model in chain:
            for _try in range(2):
                started = time.perf_counter()
                outcome, status, value, error = self._call(model, system, user, schema, timeout_s, max_tokens)
                ms = int((time.perf_counter() - started) * 1000)
                attempts.append(Attempt(model, outcome, ms, status, error))
                if value is not None:
                    return LLMResult(value=value, model=model, attempts=attempts)
                if outcome != "invalid_output":
                    break  # transport problems: next model, no retry on this one
        raise LLMUnavailable(attempts)

    def _call(self, model, system, user, schema, timeout_s, max_tokens):
        body = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": system
                    + "\n\nReply with one JSON object matching this JSON Schema, nothing else:\n"
                    + json.dumps(schema.model_json_schema()),
                },
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            response = self._http.post("/chat/completions", json=body, timeout=timeout_s)
        except httpx.TimeoutException:
            return "timeout", None, None, None
        except httpx.HTTPError:
            return "network_error", None, None, None
        code = response.status_code
        if code == 429:
            return "rate_limited", code, None, _error_text(response)
        if code >= 500:
            return "server_error", code, None, _error_text(response)
        if code >= 400:
            error = _error_text(response)
            # JSON mode: Groq rejects a generation that is not valid JSON with 400 json_validate_failed.
            outcome = "invalid_output" if error and "json_validate_failed" in error else "client_error"
            return outcome, code, None, error
        try:
            content = response.json()["choices"][0]["message"]["content"]
            return "ok", code, schema.model_validate_json(content), None
        except (KeyError, IndexError, TypeError, ValueError, ValidationError) as error:
            return "invalid_output", code, None, str(error)[:200]


def _error_text(response: httpx.Response) -> str | None:
    try:
        error = response.json().get("error", {})
        return f"{error.get('code') or error.get('type') or ''}: {error.get('message', '')}"[:200]
    except ValueError:
        return response.text[:200] or None
