"""
alerts/dimension_values.py
============================
Distinct values for one of the 5 alertable dimensions, scoped to the
SPECIFIC metric's own view (not unioned across every view that happens to
have that dimension) — every dropdown always has a chosen metric as
context now, so this is simpler and more accurate than querying broadly:
a value can only ever come from the exact table the alert will actually
filter.
"""

from sql_client import run_sql
from alerts.catalog import dimension_column_in_view, get_measure
from self_service.catalog import qualified


def get_dimension_values(dim_key: str, metric_key: str) -> list[str]:
    table = get_measure(metric_key)["table"]
    col = dimension_column_in_view(dim_key, metric_key)
    if not col:
        return []
    result = run_sql(f"SELECT DISTINCT {col} AS v FROM {qualified(table)} WHERE {col} IS NOT NULL")
    if result["status"] != "success":
        return []
    return sorted({str(r["v"]) for r in result["rows"] if r.get("v") is not None})
