-- The api schema is the ONLY surface text-to-SQL may query. Each view and column carries a COMMENT:
-- the API reads them to build the schema prompt, so the semantics live next to the SQL.

CREATE SCHEMA IF NOT EXISTS api;

CREATE VIEW api.products AS
WITH latest AS (
    SELECT DISTINCT ON (product_id) *
    FROM obs.observations
    ORDER BY product_id, capture_date DESC
)
SELECT
    p.product_id,
    p.product_name,
    p.product_kind,
    p.is_coffee,
    r.name                 AS roaster_name,
    r.roaster_id,
    r.country              AS roaster_country,
    p.origin_country,
    p.origins_label,
    p.process_canonical    AS process,
    p.variety,
    p.certifications,
    p.is_protected_designation,
    p.notable_variety,
    l.price_amount,
    l.price_currency,
    l.price_unit_grams,
    l.price_per_100g_eur,
    l.capture_date         AS price_date,
    p.first_seen_at,
    p.last_seen_at,
    p.product_url
FROM obs.products p
JOIN obs.roasters r USING (roaster_id)
LEFT JOIN latest l USING (product_id);

COMMENT ON VIEW api.products IS
    'One row per coffee product in the observatory panel, with its latest observed retail price. '
    'Fields are often NULL: origin, process, variety and price per 100 g are only known when the roaster states them.';
COMMENT ON COLUMN api.products.product_kind IS 'single_origin, blend or coffee for coffee; capsules, equipment, merch, other_drink, other for the rest.';
COMMENT ON COLUMN api.products.is_coffee IS 'True for bagged coffee (single_origin, blend, coffee). Filter on it for any question about coffee prices or origins.';
COMMENT ON COLUMN api.products.roaster_country IS 'ISO 3166-1 alpha-2 country of the roaster (where it sells), not of the coffee.';
COMMENT ON COLUMN api.products.origin_country IS 'ISO 3166-1 alpha-2 country where the coffee was grown. NULL when not stated or a blend.';
COMMENT ON COLUMN api.products.origins_label IS 'All origin countries of the product joined with "+", e.g. "BR+ET" for a blend.';
COMMENT ON COLUMN api.products.process IS 'Canonical post-harvest process: washed, natural, honey, anaerobic, ... NULL when unknown.';
COMMENT ON COLUMN api.products.price_amount IS 'Listed retail price in price_currency for the package size (price_unit_grams).';
COMMENT ON COLUMN api.products.price_per_100g_eur IS
    'Retail price per 100 g converted to EUR. The only price column safe to compare across roasters. '
    'NULL when the package weight is unknown.';
COMMENT ON COLUMN api.products.notable_variety IS 'True for rare or sought-after varieties (e.g. Geisha).';
COMMENT ON COLUMN api.products.is_protected_designation IS 'True when the stated region is a protected designation of origin.';

CREATE VIEW api.roasters AS
SELECT
    r.roaster_id,
    r.name,
    r.country,
    r.platform,
    r.seed_url,
    count(p.product_id) FILTER (WHERE p.is_coffee)          AS coffees,
    count(p.product_id)                                      AS products,
    count(p.origin_country)                                  AS products_with_origin,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY p.price_per_100g_eur)
        FILTER (WHERE p.is_coffee AND p.price_per_100g_eur IS NOT NULL) AS median_price_per_100g_eur
FROM obs.roasters r
LEFT JOIN api.products p USING (roaster_id)
GROUP BY r.roaster_id, r.name, r.country, r.platform, r.seed_url;

COMMENT ON VIEW api.roasters IS 'One row per roaster in the panel: coffees vs all products, and the median retail price per 100 g (EUR) of its coffees.';

CREATE VIEW api.price_by_origin AS
SELECT
    origin_country,
    roaster_country,
    count(*)                                                            AS products_priced,
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY price_per_100g_eur)::numeric, 2) AS median_price_per_100g_eur,
    round(min(price_per_100g_eur), 2)                                   AS min_price_per_100g_eur,
    round(max(price_per_100g_eur), 2)                                   AS max_price_per_100g_eur
FROM api.products
WHERE is_coffee AND origin_country IS NOT NULL AND price_per_100g_eur IS NOT NULL
GROUP BY origin_country, roaster_country;

COMMENT ON VIEW api.price_by_origin IS
    'Retail price per 100 g (EUR) by coffee origin and roaster country, single-origin products with a known weight only. '
    'Retail prices: never compare them with import prices in api.representation.';

CREATE VIEW api.origin_mix AS
SELECT
    roaster_country,
    origin_country,
    count(*) AS products,
    round(100.0 * count(*) / sum(count(*)) OVER (PARTITION BY roaster_country), 1) AS share_pct
FROM api.products
WHERE is_coffee AND origin_country IS NOT NULL
GROUP BY roaster_country, origin_country;

COMMENT ON VIEW api.origin_mix IS 'How often each origin appears in the catalogs of each roaster country (products with a stated origin only).';

CREATE VIEW api.regions AS
SELECT country, region_name, lat, lon, altitude_min_masl, altitude_max_masl, is_protected_designation, source
FROM obs.regions;

COMMENT ON VIEW api.regions IS 'Curated coffee-growing regions with coordinates and the sources they come from.';

CREATE VIEW api.representation AS
SELECT * FROM obs.representation;

COMMENT ON VIEW api.representation IS
    'Per importing country and year: an origin''s share of panel products vs its share of green-coffee imports (UN Comtrade HS 090111). '
    'representation_index = panel_share_pct / import_share_pct * 100; above 100 means the origin is over-represented in specialty catalogs. '
    'Import volumes cover every quality grade, so never derive margins or prices from them.';

CREATE VIEW api.data_coverage AS
SELECT
    count(*)                       AS products,
    count(*) FILTER (WHERE is_coffee) AS coffees,
    count(origin_country)          AS with_origin,
    count(process)                 AS with_process,
    count(variety)                 AS with_variety,
    count(price_per_100g_eur)      AS with_price_per_100g,
    (SELECT data_version FROM obs.dataset_version ORDER BY loaded_at DESC LIMIT 1) AS data_version,
    (SELECT cutoff FROM obs.dataset_version ORDER BY loaded_at DESC LIMIT 1)       AS cutoff
FROM api.products;

COMMENT ON VIEW api.data_coverage IS 'How many products have each field filled in, plus the dataset version and cutoff date. Use it to say what the data cannot answer.';
