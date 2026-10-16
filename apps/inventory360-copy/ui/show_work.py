"""
ui/show_work.py
=================
Renders the "Show work" panel in two tiers, from the SAME underlying
genie_results / validations data (graph/state.py) — no duplicate state,
just a rendering choice:

  1. Business-friendly summary (always visible): one line per Genie
     actually used, with a pass/caution icon. No SQL, no genie keys, no
     internal jargon.
  2. Technical details (behind a toggle, off by default): a high-level
     path summary, then per-attempt breakdown — attempt number, elapsed
     time, pass/fail + reason, the router's action/genie_key/message
     decision, result table, and SQL (shown last).

Used both for the live turn (app.py, right after a response streams in)
and when replaying prior turns from session history — same function,
just pass a unique key_prefix each time so Streamlit widget keys don't
collide across messages.
"""

import streamlit as st
from genie.config import GENIE_SPACES


def _genie_display_name(genie_key: str) -> str:
    spec = GENIE_SPACES.get(genie_key)
    return spec["display_name"] if spec else genie_key


def _summarize_by_genie(genie_results: list[dict], validations: list[dict]) -> list[dict]:
    """
    Collapse the (possibly multi-attempt) call log down to one summary
    row per distinct genie_key, in first-used order, using the LAST
    attempt's pass/fail as that genie's overall status for this turn.
    """
    order: list[str] = []
    by_key: dict[str, dict] = {}

    for rec, val in zip(genie_results, validations):
        key = rec["genie_key"]
        if key not in by_key:
            order.append(key)
            by_key[key] = {"attempts": 0, "final_passed": True}
        by_key[key]["attempts"] += 1
        by_key[key]["final_passed"] = val["passed"]  # last one wins

    return [
        {
            "genie_key": key,
            "display_name": _genie_display_name(key),
            "attempts": by_key[key]["attempts"],
            "passed": by_key[key]["final_passed"],
        }
        for key in order
    ]


def render_business_summary(genie_results: list[dict], validations: list[dict]) -> None:
    if not genie_results:
        return
    for row in _summarize_by_genie(genie_results, validations):
        icon = "✅" if row["passed"] else "⚠️"
        retried = f" (retried {row['attempts'] - 1}x)" if row["attempts"] > 1 else ""
        st.markdown(f"{icon} Checked **{row['display_name']}**{retried}")


def _summarize_path(genie_results: list[dict], validations: list[dict]) -> str:
    """
    High-level flow for a technical user: User question -> Genie A (icons
    per attempt) -> Genie B -> Synthesize -> Answer. Consecutive attempts
    of the SAME genie_key collapse into one step, with a ✅/❌ icon per
    attempt so a retry-then-succeed sequence is visible at a glance
    (e.g. "Inventory Visibility (❌✅)").
    """
    steps = []
    for rec, val in zip(genie_results, validations):
        icon = "✅" if val["passed"] else "❌"
        if steps and steps[-1]["genie_key"] == rec["genie_key"]:
            steps[-1]["icons"].append(icon)
        else:
            steps.append({"genie_key": rec["genie_key"], "name": _genie_display_name(rec["genie_key"]), "icons": [icon]})

    parts = ["User question"]
    for s in steps:
        label = f"{s['name']} {s['icons'][0]}" if len(s["icons"]) == 1 else f"{s['name']} ({''.join(s['icons'])})"
        parts.append(label)
    parts.append("Synthesize")
    parts.append("Answer")
    return "  →  ".join(parts)


def render_technical_details(genie_results: list[dict], validations: list[dict], key_prefix: str) -> None:
    if not genie_results:
        return
    show = st.toggle("Show technical details", key=f"{key_prefix}_tech_toggle")
    if not show:
        return

    st.markdown(f"**Path:** {_summarize_path(genie_results, validations)}")
    st.markdown("")

    for i, (rec, val) in enumerate(zip(genie_results, validations)):
        status_label = "Passed" if val["passed"] else f"Failed — {val['reason']}"
        genie_name = _genie_display_name(rec["genie_key"])
        st.markdown(
            f"**Attempt {rec['attempt_number']} — {genie_name}** "
            f"&nbsp;&nbsp;{rec['elapsed_seconds']}s&nbsp;&nbsp;{status_label}"
        )

        decision = rec.get("router_decision") or {}
        st.markdown(
            f"**Router decision** &nbsp; "
            f"Action: {decision.get('action', '')} &nbsp; "
            f"Genie: {decision.get('genie_key', '')}"
        )
        st.markdown(f"Message: {decision.get('message', '')}")

        result = rec["result"]
        for att in result.get("attachments", []):
            if att["type"] == "text" and att.get("content"):
                st.markdown(f"**Genie note:** {att['content']}")

        qd = result.get("query_data")
        if qd and "error" not in qd and qd.get("rows"):
            st.dataframe(qd["rows"])
        elif qd and "error" in qd:
            st.error(qd["error"])

        # SQL shown last, per attempt. No syntax-highlight colors — plain
        # monospace to keep this section from turning into a rainbow.
        for att in result.get("attachments", []):
            if att["type"] == "query":
                st.markdown("**SQL**")
                st.code(att["sql"], language=None)

        st.divider()


def render_show_work(genie_results: list[dict], validations: list[dict], key_prefix: str) -> None:
    """
    Entry point — call this once per message that has Genie results
    attached. key_prefix must be unique per message (e.g. the message's
    index in chat history) to avoid Streamlit widget key collisions when
    multiple turns each have their own "Show technical details" toggle.
    """
    if not genie_results:
        return
    with st.expander("Show work"):
        render_business_summary(genie_results, validations)
        st.markdown("")
        render_technical_details(genie_results, validations, key_prefix)