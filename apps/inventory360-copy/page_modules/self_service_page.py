"""
page_modules/self_service_page.py
===================================
Storylines and BYOV tabs (formerly one Self-Service tab; per the mockup / Goal doc):

  1. STORYLINES tab (render_storylines) — 8 fixed key themes (no "Key themes" heading; date range left, Generate insights right). 8 fixed, decision-oriented themes. The Databricks Job
     (self_service/run_themes.py) stores one scheduled run for a default
     window; the "Generate insights" button re-runs all themes live for the
     date range selected on this page and SAVES the result to the same table
     (trigger='manual'), so it survives a dropped browser session — a long
     run can outlive the app's websocket, which wipes st.session_state.
     The page always shows the most recent saved run, scheduled or manual.
  2. BYOV tab (render_byov, own independent date range, keys bv_*) — Build your own view: click "+ Add" dimensions (rows) and measures
     (values) from ONE combined list, laid out as full-width grids (3 groups per row). Anything that can't be combined with
     the current selection is greyed out with the reason shown underneath.
     Excel download of the resulting table.
  3. BYOV tab — Ask the data — the table above (plus date range, selections, notes) goes
     to the synthesis LLM with the user's question. Text answers only for now.

Layout notes for this app's older Streamlit:
  * The Storylines date range lives in a collapsed expander at the top left; Generate insights sits at the top right. Its widgets run
    even while collapsed, and the range is read from st.session_state BEFORE they render (see _current_range),
    so the heading label and everything below always use the latest selection.
  * Theme picker = a grid of white tiles. Unselected tiles are st.button()s scoped by a hidden marker element
    (see ui/theme.py); the selected tile is a plain green <div>.
  * "Your table" is an expander (already styled white app-wide) because restyling st.container(border=True)
    was tried and reverted earlier in this app.
  * The builder section is NOT inside an st.expander because it uses
    expanders itself (Streamlit forbids expander-in-expander).
  * st.tabs() in app.py runs every tab's code on every rerun, so all SQL here
    is cached (st.cache_data) — a click in the builder must not re-hit the
    warehouse for data it already has.
  * Row/value selection is stored in st.session_state and changed through
    on_click callbacks (one rerun per click, no stale state).
"""

import datetime as dt
import html

import pandas as pd
import streamlit as st

from auth import user_cache_data
from ui.safe_html import sanitize_llm_html
from self_service import db
from self_service.ask import ask_about_table
from self_service.catalog import DIMENSIONS, MEASURES, get_dim, get_measure
from self_service.dates import PRESETS, resolve_range, format_range, format_date
from self_service.export import to_download
from self_service.pivot_engine import (
    fetch_pivot, get_data_window, format_value, measure_disabled_reason, dim_disabled_reason,
)
from self_service.run_themes import run_all_themes
from self_service.themes import THEMES

MAX_MEASURES = 4
MAX_DISPLAY_ROWS = 1000
GREY = "#9AA0A6"


# ---------------------------------------------------------------------
# Cached data access
# ---------------------------------------------------------------------
@user_cache_data(ttl=3600, show_spinner=False)  # per-user: OBO data access
def _cached_window() -> dict:
    return get_data_window(include_min=False)


@user_cache_data(ttl=300, show_spinner=False)  # per-user: OBO data access
def _cached_pivot(dim_keys: tuple, measure_keys: tuple, start_iso: str, end_iso: str):
    return fetch_pivot(dim_keys, measure_keys, dt.date.fromisoformat(start_iso), dt.date.fromisoformat(end_iso))


@st.cache_data(ttl=60, show_spinner=False)
def _cached_latest_run():
    return db.get_latest_run()


# ---------------------------------------------------------------------
# Session state + callbacks
# ---------------------------------------------------------------------
def _init_state() -> None:
    st.session_state.setdefault("ss_rows", [])
    st.session_state.setdefault("ss_vals", [])
    st.session_state.setdefault("ss_qa", [])
    st.session_state.setdefault("ss_qa_sig", None)
    if not st.session_state.get("ss_table_ready"):
        try:
            db.ensure_table()
            st.session_state["ss_table_ready"] = True
        except Exception:
            pass  # reading handles a missing table; the job/first Generate creates it


