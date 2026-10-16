"""
insights/sql_agent.py
=======================
One insight agent per Genie space. Each agent:
  1. Runs direct SQL against every Unity Catalog metric view assigned to
     its Genie space (insights/metric_registry.py), using the metric-view
     query form: SELECT <dims>, MEASURE(<measure>) FROM <view> GROUP BY ALL.
  2. Formats the results (overall snapshot + a couple of breakdowns) into
     plain text.
  3. Sends that text to the LLM (call_site="synthesis" -> deepseek, per
     llm_client.ENDPOINTS) asking for a short summary + bullet insights.

Deliberately direct SQL, not the Genie NL flow — confirmed with the user.
No caching/session-state here; insights/run_agents.py decides when agents
run (scheduled job or on-demand) and insights/db.py persists the result.
"""

import json

from sql_client import run_sql
from llm_client import ask_llm_json
from insights.metric_registry import GENIE_METRIC_CONFIG, qualified
from prompts.markdown_style import MARKDOWN_STYLE_INSTRUCTIONS
from insights.personas import DEFAULT_PERSONA, get_persona

MAX_BREAKDOWN_ROWS = 8


def _run(query: str) -> list[dict]:
    result = run_sql(query)
    if result["status"] != "success":
        raise RuntimeError(f"SQL failed: {result['error']}\nStatement: {query}")
    return result["rows"]


def _overall_snapshot(table: str, measures: list[tuple]) -> dict:
    """One row: every measure aggregated across the whole metric view."""
    measure_sql = ", ".join(f"MEASURE({m[0]}) AS {m[0]}" for m in measures)
    rows = _run(f"SELECT {measure_sql} FROM {qualified(table)}")
    return rows[0] if rows else {}


def _breakdown(table: str, dim: str, measures: list[tuple]) -> list[dict]:
    """Every measure, grouped by one dimension, top N rows by the first measure."""
    measure_sql = ", ".join(f"MEASURE({m[0]}) AS {m[0]}" for m in measures)
    first_measure = measures[0][0]
    query = f"""
        SELECT {dim}, {measure_sql}
        FROM {qualified(table)}
        GROUP BY ALL
        ORDER BY {first_measure} DESC
        LIMIT {MAX_BREAKDOWN_ROWS}
    """
    return _run(query)


def _trend(table: str, date_dim: str, measures: list[tuple]) -> list[dict]:
    """Weekly trend for the first measure only, last 8 weeks."""
    first_measure = measures[0][0]
    query = f"""
        SELECT date_trunc('WEEK', {date_dim}) AS week, MEASURE({first_measure}) AS value
        FROM {qualified(table)}
        GROUP BY ALL
        ORDER BY week DESC
        LIMIT 8
    """
    rows = _run(query)
    return list(reversed(rows))


def _period_over_period(table: str, date_dim: str, measure: str) -> dict | None:
    """
    Latest complete week's value for one measure vs the week before it.
    Returns None if there isn't at least 2 weeks of data. This is what
    gives agents (and cards) something to actually describe as "up" or
    "down" — without it there's no prior-period number to compare
    against, so an LLM has no honest basis to use the positive/negative
    formatting at all (which is exactly what was happening before this
    was added: every number came back as a flat, colorless <b> value).
    """
    query = f"""
        SELECT date_trunc('WEEK', {date_dim}) AS week, MEASURE({measure}) AS value
        FROM {qualified(table)}
        GROUP BY ALL
        ORDER BY week DESC
        LIMIT 2
    """
    rows = _run(query)
    if len(rows) < 2:
        return None
    try:
        current = float(rows[0]["value"])
        previous = float(rows[1]["value"])
    except (TypeError, ValueError):
        return None
    return {
        "current_week": str(rows[0]["week"]),
        "previous_week": str(rows[1]["week"]),
        "current_value": current,
        "previous_value": previous,
        "abs_delta": current - previous,
        "pct_delta": ((current - previous) / previous * 100) if previous else None,
    }


def _format_view_context(view_cfg: dict, snapshot: dict, breakdowns: dict, pop: dict | None) -> str:
    lines = [f"### Metric view: {view_cfg['table']}", f"Overall snapshot: {json.dumps(snapshot, default=str)}"]
    if pop:
        lines.append(
            f"Week-over-week change in {view_cfg['measures'][0][1]} (the primary measure): "
            f"{json.dumps(pop, default=str)} — use this to describe an actual trend "
            f"direction (up/down) with the positive/negative formatting; do not describe "
            f"a trend for any measure you don't have this kind of comparison for."
        )
    for dim, rows in breakdowns.items():
        lines.append(f"Breakdown by {dim} (top {MAX_BREAKDOWN_ROWS} by {view_cfg['measures'][0][0]}):")
        lines.append(json.dumps(rows, default=str))
    return "\n".join(lines)


