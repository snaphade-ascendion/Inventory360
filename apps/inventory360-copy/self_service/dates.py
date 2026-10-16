"""
self_service/dates.py
=======================
Date-range presets for the Self-Service page and the scheduled run.
Presets are anchored to the latest date ALL metric views have data for
(pivot_engine.get_data_window()), not to today's date.
"""

import datetime as dt

PRESETS = ["Last 30 days", "Quarter to date", "Year to date", "Trailing 12 months"]
SCHEDULED_PRESET = "Last 30 days"  # the one window the Databricks Job stores


def resolve_range(preset: str, anchor_end: dt.date) -> tuple[dt.date, dt.date]:
    if preset == "Last 30 days":
        return anchor_end - dt.timedelta(days=29), anchor_end
    if preset == "Quarter to date":
        q_start_month = 3 * ((anchor_end.month - 1) // 3) + 1
        return dt.date(anchor_end.year, q_start_month, 1), anchor_end
    if preset == "Year to date":
        return dt.date(anchor_end.year, 1, 1), anchor_end
    if preset == "Trailing 12 months":
        try:
            start = anchor_end.replace(year=anchor_end.year - 1) + dt.timedelta(days=1)
        except ValueError:  # Feb 29
            start = anchor_end.replace(year=anchor_end.year - 1, day=28) + dt.timedelta(days=1)
        return start, anchor_end
    raise ValueError(f"Unknown preset: {preset}")


def format_date(d: dt.date) -> str:
    return d.strftime("%b %d, %Y").replace(" 0", " ")


def format_range(start: dt.date, end: dt.date) -> str:
    return f"{format_date(start)} – {format_date(end)}"


def prior_range(start: dt.date, end: dt.date) -> tuple[dt.date, dt.date]:
    """The equal-length window immediately before [start, end]."""
    length = (end - start).days + 1
    return start - dt.timedelta(days=length), start - dt.timedelta(days=1)
