"""
self_service/run_themes.py
============================
Orchestration for the Self-Service theme insights. Two callers, one code path:

  1. Databricks Job on a schedule:  python self_service/run_themes.py
     -> stores ONE window: SCHEDULED_PRESET (dates.py, default "Last 30 days")
        ending at the latest date that ALL date-bearing metric views have
        data for (pivot_engine.get_data_window), clipped to the earliest date
        they all share. trigger="scheduled".
  2. The page's "Generate insights" button -> run_all_themes(start, end) for
     whatever range the user selected, then SAVED as trigger='manual' (the page
     does the saving) so the result survives a dropped browser session.
     The page shows the most recent run, whichever trigger made it.

Paced like insights/run_agents.py so 8 back-to-back LLM calls don't burst the
shared serving endpoint.
"""

import datetime as dt
import os
import sys
import time

# Allow `python self_service/run_themes.py` (Databricks Job) as well as imports from the app.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from self_service import db
from self_service.dates import SCHEDULED_PRESET, resolve_range, format_range
from self_service.pivot_engine import get_data_window
from self_service.theme_agent import run_theme
from self_service.themes import THEMES

LLM_CALL_PACING_SECONDS = 3


def run_all_themes(start: dt.date, end: dt.date, progress_cb=None) -> list[dict]:
    """progress_cb(done, total, theme_name) is called before each theme starts (and once at the end)."""
    results = []
    for i, theme in enumerate(THEMES):
        if progress_cb:
            progress_cb(i, len(THEMES), theme["name"])
        results.append(run_theme(theme, start, end))
        if i < len(THEMES) - 1:
            time.sleep(LLM_CALL_PACING_SECONDS)
    if progress_cb:
        progress_cb(len(THEMES), len(THEMES), "")
    return results


def scheduled_window() -> tuple[dt.date, dt.date, str]:
    window = get_data_window()
    start, end = resolve_range(SCHEDULED_PRESET, window["common_end"])
    start = max(start, window["common_start"]) if window["overlap"] else start
    return start, end, SCHEDULED_PRESET


def run_and_store_scheduled() -> dict:
    start, end, preset = scheduled_window()
    themes = run_all_themes(start, end)
    db.ensure_table()
    run_id = db.save_run("scheduled", start, end, f"{preset} ({format_range(start, end)})", themes)
    return {"run_id": run_id, "start": start, "end": end, "themes": themes}


if __name__ == "__main__":
    out = run_and_store_scheduled()
    failed = [t["name"] for t in out["themes"] if t.get("error")]
    print(f"Self-Service theme run complete: {out['run_id']} "
          f"({format_range(out['start'], out['end'])}); {len(out['themes']) - len(failed)}/{len(out['themes'])} themes OK"
          + (f"; failed: {failed}" if failed else ""))
