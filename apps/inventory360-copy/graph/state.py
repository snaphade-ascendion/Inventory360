"""
graph/state.py
================
The shared state object every node reads from and writes to.

messages, genie_results, and validations use the `add` reducer (via
Annotated) so that when multiple nodes append across a single graph run
(e.g. a multi-Genie sequence, or retries), LangGraph accumulates rather
than overwrites. genie_results and validations stay 1:1 by append order —
validate_node appends exactly one ValidationRecord for every
GenieCallRecord genie_call_node appends, rather than mutating a past
record in place (which the `add` reducer doesn't support cleanly).
Everything else is last-write-wins, which is what we want for routing
decisions that get re-evaluated each loop.
"""

import operator
from typing import Annotated, Literal, TypedDict


class GenieCallRecord(TypedDict):
    genie_key: str
    request_sent: str
    result: dict  # the full call_genie() return dict
    attempt_number: int  # 1 for a fresh call, 2+ for retries of the same genie_key
    elapsed_seconds: float
    router_decision: dict  # the {"action","genie_key","genie_request","message"} that triggered this call


class ValidationRecord(TypedDict):
    passed: bool
    reason: str  # empty string when passed


class ConversationState(TypedDict):
    # Full chat history for this session (role/content pairs), used both to
    # display in the UI and to give the router conversation context.
    messages: Annotated[list[dict], operator.add]

    # The current turn's question (set once per user turn, not accumulated).
    user_question: str

    # Router's most recent decision.
    next_action: Literal["CALL_GENIE", "CLARIFY", "DECLINE", "ANSWER_DIRECTLY"] | None
    pending_genie_key: str | None
    pending_genie_request: str | None
    router_message: str | None  # acknowledgement / clarify question / decline text / direct answer

    # Accumulated Genie results for this turn, in call order (one entry per
    # actual API call, including retries — each retry is its own record).
    genie_results: Annotated[list[GenieCallRecord], operator.add]
    # 1:1 with genie_results by append order — validate_node's verdict for
    # the corresponding call.
    validations: Annotated[list[ValidationRecord], operator.add]

    # The decision (action/genie_key/genie_request/message) that triggered
    # the NEXT genie_call_node run — set by router_node on a fresh routing
    # decision, or by validate_node on a retry. Last-write-wins; consumed
    # by genie_call_node into that call's GenieCallRecord for display.
    last_router_decision: dict | None

    # Retry bookkeeping — validate.py increments this, router/genie_call reset it per new Genie.
    retry_count: int
    max_retries: int

    # Final turn status. "in_progress" until a terminal node sets it.
    status: Literal["in_progress", "clarified", "declined", "answered", "error"]
    final_answer: str | None