"""
hover.py
========
Hover-over tooltip for Overview page metric cards.

Ported from a standalone prototype that queried Genie live to get a
measure's SQL, then ran DESCRIBE EXTENDED to pull its Definition /
Calculation / Source / Point-of-Contact metadata. Per decision: the
Genie round-trip is dropped here — we already know each card's
table + measure from insights.metric_registry.OVERVIEW_CARDS, so we
go straight to DESCRIBE EXTENDED on the metric view. This also reuses
the app's existing sql_client.run_sql() (shared warehouse-resolution
+ error handling) instead of calling WorkspaceClient directly.

Tooltip content convention (matches the prototype): a measure's
`comment` is expected to read "Definition: ... Point of Contact: ...".
Not every measure in the current DDLs follows this yet (some have no
comment, or a short dev note instead) — sections with no content are
simply omitted, never shown as empty/placeholder.

Usage from overview_page.py:
    from hover import inject_hover_css, render_card_with_hover

    inject_hover_css()                 # once, e.g. in render()
    render_card_with_hover(card, value_text, delta_html, error_html)
"""

import json
import re

import streamlit as st

from auth import user_cache_data
from ui.safe_html import esc
from insights.metric_registry import qualified
from sql_client import run_sql

_POC_RE = re.compile(r"Point\s+of\s+Contact\s*[:.]+\s*(.+)", re.IGNORECASE)
_DEFINITION_PREFIX_RE = re.compile(r"^Definition\s*[:.]+\s*", re.IGNORECASE)


# ---------------------------------------------------------------------
# Metadata fetch — DESCRIBE EXTENDED on the metric view, cached like the
# rest of the Overview page's data access (5 min TTL).
# ---------------------------------------------------------------------
@user_cache_data(ttl=3600, show_spinner=False)  # per-user: DESCRIBE EXTENDED runs OBO
def _describe_extended(table: str) -> tuple[list[str], list[dict]]:
    """Raw DESCRIBE EXTENDED result for a table, cached per table (not per measure) — the
    expensive part callers share. Returns (columns, rows); ([], []) on any failure.

    TTL is 1 hour, not the 5-minute TTL the live data queries use — this is metric
    *definitions* (name, calculation, POC), which essentially never change intra-day.
    Every card's hover tooltip is fetched eagerly on every Overview page render (a true
    "only fetch on actual mouse hover" isn't achievable without a custom JS component
    that calls back into Python — Streamlit has no built-in hover event), so without a
    long TTL here this was hitting the warehouse for static metadata just as often as
    the actual live numbers. 1 hour means roughly one DESCRIBE EXTENDED per table per
    hour instead of one per table every 5 minutes, with no loss of freshness that
    actually matters for this data."""
    fq_table = qualified(table)
    resp = run_sql(f"DESCRIBE EXTENDED {fq_table}")
    if resp["status"] != "success" or not resp["rows"]:
        return [], []
    return resp["columns"], resp["rows"]


def _parse_measure_metadata(cols: list[str], rows: list[dict], measure: str) -> dict:
    """Extracts one measure's {"definition", "calculation", "source", "poc", "format"} out of
    an already-fetched DESCRIBE EXTENDED result. Shared by get_measure_tooltip (single-measure,
    used by the Overview page cards) and get_table_measures_tooltip (whole-table, used by the
    Glossary page) so neither duplicates the parsing logic."""
    result: dict = {}
    view_text = ""
    comment_text = ""

    for row in rows:
        vals = [row.get(c) for c in cols]
        col_name = (vals[0] or "").strip() if len(vals) > 0 else ""
        data_type = vals[1] or "" if len(vals) > 1 else ""
        comment = vals[2] if len(vals) > 2 else None
        metadata_str = vals[3] if len(vals) > 3 else ""

        if col_name == measure and "measure" in str(data_type).lower():
            comment_text = comment if comment and comment != "None" else ""
            try:
                meta = json.loads(metadata_str) if metadata_str else {}
                fmt = meta.get("format")
                if fmt:
                    result["format"] = fmt
            except (json.JSONDecodeError, TypeError):
                pass

        if col_name == "View Text":
            view_text = data_type

    # Split comment into Definition / Point of Contact, same convention
    # as the prototype. Falls back to showing the whole comment as the
    # definition when "Point of Contact" isn't present.
    if comment_text:
        poc_match = _POC_RE.search(comment_text)
        if poc_match:
            result["poc"] = poc_match.group(1).strip().rstrip(".")
            definition = comment_text[: poc_match.start()].strip().rstrip(".")
        else:
            definition = comment_text
        definition = _DEFINITION_PREFIX_RE.sub("", definition).strip()
        if definition:
            result["definition"] = definition

    # Pull the measure's SQL expression out of the view's YAML text.
    if view_text:
        expr_match = re.search(rf"- name: {re.escape(measure)}\s+expr: (.+)", view_text)
        if expr_match:
            result["calculation"] = expr_match.group(1).strip()

    return result


def get_measure_tooltip(table: str, measure: str) -> dict:
    """
    Returns {"definition": str, "calculation": str, "source": str, "poc": str},
    with any key missing/empty when that info isn't available. Never raises —
    callers always get a dict back, possibly empty. Used by the Overview page's
    per-card hover tooltips (one measure at a time).
    """
    cols, rows = _describe_extended(table)
    if not rows:
        return {}
    result = _parse_measure_metadata(cols, rows, measure)
    result["source"] = qualified(table)
    return result


