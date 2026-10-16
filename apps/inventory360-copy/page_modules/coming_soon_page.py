"""
page_modules/coming_soon_page.py
==================================
"Coming Soon" tab: a fancy, on-brand card grid previewing features not
yet built. Pure presentation — no data, no queries — so this file is
just the roadmap content plus styled HTML.
"""

import html

import streamlit as st

from ui.theme import COLORS

ROADMAP = [
    {
        "icon": "🕸️",
        "title": "Knowledge Graph Explorer",
        "description": (
            "A true ontology layer on top of today's Lineage tab — subclass hierarchies, named "
            "semantic relationships, and a glossary of definitions, beyond the fact/dimension "
            "model and Bronze → Silver → Gold trace already live there."
        ),
    },
    {
        "icon": "💬",
        "title": "More Collaborative Features",
        "description": (
            "Share content via email, leave comments on an insight, and loop teammates into "
            "the conversation directly from the app."
        ),
    },
    {
        "icon": "🎭",
        "title": "Persona-Based Views",
        "description": (
            "Dashboards and language tailored to the role looking at them — planner, store "
            "ops, merchandising, or executive — each surfacing what matters most to them first."
        ),
    },
    {
        "icon": "🧭",
        "title": "Explain with Inventory360",
        "description": (
            "Ask \"why\" behind any number on the app and get a narrated, data-backed "
            "explanation, not just the figure itself."
        ),
    },
    {
        "icon": "🪄",
        "title": "Context-Aware AI-Generated Charts",
        "description": (
            "Charts the AI builds on the fly, shaped to the question you just asked — not a "
            "fixed chart type picked in advance."
        ),
    },
]

_CSS = f"""
<style>
  .i360-roadmap-header {{
    background: linear-gradient(135deg, {COLORS['accent']} 0%, #0B7A70 100%);
    border-radius: 14px; padding: 28px 32px; margin-bottom: 26px;
    box-shadow: 0 4px 18px rgba(13,148,136,.25);
  }}
  .i360-roadmap-header h2 {{
    color: #fff; margin: 0 0 6px 0; font-size: 22px; font-weight: 800; letter-spacing: -.2px;
  }}
  .i360-roadmap-header p {{
    color: rgba(255,255,255,.88); margin: 0; font-size: 14px; max-width: 640px; line-height: 1.5;
  }}

  .i360-roadmap-grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 18px;
  }}

  .i360-roadmap-card {{
    position: relative; background: {COLORS['card']}; border: 1px solid {COLORS['border']};
    border-radius: 14px; padding: 22px 22px 20px 22px; overflow: hidden;
    transition: transform .15s ease, box-shadow .15s ease, border-color .15s ease;
  }}
  .i360-roadmap-card:hover {{
    transform: translateY(-3px); border-color: {COLORS['accent']};
    box-shadow: 0 10px 24px rgba(16,24,40,.10);
  }}
  .i360-roadmap-card::before {{
    content: ""; position: absolute; top: 0; left: 0; right: 0; height: 4px;
    background: linear-gradient(90deg, {COLORS['accent']}, {COLORS['blue']});
  }}

  .i360-roadmap-icon {{
    width: 46px; height: 46px; border-radius: 12px; background: {COLORS['accent_soft']};
    display: flex; align-items: center; justify-content: center; font-size: 22px;
    margin-bottom: 14px;
  }}

  .i360-roadmap-title {{
    font-size: 15.5px; font-weight: 700; color: {COLORS['text']};
    margin: 0 0 8px 0; line-height: 1.35;
  }}
  .i360-roadmap-desc {{
    font-size: 13px; color: {COLORS['text_muted']}; line-height: 1.6; margin: 0;
  }}

  .i360-roadmap-footer {{
    margin-top: 24px; text-align: center; font-size: 12.5px; color: {COLORS['text_muted']};
  }}
</style>
"""


def _card_html(item: dict, index: int) -> str:
    return (
        '<div class="i360-roadmap-card">'
        f'<div class="i360-roadmap-icon">{item["icon"]}</div>'
        f'<p class="i360-roadmap-title">{index}. {html.escape(item["title"])}</p>'
        f'<p class="i360-roadmap-desc">{html.escape(item["description"])}</p>'
        "</div>"
    )


def render() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)

    st.markdown(
        '<div class="i360-roadmap-header">'
        "<h2>What's next for Inventory360</h2>"
        "<p>A look at what the team is exploring next — not yet live, but on the roadmap.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    cards_html = "".join(_card_html(item, i) for i, item in enumerate(ROADMAP, start=1))
    st.markdown(f'<div class="i360-roadmap-grid">{cards_html}</div>', unsafe_allow_html=True)

    st.markdown(
        '<div class="i360-roadmap-footer">Have a feature you\'d like to see here? '
        "Let the Inventory360 team know.</div>",
        unsafe_allow_html=True,
    )
