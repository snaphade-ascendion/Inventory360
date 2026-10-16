"""
self_service/pivot_engine.py
==============================
Everything the Self-Service page needs to turn "rows + values + date range"
into a DataFrame, with no Streamlit dependency (so the scheduled themes job
can use it too).

Rules the engine enforces (see catalog.py for the data):
  * A metric-view query can only group by dimensions that view has. So a
    measure is usable only if ITS view supports every selected dimension,
    and a dimension is usable only if every selected measure's view has it.
    measure_disabled_reason / dim_disabled_reason implement this -> the UI
    greys out anything that returns a reason.
  * Measures from several views are fetched with one query per view and
    outer-joined in pandas on the shared dimension columns.
  * Date range is applied through each view's own date dimension. Views
    with no date dimension are NOT filtered (a note says so).
  * Stock-snapshot views (Inventory Visibility) are never summed across
    dates: with no time dimension on the rows, the latest snapshot inside
    the range is used.
  * Every Statement Execution API value arrives as a string, so measure
    columns are coerced with pd.to_numeric; percentage measures are
    normalized to 0-1 fractions (the DDLs are inconsistent: some 0-1,
    some 0-100 -- same >1.5 heuristic as the Overview page).

Unverified against live Databricks from the build sandbox: WHERE on a
metric-view dimension that is not in the SELECT list, and
date_trunc() on a dimension (the latter already works in the Overview
agents). If the WHERE form is rejected, the SQL error is surfaced as-is.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd

from sql_client import run_sql
from self_service.catalog import (
    DIMENSIONS, MEASURES, VIEWS, TIME_DIM_KEYS, qualified,
    get_dim, get_measure, dim_column, view_supports,
)

MAX_FETCH_ROWS = 2000  # per metric view, per query


# ---------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------
def format_value(value, kind: str) -> str:
    """Human-readable value. Percentages are expected as 0-1 fractions."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if kind in ("pct1", "pct2"):
        return f"{v * 100:.1f}%"
    if kind == "int":
        return f"{v:,.0f}"
    if kind == "num1":
        return f"{v:,.1f}"
    if kind == "num2":
        return f"{v:,.2f}"
    if kind == "cur0":
        return f"${v:,.0f}"
    if kind == "cur2":
        return f"${v:,.2f}"
    return str(value)


# ---------------------------------------------------------------------
# Compatibility (drives the greying-out in the UI)
# ---------------------------------------------------------------------
def measure_disabled_reason(measure_key: str, selected_dims: list[str]) -> str | None:
    m = get_measure(measure_key)
    missing = [get_dim(k)["label"] for k in selected_dims if dim_column(k, m["table"]) is None]
    if missing:
        return f"{m['area']} doesn't have: {', '.join(missing)}"
    return None


def dim_disabled_reason(dim_key: str, selected_dims: list[str], selected_measures: list[str]) -> str | None:
    if dim_key in selected_dims:
        return None
    blockers = []
    for mk in selected_measures:
        m = get_measure(mk)
        if dim_column(dim_key, m["table"]) is None:
            blockers.append(m["label"])
    if blockers:
        return f"Not available for: {', '.join(blockers)}"
    if not selected_measures:
        wanted = list(selected_dims) + [dim_key]
        if not any(view_supports(t, wanted) for t in VIEWS):
            return "No subject area has this together with the rows already selected"
    return None


# ---------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------
def _run(sql: str) -> list[dict]:
    result = run_sql(sql)
    if result["status"] != "success":
        raise RuntimeError(f"SQL failed: {result['error']}\nStatement: {sql}")
    return result["rows"]


def _dim_expr(dim_key: str, table: str) -> str:
    col = dim_column(dim_key, table)
    if dim_key == "week":
        return f"date_trunc('WEEK', {col})"
    if dim_key == "month":
        return f"date_trunc('MONTH', {col})"
    return col


def build_query(table: str, dim_keys: list[str], measure_names: list[str],
                start: dt.date | None, end: dt.date | None,
                order_by: str | None = None, ascending: bool = False,
                limit: int = MAX_FETCH_ROWS, snapshot_date: dt.date | None = None) -> str:
    select = [f"{_dim_expr(k, table)} AS d_{k}" for k in dim_keys]
    select += [f"MEASURE({n}) AS m_{n}" for n in measure_names]

    where = ""
    date_col = VIEWS[table]["date_col"]
    if date_col and snapshot_date:
        where = f"WHERE {date_col} = DATE '{snapshot_date.isoformat()}'"
    elif date_col and start and end:
        where = f"WHERE {date_col} BETWEEN DATE '{start.isoformat()}' AND DATE '{end.isoformat()}'"

    time_dims = [k for k in dim_keys if k in TIME_DIM_KEYS]
    if order_by:
        order = f"ORDER BY {order_by} {'ASC' if ascending else 'DESC'} NULLS LAST"
    elif time_dims:
        order = f"ORDER BY d_{time_dims[0]} ASC"
    elif dim_keys and measure_names:
        order = f"ORDER BY m_{measure_names[0]} DESC NULLS LAST"
    else:
        order = ""

    group_sql = "GROUP BY ALL" if dim_keys else ""
    limit_sql = f"LIMIT {limit}" if dim_keys else ""
    return f"SELECT {', '.join(select)}\nFROM {qualified(table)}\n{where}\n{group_sql}\n{order}\n{limit_sql}"


