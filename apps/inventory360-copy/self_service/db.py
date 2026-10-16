"""
self_service/db.py
====================
dsg.inventory360.self_service_theme_runs — one row per theme run (scheduled job or on-demand button)
(all 8 themes for one date window, stored together as one JSON payload so
the page always reads a consistent set). Mirrors insights/db.py, including
backslash-then-quote escaping and returning None (not raising) when the
table doesn't exist yet.
"""

import datetime as dt
import json
import uuid

from sql_client import run_app_sql as _execute  # app-owned state tables: service principal, not OBO

TABLE_RUNS = "dsg.inventory360.self_service_theme_runs"


def _run_sql(statement: str) -> list[dict]:
    result = _execute(statement)
    if result["status"] != "success":
        raise RuntimeError(f"SQL failed: {result['error']}\nStatement: {statement}")
    return result["rows"]


def _escape(value) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


def ensure_table() -> None:
    _run_sql(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_RUNS} (
            run_id        STRING NOT NULL,
            generated_ts  TIMESTAMP NOT NULL,
            trigger       STRING NOT NULL,
            window_start  DATE NOT NULL,
            window_end    DATE NOT NULL,
            window_label  STRING NOT NULL,
            payload       STRING NOT NULL
        ) USING DELTA
    """)


def save_run(trigger: str, start: dt.date, end: dt.date, label: str, themes: list[dict]) -> str:
    run_id = str(uuid.uuid4())
    payload = json.dumps({"themes": themes}, default=str)
    _run_sql(f"""
        INSERT INTO {TABLE_RUNS} (run_id, generated_ts, trigger, window_start, window_end, window_label, payload)
        VALUES ({_escape(run_id)}, current_timestamp(), {_escape(trigger)},
                DATE {_escape(start.isoformat())}, DATE {_escape(end.isoformat())},
                {_escape(label)}, {_escape(payload)})
    """)
    return run_id


def get_latest_run() -> dict | None:
    result = _execute(f"""
        SELECT run_id, generated_ts, trigger, window_start, window_end, window_label, payload
        FROM {TABLE_RUNS} ORDER BY generated_ts DESC LIMIT 1
    """)
    if result["status"] != "success":
        if "TABLE_OR_VIEW_NOT_FOUND" in (result.get("error") or ""):
            return None
        raise RuntimeError(f"SQL failed: {result['error']}")
    if not result["rows"]:
        return None
    row = result["rows"][0]
    return {
        "run_id": row["run_id"], "generated_ts": row["generated_ts"], "trigger": row["trigger"],
        "start": dt.date.fromisoformat(str(row["window_start"])[:10]),
        "end": dt.date.fromisoformat(str(row["window_end"])[:10]),
        "label": row["window_label"],
        "themes": json.loads(row["payload"]).get("themes", []),
    }
