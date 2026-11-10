import json

from explainer_data.documents import product_document
from explainer_data.load import build_documents, product_kind
from explainer_data.source import read_export

from .conftest import write_fixtures


def test_reads_flat_fixtures(fixtures_dir):
    export = read_export(str(fixtures_dir))
    assert export.version["data_version"] == "test-v1"
    assert len(export.catalog) == 3
    assert export.roasters["kima"]["registry"]["platform"] == "shopify"


def test_reads_published_layout(tmp_path):
    """version.json at the root, collections under <data_version>/, one file per roaster."""
    flat = write_fixtures(tmp_path / "flat")
    root = tmp_path / "published"
    versioned = root / "test-v1"
    (versioned / "roasters").mkdir(parents=True)
    (root / "version.json").write_text((flat / "version.json").read_text())
    for name in ("catalog", "observations", "regions", "representation"):
        (versioned / f"{name}.json").write_text((flat / f"{name}.json").read_text())
    for roaster_id, detail in json.loads((flat / "roasters.json").read_text()).items():
        (versioned / "roasters" / f"{roaster_id}.json").write_text(json.dumps(detail))

    export = read_export(str(root))
    assert set(export.roasters) == {"kima", "nord"}
    assert len(export.observations) == 4


def test_product_kind_prefers_the_export_label():
    assert product_kind({"product_name": "Kalita Wave 155 Dripper"}) == "equipment"
    assert product_kind({"product_name": "Kalita Wave 155 Dripper", "product_kind": "merch"}) == "merch"


def test_documents_are_built_from_fields_only(fixtures_dir):
    docs = {d.doc_id: d for d in build_documents(read_export(str(fixtures_dir)))}
    guji = next(d for d in docs.values() if d.title.startswith("Ethiopia Guji"))
    assert "Origin: Ethiopia." in guji.body
    assert "4.80 EUR per 100 g" not in guji.body  # latest price is used, not the first one
    assert "5.00 EUR per 100 g" in guji.body
    assert "Type: brewing equipment" in next(d for d in docs.values() if "Kalita" in d.title).body
    assert "region:CO:Huila" in docs and "about:dataset" in docs
    assert "1 of them coffees" in docs["roaster:kima"].body


def test_content_hash_changes_only_with_content(fixtures_dir):
    row = read_export(str(fixtures_dir)).catalog[0]
    first = product_document(row, "Kima Coffee", "single_origin")
    assert first.content_hash == product_document(dict(row), "Kima Coffee", "single_origin").content_hash
    assert (
        first.content_hash != product_document({**row, "price_amount": 99}, "Kima Coffee", "single_origin").content_hash
    )
