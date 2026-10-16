"""
testing/db.py
==============
Read/write helpers for the 3 testing tables (test_questions, test_runs,
test_results), built on top of sql_client.run_sql() — the confirmed
Statement Execution API pattern (auto-resolves a running SQL warehouse,
no manual warehouse ID config needed).

Table names are fully qualified (catalog.schema.table) in every query
since sql_client.run_sql() executes statements statelessly, with no
catalog/schema session context carried between calls.
"""

import uuid
from sql_client import run_app_sql as _execute  # app-owned state tables: service principal, not OBO

TABLE_QUESTIONS = "dsg.inventory360.test_questions"
TABLE_RUNS = "dsg.inventory360.test_runs"
TABLE_RESULTS = "dsg.inventory360.test_results"


def _run_sql(statement: str) -> list[dict]:
    """Execute a statement via sql_client.run_sql(); raises on failure, returns rows (possibly empty) on success."""
    result = _execute(statement)
    if result["status"] != "success":
        raise RuntimeError(f"SQL failed: {result['error']}\nStatement: {statement}")
    return result["rows"]


def _escape(value) -> str:
    """
    Minimal SQL literal escaping for the simple value types this module
    writes. Escapes BOTH backslashes and single quotes — Databricks/Spark
    SQL interprets backslash sequences as C-style escapes inside
    single-quoted string literals (\\n, \\\\, \\', etc.), same as several
    other SQL engines. Without escaping backslashes too, any value
    containing one (e.g. a JSON-encoded string with a literal newline,
    which json.dumps() represents as the two characters backslash+n) gets
    silently corrupted by the SQL engine on write — the backslash+n is
    consumed as an escape sequence and converted to an actual newline
    before the value is ever stored, breaking JSON parsing on read-back.
    Order matters: escape backslashes FIRST, before quotes, so the
    quote-doubling doesn't get affected by the backslash replacement.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"'{escaped}'"


def new_id() -> str:
    return str(uuid.uuid4())


# =====================================================================
# test_questions (benchmark bank)
# =====================================================================
def list_questions(active_only: bool = True) -> list[dict]:
    where = "WHERE active = TRUE" if active_only else ""
    return _run_sql(f"SELECT * FROM {TABLE_QUESTIONS} {where} ORDER BY created_ts")


def add_question(
    question_text: str,
    expected_value: float | None = None,
    expected_value_tolerance_pct: float = 5.0,
    expected_answer_text: str | None = None,
    category: str | None = None,
    created_by: str = "app_user",
) -> str:
    qid = new_id()
    _run_sql(f"""
        INSERT INTO {TABLE_QUESTIONS}
        (question_id, question_text, expected_value, expected_value_tolerance_pct,
         expected_answer_text, category, active, created_ts, created_by)
        VALUES ({_escape(qid)}, {_escape(question_text)}, {_escape(expected_value)},
                {_escape(expected_value_tolerance_pct)}, {_escape(expected_answer_text)},
                {_escape(category)}, TRUE, current_timestamp(), {_escape(created_by)})
    """)
    return qid


def deactivate_question(question_id: str) -> None:
    _run_sql(f"UPDATE {TABLE_QUESTIONS} SET active = FALSE WHERE question_id = {_escape(question_id)}")


# =====================================================================
# test_runs
# =====================================================================
def create_run(
    run_type: str,
    label: str,
    app_version: str,
    source_detail: str,
    total_questions: int,
    created_by: str = "app_user",
) -> str:
    run_id = new_id()
    _run_sql(f"""
        INSERT INTO {TABLE_RUNS}
        (run_id, run_type, label, app_version, source_detail, started_ts,
         completed_ts, created_by, total_questions)
        VALUES ({_escape(run_id)}, {_escape(run_type)}, {_escape(label)},
                {_escape(app_version)}, {_escape(source_detail)}, current_timestamp(),
                NULL, {_escape(created_by)}, {_escape(total_questions)})
    """)
    return run_id


def complete_run(run_id: str) -> None:
    _run_sql(f"UPDATE {TABLE_RUNS} SET completed_ts = current_timestamp() WHERE run_id = {_escape(run_id)}")


def list_runs(run_type: str | None = None, limit: int = 50) -> list[dict]:
    where = f"WHERE run_type = {_escape(run_type)}" if run_type else ""
    return _run_sql(f"SELECT * FROM {TABLE_RUNS} {where} ORDER BY started_ts DESC LIMIT {limit}")


def latest_run(run_type: str) -> dict | None:
    """
    Most recent COMPLETED run of the given type, or None if there isn't
    one yet. Used so a page load shows the latest persisted results by
    default, rather than requiring a fresh run in the current session.
    """
    rows = _run_sql(f"""
        SELECT * FROM {TABLE_RUNS}
        WHERE run_type = {_escape(run_type)} AND completed_ts IS NOT NULL
        ORDER BY started_ts DESC LIMIT 1
    """)
    return rows[0] if rows else None


# =====================================================================
# test_results
# =====================================================================
def insert_result(**kwargs) -> str:
    """
    kwargs may include any of: run_id, question_id, question_text,
    repeat_index, answer_text, genie_keys_used, elapsed_seconds, status,
    judge_confidence, judge_confidence_reason, benchmark_verdict,
    benchmark_check_method, benchmark_extracted_value,
    benchmark_numeric_match, genie_results_json.
    human_verdict always starts as 'Unreviewed'; reviewed_by/reviewed_ts
    stay NULL until update_human_review() is called.
    """
    result_id = new_id()
    cols = ["result_id", "human_verdict", "created_ts"] + list(kwargs.keys())
    vals = [_escape(result_id), "'Unreviewed'", "current_timestamp()"] + [_escape(v) for v in kwargs.values()]
    _run_sql(f"INSERT INTO {TABLE_RESULTS} ({', '.join(cols)}) VALUES ({', '.join(vals)})")
    return result_id


def list_results(run_id: str) -> list[dict]:
    return _run_sql(f"SELECT * FROM {TABLE_RESULTS} WHERE run_id = {_escape(run_id)} ORDER BY created_ts")


def update_human_review(result_id: str, verdict: str, reason: str | None, reviewed_by: str = "app_user") -> None:
    _run_sql(f"""
        UPDATE {TABLE_RESULTS}
        SET human_verdict = {_escape(verdict)}, human_reason = {_escape(reason)},
            reviewed_by = {_escape(reviewed_by)}, reviewed_ts = current_timestamp()
        WHERE result_id = {_escape(result_id)}
    """)


# =====================================================================
# Reporting aggregates (used by pages/1_Testing.py's accuracy report)
# =====================================================================
def benchmark_accuracy_summary(app_version: str | None = None) -> dict:
    where = "WHERE r.run_type = 'benchmark' AND t.benchmark_verdict IN ('Pass','Fail')"
    if app_version:
        where += f" AND r.app_version = {_escape(app_version)}"
    rows = _run_sql(f"""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN t.benchmark_verdict = 'Pass' THEN 1 ELSE 0 END) AS passed,
               AVG(t.elapsed_seconds) AS avg_response_time
        FROM {TABLE_RESULTS} t JOIN {TABLE_RUNS} r ON t.run_id = r.run_id
        {where}
    """)
    return rows[0] if rows else {"total": 0, "passed": 0, "avg_response_time": None}


def human_eval_accuracy_summary(app_version: str | None = None) -> dict:
    where = "WHERE r.run_type IN ('bulk','repeat','user') AND t.human_verdict IN ('Pass','Fail')"
    if app_version:
        where += f" AND r.app_version = {_escape(app_version)}"
    rows = _run_sql(f"""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN t.human_verdict = 'Pass' THEN 1 ELSE 0 END) AS passed,
               AVG(t.elapsed_seconds) AS avg_response_time
        FROM {TABLE_RESULTS} t JOIN {TABLE_RUNS} r ON t.run_id = r.run_id
        {where}
    """)
    return rows[0] if rows else {"total": 0, "passed": 0, "avg_response_time": None}


def confidence_distribution() -> list[dict]:
    return _run_sql(f"""
        SELECT judge_confidence, COUNT(*) AS cnt
        FROM {TABLE_RESULTS}
        WHERE judge_confidence IS NOT NULL
        GROUP BY judge_confidence
    """)


def accuracy_by_genie() -> list[dict]:
    """Human-eval accuracy (bulk + repeat + user ratings) only — scoped to match the Reliability Report's human-eval framing."""
    return _run_sql(f"""
        SELECT t.genie_keys_used,
               SUM(CASE WHEN t.human_verdict='Pass' THEN 1 ELSE 0 END) AS passed,
               SUM(CASE WHEN t.human_verdict IN ('Pass','Fail') THEN 1 ELSE 0 END) AS evaluated
        FROM {TABLE_RESULTS} t JOIN {TABLE_RUNS} r ON t.run_id = r.run_id
        WHERE t.genie_keys_used IS NOT NULL AND r.run_type IN ('bulk','repeat','user')
        GROUP BY t.genie_keys_used
    """)


