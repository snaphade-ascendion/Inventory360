"""
sql_client.py
=============
Execute arbitrary SQL against Unity Catalog via the Databricks
Statement Execution API.

Keeping all SQL logic here means:
  - If the warehouse or execution method changes, one file to update
  - app.py stays clean — it just calls run_sql()

Two entry points (see auth.py):
  run_sql()      -> runs ON BEHALF OF the signed-in user (OBO). Use for all
                    business data / metric views / metadata reads.
  run_app_sql()  -> runs as the app's service principal. Use ONLY for the
                    app's own state tables (testing, alerts audit, insight
                    and theme runs, asked questions).
"""

import os
from auth import get_app_client, get_user_client

SAMPLE_SQL = "SELECT * FROM `dsg`.`inventory360`.`dim_calendar` LIMIT 100;"


def _get_warehouse_id(w) -> str:
    """
    Resolve a SQL warehouse ID.
    Uses DATABRICKS_WAREHOUSE_ID env var if set, otherwise picks the
    first running (or available) SQL warehouse visible to the given client.
    """
    env_id = os.environ.get("DATABRICKS_WAREHOUSE_ID")
    if env_id:
        return env_id

    for wh in w.warehouses.list():
        if wh.state and wh.state.value in ("RUNNING", "STARTING"):
            return wh.id
    # Fall back to first warehouse found
    for wh in w.warehouses.list():  # noqa: RET504
        return wh.id
    raise RuntimeError("No SQL warehouse found in workspace.")


def run_sql(query: str, warehouse_id: str | None = None) -> dict:
    """Execute SQL on behalf of the signed-in user (OBO). See _execute for the return shape."""
    try:
        w = get_user_client()
    except Exception as e:
        return {"status": "error", "error": str(e), "sql": query,
                "columns": [], "col_types": [], "rows": [], "total_rows": 0}
    return _execute(w, query, warehouse_id)


def run_app_sql(query: str, warehouse_id: str | None = None) -> dict:
    """Execute SQL as the app's service principal — app-owned state tables only."""
    return _execute(get_app_client(), query, warehouse_id)


def _execute(w, query: str, warehouse_id: str | None = None) -> dict:
    """
    Execute a SQL query and return all results as a structured dict.

    Parameters
    ----------
    query : str
        The SQL statement to execute.
    warehouse_id : str | None
        SQL warehouse ID. Auto-resolved if not provided.

    Returns
    -------
    dict
        {
          "status":    "success" | "error",
          "error":     str or None,
          "sql":       str,              # the query that was executed
          "columns":   [str, ...],
          "col_types": [{"name": ..., "type": ...}, ...],
          "rows":      [dict, ...],      # each row as {col: value}
          "total_rows": int,
        }
    """
    try:
        wh_id = warehouse_id or _get_warehouse_id(w)
        resp = w.statement_execution.execute_statement(
            statement=query,
            warehouse_id=wh_id,
            wait_timeout="50s",
        )

        if resp.status and resp.status.state and resp.status.state.value == "FAILED":
            error_msg = resp.status.error.message if resp.status.error else "Unknown SQL error"
            return {"status": "error", "error": error_msg, "sql": query,
                    "columns": [], "col_types": [], "rows": [], "total_rows": 0}

        schema_cols = resp.manifest.schema.columns
        columns   = [col.name for col in schema_cols]
        col_types = [
            {"name": col.name, "type": str(col.type_name.value) if col.type_name else "STRING"}
            for col in schema_cols
        ]
        rows_raw = resp.result.data_array if resp.result and resp.result.data_array else []
        rows     = [dict(zip(columns, row)) for row in rows_raw]

        return {
            "status":     "success",
            "error":      None,
            "sql":        query,
            "columns":    columns,
            "col_types":  col_types,
            "rows":       rows,
            "total_rows": len(rows),
        }

    except Exception as e:
        return {"status": "error", "error": str(e), "sql": query,
                "columns": [], "col_types": [], "rows": [], "total_rows": 0}