def _toggle_row(key: str) -> None:
    rows = st.session_state.ss_rows
    if key in rows:
        rows.remove(key)
    else:
        rows.append(key)


def _toggle_val(key: str) -> None:
    vals = st.session_state.ss_vals
    if key in vals:
        vals.remove(key)
    elif len(vals) < MAX_MEASURES:
        vals.append(key)


def _clear_all() -> None:
    st.session_state.ss_rows = []
    st.session_state.ss_vals = []


# ---------------------------------------------------------------------
# Date range (rendered inside the Key themes header)
# ---------------------------------------------------------------------
def _data_anchor() -> tuple[dt.date, str]:
    try:
        window = _cached_window()
        anchor = window["common_end"]
        note = f"Data is available through {format_date(anchor)} in every subject area with a date dimension."
        if not window["overlap"]:
            note = "Subject areas do not share a common date window; some may show no data for the range you pick."
    except Exception as e:
        anchor = dt.date.today()
        note = f"Could not read the latest data date ({e}); presets are anchored to today."
    return anchor, note


def _current_range(anchor: dt.date, prefix: str = "ss") -> tuple[dt.date, dt.date]:
    """The selected range, read from session state so it is right even before the widgets below render.

    `prefix` keeps Storylines ("ss") and BYOV ("bv") date ranges independent of each other."""
    preset = st.session_state.get(f"{prefix}_preset", PRESETS[0])
    if preset == "Custom":
        d0, d1 = resolve_range(PRESETS[0], anchor)
        return st.session_state.get(f"{prefix}_from", d0), st.session_state.get(f"{prefix}_to", d1)
    return resolve_range(preset, anchor)


def _render_date_controls(anchor: dt.date, note: str, prefix: str = "ss") -> None:
    st.radio("Period", PRESETS + ["Custom"], horizontal=True, key=f"{prefix}_preset", label_visibility="collapsed")
    if st.session_state.get(f"{prefix}_preset") == "Custom":
        default_start, default_end = resolve_range(PRESETS[0], anchor)
        c1, c2 = st.columns(2)
        with c1:
            st.date_input("From", value=default_start, key=f"{prefix}_from")
        with c2:
            st.date_input("To", value=default_end, key=f"{prefix}_to")
    st.caption(note)


# ---------------------------------------------------------------------
# Part 1: themes
# ---------------------------------------------------------------------
def _theme_html_table(evidence: dict) -> str:
    df = pd.DataFrame(evidence["rows"], columns=evidence["columns"])
    return df.to_html(index=False, border=0, classes="i360-evidence")


def _render_theme(theme: dict) -> None:
    if theme.get("error"):
        st.warning(theme.get("headline") or "Insight could not be generated.")
    else:
        bullets = "".join(f'<li style="margin-bottom:5px;">{sanitize_llm_html(b)}</li>' for b in theme.get("bullets", []))
        has_decision = bool(theme.get("decision"))
        # One st.markdown call and zero margins between the two boxes, so they read as a single attached unit.
        green_radius = "4px 4px 0 0" if has_decision else "4px"
        html_block = (
            f'<div class="i360-callout" style="margin-bottom:0; border-radius:{green_radius};">'
            f'<div style="font-size:16px; font-weight:700;">{html.escape(theme["name"].upper())}'
            '<span class="i360-ai-badge">✨ AI-generated</span></div>'
            f'<div style="font-size:14.5px; line-height:1.6; margin-top:6px;">{sanitize_llm_html(theme.get("headline", ""))}</div>'
            + (f'<ul style="font-size:14.5px; line-height:1.6; margin:8px 0 0; padding-left:20px;">{bullets}</ul>' if bullets else "")
            + "</div>"
        )
        if has_decision:
            html_block += (
                '<div class="i360-decision" style="margin:0; border-radius:0 0 4px 4px;">'
                f'<b>Decision to consider:</b> {sanitize_llm_html(theme["decision"])}</div>'
            )
        st.markdown(html_block + '<div style="height:10px;"></div>', unsafe_allow_html=True)
    for note in theme.get("notes", []):
        st.caption(f"ℹ️ {note}")

    if theme.get("evidence"):
        with st.expander("Data behind this theme"):
            for ev in theme["evidence"]:
                st.caption(f"{ev['title']} — {ev['area']}")
                st.markdown(_theme_html_table(ev), unsafe_allow_html=True)


