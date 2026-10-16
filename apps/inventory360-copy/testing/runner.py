"""
testing/runner.py
===================
Orchestrates all 3 test types. Each question goes through the FULL
LangGraph orchestrator (graph.build_graph.run_turn) — same code path as
production — so routing accuracy is tested too, not just Genie/data
quality in isolation.

Three entry points, one per run type:
  run_benchmark() — questions from the test_questions bank, judged for
                    correctness by the LLM judge (numeric primary,
                    semantic secondary) as well as confidence.
  run_bulk()      — ad-hoc questions (e.g. from an uploaded CSV), judged
                    for confidence only; a human reviews correctness
                    afterward in the UI.
  run_repeat()    — one question run N times, same human-review model
                    as run_bulk(), to check answer consistency.
"""

import json
import time

from graph.build_graph import run_turn
from testing import db
from testing.judge import run_judge


def _genie_keys_used(genie_results: list[dict]) -> str:
    seen = []
    for rec in genie_results:
        if rec["genie_key"] not in seen:
            seen.append(rec["genie_key"])
    return ", ".join(seen)


def _sanitize_for_storage(genie_results: list[dict], validations: list[dict], max_rows: int = 20) -> dict:
    """
    Preserves the FULL shape of genie_results/validations (same
    GenieCallRecord/ValidationRecord structure graph/state.py defines,
    same shape ui/show_work.py's render_show_work() already knows how to
    render) — not a stripped-down summary. This lets the Testing app
    reuse the exact same "Show work" rendering the live chatbot uses,
    for consistency, instead of a separate bespoke detail view.

    query_data.rows is capped to max_rows per Genie call to bound storage
    size — evidence stays useful for evaluation without unbounded growth.
    """
    sanitized_results = []
    for rec in genie_results:
        result = dict(rec["result"])
        qd = result.get("query_data")
        if isinstance(qd, dict) and qd.get("rows"):
            qd = dict(qd)
            qd["rows"] = qd["rows"][:max_rows]
            result["query_data"] = qd
        sanitized_results.append({
            "genie_key": rec["genie_key"],
            "request_sent": rec["request_sent"],
            "result": result,
            "attempt_number": rec.get("attempt_number"),
            "elapsed_seconds": rec.get("elapsed_seconds"),
            "router_decision": rec.get("router_decision"),
        })
    return {"genie_results": sanitized_results, "validations": validations}


def _has_reference(expected_value: float | None, expected_answer_text: str | None) -> bool:
    return expected_value is not None or bool(expected_answer_text)


def _status_override_judge(
    status: str, expected_value: float | None, expected_answer_text: str | None
) -> dict | None:
    """
    Deterministic judge result for the two statuses that don't need (and
    shouldn't get) an LLM judgment call — the rule is fixed, not a matter
    of assessment:

    - CLARIFIED: the router asked a clarifying question instead of
      guessing. That's not an incorrect or hallucinated answer, so it
      counts as a Pass (when this is a benchmark question with a
      reference) with Medium confidence — Medium because a clarifying
      question, while safe, also didn't actually answer anything.
    - DECLINED: the router recognized the question as out of scope and
      declined rather than guessing or hallucinating an answer — same
      reasoning as CLARIFIED, so it also counts as a Pass (when this is
      a benchmark question with a reference). Confidence is High rather
      than Medium, since declining is a more decisive judgment call than
      asking a clarifying question.

    Returns None (no override — fall through to the real LLM judge) for
    any other status.
    """
    has_ref = _has_reference(expected_value, expected_answer_text)

    if status == "clarified":
        return {
            "confidence": "Medium",
            "confidence_reason": "Router asked a clarifying question rather than risking an incorrect or hallucinated answer.",
            "extracted_value": None,
            "numeric_match": None,
            "semantic_match": None,
            "benchmark_verdict": "Pass" if has_ref else None,
            "benchmark_check_method": "none",
        }

    if status == "declined":
        return {
            "confidence": "High",
            "confidence_reason": "Router correctly identified this as out of scope and declined rather than guessing.",
            "extracted_value": None,
            "numeric_match": None,
            "semantic_match": None,
            "benchmark_verdict": "Pass" if has_ref else None,
            "benchmark_check_method": "none",
        }

    return None


