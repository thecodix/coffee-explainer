# coffee-explainer — data loader

Loads one export of the coffee observatory ([thecodix/roasters](https://github.com/thecodix/roasters)) into a
separate Postgres with pgvector, for the *Ask the Coffee Observatory* app. The observatory's own database is
never touched: every load replaces this copy wholesale, in one transaction.

```
observatory export (fixtures folder, export folder or the published /data URL)
   └─ load ──▶ obs.*  (raw copy: roasters, products, observations, regions, representation)
                ├─▶ api.*  curated views + COMMENTs  ← the only thing text-to-SQL may query
                └─▶ rag.documents  (product, roaster, region and "about" cards) ── embed ──▶ vector(384)
```

## Quick start (Neon)

```bash
uv sync --dev                                   # or: pip install -e . pytest ruff
cp .env.example .env                            # fill DATABASE_URL with the Neon owner connection string
set -a; source .env; set +a

# Latest published export (2026-10-05: 26,426 products, 314 roasters):
uv run python -m explainer_data refresh --source https://observatorio-cafe.pages.dev/data
# or the snapshot that ships in the roasters repo:
uv run python -m explainer_data refresh --source ../roasters/web/src/fixtures

# Login role for the API: member of explainer_reader, read-only transactions, 5 s statement timeout
READER_PASSWORD='…' uv run python -m explainer_data create-reader explainer_api

uv run python -m explainer_data search "washed Ethiopian coffees sold in Spain"
```

`refresh` = `migrate` + `load` + `embed`. Run it again whenever a new export is published: unchanged documents
keep their embeddings, so only new or edited products are embedded.

The first `embed` downloads the embedding model (~220 MB,
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 384 dimensions, CPU via ONNX). The API must embed
queries with the same model; each document records which model embedded it.

## What the API may query

| View | What it is |
| --- | --- |
| `api.products` | One row per product with its latest price, kind (`is_coffee`), origin, process, variety |
| `api.roasters` | Coffees vs all products per roaster, median price per 100 g of its coffees |
| `api.price_by_origin` | Median, min and max EUR per 100 g by origin and roaster country (coffees only) |
| `api.origin_mix` | Share of each origin in each roaster country's catalogs |
| `api.regions` | 66 curated growing regions with coordinates and sources |
| `api.representation` | Panel share vs import share per origin (UN Comtrade HS 090111) |
| `api.data_coverage` | How many products have each field, dataset version and cutoff |

Every view and its key columns carry a `COMMENT`; the API reads them to build the text-to-SQL schema prompt.

## Notes

- Product kind: newer exports carry the observatory's own `product_kind`. Older ones (the repo fixtures) are
  classified here with a vendored copy of the observatory's classifier, on the product name only, so more
  products end up as `other` than in the observatory itself.
- Documents are written from structured fields only: no roaster copy is republished.
- Tests: `TEST_ADMIN_URL=postgresql://… uv run pytest` (needs a Postgres with pgvector where databases can be
  created; without it the database tests are skipped).
