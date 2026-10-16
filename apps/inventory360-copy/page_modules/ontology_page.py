"""
page_modules/ontology_page.py
==============================
Lineage tab (nav label "Lineage"; module/file names kept as "ontology"
internally — only the user-facing labels changed), split into two
sub-tabs:

- Logical Model (was labeled "Ontology"): business entities and the
  relationships between them, DERIVED from each metric view's own
  YAML spec — entities are its Gold (fact_/dim_) tables, relationships
  are its `joins:` (the join's `name` is the relationship label,
  already authored by whoever built the metric view), attributes are
  its `dimensions:`/`measures:` matched to the entity their `expr`
  alias points at. No table-name guessing is involved, unlike the
  Bronze/Silver pass below — so this sub-tab covers every subject area
  fully, live, from day one.

- Lineage: the original Bronze -> Silver -> Gold -> Metric View /
  Semantic table-dependency view. Every subject area in
  ontology.lineage.ONTOLOGY_REGISTRY always gets the full trace
  attempt; a subject area only shows Bronze/Silver once its tables
  exist and share keyword tokens with its Gold tables — no registry
  flag to flip when that data lands.

Both pull data once via st.cache_data(ttl=None) — cleared only by
their own "Refresh" button — and both use the same no-build custom
component (ontology.components.lineage_diagram) for click-to-select,
so clicking a node in either diagram is a real Streamlit rerun, never
a page reload, and can't disturb which tab is active.
"""

import streamlit as st

from auth import user_cache_data
from ui.safe_html import esc
from ontology.components.lineage_diagram import lineage_diagram
from ontology.diagram import build_svg
from ontology.lineage import ONTOLOGY_REGISTRY, build_all_entities, build_all_lineage
from ontology.ontology_diagram import build_entity_svg
from ui.theme import COLORS

_CSS = f"""
<style>
  .i360-ont-header {{
    background: linear-gradient(135deg, {COLORS['accent']} 0%, #0B7A70 100%);
    border-radius: 14px; padding: 22px 28px; margin-bottom: 20px;
    box-shadow: 0 4px 18px rgba(13,148,136,.22);
  }}
  .i360-ont-header h2 {{ color:#fff; margin:0 0 4px 0; font-size:20px; font-weight:800; }}
  .i360-ont-header p {{ color:rgba(255,255,255,.88); margin:0; font-size:13.5px; }}
  .i360-ont-canvas {{
    background:{COLORS['card']}; border:1px solid {COLORS['border']}; border-radius:14px;
    padding:10px 6px; box-shadow:0 2px 10px rgba(16,24,40,.06); overflow-x:auto;
  }}
  .i360-ont-panel {{
    background:{COLORS['card']}; border:1px solid {COLORS['border']}; border-radius:14px;
    padding:18px 20px; box-shadow:0 2px 10px rgba(16,24,40,.06); min-height:420px;
  }}
  .i360-ont-panel h4 {{ margin:0 0 10px 0; font-size:14px; color:{COLORS['text']}; }}
  .i360-ont-chip {{
    display:inline-block; font-size:10.5px; font-weight:700; padding:2px 9px;
    border-radius:999px; background:{COLORS['accent_soft']}; color:{COLORS['accent']};
    margin-bottom:8px;
  }}
  .i360-ont-row {{ font-size:12.5px; color:{COLORS['text_muted']}; margin:4px 0; line-height:1.5; }}
  .i360-ont-row b {{ color:{COLORS['text']}; }}
  .i360-ont-empty {{ color:{COLORS['text_muted']}; font-size:13px; }}
  .i360-ont-legend {{ display:flex; gap:16px; flex-wrap:wrap; margin:0 2px 12px 2px; font-size:11.5px; color:{COLORS['text_muted']}; }}
  .i360-ont-legend span {{ display:inline-flex; align-items:center; gap:5px; }}
  .i360-ont-legend i {{ width:14px; height:3px; border-radius:2px; display:inline-block; }}
</style>
"""

_ALL = "All"


@user_cache_data(ttl=None, show_spinner=False)  # per-user: SHOW CREATE TABLE runs OBO
def _cached_all_lineage():
    return build_all_lineage()


@user_cache_data(ttl=None, show_spinner=False)  # per-user: OBO metadata reads
def _cached_all_entities():
    return build_all_entities()


