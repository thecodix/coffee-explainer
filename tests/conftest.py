import json
import os
import uuid
from pathlib import Path

import psycopg
import pytest

CATALOG_COLUMNS = [
    "product_id",
    "roaster_id",
    "roaster_name",
    "roaster_country",
    "roaster_status",
    "seed_url",
    "product_name",
    "product_url",
    "process",
    "process_canonical",
    "variety",
    "certifications",
    "capture_date",
    "first_seen_at",
    "last_seen_at",
    "price_amount",
    "price_currency",
    "price_unit_grams",
    "price_per_100g",
    "origin_country",
    "origins_label",
    "is_protected_designation",
    "notable_variety",
    "has_certification",
    "price_per_100g_eur",
]
P1, P2, P3 = (str(uuid.UUID(int=i)) for i in (1, 2, 3))


def _catalog(kima_price: float = 12.5) -> dict:
    rows = [
        [
            P1,
            "kima",
            "Kima Coffee",
            "ES",
            "active",
            "https://kima.example/",
            "Ethiopia Guji Natural 250g",
            "https://kima.example/guji",
            "natural",
            "natural",
            "Heirloom",
            "orgánico",
            "2026-09-29",
            "2026-09-28",
            "2026-09-29",
            kima_price,
            "EUR",
            250,
            kima_price / 2.5,
            "ET",
            "ET",
            False,
            False,
            True,
            kima_price / 2.5,
        ],
        [
            P2,
            "kima",
            "Kima Coffee",
            "ES",
            "active",
            "https://kima.example/",
            "Kalita Wave 155 Dripper",
            "https://kima.example/kalita",
            None,
            None,
            None,
            None,
            "2026-09-29",
            "2026-09-29",
            "2026-09-29",
            30.0,
            "EUR",
            None,
            None,
            None,
            None,
            False,
            False,
            False,
            None,
        ],
        [
            P3,
            "nord",
            "Nord Roasters",
            "NO",
            "active",
            "https://nord.example/",
            "Colombia Huila Washed 250g",
            "https://nord.example/huila",
            "washed",
            "washed",
            "Caturra",
            None,
            "2026-09-29",
            "2026-09-29",
            "2026-09-29",
            199.0,
            "NOK",
            250,
            79.6,
            "CO",
            "CO",
            False,
            False,
            False,
            6.8,
        ],
    ]
    return {"columns": CATALOG_COLUMNS, "rows": rows}


def write_fixtures(folder: Path, kima_price: float = 12.5) -> Path:
    obs_cols = [
        "product_id",
        "capture_date",
        "price_amount",
        "price_currency",
        "price_unit_grams",
        "price_per_100g",
        "in_stock",
        "sca_score",
        "price_per_100g_eur",
        "fx_rate_date",
    ]
    files = {
        "version.json": {"data_version": "test-v1", "cutoff": "2026-09-29", "refreshed_at": "2026-10-01T00:00:00Z"},
        "catalog.json": _catalog(kima_price),
        "observations.json": {
            "columns": obs_cols,
            "rows": [
                [P1, "2026-09-28", 12.0, "EUR", 250, 4.8, None, None, 4.8, None],
                [P1, "2026-09-29", kima_price, "EUR", 250, kima_price / 2.5, None, None, kima_price / 2.5, None],
                [P2, "2026-09-29", 30.0, "EUR", None, None, None, None, None, None],
                [P3, "2026-09-29", 199.0, "NOK", 250, 79.6, None, None, 6.8, "2026-09-29"],
            ],
        },
        "regions.json": {
            "columns": [
                "region_name",
                "country",
                "lat",
                "lon",
                "altitude_min_masl",
                "altitude_max_masl",
                "source",
                "is_protected_designation",
            ],
            "rows": [["Huila", "CO", 2.5, -75.5, 1200, 2000, "FNC", True]],
        },
        "representation.json": {
            "columns": [
                "reporter_country",
                "year",
                "origin_country",
                "menciones_panel",
                "pct_share_panel",
                "tostadores_panel",
                "productos_panel",
                "importacion_kg",
                "pct_share_importacion",
                "indice_representacion",
            ],
            "rows": [
                ["ES", 2024, "ET", 1, 100.0, 1, 2, 1000.0, 10.0, 1000.0],
                ["NO", None, "CO", 1, 100.0, 1, 1, None, None, None],
            ],
        },
        "roasters.json": {
            "kima": {"registry": {"status": "active", "platform": "shopify", "seed_url": "https://kima.example/"}},
            "nord": {"registry": {"status": "active", "platform": "woocommerce", "seed_url": "https://nord.example/"}},
        },
    }
    folder.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (folder / name).write_text(json.dumps(body), encoding="utf-8")
    return folder


@pytest.fixture
def fixtures_dir(tmp_path: Path) -> Path:
    return write_fixtures(tmp_path / "fixtures")


@pytest.fixture
def conn():
    """A throwaway database. Needs TEST_ADMIN_URL: a Postgres with pgvector where we may create databases."""
    admin_url = os.environ.get("TEST_ADMIN_URL")
    if not admin_url:
        pytest.skip("TEST_ADMIN_URL not set")
    name = f"explainer_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = psycopg.conninfo.make_conninfo(admin_url, dbname=name)
    try:
        with psycopg.connect(url) as connection:
            connection.info_url = url  # type: ignore[attr-defined]
            yield connection
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
