"""
testing/seed_benchmark_questions.py
=====================================
One-time (or re-run-anytime) script to seed 6 starter benchmark questions
(5 single-Genie, 1 multi-Genie). For each question, this:

  1. Runs a direct SQL query against the real data to get the CURRENT
     correct answer (not a guessed/recalled number).
  2. Uses that measured value as expected_value, with a small tolerance
     (3%) since it's now a known ground truth, not an estimate.
  3. Inserts the question into test_questions via testing.db.add_question().

Run this from a notebook (same pattern as your earlier Step 1-5 tests),
with the app folder on sys.path.

Safe to re-run: each run adds 6 NEW question rows (doesn't check for
duplicates) — if you re-run this after data has changed, you'll get a
fresh, up-to-date set. Deactivate old ones with db.deactivate_question()
if you don't want duplicates in your active bank.
"""

from sql_client import run_sql
from testing import db

QUESTIONS = [
    {
        "question_text": "What is our sell-through improvement this year compared to last year?",
        "verify_sql": "SELECT sell_through_improvement_pct AS value FROM dsg.inventory360.kpi_sell_through_summary WHERE period_type = 'TY'",
        "category": "merchandising_po",
        "tolerance_pct": 2.0,
    },
    {
        "question_text": "What is our on-time ship rate?",
        "verify_sql": "SELECT ROUND(AVG(CASE WHEN on_time_flag = 'Y' THEN 100.0 ELSE 0 END), 1) AS value FROM dsg.inventory360.fact_order_line",
        "category": "order_orchestration",
        "tolerance_pct": 3.0,
    },
    {
        "question_text": "What is our average size-curve fill rate for footwear?",
        "verify_sql": "SELECT ROUND(AVG(size_curve_actual_pct), 1) AS value FROM dsg.inventory360.fact_allocation",
        "category": "allocation",
        "tolerance_pct": 3.0,
    },
    {
        "question_text": "What is our average store inventory accuracy?",
        "verify_sql": "SELECT ROUND(AVG(inventory_accuracy_pct) * 100, 1) AS value FROM dsg.inventory360.inv_accuracy_daily",
        "category": "store_operations",
        "tolerance_pct": 3.0,
    },
    {
        "question_text": "What share of our sellable inventory is 90+ days aged?",
        "verify_sql": """
            SELECT ROUND(
                SUM(CASE WHEN aged_days_bucket = '90+' THEN on_hand_qty ELSE 0 END) / SUM(on_hand_qty) * 100, 1
            ) AS value
            FROM dsg.inventory360.fact_inventory_snapshot
            WHERE disposition_code = 'SELLABLE'
        """,
        "category": "inventory_visibility",
        "tolerance_pct": 5.0,
    },
    {
        # MULTI-GENIE: requires order_orchestration (oversell count) AND
        # allocation (stockout-flagged count), summed into one number —
        # exercises the router's loop-back-after-first-Genie-result path,
        # not just single-Genie routing like the 5 questions above.
        "question_text": "What is the combined total of oversold order lines and stockout-flagged allocation reviews?",
        "verify_sql": """
            SELECT
              (SELECT COUNT(*) FROM dsg.inventory360.fact_order_line WHERE oversell_flag = 'Y')
              +
              (SELECT COUNT(*) FROM dsg.inventory360.fact_allocation WHERE stockout_flag = 'Y')
              AS value
        """,
        "category": "multi_genie",
        "tolerance_pct": 10.0,  # looser — compound metric, more room for aggregation nuance
    },
]

print(f"{'Question':<65} {'Measured value':>15}")
print("-" * 82)

for q in QUESTIONS:
    result = run_sql(q["verify_sql"])
    if result["status"] != "success" or not result["rows"]:
        print(f"FAILED to measure: {q['question_text']!r} -> {result.get('error')}")
        continue

    measured_value = float(result["rows"][0]["value"])
    print(f"{q['question_text']:<65} {measured_value:>15}")

    qid = db.add_question(
        question_text=q["question_text"],
        expected_value=measured_value,
        expected_value_tolerance_pct=q["tolerance_pct"],
        category=q["category"],
    )
    print(f"  -> added as question_id={qid}")

print("\nDone. Check the Benchmark tab's Question bank expander to confirm all 6 appear.")