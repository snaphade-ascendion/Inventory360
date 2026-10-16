"""
ui/navbar.py
=============
True lazy-loading top navigation, replacing st.tabs().

st.tabs() is PURELY a visual switch: Streamlit has no way to tell the Python
script which tab is currently visible, so it runs the code inside EVERY
`with tab:` block on EVERY single script rerun and just hides the inactive
panels with CSS on the frontend. That meant every tab's queries were firing
on every single page load, regardless of which tab a person was actually
looking at — Glossary's 7 DESCRIBE EXTENDED calls, Storylines/BYOV's
data-window queries, the AI Accuracy page's benchmark load, all of it,
every time, even sitting on the Overview tab the whole session.

This replaces st.tabs() with a row of real st.button()s (inactive tabs) and
a static styled label (the active tab), backed by st.session_state. Because
these are ordinary Python widgets, app.py can do genuine
`if active == "overview": overview_page.render()` branching — the other
branches, and therefore their queries, simply never execute until clicked.

Visual styling (the pill-tab look, sticky positioning, per-tab hover
tooltips) is fully self-contained here rather than added to ui/theme.py's
CUSTOM_CSS, since this entirely replaces what that file's old
[role="tab"] rules did. BYOV's own INTERNAL st.tabs() (Dimensions/Measures)
is untouched — this only replaces the top-level app.py navigation.
"""

import streamlit as st

from ui.theme import COLORS

# key: used in session_state + CSS class names (letters/underscores only).
# label: shown on the tab.
# icon: single glyph, shown on the tab's Home-page tile (ui/home_page.py)
#   — not rendered in the nav pill itself, only here as the one place that
#   owns it, same reasoning as the tip field below. Deliberately pulled
#   from the older Miscellaneous Technical / Geometric Shapes / Dingbats
#   Unicode blocks (U+2300-27BF) rather than full-color pictograph emoji
#   (📊💬📖...) — plain monochrome marks that pick up the page's accent
#   color via CSS, instead of every page getting the same handful of
#   default LLM icons rendered in Apple/Google's house art style. These
#   blocks are old enough (Unicode 1.1-5.1) to have near-universal font
#   fallback coverage, so they render as a clean glyph rather than a
#   missing-character box across browsers/OSes.
# tip: hover tooltip — ported verbatim from the old ui/theme.py
# [role="tab"]:nth-child(N) rules this replaces. Also reused verbatim as
# the Home page tile's description, so there's one place to edit a page's
# blurb instead of two copies drifting apart.
TABS = [
    {"key": "home", "label": "Home", "icon": "⌂",
     "tip": "Jump to any page in Inventory360, with a one-line description of what's inside each one."},
    {"key": "overview", "label": "Overview", "icon": "◈",
     "tip": "Live KPI cards and AI-generated callouts across all 5 subject areas — fill rate, allocation, "
            "PO health, and more — refreshed on a schedule."},
    {"key": "chat", "label": "Ask Inventory360", "icon": "⌘",
     "tip": "Ask a question in plain English and get an answer pulled straight from the warehouse, with the "
            "SQL and results shown alongside."},
    {"key": "storylines", "label": "Storylines", "icon": "❧",
     "tip": "8 pre-built themes (e.g. replenishment, aged stock, allocation leakage) with an AI headline, "
            "bullets and a decision to consider for the date range you pick."},
    {"key": "byov", "label": "BYOV", "icon": "⊞",
     "tip": "Build a custom pivot table by dragging in dimensions and measures, then ask follow-up questions "
            "about the table you built."},
    {"key": "alerts", "label": "Smart Alerts", "icon": "⌁",
     "tip": "Set a metric and a threshold (e.g. \"fill rate below 92%\") and get a decision-oriented email or "
            "Teams message when it's crossed — no dashboard-checking required."},
    {"key": "testing", "label": "AI Accuracy", "icon": "⌖",
     "tip": "Reliability report for the AI: human-evaluated accuracy, benchmark results and confidence "
            "distribution, plus tools to run new benchmark and bulk tests."},
    {"key": "ontology", "label": "Lineage", "icon": "⬡",
     "tip": "How Inventory360's data is organized conceptually, and how it physically flows from raw source "
            "tables to the metrics you see elsewhere in the app."},
    {"key": "glossary", "label": "Glossary", "icon": "§",
     "tip": "Every metric across every subject area in one searchable table — definition, calculation and "
            "point of contact."},
    {"key": "coming_soon", "label": "Coming Soon", "icon": "✦",
     "tip": "A look at what's on the roadmap — knowledge graph exploration, collaboration, persona views, "
            "and more."},
]

