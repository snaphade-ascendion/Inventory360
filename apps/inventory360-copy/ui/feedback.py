"""
ui/feedback.py
================
👍 Accurate / 👎 Not quite under each answer on the Ask Inventory360 page (mockup behaviour).

  * 👍 Accurate            -> saves a 'Pass'.
  * 👎 Not quite           -> opens the reason list (testing.constants.FAIL_REASONS, the SAME options the
                             AI Accuracy page's human review uses); clicking a reason saves a 'Fail' with it.
  * A rating can be changed afterwards: it updates the same test_results row (no duplicates).

Every rating is one row in dsg.inventory360.test_results under a rolling test_runs row with
run_type = 'user' (one per app version), reviewed_by = the signed-in user's email. It is counted in the
human-accuracy numbers on the AI Accuracy page together with bulk + repeat testing; benchmark runs are not.

Applies to every assistant answer, including out-of-scope / clarification / error replies (by request).

State (all in st.session_state, keyed by the assistant message's index in chat_history):
  turn_meta[idx]   : what to store if the user rates it (question, answer, status, elapsed, genie results)
  fb_ratings[idx]  : {"result_id", "verdict", "reason"} once rated
  fb_open          : indexes whose reason list is showing
  fb_changing      : indexes where the user chose to change an existing rating
  fb_error[idx]    : last save error, shown under the buttons
"""

import json

import streamlit as st

from testing import db
from testing.constants import APP_VERSION_DEFAULT, FAIL_REASONS
from testing.runner import _genie_keys_used, _sanitize_for_storage  # same storage shape the testing runs use
from ui.identity import get_current_user_email


def init_state() -> None:
    st.session_state.setdefault("turn_meta", {})
    st.session_state.setdefault("fb_ratings", {})
    st.session_state.setdefault("fb_open", set())
    st.session_state.setdefault("fb_changing", set())
    st.session_state.setdefault("fb_error", {})


def _user_run_id() -> str:
    key = f"fb_user_run_{APP_VERSION_DEFAULT}"
    if key not in st.session_state:
        st.session_state[key] = db.get_or_create_user_run(APP_VERSION_DEFAULT)
    return st.session_state[key]


def _save(idx: int, verdict: str, reason: str | None) -> None:
    ss = st.session_state
    meta = ss["turn_meta"][idx]
    email = get_current_user_email()
    try:
        existing = ss["fb_ratings"].get(idx)
        if existing:
            db.update_human_review(existing["result_id"], verdict, reason, reviewed_by=email)
            result_id = existing["result_id"]
        else:
            genie_results = meta.get("genie_results", [])
            result_id = db.record_user_feedback(
                run_id=_user_run_id(),
                question_text=meta["question"],
                answer_text=meta["answer"],
                genie_keys_used=_genie_keys_used(genie_results),
                elapsed_seconds=meta.get("elapsed"),
                status=meta.get("status", "unknown"),
                genie_results_json=json.dumps(_sanitize_for_storage(genie_results, meta.get("validations", [])), default=str),
                verdict=verdict, reason=reason, reviewed_by=email,
            )
        ss["fb_ratings"][idx] = {"result_id": result_id, "verdict": verdict, "reason": reason}
        ss["fb_open"].discard(idx)
        ss["fb_changing"].discard(idx)
        ss["fb_error"].pop(idx, None)
    except Exception as e:  # a failed save must never break the chat
        ss["fb_error"][idx] = str(e)


def _thumbs_up(idx: int) -> None:
    _save(idx, "Pass", None)


def _not_quite(idx: int) -> None:
    st.session_state["fb_open"].add(idx)


def _pick_reason(idx: int, reason: str) -> None:
    _save(idx, "Fail", reason)


def _cancel(idx: int) -> None:
    st.session_state["fb_open"].discard(idx)
    st.session_state["fb_changing"].discard(idx)


def _change(idx: int) -> None:
    st.session_state["fb_changing"].add(idx)


def render_feedback(idx: int) -> None:
    ss = st.session_state
    if idx not in ss["turn_meta"]:
        return
    rating = ss["fb_ratings"].get(idx)

    if rating and idx not in ss["fb_changing"]:
        msg = "👍 You marked this answer as accurate." if rating["verdict"] == "Pass" else \
              f"👎 You marked this answer as not quite — {rating['reason']}."
        c_msg, c_btn = st.columns([6, 1.3])
        with c_msg:
            st.caption(msg)
        with c_btn:
            st.button("Change", key=f"fb_change_{idx}", on_click=_change, args=(idx,))
    else:
        c_up, c_down, _ = st.columns([1.3, 1.3, 6])
        with c_up:
            st.button("👍 Accurate", key=f"fb_up_{idx}", on_click=_thumbs_up, args=(idx,))
        with c_down:
            st.button("👎 Not quite", key=f"fb_down_{idx}", on_click=_not_quite, args=(idx,))

        if idx in ss["fb_open"]:
            st.caption("What was wrong?")
            cols = st.columns(len(FAIL_REASONS) + 1)
            for col, reason in zip(cols, FAIL_REASONS):
                with col:
                    st.button(reason, key=f"fb_reason_{idx}_{reason}", on_click=_pick_reason, args=(idx, reason))
            with cols[-1]:
                st.button("Cancel", key=f"fb_cancel_{idx}", on_click=_cancel, args=(idx,))
        elif idx in ss["fb_changing"]:
            st.button("Cancel", key=f"fb_cancel_{idx}", on_click=_cancel, args=(idx,))

    if idx in ss["fb_error"]:
        st.warning(f"Your feedback could not be saved: {ss['fb_error'][idx]}")
