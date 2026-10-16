"""
insights/personas.py
======================
Audience personas for the Overview page's AI-generated text (Key Callouts +
Subject-Area Intelligence). The Overview page shows a radio button
(C-Level / Data Analyst); the selected persona key is passed through
run_agents -> sql_agent / supervisor, which splice the persona-specific
guidance below into their system prompts. Runs are stored per persona
(insights/db.py), so switching the radio button just reads that persona's
latest run.

The data fed to the LLM is identical for both personas; only the audience,
tone, level of detail and output length change. The "only state facts from
the data" rules stay in force for both.
"""

DEFAULT_PERSONA = "c_level"

PERSONAS = {
    "c_level": {
        "label": "C-Level",
        # ---- Subject-Area Intelligence (per-genie agent) ----
        "agent_audience": (
            "a C-level executive (CEO/COO/CFO) who has under a minute for this subject area"
        ),
        "agent_guidance": """- Lead with the business impact: what the headline number means for revenue,
  customer service, cost or inventory risk.
- Use plain business language. Do NOT mention metric-view names, table names, column
  names, SQL, or measure identifiers.
- Round numbers sensibly (e.g. "$2.1M", "94%") and only cite the 1-2 numbers that matter most.
- Surface the single biggest risk or opportunity; skip routine/flat detail.""",
        "agent_bullets": "2-3",
        "agent_summary_len": "1 sentence",
        # ---- Key Callouts (supervisor) ----
        "supervisor_audience": "the executive leadership team (C-suite) in a boardroom",
        "supervisor_guidance": """- Write for executives: strategic, outcome-focused, no jargon, no table/column/measure names.
- Prioritize what affects revenue, margin, customer experience or inventory risk.
- Each callout should make clear why it matters to the business, using only facts present
  in the agents' output.""",
        "supervisor_count": "3",
    },
    "data_analyst": {
        "label": "Data Analyst",
        # ---- Subject-Area Intelligence (per-genie agent) ----
        "agent_audience": (
            "a data analyst who will dig into the numbers and wants precise, granular detail"
        ),
        "agent_guidance": """- Be precise: cite exact values, absolute AND percent week-over-week deltas where provided,
  and the specific dimension values (region, category, store, etc.) behind each finding.
- Name the measure and the breakdown dimension each insight comes from (use the
  measure/dimension names as given in the data) so the analyst can trace it back.
- Call out distribution shape where visible: concentration in top members, spread between
  highest and lowest breakdown values, and outliers.
- If a KNOWN DATA CAVEAT is provided, reflect it explicitly in the relevant insight.""",
        "agent_bullets": "3-5",
        "agent_summary_len": "1-2 sentences",
        # ---- Key Callouts (supervisor) ----
        "supervisor_audience": "a team of data analysts reviewing the dashboard in detail",
        "supervisor_guidance": """- Write for analysts: specific and quantitative. Keep exact figures, deltas (absolute and %),
  and the subject area + dimension/measure each callout comes from.
- Prefer callouts that point to where to investigate next (outliers, concentrations,
  week-over-week shifts, data caveats) over high-level business framing.""",
        "supervisor_count": "5-7",
    },
}


def get_persona(persona: str | None) -> dict:
    """Returns the persona config, falling back to the default for unknown/None keys."""
    return PERSONAS.get(persona or DEFAULT_PERSONA, PERSONAS[DEFAULT_PERSONA])


def normalize_persona(persona: str | None) -> str:
    return persona if persona in PERSONAS else DEFAULT_PERSONA