def evaluated_results_for_subject_breakdown() -> list[dict]:
    """
    Raw per-result rows (genie_keys_used + both verdict columns) for every
    result that's actually been evaluated (benchmark or human), so the
    caller can attribute a multi-Genie result to EACH subject area it
    touched rather than grouping by the raw comma-joined combo string.
    """
    return _run_sql(f"""
        SELECT genie_keys_used, benchmark_verdict, human_verdict
        FROM {TABLE_RESULTS}
        WHERE genie_keys_used IS NOT NULL AND genie_keys_used != ''
          AND (benchmark_verdict IN ('Pass','Fail') OR human_verdict IN ('Pass','Fail'))
    """)


def top_human_reasons(limit: int = 5) -> list[dict]:
    return _run_sql(f"""
        SELECT human_reason, COUNT(*) AS cnt
        FROM {TABLE_RESULTS}
        WHERE human_reason IS NOT NULL
        GROUP BY human_reason
        ORDER BY cnt DESC
        LIMIT {limit}
    """)


def accuracy_by_version() -> list[dict]:
    """Human-eval accuracy (bulk + repeat + user ratings) only — scoped to match the Reliability Report's human-eval framing."""
    return _run_sql(f"""
        SELECT r.app_version,
               SUM(CASE WHEN t.human_verdict='Pass' THEN 1 ELSE 0 END) AS passed,
               SUM(CASE WHEN t.human_verdict IN ('Pass','Fail') THEN 1 ELSE 0 END) AS evaluated
        FROM {TABLE_RESULTS} t JOIN {TABLE_RUNS} r ON t.run_id = r.run_id
        WHERE r.app_version IS NOT NULL AND r.run_type IN ('bulk','repeat','user')
        GROUP BY r.app_version
        ORDER BY r.app_version
    """)


