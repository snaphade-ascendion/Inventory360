"""
self_service/theme_agent.py
=============================
Runs one Self-Service theme: executes its queries (themes.py) for a date
window, adds a period-over-period baseline computed in Python (so the LLM
never does arithmetic), then makes ONE LLM call (call_site="synthesis")
that returns {headline, bullets[], decision}.

Same code path for the scheduled Databricks Job (run_themes.py) and the
page's "Generate insights" button.

Notes
  * Independent SQL statements run in a small thread pool (SQL_PARALLELISM);
    set it to 1 to run strictly one at a time. auth.get_workspace_client()
    is a module-level shared client with no Streamlit dependency, so this is
    safe in both callers.
  * A failed query does not kill the theme: it is recorded in "notes" and the
    theme is written from whatever succeeded. If every query fails the theme
    carries an error message instead of made-up text.
"""

from __future__ import annotations

import datetime as dt
import json
from auth import ContextThreadPoolExecutor as ThreadPoolExecutor  # propagates the OBO user token to workers

import pandas as pd

from llm_client import ask_llm_json
from prompts.markdown_style import MARKDOWN_STYLE_INSTRUCTIONS
from self_service.catalog import MEASURES, VIEWS, get_dim
from self_service.dates import format_range, prior_range
from self_service.pivot_engine import query_view, format_value

SQL_PARALLELISM = 4
FETCH_ROWS = 500

_MEASURE = {(m["table"], m["name"]): m for m in MEASURES}


def _label(table: str, name: str) -> str:
    return _MEASURE[(table, name)]["label"]


def _kind(table: str, name: str) -> str:
    return _MEASURE[(table, name)]["kind"]


# ---------------------------------------------------------------------
# Query execution
# ---------------------------------------------------------------------
def _run_ranked_query(q: dict, start: dt.date, end: dt.date) -> tuple[pd.DataFrame, dict]:
    df, info = query_view(
        q["table"], q["dims"], q["measures"], start, end,
        order_by=f"m_{q['sort_by']}", ascending=q["ascending"], limit=FETCH_ROWS,
    )
    if "min_support" in q and not df.empty:
        col, frac = q["min_support"]
        threshold = df[f"m_{col}"].median() * frac
        df = df[df[f"m_{col}"] >= threshold]
    return df.head(q["limit"]).reset_index(drop=True), info


def _run_baseline(table: str, measures: list[str], start: dt.date, end: dt.date) -> tuple[pd.DataFrame, dict]:
    return query_view(table, [], measures, start, end)


def _delta_text(current: float, previous: float, kind: str) -> str:
    """Pre-computed change vs the prior period, so the LLM only has to quote it."""
    if current is None or previous is None or pd.isna(current) or pd.isna(previous):
        return "no prior-period comparison"
    if kind in ("pct1", "pct2"):
        d = (current - previous) * 100
        if abs(d) < 0.05:
            return "flat vs prior period"
        return f"{'up' if d > 0 else 'down'} {abs(d):.1f} percentage points vs prior period ({format_value(previous, kind)})"
    if previous == 0:
        return "no prior-period comparison"
    d = (current - previous) / abs(previous) * 100
    if abs(d) < 0.05:
        return "flat vs prior period"
    return f"{'up' if d > 0 else 'down'} {abs(d):.1f}% vs prior period ({format_value(previous, kind)})"


# ---------------------------------------------------------------------
# One theme
# ---------------------------------------------------------------------
THEME_SYSTEM_PROMPT = f"""You are a supply-chain decision-support analyst for Inventory360, a sporting goods
retailer. You are given freshly queried data for ONE decision theme over a stated date window. Write what
a merchandising / supply-chain / store-operations leader needs to decide what to look at first.

Return three things:
- "headline": 1-2 sentences — the single most important finding AND why it matters for the decision.
- "bullets": 3-4 one-sentence findings. Each must name a specific store, vendor, category, style, region or
  node from the data and include its number. Compare against the company-wide baseline or prior period where
  the data provides one.
- "decision": ONE sentence starting with an action verb (e.g. "Prioritize…", "Review…", "Investigate…",
  "Confirm…") that says where to focus first, naming the specific entities from the data. This is a
  recommended focus, NOT a claim about the cause.

Rules:
- Use ONLY numbers and names that appear in the data below. Never do your own arithmetic: quote the change
  wording (up/down, points or %) exactly as provided in the baseline lines.
- Do not invent causes. If two lists are related (e.g. the same store appears in both), say so only if the
  same name really appears in both.
- Respect the data notes (e.g. a table that is not date-filtered, a stock snapshot, or mocked data): mention
  such a limitation in one short clause when it affects how much weight a finding deserves.
- If a table is empty or missing, say what could not be assessed instead of guessing.

{MARKDOWN_STYLE_INSTRUCTIONS}

Respond with exactly one JSON object and nothing else:
{{"headline": "<text>", "bullets": ["<text>", ...], "decision": "<text>"}}
"""


