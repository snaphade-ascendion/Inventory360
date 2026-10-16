"""
page_modules/alerts_page.py
=============================
Smart Alerts (formerly "Alert Setup"; metadata capture, no management UI — no edit/pause/
delete, no "my alerts" list). Two ways in:

  1. Natural language -> "Interpret with AI" -> a confirm card -> accept
     or send to manual editing. Covers metric / condition / threshold /
     frequency, plus Region / Category / Product Class / Exception
     Priority if the sentence mentions them (see alerts/nl_parser.py —
     Facility is manual-only).
  2. Manual entry, in this order:
       a. Metric (single select, the 10 Overview page metrics)
       b. Condition + Threshold
       c. All 5 dimensions, always shown, each its own single-select:
          Region, Facility, Category, Product Class, Exception Priority.
          A dimension the selected metric's view doesn't have is DISABLED
          (greyed out) rather than hidden, with a caption saying why.
          Applicable ones default to "All" and offer live values
          scoped to that metric's own table.
       d. Timeframe (Daily / Weekly / Monthly)

Either path ends with ONE row in dsg.notifications.alert_audit
(alerts/db.py): the alert's own definition columns plus, for each
filtered dimension, the matching column (alerts/constants.py:
DIMENSION_COLUMN) — a dimension left at "All" is simply left out
of the INSERT (NULL). See alerts/constants.py for what the job needs to
assume about threshold scale and the metric_name key format.
"""

import streamlit as st

from auth import user_cache_data
from ui.safe_html import esc
from alerts import db
from alerts.catalog import ALERT_DIMENSIONS, DISPLAY_LABEL, alert_dimensions_status, get_measure
from alerts.constants import CHANNELS, FREQUENCIES, NO_FILTER_LABEL, OPERATORS
from alerts.dimension_values import get_dimension_values
from alerts.nl_parser import parse_alert_nl
from alerts.threshold import format_threshold, parse_threshold
from ui.identity import display_name_from_email, get_current_user_email

_OPERATOR_LABEL = dict(OPERATORS)
_FREQUENCY_LABEL = dict(FREQUENCIES)
_CHANNEL_LABEL = dict(CHANNELS)
_DIM_LABEL = {d["key"]: d["label"] for d in ALERT_DIMENSIONS}
_METRIC_KEYS_BY_LABEL_ORDER = sorted(DISPLAY_LABEL, key=lambda k: DISPLAY_LABEL[k])

# Two-line placeholder shown INSIDE the text box itself (no separate example buttons any more).
NL_PLACEHOLDER = (
    "e.g. Alert me weekly by email if size-curve fill rate in the West goes below 70%\n"
    "Ping me if sellable on-hand units go below 350K"
)


@user_cache_data(ttl=600, show_spinner=False)  # per-user: OBO data access
def _cached_dimension_values(dim_key: str, metric_key: str):
    return get_dimension_values(dim_key, metric_key)


def _init_state() -> None:
    st.session_state.setdefault("al_step", "nl")
    st.session_state.setdefault("al_pending", None)
    st.session_state.setdefault("al_error", None)
    st.session_state.setdefault("al_done_text", None)


def _reset_to_start() -> None:
    st.session_state["al_step"] = "nl"
    st.session_state["al_pending"] = None
    st.session_state["al_error"] = None
    st.session_state["al_done_text"] = None
    st.session_state.pop("al_nl_text", None)


def _summary_html(pending: dict) -> str:
    """Structured 4-line summary — Metric / Timeframe / Filters / Alert Channel — no narrative
    sentence, so there's nothing to misread."""
    m = get_measure(pending["metric_key"])
    is_pct = m["kind"] in ("pct1", "pct2")
    metric_line = (f"{DISPLAY_LABEL[pending['metric_key']]} "
                   f"({_OPERATOR_LABEL[pending['operator']].lower()} {format_threshold(pending['threshold'], is_pct)})")
    dims = pending.get("dimensions") or {}
    filters_line = ", ".join(f"{_DIM_LABEL[k]} = {v}" for k, v in dims.items()) or "None"
    rows = [
        ("Metric", metric_line),
        ("Timeframe", _FREQUENCY_LABEL[pending["frequency"]]),
        ("Filters", filters_line),
        ("Alert Channel", _CHANNEL_LABEL[pending["channel"]]),
    ]
    return "".join(
        f'<div style="margin-bottom:4px;"><b>{esc(label)}:</b> {esc(value)}</div>' for label, value in rows
    )