def latest_human_eval_version() -> str | None:
    """
    The most recently used bulk/repeat/user app_version, by start time — used
    so the top-of-page hero stat can show accuracy for the CURRENT
    version specifically, not blended across every version ever tested.
    """
    rows = _run_sql(f"""
        SELECT r.app_version
        FROM {TABLE_RUNS} r
        WHERE r.run_type IN ('bulk','repeat','user') AND r.app_version IS NOT NULL
        ORDER BY r.started_ts DESC LIMIT 1
    """)
    return rows[0]["app_version"] if rows else None


# =====================================================================
# User feedback (thumbs up / "Not quite" on the Ask Inventory360 page)
# Stored in the SAME tables as testing: run_type = 'user'. One rolling
# test_runs row per app_version holds every rating for that version.
# =====================================================================
def get_or_create_user_run(app_version: str) -> str:
    rows = _run_sql(f"""
        SELECT run_id FROM {TABLE_RUNS}
        WHERE run_type = 'user' AND app_version = {_escape(app_version)}
        ORDER BY started_ts DESC LIMIT 1
    """)
    if rows:
        return rows[0]["run_id"]
    run_id = create_run(
        run_type="user", label=f"User feedback {app_version}", app_version=app_version,
        source_detail="Thumbs feedback on Ask Inventory360 answers", total_questions=0, created_by="app_user",
    )
    complete_run(run_id)  # a rolling run has no "end"; mark complete so it behaves like any finished run
    return run_id


