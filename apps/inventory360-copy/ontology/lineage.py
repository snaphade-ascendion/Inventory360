"""
ontology/lineage.py
====================
Live Bronze -> Silver -> Gold -> Metric View lineage discovery for the
Lineage tab (its "Lineage" sub-tab specifically; "Logical Model" is
build_all_entities()/build_entity_model() below).

Translation of the original PySpark/notebook script into the app's
existing SQL access pattern (sql_client.run_sql — the Databricks
Statement Execution API, same as hover.py / glossary_page.py) rather
than a live Spark session. Only reads are performed:
  - SELECT against information_schema.tables      (list + classify tables)
  - SHOW CREATE TABLE on each metric view          (to recover its YAML spec)
No table is ever created, written to, or altered — the result is an
in-memory list of edges that lives only in Streamlit's cache (cleared
by the "Refresh lineage" button), never persisted to Unity Catalog.

Bronze -> Silver and Silver -> Gold edges are inferred by keyword
overlap in table names (no real lineage metadata exists for those
tiers yet) — same heuristic as the original script. Gold -> Metric
View edges are exact, parsed from each metric view's YAML
source/joins.

ONTOLOGY_REGISTRY is the single place that lists every subject area
to trace. Every entry always gets the full Bronze -> Silver -> Gold
keyword-matching pass as well as the exact Gold -> Metric View edges
— there is no per-area on/off switch. A subject area whose Bronze/
Silver tables don't exist yet (or whose names don't share keyword
tokens with its Gold tables) simply comes back with zero Bronze/
Silver edges, same as before full_trace existed, so a new area shows
its Bronze/Silver layer automatically the moment those tables land
in Unity Catalog — no code change needed here.
Add a new subject area by adding an entry here.
"""

import re

import yaml

from sql_client import run_sql

CATALOG_SCHEMA = "dsg.inventory360"
INFO_SCHEMA = "dsg.information_schema.tables"

ONTOLOGY_REGISTRY = {
    "merchandising_po": {
        "display_name": "Merchandising & PO Optimization",
        "table": "mv_po_allocations",
    },
    "inventory_visibility": {"display_name": "Inventory Visibility", "table": "mv_inventory_visibility"},
    "order_orchestration": {"display_name": "Order Orchestration & Sourcing", "table": "mv_order_orchestration"},
    "allocation": {"display_name": "Allocation & Replenishment", "table": "mv_allocation_replenishment"},
    "store_operations": {"display_name": "Store Operations", "table": "mv_store_operations"},
}


class LineageError(Exception):
    pass


def _extract_tables(src_val) -> list[str]:
    if isinstance(src_val, str) and src_val.strip().upper().startswith("SELECT"):
        return [m.group(1) for m in re.finditer(r"(?:FROM|JOIN)\s+([\w.]+)", src_val, re.IGNORECASE)]
    return [str(src_val)] if src_val else []


def _classify_tables() -> dict[str, str]:
    """table_name -> 'BRONZE' | 'SILVER' | 'GOLD' | 'METRIC_VIEW' | 'OTHER'."""
    sql = f"""
        SELECT table_name, table_type,
               CASE
                 WHEN table_name LIKE 'bronze_%' THEN 'BRONZE'
                 WHEN table_name LIKE 'silver_%' THEN 'SILVER'
                 WHEN table_name LIKE 'fact_%' OR table_name LIKE 'dim_%' THEN 'GOLD'
                 WHEN table_type = 'METRIC_VIEW' THEN 'METRIC_VIEW'
                 ELSE 'OTHER'
               END AS tier
        FROM {INFO_SCHEMA}
        WHERE table_schema = 'inventory360'
    """
    resp = run_sql(sql)
    if resp["status"] != "success":
        raise LineageError(resp["error"] or "Failed to list tables")
    return {r["table_name"]: r["tier"] for r in resp["rows"]}


def _metric_view_spec(table: str) -> dict:
    resp = run_sql(f"SHOW CREATE TABLE {CATALOG_SCHEMA}.{table}")
    if resp["status"] != "success" or not resp["rows"]:
        raise LineageError(resp["error"] or f"SHOW CREATE TABLE returned nothing for {table}")
    ddl = resp["rows"][0].get("createtab_stmt") or next(iter(resp["rows"][0].values()))
    match = re.search(r"\$\$\s*(.+?)\s*\$\$", ddl, re.DOTALL)
    if not match:
        raise LineageError(f"Could not find YAML spec ($$ ... $$) in DDL for {table}")
    return yaml.safe_load(match.group(1)) or {}


