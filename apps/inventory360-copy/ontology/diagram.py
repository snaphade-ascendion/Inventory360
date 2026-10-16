"""
ontology/diagram.py
====================
Renders a lineage edge list (see ontology.lineage.build_lineage) as a
themed SVG diagram: four columns (Bronze / Silver / Gold / Metric
Views), curved arrows between them, colored by edge type. This is a
from-scratch SVG re-implementation of the layout logic in the original
matplotlib script — matplotlib's plt.show() only works in a notebook,
not a browser, so it can't be reused directly inside Streamlit.

Rendered via st.markdown(unsafe_allow_html=True) (not an iframe), so
it sits directly in the page DOM — this is what lets plain CSS hover
tooltips (<title> + a styled .i360-ont-tip) work with no JS bridge,
and keeps it visually consistent with the rest of the app.
"""

import html

from ui.theme import COLORS

_TIER_COLORS = {
    "BRONZE": {"fill": "#E8F5E9", "stroke": "#2E7D32", "text": "#1B5E20"},
    "SILVER": {"fill": "#E0F7FA", "stroke": "#00838F", "text": "#004D52"},
    "GOLD": {"fill": "#E3F2FD", "stroke": "#1565C0", "text": "#0D3D73"},
    "METRIC_VIEW": {"fill": "#FFF3E0", "stroke": COLORS["gold"], "text": "#7A4F00"},
}

_EDGE_COLORS = {
    "BRONZE -> SILVER": COLORS["green"],
    "SILVER -> GOLD": "#00ACC1",
    "PRIMARY SOURCE": COLORS["blue"],
    "JOIN": "#9E9E9E",
}

_COL_X = {"BRONZE": 90, "SILVER": 330, "GOLD": 570, "METRIC_VIEW": 900}
_COL_LABEL = {"BRONZE": "Bronze", "SILVER": "Silver", "GOLD": "Gold", "METRIC_VIEW": "Metric Views / Semantic"}
_BOX_W, _BOX_H, _ROW_GAP = 190, 40, 58


def _short(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def _edge_color(relationship: str) -> str:
    if "BRONZE" in relationship:
        return _EDGE_COLORS["BRONZE -> SILVER"]
    if "SILVER" in relationship:
        return _EDGE_COLORS["SILVER -> GOLD"]
    if "PRIMARY" in relationship:
        return _EDGE_COLORS["PRIMARY SOURCE"]
    return _EDGE_COLORS["JOIN"]


def _node_tiers(edges: list[dict]) -> dict[str, str]:
    """short_name -> tier, derived from every edge endpoint."""
    tiers: dict[str, str] = {}
    for e in edges:
        tiers[_short(e["source"])] = e["tier_from"]
        tiers[_short(e["target"])] = e["tier_to"]
    return tiers


def build_svg(edges: list[dict], highlight: str | None = None) -> tuple[str, dict[str, str]]:
    """
    Returns (svg_markup, node_tooltips) where node_tooltips maps each
    short table name to a one-line summary (used by the side panel's
    selectbox default text, and as the SVG <title> tooltip).
    """
    tiers = _node_tiers(edges)
    by_col: dict[str, list[str]] = {"BRONZE": [], "SILVER": [], "GOLD": [], "METRIC_VIEW": []}
    for name, tier in tiers.items():
        by_col.setdefault(tier, []).append(name)
    for col in by_col:
        by_col[col].sort()

    positions: dict[str, tuple[int, int]] = {}
    for col, names in by_col.items():
        x = _COL_X[col]
        for i, name in enumerate(names):
            positions[name] = (x, 60 + i * _ROW_GAP)

    height = max((len(v) for v in by_col.values()), default=1) * _ROW_GAP + 100
    width = _COL_X["METRIC_VIEW"] + _BOX_W + 40

    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" '
        f'style="min-height:{min(height, 620)}px;max-height:640px;" '
        'xmlns="http://www.w3.org/2000/svg">'
        '<style>.i360-node{cursor:pointer;transition:opacity .12s ease}'
        '.i360-node:hover rect{stroke-width:3}</style>'
    ]

    # Column headers
    for col, label in _COL_LABEL.items():
        cx = _COL_X[col] + _BOX_W / 2
        c = _TIER_COLORS[col]["stroke"]
        parts.append(
            f'<text x="{cx}" y="28" text-anchor="middle" font-size="13" '
            f'font-weight="700" fill="{c}">{html.escape(label)}</text>'
        )

    # Edges (behind nodes)
    for e in edges:
        s, t = _short(e["source"]), _short(e["target"])
        if s not in positions or t not in positions:
            continue
        sx, sy = positions[s]
        tx, ty = positions[t]
        x1, y1 = sx + _BOX_W, sy + _BOX_H / 2
        x2, y2 = tx, ty + _BOX_H / 2
        mx = (x1 + x2) / 2
        color = _edge_color(e["relationship"])
        faded = highlight and highlight not in (s, t)
        opacity = 0.18 if faded else 0.75
        parts.append(
            f'<path d="M {x1} {y1} C {mx} {y1}, {mx} {y2}, {x2} {y2}" '
            f'stroke="{color}" stroke-width="1.8" fill="none" opacity="{opacity}" '
            'marker-end="url(#arrow)"/>'
        )

    parts.append(
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" '
        'orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#9aa0a6"/></marker></defs>'
    )

    # Nodes
    tooltips: dict[str, str] = {}
    for tier, names in by_col.items():
        style = _TIER_COLORS[tier]
        for name in names:
            x, y = positions[name]
            faded = highlight and highlight != name
            opacity = 0.35 if faded else 1.0
            stroke_w = 3 if highlight == name else 1.4
            label = name if len(name) <= 24 else name[:22] + "…"
            tooltips[name] = f"{_COL_LABEL[tier]} • {name}"
            parts.append(
                f'<g class="i360-node" data-node="{html.escape(name)}" opacity="{opacity}">'
                f'<title>{html.escape(name)}</title>'
                f'<rect x="{x}" y="{y}" width="{_BOX_W}" height="{_BOX_H}" rx="9" '
                f'fill="{style["fill"]}" stroke="{style["stroke"]}" stroke-width="{stroke_w}"/>'
                f'<text x="{x + _BOX_W / 2}" y="{y + _BOX_H / 2 + 4}" text-anchor="middle" '
                f'font-size="11.5" font-weight="600" fill="{style["text"]}">'
                f'{html.escape(label)}</text></g>'
            )

    parts.append("</svg>")
    return "".join(parts), tooltips
