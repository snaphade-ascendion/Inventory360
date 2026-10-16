-- insights/schema.sql
-- =====================================================================
-- One row per Overview insight run. A run = the 5 per-genie agents +
-- the supervisor callouts, generated together and stored as one record
-- so the app always reads a consistent snapshot (never a mix of two
-- different runs' numbers).
--
-- trigger: 'scheduled' (Databricks Job) or 'manual' (Refresh Now button)
-- payload: JSON blob — {"agents": {genie_key: {...}}, "key_callouts": [...]}
--          kept as one JSON column rather than normalized tables since
--          the app only ever reads the latest whole run.
-- =====================================================================

CREATE TABLE IF NOT EXISTS dsg.inventory360.overview_insight_runs (
    run_id        STRING NOT NULL,
    generated_ts  TIMESTAMP NOT NULL,
    trigger       STRING NOT NULL,   -- 'scheduled' | 'manual'
    payload       STRING NOT NULL    -- JSON: {"agents": {...}, "key_callouts": [...]}
) USING DELTA;
