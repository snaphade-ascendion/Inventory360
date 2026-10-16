"""
page_modules/testing_page.py
==============================
Moved out of Streamlit's magic pages/ folder into page_modules/ so the
app no longer gets Streamlit's automatic sidebar nav — nav is now the
horizontal top tabs built in app.py, which runs this file's top-level
code in place via runpy (unchanged logic, just no longer a standalone
Streamlit "page"). st.set_page_config()/inject_custom_css() were removed
from here — the shared app.py entrypoint calls them once for all tabs.

Three tabs, in this order:
  1. Reliability Report — the primary landing view. Human-evaluated
     accuracy (bulk+repeat) first and most prominent, then accuracy by
     app version, then by business-friendly subject area, then
     benchmark results, then confidence distribution across all types.
     Visually styled to match the mockup (cards, big stat numbers,
     horizontal bar visuals) via ui/theme.py.
  2. Benchmark   — question bank + run controls + per-run results.
  3. Bulk Test   — combined bulk CSV + repeat-question testing.

All actual logic lives in testing/db.py, testing/judge.py, and
testing/runner.py — this file is rendering + wiring only.
"""

import json

import streamlit as st

from ui.safe_html import esc

from genie.config import GENIE_SPACES
from testing import db
from testing.constants import APP_VERSION_DEFAULT, HUMAN_REASONS
from testing.runner import run_benchmark, run_bulk, run_repeat
from ui.show_work import render_business_summary, render_technical_details
from ui.theme import COLORS, inject_custom_css

st.title("Inventory360 — AI Accuracy")

tab_reliability, tab_benchmark, tab_bulk_test = st.tabs(["Reliability Report", "Benchmark", "Bulk Test"])


# =====================================================================
# Shared helpers (used across tabs)
# =====================================================================
def _run_with_progress(run_fn, *args, **kwargs):
    progress = st.progress(0.0, text="Starting…")

    def _cb(i, total, question_text):
        pct = i / max(total, 1)
        progress.progress(min(pct, 0.99), text=f"({i + 1}/{total}) {question_text[:80]}")

    run_id = run_fn(*args, progress_callback=_cb, **kwargs)
    progress.progress(1.0, text="Done.")
    return run_id


def _num(value, default: float = 0) -> float:
    """
    Databricks' Statement Execution API returns every column value as a
    string in the JSON response, regardless of the underlying SQL type
    (COUNT/SUM included) — so row values need explicit coercion before
    any arithmetic, or Python raises TypeError on str / str.
    """
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _pct(passed, total) -> float | None:
    return round((passed / total) * 100, 1) if total else None


def _subject_area_label(genie_keys_used: str | None) -> str:
    """Maps stored genie_key(s) to business-friendly display names — never shows a raw genie_key to the user."""
    if not genie_keys_used:
        return "General / No data lookup"
    keys = [k.strip() for k in genie_keys_used.split(",") if k.strip()]
    names = [GENIE_SPACES.get(k, {}).get("display_name", k) for k in keys]
    return " + ".join(names) if names else "General / No data lookup"


