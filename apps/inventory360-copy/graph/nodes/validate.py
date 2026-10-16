"""
graph/nodes/validate.py
=========================
Runs after every genie_call_node. Fully rule-based, no LLM call — keeps
this step fast and cheap.

Two checks:
1. Structural: did the call succeed at all, did it return rows.
2. Scale sanity: for columns that look like a percentage (name contains
   "pct"/"rate") or a count/quantity (name contains "count"/"units"/"qty"),
   flag values clearly outside a plausible range. This can't be a precise
   per-metric check — Genie generates its own SQL column aliases, so we
   can't reliably map a returned column back to a specific named measure.
   It catches real scale bugs (e.g. a percentage column accidentally
   returning 5419 instead of 54.19) without needing semantic judgment.

Returns one of: PROCEED (loop back to router), RETRY (same Genie, refined
request), or GIVE_UP (retries exhausted — go to synthesize with a caveat).
"""

from graph.state import ConversationState

# Generic scale bounds by column-name pattern. Deliberately loose — this is
# a guard against obvious scale bugs, not a precise per-metric plausibility
# check (see module docstring for why that's not reliably possible here).
PCT_COLUMN_HINTS = ("pct", "rate", "percent")
PCT_PLAUSIBLE_RANGE = (-100.0, 100.0)

COUNT_COLUMN_HINTS = ("count", "units", "qty", "quantity")


def _rule_based_check(result: dict) -> tuple[bool, str]:
    """Returns (passed, reason_if_failed). Structural checks only."""
    if result.get("status") != "success":
        return False, f"Genie call did not succeed (status: {result.get('status')}, error: {result.get('error')})"
    qd = result.get("query_data")
    if qd is None:
        return False, "Genie returned no query data (likely answered without running SQL, or SQL failed silently)."
    if "error" in qd:
        return False, f"Could not extract query result: {qd['error']}"
    if qd.get("total_rows", 0) == 0:
        return False, "Query returned zero rows."
    return True, ""


def _scale_sanity_check(qd: dict) -> tuple[bool, str]:
    """Returns (passed, reason_if_suspicious). Generic scale check only."""
    columns = qd.get("columns", [])
    rows = qd.get("rows", [])
    issues = []

    for col in columns:
        col_lower = col.lower()
        is_pct_col = any(hint in col_lower for hint in PCT_COLUMN_HINTS)
        is_count_col = any(hint in col_lower for hint in COUNT_COLUMN_HINTS)

        for row in rows:
            val = row.get(col)
            if val is None:
                continue
            try:
                num = float(val)
            except (TypeError, ValueError):
                continue  # not a numeric column, skip

            if is_pct_col:
                lo, hi = PCT_PLAUSIBLE_RANGE
                if not (lo <= num <= hi):
                    issues.append(f"Column '{col}' has value {num}, outside plausible percentage range ({lo} to {hi}) — possible scale error.")
                    break  # one flagged issue per column is enough
            elif is_count_col:
                if num < 0:
                    issues.append(f"Column '{col}' has negative value {num} — counts/quantities shouldn't be negative.")
                    break

    if issues:
        return False, "; ".join(issues)
    return True, ""


def validate_node(state: ConversationState) -> dict:
    latest = state["genie_results"][-1]
    result = latest["result"]
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)

    passed, reason = _rule_based_check(result)

    if passed:
        # Structural check passed — run the scale sanity check too.
        scale_passed, scale_reason = _scale_sanity_check(result["query_data"])
        if not scale_passed:
            passed, reason = False, scale_reason

    if not passed:
        if retry_count < max_retries:
            retry_request = (
                f"{latest['request_sent']}\n\n"
                f"(Retry note: the previous attempt looked wrong — {reason}. "
                f"Please adjust the query accordingly.)"
            )
            return {
                "validations": [{"passed": False, "reason": reason}],
                "retry_count": retry_count + 1,
                "next_action": "CALL_GENIE",
                "pending_genie_key": latest["genie_key"],
                "pending_genie_request": retry_request,
                "last_router_decision": {
                    "action": "RETRY",
                    "genie_key": latest["genie_key"],
                    "genie_request": retry_request,
                    "message": f"Retrying {latest['genie_key']} — previous attempt failed validation: {reason}",
                },
            }
        return {
            "validations": [{"passed": False, "reason": f"Retries exhausted: {reason}"}],
            "next_action": "SYNTHESIZE",
            "router_message": (
                f"I wasn't able to get a reliable answer after {max_retries} attempts "
                f"({reason}). I'll answer with what I have and note the limitation."
            ),
        }

    # Passed both checks — hand back to the router to decide whether
    # another Genie is needed or we're ready to synthesize.
    return {
        "validations": [{"passed": True, "reason": ""}],
        "next_action": "ROUTER",
    }