def _legend_html(items: list[tuple[str, str]]) -> str:
    spans = "".join(f'<span><i style="background:{c}"></i>{label}</span>' for c, label in items)
    return f'<div class="i360-ont-legend">{spans}</div>'


# ---------------------------------------------------------------------
# Ontology sub-tab
# ---------------------------------------------------------------------
def _ontology_panel_html(selected: str | None, entities: dict, relationships: list[dict]) -> str:
    if not selected:
        return (
            '<div class="i360-ont-panel"><h4>Entity details</h4>'
            '<div class="i360-ont-empty">Click an entity in the diagram to see its '
            "attributes and relationships.</div></div>"
        )

    e = entities[selected]
    outbound = [r for r in relationships if r["from"] == selected]
    inbound = [r for r in relationships if r["to"] == selected]
    subject_areas = sorted(e["subject_areas"])

    rows = [f'<h4>{esc(e["name"])}</h4><span class="i360-ont-chip">{esc(selected)}</span>']
    if subject_areas:
        rows.append(f'<div class="i360-ont-row"><b>Used by:</b> {esc(", ".join(subject_areas))}</div>')
    if e["attributes"]:
        rows.append('<div class="i360-ont-row"><b>Attributes</b></div>')
        for a in e["attributes"]:
            tag = " <i>(measure)</i>" if a["is_measure"] else ""
            rows.append(f'<div class="i360-ont-row">• {esc(a["name"])}{tag}</div>')
    if outbound:
        rows.append('<div class="i360-ont-row"><b>Relationships</b></div>')
        for r in outbound:
            rows.append(
                f'<div class="i360-ont-row">→ <b>{esc(r["label"])}</b> → '
                f'{esc(entities[r["to"]]["name"])}</div>'
            )
    if inbound:
        rows.append('<div class="i360-ont-row"><b>Referenced by</b></div>')
        for r in inbound:
            rows.append(
                f'<div class="i360-ont-row">← {esc(entities[r["from"]]["name"])} '
                f'via <b>{esc(r["label"])}</b></div>'
            )

    return f'<div class="i360-ont-panel">{"".join(rows)}</div>'


def _render_ontology():
    st.caption(
        "Entities are the business objects behind every metric view's Gold tables; "
        "relationships are the joins those metric views already define — nothing here "
        "is guessed from table names."
    )

    with st.spinner("Deriving the entity model from Unity Catalog…"):
        entities, relationships, errors = _cached_all_entities()

    if errors:
        st.caption(f"⚠️ Skipped {len(errors)} subject area(s) not available yet: {'; '.join(errors)}")

    if not entities:
        st.warning("No entities found.")
        return

    _render_graph(
        key_prefix="ontology",
        legend=[(COLORS["blue"], "Business process (fact)"), (COLORS["accent"], "Related entity (dimension)")],
        build_svg_fn=lambda highlight: build_entity_svg(entities, relationships, highlight=highlight),
        all_nodes=set(entities.keys()),
        panel_fn=lambda sel: _ontology_panel_html(sel, entities, relationships),
    )


# ---------------------------------------------------------------------
# Lineage sub-tab
# ---------------------------------------------------------------------
def _lineage_panel_html(selected_node: str | None, edges: list[dict]) -> str:
    if not selected_node:
        return (
            '<div class="i360-ont-panel"><h4>Table details</h4>'
            '<div class="i360-ont-empty">Click a table in the diagram to see what '
            "feeds it, how it's joined, and which subject areas use it.</div></div>"
        )

    def short(n):
        return n.rsplit(".", 1)[-1]

    inbound = [e for e in edges if short(e["target"]) == selected_node]
    outbound = [e for e in edges if short(e["source"]) == selected_node]
    subject_areas = sorted({sa for e in inbound + outbound for sa in e.get("subject_areas", ())})
    mv_desc = next((e["mv_description"] for e in inbound + outbound if e.get("mv_description")), "")

    rows = [f'<h4>{esc(selected_node)}</h4>']
    rows.append(f'<span class="i360-ont-chip">{len(inbound)} upstream · {len(outbound)} downstream</span>')
    if subject_areas:
        rows.append(f'<div class="i360-ont-row"><b>Used by:</b> {esc(", ".join(subject_areas))}</div>')
    if mv_desc:
        rows.append(f'<div class="i360-ont-row">{esc(mv_desc)}</div>')
    if inbound:
        rows.append('<div class="i360-ont-row"><b>Upstream</b></div>')
        for e in inbound:
            jc = f" — <code>{esc(e['join_condition'])}</code>" if e["join_condition"] not in ("—", None) else ""
            rows.append(
                f'<div class="i360-ont-row">← <b>{esc(short(e["source"]))}</b> '
                f'<span style="opacity:.7">({esc(e["relationship"])})</span>{jc}</div>'
            )
    if outbound:
        rows.append('<div class="i360-ont-row"><b>Downstream</b></div>')
        for e in outbound:
            rows.append(
                f'<div class="i360-ont-row">→ <b>{esc(short(e["target"]))}</b> '
                f'<span style="opacity:.7">({esc(e["relationship"])})</span></div>'
            )

    return f'<div class="i360-ont-panel">{"".join(rows)}</div>'