def _render_results_table(run_id: str, editable_human_review: bool):
    """Used by the Benchmark tab's 'Details' section."""
    results = db.list_results(run_id)
    if not results:
        st.info("No results yet.")
        return

    for r in results:
        with st.container(border=True):
            label = r["question_text"]
            if r.get("repeat_index"):
                label += f"  (run {r['repeat_index']})"
            st.markdown(f"**{label}**")
            st.markdown(r["answer_text"] or "_(no answer)_")

            cols = st.columns([1, 1, 1, 2])
            cols[0].markdown(f"Confidence: **{r.get('judge_confidence', '—')}**")
            cols[1].markdown(f"Elapsed: {r.get('elapsed_seconds', '—')}s")
            cols[2].markdown(f"Subject area: {_subject_area_label(r.get('genie_keys_used'))}")

            if r.get("benchmark_verdict") not in (None, "NA"):
                verdict_icon = "✅" if r["benchmark_verdict"] == "Pass" else "❌"
                cols[3].markdown(
                    f"Benchmark: {verdict_icon} **{r['benchmark_verdict']}** "
                    f"({r.get('benchmark_check_method', 'none')})"
                )
                if r.get("benchmark_extracted_value") is not None:
                    st.caption(
                        f"Extracted value: {r['benchmark_extracted_value']} · "
                        f"Numeric match: {r.get('benchmark_numeric_match')}"
                    )

            if editable_human_review:
                existing_verdict = r.get("human_verdict", "Unreviewed")
                vcols = st.columns([1, 2, 1])
                verdict = vcols[0].selectbox(
                    "Result", ["Unreviewed", "Pass", "Fail"],
                    index=["Unreviewed", "Pass", "Fail"].index(existing_verdict) if existing_verdict in ("Unreviewed", "Pass", "Fail") else 0,
                    key=f"verdict_{r['result_id']}",
                )
                reason = vcols[1].selectbox(
                    "Reason (if Fail)", HUMAN_REASONS, key=f"reason_{r['result_id']}",
                )
                if vcols[2].button("Save", key=f"save_{r['result_id']}"):
                    db.update_human_review(r["result_id"], verdict, reason or None)
                    st.rerun()


def _parse_genie_blob(raw: str | None) -> tuple[list, list, bool]:
    """Returns (genie_results, validations, is_old_format)."""
    if not raw:
        return [], [], False
    try:
        blob = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return [], [], False
    if isinstance(blob, dict):
        return blob.get("genie_results", []), blob.get("validations", []), False
    return [], [], True


def _render_test_question_row(r: dict, row_key_prefix: str, show_details: bool) -> None:
    result_id = r["result_id"]
    c1, c2, c3, c4 = st.columns([3, 1, 1.2, 1.8])

    label = r["question_text"]
    if r.get("repeat_index"):
        label += f"  (run {r['repeat_index']})"
    c1.markdown(label)
    c2.markdown(r.get("judge_confidence") or "—")

    verdict_key = f"{row_key_prefix}_verdict_{result_id}"
    reason_key = f"{row_key_prefix}_reason_{result_id}"
    existing_verdict = r.get("human_verdict", "Unreviewed")
    existing_reason = r.get("human_reason") or ""

    c3.selectbox(
        "Result", ["Unreviewed", "Pass", "Fail"],
        index=["Unreviewed", "Pass", "Fail"].index(existing_verdict) if existing_verdict in ("Unreviewed", "Pass", "Fail") else 0,
        key=verdict_key, label_visibility="collapsed",
    )
    c4.selectbox(
        "Reason", HUMAN_REASONS,
        index=HUMAN_REASONS.index(existing_reason) if existing_reason in HUMAN_REASONS else 0,
        key=reason_key, label_visibility="collapsed",
    )

    if show_details:
        genie_results, validations, is_old_format = _parse_genie_blob(r.get("genie_results_json"))
        with st.container(border=True):
            st.markdown(r["answer_text"] or "_(no answer)_")
            st.caption(
                f"Confidence reason: {r.get('judge_confidence_reason', '—')} · "
                f"Elapsed: {r.get('elapsed_seconds', '—')}s · Status: {r.get('status', '—')}"
            )
            if genie_results:
                render_business_summary(genie_results, validations)
                st.markdown("")
                render_technical_details(genie_results, validations, key_prefix=f"{row_key_prefix}_{result_id}")
            elif is_old_format:
                st.caption(
                    "_No detailed trace stored for this result — it was run before Show Work "
                    "data capture was added. Re-run this question to see the full trace._"
                )


