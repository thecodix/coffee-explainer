import os

import psycopg
import pytest

from explainer_data.__main__ import _create_reader
from explainer_data.db import migrate
from explainer_data.embed import HashEmbedder, embed_pending, search
from explainer_data.load import load
from explainer_data.source import read_export

from .conftest import write_fixtures


def test_load_embed_and_reload(conn, tmp_path):
    migrate(conn)
    summary = load(conn, read_export(str(write_fixtures(tmp_path / "v1"))))
    assert (summary.products, summary.observations, summary.representation) == (3, 4, 2)
    assert embed_pending(conn, HashEmbedder()) == summary.documents

    # Coffee-only views: the dripper is excluded, prices come from the latest observation.
    rows = conn.execute(
        "SELECT origin_country, median_price_per_100g_eur FROM api.price_by_origin ORDER BY origin_country"
    ).fetchall()
    assert [(c, float(p)) for c, p in rows] == [("CO", 6.8), ("ET", 5.0)]
    assert conn.execute("SELECT coffees, products FROM api.data_coverage").fetchone() == (2, 3)

    # Same export again: nothing to embed. A changed price: only that product and its roaster's card...
    load(conn, read_export(str(write_fixtures(tmp_path / "v1"))))
    assert embed_pending(conn, HashEmbedder()) == 0
    load(conn, read_export(str(write_fixtures(tmp_path / "v2", kima_price=15.0))))
    assert embed_pending(conn, HashEmbedder()) == 1  # ...only the product: the roaster card has no prices

    hits = search(conn, HashEmbedder(), "Ethiopia Guji Natural 250g", k=1, kinds=["product"])
    assert len(hits) == 1


def test_reader_role_sees_api_only(conn, tmp_path):
    migrate(conn)
    load(conn, read_export(str(write_fixtures(tmp_path / "v1"))))
    os.environ["READER_PASSWORD"] = "test-reader-pw"
    name = f"reader_{conn.info.dbname[-8:]}"
    _create_reader(conn, name)
    conn.commit()
    url = psycopg.conninfo.make_conninfo(conn.info_url, user=name, password="test-reader-pw")
    try:
        with psycopg.connect(url) as reader:
            assert reader.execute("SELECT count(*) FROM products").fetchone() == (3,)  # search_path = api, rag
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                reader.execute("SELECT * FROM obs.products")
            reader.rollback()
            with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                reader.execute("DELETE FROM rag.documents")
    finally:
        conn.execute(f'DROP OWNED BY "{name}"')
        conn.execute(f'DROP ROLE "{name}"')
        conn.commit()
