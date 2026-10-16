"""
insights/metric_registry.py
============================
Static registry of the Unity Catalog metric views behind the Overview page,
built directly from the DDLs in the project's context files (filenames =
metric view names). Catalog/schema confirmed by the user: dsg.inventory360.

One entry per Genie space (genie/config.py key) — this is the "one agent
per metric view is a metric view" but the user asked for ONE INSIGHT AGENT
PER GENIE SPACE, so a genie with multiple metric views (store_operations,
merchandising_po) has multiple entries under "metric_views"; the agent
queries all of them and writes one combined insight.

Measure "kind" drives display formatting (see insights/sql_agent.py):
  pct1 / pct2      -> percentage, 1 or 2 decimal places
  num0 / num1      -> plain number, 0 or 1 decimal places
  compact0         -> large integer, compact-abbreviated (e.g. 412K)
  currency0        -> USD, compact-abbreviated, 0 decimals
"""

CATALOG_SCHEMA = "dsg.inventory360"


def qualified(table: str) -> str:
    return f"{CATALOG_SCHEMA}.{table}"


# Each metric view: table name, optional date dimension (for trend charts),
# 1-2 breakdown dimensions (for the second drilldown chart / agent context),
# and its measures as (name, display_name, kind).
GENIE_METRIC_CONFIG = {
    "inventory_visibility": {
        "display_name": "Inventory Visibility",
        "caveat": None,
        "metric_views": [
            {
                "table": "mv_inventory_visibility",
                "date_dim": "snapshot_date",
                "breakdown_dims": ["region", "category"],
                "measures": [
                    ("sellable_on_hand_units", "Sellable On-Hand Units", "compact0"),
                    ("available_to_commerce_units", "Available-to-Commerce Units", "compact0"),
                    ("soft_allocation_shrinkage_pct", "Soft-Allocation Shrinkage %", "pct1"),
                    ("aged_90plus_unit_share_pct", "Aged 90+ Day Unit Share %", "pct1"),
                    ("avg_cycle_count_variance_pct", "Avg Cycle Count Variance %", "pct1"),
                    ("on_hand_units", "On-Hand Units", "compact0"),
                ],
            }
        ],
    },
    "order_orchestration": {
        "display_name": "Order Orchestration & Sourcing",
        "caveat": None,
        "metric_views": [
            {
                "table": "mv_order_orchestration",
                "date_dim": "order_date",
                "breakdown_dims": ["region", "channel_group"],
                "measures": [
                    ("on_time_ship_rate_pct", "On-Time Ship Rate", "pct1"),
                    ("ship_from_store_rate_pct", "Ship-from-Store Rate", "pct1"),
                    ("split_shipment_rate_pct", "Split Shipment Rate", "pct1"),
                    ("oversell_rate_pct", "Oversell Rate", "pct2"),
                    ("order_line_count", "Order Line Count", "compact0"),
                    ("total_revenue", "Total Revenue", "currency0"),
                    ("avg_sourcing_cost", "Avg Sourcing Cost / Line", "num1"),
                ],
            }
        ],
    },
    "allocation": {
        "display_name": "Allocation & Replenishment",
        "caveat": None,
        "metric_views": [
            {
                "table": "mv_allocation_replenishment",
                "date_dim": "review_date",
                "breakdown_dims": ["region", "category"],
                "measures": [
                    ("avg_size_curve_fill_pct", "Avg Size-Curve Fill Rate", "pct1"),
                    ("replen_trigger_rate_pct", "Replenishment Trigger Rate", "pct1"),
                    ("stockout_flag_rate_pct", "Stockout-Flagged Rate", "pct2"),
                    ("total_replen_units", "Total Replenishment Units", "compact0"),
                ],
            }
        ],
    },
    "store_operations": {
        "display_name": "Store Operations",
        "caveat": None,
        "metric_views": [
            {
                "table": "mv_store_operations",
                "date_dim": "activity_date",
                "breakdown_dims": ["region"],
                "measures": [
                    ("avg_inventory_accuracy_pct", "Store Inventory Accuracy", "pct1"),
                    ("avg_rfid_coverage_pct", "RFID Cycle Count Coverage", "pct1"),
                    ("zero_result_search_rate_pct", "Zero-Result Search Rate", "pct1"),
                    ("avg_pick_uph", "Pick UPH (BOPIS/SDD)", "num1"),
                    ("avg_skus_replenished_per_cart", "Avg SKUs Replenished/Cart", "num1"),
                    ("out_of_stock_sku_rate_pct", "Out-of-Stock SKU Rate", "pct2"),
                ],
            },
            {
                "table": "mv_store_product_inventory",
                "date_dim": None,
                "breakdown_dims": ["category_group", "region"],
                "measures": [
                    ("available_to_sell_units", "Sellable On-Hand Units", "compact0"),
                    ("out_of_stock_rate_pct", "Out-of-Stock Rate", "pct1"),
                    ("low_stock_rate_pct", "Low-Stock Rate", "pct1"),
                    ("on_hand_units", "On-Hand Units", "compact0"),
                ],
            },
        ],
    },
    "merchandising_po": {
        "display_name": "Merchandising & PO Optimization",
        "caveat": None,
        "metric_views": [
            {
                "table": "mv_merchandising_planning",
                "date_dim": None,
                "breakdown_dims": ["department", "product_program"],
                "measures": [
                    ("avg_sell_through_pct", "Avg Sell-Through %", "pct1"),
                    ("avg_inventory_turnover", "Avg Inventory Turnover", "num1"),
                    ("avg_weeks_of_supply", "Avg Weeks of Supply", "num1"),
                    ("avg_margin_pct", "Avg Margin %", "pct1"),
                    ("exception_style_count", "Exception-Flagged Styles", "num0"),
                    ("p1_exception_count", "P1 Exception Count", "num0"),
                ],
            },
            {
                "table": "mv_po_transactions",
                "date_dim": "calendar_date",
                "breakdown_dims": ["region"],
                "measures": [
                    ("forecast_accuracy_pct", "Forecast Accuracy", "pct1"),
                    ("total_sales_amt", "Total Sales Amount", "currency0"),
                ],
            },
            {
                "table": "mv_po_allocations",
                "date_dim": "calendar_date",
                "breakdown_dims": ["store_region"],
                "measures": [
                    ("total_alloc_units", "Total Allocated Units", "compact0"),
                    ("po_count", "PO Count", "num0"),
                ],
            },
        ],
    },
}