def build_agent_system_prompt(persona: str | None = DEFAULT_PERSONA) -> str:
    """Per-persona system prompt for the subject-area agents (see insights/personas.py)."""
    p = get_persona(persona)
    return f"""You are a supply-chain analytics agent for Inventory360, a sporting
goods retailer. You have been given real, freshly queried data for ONE subject area
(a set of Unity Catalog metric views). Write a short, factual summary and {p['agent_bullets']} bullet
insights written for {p['agent_audience']}.

Audience-specific guidance:
{p['agent_guidance']}

Rules:
- Only state numbers and comparisons that are directly supported by the data given.
- Prefer noting the most notable outlier, trend, or concentration (e.g. "concentrated
  in the West region") over a flat restatement of every number.
- If a week-over-week comparison is provided for the primary measure, describe that
  trend explicitly (state both the direction and the size of the change) using the
  positive/negative formatting below — this is exactly the kind of number that
  formatting exists for. Don't invent a trend for a measure you have no comparison for.
- Do not invent causes or recommend actions — describe what the data shows, not why.
- Keep the summary to {p['agent_summary_len']}. Keep each insight bullet to one sentence.

{MARKDOWN_STYLE_INSTRUCTIONS}

Respond with exactly one JSON object and nothing else. The "summary" and each string in
"insights" should themselves contain the HTML-formatted text per the rules above:
{{"summary": "<summary>", "insights": ["<bullet 1>", "<bullet 2>", ...]}}
"""


# Backwards-compatible default (C-Level) for any other importer.
AGENT_SYSTEM_PROMPT = build_agent_system_prompt(DEFAULT_PERSONA)


def run_insight_agent(genie_key: str, persona: str = DEFAULT_PERSONA) -> dict:
    """
    Query every metric view for one Genie space and produce one insight
    record: {"genie_key", "display_name", "summary", "insights": [...],
    "snapshots": {table: {...}}, "caveat": str|None}.
    """
    cfg = GENIE_METRIC_CONFIG[genie_key]
    context_blocks = []
    snapshots = {}

    for view_cfg in cfg["metric_views"]:
        table = view_cfg["table"]
        measures = view_cfg["measures"]
        snapshot = _overall_snapshot(table, measures)
        snapshots[table] = snapshot

        breakdowns = {}
        for dim in view_cfg["breakdown_dims"][:2]:
            breakdowns[dim] = _breakdown(table, dim, measures)

        pop = _period_over_period(table, view_cfg["date_dim"], measures[0][0]) if view_cfg["date_dim"] else None

        context_blocks.append(_format_view_context(view_cfg, snapshot, breakdowns, pop))

    context_text = "\n\n".join(context_blocks)
    caveat_note = f"\nKNOWN DATA CAVEAT: {cfg['caveat']}\n" if cfg.get("caveat") else ""

    messages = [
        {"role": "system", "content": build_agent_system_prompt(persona)},
        {"role": "user", "content": (
            f"Subject area: {cfg['display_name']}\n{caveat_note}\n{context_text}"
        )},
    ]

    try:
        parsed = ask_llm_json(messages, call_site="synthesis", temperature=0.7)
        summary = parsed.get("summary", "")
        insights = parsed.get("insights", [])
    except Exception as e:
        summary = f"Insight generation failed: {e}"
        insights = []

    return {
        "genie_key": genie_key,
        "display_name": cfg["display_name"],
        "summary": summary,
        "insights": insights,
        "snapshots": snapshots,
        "caveat": cfg.get("caveat"),
    }


def fetch_card_value(table: str, measure: str) -> dict:
    """One measure, whole-view aggregate — used by the Overview cards (live query, independent of agent runs)."""
    rows = _run(f"SELECT MEASURE({measure}) AS value FROM {qualified(table)}")
    return rows[0] if rows else {"value": None}


def fetch_card_delta(table: str, measure: str, date_dim: str | None) -> dict | None:
    """Public wrapper for the Overview cards — same week-over-week comparison the agents use, for the up/down arrow."""
    if not date_dim:
        return None
    return _period_over_period(table, date_dim, measure)


