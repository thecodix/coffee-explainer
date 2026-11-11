"""Where each pipeline step lives in the source, so the explainer can show the code that ran.

Found by reading pipeline.py: the block that starts at `trace.step("<name>")` and runs until the indentation drops back.
"""

from __future__ import annotations

import re
import textwrap
from functools import lru_cache
from pathlib import Path

PIPELINE_FILE = Path(__file__).with_name("pipeline.py")
PIPELINE_PATH = f"coffee_api/{PIPELINE_FILE.name}"


@lru_cache(maxsize=1)
def _lines() -> tuple[str, ...]:
    return tuple(PIPELINE_FILE.read_text(encoding="utf-8").splitlines())


def _indent(text: str) -> int:
    return len(text) - len(text.lstrip())


def source_for(step: str) -> dict | None:
    """{file, start, end, code} for the block of `trace.step("<step>")`, 1-based lines; None if not found."""
    lines = _lines()
    pattern = re.compile(r"trace\.step\(\"" + re.escape(step) + r"\"\)")
    start = next((i for i, line in enumerate(lines) if pattern.search(line)), None)
    if start is None:
        return None
    indent = _indent(lines[start])
    end = start
    for j in range(start + 1, len(lines)):
        if lines[j].strip() and _indent(lines[j]) <= indent:
            break
        if lines[j].strip():
            end = j
    block = textwrap.dedent("\n".join(lines[start : end + 1]))
    return {"file": PIPELINE_PATH, "start": start + 1, "end": end + 1, "code": block}
