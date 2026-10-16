"""
ontology/components/lineage_diagram.py
========================================
Python side of the lineage-diagram custom component. No build step: the
frontend (./lineage_diagram/index.html) is plain HTML/JS using a vendored
~25-line Streamlit<->iframe bridge (see that file's comment for source),
not a React/webpack component — declare_component(path=...) serves it as
static files, exactly as Streamlit's own "no framework" template does.

Returns the clicked table's short name (e.g. "dim_product"), or None if
nothing is selected / the user clicked the already-selected node again.
"""

import os

import streamlit.components.v1 as components

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lineage_diagram")
_component_func = components.declare_component("i360_lineage_diagram", path=_DIR)


def lineage_diagram(svg: str, selected: str | None, key: str | None = None) -> str | None:
    return _component_func(svg=svg, selected=selected, key=key, default=None)