def _table_text(title: str, columns: list[str], rows: list[list[str]]) -> str:
    lines = [f"### {title}", " | ".join(columns)]
    lines += [" | ".join(r) for r in rows] if rows else ["(no rows)"]
    return "\n".join(lines)


def run_theme(theme: dict, start: dt.date, end: dt.date) -> dict:
    p_start, p_end = prior_range(start, end)
    notes: list[str] = []

    # ---- 1. queue every SQL statement this theme needs ----
    tables = {}
    for q in theme["queries"]:
        tables.setdefault(q["table"], [])
        for m in q["measures"]:
            if m not in tables[q["table"]]:
                tables[q["table"]].append(m)

    jobs = {}
    for i, q in enumerate(theme["queries"]):
        jobs[("q", i)] = lambda q=q: _run_ranked_query(q, start, end)
    for table, measures in tables.items():
        jobs[("base", table)] = lambda t=table, ms=measures: _run_baseline(t, ms, start, end)
        if VIEWS[table]["date_col"]:
            jobs[("prior", table)] = lambda t=table, ms=measures: _run_baseline(t, ms, p_start, p_end)

    def _safe(job):
        try:
            return job(), None
        except Exception as e:
            return None, str(e)

    with ThreadPoolExecutor(max_workers=SQL_PARALLELISM) as pool:
        futures = {k: pool.submit(_safe, job) for k, job in jobs.items()}
        results = {k: f.result() for k, f in futures.items()}

    # ---- 2. baseline lines (current window + change vs prior window) ----
    context_blocks, evidence = [], []
    for table, measures in tables.items():
        cfg = VIEWS[table]
        base, base_err = results[("base", table)]
        prior, _ = results.get(("prior", table), (None, None))
        if base_err:
            notes.append(f"{cfg['area']} baseline query failed: {base_err.splitlines()[0]}")
            continue
        base_df, base_info = base
        prior_df = prior[0] if prior else None
        if base_df.empty:
            continue
        lines = [f"### Company-wide baseline — {cfg['area']}"]
        for m in measures:
            cur = base_df[f"m_{m}"].iloc[0]
            prev = prior_df[f"m_{m}"].iloc[0] if prior_df is not None and not prior_df.empty else None
            kind = _kind(table, m)
            change = _delta_text(cur, prev, kind) if prior_df is not None else "no prior-period comparison (view has no date dimension)"
            lines.append(f"- {_label(table, m)}: {format_value(cur, kind)} ({change})")
        context_blocks.append("\n".join(lines))

        if cfg["date_col"] is None:
            notes.append(f"{cfg['area']} has no date dimension: figures cover all available data, not just the selected window.")
        elif cfg["snapshot"] and base_info.get("snapshot_date"):
            notes.append(f"{cfg['area']} is a stock snapshot: figures are the latest snapshot in the window ({base_info['snapshot_date'].isoformat()}).")
        if cfg["note"]:
            notes.append(cfg["note"])

    # ---- 3. ranked tables ----
    n_ok = 0
    for i, q in enumerate(theme["queries"]):
        res, err = results[("q", i)]
        if err:
            notes.append(f"Query '{q['label']}' failed: {err.splitlines()[0]}")
            continue
        df, info = res
        n_ok += 1
        columns = [get_dim(d)["label"] for d in q["dims"]] + [_label(q["table"], m) for m in q["measures"]]
        rows = []
        for _, r in df.iterrows():
            rows.append([str(r[f"d_{d}"]) for d in q["dims"]]
                        + [format_value(r[f"m_{m}"], _kind(q["table"], m)) for m in q["measures"]])
        direction = "lowest first" if q["ascending"] else "highest first"
        title = f"{q['label']} ({direction}; {VIEWS[q['table']]['area']})"
        context_blocks.append(_table_text(title, columns, rows))
        evidence.append({"title": q["label"], "area": VIEWS[q["table"]]["area"], "columns": columns, "rows": rows})

    base = {
        "key": theme["key"], "name": theme["name"], "question": theme["question"],
        "window_start": start.isoformat(), "window_end": end.isoformat(),
        "notes": sorted(set(notes)), "evidence": evidence,
    }
    if n_ok == 0:
        return {**base, "headline": "Insight could not be generated — every query for this theme failed.",
                "bullets": [], "decision": "", "error": True}

    # ---- 4. one LLM call ----
    user_msg = (
        f"Theme: {theme['name']}\nDecision question: {theme['question']}\n"
        f"Date window: {format_range(start, end)} (prior period for comparison: {format_range(p_start, p_end)})\n"
        f"Data notes: {json.dumps(sorted(set(notes)))}\n\n" + "\n\n".join(context_blocks)
    )
    try:
        parsed = ask_llm_json(
            [{"role": "system", "content": THEME_SYSTEM_PROMPT}, {"role": "user", "content": user_msg}],
            call_site="synthesis",
            temperature=0.7,
        )
        return {**base,
                "headline": parsed.get("headline", ""),
                "bullets": parsed.get("bullets", []),
                "decision": parsed.get("decision", ""),
                "error": False}
    except Exception as e:
        return {**base, "headline": f"Insight generation failed: {e}", "bullets": [], "decision": "", "error": True}
