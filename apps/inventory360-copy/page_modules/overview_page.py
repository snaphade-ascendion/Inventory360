"""
page_modules/overview_page.py
===============================
The Overview page: Key Callouts (supervisor agent output), standard BI
cards (live SQL against the metric views), and one compact row per
subject area — chart | AI summary | chart — instead of a click-to-drill
panel. All 5 subject areas are visible at once, no selector.

Insights themselves are NOT generated on page load — insights/run_agents.py
runs on a schedule (Databricks Job) and writes to
dsg.inventory360.overview_insight_runs; this page just reads the latest
row. The "Run insights now" button calls the same orchestration function
in-process, for demo purposes, then re-reads — same code path either way.

Card VALUES (not insights) are separate: fetched live via direct SQL
every render (cached briefly with st.cache_data) so the numbers are
always current even between insight runs.

Charts use Altair directly (st.altair_chart), not st.line_chart/
st.bar_chart — the simple chart wrappers don't expose axis number
formatting, and percentages/currency/decimal-place control was asked
for explicitly. Altair ships as a core Streamlit dependency, so this
needs no new install.
"""

import datetime as dt

import altair as alt
import pandas as pd
import streamlit as st

from auth import ContextThreadPoolExecutor, user_cache_data
from ui.safe_html import esc, sanitize_llm_html
from genie.config import GENIE_SPACES
from sharing.compose import build_sections, build_share_image, plain_text
from hover import get_measure_tooltip, inject_hover_css, render_card_with_hover
from insights import db, formatter
from insights.metric_registry import GENIE_METRIC_CONFIG, OVERVIEW_CARDS
from insights.run_agents import run_all_and_store
from insights.personas import DEFAULT_PERSONA, PERSONAS
from insights.sql_agent import fetch_card_snapshot, fetch_drilldown

CARD_ROW_1 = OVERVIEW_CARDS[:5]
CARD_ROW_2 = OVERVIEW_CARDS[5:]

# date_dim per card's table, looked up once from the registry rather than
# duplicated onto every OVERVIEW_CARDS entry — None where the view has no
# date dimension (no period-over-period comparison possible there).
_TABLE_DATE_DIM = {
    view_cfg["table"]: view_cfg["date_dim"]
    for cfg in GENIE_METRIC_CONFIG.values()
    for view_cfg in cfg["metric_views"]
}

CHART_HEIGHT = 190  # plot-area height (axes/labels add to it)
VERTICAL_BAR_HEIGHT = 150  # vertical bars carry ~40px of slanted category labels; a shorter plot area keeps the total height level with the line/horizontal charts
# Column weights for [chart | summary | chart]. Originally 1 : 1.2 : 1 (31% of the row per chart); briefly 2.14
# (39%). 0.85 is 25% narrower than that 39% (29% per chart), which gives the summary column ~41% of the row.
CHART_COL_WEIGHT = 0.85
SUMMARY_COL_WEIGHT = 1.2
ACCENT_COLOR = "#0D9488"
LABEL_ANGLE = -40   # vertical-bar category labels: slanted + truncated so long names (e.g. product programs) can't eat the plot area
LABEL_LIMIT = 85
BAR_SIZE = 26  # bar thickness/width in px: 21 -> 26 (+25%). # ~50% wider than the previous 14px (still slimmer than Vega-Lite's default auto width)

# kind -> Vega-Lite/d3 number format string. Percentages/currency shown
# as such, capped at 1 decimal place everywhere (per request — no more
# than one decimal anywhere on an axis or tooltip).
AXIS_FORMAT = {
    "pct1": ".1%",
    "pct2": ".1%",
    "currency0": "$,.0f",
    "compact0": ",.0f",
    "num0": ",.0f",
    "num1": ",.1f",
}


# ---------------------------------------------------------------------
# Cached data access — cards/charts are live SQL, refreshed at most
# every 5 minutes per unique query so navigating the page doesn't
# re-hit the warehouse on every widget interaction.
# ---------------------------------------------------------------------
@user_cache_data(ttl=300, show_spinner=False)  # per-user: results depend on the user's UC permissions
def _cached_card_snapshot(table: str, measure: str, date_dim: str | None) -> dict:
    """ONE round-trip for both a card's value and its week-over-week delta — see
    insights/sql_agent.py::fetch_card_snapshot. Replaces what used to be two separate
    cached functions/queries (confirmed working via a UNION ALL query tested directly
    in the SQL editor before this was wired in)."""
    return fetch_card_snapshot(table, measure, date_dim)