def record_user_feedback(
    run_id: str, question_text: str, answer_text: str, genie_keys_used: str, elapsed_seconds: float | None,
    status: str, genie_results_json: str, verdict: str, reason: str | None, reviewed_by: str,
) -> str:
    """One row per rated answer. human_verdict / reason / reviewer are written in the same INSERT (no 'Unreviewed' phase)."""
    result_id = new_id()
    cols = ["result_id", "run_id", "question_text", "answer_text", "genie_keys_used", "elapsed_seconds", "status",
            "genie_results_json", "human_verdict", "human_reason", "reviewed_by"]
    vals = [result_id, run_id, question_text, answer_text, genie_keys_used, elapsed_seconds, status,
            genie_results_json, verdict, reason, reviewed_by]
    _run_sql(f"""
        INSERT INTO {TABLE_RESULTS} ({', '.join(cols)}, reviewed_ts, created_ts)
        VALUES ({', '.join(_escape(v) for v in vals)}, current_timestamp(), current_timestamp())
    """)
    return result_id


TABLE_ASKED_QUESTIONS = "dsg.inventory360.asked_questions"


def ensure_asked_questions_table() -> None:
    _run_sql(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_ASKED_QUESTIONS} (
            question_id   STRING NOT NULL,
            question_text STRING NOT NULL,
            asked_by      STRING,
            asked_ts      TIMESTAMP NOT NULL
        ) USING DELTA
    """)


def log_asked_question(question_text: str, asked_by: str = "app_user") -> None:
    """One row per question typed or clicked on Ask Inventory360 — EVERY question, rated or not.
    Powers the 'Popular questions' rail. Called best-effort from chat_page.py; a failure here
    must never block the actual chat turn."""
    ensure_asked_questions_table()
    qid = new_id()
    _run_sql(f"""
        INSERT INTO {TABLE_ASKED_QUESTIONS} (question_id, question_text, asked_by, asked_ts)
        VALUES ({_escape(qid)}, {_escape(question_text)}, {_escape(asked_by)}, current_timestamp())
    """)


def top_questions(limit: int = 5) -> list[dict]:
    """Most frequently asked questions across ALL asks (dsg.inventory360.asked_questions),
    not just ones someone rated."""
    return _run_sql(f"""
        SELECT question_text, COUNT(*) AS ask_count
        FROM {TABLE_ASKED_QUESTIONS}
        GROUP BY question_text
        ORDER BY ask_count DESC, question_text
        LIMIT {int(limit)}
    """)


def human_eval_source_counts(app_version: str | None = None) -> dict:
    """How many of the evaluated (Pass/Fail) human-accuracy results came from testing vs. from users."""
    where = "WHERE t.human_verdict IN ('Pass','Fail') AND r.run_type IN ('bulk','repeat','user')"
    if app_version:
        where += f" AND r.app_version = {_escape(app_version)}"
    rows = _run_sql(f"""
        SELECT SUM(CASE WHEN r.run_type IN ('bulk','repeat') THEN 1 ELSE 0 END) AS tested,
               SUM(CASE WHEN r.run_type = 'user' THEN 1 ELSE 0 END) AS from_users
        FROM {TABLE_RESULTS} t JOIN {TABLE_RUNS} r ON t.run_id = r.run_id
        {where}
    """)
    return rows[0] if rows else {"tested": 0, "from_users": 0}
