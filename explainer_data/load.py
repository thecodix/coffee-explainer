"""Replace the obs.* copy with one export and rebuild the retrieval corpus, in a single transaction.

Readers never see a half-loaded dataset: either the previous export or the new one. Embeddings survive a
reload when a document did not change (same content hash), so only new or edited documents need embedding.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import psycopg

from .documents import Document, about_documents, product_document, region_document, roaster_document
from .product_kind import classify, is_coffee
from .source import Export


@dataclass(frozen=True)
class LoadSummary:
    data_version: str
    roasters: int
    products: int
    observations: int
    regions: int
    representation: int
    documents: int
    documents_needing_embedding: int


def _certifications(value: Any) -> list[str] | None:
    if not value:
        return None
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in re.split(r"[;,|]", str(value)) if part.strip()]


def _roaster_rows(export: Export) -> list[tuple]:
    seen: dict[str, tuple] = {}
    for row in export.catalog:
        roaster_id = row["roaster_id"]
        if roaster_id in seen:
            continue
        registry = (export.roasters.get(roaster_id) or {}).get("registry") or {}
        seen[roaster_id] = (
            roaster_id,
            row["roaster_name"],
            row["roaster_country"],
            registry.get("status") or row.get("roaster_status"),
            registry.get("platform"),
            registry.get("seed_url") or row.get("seed_url"),
        )
    return list(seen.values())


def product_kind(row: dict[str, Any]) -> str:
    """The observatory's own label when the export has one; otherwise its classifier on the product name."""
    return row.get("product_kind") or classify(row["product_name"])


def _product_rows(export: Export) -> list[tuple]:
    return [
        (
            r["product_id"],
            r["roaster_id"],
            r["product_name"],
            r.get("product_url"),
            product_kind(r),
            is_coffee(product_kind(r)),
            r.get("process"),
            r.get("process_canonical"),
            r.get("variety"),
            _certifications(r.get("certifications")),
            r.get("origin_country"),
            r.get("origins_label"),
            r.get("canonical_region"),
            bool(r.get("is_protected_designation")),
            bool(r.get("notable_variety")),
            bool(r.get("has_certification")),
            r.get("first_seen_at"),
            r.get("last_seen_at"),
        )
        for r in export.catalog
    ]


def _observation_rows(export: Export) -> list[tuple]:
    return [
        (
            r["product_id"],
            r["capture_date"],
            r.get("price_amount"),
            r.get("price_currency"),
            r.get("price_unit_grams"),
            r.get("price_per_100g"),
            r.get("price_per_100g_eur"),
            r.get("fx_rate_date"),
            r.get("in_stock"),
            r.get("sca_score"),
        )
        for r in export.observations
    ]


def _region_rows(export: Export) -> list[tuple]:
    return [
        (
            r["country"],
            r["region_name"],
            r.get("lat"),
            r.get("lon"),
            r.get("altitude_min_masl"),
            r.get("altitude_max_masl"),
            r.get("source"),
            bool(r.get("is_protected_designation")),
        )
        for r in export.regions
    ]


def _representation_rows(export: Export) -> list[tuple]:
    return [
        (
            r["reporter_country"],
            r["year"],
            r["origin_country"],
            r.get("menciones_panel"),
            r.get("pct_share_panel"),
            r.get("tostadores_panel"),
            r.get("productos_panel"),
            r.get("importacion_kg"),
            r.get("pct_share_importacion"),
            r.get("indice_representacion"),
        )
        for r in export.representation
    ]


def build_documents(export: Export) -> list[Document]:
    roasters = {row[0]: row for row in _roaster_rows(export)}
    by_roaster: dict[str, list[dict[str, Any]]] = {}
    docs: list[Document] = []
    for row in export.catalog:
        by_roaster.setdefault(row["roaster_id"], []).append(row)
        docs.append(product_document(row, roasters[row["roaster_id"]][1], product_kind(row)))
    for roaster_id, (_, name, country, _status, platform, seed_url) in roasters.items():
        roaster = {
            "roaster_id": roaster_id,
            "name": name,
            "country": country,
            "platform": platform,
            "seed_url": seed_url,
        }
        rows = by_roaster.get(roaster_id, [])
        docs.append(roaster_document(roaster, rows, [r for r in rows if is_coffee(product_kind(r))]))
    docs.extend(region_document(region) for region in export.regions)
    docs.extend(about_documents())
    return docs