def get_table_measures_tooltip(table: str, measures: list[str]) -> dict[str, dict]:
    """
    Same metadata as get_measure_tooltip, for every measure in `measures` at once,
    off a SINGLE DESCRIBE EXTENDED call for the table (shared via _describe_extended's
    cache) instead of one call per measure. Used by the Glossary page, which needs
    every metric in every metric view rather than one card's measure at a time.
    Returns {measure_name: {"definition":..., "calculation":..., "source":..., "poc":...}}.
    Never raises — a table that fails to describe just yields empty dicts per measure.
    """
    cols, rows = _describe_extended(table)
    source = qualified(table)
    out = {}
    for measure in measures:
        meta = _parse_measure_metadata(cols, rows, measure) if rows else {}
        if rows:
            meta["source"] = source
        out[measure] = meta
    return out


# ---------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------
def _tt_section(label: str, value: str) -> str:
    return (
        f'<div class="i360-tt-section">'
        f'<div class="i360-tt-label">{label}</div>'
        f'<div class="i360-tt-value">{value}</div>'
        f"</div>"
    )


def _tooltip_html(meta: dict) -> str:
    sections = []
    if meta.get("definition"):
        # UC comments/metadata are editable by anyone with MODIFY on the view -> treat as untrusted
        sections.append(_tt_section("Definition", esc(meta["definition"])))
    if meta.get("calculation"):
        sections.append(_tt_section("Calculation", f"<code>{esc(meta['calculation'])}</code>"))
    if meta.get("source"):
        sections.append(_tt_section("Source", esc(meta["source"])))
    if meta.get("poc"):
        sections.append(_tt_section("POC", esc(meta["poc"])))
    return "".join(sections) if sections else '<div class="i360-tt-empty">No metadata available</div>'


def render_card_with_hover(card: dict, value_text: str, delta_html: str = "", error_html: str = "") -> None:
    """
    Drop-in replacement for overview_page._render_card's markup — same
    .i360-card shell and classes, with a hover info-icon added next to
    the label. Tooltip metadata is fetched (cached) per card's table/measure.
    """
    meta = {}
    try:
        meta = get_measure_tooltip(card["table"], card["measure"])
    except Exception:
        pass  # tooltip is best-effort; never block the card itself

    st.markdown(
        f'<div class="i360-card">'
        f'<div class="i360-card-header">'
        f'<div class="i360-card-label">{card["label"]}</div>'
        f'<div class="i360-tooltip-container">'
        f'<span class="i360-info-icon">i</span>'
        f'<div class="i360-tooltip-bubble">{_tooltip_html(meta)}</div>'
        f"</div>"
        f"</div>"
        f'<div class="i360-card-value">{value_text}</div>'
        f"{delta_html}"
        f"{error_html}"
        f"</div>",
        unsafe_allow_html=True,
    )


_HOVER_CSS = """
<style>
  .i360-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .i360-tooltip-container {
    display: inline-block;
    position: relative;
  }
  .i360-info-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    background-color: #F0F4F8;
    color: #0D9488;
    border-radius: 50%;
    font-weight: bold;
    font-size: 11px;
    border: 1px solid #CCE4E1;
    cursor: pointer;
    transition: all 0.15s ease;
  }
  .i360-info-icon:hover {
    background-color: #0D9488;
    color: #FFFFFF;
  }
  .i360-tooltip-bubble {
    visibility: hidden;
    opacity: 0;
    width: max-content;
    min-width: 240px;
    max-width: 360px;
    background: #1E2433;
    color: #DDE3EC;
    text-align: left;
    border-radius: 10px;
    padding: 14px 16px;
    font-size: 0.74rem;
    line-height: 1.5;
    position: absolute;
    z-index: 9999;
    top: calc(100% + 8px);
    right: 0;
    transition: opacity 0.15s ease, visibility 0.15s ease;
    box-shadow: 0 8px 24px rgba(0,0,0,0.3);
    white-space: normal;
  }
  .i360-tooltip-container:hover .i360-tooltip-bubble {
    visibility: visible;
    opacity: 1;
  }
  .i360-tt-section { margin-bottom: 10px; }
  .i360-tt-section:last-child { margin-bottom: 0; }
  .i360-tt-label {
    font-size: 0.6rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #7FB3A8;
    margin-bottom: 3px;
  }
  .i360-tt-value {
    color: #DDE3EC;
    font-size: 0.74rem;
    line-height: 1.5;
  }
  .i360-tt-value code {
    font-family: ui-monospace, Menlo, Consolas, monospace;
    font-size: 0.72rem;
    color: #DDE3EC !important;
    background: transparent !important;
    padding: 0 !important;
    border: none !important;
    white-space: pre-wrap !important;
  }
  .i360-tt-empty {
    color: #9AA3B2;
    font-size: 0.74rem;
    font-style: italic;
  }
</style>
"""

def inject_hover_css() -> None:
    """Must run on EVERY render(), not just the first. Streamlit rebuilds the whole element
    tree on every script rerun (e.g. clicking any button elsewhere on the page) — an element
    this function skips emitting on a given rerun is removed from the page, not left in place.
    An earlier version gated this behind a session_state flag to "only inject once"; that
    silently deleted the <style> tag on the second rerun onward, which is why the tooltip
    bubbles (always present in the HTML, meant to be hidden until :hover) showed up fully
    expanded on screen after any button click."""
    st.markdown(_HOVER_CSS, unsafe_allow_html=True)
