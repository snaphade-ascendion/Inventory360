"""
genie/client.py
================
All Databricks Genie API logic in one place.

Adapted from a confirmed-working extraction pattern:
  start_conversation -> poll get_message -> get_message_query_result
  -> get_statement_result_chunk_n -> data_array

The raw REST re-fetch in call_genie() exists because the SDK (as of the
version this was tested against) drops viz/thoughts/text.purpose fields
that only come back on the raw JSON response — worth re-checking against
the installed databricks-sdk version before assuming this is still needed.

Keeping all Genie logic here means:
  - If the SDK changes, one file to update.
  - Adding a new Genie = add one entry to genie/config.py only.
  - Node functions (graph/nodes/genie_call.py) stay clean — they just
    call call_genie() and work with the structured dict it returns.
"""

import time
from auth import get_user_client
from genie.config import GENIE_SPACES

POLL_INTERVAL_SECONDS = 2
MAX_POLL_ATTEMPTS = 45  # 45 x 2s = 90 second timeout per Genie call


def call_genie(genie_key: str, question: str, conversation_id: str | None = None) -> dict:
    """
    Call a Databricks Genie and return ALL response content as a structured dict.

    Parameters
    ----------
    genie_key : str
        Key into genie.config.GENIE_SPACES (e.g. "inventory_visibility").
    question : str
        The (already reformatted-by-router) request text to send to Genie.
    conversation_id : str, optional
        Pass a prior conversation_id to continue the same Genie conversation
        (useful for a retry/refinement within the same turn). Genies are
        otherwise stateless between separate calls.

    Returns
    -------
    dict with keys:
      status:          "success" | "failed" | "timeout" | "error"
      error:            str or None
      conversation_id:  str
      message_id:       str
      attachments:      list of {"type": "text"|"query"|"viz"|"suggested_questions", ...}
      query_data:       {"columns": [...], "col_types": [...], "rows": [...],
                          "total_rows": int} or None or {"error": str}
    """
    if genie_key not in GENIE_SPACES:
        return {"status": "error", "error": f"Unknown genie_key: {genie_key}"}

    space_id = GENIE_SPACES[genie_key]["space_id"]

    try:
        # On behalf of the signed-in user: Genie runs its SQL with the user's UC permissions.
        w = get_user_client()

        # Step 1 — Start (or continue) conversation
        if conversation_id:
            response = w.genie.create_message(
                space_id=space_id, conversation_id=conversation_id, content=question
            )
            message_id = response.message_id
        else:
            response = w.genie.start_conversation(space_id=space_id, content=question)
            conversation_id = response.conversation_id
            message_id = response.message_id

        # Step 2 — Poll until completed
        msg = None
        for _ in range(MAX_POLL_ATTEMPTS):
            msg = w.genie.get_message(
                space_id=space_id, conversation_id=conversation_id, message_id=message_id
            )
            if msg.status and msg.status.value == "COMPLETED":
                break
            elif msg.status and msg.status.value in ("FAILED", "CANCELLED"):
                return {
                    "status": "failed",
                    "error": f"Genie query failed with status: {msg.status.value}",
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                }
            time.sleep(POLL_INTERVAL_SECONDS)
        else:
            return {
                "status": "timeout",
                "error": "Genie did not complete within 90 seconds.",
                "conversation_id": conversation_id,
                "message_id": message_id,
            }

        # Step 3 — Re-fetch message via raw REST API to capture ALL fields
        # (public api_client.do: same user auth, SDK-managed timeouts/retries)
        try:
            raw_msg = w.api_client.do(
                "GET",
                f"/api/2.0/genie/spaces/{space_id}/conversations/{conversation_id}/messages/{message_id}",
            ) or {}
        except Exception:
            raw_msg = {}

        attachments = []
        for att in raw_msg.get("attachments", []):
            aid = att.get("attachment_id", "")

            if "text" in att:
                attachments.append({
                    "type": "text",
                    "content": att["text"].get("content", ""),
                    "purpose": att["text"].get("purpose", ""),
                    "attachment_id": aid,
                })

            if "query" in att:
                q = att["query"]
                meta = q.get("query_result_metadata", {})
                attachments.append({
                    "type": "query",
                    "sql": q.get("query", ""),
                    "title": q.get("title", ""),
                    "description": q.get("description", ""),
                    "statement_id": q.get("statement_id", ""),
                    "thoughts": q.get("thoughts", []),
                    "parameters": q.get("parameters", []),
                    "result_metadata": {
                        "row_count": meta.get("row_count"),
                        "is_truncated": meta.get("is_truncated"),
                    },
                    "attachment_id": aid,
                })

            if "viz" in att:
                attachments.append({
                    "type": "viz",
                    "query_attachment_id": att["viz"].get("query_attachment_id", ""),
                    "attachment_id": aid,
                })

            if "suggested_questions" in att:
                attachments.append({
                    "type": "suggested_questions",
                    "questions": att["suggested_questions"].get("questions", []),
                    "attachment_id": aid,
                })

        # Step 4 — Fetch data rows via statement execution (with column types)
        query_data = None
        try:
            query_result = w.genie.get_message_query_result(
                space_id=space_id, conversation_id=conversation_id, message_id=message_id
            )
            if query_result.statement_response is not None:
                statement_id = query_result.statement_response.statement_id
                schema_cols = query_result.statement_response.manifest.schema.columns
                columns = [col.name for col in schema_cols]
                col_types = [
                    {"name": col.name, "type": str(col.type_name.value) if col.type_name else "STRING"}
                    for col in schema_cols
                ]
                chunk = w.statement_execution.get_statement_result_chunk_n(
                    statement_id=statement_id, chunk_index=0
                )
                rows = chunk.data_array or []
                query_data = {
                    "columns": columns,
                    "col_types": col_types,
                    "rows": [dict(zip(columns, row)) for row in rows],
                    "total_rows": len(rows),
                }
        except Exception as e:
            query_data = {"error": f"Could not extract query result: {str(e)}"}

        return {
            "status": "success",
            "error": None,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "attachments": attachments,
            "query_data": query_data,
        }

    except Exception as e:
        return {"status": "error", "error": f"Error calling '{genie_key}' genie: {str(e)}"}


