"""
llm_client.py
=============
All LLM endpoint logic in one place.

Extends the original ask_llm() pattern: the router and synthesis steps can
use different endpoints/models without any other file changing. Swap a
model by editing ENDPOINTS below — nothing in graph/nodes/*.py needs to
change.

Uses the app's service principal auth (default WorkspaceClient) for
model-serving calls. Foundation model endpoints are shared resources that
don't require per-user identity — OBO tokens scoped by the Apps proxy
don't include serving-endpoint access.
"""

import json
import time
import requests
from auth import get_app_client  # service principal: OBO scopes don't cover model serving

# =============================================================================
# CONFIGURATION — one place to change models per call site
# =============================================================================
DEFAULT_ENDPOINT = "databricks-claude-sonnet-4-5"
SYNTHESIS_ENDPOINT = "databricks-claude-opus-4-1"  # confirmed working via
    # insights/find_working_endpoint_standalone.py (was databricks-deepseek-v4-pro-0813,
    # then briefly databricks-claude-sonnet-4-5 — see git history/prior comments if needed)
JUDGE_ENDPOINT = "databricks-claude-opus-4-1"  # confirmed working the same way
    # (was databricks-glm-5-3 — that endpoint returned HTTP 200 but an EMPTY completion
    # on a test prompt, not a clean error; not proven safe, so not used here)

ENDPOINTS = {
    "router": DEFAULT_ENDPOINT,     # fast, cheap — classification/routing only
    "synthesis": SYNTHESIS_ENDPOINT,  # swap to a larger model here if answer
                                     # quality on synthesis needs it later
    "judge": JUDGE_ENDPOINT,      # reserved for the LLM-as-judge eval step
}

REQUEST_TIMEOUT_SECONDS = 60

# Retry behavior for rate limiting (429) and transient server errors (5xx).
# A shared pay-per-token Foundation Model endpoint can have a fairly low
# default QPS limit, and a single graph turn can make 2-4 LLM calls
# back-to-back (router, possibly a second router pass, synthesis) — so
# backing off and retrying is worth having rather than failing the whole
# turn on the first 429.
MAX_LLM_RETRIES = 4
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
BASE_BACKOFF_SECONDS = 2.0


def ask_llm(
    messages: list[dict],
    call_site: str = "router",
    endpoint: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    response_format: dict | None = None,
) -> str:
    """
    Send a chat-style message list to a Databricks model-serving endpoint
    and return the response text.

    Parameters
    ----------
    messages : list[dict]
        OpenAI-style messages, e.g. [{"role": "system", "content": "..."},
        {"role": "user", "content": "..."}]. Callers build the full message
        list (system prompt + conversation history) — this function does
        not inject anything.
    call_site : str
        One of the keys in ENDPOINTS ("router", "synthesis", "judge").
        Determines which endpoint is used unless `endpoint` overrides it.
    endpoint : str, optional
        Explicit endpoint name. Overrides call_site lookup when provided.
    temperature : float
        Sampling temperature. Router calls should stay at 0.0 for
        consistent routing decisions; synthesis can go slightly higher
        if more natural-sounding prose is wanted later.
    response_format : dict, optional
        Pass a JSON schema / structured-output spec if the endpoint
        supports it. Left optional since not all serving endpoints
        support constrained decoding identically.

    Returns
    -------
    str
        The model's response text (message content only).

    Raises
    ------
    requests.HTTPError
        If the endpoint keeps returning a retryable error past
        MAX_LLM_RETRIES, or returns any non-retryable error status.
    """
    w = get_app_client()
    resolved_endpoint = endpoint or ENDPOINTS.get(call_site, DEFAULT_ENDPOINT)
    url = f"{w.config.host}/serving-endpoints/{resolved_endpoint}/invocations"
    headers = dict(w.config.authenticate())  # public SDK API (was private _header_factory)
    headers["Content-Type"] = "application/json"

    payload = {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if response_format is not None:
        payload["response_format"] = response_format

    last_error = None
    for attempt in range(MAX_LLM_RETRIES + 1):
        resp = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)

        if resp.status_code not in RETRYABLE_STATUS_CODES:
            if not resp.ok:
                # Surface the response body — a bare raise_for_status() only
                # gives the status line ("400 Bad Request"), not WHY. Most
                # Databricks/OpenAI-style serving errors put the real reason
                # (quota exceeded, malformed payload, etc.) in the JSON body.
                try:
                    detail = resp.json()
                except ValueError:
                    detail = resp.text
                raise requests.HTTPError(
                    f"{resp.status_code} error from '{resolved_endpoint}' "
                    f"(call_site={call_site}): {detail}",
                    response=resp,
                )
            return resp.json()["choices"][0]["message"]["content"]

        last_error = resp
        if attempt < MAX_LLM_RETRIES:
            # Honor the endpoint's Retry-After header if it sends one,
            # otherwise exponential backoff: 2s, 4s, 8s, 16s.
            retry_after = resp.headers.get("Retry-After")
            wait_seconds = float(retry_after) if retry_after else BASE_BACKOFF_SECONDS * (2 ** attempt)
            time.sleep(wait_seconds)

    last_error.raise_for_status()  # exhausted retries — raise the final error


def _balanced_span(text: str, start: int) -> str | None:
    """
    Given text[start] == '{', returns the substring from there through its
    matching '}' (brace-counting, respecting strings/escapes so a brace
    inside a string value doesn't throw the count off), or None if it never
    balances before the text ends.
    """
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _extract_json_object(text: str) -> dict | None:
    """
    Finds a parseable JSON object somewhere in `text`, tolerating junk
    before/after/between. Tries every '{' in the text, in order, as a
    candidate start — not just the first — because at a non-zero
    temperature the model occasionally emits stray characters that
    themselves contain an unmatched '{' before the real JSON starts (seen
    live: a garbled, fence-less '{"json">' right before the actual
    object). Anchoring on only the first '{' would consume that spurious
    brace, never find its matching close, and fail even though a valid
    object follows immediately after — so each candidate is independently
    balanced AND parsed, and the first one that succeeds wins.

    Returns the parsed dict, or None if no candidate parses.
    """
    idx = text.find("{")
    while idx != -1:
        span = _balanced_span(text, idx)
        if span is not None:
            try:
                return json.loads(span)
            except json.JSONDecodeError:
                pass
        idx = text.find("{", idx + 1)
    return None


def ask_llm_json(messages: list[dict], call_site: str = "router", **kwargs) -> dict:
    """
    Convenience wrapper for call sites (router, validate) that expect a
    single JSON object back. Raises ValueError with the raw text included
    if parsing fails, rather than silently returning None — callers
    (nodes) decide how to handle a malformed response (retry, decline,
    etc.), this function doesn't make that decision itself.

    Tries an increasingly tolerant sequence rather than one fixed cleanup,
    since at non-zero temperature the ways a response can have junk around
    the JSON vary (clean fence, clean object, stray prefix with no fence,
    etc.) — see _extract_json_object's docstring for the case that
    motivated this.
    """
    raw = ask_llm(messages, call_site=call_site, **kwargs)
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    extracted = _extract_json_object(cleaned)
    if extracted is not None:
        return extracted

    raise ValueError(f"LLM did not return valid JSON at call_site='{call_site}': {raw!r}")