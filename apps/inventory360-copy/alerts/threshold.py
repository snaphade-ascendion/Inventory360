"""
alerts/threshold.py
=====================
Parses a threshold entered as text ("70%", "350K", "$1.2M", "95") into a
plain float on the display scale (see constants.py note 4). Shared by the
manual form and by validating whatever number the NL parser returns.
"""

import re

_SUFFIXES = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}


def parse_threshold(raw) -> float:
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().upper().replace(",", "").replace("$", "").replace("%", "")
    if not text:
        raise ValueError("Enter a threshold value.")
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)([KMB]?)", text)
    if not m:
        raise ValueError(f"Couldn't read '{raw}' as a number.")
    value, suffix = m.groups()
    return float(value) * _SUFFIXES.get(suffix, 1)


def format_threshold(value: float, is_percent: bool) -> str:
    if is_percent:
        return f"{value:g}%"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:g}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:g}K"
    return f"{value:g}"
