"""
ontology/ontology_diagram.py
=============================
Renders the entity-relationship model from
ontology.lineage.build_all_entities() as a themed SVG: business
process / fact entities on the left, business object / dimension
entities on the right, with labeled relationship edges (the join
alias each metric view's YAML already defines — e.g. "dc", "store").

Same clickable-node pattern as ontology/diagram.py (data-node attrs,
reused by the same lineage_diagram custom component) so clicking an
entity here works identically to clicking a table in the Lineage view.
"""

import html

from ui.theme import COLORS

_HUB_COLOR = {"fill": "#E3F2FD", "stroke": "#1565C0", "text": "#0D3D73"}
_DIM_COLOR = {"fill": "#E0F7FA", "stroke": "#00838F", "text": "#004D52"}

_COL_X = {"hub": 90, "dim": 540}
_BOX_W = 240
# Box height fits the title plus up to two wrapped attribute lines with
# clear padding, instead of a single line that overflowed the box edge.
_TITLE_Y, _ATTR_Y1, _ATTR_LINE_H = 22, 40, 13
_BOX_H = _ATTR_Y1 + _ATTR_LINE_H * 2 + 10
# Row gap leaves visible breathing room between boxes instead of packing
# them edge to edge.
_ROW_GAP = _BOX_H + 26

_CHARS_PER_LINE = 34  # ~ (box width - padding) / avg char width at 9.5px


def _wrap_attrs(attrs: list[dict], max_lines: int = 2, chars_per_line: int = _CHARS_PER_LINE) -> list[str]:
    """Greedy-wrap the attribute list into up to `max_lines` lines that fit
    inside the box width, folding anything left over into a trailing
    '+N more' on the last line (truncated with an ellipsis if even that
    doesn't fit) — so text never spills past the box edge."""
    names = [a["name"] for a in attrs if a["name"]]
    if not names:
        return []

    text = ", ".join(names)
    lines: list[str] = []
    remaining = text
    while remaining and len(lines) < max_lines:
        if len(remaining) <= chars_per_line:
            lines.append(remaining)
            remaining = ""
            break
        cut = remaining.rfind(", ", 0, chars_per_line)
        if cut == -1:
            # No attribute boundary in range — break on a word instead of
            # mid-word, falling back to a hard cut only as a last resort.
            cut = remaining.rfind(" ", 0, chars_per_line)
        if cut <= 0:
            cut = chars_per_line
        lines.append(remaining[:cut].rstrip(", "))
        remaining = remaining[cut:].lstrip(", ")

    if remaining:
        extra = len([n for n in remaining.split(", ") if n])
        suffix = f" +{extra} more"
        last = lines[-1] if lines else ""
        avail = chars_per_line - len(suffix)
        if len(last) > avail:
            last = last[: max(avail - 1, 0)].rstrip(", ") + "…"
        lines = lines[:-1] + [last + suffix] if lines else [suffix.strip()]

    return lines


def build_entity_svg(entities: dict, relationships: list[dict], highlight: str | None = None) -> str:
    hubs = sorted([t for t, e in entities.items() if e["is_hub"]], key=lambda t: entities[t]["name"])
    dims = sorted([t for t, e in entities.items() if not e["is_hub"]], key=lambda t: entities[t]["name"])

    positions: dict[str, tuple[int, int]] = {}
    for i, t in enumerate(hubs):
        positions[t] = (_COL_X["hub"], 50 + i * _ROW_GAP)
    for i, t in enumerate(dims):
        positions[t] = (_COL_X["dim"], 50 + i * _ROW_GAP)

    height = max(len(hubs), len(dims), 1) * _ROW_GAP + 80
    width = _COL_X["dim"] + _BOX_W + 40

    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" '
        f'style="min-height:{min(height, 760)}px;max-height:900px;" '
        'xmlns="http://www.w3.org/2000/svg">'
        '<style>.i360-node{cursor:pointer}.i360-node:hover rect{stroke-width:3}</style>'
    ]

    parts.append(
        f'<text x="{_COL_X["hub"] + _BOX_W / 2}" y="26" text-anchor="middle" font-size="13" '
        f'font-weight="700" fill="{_HUB_COLOR["stroke"]}">Business Processes</text>'
    )
    parts.append(
        f'<text x="{_COL_X["dim"] + _BOX_W / 2}" y="26" text-anchor="middle" font-size="13" '
        f'font-weight="700" fill="{_DIM_COLOR["stroke"]}">Business Entities</text>'
    )

    # Relationship edges, labeled with the join alias
    for rel in relationships:
        s, t = rel["from"], rel["to"]
        if s not in positions or t not in positions:
            continue
        sx, sy = positions[s]
        tx, ty = positions[t]
        x1, y1 = sx + _BOX_W, sy + _BOX_H / 2
        x2, y2 = tx, ty + _BOX_H / 2
        mx = (x1 + x2) / 2
        faded = highlight and highlight not in (s, t)
        opacity = 0.15 if faded else 0.8
        parts.append(
            f'<path d="M {x1} {y1} C {mx} {y1}, {mx} {y2}, {x2} {y2}" '
            f'stroke="{COLORS["accent"]}" stroke-width="1.8" fill="none" opacity="{opacity}" '
            'marker-end="url(#oarrow)"/>'
        )
        if not faded:
            lx, ly = (x1 + x2) / 2, (y1 + y2) / 2
            label = rel["label"]
            parts.append(
                f'<rect x="{lx - 5 * len(label) / 2 - 4}" y="{ly - 10}" '
                f'width="{5 * len(label) + 8}" height="16" fill="white" opacity="0.9" rx="3"/>'
                f'<text x="{lx}" y="{ly + 2}" text-anchor="middle" font-size="10.5" '
                f'font-style="italic" fill="{COLORS["text_muted"]}">{html.escape(label)}</text>'
            )

    parts.append(
        '<defs><marker id="oarrow" markerWidth="8" markerHeight="8" refX="7" refY="4" '
        f'orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="{COLORS["accent"]}"/></marker></defs>'
    )

    for table, (x, y) in positions.items():
        e = entities[table]
        style = _HUB_COLOR if e["is_hub"] else _DIM_COLOR
        faded = highlight and highlight != table
        opacity = 0.3 if faded else 1.0
        stroke_w = 3 if highlight == table else 1.4
        attr_lines = _wrap_attrs(e["attributes"])
        attr_svg = "".join(
            f'<text x="{x + 12}" y="{y + _ATTR_Y1 + i * _ATTR_LINE_H}" font-size="9.5" '
            f'fill="{COLORS["text_muted"]}">{html.escape(line)}</text>'
            for i, line in enumerate(attr_lines)
        )
        parts.append(
            f'<g class="i360-node" data-node="{html.escape(table)}" opacity="{opacity}">'
            f'<title>{html.escape(e["name"])} ({table})</title>'
            f'<rect x="{x}" y="{y}" width="{_BOX_W}" height="{_BOX_H}" rx="10" '
            f'fill="{style["fill"]}" stroke="{style["stroke"]}" stroke-width="{stroke_w}"/>'
            f'<text x="{x + 12}" y="{y + _TITLE_Y}" font-size="12.5" font-weight="700" '
            f'fill="{style["text"]}">{html.escape(e["name"])}</text>'
            f'{attr_svg}</g>'
        )

    parts.append("</svg>")
    return "".join(parts)