def _render_test_batch(run: dict) -> None:
    run_id = run["run_id"]
    results = db.list_results(run_id)
    reviewed = sum(1 for r in results if r.get("human_verdict") in ("Pass", "Fail"))
    label = run.get("label") or f"{run.get('run_type', 'Run').title()} {run.get('started_ts', '')}"
    type_badge = "🔁 Repeat" if run.get("run_type") == "repeat" else "📋 Bulk"

    with st.expander(f"{type_badge} — {label}  —  {len(results)} question(s), {reviewed} reviewed"):
        if not results:
            st.info("No results in this batch.")
            return

        show_details = st.toggle("Show details for all questions", key=f"show_all_{run_id}")

        h1, h2, h3, h4 = st.columns([3, 1, 1.2, 1.8])
        h1.markdown("**Question**")
        h2.markdown("**Confidence**")
        h3.markdown("**Result**")
        h4.markdown("**Reason**")

        for i, r in enumerate(results):
            _render_test_question_row(r, row_key_prefix=f"batch_{run_id}", show_details=show_details)
            if i < len(results) - 1:
                st.divider()

        if st.button("💾 Save all responses", key=f"save_all_{run_id}"):
            for r in results:
                verdict = st.session_state.get(f"batch_{run_id}_verdict_{r['result_id']}", r.get("human_verdict", "Unreviewed"))
                reason = st.session_state.get(f"batch_{run_id}_reason_{r['result_id']}", "") or None
                db.update_human_review(r["result_id"], verdict, reason)
            st.success("Saved.")
            st.rerun()


# =====================================================================
# Reliability Report — visual helpers
# =====================================================================
def _section_header(title: str) -> None:
    st.markdown(
        f'<div style="font-size:17px; font-weight:700; margin-bottom:10px;">{title}</div>',
        unsafe_allow_html=True,
    )


def _hero_stat(value_str: str, label: str, sublabel: str, color: str) -> None:
    st.markdown(
        f'''
        <div style="text-align:center; padding: 6px 0 2px;">
          <div style="font-size:46px; font-weight:800; color:{color}; line-height:1.1;">{value_str}</div>
          <div style="font-size:14.5px; font-weight:700; color:{COLORS['text']}; margin-top:6px;">{label}</div>
          <div style="font-size:12.5px; color:{COLORS['text_muted']}; margin-top:2px;">{sublabel}</div>
        </div>
        ''',
        unsafe_allow_html=True,
    )


def _stat_tile(value_str: str, sublabel: str, color: str) -> None:
    """Smaller sibling of _hero_stat, for side-by-side tiles rather than the top-of-page hero number."""
    st.markdown(
        f'''
        <div style="text-align:center; padding: 4px 0 2px;">
          <div style="font-size:32px; font-weight:800; color:{color}; line-height:1.1;">{value_str}</div>
          <div style="font-size:12px; color:{COLORS['text_muted']}; margin-top:4px;">{sublabel}</div>
        </div>
        ''',
        unsafe_allow_html=True,
    )


def _bar_row(label: str, pct_value: float | None, count_text: str, color: str) -> None:
    pct_display = 0 if pct_value is None else pct_value
    pct_text = "—" if pct_value is None else f"{pct_value}%"
    st.markdown(
        f'''
        <div style="margin-bottom:12px;">
          <div style="display:flex; justify-content:space-between; font-size:13.5px; margin-bottom:4px;">
            <span style="font-weight:600; color:{COLORS['text']};">{esc(label)}</span>
            <span style="color:{COLORS['text_muted']};">{esc(pct_text)} ({esc(count_text)})</span>
          </div>
          <div style="background:{COLORS['border']}; border-radius:6px; height:9px; overflow:hidden;">
            <div style="background:{color}; width:{pct_display}%; height:100%; border-radius:6px;"></div>
          </div>
        </div>
        ''',
        unsafe_allow_html=True,
    )


CONFIDENCE_COLORS = {"High": COLORS["green"], "Medium": COLORS["gold"], "Low": COLORS["red"]}