def build_lineage(table: str, full_trace: bool = True) -> list[dict]:
    """
    Lineage for one metric view, as a flat list of edge dicts:
    {tier_from, tier_to, source, target, relationship, join_condition, mv_description}.
    Always includes Gold -> Metric View edges (exact, from the YAML spec).
    Only chases Bronze -> Silver -> Gold (keyword-matching heuristic) when
    full_trace=True — subject areas not fully wired up yet get the Gold /
    Semantic layer only.
    """
    spec = _metric_view_spec(table)
    mv_full = f"{CATALOG_SCHEMA}.{table}"
    comment = spec.get("comment", "")

    edges: list[dict] = []

    for tbl in _extract_tables(spec.get("source", "")):
        edges.append({
            "tier_from": "GOLD", "tier_to": "METRIC_VIEW",
            "source": tbl, "target": mv_full,
            "relationship": "PRIMARY SOURCE", "join_condition": "—",
            "mv_description": comment,
        })

    def _process_joins(joins_list, parent_name=""):
        for j in (joins_list or []):
            for tbl in _extract_tables(j.get("source", "")):
                label = f"JOIN ({j.get('name', '')})"
                if parent_name:
                    label = f"NESTED JOIN ({parent_name} -> {j.get('name', '')})"
                edges.append({
                    "tier_from": "GOLD", "tier_to": "METRIC_VIEW",
                    "source": tbl, "target": mv_full,
                    "relationship": label,
                    "join_condition": str(j.get("on", j.get("using", "—"))),
                    "mv_description": comment,
                })
            if "joins" in j:
                _process_joins(j["joins"], parent_name=j.get("name", ""))

    _process_joins(spec.get("joins", []))

    if not full_trace:
        return edges

    tiers = _classify_tables()
    bronze_set = {t for t, tier in tiers.items() if tier == "BRONZE"}
    silver_set = {t for t, tier in tiers.items() if tier == "SILVER"}
    gold_set = {t for t, tier in tiers.items() if tier in ("GOLD", "OTHER")}

    # Only chase Bronze/Silver ancestry for Gold tables actually feeding
    # this metric view — keeps the diagram scoped to this subject area.
    gold_sources = {e["source"].split(".")[-1] for e in edges if e["tier_from"] == "GOLD"} & gold_set

    for b in sorted(bronze_set):
        b_tokens = set(b.replace("bronze_", "").split("_"))
        for s in sorted(silver_set):
            s_tokens = set(s.replace("silver_", "").split("_"))
            if b_tokens & s_tokens:
                feeds_this_mv = any(
                    s_tokens & set(g.replace("fact_", "").replace("dim_", "").split("_"))
                    for g in gold_sources
                )
                if feeds_this_mv:
                    edges.append({
                        "tier_from": "BRONZE", "tier_to": "SILVER",
                        "source": f"{CATALOG_SCHEMA}.{b}", "target": f"{CATALOG_SCHEMA}.{s}",
                        "relationship": "BRONZE -> SILVER", "join_condition": "—", "mv_description": "",
                    })

    for s in sorted(silver_set):
        s_tokens = set(s.replace("silver_", "").split("_"))
        for g in sorted(gold_sources):
            g_tokens = set(g.replace("fact_", "").replace("dim_", "").split("_"))
            if s_tokens & g_tokens:
                edges.append({
                    "tier_from": "SILVER", "tier_to": "GOLD",
                    "source": f"{CATALOG_SCHEMA}.{s}", "target": f"{CATALOG_SCHEMA}.{g}",
                    "relationship": "SILVER -> GOLD", "join_condition": "—", "mv_description": "",
                })

    return edges


def _clean_entity_name(table: str) -> str:
    """dim_product -> 'Product', fact_allocations -> 'Allocations'."""
    core = table
    for prefix in ("fact_", "dim_"):
        if core.startswith(prefix):
            core = core[len(prefix):]
            break
    return " ".join(w.capitalize() for w in core.split("_"))


_ALIAS_RE = re.compile(r"\b([A-Za-z_]\w*)\.[A-Za-z_]\w*")


def _expr_alias(expr: str) -> str | None:
    """'dc.facility_name' -> 'dc'; 'SUM(source.alloc_units)' -> 'source';
    'COUNT(1)' -> None (no alias found -> falls back to the hub entity)."""
    if not isinstance(expr, str):
        return None
    m = _ALIAS_RE.search(expr)
    return m.group(1) if m else None


