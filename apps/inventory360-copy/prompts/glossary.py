"""
prompts/glossary.py
====================
Domain glossary and plausibility anchors, kept separate from the prompt
templates so they can be edited/extended without touching router or
synthesis logic. Grounded in the Goal doc, the Manhattan POC doc, and the
actual metric view definitions — not invented.
"""

GLOSSARY = """
## Key Terms

- Soft Allocation: a "4-wall" holistic inventory check — inventory looks available at
  the facility level but hasn't been committed to a specific order yet.
- Hard Allocation: LPN-level, task-driven commitment of specific inventory to a specific
  order. The gap between soft and hard allocation is what "soft_allocation_shrinkage_pct"
  measures — inventory that looked available but wasn't actually committable.
- Size-Curve Fill Rate: how closely a store's actual size distribution for a footwear
  style matches the target size curve. 100% = perfectly matched, NOT "fully stocked."
  A style can have 100% size-curve fill and still be low on total units.
- Available-to-Commerce: sellable on-hand units minus the soft-allocation gap — the
  practical, sellable quantity after accounting for soft holds.
- OTIF / On-Time Ship Rate: share of order lines shipped on or before the promise date.
- Ship-from-Store: fulfilling a digital (Web/Marketplace/Wholesale) order from a store's
  inventory instead of a distribution center. This concept does not apply to in-store
  purchases (Retail channel) — ship_from_store_rate_pct already excludes those.
- Category vs. Category Group: "category" is the footwear-specific style category
  (Running, Basketball, Training, Lifestyle/Casual, Cleats/Outdoor). "category_group" is
  the broader retail grouping (Footwear, Apparel, Equipment, Accessories). These are two
  different classification systems used by different subject areas — do not conflate them.
- Aged/Excess Inventory: units in the 90+ day aged bucket, one of four buckets
  (0-30, 31-60, 61-90, 90+ days).
- Exception Priority (P1/P2/P3): merchandising style-level severity flags. P1 is highest
  severity (most financial impact / sales variance).
- Sell-Through %: share of beginning-of-period + receipts inventory that sold during
  the period. Different from margin % — do not conflate the two even though both are
  percentages in the same table.
- Weeks of Supply / Inventory Turnover: standard merchandising planning metrics,
  Nike footwear class only in the current dataset.

## Data Grain Notes (important for router request-formatting)

- Inventory Visibility (mv_inventory_visibility): WEEKLY snapshot grain, not daily.
- Allocation (mv_allocation_replenishment): BI-WEEKLY review cycle grain.
- Store Operations (mv_store_operations): DAILY, but the 5 underlying source tables
  don't all have a row for every store/date combination.
- Order Orchestration, Store Product Inventory: transactional / point-in-time grain.
"""

PLAUSIBILITY_ANCHORS = """
## Plausibility Anchors (sanity-check returned numbers against these ranges)

- on_time_ship_rate_pct: typically 90-99%. A value below 70% or above 100% is
  suspicious and likely a query/grain error, not a real business result.
- avg_size_curve_fill_pct: typically 60-100%. Below 30% across a large sample is
  suspicious.
- avg_inventory_accuracy_pct / avg_rfid_coverage_pct: typically 85-99%.
- ship_from_store_rate_pct: typically single digits to low teens (this retailer's
  store network is not the primary digital fulfillment channel).
- oversell_rate_pct: should be a small fraction of a percent to a few percent — a
  double-digit oversell rate is implausible and likely reflects a bad denominator.
- zero_result_search_rate_pct: typically mid-single-digits to ~15%.
- aged_90plus_unit_share_pct: typically under 15%. Above 30% is suspicious.
- All percentage measures should fall between 0 and 100 (or 0 and 1 if the
  formatting convention wasn't applied) — a percentage far outside that range
  signals a scale/formatting bug in the query, not a real result.
"""

OUT_OF_SCOPE_GUIDANCE = """
## Out-of-Scope Topics — use graceful decline, do not force-route to a Genie

- Wave/Task Execution (DC pick/pack/putaway operations, labor scheduling)
- Inbound/Receiving (ASN, PO receipt, dock-to-stock cycle time)
- Finance & Cost Accounting (carrying cost, P&L, budgets, headcount)
- Strategy or prescriptive recommendations ("what should we do to improve X")
- Anything unrelated to Inventory360's supply chain / retail domain
- Non-Nike brand questions specifically within Merchandising & PO (dim_product is
  Nike-only in the current dataset)
"""