def latest_snapshot(table: str, start: dt.date, end: dt.date) -> dt.date | None:
    """Most recent snapshot date of a snapshot-type view inside [start, end]."""
    date_col = VIEWS[table]["date_col"]
    first_measure = next(m["name"] for m in MEASURES if m["table"] == table)
    rows = _run(
        f"SELECT {date_col} AS d, MEASURE({first_measure}) AS v\n"
        f"FROM {qualified(table)}\n"
        f"WHERE {date_col} BETWEEN DATE '{start.isoformat()}' AND DATE '{end.isoformat()}'\n"
        f"GROUP BY ALL\nORDER BY d DESC\nLIMIT 1"
    )
    if not rows or not rows[0].get("d"):
        return None
    return dt.date.fromisoformat(str(rows[0]["d"])[:10])


def _normalize_pct(series: pd.Series) -> pd.Series:
    if series.dropna().empty:
        return series
    return series / 100.0 if series.abs().max() > 1.5 else series


def query_view(table: str, dim_keys: list[str], measure_names: list[str],
               start: dt.date | None, end: dt.date | None,
               order_by: str | None = None, ascending: bool = False,
               limit: int = MAX_FETCH_ROWS) -> tuple[pd.DataFrame, dict]:
    """
    One metric view -> DataFrame with columns d_<dimkey> (strings) and
    m_<measure> (floats; percentages as 0-1 fractions). Also returns a
    small info dict: {"snapshot_date": date|None, "capped": bool}.
    """
    info = {"snapshot_date": None, "capped": False}
    snapshot_date = None
    has_time_dim = any(k in TIME_DIM_KEYS for k in dim_keys)
    if VIEWS[table]["snapshot"] and VIEWS[table]["date_col"] and start and end and not has_time_dim:
        snapshot_date = latest_snapshot(table, start, end)
        info["snapshot_date"] = snapshot_date
        if snapshot_date is None:
            cols = [f"d_{k}" for k in dim_keys] + [f"m_{n}" for n in measure_names]
            return pd.DataFrame(columns=cols), info

    sql = build_query(table, dim_keys, measure_names, start, end, order_by, ascending, limit, snapshot_date)
    df = pd.DataFrame(_run(sql))
    if df.empty:
        df = pd.DataFrame(columns=[f"d_{k}" for k in dim_keys] + [f"m_{n}" for n in measure_names])
    info["capped"] = bool(dim_keys) and len(df) >= limit

    kinds = {m["name"]: m["kind"] for m in MEASURES if m["table"] == table}
    for n in measure_names:
        col = f"m_{n}"
        df[col] = pd.to_numeric(df[col], errors="coerce")
        if kinds.get(n) in ("pct1", "pct2"):
            df[col] = _normalize_pct(df[col])
    for k in dim_keys:
        df[f"d_{k}"] = df[f"d_{k}"].astype("object").where(df[f"d_{k}"].notna(), "(blank)")
    return df, info


# ---------------------------------------------------------------------
# The pivot
# ---------------------------------------------------------------------
@dataclass
class PivotResult:
    df: pd.DataFrame = field(default_factory=pd.DataFrame)
    dim_cols: list[str] = field(default_factory=list)        # display names, in order
    measure_cols: list[tuple[str, str]] = field(default_factory=list)  # (display name, kind)
    notes: list[str] = field(default_factory=list)
    capped: bool = False


def _fmt_date(d: dt.date) -> str:
    return d.strftime("%b %d, %Y").replace(" 0", " ")