@user_cache_data(ttl=300, show_spinner=False)  # per-user: results depend on the user's UC permissions
def _cached_drilldown(table: str, measure: str, date_dim: str | None, breakdown_dims: list[str]) -> dict:
    return fetch_drilldown(table, measure, date_dim, breakdown_dims)


def _format_value(value, kind: str) -> str:
    if value is None:
        return "—"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)

    if kind in ("pct1", "pct2"):
        return f"{value * 100:.1f}%" if abs(value) <= 1.5 else f"{value:.1f}%"
    if kind == "num0":
        return f"{value:,.0f}"
    if kind == "num1":
        return f"{value:,.1f}"
    if kind == "compact0":
        if abs(value) >= 1_000_000:
            return f"{value / 1_000_000:.1f}M"
        if abs(value) >= 1_000:
            return f"{value / 1_000:.0f}K"
        return f"{value:,.0f}"
    if kind == "currency0":
        if abs(value) >= 1_000_000:
            return f"${value / 1_000_000:.1f}M"
        if abs(value) >= 1_000:
            return f"${value / 1_000:.0f}K"
        return f"${value:,.0f}"
    return str(value)


def _axis_title(field: str) -> str:
    return field.replace("_", " ").title()


def _normalize_pct(df: pd.DataFrame, kind: str) -> pd.DataFrame:
    """
    Some DDLs store percentage measures as 0-1 fractions (expr divides by
    100.0), others as 0-100 directly (no division in the expr) —
    inconsistent across the metric views as given. Altair's ".1%" format
    assumes a 0-1 fraction and multiplies by 100 itself, so a 0-100 value
    would render as e.g. 9700.0% unless corrected first. Same heuristic
    _format_value() already uses for the cards: if values are bigger than
    a plausible fraction, they must already be 0-100 — divide down.
    """
    if kind not in ("pct1", "pct2") or df.empty:
        return df
    if df["value"].abs().max() > 1.5:
        df = df.copy()
        df["value"] = df["value"] / 100.0
    return df


def _format_delta(pop: dict | None, kind: str) -> str:
    """
    Small colored arrow+number line under a card's value — percentage
    POINT change for percentage-kind measures (e.g. "▲ 2.1 pts"), percent
    CHANGE for everything else (e.g. "▼ 4.3%"), per the ask: point
    comparison where the metric itself is already a percentage, percent
    comparison otherwise. Returns "" (nothing rendered) when there's no
    prior-period data to compare against, rather than fabricating one.
    """
    if not pop:
        return ""

    if kind in ("pct1", "pct2"):
        # abs_delta is in whatever units the raw measure is in (0-1 or
        # 0-100, inconsistent across views — same issue _normalize_pct
        # handles for charts). Normalize to percentage points here too.
        current, previous = pop["current_value"], pop["previous_value"]
        if abs(current) <= 1.5 and abs(previous) <= 1.5:
            point_delta = (current - previous) * 100
        else:
            point_delta = current - previous
        if abs(point_delta) < 0.05:
            return '<div class="i360-card-delta neutral">▬ flat vs last week</div>'
        arrow, css_class = ("▲", "positive") if point_delta > 0 else ("▼", "negative")
        return f'<div class="i360-card-delta {css_class}">{arrow} {abs(point_delta):.1f} pts vs last week</div>'

    pct_delta = pop.get("pct_delta")
    if pct_delta is None:
        return ""
    if abs(pct_delta) < 0.05:
        return '<div class="i360-card-delta neutral">▬ flat vs last week</div>'
    arrow, css_class = ("▲", "positive") if pct_delta > 0 else ("▼", "negative")
    return f'<div class="i360-card-delta {css_class}">{arrow} {abs(pct_delta):.1f}% vs last week</div>'


def _render_card(card: dict) -> None:
    try:
        date_dim = _TABLE_DATE_DIM.get(card["table"])
        snapshot = _cached_card_snapshot(card["table"], card["measure"], date_dim)
        value_text = _format_value(snapshot["value"].get("value"), card["kind"])
        error_html = ""
        delta_html = _format_delta(snapshot["pop"], card["kind"])
    except Exception as e:
        value_text = "—"
        error_html = f'<div class="i360-card-error">⚠ {esc(e)}</div>'
        delta_html = ""

    render_card_with_hover(card, value_text, delta_html, error_html)


