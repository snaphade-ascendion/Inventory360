-- self_service/schema.sql
-- One row per SCHEDULED Self-Service theme run: all 8 themes for one date
-- window, stored as one JSON payload. Created automatically by
-- self_service/db.py::ensure_table(); this file is documentation.
CREATE TABLE IF NOT EXISTS dsg.inventory360.self_service_theme_runs (
    run_id        STRING NOT NULL,
    generated_ts  TIMESTAMP NOT NULL,
    trigger       STRING NOT NULL,    -- 'scheduled'
    window_start  DATE NOT NULL,
    window_end    DATE NOT NULL,
    window_label  STRING NOT NULL,    -- e.g. 'Last 30 days (Sep 1, 2026 – Sep 28, 2026)'
    payload       STRING NOT NULL     -- JSON: {"themes": [{key, name, headline, bullets, decision, evidence, notes, ...}]}
) USING DELTA;
