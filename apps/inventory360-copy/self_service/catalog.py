"""
self_service/catalog.py
=========================
Single source of truth for the Self-Service page: which dimensions and
measures exist, which metric view each one lives in, and how to format
each measure. Hand-built from the DDLs in the project's mv_*.txt files
(filename = metric view name). One combined list is shown to the user;
the compatibility rules in pivot_engine.py decide what can be combined.

Adding a dimension or measure later = one entry here, nothing else.

Measure "kind" (display formatting):
  pct1 / pct2 -> percentage (stored internally as a 0-1 fraction)
  int         -> whole number      num1 / num2 -> 1 / 2 decimals
  cur0 / cur2 -> USD, 0 / 2 decimals
"""

CATALOG_SCHEMA = "dsg.inventory360"

# ---------------------------------------------------------------------
# Metric views
#   area      : label shown next to measures
#   date_col  : the view's own date dimension (None = no date dimension)
#   snapshot  : True if the fact is a stock snapshot (summing it across
#               dates is meaningless -> engine uses the latest snapshot
#               in the selected range unless a time dimension is a row)
#   note      : caveat shown when a measure from this view is selected
# ---------------------------------------------------------------------
VIEWS = {
    "mv_inventory_visibility": {
        "area": "Inventory Visibility", "date_col": "snapshot_date", "snapshot": True,
        "note": None,
    },
    "mv_order_orchestration": {
        "area": "Order Orchestration", "date_col": "order_date", "snapshot": False,
        "note": "Region and Store/Facility in Order Orchestration mean the SOURCING node that fulfilled the order.",
    },
    "mv_allocation_replenishment": {
        "area": "Allocation & Replenishment", "date_col": "review_date", "snapshot": False,
        "note": None,
    },
    "mv_store_operations": {
        "area": "Store Operations", "date_col": "activity_date", "snapshot": False,
        "note": None,
    },
    "mv_store_product_inventory": {
        "area": "Store Product Inventory", "date_col": None, "snapshot": False,
        "note": None,
    },
    "mv_merchandising_planning": {
        "area": "Merchandising Planning", "date_col": None, "snapshot": False,
        "note": "Merchandising measures combine This Year and Last Year rows unless 'Period (TY/LY)' is added as a row.",
    },
    "mv_po_transactions": {
        "area": "PO Sales & Forecast", "date_col": "calendar_date", "snapshot": False,
        "note": "PO Sales & Forecast uses MOCKED source data.",
    },
    "mv_po_allocations": {
        "area": "PO Allocations", "date_col": "calendar_date", "snapshot": False,
        "note": "PO Allocations uses MOCKED source data. 'Region' here is the DESTINATION store region.",
    },
}

# ---------------------------------------------------------------------
# Dimensions. cols: {metric_view: column name in that view}
# Time dimensions (week/month) are special: they map every view that has
# a date_col automatically (see pivot_engine.TIME_DIMS).
# ---------------------------------------------------------------------
TIME_DIM_KEYS = ("week", "month")