def _insert(cur: psycopg.Cursor, table: str, columns: str, rows: list[tuple]) -> None:
    placeholders = ", ".join(["%s"] * len(columns.split(",")))
    cur.executemany(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", rows)


def load(conn: psycopg.Connection, export: Export) -> LoadSummary:
    version = export.version
    roasters = _roaster_rows(export)
    products = _product_rows(export)
    observations = _observation_rows(export)
    regions = _region_rows(export)
    representation = _representation_rows(export)
    docs = build_documents(export)

    with conn.transaction(), conn.cursor() as cur:
        cur.execute("TRUNCATE obs.observations, obs.products, obs.roasters, obs.regions, obs.representation")
        _insert(cur, "obs.roasters", "roaster_id, name, country, status, platform, seed_url", roasters)
        _insert(
            cur,
            "obs.products",
            "product_id, roaster_id, product_name, product_url, product_kind, is_coffee, process, process_canonical, variety, "
            "certifications, origin_country, origins_label, canonical_region, is_protected_designation, "
            "notable_variety, has_certification, first_seen_at, last_seen_at",
            products,
        )
        _insert(
            cur,
            "obs.observations",
            "product_id, capture_date, price_amount, price_currency, price_unit_grams, price_per_100g, "
            "price_per_100g_eur, fx_rate_date, in_stock, sca_score",
            observations,
        )
        _insert(
            cur,
            "obs.regions",
            "country, region_name, lat, lon, altitude_min_masl, altitude_max_masl, source, is_protected_designation",
            regions,
        )
        _insert(
            cur,
            "obs.representation",
            "reporter_country, year, origin_country, panel_mentions, panel_share_pct, panel_roasters, "
            "panel_products, import_kg, import_share_pct, representation_index",
            representation,
        )
        cur.execute(
            "INSERT INTO obs.dataset_version (data_version, cutoff, refreshed_at, source) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (data_version) DO UPDATE SET source = EXCLUDED.source, loaded_at = now()",
            (version["data_version"], version.get("cutoff"), version.get("refreshed_at"), export.source),
        )

        # Corpus: upsert every document; keep the embedding only when the content did not change.
        cur.executemany(
            "INSERT INTO rag.documents (doc_id, kind, ref_id, title, body, url, metadata, content_hash) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (doc_id) DO UPDATE SET kind = EXCLUDED.kind, ref_id = EXCLUDED.ref_id, "
            "title = EXCLUDED.title, body = EXCLUDED.body, url = EXCLUDED.url, metadata = EXCLUDED.metadata, "
            "content_hash = EXCLUDED.content_hash, updated_at = now(), "
            "embedding = CASE WHEN rag.documents.content_hash = EXCLUDED.content_hash "
            "THEN rag.documents.embedding END, "
            "embedding_model = CASE WHEN rag.documents.content_hash = EXCLUDED.content_hash "
            "THEN rag.documents.embedding_model END",
            [
                (
                    d.doc_id,
                    d.kind,
                    d.ref_id,
                    d.title,
                    d.body,
                    d.url,
                    json.dumps(d.metadata, default=str),
                    d.content_hash,
                )
                for d in docs
            ],
        )
        cur.execute("DELETE FROM rag.documents WHERE NOT (doc_id = ANY(%s))", ([d.doc_id for d in docs],))
        pending = cur.execute("SELECT count(*) FROM rag.documents WHERE embedding IS NULL").fetchone()[0]

    return LoadSummary(
        data_version=version["data_version"],
        roasters=len(roasters),
        products=len(products),
        observations=len(observations),
        regions=len(regions),
        representation=len(representation),
        documents=len(docs),
        documents_needing_embedding=pending,
    )
