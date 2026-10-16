"""
alerts/catalog.py
===================
Alertable metrics = exactly the 10 cards on the Overview page (imported
from insights/metric_registry.py:OVERVIEW_CARDS, so this can never drift
out of sync with what Overview actually shows).

Alertable dimensions = a FIXED set of 5, chosen so every one of the 10
metrics has at least one usable filter: Region, Facility, Category,
Product Class, Exception Priority. All 5 are always shown; a dimension is
disabled ("greyed out") when the selected metric's view doesn't have that
column — see alert_dimensions_status().

Week / Month are not in this set: they're not a fixed value to filter an
alert by (see alerts/constants.py).
"""

from insights.metric_registry import OVERVIEW_CARDS
from self_service.catalog import DIMENSIONS, MEASURES, dim_column, measure_key

_MEASURE_BY_KEY = {m["key"]: m for m in MEASURES}
ALERT_MEASURES = [_MEASURE_BY_KEY[measure_key(card["table"], card["measure"])] for card in OVERVIEW_CARDS]
_BY_KEY = {m["key"]: m for m in ALERT_MEASURES}

# Two of the 10 share a table (On-Time Ship Rate / Ship-from-Store Rate both come from Order
# Orchestration), but their labels don't collide, so no disambiguation suffix is ever needed here.
DISPLAY_LABEL = {m["key"]: m["label"] for m in ALERT_MEASURES}

ALERT_DIMENSION_KEYS = ["region", "facility", "category", "class", "exc_priority"]
_DIM_BY_KEY = {d["key"]: d for d in DIMENSIONS}
ALERT_DIMENSIONS = [_DIM_BY_KEY[k] for k in ALERT_DIMENSION_KEYS]


def get_measure(key: str) -> dict:
    return _BY_KEY[key]


def alert_dimensions_status(metric_key: str) -> dict:
    """{dim_key: True/False} — whether the metric's own view has that dimension column."""
    table = _BY_KEY[metric_key]["table"]
    return {d["key"]: bool(dim_column(d["key"], table)) for d in ALERT_DIMENSIONS}


def dimension_column_in_view(dim_key: str, metric_key: str) -> str | None:
    return dim_column(dim_key, _BY_KEY[metric_key]["table"])