def _render_card_row(cards: list[dict]) -> None:
    cols = st.columns(len(cards))
    for col, card in zip(cols, cards):
        with col:
            _render_card(card)


def _trend_chart(rows: list[dict], y_title: str, kind: str):
    df = pd.DataFrame(rows)
    if df.empty:
        return None
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["week"] = pd.to_datetime(df["week"])
    df = _normalize_pct(df, kind)
    fmt = AXIS_FORMAT.get(kind, ",.1f")
    return (
        alt.Chart(df)
        .mark_line(color=ACCENT_COLOR)
        .encode(
            x=alt.X("week:T", title=None, axis=alt.Axis(format="%b %d", grid=False)),
            y=alt.Y("value:Q", title=y_title, axis=alt.Axis(format=fmt, grid=False)),
            tooltip=[
                alt.Tooltip("week:T", title="Week", format="%b %d, %Y"),
                alt.Tooltip("value:Q", title=y_title, format=fmt),
            ],
        )
        .properties(height=CHART_HEIGHT, background="white")
        .configure_view(strokeWidth=0)
    )


def _breakdown_chart(rows: list[dict], dim: str, y_title: str, kind: str, horizontal: bool = False):
    df = pd.DataFrame(rows)
    if df.empty:
        return None
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = _normalize_pct(df, kind)
    fmt = AXIS_FORMAT.get(kind, ",.1f")

    n_bars = len(df)
    # Horizontal bars are as thick as BAR_SIZE, so the plot must be tall enough for n bars (+5px gaps) or they overlap.
    plot_height = max(CHART_HEIGHT, n_bars * (BAR_SIZE + 5)) if horizontal else VERTICAL_BAR_HEIGHT

    if horizontal:
        encode_kwargs = dict(
            y=alt.Y(f"{dim}:N", title=None, sort="-x", axis=alt.Axis(labelLimit=140)),
            x=alt.X("value:Q", title=y_title, axis=alt.Axis(format=fmt, grid=False)),
        )
    else:
        encode_kwargs = dict(
            x=alt.X(f"{dim}:N", title=None, sort="-y", axis=alt.Axis(labelAngle=LABEL_ANGLE, labelLimit=LABEL_LIMIT)),
            y=alt.Y("value:Q", title=y_title, axis=alt.Axis(format=fmt, grid=False)),
        )

    return (
        alt.Chart(df)
        .mark_bar(color=ACCENT_COLOR, size=BAR_SIZE)
        .encode(
            tooltip=[
                alt.Tooltip(f"{dim}:N", title=_axis_title(dim)),
                alt.Tooltip("value:Q", title=y_title, format=fmt),
            ],
            **encode_kwargs,
        )
        .properties(height=plot_height, background="white")
        .configure_view(strokeWidth=0)
    )


def _build_subject_area_charts(genie_key: str, horizontal: bool = False) -> dict:
    """Builds the same chart1/chart2 Altair objects for a subject area that
    _render_subject_area_row displays on the page. Extracted so the Share feature's
    chart export (_collect_subject_area_summaries) draws from IDENTICAL chart objects —
    same data, same styling — rather than recomputing its own version."""
    cfg = GENIE_METRIC_CONFIG[genie_key]
    view_cfg = cfg["metric_views"][0]
    measure_name, measure_label, kind = view_cfg["measures"][0]

    data = _cached_drilldown(view_cfg["table"], measure_name, view_cfg["date_dim"], view_cfg["breakdown_dims"])

    # Chart 1: trend if this view has a date dimension, else first breakdown.
    if data["trend"]:
        chart1 = _trend_chart(data["trend"], measure_label, kind)
        chart1_caption = f"{measure_label} — trend"
        dim2 = view_cfg["breakdown_dims"][0] if view_cfg["breakdown_dims"] else None
    elif view_cfg["breakdown_dims"]:
        dim1 = view_cfg["breakdown_dims"][0]
        chart1 = _breakdown_chart(data["breakdowns"].get(dim1, []), dim1, measure_label, kind, horizontal=horizontal)
        chart1_caption = f"{measure_label} by {_axis_title(dim1)}"
        dim2 = view_cfg["breakdown_dims"][1] if len(view_cfg["breakdown_dims"]) > 1 else None
    else:
        chart1, chart1_caption, dim2 = None, "", None

    chart2, chart2_caption = None, ""
    if dim2:
        chart2 = _breakdown_chart(data["breakdowns"].get(dim2, []), dim2, measure_label, kind, horizontal=horizontal)
        chart2_caption = f"{measure_label} by {_axis_title(dim2)}"

    return {"chart1": chart1, "chart1_caption": chart1_caption, "chart2": chart2, "chart2_caption": chart2_caption}