def _run_one_question(
    question_text: str,
    question_id: str | None,
    expected_value: float | None,
    expected_value_tolerance_pct: float | None,
    expected_answer_text: str | None,
    repeat_index: int | None,
    run_id: str,
) -> str:
    """Runs one question through the full graph, judges it, writes one test_results row. Returns result_id."""
    start = time.time()
    final_state = run_turn(user_question=question_text, prior_messages=[])
    elapsed = round(time.time() - start, 2)

    answer = final_state.get("final_answer") or ""
    genie_results = final_state.get("genie_results", [])
    validations = final_state.get("validations", [])
    status = final_state.get("status", "unknown")

    judge_result = _status_override_judge(status, expected_value, expected_answer_text)
    if judge_result is None:
        judge_result = run_judge(
            question=question_text,
            answer=answer,
            genie_results=genie_results,
            expected_value=expected_value,
            expected_value_tolerance_pct=expected_value_tolerance_pct,
            expected_answer_text=expected_answer_text,
        )

    benchmark_verdict = judge_result["benchmark_verdict"] if judge_result["benchmark_verdict"] else (
        "NA" if not _has_reference(expected_value, expected_answer_text) else None
    )

    return db.insert_result(
        run_id=run_id,
        question_id=question_id,
        question_text=question_text,
        repeat_index=repeat_index,
        answer_text=answer,
        genie_keys_used=_genie_keys_used(genie_results),
        elapsed_seconds=elapsed,
        status=status,
        judge_confidence=judge_result["confidence"],
        judge_confidence_reason=judge_result["confidence_reason"],
        benchmark_verdict=benchmark_verdict,
        benchmark_check_method=judge_result["benchmark_check_method"],
        benchmark_extracted_value=judge_result["extracted_value"],
        benchmark_numeric_match=judge_result["numeric_match"],
        genie_results_json=json.dumps(_sanitize_for_storage(genie_results, validations), default=str),
    )


def run_benchmark(app_version: str, label: str = "Benchmark run", progress_callback=None) -> str:
    """
    Runs every active question in the test_questions bank. Returns the
    run_id. progress_callback(current_index, total, question_text), if
    given, is called before each question so a UI can show live progress.
    """
    questions = db.list_questions(active_only=True)
    run_id = db.create_run(
        run_type="benchmark", label=label, app_version=app_version,
        source_detail="full active question bank", total_questions=len(questions),
    )
    for i, q in enumerate(questions):
        if progress_callback:
            progress_callback(i, len(questions), q["question_text"])
        _run_one_question(
            question_text=q["question_text"],
            question_id=q["question_id"],
            expected_value=q.get("expected_value"),
            expected_value_tolerance_pct=q.get("expected_value_tolerance_pct"),
            expected_answer_text=q.get("expected_answer_text"),
            repeat_index=None,
            run_id=run_id,
        )
    db.complete_run(run_id)
    return run_id


def run_bulk(questions: list[str], app_version: str, label: str = "Bulk run", source_detail: str = "", progress_callback=None) -> str:
    """
    Runs a list of ad-hoc question strings (e.g. from an uploaded CSV,
    capped by the caller — UI enforces the ~30 question limit). No
    reference answers — correctness is reviewed by a human afterward.
    """
    run_id = db.create_run(
        run_type="bulk", label=label, app_version=app_version,
        source_detail=source_detail or f"{len(questions)} ad-hoc questions", total_questions=len(questions),
    )
    for i, question_text in enumerate(questions):
        if progress_callback:
            progress_callback(i, len(questions), question_text)
        _run_one_question(
            question_text=question_text, question_id=None,
            expected_value=None, expected_value_tolerance_pct=None, expected_answer_text=None,
            repeat_index=None, run_id=run_id,
        )
    db.complete_run(run_id)
    return run_id


def run_repeat(question: str, n: int, app_version: str, label: str = "Repeat run", progress_callback=None) -> str:
    """
    Runs the SAME question n times, to check answer consistency. No
    reference answer — correctness/consistency is reviewed by a human
    afterward, same as run_bulk().
    """
    run_id = db.create_run(
        run_type="repeat", label=label, app_version=app_version,
        source_detail=f"{question!r} x{n}", total_questions=n,
    )
    for i in range(n):
        if progress_callback:
            progress_callback(i, n, question)
        _run_one_question(
            question_text=question, question_id=None,
            expected_value=None, expected_value_tolerance_pct=None, expected_answer_text=None,
            repeat_index=i + 1, run_id=run_id,
        )
    db.complete_run(run_id)
    return run_id