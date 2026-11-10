-- Core tables: a read-only copy of one observatory export (catalog, prices, regions, representation).
-- Every load replaces these tables wholesale inside one transaction; nothing else writes here.

CREATE SCHEMA IF NOT EXISTS obs;

CREATE TABLE obs.dataset_version (
    data_version text PRIMARY KEY,
    cutoff       date,
    refreshed_at timestamptz,
    source       text NOT NULL,
    loaded_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE obs.roasters (
    roaster_id text PRIMARY KEY,
    name       text NOT NULL,
    country    char(2) NOT NULL,
    status     text,
    platform   text,
    seed_url   text
);

CREATE TABLE obs.products (
    product_id               uuid PRIMARY KEY,
    roaster_id               text NOT NULL REFERENCES obs.roasters (roaster_id),
    product_name             text NOT NULL,
    product_url              text,
    product_kind             text NOT NULL,  -- single_origin | blend | coffee | capsules | equipment | ...
    is_coffee                boolean NOT NULL,
    process                  text,
    process_canonical        text,
    variety                  text,
    certifications           text[],
    origin_country           char(2),
    origins_label            text,
    canonical_region         text,
    is_protected_designation boolean NOT NULL DEFAULT false,
    notable_variety          boolean NOT NULL DEFAULT false,
    has_certification        boolean NOT NULL DEFAULT false,
    first_seen_at            date,
    last_seen_at             date
);

CREATE INDEX products_roaster_idx ON obs.products (roaster_id);
CREATE INDEX products_origin_idx ON obs.products (origin_country);

CREATE TABLE obs.observations (
    product_id         uuid NOT NULL REFERENCES obs.products (product_id),
    capture_date       date NOT NULL,
    price_amount       numeric(12, 2),
    price_currency     char(3),
    price_unit_grams   integer,
    price_per_100g     numeric(12, 4),
    price_per_100g_eur numeric(12, 4),
    fx_rate_date       date,
    in_stock           boolean,
    sca_score          numeric(5, 2),
    PRIMARY KEY (product_id, capture_date)
);

CREATE TABLE obs.regions (
    country                  char(2) NOT NULL,
    region_name              text NOT NULL,
    lat                      double precision,
    lon                      double precision,
    altitude_min_masl        integer,
    altitude_max_masl        integer,
    source                   text,
    is_protected_designation boolean NOT NULL DEFAULT false,
    PRIMARY KEY (country, region_name)
);

CREATE TABLE obs.representation (
    reporter_country      char(2) NOT NULL,
    year                  integer,          -- NULL: panel shares for a country with no import data yet
    origin_country        char(2) NOT NULL,
    panel_mentions        integer,
    panel_share_pct       numeric(8, 2),
    panel_roasters        integer,
    panel_products        integer,
    import_kg             numeric(16, 1),
    import_share_pct      numeric(8, 2),
    representation_index  numeric(10, 2),
    UNIQUE NULLS NOT DISTINCT (reporter_country, year, origin_country)
);
