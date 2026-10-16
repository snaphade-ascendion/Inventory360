"""
graph/nodes/decline.py
========================
Terminal node for this turn: the question is out of scope for all
configured Genies. Declines gracefully rather than forcing a bad-fit
Genie call or hallucinating an answer.
"""

from genie.config import scope_topics_sentence
from graph.state import ConversationState


def decline_node(state: ConversationState) -> dict:
    message = state.get("router_message") or (
        f"Sorry, that's not in my knowledge base. I answer questions related to "
        f"{scope_topics_sentence()}."
    )
    return {
        "status": "declined",
        "final_answer": message,
        "messages": [{"role": "assistant", "content": message}],
    }