def fetch_pivot(dim_keys: tuple, measure_keys: tuple, start: dt.date, end: dt.date) -> PivotResult:
    dim_keys, measure_keys = list(dim_keys), list(measure_keys)
    result = PivotResult()
    if not dim_keys or not measure_keys:
        return result

    measures = [get_measure(k) for k in measure_keys]
    for m in measures:  # defensive: UI should already have blocked this
        reason = measure_disabled_reason(m["key"], dim_keys)
        if reason:
            raise ValueError(f"'{m['label']}' can't be combined with the selected rows. {reason}")

    # Display names: plain label, plus "(Area)" only where two selected measures share a label.
    labels = [m["label"] for m in measures]
    display = {m["key"]: (f"{m['label']} ({m['area']})" if labels.count(m["label"]) > 1 else m["label"])
               for m in measures}
    dim_display = {k: get_dim(k)["label"] for k in dim_keys}

    tables: dict[str, list[dict]] = {}
    for m in measures:
        tables.setdefault(m["table"], []).append(m)

    merged: pd.DataFrame | None = None
    for table, ms in tables.items():
        names = [m["name"] for m in ms]
        df, info = query_view(table, dim_keys, names, start, end)
        result.capped = result.capped or info["capped"]
        df = df.rename(columns={f"m_{m['name']}": display[m["key"]] for m in ms})
        merged = df if merged is None else merged.merge(df, on=[f"d_{k}" for k in dim_keys], how="outer")

        cfg = VIEWS[table]
        if cfg["date_col"] is None:
            result.notes.append(f"The date range does not apply to {cfg['area']} (no date dimension) — it shows all available data.")
        elif cfg["snapshot"] and info["snapshot_date"]:
            result.notes.append(
                f"{cfg['area']} is a stock snapshot: it shows the latest snapshot in the range "
                f"({_fmt_date(info['snapshot_date'])}). Add Week or Month as a row to see each snapshot.")
        elif cfg["snapshot"] and not info["snapshot_date"] and not any(k in TIME_DIM_KEYS for k in dim_keys):
            result.notes.append(f"{cfg['area']} has no snapshot inside the selected date range.")
        if cfg["note"]:
            result.notes.append(cfg["note"])

    if len(tables) > 1:
        result.notes.append(
            "Measures from different subject areas are joined on the selected rows; each area's own "
            "definition of Region / Store applies (see the notes above).")
    if result.capped:
        result.notes.append(f"A subject area returned the maximum {MAX_FETCH_ROWS:,} rows — results are truncated. Use fewer rows or a shorter date range.")

    time_dims = [k for k in dim_keys if k in TIME_DIM_KEYS]
    first_measure_col = display[measure_keys[0]]
    if time_dims:
        merged = merged.sort_values([f"d_{k}" for k in time_dims], na_position="last")
    else:
        merged = merged.sort_values(first_measure_col, ascending=False, na_position="last")

    merged = merged.rename(columns={f"d_{k}": dim_display[k] for k in dim_keys})
    ordered = [dim_display[k] for k in dim_keys] + [display[k] for k in measure_keys]
    result.df = merged[ordered].reset_index(drop=True)
    result.dim_cols = [dim_display[k] for k in dim_keys]
    result.measure_cols = [(display[m["key"]], m["kind"]) for m in measures]
    return result


# ---------------------------------------------------------------------
# What dates does the data actually cover?
# ---------------------------------------------------------------------
def get_data_window(include_min: bool = True) -> dict:
    """
    Min/max date per date-bearing metric view and the window common to ALL of
    them. Presets ("Last 30 days" ...) are anchored to common_end rather than
    today's date so they never point at a period where some subject area
    has no data. If the views don't overlap at all, overlap=False and
    common_start > common_end.

    include_min=False skips the "earliest date" queries (the page only needs
    common_end for its presets; only the scheduled job needs common_start).
    Views are queried in parallel; one failing view is skipped and reported
    in "errors" rather than blanking the page.
    """
    from auth import ContextThreadPoolExecutor as ThreadPoolExecutor  # propagates the OBO user token

    def _bound(table: str, direction: str) -> dt.date:
        col = VIEWS[table]["date_col"]
        first_measure = next(m["name"] for m in MEASURES if m["table"] == table)
        rows = _run(
            f"SELECT {col} AS d, MEASURE({first_measure}) AS v FROM {qualified(table)} "
            f"GROUP BY ALL ORDER BY d {direction} LIMIT 1"
        )
        return dt.date.fromisoformat(str(rows[0]["d"])[:10])

    def _one(table: str):
        try:
            latest = _bound(table, "DESC")
            earliest = _bound(table, "ASC") if include_min else None
            return table, (earliest, latest), None
        except Exception as e:
            return table, None, str(e)

    tables = [t for t, cfg in VIEWS.items() if cfg["date_col"]]
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(_one, tables))

    per_view = {t: b for t, b, err in outcomes if b}
    errors = {t: err for t, b, err in outcomes if err}
    if not per_view:
        raise RuntimeError(f"Could not read date ranges from any metric view: {errors}")

    common_end = min(latest for _, latest in per_view.values())
    starts = [s for s, _ in per_view.values() if s is not None]
    common_start = max(starts) if starts else None
    return {
        "per_view": per_view, "errors": errors,
        "common_start": common_start, "common_end": common_end,
        "overlap": (common_start <= common_end) if common_start else True,
    }