# ---------------------------------------------------------------------
def _render_nl_step() -> None:
    st.caption("Describe the alert in plain language — the assistant will translate it into a structured rule.")
    st.session_state.setdefault("al_nl_text", "")

    c_input, c_btn = st.columns([1, 1])  # entry box ~50% width, button sits beside it
    with c_input:
        st.text_area("Describe the alert", key="al_nl_text", label_visibility="collapsed", height=90,
                     placeholder=NL_PLACEHOLDER)
    with c_btn:
        st.markdown('<div style="height:6px;"></div>', unsafe_allow_html=True)  # rough vertical alignment with the textarea
        if st.button("✨ Generate Alert", key="al_interpret", type="primary"):
            try:
                pending = parse_alert_nl(st.session_state.get("al_nl_text", ""))
                st.session_state["al_pending"] = pending
                st.session_state["al_error"] = None
                st.session_state["al_step"] = "confirm"
                st.rerun()
            except ValueError as e:
                st.session_state["al_error"] = str(e)

    if st.session_state.get("al_error"):
        st.warning(st.session_state["al_error"])
        st.caption("Voice parsing doesn't cover a Facility filter — for that, use manual entry.")

    st.markdown("")
    if st.button("✏️ Or set it up manually instead", key="al_go_manual", type="secondary"):
        st.session_state["al_pending"] = None
        st.session_state["al_step"] = "manual"
        st.rerun()


