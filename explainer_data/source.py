"""Read one observatory export, wherever it lives.

Two layouts carry the same JSON bodies (the observatory's static exporter writes them byte for byte):

* fixtures: a flat folder with ``catalog.json``, ``observations.json``, ``regions.json``,
  ``representation.json``, ``roasters.json`` (``{roaster_id: detail}``) and ``version.json``;
* a published export: ``version.json`` points at ``<data_version>/``, which holds the same collections
  plus ``roasters/<roaster_id>.json``. It can be a local folder or the ``/data`` URL of the published site.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

COLLECTIONS = ("catalog", "observations", "regions", "representation")


@dataclass(frozen=True)
class Export:
    source: str
    version: dict[str, Any]
    catalog: list[dict[str, Any]]
    observations: list[dict[str, Any]]
    regions: list[dict[str, Any]]
    representation: list[dict[str, Any]]
    roasters: dict[str, dict[str, Any]]  # roaster_id -> detail (registry: status, platform, seed_url)


def records(table: dict[str, Any]) -> list[dict[str, Any]]:
    """``{"columns": [...], "rows": [[...]]}`` -> list of dicts."""
    columns = table["columns"]
    return [dict(zip(columns, row, strict=True)) for row in table["rows"]]


def _reader(source: str) -> Callable[[str], Any]:
    if source.startswith(("http://", "https://")):
        base = source.rstrip("/") + "/"

        def read_url(path: str) -> Any:
            request = urllib.request.Request(base + path, headers={"User-Agent": "coffee-explainer-loader"})
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)

        return read_url

    root = Path(source)

    def read_file(path: str) -> Any:
        return json.loads((root / path).read_text(encoding="utf-8"))

    return read_file


def _is_fixtures(source: str) -> bool:
    return not source.startswith(("http://", "https://")) and (Path(source) / "catalog.json").exists()


def read_export(source: str) -> Export:
    read = _reader(source)
    version = read("version.json")
    if _is_fixtures(source):
        prefix = ""
        roasters = read("roasters.json")
    else:
        prefix = f"{version['data_version']}/"
        roasters = {}
    tables = {name: records(read(f"{prefix}{name}.json")) for name in COLLECTIONS}
    if not roasters:
        ids = sorted({row["roaster_id"] for row in tables["catalog"] if row["roaster_id"]})
        roasters = {roaster_id: read(f"{prefix}roasters/{roaster_id}.json") for roaster_id in ids}
    return Export(source=source, version=version, roasters=roasters, **tables)
