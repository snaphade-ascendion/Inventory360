"""
genie/config.py
================
Registry of all Genie spaces: space IDs plus the scope metadata the router
needs to pick the right one (or decline/clarify instead of guessing).

Adding a new Genie later = add one entry here. Nothing in graph/ needs to
change structurally — router.py reads this dict to build its prompt.
"""

GENIE_SPACES = {
    "inventory_visibility": {
        "space_id": "01f1b762113f1ed3be69cb42023aad11",
        "display_name": "Inventory Visibility",
        "metric_views": ["mv_inventory_visibility"],
        "metrics": [
            "on_hand_units", "sellable_on_hand_units", "available_to_commerce_units",
            "soft_allocation_shrinkage_pct", "avg_cycle_count_variance_pct",
            "aged_90plus_unit_share_pct", "item_facility_row_count",
        ],
        "good_for": (
            "On-hand inventory levels, available-to-commerce quantity, "
            "soft-allocation shrinkage, aged/excess inventory, cycle-count "
            "variance — by item, style category, category group, brand, "
            "facility, facility type, or region. Weekly snapshot grain."
        ),
        "not_good_for": (
            "Order/sales questions, size-curve or replenishment questions, "
            "store-level operational metrics (RFID accuracy, search rate), "
            "vendor performance, purchase orders, sell-through, or margin. "
            "IMPORTANT: this Genie does NOT have purchase-order 'allocated "
            "units' data even though it covers facilities/DCs — questions "
            "like 'allocated units by distribution center' belong to "
            "Merchandising & PO Optimization instead, not here."
        ),
    },
    "order_orchestration": {
        "space_id": "01f1b76283f71bbbb3e5b428202ceb88",
        "display_name": "Order Orchestration & Sourcing",
        "metric_views": ["mv_order_orchestration"],
        "metrics": [
            "order_line_count", "total_units", "total_revenue",
            "on_time_ship_rate_pct", "ship_from_store_rate_pct",
            "split_shipment_rate_pct", "oversell_rate_pct", "avg_sourcing_cost",
        ],
        "good_for": (
            "Order fulfillment: on-time ship rate, ship-from-store rate, "
            "split shipments, oversells, sourcing cost — by style category, "
            "sourcing facility, facility type, region, channel, or "
            "ship-from-store flag."
        ),
        "not_good_for": (
            "On-hand inventory levels, size-curve fill or replenishment "
            "triggers, store operational metrics (pick UPH, RFID accuracy), "
            "merchandising/sell-through/PO questions."
        ),
    },
    "allocation": {
        "space_id": "01f1b762c8541b6e9ad321545eab7b2f",
        "display_name": "Allocation & Replenishment",
        "metric_views": ["mv_allocation_replenishment"],
        "metrics": [
            "avg_size_curve_fill_pct", "replen_trigger_rate_pct",
            "stockout_flag_rate_pct", "total_replen_units", "review_count",
        ],
        "good_for": (
            "Footwear-only size-curve fill rate, replenishment trigger "
            "rate, stockout-flagged rate — by store, region, vendor, style "
            "category, category group, or brand. Bi-weekly review grain."
        ),
        "not_good_for": (
            "Apparel/Equipment/Accessories questions (footwear only), "
            "on-hand inventory, order fulfillment/shipping, store "
            "operational metrics. NOTE: this Genie is about size-curve "
            "FIT allocation, not purchase-order quantity allocation — "
            "questions about 'allocated units by distribution center' "
            "or PO quantities belong to Merchandising & PO Optimization."
        ),
    },
    "store_operations": {
        "space_id": "01f1b763d32a1fb5b14a34c17deb5737",
        "display_name": "Store Operations",
        "metric_views": ["mv_store_operations", "mv_store_product_inventory"],
        "metrics": [
            "avg_inventory_accuracy_pct", "avg_rfid_coverage_pct",
            "avg_skus_replenished_per_cart", "total_units_replenished", "avg_pick_uph",
            "zero_result_search_rate_pct", "out_of_stock_sku_rate_pct",
            "bopis_orders_filled", "sdd_orders_filled",
            # from mv_store_product_inventory — NOTE: "on_hand_units" here is the
            # store/SKU-level available-to-sell breakdown, a DIFFERENT metric from
            # Inventory Visibility's company-wide "on_hand_units" across all
            # dispositions/facilities (including DCs). Same name, two Genies — see
            # the router prompt's overlap note for how to disambiguate.
            "on_hand_units", "available_to_sell_units", "allocated_units",
            "out_of_stock_rate_pct", "low_stock_rate_pct", "sku_facility_count",
        ],
        "good_for": (
            "Two related things: (1) store trend metrics over time — "
            "inventory accuracy, RFID coverage, replenishment productivity, "
            "pick UPH, zero-result search rate, out-of-stock SKU rate, "
            "BOPIS/SDD order counts; (2) point-in-time product stock "
            "status per store (in-stock/low-stock/out-of-stock)."
        ),
        "not_good_for": (
            "Company-wide inventory including DCs (store-only), order "
            "sourcing/shipping decisions, footwear size-curve/replenishment "
            "triggers, merchandising/sell-through/PO questions. Pick UPH "
            "is not split by BOPIS vs. SDD individually."
        ),
    },
    "merchandising_po": {
        "space_id": "01f1b76400561ef7b46d61319f98b88e",
        "display_name": "Merchandising & PO Optimization",
        "metric_views": ["mv_merchandising_planning", "mv_po_transactions", "mv_po_allocations"],
        "metrics": [
            # mv_merchandising_planning
            "total_sales_units", "total_sales_amt", "avg_margin_pct", "eop_units",
            "bop_units", "avg_sell_through_pct", "avg_inventory_turnover",
            "avg_weeks_of_supply", "avg_financial_impact", "exception_style_count",
            "p1_exception_count",
            # mv_po_transactions — note total_sales_units/total_sales_amt repeat here;
            # both are within this SAME Genie, so no cross-Genie ambiguity to resolve.
            "total_on_hand_units", "total_on_order_units", "forecast_accuracy_pct",
            "avg_forecast_variance_units",
            # mv_po_allocations
            "total_alloc_units", "po_count", "allocation_line_count",
        ],
        "good_for": (
            "PURCHASE-ORDER ALLOCATION quantities from distribution center to "
            "store (e.g. 'allocated units by DC', 'PO allocation by store') — "
            "this is the ONLY Genie with DC-to-store allocation data. Also: "
            "sell-through %, inventory turnover, weeks of supply, style "
            "exception severity (P1/P2/P3) — Nike footwear class only. Also "
            "PO-level sales/inventory/forecast trends."
        ),
        "not_good_for": (
            "Non-Nike brand/vendor questions (dim_product is Nike-only "
            "currently), item/facility ON-HAND inventory levels (use "
            "Inventory Visibility — that Genie does NOT have allocation "
            "data despite covering facilities/DCs), order fulfillment/"
            "shipping, footwear size-curve/replenishment (a DIFFERENT "
            "kind of 'allocation' — see the Allocation & Replenishment "
            "Genie), store operational metrics."
        ),
    },
}

# Topics explicitly out of scope for ALL Genies — used by the decline node
# and mentioned in the router prompt so the model doesn't try to force-fit
# these into one of the 5 spaces above.
OUT_OF_SCOPE_TOPICS = [
    "Wave/Task Execution (DC pick/pack/putaway operations)",
    "Inbound/Receiving (ASN, PO receipt, dock-to-stock)",
    "Finance & Cost Accounting (carrying cost, P&L, budgets)",
    "Strategy or prescriptive recommendations (what should we do to improve X)",
    "Anything unrelated to Inventory360's supply chain / retail domain",
]


def scope_topics_sentence() -> str:
    """
    Natural-language list of what IS in scope, built from GENIE_SPACES'
    display names so it can't drift out of sync with the actual Genies
    configured. Used in every "sorry, that's not something I can help
    with" style message (decline, and router's fallback paths).
    """
    names = [spec["display_name"] for spec in GENIE_SPACES.values()]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f", or {names[-1]}"