def fetch_card_snapshot(table: str, measure: str, date_dim: str | None) -> dict:
    """
    Merged version of fetch_card_value() + fetch_card_delta() — ONE warehouse round-trip
    instead of two, via UNION ALL of the same two independently-valid query shapes those
    functions already used (confirmed working directly against this app's metric views
    before this was written — same 'overall' ungrouped aggregate + 'weekly' grouped-by-
    week aggregate pattern, just combined into one statement).

    Returns {"value": <dict as fetch_card_value would>, "pop": <dict as fetch_card_delta
    would, or None>} — same two shapes callers already handle, just fetched together.
    fetch_card_value()/fetch_card_delta() are left in place for any other caller that
    still wants just one piece (e.g. a future API that doesn't need both).
    """
    if not date_dim:
        return {"value": fetch_card_value(table, measure), "pop": None}

    query = f"""
        (SELECT 'overall' AS row_type, CAST(NULL AS STRING) AS week, MEASURE({measure}) AS value
         FROM {qualified(table)}
         GROUP BY ALL)

        UNION ALL

        (SELECT 'weekly' AS row_type, CAST(date_trunc('WEEK', {date_dim}) AS STRING) AS week,
                MEASURE({measure}) AS value
         FROM {qualified(table)}
         GROUP BY ALL
         ORDER BY week DESC
         LIMIT 2)
    """
    rows = _run(query)

    overall_row = next((r for r in rows if r["row_type"] == "overall"), None)
    weekly_rows = [r for r in rows if r["row_type"] == "weekly"]
    # weekly_rows arrive in the branch's own ORDER BY week DESC order — newest first,
    # same order _period_over_period()'s rows[0]/rows[1] relied on below.

    value = {"value": overall_row["value"] if overall_row else None}

    pop = None
    if len(weekly_rows) >= 2:
        try:
            current = float(weekly_rows[0]["value"])
            previous = float(weekly_rows[1]["value"])
            pop = {
                "current_week": str(weekly_rows[0]["week"]),
                "previous_week": str(weekly_rows[1]["week"]),
                "current_value": current,
                "previous_value": previous,
                "abs_delta": current - previous,
                "pct_delta": ((current - previous) / previous * 100) if previous else None,
            }
        except (TypeError, ValueError):
            pop = None

    return {"value": value, "pop": pop}


def fetch_drilldown(table: str, measure: str, date_dim: str | None, breakdown_dims: list[str]) -> dict:
    """
    Data for the Overview drilldown panel: an (optional) weekly trend for one measure,
    plus up to two breakdown charts — fetched in ONE warehouse round-trip via UNION ALL
    instead of up to three separate ones (this was the single biggest contributor to the
    Overview page's query count: 5 subject areas x up to 3 queries each = up to 15 calls).

    Each UNION ALL branch is EXACTLY the same SELECT ... GROUP BY ALL / MEASURE(...)
    shape the three original separate queries used — just combined into one statement
    with a 'section' tag column so the one result set can be split back into
    trend_rows / breakdown_charts in Python afterward. This is not a reinterpretation of
    the data, only fewer round-trips to fetch the identical rows the separate queries
    returned. (Deliberately NOT reusing _trend()/_breakdown() above — those are also
    called independently by run_insight_agent for the AI insight pipeline and must keep
    issuing their own separate queries there; this merge is specific to what the
    Overview page's drilldown panel needs.)
    """
    dims_to_use = breakdown_dims[:2]
    branches = []  # [(section_tag, sql)]

    if date_dim:
        branches.append(("__trend__", f"""
            SELECT '__trend__' AS section, CAST(date_trunc('WEEK', {date_dim}) AS STRING) AS dim_value,
                   MEASURE({measure}) AS value
            FROM {qualified(table)}
            GROUP BY ALL
            ORDER BY dim_value DESC
            LIMIT 8
        """))

    for dim in dims_to_use:
        branches.append((dim, f"""
            SELECT '{dim}' AS section, CAST({dim} AS STRING) AS dim_value, MEASURE({measure}) AS value
            FROM {qualified(table)}
            GROUP BY ALL
            ORDER BY value DESC
            LIMIT {MAX_BREAKDOWN_ROWS}
        """))

    if not branches:
        return {"trend": [], "breakdowns": {}}

    combined_sql = "\nUNION ALL\n".join(f"({sql.strip()})" for _, sql in branches)
    rows = _run(combined_sql)

    trend_rows = []
    breakdown_charts = {dim: [] for dim, _ in branches if dim != "__trend__"}
    for row in rows:
        section = row["section"]
        if section == "__trend__":
            trend_rows.append({"week": row["dim_value"], "value": row["value"]})
        else:
            breakdown_charts[section].append({section: row["dim_value"], "value": row["value"]})

    # Each branch's own ORDER BY/LIMIT already sorted and capped its rows correctly;
    # the only re-sort needed is trend: the DESC-per-branch order (newest first, for the
    # LIMIT 8 to keep the most RECENT 8 weeks) has to be reversed to oldest -> newest for
    # the line chart, exactly as the original _trend() did.
    trend_rows = list(reversed(trend_rows))

    return {"trend": trend_rows, "breakdowns": breakdown_charts}