def _render_lineage():
    st.caption(
        "Bronze → Silver → Gold → Metric View / Semantic table dependencies. Every subject "
        "area is traced live end to end; a subject area shows Bronze → Silver once those "
        "tables exist for it, and its Gold / Semantic layer otherwise."
    )

    area_options = [_ALL] + [cfg["display_name"] for cfg in ONTOLOGY_REGISTRY.values()]
    selected_area = st.pills(
        "Subject area", area_options, selection_mode="single",
        default=_ALL, key="lineage_area_pills", label_visibility="collapsed",
    ) or _ALL

    with st.spinner("Pulling lineage from Unity Catalog…"):
        all_edges, errors = _cached_all_lineage()

    if errors:
        st.caption(f"⚠️ Skipped {len(errors)} subject area(s) not available yet: {'; '.join(errors)}")

    if not all_edges:
        st.warning("No lineage edges found.")
        return

    edges = all_edges if selected_area == _ALL else [
        e for e in all_edges if selected_area in e.get("subject_areas", ())
    ]
    if not edges:
        st.info(f"No lineage edges found for {selected_area} yet.")
        return

    all_nodes = {e["source"].rsplit(".", 1)[-1] for e in edges} | {e["target"].rsplit(".", 1)[-1] for e in edges}

    _render_graph(
        key_prefix=f"lineage_{selected_area}",
        legend=[
            (COLORS["green"], "Bronze → Silver"), ("#00ACC1", "Silver → Gold"),
            (COLORS["blue"], "Primary Source (Gold → MV)"), ("#9E9E9E", "Join (Gold → MV)"),
        ],
        build_svg_fn=lambda highlight: build_svg(edges, highlight=highlight)[0],
        all_nodes=all_nodes,
        panel_fn=lambda sel: _lineage_panel_html(sel, edges),
    )


# ---------------------------------------------------------------------
# Shared diagram + panel layout (used by both sub-tabs)
# ---------------------------------------------------------------------
def _render_graph(key_prefix: str, legend: list[tuple[str, str]], build_svg_fn, all_nodes: set, panel_fn):
    st.markdown(_legend_html(legend), unsafe_allow_html=True)

    col_diagram, col_panel = st.columns([3, 1.1])

    with col_panel:
        panel_slot = st.empty()

    with col_diagram:
        state_key = f"{key_prefix}_selected_node"
        prior = st.session_state.get(state_key)
        selected_node = prior if prior in all_nodes else None

        svg = build_svg_fn(selected_node)
        clicked = lineage_diagram(svg, selected=selected_node, key=f"{key_prefix}_diagram")
        if clicked != selected_node:
            st.session_state[state_key] = clicked
            st.rerun()

    panel_slot.markdown(panel_fn(selected_node), unsafe_allow_html=True)


def render() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown(
        '<div class="i360-ont-header"><h2>🕸️ Lineage</h2>'
        "<p>How Inventory360's data is organized conceptually, and how it physically "
        "flows from raw source tables to the metrics you see elsewhere in the app.</p></div>",
        unsafe_allow_html=True,
    )

    tab_ontology, tab_lineage = st.tabs(["Logical Model", "Lineage"])
    with tab_ontology:
        _render_ontology()
    with tab_lineage:
        _render_lineage()