DIMENSIONS = [
    # ---- Time ----
    {"key": "week", "label": "Week", "group": "Time", "cols": {}},
    {"key": "month", "label": "Month", "group": "Time", "cols": {}},
    # ---- Location ----
    {"key": "region", "label": "Region", "group": "Location", "cols": {
        "mv_inventory_visibility": "region", "mv_order_orchestration": "region",
        "mv_allocation_replenishment": "region", "mv_store_operations": "region",
        "mv_store_product_inventory": "region", "mv_po_transactions": "region",
        "mv_po_allocations": "store_region"}},
    {"key": "facility", "label": "Store / Facility", "group": "Location", "cols": {
        "mv_inventory_visibility": "facility_name", "mv_order_orchestration": "facility_name",
        "mv_allocation_replenishment": "facility_name", "mv_store_operations": "facility_name",
        "mv_store_product_inventory": "facility_name", "mv_po_transactions": "facility_name",
        "mv_po_allocations": "store_name"}},
    {"key": "facility_type", "label": "Facility Type", "group": "Location", "cols": {
        "mv_inventory_visibility": "facility_type", "mv_order_orchestration": "facility_type"}},
    {"key": "dc", "label": "Distribution Center", "group": "Location", "cols": {
        "mv_po_allocations": "dc_name"}},
    # ---- Product ----
    {"key": "category", "label": "Style Category", "group": "Product", "cols": {
        "mv_inventory_visibility": "category", "mv_order_orchestration": "category",
        "mv_allocation_replenishment": "category", "mv_store_product_inventory": "category"}},
    {"key": "category_group", "label": "Category Group", "group": "Product", "cols": {
        "mv_inventory_visibility": "category_group", "mv_order_orchestration": "category_group",
        "mv_allocation_replenishment": "category_group", "mv_store_product_inventory": "category_group"}},
    {"key": "brand", "label": "Brand", "group": "Product", "cols": {
        "mv_inventory_visibility": "brand", "mv_allocation_replenishment": "brand",
        "mv_store_product_inventory": "brand"}},
    {"key": "style_number", "label": "Style Number", "group": "Product", "cols": {
        "mv_merchandising_planning": "style_number", "mv_po_transactions": "style_number",
        "mv_po_allocations": "style_number"}},
    {"key": "department", "label": "Department", "group": "Product", "cols": {
        "mv_merchandising_planning": "department"}},
    {"key": "program", "label": "Product Program", "group": "Product", "cols": {
        "mv_merchandising_planning": "product_program"}},
    {"key": "class", "label": "Product Class", "group": "Product", "cols": {
        "mv_merchandising_planning": "product_class"}},
    # ---- Channel & Vendor ----
    {"key": "channel", "label": "Channel", "group": "Channel & Vendor", "cols": {
        "mv_order_orchestration": "channel_name"}},
    {"key": "channel_group", "label": "Channel Group", "group": "Channel & Vendor", "cols": {
        "mv_order_orchestration": "channel_group"}},
    {"key": "vendor", "label": "Vendor", "group": "Channel & Vendor", "cols": {
        "mv_allocation_replenishment": "vendor_name"}},
    # ---- Status & Flags ----
    {"key": "disposition", "label": "Disposition", "group": "Status & Flags", "cols": {
        "mv_inventory_visibility": "disposition_code"}},
    {"key": "aged_bucket", "label": "Aged Days Bucket", "group": "Status & Flags", "cols": {
        "mv_inventory_visibility": "aged_days_bucket"}},
    {"key": "inv_status", "label": "Inventory Status", "group": "Status & Flags", "cols": {
        "mv_store_product_inventory": "inventory_status"}},
    {"key": "f_sfs", "label": "Ship-from-Store?", "group": "Status & Flags", "cols": {
        "mv_order_orchestration": "ship_from_store_flag"}},
    {"key": "f_ontime", "label": "On-Time?", "group": "Status & Flags", "cols": {
        "mv_order_orchestration": "on_time_flag"}},
    {"key": "f_split", "label": "Split Shipment?", "group": "Status & Flags", "cols": {
        "mv_order_orchestration": "split_shipment_flag"}},
    {"key": "f_oversell", "label": "Oversell?", "group": "Status & Flags", "cols": {
        "mv_order_orchestration": "oversell_flag"}},
    {"key": "f_replen", "label": "Replenishment Triggered?", "group": "Status & Flags", "cols": {
        "mv_allocation_replenishment": "replen_trigger_flag"}},
    {"key": "f_stockout", "label": "Stockout-Flagged?", "group": "Status & Flags", "cols": {
        "mv_allocation_replenishment": "stockout_flag"}},
    {"key": "exc_priority", "label": "Exception Priority", "group": "Status & Flags", "cols": {
        "mv_merchandising_planning": "exception_priority"}},
    # ---- Planning periods ----
    {"key": "period_type", "label": "Period (TY/LY)", "group": "Planning Period", "cols": {
        "mv_merchandising_planning": "period_type"}},
    {"key": "fiscal_period", "label": "Fiscal Period", "group": "Planning Period", "cols": {
        "mv_po_transactions": "fiscal_period"}},
]

