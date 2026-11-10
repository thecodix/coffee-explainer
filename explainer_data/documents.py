"""Turn the loaded tables into retrieval documents.

The export has no free-text descriptions (no tasting notes, no roaster copy), so documents are written from
the structured fields. That keeps answers grounded in what the observatory measured and never republishes a
roaster's own text.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

COUNTRIES = {
    "BI": "Burundi",
    "BO": "Bolivia",
    "BR": "Brazil",
    "CN": "China",
    "CO": "Colombia",
    "CR": "Costa Rica",
    "DK": "Denmark",
    "EC": "Ecuador",
    "ES": "Spain",
    "ET": "Ethiopia",
    "GB": "United Kingdom",
    "GT": "Guatemala",
    "HN": "Honduras",
    "ID": "Indonesia",
    "IN": "India",
    "KE": "Kenya",
    "MM": "Myanmar",
    "MW": "Malawi",
    "MX": "Mexico",
    "NI": "Nicaragua",
    "NO": "Norway",
    "PA": "Panama",
    "PE": "Peru",
    "PG": "Papua New Guinea",
    "RW": "Rwanda",
    "SV": "El Salvador",
    "TH": "Thailand",
    "TZ": "Tanzania",
    "UG": "Uganda",
    "VN": "Vietnam",
    "YE": "Yemen",
    "DE": "Germany",
    "FR": "France",
    "IT": "Italy",
    "NL": "Netherlands",
    "BE": "Belgium",
    "PT": "Portugal",
    "SE": "Sweden",
    "FI": "Finland",
    "JM": "Jamaica",
    "LA": "Laos",
    "CD": "DR Congo",
}

ABOUT = [
    (
        "dataset",
        "About the coffee observatory data",
        (
            "The observatory is a longitudinal panel of European specialty-coffee roasters. A scraper reads each "
            "roaster's online shop through its platform API (Shopify or WooCommerce) and records every coffee product: "
            "name, stated origin, process, variety, certifications, package size and price. Prices are converted to "
            "euros per 100 g so roasters can be compared. Fields are only filled when the roaster states them, so many "
            "products have no origin, process or price per 100 g."
        ),
    ),
    (
        "representation",
        "How over- and under-representation of origins is measured",
        (
            "For each importing country and year, the observatory compares an origin's share of specialty products in "
            "the panel with that origin's share of green-coffee imports reported to UN Comtrade (HS code 090111). "
            "The representation index is the panel share divided by the import share, times 100. Above 100 means "
            "specialty roasters feature the origin more than its import volume would suggest. Import statistics cover "
            "every quality grade, so they say nothing about specialty prices or margins."
        ),
    ),
]


@dataclass(frozen=True)
class Document:
    kind: str
    ref_id: str
    title: str
    body: str
    url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def doc_id(self) -> str:
        return f"{self.kind}:{self.ref_id}"

    @property
    def content_hash(self) -> str:
        payload = json.dumps([self.title, self.body, self.url, self.metadata], sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:32]

    @property
    def text(self) -> str:
        """What gets embedded."""
        return f"{self.title}\n{self.body}"


def country(code: str | None) -> str | None:
    if not code:
        return None
    return COUNTRIES.get(code, code)


def _origins(label: str | None) -> str | None:
    if not label:
        return None
    return " + ".join(country(code) or code for code in label.split("+"))


KIND_WORDS = {
    "single_origin": "single-origin coffee",
    "blend": "coffee blend",
    "coffee": "coffee",
    "capsules": "coffee capsules",
    "equipment": "brewing equipment, not coffee",
    "merch": "merchandise, not coffee",
    "other_drink": "a drink that is not coffee beans",
    "pack": "a pack or bundle",
    "other": "not a coffee product",
}


def product_document(row: dict[str, Any], roaster_name: str, kind: str) -> Document:
    facts = [f"Type: {KIND_WORDS.get(kind, kind)}.", f"Sold by {roaster_name} ({country(row['roaster_country'])})."]
    origin = _origins(row.get("origins_label")) or country(row.get("origin_country"))
    facts.append(f"Origin: {origin}." if origin else "Origin: not stated by the roaster.")
    if row.get("canonical_region"):
        facts.append(f"Region: {row['canonical_region']}.")
    if row.get("process_canonical"):
        facts.append(f"Process: {row['process_canonical'].replace('_', ' ')}.")
    if row.get("variety"):
        facts.append(f"Variety: {row['variety']}.")
    if row.get("certifications"):
        facts.append(f"Certifications: {row['certifications']}.")
    if row.get("notable_variety"):
        facts.append("Flagged as a notable variety.")
    if row.get("is_protected_designation"):
        facts.append("From a protected designation of origin.")
    if row.get("price_amount") is not None:
        size = f" for {row['price_unit_grams']} g" if row.get("price_unit_grams") else ""
        per_100 = (
            f", {row['price_per_100g_eur']:.2f} EUR per 100 g" if row.get("price_per_100g_eur") is not None else ""
        )
        facts.append(f"Price on {row['capture_date']}: {row['price_amount']} {row['price_currency']}{size}{per_100}.")
    return Document(
        kind="product",
        ref_id=row["product_id"],
        title=row["product_name"],
        body=" ".join(facts),
        url=row.get("product_url"),
        metadata={
            "roaster_id": row["roaster_id"],
            "roaster_country": row["roaster_country"],
            "origin_country": row.get("origin_country"),
            "process": row.get("process_canonical"),
            "product_kind": kind,
        },
    )


def roaster_document(
    roaster: dict[str, Any], products: list[dict[str, Any]], coffees: list[dict[str, Any]]
) -> Document:
    origins: dict[str, int] = {}
    for row in coffees:
        if row.get("origin_country"):
            origins[row["origin_country"]] = origins.get(row["origin_country"], 0) + 1
    top = sorted(origins.items(), key=lambda item: (-item[1], item[0]))[:5]
    facts = [
        f"{roaster['name']} is a specialty-coffee roaster in {country(roaster['country'])}.",
        f"The observatory tracks {len(products)} products from its online shop"
        + (f" ({roaster['platform']})" if roaster.get("platform") else "")
        + f", {len(coffees)} of them coffees.",
    ]
    if top:
        facts.append("Most frequent stated origins: " + ", ".join(f"{country(c)} ({n})" for c, n in top) + ".")
    return Document(
        kind="roaster",
        ref_id=roaster["roaster_id"],
        title=roaster["name"],
        body=" ".join(facts),
        url=roaster.get("seed_url"),
        metadata={"country": roaster["country"]},
    )


def region_document(region: dict[str, Any]) -> Document:
    facts = [f"{region['region_name']} is a coffee-growing region in {country(region['country'])}."]
    low, high = region.get("altitude_min_masl"), region.get("altitude_max_masl")
    if low and high:
        facts.append(f"Altitude: {low}-{high} m above sea level.")
    if region.get("is_protected_designation"):
        facts.append("It is a protected designation of origin.")
    if region.get("source"):
        facts.append(f"Sources: {region['source']}.")
    return Document(
        kind="region",
        ref_id=f"{region['country']}:{region['region_name']}",
        title=f"{region['region_name']} ({country(region['country'])})",
        body=" ".join(facts),
        metadata={"country": region["country"], "lat": region.get("lat"), "lon": region.get("lon")},
    )


def about_documents() -> list[Document]:
    return [Document(kind="about", ref_id=ref, title=title, body=body) for ref, title, body in ABOUT]