def _render_subject_area_row(genie_key: str, latest_run: dict | None, horizontal: bool = False, is_last: bool = False) -> None:
    cfg = GENIE_METRIC_CONFIG[genie_key]
    charts = _build_subject_area_charts(genie_key, horizontal=horizontal)
    chart1, chart1_caption = charts["chart1"], charts["chart1_caption"]
    chart2, chart2_caption = charts["chart2"], charts["chart2_caption"]

    col1, col_summary, col2 = st.columns([CHART_COL_WEIGHT, SUMMARY_COL_WEIGHT, CHART_COL_WEIGHT])

    with col1:
        if chart1 is not None:
            st.caption(chart1_caption)
            st.altair_chart(chart1, use_container_width=True, theme=None)

    with col_summary:
        st.markdown(
            f'<div style="font-weight:700; font-size:20px;">{cfg["display_name"]}'
            f'<span class="i360-ai-badge">✨ AI-generated</span></div>',
            unsafe_allow_html=True,
        )
        agent = (latest_run or {}).get("agents", {}).get(genie_key)
        if not agent:
            st.caption("No insight run yet — click **Run insights now** above.")
        else:
            if agent.get("caveat"):
                st.caption(agent["caveat"])
            st.markdown(sanitize_llm_html(agent.get("summary", "")), unsafe_allow_html=True)
            for bullet in agent.get("insights", []):
                st.markdown(f"- {sanitize_llm_html(bullet)}", unsafe_allow_html=True)

    with col2:
        if chart2 is not None:
            st.caption(chart2_caption)
            st.altair_chart(chart2, use_container_width=True, theme=None)

    if not is_last:
        st.markdown('<hr class="i360-divider-strong">', unsafe_allow_html=True)


def _collect_card_summaries() -> list[dict]:
    """Reads the already-cached card values (no extra warehouse hit) in the shape the share
    module wants — value AND the trend delta (e.g. "2.0M (▲ 5.9% vs last week)"), so the
    share download carries the same trend signal the live card shows, not just the raw number."""
    summaries = []
    for card in OVERVIEW_CARDS:
        try:
            date_dim = _TABLE_DATE_DIM.get(card["table"])
            snapshot = _cached_card_snapshot(card["table"], card["measure"], date_dim)
            value_text = _format_value(snapshot["value"].get("value"), card["kind"])
            delta_text = plain_text(_format_delta(snapshot["pop"], card["kind"]))
        except Exception:
            value_text, delta_text = "—", ""
        display = f"{value_text} ({delta_text})" if delta_text else value_text
        summaries.append({"label": card["label"], "value_text": display})
    return summaries


def _collect_subject_area_summaries(latest_run: dict | None) -> list[dict]:
    """One entry per subject area shown in the Subject-Area Intelligence expander below —
    same genie_keys, same order, same display names — now also carrying the same chart
    objects that section renders, so the Share download can export them as real images."""
    summaries = []
    for genie_key in GENIE_SPACES.keys():
        cfg = GENIE_METRIC_CONFIG[genie_key]
        agent = (latest_run or {}).get("agents", {}).get(genie_key) or {}
        try:
            charts = _build_subject_area_charts(genie_key)
            chart_objs = [c for c in (charts["chart1"], charts["chart2"]) if c is not None]
        except Exception:
            chart_objs = []
        summaries.append({
            "display_name": cfg["display_name"],
            "summary": agent.get("summary"),
            "insights": agent.get("insights", []),
            "charts": chart_objs,
        })
    return summaries


