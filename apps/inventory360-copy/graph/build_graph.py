"""
graph/build_graph.py
======================
Wires the state graph:

                    ┌─────────┐
        ┌──────────►│ router  │◄────────────┐
        │           └────┬────┘             │
        │      ┌─────────┼──────────┐       │ (ROUTER: need
        │      ▼         ▼          ▼        │  another Genie)
        │  clarify   decline  direct_answer  │
        │    END       END        END        │
        │                                    │
        │  CALL_GENIE                 SYNTHESIZE
        │      │                             │
        │      ▼                             ▼
        │  genie_call ──────────────► synthesize
        │      │                          END
        │      ▼
        │  validate
        │      │
        └──────┼─── CALL_GENIE (retry, same genie)
               └─── SYNTHESIZE (retries exhausted, give-up-with-caveat path)

validate's "ROUTER" outcome loops back to router_node, which re-evaluates
with the accumulated genie_results now visible and decides CALL_GENIE
(another Genie needed), SYNTHESIZE (enough data gathered), CLARIFY, or
DECLINE.
"""

from langgraph.graph import StateGraph, END

from graph.state import ConversationState
from graph.nodes.router import router_node
from graph.nodes.genie_call import genie_call_node
from graph.nodes.validate import validate_node
from graph.nodes.clarify import clarify_node
from graph.nodes.decline import decline_node
from graph.nodes.direct_answer import direct_answer_node
from graph.nodes.synthesize import synthesize_node


def _route_after_router(state: ConversationState) -> str:
    return {
        "CALL_GENIE": "genie_call",
        "CLARIFY": "clarify",
        "DECLINE": "decline",
        "ANSWER_DIRECTLY": "direct_answer",
        "SYNTHESIZE": "synthesize",
    }[state["next_action"]]


def _route_after_validate(state: ConversationState) -> str:
    # validate_node sets next_action to either "CALL_GENIE" (retry the same
    # genie), "ROUTER" (loop back for a fresh routing decision with the new
    # result visible), or "SYNTHESIZE" (retries exhausted, give up gracefully).
    return {
        "CALL_GENIE": "genie_call",
        "ROUTER": "router",
        "SYNTHESIZE": "synthesize",
    }[state["next_action"]]


def build_graph():
    graph = StateGraph(ConversationState)

    graph.add_node("router", router_node)
    graph.add_node("genie_call", genie_call_node)
    graph.add_node("validate", validate_node)
    graph.add_node("clarify", clarify_node)
    graph.add_node("decline", decline_node)
    graph.add_node("direct_answer", direct_answer_node)
    graph.add_node("synthesize", synthesize_node)

    graph.set_entry_point("router")

    graph.add_conditional_edges(
        "router",
        _route_after_router,
        {
            "genie_call": "genie_call",
            "clarify": "clarify",
            "decline": "decline",
            "direct_answer": "direct_answer",
            "synthesize": "synthesize",
        },
    )
    graph.add_edge("genie_call", "validate")
    graph.add_conditional_edges(
        "validate",
        _route_after_validate,
        {
            "genie_call": "genie_call",
            "router": "router",
            "synthesize": "synthesize",
        },
    )

    graph.add_edge("clarify", END)
    graph.add_edge("decline", END)
    graph.add_edge("direct_answer", END)
    graph.add_edge("synthesize", END)

    return graph.compile()


# Module-level compiled graph — build once, reuse across Streamlit reruns.
_compiled_graph = None


def get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


def _build_initial_state(user_question: str, prior_messages: list[dict] | None) -> ConversationState:
    return {
        "messages": prior_messages or [],
        "user_question": user_question,
        "next_action": None,
        "pending_genie_key": None,
        "pending_genie_request": None,
        "router_message": None,
        "genie_results": [],
        "validations": [],
        "last_router_decision": None,
        "retry_count": 0,
        "max_retries": 3,
        "status": "in_progress",
        "final_answer": None,
    }


def run_turn(user_question: str, prior_messages: list[dict] | None = None) -> dict:
    """
    Entry point for app.py: runs one full turn (potentially multiple
    Genie calls / retries internally) and returns the final state.

    Parameters
    ----------
    user_question : str
        The new question from the user.
    prior_messages : list[dict], optional
        Conversation history (role/content pairs) from earlier turns in
        this session, for router context.

    Returns
    -------
    dict
        The final graph state — use state["final_answer"] for display,
        state["genie_results"] for an expandable "show work" panel,
        state["status"] to distinguish clarified/declined/answered.
    """
    graph = get_graph()
    initial_state = _build_initial_state(user_question, prior_messages)
    final_state = graph.invoke(initial_state)
    return final_state


def stream_turn(user_question: str, prior_messages: list[dict] | None = None):
    """
    Generator version of run_turn(), for live progress UI (e.g. a
    st.status() box in app.py that shows a friendly message per node as
    the graph actually executes — not a decorative fake timer).

    Yields
    ------
    ("node", node_name: str)
        Once per node as it completes, in execution order. A multi-Genie
        or retry turn will yield "router" / "genie_call" / "validate"
        more than once — callers can track visit counts if they want to
        distinguish e.g. the first router call from a later one.
    ("done", final_state: dict)
        Exactly once, at the end — the authoritative final state (taken
        from LangGraph's "values" stream, so it's the real merged state,
        not something we've hand-reconstructed from partial updates).
    """
    graph = get_graph()
    initial_state = _build_initial_state(user_question, prior_messages)

    final_state = None
    for mode, chunk in graph.stream(initial_state, stream_mode=["updates", "values"]):
        if mode == "updates":
            for node_name in chunk.keys():
                yield ("node", node_name)
        elif mode == "values":
            final_state = chunk
    yield ("done", final_state)