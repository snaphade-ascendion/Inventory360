"""
testing/judge.py
==================
LLM-as-judge for the testing app. One function, one LLM call per result:

- ALWAYS returns a confidence label (High/Medium/Low) — an assessment of
  how well-grounded and complete the answer looks given the data that
  was actually retrieved, independent of any reference answer. This
  applies to every run type (benchmark, bulk, repeat).
- When a reference is supplied (benchmark run type), ALSO returns a
  Pass/Fail correctness verdict:
    - expected_value present -> numeric check is PRIMARY: the judge
      extracts the relevant number from the answer and compares it to
      expected_value within expected_value_tolerance_pct.
    - expected_answer_text is a SECONDARY, supporting signal — used to
      help pick the right number when the answer mentions several, and
      as the sole basis for the verdict when no expected_value exists
      (qualitative questions with no single number to check).

Kept as a single combined call (not two separate judge calls) to avoid
doubling LLM cost/latency per test result.
"""

from llm_client import ask_llm_json
from genie.client import format_genie_response

JUDGE_OUTPUT_CONTRACT = """
Respond with exactly one JSON object and nothing else:

{
  "confidence": "High" | "Medium" | "Low",
  "confidence_reason": "<one sentence>",
  "extracted_value": <number or null>,
  "numeric_match": <true|false|null>,
  "semantic_match": <true|false|null>,
  "benchmark_verdict": "Pass" | "Fail" | null,
  "benchmark_check_method": "numeric" | "semantic" | "none"
}

Field rules:
- confidence/confidence_reason: ALWAYS populate. Judge how well the answer is grounded in
  the retrieved data shown below — is it specific, does it actually answer the question,
  does it avoid overreaching beyond what the data supports. This is independent of whether
  a reference answer was provided.
- extracted_value: if a reference numeric value was given, extract the SINGLE number from
  the answer that corresponds to what was asked (not a delta, not an unrelated figure that
  happens to appear). null if no reference numeric value was given, or no matching number
  could be found in the answer.
- numeric_match: true if extracted_value is within the given tolerance of the expected
  value, false if not, null if no expected numeric value was given.
- semantic_match: true/false assessment of whether the answer's meaning matches the
  reference answer text (when one was given). null if no reference text was given.
- benchmark_verdict: null if no reference (numeric or text) was given at all (this is a
  bulk/repeat question, not a benchmark question — a human will judge correctness instead).
  Otherwise: if an expected numeric value was given, base the verdict PRIMARILY on
  numeric_match (method "numeric") — semantic_match is a secondary signal only, mentioned in
  confidence_reason if it disagrees with the numeric result, but does not override it. If no
  expected numeric value was given but reference text was, base the verdict on semantic_match
  alone (method "semantic").
- benchmark_check_method: "numeric" | "semantic" | "none" — matches which check determined
  benchmark_verdict, or "none" if benchmark_verdict is null.
"""


def _build_judge_prompt(
    question: str,
    answer: str,
    genie_results: list[dict],
    expected_value: float | None,
    expected_value_tolerance_pct: float | None,
    expected_answer_text: str | None,
) -> str:
    genie_context = "\n\n".join(
        f"Genie '{rec['genie_key']}' was asked: {rec['request_sent']!r}\n{format_genie_response(rec['result'])}"
        for rec in genie_results
    ) or "(no Genie was called for this answer)"

    reference_block = "No reference answer was provided for this question (bulk/repeat run — a human will judge correctness separately)."
    if expected_value is not None or expected_answer_text:
        reference_block = "Reference answer for this benchmark question:\n"
        if expected_value is not None:
            tol = expected_value_tolerance_pct if expected_value_tolerance_pct is not None else 5.0
            reference_block += f"- Expected numeric value: {expected_value} (tolerance: ±{tol}%)\n"
        if expected_answer_text:
            reference_block += f"- Expected answer text (secondary signal): {expected_answer_text}\n"

    return f"""{JUDGE_OUTPUT_CONTRACT}

---

Question: {question}

Answer given: {answer}

---

Data actually retrieved to produce this answer:
{genie_context}

---

{reference_block}
"""


def run_judge(
    question: str,
    answer: str,
    genie_results: list[dict],
    expected_value: float | None = None,
    expected_value_tolerance_pct: float | None = None,
    expected_answer_text: str | None = None,
) -> dict:
    """
    Returns a dict with keys: confidence, confidence_reason,
    extracted_value, numeric_match, semantic_match, benchmark_verdict,
    benchmark_check_method. Falls back to a safe "Low confidence, no
    verdict" result if the judge call itself fails to parse, rather than
    raising and losing the whole test result.
    """
    prompt = _build_judge_prompt(
        question, answer, genie_results, expected_value, expected_value_tolerance_pct, expected_answer_text
    )
    try:
        result = ask_llm_json([{"role": "user", "content": prompt}], call_site="judge")
    except ValueError:
        return {
            "confidence": "Low",
            "confidence_reason": "Judge call failed to return valid JSON.",
            "extracted_value": None,
            "numeric_match": None,
            "semantic_match": None,
            "benchmark_verdict": None,
            "benchmark_check_method": "none",
        }

    # Defensive normalization — never trust the LLM's output shape blindly.
    confidence = result.get("confidence") if result.get("confidence") in ("High", "Medium", "Low") else "Low"
    verdict = result.get("benchmark_verdict") if result.get("benchmark_verdict") in ("Pass", "Fail") else None
    method = result.get("benchmark_check_method") if result.get("benchmark_check_method") in ("numeric", "semantic", "none") else "none"

    return {
        "confidence": confidence,
        "confidence_reason": result.get("confidence_reason", ""),
        "extracted_value": result.get("extracted_value"),
        "numeric_match": result.get("numeric_match"),
        "semantic_match": result.get("semantic_match"),
        "benchmark_verdict": verdict,
        "benchmark_check_method": method,
    }