# ---------------------------------------------------------------------
# Measures: (metric_view, measure name in the DDL, display label, kind)
# Deliberately left out: mv_po_transactions total_on_hand_units /
# total_on_order_units — they are stock measures that would be summed
# across every day in the range (meaningless), unlike the weekly
# snapshot view which the engine handles explicitly.
# ---------------------------------------------------------------------
_MEASURE_ROWS = [
    # Inventory Visibility
    ("mv_inventory_visibility", "on_hand_units", "On-Hand Units", "int"),
    ("mv_inventory_visibility", "sellable_on_hand_units", "Sellable On-Hand Units", "int"),
    ("mv_inventory_visibility", "available_to_commerce_units", "Available-to-Commerce Units", "int"),
    ("mv_inventory_visibility", "soft_allocation_shrinkage_pct", "Soft-Allocation Shrinkage %", "pct1"),
    ("mv_inventory_visibility", "aged_90plus_unit_share_pct", "Aged 90+ Day Unit Share %", "pct1"),
    ("mv_inventory_visibility", "avg_cycle_count_variance_pct", "Avg Cycle Count Variance %", "pct1"),
    # Order Orchestration
    ("mv_order_orchestration", "order_line_count", "Order Line Count", "int"),
    ("mv_order_orchestration", "total_units", "Total Units Ordered", "int"),
    ("mv_order_orchestration", "total_revenue", "Total Revenue", "cur0"),
    ("mv_order_orchestration", "on_time_ship_rate_pct", "On-Time Ship Rate", "pct1"),
    ("mv_order_orchestration", "ship_from_store_rate_pct", "Ship-from-Store Rate", "pct1"),
    ("mv_order_orchestration", "split_shipment_rate_pct", "Split Shipment Rate", "pct1"),
    ("mv_order_orchestration", "oversell_rate_pct", "Oversell Rate", "pct2"),
    ("mv_order_orchestration", "avg_sourcing_cost", "Avg Sourcing Cost per Line", "cur2"),
    # Allocation & Replenishment
    ("mv_allocation_replenishment", "avg_size_curve_fill_pct", "Avg Size-Curve Fill Rate", "pct1"),
    ("mv_allocation_replenishment", "replen_trigger_rate_pct", "Replenishment Trigger Rate", "pct1"),
    ("mv_allocation_replenishment", "stockout_flag_rate_pct", "Stockout-Flagged Rate", "pct2"),
    ("mv_allocation_replenishment", "total_replen_units", "Total Replenishment Units", "int"),
    ("mv_allocation_replenishment", "review_count", "Size-Curve Review Count", "int"),
    # Store Operations
    ("mv_store_operations", "avg_inventory_accuracy_pct", "Store Inventory Accuracy", "pct1"),
    ("mv_store_operations", "avg_rfid_coverage_pct", "RFID Cycle Count Coverage", "pct1"),
    ("mv_store_operations", "zero_result_search_rate_pct", "Zero-Result Search Rate", "pct1"),
    ("mv_store_operations", "out_of_stock_sku_rate_pct", "Out-of-Stock SKU Rate", "pct2"),
    ("mv_store_operations", "avg_pick_uph", "Pick UPH (BOPIS/SDD)", "num1"),
    ("mv_store_operations", "avg_skus_replenished_per_cart", "Avg SKUs Replenished per Cart", "num1"),
    ("mv_store_operations", "total_units_replenished", "Total Units Replenished", "int"),
    ("mv_store_operations", "bopis_orders_filled", "BOPIS Orders Filled", "int"),
    ("mv_store_operations", "sdd_orders_filled", "Same-Day Delivery Orders Filled", "int"),
    # Store Product Inventory
    ("mv_store_product_inventory", "on_hand_units", "On-Hand Units", "int"),
    ("mv_store_product_inventory", "available_to_sell_units", "Available-to-Sell Units", "int"),
    ("mv_store_product_inventory", "allocated_units", "Allocated Units", "int"),
    ("mv_store_product_inventory", "out_of_stock_rate_pct", "Out-of-Stock Rate", "pct1"),
    ("mv_store_product_inventory", "low_stock_rate_pct", "Low-Stock Rate", "pct1"),
    ("mv_store_product_inventory", "sku_facility_count", "SKU-Facility Row Count", "int"),
    # Merchandising Planning
    ("mv_merchandising_planning", "avg_sell_through_pct", "Avg Sell-Through %", "pct1"),
    ("mv_merchandising_planning", "avg_inventory_turnover", "Avg Inventory Turnover", "num2"),
    ("mv_merchandising_planning", "avg_weeks_of_supply", "Avg Weeks of Supply", "num1"),
    ("mv_merchandising_planning", "avg_margin_pct", "Avg Margin %", "pct1"),
    ("mv_merchandising_planning", "total_sales_units", "Total Sales Units", "int"),
    ("mv_merchandising_planning", "total_sales_amt", "Total Sales Amount", "cur0"),
    ("mv_merchandising_planning", "bop_units", "Beginning-of-Period Units", "int"),
    ("mv_merchandising_planning", "eop_units", "End-of-Period Units", "int"),
    ("mv_merchandising_planning", "exception_style_count", "Exception-Flagged Styles", "int"),
    ("mv_merchandising_planning", "p1_exception_count", "P1 Exception Styles", "int"),
    ("mv_merchandising_planning", "avg_financial_impact", "Avg Financial Impact (Exceptions)", "cur0"),
    # PO Sales & Forecast
    ("mv_po_transactions", "forecast_accuracy_pct", "Forecast Accuracy", "pct1"),
    ("mv_po_transactions", "avg_forecast_variance_units", "Avg Forecast Variance (Units)", "num1"),
    ("mv_po_transactions", "total_sales_units", "Total Sales Units", "int"),
    ("mv_po_transactions", "total_sales_amt", "Total Sales Amount", "cur0"),
    # PO Allocations
    ("mv_po_allocations", "total_alloc_units", "Total Allocated Units", "int"),
    ("mv_po_allocations", "po_count", "PO Count", "int"),
    ("mv_po_allocations", "allocation_line_count", "Allocation Line Count", "int"),
]

MEASURES = [
    {"key": f"{table}.{name}", "table": table, "name": name, "label": label, "kind": kind,
     "area": VIEWS[table]["area"]}
    for table, name, label, kind in _MEASURE_ROWS
]

_DIM_BY_KEY = {d["key"]: d for d in DIMENSIONS}
_MEASURE_BY_KEY = {m["key"]: m for m in MEASURES}


def qualified(table: str) -> str:
    return f"{CATALOG_SCHEMA}.{table}"


def get_dim(key: str) -> dict:
    return _DIM_BY_KEY[key]


def get_measure(key: str) -> dict:
    return _MEASURE_BY_KEY[key]


def measure_key(table: str, name: str) -> str:
    return f"{table}.{name}"


def dim_column(dim_key: str, table: str) -> str | None:
    """The column name of this dimension in this metric view, or None if the view lacks it."""
    if dim_key in TIME_DIM_KEYS:
        return VIEWS[table]["date_col"]
    return _DIM_BY_KEY[dim_key]["cols"].get(table)


def view_supports(table: str, dim_keys) -> bool:
    return all(dim_column(k, table) is not None for k in dim_keys)
