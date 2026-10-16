"""
alerts/db.py
=============
Writes ONE row to dsg.notifications.alert_audit per alert created.

metric_name holds the display label; metric_name_details holds the
qualified "<view>.<column>" key (see alerts/constants.py). notification_
channel is a new column the person is adding themselves.
"""

from sql_client import run_app_sql as run_sql  # app-owned audit table: service principal, not OBO
from alerts.constants import CHANNEL_COLUMN, DIMENSION_COLUMN, METRIC_DETAILS_COLUMN, TABLE, OPERATOR_COLUMN


def _escape(value) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


def _run(statement: str) -> None:
    result = run_sql(statement)
    if result["status"] != "success":
        raise RuntimeError(f"SQL failed: {result['error']}\nStatement: {statement}")


def insert_alert(
    metric_label: str, metric_key: str, operator: str, threshold_value: float, frequency: str,
    channel: str, dimension_filters: dict, user_name: str, user_email: str,
) -> None:
    """dimension_filters: {catalog dim key -> chosen value}, only for dims the alert filters on."""
    cols = ["user_name", "user_email", "metric_name", METRIC_DETAILS_COLUMN, "threshold_value",
            OPERATOR_COLUMN, CHANNEL_COLUMN, "frequency"]
    vals = [user_name, user_email, metric_label, metric_key, threshold_value, operator, channel, frequency]
    for dim_key, value in dimension_filters.items():
        if value is None:
            continue
        cols.append(DIMENSION_COLUMN[dim_key])
        vals.append(value)
    _run(f"""
        INSERT INTO {TABLE} ({', '.join(cols)}, created_date)
        VALUES ({', '.join(_escape(v) for v in vals)}, current_date())
    """)
