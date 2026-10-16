# Databricks notebook — run this in a notebook attached to a cluster
# with the app's repo on the path (or paste llm_client.py/auth.py next
# to this notebook so the imports below resolve).
#
# What it does:
#   1. Lists every serving endpoint in the workspace so you can see
#      what's actually available (vs. what ENDPOINTS in llm_client.py
#      currently points at).
#   2. Test-calls a shortlist of current Foundation Model API names
#      with a trivial prompt via your own ask_llm(), so you find a
#      working replacement using the EXACT code path the app uses
#      (same auth, same request shape) — not a guess.
#
# Once you find one that works, update SYNTHESIS_ENDPOINT (and/or
# JUDGE_ENDPOINT) in llm_client.py to that name — nothing else in the
# app needs to change, per llm_client.py's own design (ENDPOINTS dict
# is the single place model names live).

# COMMAND ----------

from auth import get_workspace_client
from llm_client import ask_llm

w = get_workspace_client()

# COMMAND ----------

# 1. List every serving endpoint in the workspace, so you can see the
#    real current names rather than guessing from docs.
print(f"{'NAME':45} {'STATE':12} {'READY':8}")
for ep in w.serving_endpoints.list():
    state = ep.state.config_update.value if ep.state and ep.state.config_update else "?"
    ready = ep.state.ready.value if ep.state and ep.state.ready else "?"
    print(f"{ep.name:45} {state:12} {ready:8}")

# COMMAND ----------

# 2. Try a shortlist of likely-current Databricks Foundation Model API
#    names (as of the docs page in the error message) against the
#    app's OWN ask_llm() — same code path, same auth, so a pass here
#    means it'll actually work in the app, not just "exists".
#
#    Trim/extend this list to match what you saw in step 1's output.
CANDIDATE_ENDPOINTS = [
    "databricks-claude-sonnet-4-5",       # already used for the router — known-good baseline
    "databricks-claude-opus-4-1",
    "databricks-meta-llama-3-3-70b-instruct",
    "databricks-deepseek-v3",             # non-deprecated deepseek name, if present
]

test_messages = [{"role": "user", "content": "Reply with exactly one word: OK"}]

working = []
for name in CANDIDATE_ENDPOINTS:
    try:
        result = ask_llm(test_messages, endpoint=name, max_tokens=10)
        print(f"✅ {name}: {result!r}")
        working.append(name)
    except Exception as e:
        print(f"❌ {name}: {e}")

print("\nWorking endpoints:", working)

# COMMAND ----------

# 3. Once you've picked one from the "Working endpoints" list above,
#    update llm_client.py:
#
#    SYNTHESIS_ENDPOINT = "databricks-claude-sonnet-4-5"   # <- your pick
#
# That's the only edit needed — insights/sql_agent.py, supervisor.py,
# and graph/nodes/synthesize.py all call ask_llm(call_site="synthesis")
# and pick up whatever SYNTHESIS_ENDPOINT resolves to.