@st.dialog("Share insights")
def _share_dialog(latest_run: dict | None) -> None:
    """A modal rather than an inline expanding panel: page content never shifts while this
    is open, and it has an unambiguous close affordance (✕ in the corner, click outside, or
    Esc) — the two complaints about the old inline st.container(border=True) version."""
    st.caption("Choose what to include, then download.")
    all_selected = st.checkbox("All", key="ov_share_all")
    sel_callouts = st.checkbox("Key Callouts", value=all_selected, key="ov_share_callouts",
                                disabled=all_selected)
    sel_cards = st.checkbox("Metric Cards", value=all_selected, key="ov_share_cards",
                             disabled=all_selected)
    sel_areas = st.checkbox("Subject-Area Intelligence (each area)", value=all_selected,
                             key="ov_share_areas", disabled=all_selected)

    selection = set()
    if all_selected or sel_callouts:
        selection.add("callouts")
    if all_selected or sel_cards:
        selection.add("cards")
    if all_selected or sel_areas:
        selection.add("subject_areas")

    if selection:
        sections = build_sections(
            selection,
            key_callouts=(latest_run or {}).get("key_callouts"),
            card_summaries=_collect_card_summaries() if "cards" in selection else [],
            subject_area_summaries=(
                _collect_subject_area_summaries(latest_run) if "subject_areas" in selection else []
            ),
        )
        image_bytes = build_share_image(sections)
    else:
        image_bytes = b""  # button below is disabled in this case, so this is never actually downloadable

    # Always visible, greyed out until a selection is made — rather than appearing only
    # once something's picked — so the download action itself is never a surprise.
    st.download_button(
        "⬇️ Download",
        data=image_bytes,
        file_name=f"inventory360_share_{dt.date.today().isoformat()}.png",
        mime="image/png",
        key="ov_share_download",
        disabled=not selection,
    )
    if not selection:
        st.caption("Pick at least one item above to enable the download.")


def _render_share(latest_run: dict | None) -> None:
    if st.button("📤 Share"):
        _share_dialog(latest_run)


@st.dialog("Edit Key Callouts")
def _edit_callouts_dialog(latest_run: dict) -> None:
    """A modal, same reasoning as _share_dialog above. Shows each callout as
    plain text (formatter.to_plain_text strips the <b>/<span> markup the LLM
    normally writes) so editing is just editing a sentence, never HTML. On
    Save, the edited plain text is run back through the same formatting
    rules the agents use (formatter.reformat_callouts) and OVERWRITES the
    current run's key_callouts in place — no version history yet, this is
    always "the latest version", by design for now."""
    st.caption(
        "Edit the text below, then save — your wording is kept exactly as written. "
        "Bold/colored number formatting is re-applied automatically to match the rest "
        "of the app."
    )
    plain_lines = [formatter.to_plain_text(c) for c in latest_run.get("key_callouts", [])]
    edited = st.text_area(
        "One callout per line", value="\n".join(plain_lines), height=220,
        key="ov_edit_callouts_text", label_visibility="collapsed",
    )

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("💾 Save", key="ov_edit_callouts_save", use_container_width=True, type="primary"):
            new_lines = [ln.strip() for ln in edited.split("\n") if ln.strip()]
            with st.spinner("Applying formatting…"):
                formatted = formatter.reformat_callouts(new_lines)
            db.update_callouts(latest_run["run_id"], latest_run.get("agents", {}), formatted)
            st.cache_data.clear()
            st.rerun()
    with col_cancel:
        if st.button("Cancel", key="ov_edit_callouts_cancel", use_container_width=True):
            st.rerun()


def _prefetch_all() -> None:
    """Fires every independent read query this page needs CONCURRENTLY, before any
    rendering starts, instead of the ~40-50 of them happening one at a time as each
    card/row renders sequentially. Every function called here is a pure st.cache_data
    data fetch with no Streamlit UI calls inside it — that split matters, because
    Streamlit's UI APIs (st.markdown, st.columns, etc.) are NOT safe to call from a
    background thread, only from the main script thread. This function only warms the
    cache; the actual rendering below is untouched and still calls the same cached
    functions per card/row — they just hit a warm cache by the time it does, instead of
    each one blocking on its own network round-trip in turn."""
    tasks = []
    with ContextThreadPoolExecutor(max_workers=8) as pool:  # carries the OBO user token into workers
        for card in OVERVIEW_CARDS:
            date_dim = _TABLE_DATE_DIM.get(card["table"])
            tasks.append(pool.submit(_cached_card_snapshot, card["table"], card["measure"], date_dim))
            tasks.append(pool.submit(get_measure_tooltip, card["table"], card["measure"]))

        for genie_key in GENIE_SPACES.keys():
            view_cfg = GENIE_METRIC_CONFIG[genie_key]["metric_views"][0]
            measure_name = view_cfg["measures"][0][0]
            tasks.append(pool.submit(
                _cached_drilldown, view_cfg["table"], measure_name, view_cfg["date_dim"], view_cfg["breakdown_dims"]
            ))

        # Swallow individual failures here — a query that fails during prefetch just
        # means that card/row falls back to its normal per-card error handling when the
        # sequential render path below calls the same (still-uncached) function again.
        # One bad query must never block the rest of the page from loading.
        for t in tasks:
            try:
                t.result()
            except Exception:
                pass