# =====================================================================
# TAB 1 — Reliability Report
# =====================================================================
with tab_reliability:
    latest_version = db.latest_human_eval_version()
    latest_summary = db.human_eval_accuracy_summary(app_version=latest_version) if latest_version else {"total": 0, "passed": 0}

    latest_total = int(_num(latest_summary.get("total")))
    latest_passed = int(_num(latest_summary.get("passed")))
    latest_pct = _pct(latest_passed, latest_total)

    version_label = f" — {latest_version} (latest)" if latest_version else ""
    _section_header(f"Human-Evaluated Accuracy{version_label}")
    st.caption("Bulk and Repeat testing plus user ratings from Ask Inventory360, all reviewed by a person — the primary reliability signal. Benchmark runs are scored separately.")

    # --- 4 tiles, one row: pass rate · questions evaluated · by version · by subject area ---
    col_rate, col_count, col_version, col_subject = st.columns(4)

    with col_rate:
        with st.expander("Pass Rate", expanded=True):
            _stat_tile(
                value_str=f"{latest_pct}%" if latest_pct is not None else "—",
                sublabel=f"{latest_passed} passed / {latest_total - latest_passed} failed" if latest_total else "No results yet",
                color=COLORS["accent"],
            )
            if latest_total:
                source = db.human_eval_source_counts(latest_version)
                st.caption(f"{int(_num(source.get('tested')))} tested · {int(_num(source.get('from_users')))} from users")

    with col_count:
        with st.expander("Questions Evaluated", expanded=True):
            _stat_tile(
                value_str=str(latest_total),
                sublabel=f"for {latest_version}" if latest_version else "no version tested yet",
                color=COLORS["accent"],
            )

    with col_version:
        with st.expander("By App Version", expanded=True):
            version_rows = db.accuracy_by_version()
            if version_rows:
                for row in version_rows:
                    evaluated = int(_num(row.get("evaluated")))
                    passed = int(_num(row.get("passed")))
                    pct = _pct(passed, evaluated)
                    _bar_row(row.get("app_version") or "—", pct, f"{passed}/{evaluated}", COLORS["accent"])
            else:
                st.caption("No evaluated results yet.")

    with col_subject:
        with st.expander("By Subject Area", expanded=True):
            genie_rows = db.accuracy_by_genie()
            if genie_rows:
                for row in genie_rows:
                    evaluated = int(_num(row.get("evaluated")))
                    passed = int(_num(row.get("passed")))
                    pct = _pct(passed, evaluated)
                    _bar_row(_subject_area_label(row.get("genie_keys_used")), pct, f"{passed}/{evaluated}", COLORS["accent"])
            else:
                st.caption("No evaluated results yet.")

    # --- Confidence distribution (all types) ---
    with st.expander("Confidence Distribution (LLM as a judge)", expanded=True):
        st.caption("Across all runs — benchmark, bulk, and repeat.")
        conf_rows = db.confidence_distribution()
        if conf_rows:
            conf_total = sum(int(_num(row.get("cnt"))) for row in conf_rows)
            conf_by_label = {row["judge_confidence"]: int(_num(row.get("cnt"))) for row in conf_rows}
            for level in ["High", "Medium", "Low"]:
                count = conf_by_label.get(level, 0)
                pct = _pct(count, conf_total)
                _bar_row(level, pct, f"{count} result(s)", CONFIDENCE_COLORS[level])
        else:
            st.caption("No results yet.")


