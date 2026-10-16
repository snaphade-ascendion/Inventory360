"""
graph/nodes/synthesize.py
============================
Terminal node for this turn: writes the final answer from all Genie
results gathered so far (one or more), using the synthesis prompt's
verification checklist and plausibility anchors.
"""

from genie.client import format_genie_response
from llm_client import ask_llm
from graph.state import ConversationState
from prompts.synthesis_prompt import build_synthesis_prompt


def _format_all_results(state: ConversationState) -> str:
    parts = []
    for rec in state.get("genie_results", []):
        parts.append(f"## Genie: {rec['genie_key']}")
        parts.append(f"Request sent: {rec['request_sent']}")
        parts.append(format_genie_response(rec["result"]))
        parts.append("")
    return "\n".join(parts) if parts else "(No Genie results were gathered this turn.)"


def synthesize_node(state: ConversationState) -> dict:
    system_prompt = build_synthesis_prompt()
    results_text = _format_all_results(state)
    caveat = state.get("router_message", "")  # set by validate.py on the give-up path

    user_content = f"""User's question: {state['user_question']}

{results_text}
"""
    if caveat:
        user_content += f"\nNote to incorporate: {caveat}\n"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    answer = ask_llm(messages, call_site="synthesis")

    return {
        "status": "answered",
        "final_answer": answer,
        "messages": [{"role": "assistant", "content": answer}],
    }