def build_entity_model(table: str) -> dict:
    """
    One metric view's entity-relationship model, derived entirely from
    its YAML spec (source + joins + dimensions + measures) — no table-
    name heuristics, unlike the Bronze/Silver lineage pass. Only needs
    the Gold / Metric View layer, so this works for every subject area
    the same way, independent of whether its Bronze/Silver tables
    exist yet.

    Returns:
      hub: short table name of the metric view's primary source (fact) table
      aliases: {join_alias_or_"source": short_table_name} for every join,
                plus the hub itself under "source"
      attributes: {short_table_name: [{"name": display_name, "is_measure": bool}]}
      relationships: [{"from": hub, "to": dim_table, "label": join_alias}]
      comment: the metric view's own description
    """
    spec = _metric_view_spec(table)
    mv_full = f"{CATALOG_SCHEMA}.{table}"

    hub_tables = _extract_tables(spec.get("source", ""))
    hub = hub_tables[0].rsplit(".", 1)[-1] if hub_tables else None

    aliases: dict[str, str] = {"source": hub} if hub else {}
    relationships: list[dict] = []

    def _walk_joins(joins_list):
        for j in (joins_list or []):
            name = j.get("name")
            srcs = _extract_tables(j.get("source", ""))
            if name and srcs:
                dim_table = srcs[0].rsplit(".", 1)[-1]
                aliases[name] = dim_table
                if hub:
                    relationships.append({
                        "from": hub, "to": dim_table, "label": name,
                        "join_condition": str(j.get("on", j.get("using", "—"))),
                        "mv_table": mv_full,
                    })
            if "joins" in j:
                _walk_joins(j["joins"])

    _walk_joins(spec.get("joins", []))

    attributes: dict[str, list[dict]] = {}

    def _collect(items, is_measure: bool):
        for item in (items or []):
            alias = _expr_alias(item.get("expr", "")) or "source"
            owner = aliases.get(alias, hub)
            if not owner:
                continue
            attributes.setdefault(owner, []).append({
                "name": item.get("display_name") or item.get("name", ""),
                "is_measure": is_measure,
            })

    _collect(spec.get("dimensions", []), is_measure=False)
    _collect(spec.get("measures", []), is_measure=True)

    return {
        "hub": hub,
        "aliases": aliases,
        "attributes": attributes,
        "relationships": relationships,
        "comment": spec.get("comment", ""),
        "mv_table": mv_full,
    }


def build_all_entities() -> tuple[dict, list[dict], list[str]]:
    """
    Merged entity-relationship model across every subject area in
    ONTOLOGY_REGISTRY. Returns:
      entities: {short_table: {"name": display name, "attributes": [...],
                 "subject_areas": set(), "is_hub": bool}}
      relationships: [{"from", "to", "label", "subject_areas": set(), ...}]
      errors: subject areas whose metric view couldn't be queried
    """
    entities: dict[str, dict] = {}
    rel_merged: dict[tuple, dict] = {}
    errors: list[str] = []

    def _touch_entity(table: str, is_hub: bool, area: str, label: str | None = None):
        e = entities.setdefault(table, {
            "name": _clean_entity_name(table), "attributes": [],
            "subject_areas": set(), "is_hub": False,
        })
        if label:
            # Hub ("business process") nodes take their display name from the
            # subject area they represent (ONTOLOGY_REGISTRY display_name),
            # not the raw table name — this is what the Lineage tab's
            # subject-area pills already use, so the same business process
            # reads identically in both sub-tabs instead of showing up as
            # e.g. "Allocations" here and "Merchandising & PO Optimization"
            # there. The underlying table name stays visible as the node's
            # technical id (shown in the detail panel's chip).
            e["name"] = label
        e["subject_areas"].add(area)
        e["is_hub"] = e["is_hub"] or is_hub

    for cfg in ONTOLOGY_REGISTRY.values():
        try:
            model = build_entity_model(cfg["table"])
        except LineageError as e:
            errors.append(f"{cfg['display_name']}: {e}")
            continue
        if not model["hub"]:
            continue
        _touch_entity(model["hub"], is_hub=True, area=cfg["display_name"], label=cfg["display_name"])
        for dim_table in set(model["aliases"].values()) - {model["hub"]}:
            _touch_entity(dim_table, is_hub=False, area=cfg["display_name"])
        for rel in model["relationships"]:
            key = (rel["from"], rel["to"], rel["label"])
            if key in rel_merged:
                rel_merged[key]["subject_areas"].add(cfg["display_name"])
            else:
                rel_merged[key] = {**rel, "subject_areas": {cfg["display_name"]}}
        for table, attrs in model["attributes"].items():
            existing_names = {a["name"] for a in entities[table]["attributes"]}
            for a in attrs:
                if a["name"] and a["name"] not in existing_names:
                    entities[table]["attributes"].append(a)
                    existing_names.add(a["name"])

    return entities, list(rel_merged.values()), errors


def build_all_lineage() -> tuple[list[dict], list[str]]:
    """
    Merged lineage across every subject area in ONTOLOGY_REGISTRY —
    the Lineage tab's default "All" view. Each edge is tagged with
    the subject area(s) that reference it (subject_areas: set of
    display names). Returns (edges, errors) — a table that fails to
    query (e.g. not deployed yet) is skipped, not fatal to the rest.
    """
    merged: dict[tuple, dict] = {}
    errors: list[str] = []

    for cfg in ONTOLOGY_REGISTRY.values():
        try:
            table_edges = build_lineage(cfg["table"])
        except LineageError as e:
            errors.append(f"{cfg['display_name']}: {e}")
            continue
        for e in table_edges:
            key = (e["source"], e["target"], e["relationship"])
            if key in merged:
                merged[key]["subject_areas"].add(cfg["display_name"])
            else:
                merged[key] = {**e, "subject_areas": {cfg["display_name"]}}

    return list(merged.values()), errors
