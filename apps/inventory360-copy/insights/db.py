"""
insights/db.py
================
Read/write helpers for dsg.inventory360.overview_insight_runs (see
schema.sql). Mirrors testing/db.py's pattern exactly, including the
backslash-then-quote escaping order (testing/db.py's fixed bug — a
JSON payload column makes this app just as exposed to it).
"""

import json
import uuid

from sql_client import run_app_sql as _execute  # app-owned state tables: service principal, not OBO

# Persona-aware copy: runs are stored in a SEPARATE table (with a persona column)
# so this app never mixes C-Level / Data Analyst rows into the original
# inventory360 app's dsg.inventory360.overview_insight_runs table.
TABLE_RUNS = "dsg.inventory360.overview_insight_runs_persona"
DEFAULT_PERSONA = "c_level"


def _run_sql(statement: str) -> list[dict]:
    result = _execute(statement)
    if result["status"] != "success":
        raise RuntimeError(f"SQL failed: {result['error']}\nStatement: {statement}")
    return result["rows"]


def _escape(value) -> str:
    """Escape backslashes FIRST, then quotes — see testing/db.py for why the order matters."""
    if value is None:
        return "NULL"
    escaped = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"'{escaped}'"


def save_run(trigger: str, agents: dict, key_callouts: list[str], persona: str = DEFAULT_PERSONA) -> str:
    """
    Persist one complete insight run. agents: {genie_key: agent_result_dict}
    (from sql_agent.run_insight_agent, snapshots/summary/insights included).
    """
    run_id = str(uuid.uuid4())
    payload = json.dumps({"agents": agents, "key_callouts": key_callouts}, default=str)
    _run_sql(f"""
        INSERT INTO {TABLE_RUNS} (run_id, generated_ts, trigger, persona, payload)
        VALUES ({_escape(run_id)}, current_timestamp(), {_escape(trigger)}, {_escape(persona)}, {_escape(payload)})
    """)
    return run_id


def update_callouts(run_id: str, agents: dict, key_callouts: list[str]) -> None:
    """
    Overwrites key_callouts on an existing run in place (used by the
    Overview page's Key Callouts "Edit" dialog) — `agents` is passed
    back in unchanged from the same get_latest_run() dict so the
    snapshots/summaries/insights the callouts were originally drawn
    from stay in the payload; only key_callouts changes.

    No version history yet, per the dialog's design: this REPLACES the
    run's payload rather than inserting a new row, so there is exactly
    one (latest) version of each callout at any time. Layering on
    history later means switching this to an INSERT of a new run
    instead, without changing callers of this function.
    """
    payload = json.dumps({"agents": agents, "key_callouts": key_callouts}, default=str)
    _run_sql(f"""
        UPDATE {TABLE_RUNS}
        SET payload = {_escape(payload)}
        WHERE run_id = {_escape(run_id)}
    """)


def get_latest_run(persona: str = DEFAULT_PERSONA) -> dict | None:
    """
    Latest run, parsed. Returns None if the table is empty OR doesn't
    exist yet (first-ever run not yet done) rather than raising — the
    Overview page falls back to an empty state in that case. The
    TABLE_OR_VIEW_NOT_FOUND case matters on a brand-new deployment:
    this function can be called on page load, before "Run insights now"
    (which is what actually creates the table via ensure_table()) has
    ever been clicked.
    """
    result = _execute(f"""
        SELECT run_id, generated_ts, trigger, persona, payload
        FROM {TABLE_RUNS}
        WHERE persona = {_escape(persona)}
        ORDER BY generated_ts DESC
        LIMIT 1
    """)
    if result["status"] != "success":
        if "TABLE_OR_VIEW_NOT_FOUND" in (result.get("error") or ""):
            return None
        raise RuntimeError(f"SQL failed: {result['error']}")
    rows = result["rows"]
    if not rows:
        return None
    row = rows[0]
    payload = json.loads(row["payload"])
    return {
        "run_id": row["run_id"],
        "generated_ts": row["generated_ts"],
        "trigger": row["trigger"],
        "persona": row["persona"],
        "agents": payload.get("agents", {}),
        "key_callouts": payload.get("key_callouts", []),
    }


def ensure_table() -> None:
    """Idempotent — safe to call on every app start. Mirrors schema.sql."""
    _run_sql(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_RUNS} (
            run_id        STRING NOT NULL,
            generated_ts  TIMESTAMP NOT NULL,
            trigger       STRING NOT NULL,
            persona       STRING NOT NULL,
            payload       STRING NOT NULL
        ) USING DELTA
    """)
