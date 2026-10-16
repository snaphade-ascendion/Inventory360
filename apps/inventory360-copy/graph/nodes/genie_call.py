"""
graph/nodes/genie_call.py
===========================
Invokes whichever Genie the router (or validate, on retry) chose.
Purely mechanical — no LLM call here, just call_genie() and append the
result (with timing and attempt-number metadata) to state.
"""

import time
from genie.client import call_genie
from graph.state import ConversationState


def genie_call_node(state: ConversationState) -> dict:
    genie_key = state["pending_genie_key"]
    request = state["pending_genie_request"]
    attempt_number = state.get("retry_count", 0) + 1  # 1 for a fresh call, 2+ for retries
    router_decision = state.get("last_router_decision") or {
        "action": "CALL_GENIE", "genie_key": genie_key, "genie_request": request, "message": "(no router decision captured)"
    }

    start = time.time()
    result = call_genie(genie_key=genie_key, question=request)
    elapsed = round(time.time() - start, 2)

    return {
        "genie_results": [
            {
                "genie_key": genie_key,
                "request_sent": request,
                "result": result,
                "attempt_number": attempt_number,
                "elapsed_seconds": elapsed,
                "router_decision": router_decision,
            }
        ],
    }