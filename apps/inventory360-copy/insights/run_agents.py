"""
insights/run_agents.py
========================
Orchestration entry point for an Overview insight run. Two callers:

  1. A Databricks Job on a schedule (e.g. hourly/nightly) runs this file
     directly -> `python insights/run_agents.py`, trigger="scheduled".
  2. The Overview page's "Run insights now" button imports and calls
     run_all_and_store("manual") directly in-process, for the demo.

Same function either way, so a scheduled run and a manual run are
identical in every respect except the trigger label stored with them.

Paced deliberately: 6 LLM calls happen here back-to-back (5 agents +
1 supervisor), all against the same shared, low-QPS "synthesis" serving
endpoint (databricks-deepseek-v4-pro-0813 — see llm_client.py's own
comment on this). Firing them with no gap risked tripping a rate/quota
limit that then blocked OTHER callers of that same endpoint too (seen
live: the chatbot's synthesize step failed right after an insight run).
LLM_CALL_PACING_SECONDS puts a small gap between each call — cheap
insurance, and easy to tune down once the endpoint's real QPS budget
is known.
"""

import sys
import time

from genie.config import GENIE_SPACES
from insights import db
from insights.personas import DEFAULT_PERSONA, PERSONAS, normalize_persona
from insights.sql_agent import run_insight_agent
from insights.supervisor import run_supervisor

LLM_CALL_PACING_SECONDS = 3


def run_all_and_store(trigger: str = "scheduled", persona: str = DEFAULT_PERSONA) -> dict:
    """
    Runs all 5 per-genie insight agents, then the supervisor, then
    persists one combined run for the given persona (insights/personas.py).
    Returns the same dict db.get_latest_run(persona) would return, so a
    caller can render immediately without a re-read.
    """
    persona = normalize_persona(persona)
    agent_results = {}
    genie_keys = list(GENIE_SPACES.keys())
    for i, genie_key in enumerate(genie_keys):
        agent_results[genie_key] = run_insight_agent(genie_key, persona=persona)
        if i < len(genie_keys) - 1:
            time.sleep(LLM_CALL_PACING_SECONDS)

    time.sleep(LLM_CALL_PACING_SECONDS)
    supervisor_output = run_supervisor(list(agent_results.values()), persona=persona)
    key_callouts = supervisor_output["key_callouts"]

    db.ensure_table()
    run_id = db.save_run(trigger=trigger, agents=agent_results, key_callouts=key_callouts, persona=persona)

    return {
        "run_id": run_id,
        "trigger": trigger,
        "persona": persona,
        "agents": agent_results,
        "key_callouts": key_callouts,
    }


if __name__ == "__main__":
    # Scheduled Databricks Job entry point. Optional arg: a persona key
    # (c_level / data_analyst); with no arg, every persona is generated.
    personas = [sys.argv[1]] if len(sys.argv) > 1 else list(PERSONAS.keys())
    for i, p in enumerate(personas):
        result = run_all_and_store(trigger="scheduled", persona=p)
        print(f"Overview insight run complete [{result['persona']}]: {result['run_id']} ({len(result['agents'])} agents)")
        if i < len(personas) - 1:
            time.sleep(LLM_CALL_PACING_SECONDS)
