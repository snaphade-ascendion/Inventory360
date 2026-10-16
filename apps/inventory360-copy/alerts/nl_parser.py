"""
alerts/nl_parser.py
=====================
"Describe the alert in plain language" -> a structured, VALIDATED alert
dict. One ask_llm_json call (call_site="router").

Covers metric, condition, threshold, frequency, and any of Region /
Category / Product Class / Exception Priority the sentence mentions.
Facility is deliberately NOT parsed from free text: store/DC names are
numerous and easy to mismatch from a sentence, so a Facility filter can
only be set through manual entry, where it's a real dropdown of live
values for the chosen metric.

The model's output is re-validated in Python against real allow-lists —
never trusted directly, the same way graph/nodes/router.py re-checks the
chat router's genie_key rather than trusting the LLM's choice blindly.
Region/category/class/exc_priority: since the metric isn't known when the
candidate value lists are built, they're a union across every alertable
metric's view; after the metric IS known, each chosen value is re-checked
against THAT metric's own dimension values (and dropped if the metric's
view doesn't have the dimension at all, or the value doesn't exist there).
"""

from sql_client import run_sql
from llm_client import ask_llm_json
from alerts.catalog import ALERT_DIMENSION_KEYS, ALERT_MEASURES, DISPLAY_LABEL, alert_dimensions_status
from alerts.constants import OPERATORS, FREQUENCIES
from alerts.dimension_values import get_dimension_values
from alerts.threshold import parse_threshold
from self_service.catalog import dim_column, qualified

_NL_DIMENSION_KEYS = [k for k in ALERT_DIMENSION_KEYS if k != "facility"]  # region, category, class, exc_priority

SYSTEM_PROMPT_TEMPLATE = """You translate one sentence describing an inventory/supply-chain alert into a
structured rule for Inventory360, a sporting goods retailer's analytics app.

## Metrics (use the exact key on the left)
{metric_lines}

## Region (use exactly one of these, or null if no region is mentioned)
{region_list}

## Category (use exactly one of these, or null if no category is mentioned)
{category_list}

## Product Class (use exactly one of these, or null if not mentioned)
{class_list}

## Exception Priority (use exactly one of these, or null if not mentioned)
{exc_priority_list}

## Output contract
Respond with exactly one JSON object and nothing else:
{{
  "metric_key": "<one metric key from the list above>",
  "operator": "above" | "below" | "equal",
  "threshold": <number, on the same scale the metric is normally shown in — e.g. 95 for "95%", not 0.95>,
  "region": "<one value from the Region list, or null>",
  "category": "<one value from the Category list, or null>",
  "class": "<one value from the Product Class list, or null>",
  "exc_priority": "<one value from the Exception Priority list, or null>",
  "frequency": "daily" | "weekly" | "monthly"
}}

Rules:
- "goes above" / "exceeds" / "is over" -> operator "above". "drops below" / "falls below" / "under" ->
  "below". "equals" / "is exactly" -> "equal".
- If frequency isn't stated, default to "weekly".
- Only set a filter if the sentence actually mentions it — never guess.
- Never invent a value outside the lists above — pick the closest real match, or null.
- Most metrics here do NOT have all four filters available — that's checked separately, so include
  whatever the sentence mentions and let the check afterward drop anything that doesn't apply.
"""


def _union_values(dim_key: str) -> list[str]:
    """Candidate values for the NL prompt, before the metric is known — union across whichever of
    the 10 alertable metrics' views have this dimension."""
    seen: set[str] = set()
    for m in ALERT_MEASURES:
        col = dim_column(dim_key, m["table"])
        if not col:
            continue
        result = run_sql(f"SELECT DISTINCT {col} AS v FROM {qualified(m['table'])} WHERE {col} IS NOT NULL")
        if result["status"] == "success":
            seen.update(str(r["v"]) for r in result["rows"] if r.get("v") is not None)
    return sorted(seen)


def _build_prompt() -> str:
    metric_lines = "\n".join(f"- {key}  (\"{DISPLAY_LABEL[key]}\")" for key in DISPLAY_LABEL)
    values = {k: _union_values(k) for k in _NL_DIMENSION_KEYS}
    return SYSTEM_PROMPT_TEMPLATE.format(
        metric_lines=metric_lines,
        region_list=", ".join(values["region"]) or "(none found)",
        category_list=", ".join(values["category"]) or "(none found)",
        class_list=", ".join(values["class"]) or "(none found)",
        exc_priority_list=", ".join(values["exc_priority"]) or "(none found)",
    )


def parse_alert_nl(text: str) -> dict:
    """Returns {metric_key, operator, threshold, frequency, dimensions: {dim_key: value}}."""
    if not text or not text.strip():
        raise ValueError("Describe the alert first.")

    system_prompt = _build_prompt()
    try:
        parsed = ask_llm_json(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": text.strip()}],
            call_site="router",
        )
    except ValueError:
        raise ValueError("Couldn't interpret that — try rephrasing, or use manual entry below.")

    metric_key = parsed.get("metric_key")
    if metric_key not in DISPLAY_LABEL:
        raise ValueError(f"Couldn't match a metric ('{metric_key}' isn't one I know) — try manual entry.")

    operator = parsed.get("operator")
    if operator not in {k for k, _ in OPERATORS}:
        raise ValueError(f"Couldn't work out the condition ('{operator}') — try manual entry.")

    try:
        threshold = parse_threshold(parsed.get("threshold"))
    except (ValueError, TypeError):
        raise ValueError("Couldn't work out the threshold number — try manual entry.")

    frequency = parsed.get("frequency")
    if frequency not in {k for k, _ in FREQUENCIES}:
        frequency = "weekly"

    # Keep a parsed dimension only if the chosen metric's own view actually has it, AND the value
    # is one that view really contains — e.g. a Merchandising metric can never carry a Region
    # filter, whatever the model returned.
    status = alert_dimensions_status(metric_key)
    dimensions: dict[str, str] = {}
    for dim_key in _NL_DIMENSION_KEYS:
        value = parsed.get(dim_key)
        if value and status.get(dim_key) and value in get_dimension_values(dim_key, metric_key):
            dimensions[dim_key] = value

    return {
        "metric_key": metric_key, "operator": operator, "threshold": threshold,
        "frequency": frequency, "dimensions": dimensions,
    }