# The 10 Overview headline/experience cards: (card_key, genie_key, table,
# measure_name, display_name, kind). Picked from real measures above,
# mirroring the mockup's two card rows as closely as the actual schema
# supports (mockup's "Nearby-Store Stock Shown" has no backing measure in
# any DDL provided, so it's swapped for the real "Out-of-Stock Rate").
OVERVIEW_CARDS = [
    # Row 1 — Company Overview
    {"key": "instock", "genie_key": "inventory_visibility", "table": "mv_inventory_visibility",
     "measure": "sellable_on_hand_units", "label": "Sellable On-Hand Units", "kind": "compact0"},
    {"key": "ontime", "genie_key": "order_orchestration", "table": "mv_order_orchestration",
     "measure": "on_time_ship_rate_pct", "label": "On-Time Ship Rate", "kind": "pct1"},
    {"key": "sizecurve", "genie_key": "allocation", "table": "mv_allocation_replenishment",
     "measure": "avg_size_curve_fill_pct", "label": "Size-Curve Fill Rate", "kind": "pct1"},
    {"key": "sfs", "genie_key": "order_orchestration", "table": "mv_order_orchestration",
     "measure": "ship_from_store_rate_pct", "label": "Ship-from-Store Rate", "kind": "pct1"},
    {"key": "sellthru", "genie_key": "merchandising_po", "table": "mv_merchandising_planning",
     "measure": "avg_sell_through_pct", "label": "Avg Sell-Through %", "kind": "pct1"},
    # Row 2 — Store Experience & Productivity
    {"key": "accuracy", "genie_key": "store_operations", "table": "mv_store_operations",
     "measure": "avg_inventory_accuracy_pct", "label": "Store Inventory Accuracy", "kind": "pct1"},
    {"key": "zeroresult", "genie_key": "store_operations", "table": "mv_store_operations",
     "measure": "zero_result_search_rate_pct", "label": "Zero-Result Search Rate", "kind": "pct1"},
    {"key": "rfidcoverage", "genie_key": "store_operations", "table": "mv_store_operations",
     "measure": "avg_rfid_coverage_pct", "label": "RFID Cycle Count Coverage", "kind": "pct1"},
    {"key": "pickuph", "genie_key": "store_operations", "table": "mv_store_operations",
     "measure": "avg_pick_uph", "label": "Pick UPH (BOPIS/SDD)", "kind": "num1"},
    {"key": "oosrate", "genie_key": "store_operations", "table": "mv_store_product_inventory",
     "measure": "out_of_stock_rate_pct", "label": "Out-of-Stock Rate", "kind": "pct1"},
]
