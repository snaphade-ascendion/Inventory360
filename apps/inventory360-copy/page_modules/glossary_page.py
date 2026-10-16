"""
page_modules/glossary_page.py
================================
Metrics Glossary: every metric across every Inventory360 subject area /
metric view, in one searchable table — Subject Area, Metric View, Metric,
Definition, Calculation, POC.

Metadata (definition / calculation / POC) comes from the same
DESCRIBE EXTENDED mechanism the Overview page's card tooltips already use
(hover.py) — but fetched ONCE PER TABLE (hover.get_table_measures_tooltip)
rather than once per measure, since a table with 6 measures doesn't need
6 separate DESCRIBE EXTENDED round-trips for the same underlying metadata.

Search: a single text box, filtered on Enter (Streamlit's st.text_input
only triggers a rerun on Enter/blur, not per keystroke, so this is the
default behavior — nothing special needed to "wait for Enter"). Supports
simple wildcards (*, ?) via fnmatch-style translation to regex; a plain
word with no wildcard just does a case-insensitive substring search
across every column.
"""

import html
import re

import streamlit as st

from auth import user_cache_data
from hover import get_table_measures_tooltip
from insights.metric_registry import GENIE_METRIC_CONFIG
from ui.theme import COLORS

_COLUMNS = ("subject_area", "table", "metric", "definition", "calculation", "poc")


# ---------------------------------------------------------------------
# Build the full catalog — one DESCRIBE EXTENDED per unique table.
# ---------------------------------------------------------------------
@user_cache_data(ttl=300, show_spinner=False)  # per-user: DESCRIBE EXTENDED runs OBO
def _build_catalog() -> list[dict]:
    rows = []
    for cfg in GENIE_METRIC_CONFIG.values():
        subject_area = cfg["display_name"]
        for view_cfg in cfg["metric_views"]:
            table = view_cfg["table"]
            measure_names = [m[0] for m in view_cfg["measures"]]
            try:
                tooltips = get_table_measures_tooltip(table, measure_names)
            except Exception:
                tooltips = {}
            for measure_name, display_name, _kind in view_cfg["measures"]:
                meta = tooltips.get(measure_name, {})
                rows.append({
                    "subject_area": subject_area,
                    "table": table,
                    "metric": display_name,
                    "definition": meta.get("definition") or "—",
                    "calculation": meta.get("calculation") or "—",
                    "poc": meta.get("poc") or "—",
                })
    rows.sort(key=lambda r: (r["subject_area"], r["metric"]))
    return rows


# ---------------------------------------------------------------------
# Search — wildcard-aware, case-insensitive, across every column.
# ---------------------------------------------------------------------
def _wildcard_to_regex(pattern: str) -> str:
    escaped = re.escape(pattern)
    return escaped.replace(r"\*", ".*").replace(r"\?", ".")


def _matches(row: dict, pattern: str) -> bool:
    if not pattern.strip():
        return True
    haystack = " ".join(str(row.get(col, "")) for col in _COLUMNS)
    try:
        return re.search(_wildcard_to_regex(pattern), haystack, re.IGNORECASE) is not None
    except re.error:
        return pattern.lower() in haystack.lower()


# ---------------------------------------------------------------------
# Rendering — a styled HTML table matching the app's color system.
# ---------------------------------------------------------------------
_TABLE_CSS = f"""
<style>
  .i360-glossary-wrap {{
    overflow-x: auto; border-radius: 10px;
    box-shadow: 0 2px 10px rgba(16,24,40,.08);
    border: 1px solid {COLORS['border']};
  }}
  table.i360-glossary-table {{
    width: 100%; border-collapse: collapse; font-size: 13.5px;
    background: {COLORS['card']};
  }}
  table.i360-glossary-table thead th {{
    background: {COLORS['accent']}; color: #fff; text-align: left;
    padding: 12px 16px; font-size: 11.5px; font-weight: 700;
    text-transform: uppercase; letter-spacing: .5px; white-space: nowrap;
  }}
  table.i360-glossary-table tbody td {{
    padding: 11px 16px; border-bottom: 1px solid {COLORS['border']};
    vertical-align: top; color: {COLORS['text']}; line-height: 1.5;
  }}
  table.i360-glossary-table tbody tr:nth-child(even) td {{ background: {COLORS['bg_alt']}; }}
  table.i360-glossary-table tbody tr:hover td {{ background: {COLORS['accent_soft']}; }}
  .i360-glossary-area {{
    display: inline-block; background: {COLORS['accent_soft']}; color: {COLORS['accent']};
    font-size: 11px; font-weight: 700; padding: 3px 10px; border-radius: 999px;
    white-space: nowrap;
  }}
  .i360-glossary-metric {{ font-weight: 700; color: {COLORS['text']}; white-space: nowrap; }}
  table.i360-glossary-table code {{
    font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px;
    background: {COLORS['bg_alt']}; padding: 2px 6px; border-radius: 4px;
    color: {COLORS['text']}; white-space: pre-wrap;
  }}
  table.i360-glossary-table tbody tr:nth-child(even) td code {{ background: {COLORS['card']}; }}
</style>
"""


def _render_table(rows: list[dict]) -> None:
    if not rows:
        st.info("No metrics match your search.")
        return

    body = []
    for r in rows:
        calc = html.escape(r["calculation"]) if r["calculation"] != "—" else "—"
        body.append(
            "<tr>"
            f"<td><span class='i360-glossary-area'>{html.escape(r['subject_area'])}</span></td>"
            f"<td><code>{html.escape(r['table'])}</code></td>"
            f"<td class='i360-glossary-metric'>{html.escape(r['metric'])}</td>"
            f"<td>{html.escape(r['definition'])}</td>"
            f"<td><code>{calc}</code></td>"
            f"<td>{html.escape(r['poc'])}</td>"
            "</tr>"
        )

    table_html = (
        '<div class="i360-glossary-wrap"><table class="i360-glossary-table">'
        "<thead><tr>"
        "<th>Subject Area</th><th>Metric View</th><th>Metric</th>"
        "<th>Definition</th><th>Calculation</th><th>POC</th>"
        "</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )
    st.markdown(_TABLE_CSS + table_html, unsafe_allow_html=True)


def render() -> None:
    st.title("Inventory360 — Metrics Glossary")
    st.caption("Every metric across every subject area, with its definition, calculation and point of contact.")

    query = st.text_input(
        "Search",
        placeholder="Search metrics… try fill*, *rate, a name, or a table like mv_order_orchestration  (press Enter)",
        label_visibility="collapsed",
    )

    with st.spinner("Loading metric metadata…"):
        catalog = _build_catalog()

    filtered = [r for r in catalog if _matches(r, query)] if query else catalog
    st.caption(f"{len(filtered)} of {len(catalog)} metrics")
    _render_table(filtered)