# =====================================================================
# TAB 2 — Benchmark
# =====================================================================
with tab_benchmark:
    app_version = APP_VERSION_DEFAULT
    st.markdown(f"App version: {app_version}")

    with st.expander("Question bank"):
        questions = db.list_questions(active_only=True)
        st.caption(f"{len(questions)} active question(s)")
        for q in questions:
            st.markdown(f"- **{q['question_text']}** — expected: {q.get('expected_value', '—')} (±{q.get('expected_value_tolerance_pct', '—')}%)")
        st.caption("Question bank is managed outside the app (e.g. testing/seed_benchmark_questions.py) — not editable here.")

    if st.button("▶ Run full benchmark", type="primary"):
        run_id = _run_with_progress(run_benchmark, app_version=app_version, label=f"Benchmark {app_version}")
        st.session_state["last_benchmark_run_id"] = run_id

    display_run_id = st.session_state.get("last_benchmark_run_id")
    display_run_meta = None
    if display_run_id is None:
        latest = db.latest_run("benchmark")
        if latest:
            display_run_id = latest["run_id"]
            display_run_meta = latest

    if display_run_id:
        if display_run_meta:
            st.caption(
                f"Showing latest benchmark run — app version **{display_run_meta.get('app_version', '—')}**, "
                f"run on {display_run_meta.get('started_ts', '—')}"
            )

        bench_results = db.list_results(display_run_id)
        scored = [r for r in bench_results if r.get("benchmark_verdict") in ("Pass", "Fail")]
        passed_count = sum(1 for r in scored if r["benchmark_verdict"] == "Pass")
        failed_count = len(scored) - passed_count
        pass_pct = round((passed_count / len(scored)) * 100, 1) if scored else None

        st.markdown("### Run summary")
        s1, s2, s3 = st.columns(3)
        s1.metric("Passed", passed_count)
        s2.metric("Failed", failed_count)
        s3.metric("Pass rate", f"{pass_pct}%" if pass_pct is not None else "—")

        st.markdown("### Results")
        st.dataframe(
            [{"Question": r["question_text"], "Result": r.get("benchmark_verdict") or "—"} for r in bench_results],
            hide_index=True,
            use_container_width=True,
        )

        st.markdown("### Details")
        _render_results_table(display_run_id, editable_human_review=False)


# =====================================================================
# TAB 3 — Bulk Test (Bulk CSV + Repeat, combined)
# =====================================================================
with tab_bulk_test:
    st.markdown("## Bulk Questions (CSV)")
    app_version_bulk = APP_VERSION_DEFAULT
    st.markdown(f"App version: {app_version_bulk}")
    batch_name = st.text_input("Batch name (optional)", key="bulk_batch_name", placeholder="e.g. Sept 24 smoke test")
    uploaded = st.file_uploader("Upload CSV (one question per row, max 30)", type=["csv"], key="bulk_csv")

    bulk_questions = []
    if uploaded is not None:
        import csv, io
        content = uploaded.getvalue().decode("utf-8")
        reader = csv.reader(io.StringIO(content))
        bulk_questions = [row[0].strip() for row in reader if row and row[0].strip()]

    if len(bulk_questions) > 30:
        st.warning(f"{len(bulk_questions)} questions found — capping to the first 30 for performance.")
        bulk_questions = bulk_questions[:30]
    elif bulk_questions:
        st.caption(f"{len(bulk_questions)} question(s) ready to run.")

    if st.button("▶ Run bulk set", type="primary", disabled=not bulk_questions):
        label = batch_name.strip() or f"Bulk {app_version_bulk}"
        _run_with_progress(run_bulk, questions=bulk_questions, app_version=app_version_bulk, label=label)

    st.divider()

    st.markdown("## Repeat a Single Question")
    app_version_repeat = APP_VERSION_DEFAULT
    st.markdown(f"App version: {app_version_repeat}")
    repeat_batch_name = st.text_input("Batch name (optional)", key="repeat_batch_name", placeholder="e.g. Consistency check")
    repeat_question = st.text_input("Question to repeat", key="repeat_question_text")
    repeat_n = st.number_input("Number of times to repeat", min_value=2, max_value=20, value=5, key="repeat_n")

    if st.button("▶ Run repeat set", type="primary", disabled=not repeat_question.strip()):
        label = repeat_batch_name.strip() or f"Repeat {app_version_repeat}"
        _run_with_progress(
            run_repeat, question=repeat_question.strip(), n=int(repeat_n),
            app_version=app_version_repeat, label=label,
        )

    st.divider()

    st.markdown("## Batches")
    all_runs = db.list_runs(run_type="bulk") + db.list_runs(run_type="repeat")
    all_runs.sort(key=lambda r: r.get("started_ts") or "", reverse=True)
    if not all_runs:
        st.info("No batches yet.")
    for run in all_runs:
        _render_test_batch(run)