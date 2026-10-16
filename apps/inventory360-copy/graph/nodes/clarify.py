"""
graph/nodes/clarify.py
========================
Terminal node for this turn: the router determined the question is
ambiguous and there's no safe default. Surfaces the clarifying question
to the user and ends the graph run — no Genie was called.
"""

from graph.state import ConversationState


def clarify_node(state: ConversationState) -> dict:
    message = state.get("router_message") or "Could you clarify your question?"
    return {
        "status": "clarified",
        "final_answer": message,
        "messages": [{"role": "assistant", "content": message}],
    }
