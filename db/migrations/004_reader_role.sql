-- Group role for the public API. It can read the curated api views and the RAG corpus, nothing else.
-- The login role the API connects with is created separately (`python -m explainer_data create-reader`)
-- and made a member of this one, with read-only transactions and a statement timeout.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'explainer_reader') THEN
        CREATE ROLE explainer_reader NOLOGIN;
    END IF;
END
$$;

REVOKE ALL ON SCHEMA obs FROM PUBLIC;
GRANT USAGE ON SCHEMA api, rag TO explainer_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA api TO explainer_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA rag TO explainer_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA api GRANT SELECT ON TABLES TO explainer_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA rag GRANT SELECT ON TABLES TO explainer_reader;
-- The api views read obs.* with their owner's rights, so the reader never needs obs itself.