def _select_theme(key: str) -> None:
    st.session_state["ss_theme_key"] = key


def _render_theme_tiles() -> str:
    """4 x 2 grid of white tiles; the selected one is light green. Returns the selected theme's key."""
    selected = st.session_state.get("ss_theme_key", THEMES[0]["key"])
    per_row = 4
    for i in range(0, len(THEMES), per_row):
        cols = st.columns(per_row)
        for col, theme in zip(cols, THEMES[i:i + per_row]):
            with col:
                if theme["key"] == selected:
                    st.markdown(f'<div class="i360-tile-selected">{html.escape(theme["name"])}</div>', unsafe_allow_html=True)
                else:
                    st.markdown('<span class="i360-tile-marker"></span>', unsafe_allow_html=True)
                    st.button(theme["name"], key=f"ss_tile_{theme['key']}", on_click=_select_theme, args=(theme["key"],))
    return selected


def _render_themes(anchor: dt.date, data_note: str, start: dt.date, end: dt.date) -> None:
    head_l, head_r = st.columns([3, 1.6])
    with head_l:
        with st.expander(f"Date range: {format_range(start, end)}", expanded=False):
            _render_date_controls(anchor, data_note, "ss")
    with head_r:
        clicked = st.button("✨ Generate insights", key="ss_generate")

    if start > end:
        st.error("The 'From' date must be on or before the 'To' date.")
        return

    latest = None
    try:
        latest = _cached_latest_run()
    except Exception as e:
        st.caption(f"Could not read the saved run: {e}")
    live = st.session_state.get("ss_live_run")  # fallback only if saving failed
    shown = None
    src = latest or live
    if src:
        shown = {"start": src["start"], "end": src["end"], "themes": src["themes"]}

    st.markdown(
        '<div style="font-size:13px; color:#6E7079; margin:-4px 0 6px;">The insights below are for the date range shown. '
        "To change the date range, click Generate insights.</div>",
        unsafe_allow_html=True,
    )

    if clicked:
        st.warning("Running all 8 themes for the selected dates — this can take a few minutes. Please stay on this "
                   "page (don't click a theme or switch tabs) until it finishes, or the run is cancelled.")
        bar = st.progress(0)
        status = st.empty()

        def _progress(done: int, total: int, name: str) -> None:
            bar.progress(done / total)
            status.caption(f"Working on: {name}" if name else "Saving…")

        themes = run_all_themes(start, end, progress_cb=_progress)
        st.session_state.pop("ss_live_run", None)
        st.session_state.pop("ss_save_error", None)
        try:
            db.ensure_table()
            db.save_run("manual", start, end, f"Selected range ({format_range(start, end)})", themes)
        except Exception as e:
            st.session_state["ss_live_run"] = {"start": start, "end": end, "themes": themes}
            st.session_state["ss_save_error"] = str(e)
        st.cache_data.clear()
        st.rerun()

    if st.session_state.get("ss_save_error"):
        st.warning(f"The insights were generated but could not be saved (they will be lost if the page reloads): "
                   f"{st.session_state['ss_save_error']}")

    if shown and (shown["start"], shown["end"]) != (start, end):
        st.info(f"These insights cover {format_range(shown['start'], shown['end'])}. The date range selected above is "
                f"{format_range(start, end)} — click **Generate insights** to refresh them for the selected dates.")

    selected_key = _render_theme_tiles()
    st.markdown("")

    by_key = {t["key"]: t for t in (shown["themes"] if shown else [])}
    if selected_key in by_key:
        _render_theme(by_key[selected_key])
    else:
        theme_def = next(t for t in THEMES if t["key"] == selected_key)
        st.markdown(
            '<div class="i360-callout">'
            f'<div style="font-size:16px; font-weight:700;">{html.escape(theme_def["name"].upper())}</div>'
            f'<div style="font-size:14.5px; margin-top:6px;">{html.escape(theme_def["question"])}</div>'
            '<div style="font-size:13px; margin-top:6px;">No insight yet for this theme — click "Generate insights".</div>'
            "</div>",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------
# Part 2: pivot builder
# ---------------------------------------------------------------------
def _field_row(label: str, active: bool, reason: str | None, on_click, arg: str, key: str, area: str | None = None) -> None:
    c_name, c_btn = st.columns([3, 1.4])
    with c_name:
        if active:
            st.markdown(f'<span style="font-weight:700; color:#0D9488;">{html.escape(label)}</span>', unsafe_allow_html=True)
        elif reason:
            st.markdown(f'<span style="color:{GREY};">{html.escape(label)}</span>', unsafe_allow_html=True)
        else:
            st.markdown(html.escape(label), unsafe_allow_html=True)
        if reason and not active:
            st.caption(reason)
    with c_btn:
        st.button("Remove" if active else "+ Add", key=key, on_click=on_click, args=(arg,),
                  disabled=bool(reason) and not active)


def _grid(items: list, per_row: int = 3):
    """Yield (item, column) so callers can lay expanders out `per_row` to a row instead of one tall stack."""
    for i in range(0, len(items), per_row):
        cols = st.columns(per_row)
        for item, col in zip(items[i:i + per_row], cols):
            yield item, col


def _render_field_lists() -> None:
    rows, vals = st.session_state.ss_rows, st.session_state.ss_vals
    tab_dims, tab_meas = st.tabs(["Dimensions", "Measures"])

    with tab_dims:
        st.caption("Greyed-out items can't be combined with your current values.")
        groups: dict[str, list[dict]] = {}
        for d in DIMENSIONS:
            groups.setdefault(d["group"], []).append(d)
        for (group, dims), col in _grid(list(groups.items())):
            with col:
                with st.expander(group, expanded=False):
                    for d in dims:
                        reason = dim_disabled_reason(d["key"], rows, vals)
                        _field_row(d["label"], d["key"] in rows, reason, _toggle_row, d["key"], f"ss_d_{d['key']}")

    with tab_meas:
        st.caption(f"Up to {MAX_MEASURES} values, grouped by subject area.")
        areas: dict[str, list[dict]] = {}
        for m in MEASURES:
            areas.setdefault(m["area"], []).append(m)
        for (area, ms), col in _grid(list(areas.items())):
            with col:
                with st.expander(area, expanded=False):
                    for m in ms:
                        reason = measure_disabled_reason(m["key"], rows)
                        if not reason and m["key"] not in vals and len(vals) >= MAX_MEASURES:
                            reason = f"Maximum of {MAX_MEASURES} values reached"
                        _field_row(m["label"], m["key"] in vals, reason, _toggle_val, m["key"], f"ss_m_{m['key']}")


def _render_zone(title: str, keys: list[str], label_of, on_click, prefix: str) -> None:
    st.markdown(f'<div style="font-size:11px; font-weight:700; color:#6E7079; letter-spacing:.5px;">{title}</div>',
                unsafe_allow_html=True)
    if not keys:
        st.caption("Nothing added yet — use “+ Add” in the list on the left.")
        return
    cols = st.columns(max(len(keys), 3))
    for col, key in zip(cols, keys):
        with col:
            st.button(f"✕ {label_of(key)}", key=f"{prefix}{key}", on_click=on_click, args=(key,))


def _measure_chip_label(key: str) -> str:
    m = get_measure(key)
    return m["label"]


def _render_builder(start: dt.date, end: dt.date):
    """Returns the PivotResult currently on screen (or None) for the Ask section."""
    _render_field_lists()  # full-width grids of dimension groups / measure areas, 3 per row
    st.markdown("")

    result = None
    with st.expander("Your table", expanded=True):
        _render_zone("ROWS", st.session_state.ss_rows, lambda k: get_dim(k)["label"], _toggle_row, "ss_rmr_")
        st.markdown("")
        _render_zone("VALUES", st.session_state.ss_vals, _measure_chip_label, _toggle_val, "ss_rmv_")
        if st.session_state.ss_rows or st.session_state.ss_vals:
            st.button("Clear all", key="ss_clear", on_click=_clear_all)

        rows, vals = tuple(st.session_state.ss_rows), tuple(st.session_state.ss_vals)
        if not rows or not vals:
            st.info("Add at least one row and one value to see a table.")
            return None

        try:
            with st.spinner("Querying…"):
                fetched = _cached_pivot(rows, vals, start.isoformat(), end.isoformat())
        except Exception as e:
            st.error("The query failed.")
            with st.expander("Error details"):
                st.code(str(e))
            return None

        if fetched.df.empty:
            st.warning("No data for this combination in the selected date range.")
            for note in fetched.notes:
                st.caption(f"ℹ️ {note}")
            return None

        result = fetched
        info_l, info_r = st.columns([3, 1.4])
        suffix = f" (showing the first {MAX_DISPLAY_ROWS:,})" if len(result.df) > MAX_DISPLAY_ROWS else ""
        with info_l:
            st.caption(f"{len(result.df):,} rows{suffix} · {format_range(start, end)}")
        with info_r:
            data, ext, mime = to_download(result, start, end)
            st.download_button(
                "⬇️ Download to Excel" if ext == "xlsx" else "⬇️ Download (CSV)",
                data=data, file_name=f"inventory360_self_service_{end.isoformat()}.{ext}",
                mime=mime, key="ss_download",
            )
        for note in result.notes:
            st.caption(f"ℹ️ {note}")

        shown_df = result.df.head(MAX_DISPLAY_ROWS)
        formats = {name: (lambda v, k=kind: format_value(v, k)) for name, kind in result.measure_cols}
        st.dataframe(shown_df.style.format(formats), use_container_width=True,
                     height=min(420, 38 * (len(shown_df) + 1) + 3))
    return result


# ---------------------------------------------------------------------
# Part 3: ask the data
# ---------------------------------------------------------------------
_ASK_HEADER = (
    '<div style="font-size:17px; font-weight:700;">Ask a question about the table above'
    '<span class="i360-ai-badge">✨ AI-generated</span></div>'
    '<div style="font-size:13.5px; margin:4px 0 10px;">Your date range, rows and values are sent along with your '
    "question. Ask in plain language, for example “which region is lowest?”. Charts are coming in a later step.</div>"
)


def _render_ask(result, start: dt.date, end: dt.date) -> None:
    sig = (tuple(st.session_state.ss_rows), tuple(st.session_state.ss_vals), start.isoformat(), end.isoformat())
    if st.session_state.ss_qa_sig != sig:
        st.session_state.ss_qa = []  # answers belong to the table they were asked about
        st.session_state.ss_qa_sig = sig

    if result is None:
        st.markdown(
            f'<div class="i360-ask-box">{_ASK_HEADER}'
            '<div style="font-size:13.5px; font-weight:600;">Build a table above first, then ask a question about it.</div></div>',
            unsafe_allow_html=True,
        )
        return

    with st.form("ss_ask_form", clear_on_submit=True):
        st.markdown(_ASK_HEADER, unsafe_allow_html=True)
        c_input, c_button = st.columns([6, 1])
        with c_input:
            question = st.text_input("Question", placeholder="e.g. which category has the lowest fill rate, and by how much?",
                                     label_visibility="collapsed")
        with c_button:
            submitted = st.form_submit_button("Ask")

    if submitted and question.strip():
        try:
            with st.spinner("Thinking…"):
                answer = ask_about_table(question.strip(), result, start, end)
            st.session_state.ss_qa.insert(0, {"q": question.strip(), "a": answer})
        except Exception as e:
            st.error(f"The question could not be answered: {e}")

    for qa in st.session_state.ss_qa:
        st.markdown(
            f'<div class="i360-qa-box"><div class="i360-qa-title">Question</div>'
            f'<div class="i360-qa-content">{html.escape(qa["q"])}</div></div>'
            f'<div class="i360-qa-box answer"><div class="i360-qa-title">Answer</div>'
            f'<div class="i360-qa-content">{sanitize_llm_html(qa["a"])}</div></div>',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------
def render_storylines() -> None:
    st.title("Inventory360 — Storylines")
    _init_state()
    anchor, data_note = _data_anchor()
    start, end = _current_range(anchor, "ss")
    _render_themes(anchor, data_note, start, end)


def render_byov() -> None:
    st.title("Inventory360 — Build Your Own View")
    _init_state()
    anchor, data_note = _data_anchor()
    start, end = _current_range(anchor, "bv")
    with st.expander(f"Date range: {format_range(start, end)}", expanded=False):
        _render_date_controls(anchor, data_note, "bv")
    if start > end:
        st.error("The 'From' date must be on or before the 'To' date.")
        return
    result = _render_builder(start, end)
    st.markdown("")
    _render_ask(result, start, end)
