"""
page_modules/chat_page.py
===========================
Conversation Analytics tab. Identical logic to the original app.py, minus
st.set_page_config / inject_custom_css / the top-level st.title — those
now happen once in the shared app.py entrypoint (Overview / Chat /
Testing all share one page config, per Streamlit's one-call rule).
"""

import time

import streamlit as st

from ui.safe_html import esc, sanitize_llm_html

from graph.build_graph import stream_turn
from testing import db as testing_db
from ui.feedback import init_state as init_feedback_state, render_feedback
from ui.identity import get_current_user_email
from ui.show_work import render_show_work
from ui.progress import label_for_node

st.title("Inventory360 — Conversation Analytics")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []  # list of {"role": ..., "content": ...}
init_feedback_state()
if "turn_results" not in st.session_state:
    # message_index (in chat_history) -> {"genie_results": [...], "validations": [...]}
    st.session_state.turn_results = {}


@st.cache_data(ttl=300, show_spinner=False)
def _cached_top_questions():
    return testing_db.top_questions(limit=5)


def _ask_popular(question: str) -> None:
    st.session_state["pending_question"] = question


def _popular_question_list() -> list[str]:
    """Real asked-question data once it exists (logged via testing_db.log_asked_question,
    every question — not just rated ones); falls back to the curated SAMPLE_QUESTIONS
    until the table has enough history to be meaningful."""
    try:
        rows = _cached_top_questions()
    except Exception as e:
        st.session_state["ov_popq_error"] = str(e)  # kept for debugging, never shown to the user
        rows = []
    if rows:
        return [r["question_text"] for r in rows]
    return SAMPLE_QUESTIONS


def render_popular_questions() -> None:
    """Small, clickable 'popular questions' rail — only shown before the first question,
    so it doesn't compete with an active conversation. Replaces the old plain-text
    'Try asking — ...' hint: same questions, but now clickable."""
    questions = _popular_question_list()
    if not questions:
        return

    st.markdown(
        '<div style="font-size:11px; font-weight:700; color:#9AA3B2; letter-spacing:.4px; margin:0 0 6px 2px;">'
        "POPULAR QUESTIONS</div>",
        unsafe_allow_html=True,
    )
    # One per row rather than equal-width columns — these are full sentences, and cramming
    # several into narrow side-by-side columns wraps badly (same issue the Share picker had).
    # st.button sizes to its text by default (no use_container_width), so this still reads as
    # a stack of small pills, not a stack of full-width bars.
    for question in questions:
        st.markdown('<span class="i360-popq-marker"></span>', unsafe_allow_html=True)
        st.button(question, key=f"popq_{hash(question)}", on_click=_ask_popular, args=(question,))


def render_message(role: str, content: str) -> None:
    """
    Both Question and Answer render as titled white containers,
    left-aligned. Answer is indented and keeps a left accent border so
    it reads clearly as the response. No avatars, no chat bubbles.
    """
    css_class = "question" if role == "user" else "answer"
    title = "Question" if role == "user" else "Answer"
    # User text is fully escaped; LLM answers keep only the allowlisted formatting tags.
    content = esc(content) if role == "user" else sanitize_llm_html(content)
    st.markdown(
        f'<div class="i360-qa-box {css_class}">'
        f'<div class="i360-qa-title">{title}</div>'
        f'<div class="i360-qa-content">{content}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


SAMPLE_QUESTIONS = [
    "Do categories with a high aged inventory share also have low size-curve fill?",
    "What is our store inventory accuracy rate in 2026?",
    "Compare size-curve fill rate and on-time ship rate for Running footwear?",
    "Who is the POC for store inventory accuracy?",
]

# Only shown before the first question is asked — stays out of the way
# once a real conversation is underway. Deliberately plain (no card,
# no border, muted color) so it reads as a hint, not a feature.
if not st.session_state.chat_history:
    render_popular_questions()

# Render prior turns
for i, msg in enumerate(st.session_state.chat_history):
    render_message(msg["role"], msg["content"])
    if i in st.session_state.turn_results:
        render_show_work(
            st.session_state.turn_results[i]["genie_results"],
            st.session_state.turn_results[i]["validations"],
            key_prefix=f"hist_{i}",
        )
    if msg["role"] == "assistant":
        render_feedback(i)
        st.divider()

user_question = st.chat_input("Ask about inventory, orders, allocation, store ops, or merchandising…")
user_question = user_question or st.session_state.pop("pending_question", None)

if user_question:
    try:
        testing_db.log_asked_question(user_question, asked_by=get_current_user_email())
    except Exception as e:
        st.session_state["ov_popq_error"] = str(e)  # logging must never block the actual chat turn
    _cached_top_questions.clear()  # so a brand-new question can surface in the rail right away

    st.session_state.chat_history.append({"role": "user", "content": user_question})
    render_message("user", user_question)

    turn_started = time.time()
    with st.status("Working on it…", expanded=False) as status_box:
        router_visits = 0
        final_state = None
        for kind, payload in stream_turn(
            user_question=user_question,
            prior_messages=st.session_state.chat_history[:-1],
        ):
            if kind == "node":
                if payload == "router":
                    router_visits += 1
                status_box.update(label=label_for_node(payload, router_visits), state="running")
            elif kind == "done":
                final_state = payload
        status_box.update(label="Done", state="complete")
    final_state = final_state or {}
    answer = final_state.get("final_answer") or "Sorry, something went wrong — please try again."
    render_message("assistant", answer)

    genie_results = final_state.get("genie_results", [])
    validations = final_state.get("validations", [])
    msg_index = len(st.session_state.chat_history)
    render_show_work(genie_results, validations, key_prefix=f"live_{msg_index}")

    # Everything needed to store a rating for this answer (see ui/feedback.py) — kept for EVERY answer,
    # not only ones that returned data.
    st.session_state["turn_meta"][msg_index] = {
        "question": user_question,
        "answer": answer,
        "status": final_state.get("status", "unknown"),
        "elapsed": round(time.time() - turn_started, 2),
        "genie_results": genie_results,
        "validations": validations,
    }
    render_feedback(msg_index)
    st.divider()

    st.session_state.chat_history.append({"role": "assistant", "content": answer})
    if genie_results:
        st.session_state.turn_results[msg_index] = {
            "genie_results": genie_results,
            "validations": validations,
        }
