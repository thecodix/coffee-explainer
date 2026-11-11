-- One roaster selling many origins at a flat price could top an origin ranking on its own (first real run:
-- three origins tied at 5.16 EUR / 100 g). Expose how many distinct roasters stand behind each median.
-- CREATE OR REPLACE may only append columns, so `roasters` goes last; grants are kept.

CREATE OR REPLACE VIEW api.price_by_origin AS
SELECT
    origin_country,
    roaster_country,
    count(*)                                                            AS products_priced,
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY price_per_100g_eur)::numeric, 2) AS median_price_per_100g_eur,
    round(min(price_per_100g_eur), 2)                                   AS min_price_per_100g_eur,
    round(max(price_per_100g_eur), 2)                                   AS max_price_per_100g_eur,
    count(DISTINCT roaster_id)                                          AS roasters
FROM api.products
WHERE is_coffee AND origin_country IS NOT NULL AND price_per_100g_eur IS NOT NULL
GROUP BY origin_country, roaster_country;

COMMENT ON COLUMN api.price_by_origin.products_priced IS 'Coffees with a known price per 100 g behind this median.';
COMMENT ON COLUMN api.price_by_origin.roasters IS
    'Distinct roasters behind this median. Rank only groups with at least 3: fewer means one shop''s pricing.';
