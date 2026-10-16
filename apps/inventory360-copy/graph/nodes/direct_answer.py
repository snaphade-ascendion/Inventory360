"""
graph/nodes/direct_answer.py
==============================
Terminal node for this turn: the router determined the question can be
answered from the glossary alone (e.g. "what does OTIF mean?") with no
Genie call needed.
"""

from graph.state import ConversationState


def direct_answer_node(state: ConversationState) -> dict:
    message = state.get("router_message") or "I don't have a direct answer for that."
    return {
        "status": "answered",
        "final_answer": message,
        "messages": [{"role": "assistant", "content": message}],
    }