def _render_confirm_step() -> None:
    pending = st.session_state["al_pending"]
    pending.setdefault("channel", "email")

    c_ch, _ = st.columns([1, 2])
    with c_ch:
        ch_keys = [k for k, _ in CHANNELS]
        pending["channel"] = st.selectbox("Alert Channel", ch_keys, index=ch_keys.index(pending["channel"]),
                                          format_func=lambda k: _CHANNEL_LABEL[k], key="al_confirm_channel")

    st.markdown("**Here's what I understood** ✨ *AI-generated*")
    st.markdown(f'<div class="i360-callout">{_summary_html(pending)}</div>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("✅ Confirm & set alert", key="al_confirm", type="primary", use_container_width=True):
            _save_alert(pending)
    with c2:
        if st.button("✏️ Not quite — edit manually", key="al_edit_manual", use_container_width=True):
            st.session_state["al_step"] = "manual"
            st.rerun()


def _render_manual_step() -> None:
    pending = st.session_state.get("al_pending") or {}
    st.caption("Set the alert manually.")

    # a. Metric
    default_metric = pending.get("metric_key", _METRIC_KEYS_BY_LABEL_ORDER[0])
    metric_key = st.selectbox(
        "Metric", _METRIC_KEYS_BY_LABEL_ORDER,
        index=_METRIC_KEYS_BY_LABEL_ORDER.index(default_metric) if default_metric in _METRIC_KEYS_BY_LABEL_ORDER else 0,
        format_func=lambda k: DISPLAY_LABEL[k], key="al_m_metric",
    )
    m = get_measure(metric_key)
    is_pct = m["kind"] in ("pct1", "pct2")

    # b. Condition + Threshold + Timeframe + Alert Channel
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        op_keys = [k for k, _ in OPERATORS]
        operator = st.selectbox("Condition", op_keys, index=op_keys.index(pending.get("operator", "below")),
                                format_func=lambda k: _OPERATOR_LABEL[k], key="al_m_operator")
    with c2:
        default_threshold = format_threshold(pending["threshold"], is_pct) if pending.get("threshold") is not None else ("70%" if is_pct else "")
        threshold_raw = st.text_input("Threshold", value=default_threshold, key="al_m_threshold",
                                      placeholder="e.g. 70%" if is_pct else "e.g. 350K")
    with c3:
        freq_keys = [k for k, _ in FREQUENCIES]
        frequency = st.selectbox("Timeframe", freq_keys, index=freq_keys.index(pending.get("frequency", "weekly")),
                                 format_func=lambda k: _FREQUENCY_LABEL[k], key="al_m_frequency")
    with c4:
        ch_keys = [k for k, _ in CHANNELS]
        channel = st.selectbox("Alert Channel", ch_keys, index=ch_keys.index(pending.get("channel", "email")),
                               format_func=lambda k: _CHANNEL_LABEL[k], key="al_m_channel")

    # c. All 5 dimensions, always shown — disabled when not applicable to this metric.
    # Prior selections came from a (possibly different) metric, so they're only reused as the
    # default when the metric hasn't changed since; each widget is keyed by metric_key too, which
    # gives every metric a fresh, valid set of choices rather than carrying over a stale one.
    status = alert_dimensions_status(metric_key)
    prior_dims = pending.get("dimensions") or {} if pending.get("metric_key") == metric_key else {}
    dimension_filters: dict[str, str] = {}
    dim_cols = st.columns(len(ALERT_DIMENSIONS))
    for col, d in zip(dim_cols, ALERT_DIMENSIONS):
        dim_key = d["key"]
        with col:
            applicable = status.get(dim_key, False)
            if not applicable:
                st.selectbox(d["label"], [NO_FILTER_LABEL], disabled=True, key=f"al_m_dim_{metric_key}_{dim_key}")
                st.caption(f"Not available for {DISPLAY_LABEL[metric_key]}")
                continue
            values = _cached_dimension_values(dim_key, metric_key)
            options = [NO_FILTER_LABEL] + values
            default_value = prior_dims.get(dim_key, NO_FILTER_LABEL)
            choice = st.selectbox(d["label"], options, index=options.index(default_value) if default_value in options else 0,
                                  key=f"al_m_dim_{metric_key}_{dim_key}")
            if choice != NO_FILTER_LABEL:
                dimension_filters[dim_key] = choice

    if st.button("✅ Set alert", key="al_confirm_manual", type="primary"):
        try:
            threshold = parse_threshold(threshold_raw)
        except ValueError as e:
            st.error(str(e))
            return
        manual_pending = {
            "metric_key": metric_key, "operator": operator, "threshold": threshold,
            "frequency": frequency, "channel": channel, "dimensions": dimension_filters,
        }
        _save_alert(manual_pending)


def _save_alert(pending: dict) -> None:
    email = get_current_user_email()
    try:
        db.insert_alert(
            metric_label=DISPLAY_LABEL[pending["metric_key"]], metric_key=pending["metric_key"],
            operator=pending["operator"], threshold_value=pending["threshold"], frequency=pending["frequency"],
            channel=pending["channel"], dimension_filters=pending.get("dimensions") or {},
            user_name=display_name_from_email(email), user_email=email,
        )
        st.session_state["al_done_text"] = _summary_html(pending)
        st.session_state["al_step"] = "done"
        st.rerun()
    except Exception as e:
        st.error(f"The alert could not be saved: {e}")


def _render_done_step() -> None:
    st.markdown(
        f'<div class="i360-callout"><b>ALERT SET</b><br><br>{st.session_state["al_done_text"]}</div>',
        unsafe_allow_html=True,
    )
    st.caption("This only saves the alert's definition — the check itself runs on the schedule your Databricks job uses.")
    st.button("Set another alert", key="al_another", on_click=_reset_to_start)


# ---------------------------------------------------------------------
def render() -> None:
    st.title("Inventory360 — Smart Alerts")
    _init_state()

    st.markdown("🔔 **Set an alert**")
    step = st.session_state["al_step"]
    if step == "nl":
        _render_nl_step()
    elif step == "confirm":
        _render_confirm_step()
    elif step == "manual":
        _render_manual_step()
    elif step == "done":
        _render_done_step()
