"""
self_service/themes.py
========================
The 8 fixed Self-Service themes. Each one is a DECISION a merchandising /
supply-chain / store-ops leader has to make, backed by 2-4 direct queries
against the metric views. Deliberately more granular than the Overview
page (which summarises each subject area): these name specific stores,
vendors, categories, styles and nodes to look at first.

Theme names + queries are static for now (per the plan); the numbers and
the written storyline are generated from live data by theme_agent.py.

Query spec fields
  label        : caption shown above the evidence table
  table        : metric view
  dims         : catalog dimension keys (see catalog.DIMENSIONS)
  measures     : measure names inside that view (first one is the "lead" measure)
  sort_by      : measure name to rank by            ascending: True = worst-first for rates
  limit        : rows kept after ranking
  min_support  : (measure name, fraction) -> drop rows whose measure is below
                 fraction x the median of the fetched rows. Keeps a store with
                 3 reviews from topping a "lowest fill rate" list.
"""

THEMES = [
    {
        "key": "replenish_first",
        "name": "Stores & categories to replenish first",
        "question": "Which stores and style categories should get replenishment attention first?",
        "queries": [
            {"label": "Lowest size-curve fill by store and category",
             "table": "mv_allocation_replenishment", "dims": ["facility", "category"],
             "measures": ["avg_size_curve_fill_pct", "stockout_flag_rate_pct", "replen_trigger_rate_pct", "review_count"],
             "sort_by": "avg_size_curve_fill_pct", "ascending": True, "limit": 10,
             "min_support": ("review_count", 0.25)},
            {"label": "Size-curve fill by style category",
             "table": "mv_allocation_replenishment", "dims": ["category"],
             "measures": ["avg_size_curve_fill_pct", "stockout_flag_rate_pct", "total_replen_units", "review_count"],
             "sort_by": "avg_size_curve_fill_pct", "ascending": True, "limit": 8},
        ],
    },
    {
        "key": "vendor_gaps",
        "name": "Vendors linked to size-curve gaps",
        "question": "Which vendors are associated with the weakest size-curve fill, and where should we follow up?",
        "queries": [
            {"label": "Lowest size-curve fill by vendor",
             "table": "mv_allocation_replenishment", "dims": ["vendor"],
             "measures": ["avg_size_curve_fill_pct", "stockout_flag_rate_pct", "total_replen_units", "review_count"],
             "sort_by": "avg_size_curve_fill_pct", "ascending": True, "limit": 10,
             "min_support": ("review_count", 0.25)},
            {"label": "Lowest size-curve fill by vendor and category",
             "table": "mv_allocation_replenishment", "dims": ["vendor", "category"],
             "measures": ["avg_size_curve_fill_pct", "total_replen_units", "review_count"],
             "sort_by": "avg_size_curve_fill_pct", "ascending": True, "limit": 10,
             "min_support": ("review_count", 0.25)},
        ],
    },
    {
        "key": "aged_stock",
        "name": "Aged stock: markdown and transfer candidates",
        "question": "Where is aged inventory concentrated, and which departments have the most supply relative to demand?",
        "queries": [
            {"label": "Highest 90+ day aged share by facility",
             "table": "mv_inventory_visibility", "dims": ["facility"],
             "measures": ["aged_90plus_unit_share_pct", "on_hand_units", "sellable_on_hand_units"],
             "sort_by": "aged_90plus_unit_share_pct", "ascending": False, "limit": 8,
             "min_support": ("on_hand_units", 0.25)},
            {"label": "Highest 90+ day aged share by category and brand",
             "table": "mv_inventory_visibility", "dims": ["category", "brand"],
             "measures": ["aged_90plus_unit_share_pct", "on_hand_units"],
             "sort_by": "aged_90plus_unit_share_pct", "ascending": False, "limit": 8,
             "min_support": ("on_hand_units", 0.25)},
            {"label": "On-hand units by aging bucket",
             "table": "mv_inventory_visibility", "dims": ["aged_bucket"],
             "measures": ["on_hand_units", "sellable_on_hand_units"],
             "sort_by": "on_hand_units", "ascending": False, "limit": 6},
            {"label": "Weeks of supply and sell-through by department (TY vs LY)",
             "table": "mv_merchandising_planning", "dims": ["period_type", "department"],
             "measures": ["avg_weeks_of_supply", "avg_sell_through_pct", "avg_inventory_turnover", "eop_units"],
             "sort_by": "avg_weeks_of_supply", "ascending": False, "limit": 10},
        ],
    },
    {
        "key": "soft_allocation",
        "name": "Soft-allocation leakage",
        "question": "Where is sellable inventory being held back from commerce, and is it justified?",
        "queries": [
            {"label": "Highest soft-allocation shrinkage by facility type and region",
             "table": "mv_inventory_visibility", "dims": ["facility_type", "region"],
             "measures": ["soft_allocation_shrinkage_pct", "sellable_on_hand_units", "available_to_commerce_units"],
             "sort_by": "soft_allocation_shrinkage_pct", "ascending": False, "limit": 10},
            {"label": "Highest soft-allocation shrinkage by style category",
             "table": "mv_inventory_visibility", "dims": ["category"],
             "measures": ["soft_allocation_shrinkage_pct", "sellable_on_hand_units", "available_to_commerce_units"],
             "sort_by": "soft_allocation_shrinkage_pct", "ascending": False, "limit": 8},
            {"label": "Store allocated vs available-to-sell units by category",
             "table": "mv_store_product_inventory", "dims": ["category"],
             "measures": ["allocated_units", "available_to_sell_units", "out_of_stock_rate_pct", "low_stock_rate_pct"],
             "sort_by": "allocated_units", "ascending": False, "limit": 8},
        ],
    },
    {
        "key": "fulfillment_tradeoffs",
        "name": "Fulfillment cost vs service trade-offs",
        "question": "Which channel and sourcing-node combinations cost the most to serve, and what do they buy us in service?",
        "queries": [
            {"label": "Cost and service by channel group and ship-from-store",
             "table": "mv_order_orchestration", "dims": ["channel_group", "f_sfs"],
             "measures": ["avg_sourcing_cost", "on_time_ship_rate_pct", "split_shipment_rate_pct", "order_line_count"],
             "sort_by": "avg_sourcing_cost", "ascending": False, "limit": 10},
            {"label": "Cost and service by sourcing facility type and region",
             "table": "mv_order_orchestration", "dims": ["facility_type", "region"],
             "measures": ["avg_sourcing_cost", "on_time_ship_rate_pct", "split_shipment_rate_pct", "order_line_count"],
             "sort_by": "avg_sourcing_cost", "ascending": False, "limit": 10},
            {"label": "Split-shipment rate and cost by style category",
             "table": "mv_order_orchestration", "dims": ["category"],
             "measures": ["split_shipment_rate_pct", "avg_sourcing_cost", "on_time_ship_rate_pct", "order_line_count"],
             "sort_by": "split_shipment_rate_pct", "ascending": False, "limit": 8},
        ],
    },
    {
        "key": "oversell_counts",
        "name": "Oversell hot-spots vs inventory count discipline",
        "question": "Which sourcing nodes oversell most, and do the same locations have weak inventory accuracy or RFID coverage?",
        "queries": [
            {"label": "Highest oversell rate by sourcing facility",
             "table": "mv_order_orchestration", "dims": ["facility"],
             "measures": ["oversell_rate_pct", "on_time_ship_rate_pct", "order_line_count"],
             "sort_by": "oversell_rate_pct", "ascending": False, "limit": 8,
             "min_support": ("order_line_count", 0.25)},
            {"label": "Lowest inventory accuracy by store",
             "table": "mv_store_operations", "dims": ["facility"],
             "measures": ["avg_inventory_accuracy_pct", "avg_rfid_coverage_pct", "out_of_stock_sku_rate_pct"],
             "sort_by": "avg_inventory_accuracy_pct", "ascending": True, "limit": 8},
            {"label": "Lowest RFID cycle-count coverage by store",
             "table": "mv_store_operations", "dims": ["facility"],
             "measures": ["avg_rfid_coverage_pct", "avg_inventory_accuracy_pct"],
             "sort_by": "avg_rfid_coverage_pct", "ascending": True, "limit": 8},
        ],
    },
    {
        "key": "store_productivity",
        "name": "Store pick productivity and findability",
        "question": "Which stores need attention on pick productivity or on-site product findability?",
        "queries": [
            {"label": "Lowest pick UPH by store",
             "table": "mv_store_operations", "dims": ["facility"],
             "measures": ["avg_pick_uph", "bopis_orders_filled", "sdd_orders_filled", "avg_skus_replenished_per_cart"],
             "sort_by": "avg_pick_uph", "ascending": True, "limit": 8},
            {"label": "Highest zero-result search rate by store",
             "table": "mv_store_operations", "dims": ["facility"],
             "measures": ["zero_result_search_rate_pct", "out_of_stock_sku_rate_pct", "avg_pick_uph"],
             "sort_by": "zero_result_search_rate_pct", "ascending": False, "limit": 8},
            {"label": "Pick UPH and BOPIS/SDD volume by region",
             "table": "mv_store_operations", "dims": ["region"],
             "measures": ["avg_pick_uph", "bopis_orders_filled", "sdd_orders_filled"],
             "sort_by": "avg_pick_uph", "ascending": True, "limit": 8},
        ],
    },
    {
        "key": "forecast_exposure",
        "name": "Forecast misses and style exception exposure",
        "question": "Which styles and departments carry the biggest forecast or exception risk before the next PO decisions?",
        "queries": [
            {"label": "Lowest forecast accuracy by region",
             "table": "mv_po_transactions", "dims": ["region"],
             "measures": ["forecast_accuracy_pct", "avg_forecast_variance_units", "total_sales_amt"],
             "sort_by": "forecast_accuracy_pct", "ascending": True, "limit": 8},
            {"label": "Lowest forecast accuracy by style (material sales only)",
             "table": "mv_po_transactions", "dims": ["style_number"],
             "measures": ["forecast_accuracy_pct", "avg_forecast_variance_units", "total_sales_amt"],
             "sort_by": "forecast_accuracy_pct", "ascending": True, "limit": 10,
             "min_support": ("total_sales_amt", 0.25)},
            {"label": "Style exceptions and financial impact by priority and department",
             "table": "mv_merchandising_planning", "dims": ["exc_priority", "department"],
             "measures": ["exception_style_count", "avg_financial_impact", "avg_sell_through_pct"],
             "sort_by": "avg_financial_impact", "ascending": False, "limit": 10},
            {"label": "Allocated units and PO count by distribution center",
             "table": "mv_po_allocations", "dims": ["dc"],
             "measures": ["total_alloc_units", "po_count"],
             "sort_by": "total_alloc_units", "ascending": False, "limit": 6},
        ],
    },
]

THEME_BY_KEY = {t["key"]: t for t in THEMES}