_DEFAULT_TAB = TABS[0]["key"]


def _build_css() -> str:
    tooltip_rules = []
    for tab in TABS:
        marker = f"i360-navtab-marker-{tab['key']}"
        tip = tab["tip"].replace('"', '\\"')
        tooltip_rules.append(f"""
  [data-testid="element-container"]:has(.{marker}) + [data-testid="element-container"],
  [data-testid="stElementContainer"]:has(.{marker}) + [data-testid="stElementContainer"] {{
    position: relative;
  }}
  [data-testid="element-container"]:has(.{marker}) + [data-testid="element-container"]::after,
  [data-testid="stElementContainer"]:has(.{marker}) + [data-testid="stElementContainer"]::after {{
    content: "{tip}";
    display: block; position: absolute; top: calc(100% + 10px); left: 50%;
    transform: translateX(-50%) translateY(-4px); width: 230px; padding: 10px 12px;
    background: #1F2430; color: #F4F5F7; font-size: 12.5px; font-weight: 500; line-height: 1.45;
    text-align: left; border-radius: 8px; box-shadow: 0 6px 16px rgba(16,24,40,.22);
    opacity: 0; visibility: hidden; pointer-events: none; transition: opacity .15s, transform .15s;
    z-index: 1000; white-space: normal;
  }}
  [data-testid="element-container"]:has(.{marker}) + [data-testid="element-container"]:hover::after,
  [data-testid="stElementContainer"]:has(.{marker}) + [data-testid="stElementContainer"]:hover::after {{
    opacity: 1; visibility: visible; transform: translateX(-50%) translateY(0);
  }}""")

    return f"""
<style>
  /* Hide every nav marker span itself — purely a CSS hook, never meant to be seen. */
  [data-testid="element-container"]:has(.i360-navtab-marker),
  [data-testid="stElementContainer"]:has(.i360-navtab-marker),
  [data-testid="element-container"]:has(.i360-navbar-row-marker),
  [data-testid="stElementContainer"]:has(.i360-navbar-row-marker) {{ display: none; }}

  /* The row of columns holding the tabs: sticky pill-bar, same look st.tabs() had, plus
     a glowing green underline spanning the full row (::after below) instead of a flat border.

     Selector covers TWO possible DOM shapes, since it's not certain from here whether
     st.columns()'s stHorizontalBlock sits as a DIRECT sibling of the marker's container, or
     one level deeper inside its own wrapper — the per-pill marker+button rules only ever
     needed the direct-sibling case and those confirmed working, but this row-level rule
     needs both to be safe. Harmless if one pattern simply never matches. */
  [data-testid="element-container"]:has(.i360-navbar-row-marker) + [data-testid="stHorizontalBlock"],
  [data-testid="element-container"]:has(.i360-navbar-row-marker) + * [data-testid="stHorizontalBlock"],
  [data-testid="stElementContainer"]:has(.i360-navbar-row-marker) + [data-testid="stHorizontalBlock"],
  [data-testid="stElementContainer"]:has(.i360-navbar-row-marker) + * [data-testid="stHorizontalBlock"] {{
    position: sticky !important; top: 3.75rem; z-index: 990;
    background: {COLORS['bg']}; padding: 8px 2px 16px; margin-bottom: 6px;
    display: flex !important; flex-wrap: wrap; gap: 4px !important;
  }}
  /* Columns shrink-wrap to their pill's natural width instead of stretching equally —
     without this, st.columns()'s default equal-width behavior would turn each compact
     pill into a full-width bar. Padding zeroed too, so the 4px gap above is the ONLY
     space between pills (Streamlit's own column gutter would otherwise add more). */
  [data-testid="element-container"]:has(.i360-navbar-row-marker) + [data-testid="stHorizontalBlock"] > [data-testid="column"],
  [data-testid="element-container"]:has(.i360-navbar-row-marker) + * [data-testid="stHorizontalBlock"] > [data-testid="column"],
  [data-testid="stElementContainer"]:has(.i360-navbar-row-marker) + [data-testid="stHorizontalBlock"] > [data-testid="column"],
  [data-testid="stElementContainer"]:has(.i360-navbar-row-marker) + * [data-testid="stHorizontalBlock"] > [data-testid="column"],
  [data-testid="element-container"]:has(.i360-navbar-row-marker) + [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
  [data-testid="element-container"]:has(.i360-navbar-row-marker) + * [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
  [data-testid="stElementContainer"]:has(.i360-navbar-row-marker) + [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
  [data-testid="stElementContainer"]:has(.i360-navbar-row-marker) + * [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{
    flex: 0 0 auto !important; width: auto !important; min-width: 0 !important; padding: 0 !important;
  }}
  /* Glowing green underline across the full width of the nav row. */
  [data-testid="element-container"]:has(.i360-navbar-row-marker) + [data-testid="stHorizontalBlock"]::after,
  [data-testid="element-container"]:has(.i360-navbar-row-marker) + * [data-testid="stHorizontalBlock"]::after,
  [data-testid="stElementContainer"]:has(.i360-navbar-row-marker) + [data-testid="stHorizontalBlock"]::after,
  [data-testid="stElementContainer"]:has(.i360-navbar-row-marker) + * [data-testid="stHorizontalBlock"]::after {{
    content: ""; position: absolute; left: 0; right: 0; bottom: 0;
    height: 1.5px; border-radius: 1px;
    background: linear-gradient(90deg, {COLORS['accent']}, #16C2B2, {COLORS['accent']});
    box-shadow: 0 0 7px 1px rgba(13,148,136,.5), 0 0 2px rgba(13,148,136,.85);
  }}

  /* Inactive tabs: real st.button()s, restyled as pills. */
  [data-testid="element-container"]:has(.i360-navtab-marker) + [data-testid="element-container"] button,
  [data-testid="stElementContainer"]:has(.i360-navtab-marker) + [data-testid="stElementContainer"] button {{
    height: auto !important; padding: 9px 22px !important; border-radius: 999px !important;
    background: {COLORS['card']} !important; border: 1px solid {COLORS['border']} !important;
    box-shadow: 0 1px 2px rgba(16,24,40,.06) !important;
    font-size: 14.5px !important; font-weight: 600 !important; letter-spacing: .2px;
    color: {COLORS['text']} !important;
    transition: background .15s, border-color .15s, box-shadow .15s, transform .15s;
  }}
  [data-testid="element-container"]:has(.i360-navtab-marker) + [data-testid="element-container"] button:hover,
  [data-testid="stElementContainer"]:has(.i360-navtab-marker) + [data-testid="stElementContainer"] button:hover {{
    background: {COLORS['accent_soft']} !important; border-color: {COLORS['accent']} !important;
    color: {COLORS['accent']} !important; transform: translateY(-1px);
  }}

  /* Active tab: a static styled label (not a button — clicking it again would be a no-op). */
  .i360-navtab-active {{
    display: inline-block; padding: 9px 22px; border-radius: 999px;
    background: {COLORS['accent']}; border: 1px solid {COLORS['accent']};
    box-shadow: 0 3px 8px rgba(13,148,136,.35);
    font-size: 14.5px; font-weight: 600; letter-spacing: .2px; color: #fff;
    white-space: nowrap;
  }}

  {"".join(tooltip_rules)}
</style>
"""


def render_navbar() -> str:
    """Renders the pill-tab row and returns the active tab's key. Call this once per
    script run, early, then branch on the returned key — the whole point is that only
    the branch matching the returned key should actually execute."""
    st.session_state.setdefault("active_tab", _DEFAULT_TAB)
    st.markdown(_build_css(), unsafe_allow_html=True)

    st.markdown('<span class="i360-navbar-row-marker"></span>', unsafe_allow_html=True)
    cols = st.columns(len(TABS))
    for col, tab in zip(cols, TABS):
        with col:
            st.markdown(f'<span class="i360-navtab-marker i360-navtab-marker-{tab["key"]}"></span>',
                        unsafe_allow_html=True)
            if st.session_state["active_tab"] == tab["key"]:
                st.markdown(f'<div class="i360-navtab-active">{tab["label"]}</div>', unsafe_allow_html=True)
            else:
                if st.button(tab["label"], key=f"nav_{tab['key']}"):
                    st.session_state["active_tab"] = tab["key"]
                    st.rerun()

    return st.session_state["active_tab"]
