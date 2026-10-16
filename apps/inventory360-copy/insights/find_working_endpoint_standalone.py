# Databricks notebook — standalone, no app files needed.
# Just needs databricks-sdk + requests on the cluster (both already in
# requirements.txt, so any cluster that's ever run this app has them;
# otherwise: %pip install databricks-sdk requests).
#
# Same auth pattern as auth.py (WorkspaceClient(), works inside a
# Databricks Apps / notebook context automatically) and same request
# shape as llm_client.ask_llm() — this is that function copied out
# standalone, not reimplemented, so a pass here means the app's real
# ask_llm() will also work against the same endpoint name.

# COMMAND ----------

import requests
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

# COMMAND ----------

# 1. List every serving endpoint in the workspace — real current names,
#    not a guess from docs.
print(f"{'NAME':45} {'STATE':12} {'READY':8}")
for ep in w.serving_endpoints.list():
    state = ep.state.config_update.value if ep.state and ep.state.config_update else "?"
    ready = ep.state.ready.value if ep.state and ep.state.ready else "?"
    print(f"{ep.name:45} {state:12} {ready:8}")

# COMMAND ----------

def ask_llm(messages: list[dict], endpoint: str, max_tokens: int = 10, temperature: float = 0.0) -> str:
    """Copied from llm_client.ask_llm() — same URL/header/payload shape, no retry logic (this is a one-shot test, not production traffic)."""
    url = f"{w.config.host}/serving-endpoints/{endpoint}/invocations"
    headers = dict(w.config._header_factory())
    headers["Content-Type"] = "application/json"
    payload = {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}

    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    if not resp.ok:
        try:
            detail = resp.json()
        except ValueError:
            detail = resp.text
        raise RuntimeError(f"{resp.status_code} from '{endpoint}': {detail}")
    return resp.json()["choices"][0]["message"]["content"]


# COMMAND ----------

# 2. Try a shortlist of likely-current Foundation Model API names
#    against that same real request shape. Trim/extend to match what
#    you saw printed in step 1.
CANDIDATE_ENDPOINTS = [
    "databricks-claude-sonnet-4-5",       # already used for the router in llm_client.py — known-good baseline
    "databricks-claude-opus-4-1",
    "databricks-meta-llama-3-3-70b-instruct",
    "databricks-deepseek-v3",             # non-deprecated deepseek name, if present
]

test_messages = [{"role": "user", "content": "Reply with exactly one word: OK"}]

working = []
for name in CANDIDATE_ENDPOINTS:
    try:
        result = ask_llm(test_messages, endpoint=name)
        print(f"✅ {name}: {result!r}")
        working.append(name)
    except Exception as e:
        print(f"❌ {name}: {e}")

print("\nWorking endpoints:", working)

# COMMAND ----------

# 3. Once you've picked one, in llm_client.py update:
#
#    SYNTHESIS_ENDPOINT = "<your pick>"
#
# (and check JUDGE_ENDPOINT = "databricks-glm-5-3" the same way — add
# it to CANDIDATE_ENDPOINTS above if you're not sure it's still live —
# it may hit the same deprecation issue.)
#
# That's the only app change needed: every insights/chat call goes
# through ask_llm(call_site="synthesis"), which reads SYNTHESIS_ENDPOINT
# from the ENDPOINTS dict — no other file references the model name.