@st.cache_resource(show_spinner=False)
def _ensure_table_once() -> bool:
    """db.ensure_table() is a CREATE TABLE IF NOT EXISTS — idempotent, but was running on
    EVERY page load, forever, even though the table is permanently created after the very
    first run. st.cache_resource (no ttl) runs this once per app process lifetime instead
    of once per page view, removing one more full sequential warehouse round-trip that sat
    in front of _prefetch_all() on every single load."""
    db.ensure_table()
    return True


def render() -> None:
    st.title("Inventory360 — Overview")

    # ---- Audience selector: drives the prompts behind Key Callouts and
    # Subject-Area Intelligence (insights/personas.py). Each persona has its
    # own stored runs, so switching just reads that persona's latest run.
    persona_keys = list(PERSONAS.keys())
    persona = st.radio(
        "View insights as",
        options=persona_keys,
        index=persona_keys.index(DEFAULT_PERSONA),
        format_func=lambda k: PERSONAS[k]["label"],
        horizontal=True,
        key="ov_persona",
    )
    persona_label = PERSONAS[persona]["label"]

    inject_hover_css()
    _ensure_table_once()
    latest_run = db.get_latest_run(persona)
    _prefetch_all()

    header_cols = st.columns([3.3, 1, 1])
    with header_cols[0]:
        if latest_run:
            ts = latest_run["generated_ts"]
            trigger_label = "scheduled run" if latest_run["trigger"] == "scheduled" else "manual run"
            st.caption(f"{persona_label} insights last generated: {ts} · {trigger_label}")
        else:
            st.caption(f"{persona_label} insights have not been generated yet.")
    with header_cols[1]:
        _render_share(latest_run)
    with header_cols[2]:
        if st.button("🔄 Run insights now"):
            st.warning("Running — this takes ~1-2 minutes (6 paced LLM calls). Please don't switch tabs or submit anything else until it finishes, or the run will be cancelled with nothing saved.")
            with st.spinner(f"Running 5 subject-area agents + supervisor for {persona_label}… (~1-2 min)"):
                run_all_and_store(trigger="manual", persona=persona)
            st.cache_data.clear()
            st.rerun()

    # ---- Key Callouts ----
    st.markdown(
        '<div class="i360-callout">'
        f'<div style="font-size:18px; font-weight:700;">KEY CALLOUTS · {esc(persona_label.upper())}'
        '<span class="i360-ai-badge">✨ AI-generated</span></div>'
        + (
            "".join(f'<div style="font-size:14.5px; line-height:1.6; margin-top:4px;">• {sanitize_llm_html(c)}</div>' for c in latest_run["key_callouts"])
            if latest_run and latest_run.get("key_callouts")
            else '<div style="font-size:14.5px;">No insights generated yet — click "Run insights now" above.</div>'
        )
        + "</div>",
        unsafe_allow_html=True,
    )
    # Edit trigger sits bottom-right, directly under the box above, rather than
    # inside it — a real HTML form control can't be mixed into the raw
    # st.markdown(unsafe_allow_html=True) block the callouts themselves render
    # in, so this is its own element, right-aligned via the empty spacer column.
    _, edit_col = st.columns([6, 1])
    with edit_col:
        if st.button("✎ Edit", key="ov_edit_callouts_open", use_container_width=True,
                     disabled=not (latest_run and latest_run.get("key_callouts"))):
            _edit_callouts_dialog(latest_run)

    # ---- Cards ----
    _render_card_row(CARD_ROW_1)
    st.markdown("")
    st.caption("Store Experience & Productivity")
    _render_card_row(CARD_ROW_2)

    st.markdown("")

    # ---- Subject-area rows: chart | summary | chart, one per genie ----
    with st.expander(f"Subject-Area Intelligence — {persona_label} view", expanded=True):
        for i, genie_key in enumerate(GENIE_SPACES.keys()):
            _render_subject_area_row(genie_key, latest_run, horizontal=(i % 2 == 1), is_last=(i == len(GENIE_SPACES) - 1))