def format_genie_response(result: dict) -> str:
    """
    Turn a call_genie() dict into a human-readable string. Used by
    validate/synthesize nodes when they need a plain-text summary to feed
    into an LLM prompt — NOT necessarily what gets shown in the UI (the
    Streamlit layer can render the structured dict directly with richer
    formatting, e.g. an expandable SQL block).
    """
    if result.get("status") != "success":
        return result.get("error", "Unknown error")

    parts = []
    for att in result.get("attachments", []):
        if att["type"] == "text":
            parts.append(att["content"])
        elif att["type"] == "query":
            parts.append(f"SQL generated:\n{att['sql']}")
            if att.get("description"):
                parts.append(f"Query description: {att['description']}")
        elif att["type"] == "viz":
            parts.append(f"Visualization requested (linked to query attachment {att.get('query_attachment_id', 'N/A')})")
        elif att["type"] == "suggested_questions":
            parts.append("Suggested follow-ups: " + "; ".join(att.get("questions", [])))

    qd = result.get("query_data")
    if qd and "error" not in qd:
        rows = qd.get("rows", [])
        if rows:
            parts.append(f"\nQuery data ({qd['total_rows']} rows):")
            parts.append("Columns: " + ", ".join(qd["columns"]))
            for row in rows[:20]:
                parts.append(str(row))
            if len(rows) > 20:
                parts.append(f"... (showing first 20 of {qd['total_rows']} rows)")
        else:
            parts.append("Query returned no rows.")
    elif qd and "error" in qd:
        parts.append(qd["error"])

    return "\n\n".join(parts) if parts else "Genie completed but returned no content."
