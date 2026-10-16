"""
graph/nodes/router.py
======================
Decides the next action: call a Genie, ask for clarification, decline
gracefully, or answer directly from the glossary.

This node is re-entered after each Genie result too (via validate.py's
NEEDS_ANOTHER_GENIE path), so it always looks at the full accumulated
genie_results in state, not just the original question in isolation.
"""

from genie.config import GENIE_SPACES, scope_topics_sentence
from llm_client import ask_llm_json
from graph.state import ConversationState
from prompts.router_prompt import build_router_prompt


def _format_prior_results(state: ConversationState) -> str:
    if not state.get("genie_results"):
        return ""
    parts = ["\n## Genie results gathered so far this turn:\n"]
    for rec in state["genie_results"]:
        parts.append(f"- Genie '{rec['genie_key']}' was asked: {rec['request_sent']!r}")
        result = rec["result"]
        if result.get("status") == "success" and result.get("query_data"):
            qd = result["query_data"]
            if "error" not in qd:
                parts.append(f"  Returned columns: {qd['columns']}, {qd['total_rows']} row(s).")
                for row in qd["rows"][:5]:
                    parts.append(f"    {row}")
        else:
            parts.append(f"  Status: {result.get('status')}, error: {result.get('error')}")
    return "\n".join(parts)


def router_node(state: ConversationState) -> dict:
    system_prompt = build_router_prompt()
    prior_results_text = _format_prior_results(state)

    messages = [{"role": "system", "content": system_prompt}]
    # Include recent conversation history for context (Genies are stateless,
    # but the router needs to remember what's already been asked/answered
    # this session).
    messages.extend(state.get("messages", [])[-10:])
    user_turn = state["user_question"]
    if prior_results_text:
        user_turn += f"\n\n{prior_results_text}\n\nDecide the next single action."
    messages.append({"role": "user", "content": user_turn})

    try:
        decision = ask_llm_json(messages, call_site="router")
    except ValueError:
        # Router produced malformed JSON — fail safe to a clarifying question
        # rather than guessing an action or crashing the graph.
        return {
            "next_action": "CLARIFY",
            "pending_genie_key": None,
            "pending_genie_request": None,
            "router_message": (
                f"Sorry, that's not in my knowledge base. I answer questions related to "
                f"{scope_topics_sentence()}."
            ),
        }

    action = decision.get("action")
    genie_key = decision.get("genie_key")
    genie_request = decision.get("genie_request")
    message = decision.get("message", "")

    # Validate the LLM's choices against what's actually configured, rather
    # than trusting the model output blindly.
    if action == "CALL_GENIE" and genie_key not in GENIE_SPACES:
        return {
            "next_action": "CLARIFY",
            "pending_genie_key": None,
            "pending_genie_request": None,
            "router_message": (
                f"Sorry, that's not in my knowledge base. I answer questions related to "
                f"{scope_topics_sentence()}."
            ),
        }

    if action not in ("CALL_GENIE", "CLARIFY", "DECLINE", "ANSWER_DIRECTLY", "SYNTHESIZE"):
        action = "CLARIFY"
        message = message or "Could you clarify your question?"

    return {
        "next_action": action,
        "pending_genie_key": genie_key if action == "CALL_GENIE" else None,
        "pending_genie_request": genie_request if action == "CALL_GENIE" else None,
        "router_message": message,
        "last_router_decision": (
            {"action": action, "genie_key": genie_key, "genie_request": genie_request, "message": message}
            if action == "CALL_GENIE" else None
        ),
    }