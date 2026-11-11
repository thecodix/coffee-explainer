"""Cheap checks before any model sees the question: length and obvious prompt-injection patterns.

This is a first screen, not the only one: the router can still classify a question as out of scope, the SQL
guard limits what any generated query can do, and the database role is read-only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

INJECTION_PATTERNS = [
    r"\bignore\b.{0,40}\b(instructions?|rules|prompt|above|previous)\b",
    r"\b(disregard|forget)\b.{0,40}\b(instructions?|rules|prompt)\b",
    r"\b(system|developer)\s+(prompt|message|instructions?)\b",
    r"\byou\s+are\s+now\b",
    r"\bact\s+as\b.{0,30}\b(admin|root|dba|developer|unrestricted)\b",
    r"\b(jailbreak|DAN mode)\b",
    r"\b(drop|truncate|alter|grant|revoke)\s+(table|schema|role|database)\b",
    r"\b(delete\s+from|insert\s+into|update\s+\w+\s+set)\b",
    r"<\s*/?\s*(system|assistant|tool)\s*>",
]
_INJECTION = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class GuardVerdict:
    allowed: bool
    reason: str | None = None


def screen(question: str, max_chars: int) -> GuardVerdict:
    text = question.strip()
    if not text:
        return GuardVerdict(False, "empty")
    if len(text) > max_chars:
        return GuardVerdict(False, "too_long")
    if _INJECTION.search(text):
        return GuardVerdict(False, "injection_pattern")
    return GuardVerdict(True)
