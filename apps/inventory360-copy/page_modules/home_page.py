"""
page_modules/home_page.py
===========================
Home tab — the app's default landing page: a card grid of every other
page (icon, title, one-line description, "Open" button), styled the
same way as page_modules/coming_soon_page.py's roadmap grid so the two
"tile grid" pages in the app look like one family.

Icon / label / description all come from ui.navbar.TABS — that's
already the single source of truth for what each page is called and
does (it drives the nav pill's hover tooltip), so this file doesn't
keep a second hand-written copy that could drift out of sync with it.
Reading TABS also means a new page added there shows up here for free.

Pure presentation plus session_state navigation — no data, no queries.
"""

import html

import streamlit as st

from ui.navbar import TABS
from ui.theme import COLORS

_CSS = f"""
<style>
  .i360-home-header {{
    background: linear-gradient(135deg, {COLORS['accent']} 0%, #0B7A70 100%);
    border-radius: 14px; padding: 28px 32px; margin-bottom: 26px;
    box-shadow: 0 4px 18px rgba(13,148,136,.25);
  }}
  .i360-home-header h2 {{
    color: #fff; margin: 0 0 6px 0; font-size: 22px; font-weight: 800; letter-spacing: -.2px;
  }}
  .i360-home-header p {{
    color: rgba(255,255,255,.88); margin: 0; font-size: 14px; max-width: 640px; line-height: 1.5;
  }}

  .i360-home-card {{
    position: relative; background: {COLORS['card']}; border: 1px solid {COLORS['border']};
    border-radius: 14px 14px 0 0; border-bottom: none; padding: 20px 20px 10px 20px;
    overflow: hidden; min-height: 168px;
  }}
  .i360-home-card::before {{
    content: ""; position: absolute; top: 0; left: 0; right: 0; height: 4px;
    background: linear-gradient(90deg, {COLORS['accent']}, {COLORS['blue']});
  }}
  .i360-home-icon {{
    width: 44px; height: 44px; border-radius: 12px; background: {COLORS['accent_soft']};
    display: flex; align-items: center; justify-content: center; font-size: 22px;
    font-weight: 600; color: {COLORS['accent']}; line-height: 1;
    margin-bottom: 12px;
  }}
  .i360-home-title {{
    font-size: 15px; font-weight: 700; color: {COLORS['text']};
    margin: 0 0 6px 0; line-height: 1.35;
  }}
  .i360-home-desc {{
    font-size: 12.5px; color: {COLORS['text_muted']}; line-height: 1.55; margin: 0;
  }}

  /* Hide the marker row, then restyle the button immediately after it so
     it reads as the bottom edge of the card above rather than a generic
     Streamlit button — same sibling-selector trick as ui/navbar.py. */
  [data-testid="element-container"]:has(.i360-home-btn-marker),
  [data-testid="stElementContainer"]:has(.i360-home-btn-marker) {{ display: none; }}

  [data-testid="element-container"]:has(.i360-home-btn-marker) + [data-testid="element-container"] button,
  [data-testid="stElementContainer"]:has(.i360-home-btn-marker) + [data-testid="stElementContainer"] button {{
    width: 100%; border-radius: 0 0 14px 14px !important;
    border: 1px solid {COLORS['border']} !important; border-top: none !important;
    background: {COLORS['bg_alt']} !important; color: {COLORS['accent']} !important;
    font-size: 12.5px !important; font-weight: 700 !important; padding: 8px 0 !important;
    margin-top: -1px;
  }}
  [data-testid="element-container"]:has(.i360-home-btn-marker) + [data-testid="element-container"] button:hover,
  [data-testid="stElementContainer"]:has(.i360-home-btn-marker) + [data-testid="stElementContainer"] button:hover {{
    background: {COLORS['accent']} !important; color: #fff !important; border-color: {COLORS['accent']} !important;
  }}
</style>
"""

_COLS = 3


def _card_html(tab: dict) -> str:
    return (
        '<div class="i360-home-card">'
        f'<div class="i360-home-icon">{tab["icon"]}</div>'
        f'<p class="i360-home-title">{html.escape(tab["label"])}</p>'
        f'<p class="i360-home-desc">{html.escape(tab["tip"])}</p>'
        "</div>"
    )


def render() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)

    st.markdown(
        '<div class="i360-home-header"><h2>👋 Welcome to Inventory360</h2>'
        "<p>Pick a page below — each one covers a different slice of inventory, allocation, "
        "and order data, from live KPIs to free-form Q&A.</p></div>",
        unsafe_allow_html=True,
    )

    pages = [t for t in TABS if t["key"] != "home"]
    for i in range(0, len(pages), _COLS):
        row = pages[i : i + _COLS]
        cols = st.columns(_COLS)
        for col, tab in zip(cols, row):
            with col:
                st.markdown(_card_html(tab), unsafe_allow_html=True)
                st.markdown('<span class="i360-home-btn-marker"></span>', unsafe_allow_html=True)
                if st.button(f"Open {tab['label']} →", key=f"home_open_{tab['key']}", use_container_width=True):
                    st.session_state["active_tab"] = tab["key"]
                    st.rerun()
