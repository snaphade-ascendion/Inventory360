"""
alerts/constants.py
=====================
Single place for every value the alert-setup screen and its future job
need to agree on.

DIMENSION_COLUMN maps the 5 fixed alertable dimensions (alerts/catalog.py)
to their column on dsg.notifications.alert_audit: region, facility,
category, product_class, exception_priority. Whichever of the 5 a person
actually filters by gets that column filled in; the rest are left out of
the INSERT entirely (NULL) — not filtering by a dimension IS a person
simply leaving it on "All", nothing gets written for it.

Two things the job still needs to know, since its read side hasn't been
reviewed here:
1. THRESHOLD SCALE: threshold_value is stored in the same scale shown on
   screen (95 for "95%", not 0.95; 350000, not "350K").
2. metric_name holds the human-readable display label (e.g. "Avg
   Size-Curve Fill Rate"); METRIC_DETAILS_COLUMN holds the fully-qualified
   "<metric_view>.<measure column>" key (e.g.
   "mv_allocation_replenishment.avg_size_curve_fill_pct") for the job to
   resolve unambiguously — several measures share a display label across
   views (e.g. "On-Hand Units"), so the job should key off
   metric_name_details, not metric_name.

There is no separate user_id column — user_email is the identifier, and
user_name is a best-effort label derived from the email's local part
(ui/identity.py), not verified directory data.
"""

TABLE = "dsg.notifications.alert_audit"
OPERATOR_COLUMN = "alert_operator"
METRIC_DETAILS_COLUMN = "metric_name_details"  # the qualified key, e.g. mv_inventory_visibility.avg_cycle_count_variance_pct
CHANNEL_COLUMN = "notification_channel"  # new — person will add this column themselves

OPERATORS = [("above", "Goes above"), ("below", "Drops below"), ("equal", "Equals")]
FREQUENCIES = [("daily", "Daily"), ("weekly", "Weekly"), ("monthly", "Monthly")]
CHANNELS = [("email", "Email"), ("teams", "Teams")]

DIMENSION_COLUMN = {
    "region": "region",
    "facility": "facility",
    "category": "category",
    "class": "product_class",
    "exc_priority": "exception_priority",
}

NO_FILTER_LABEL = "All"
