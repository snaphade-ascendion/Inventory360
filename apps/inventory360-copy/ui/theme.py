"""
ui/theme.py
============
Ports the Inventory360 mockup's visual design system (colors, panel/card
styling, badges, chat typography) into the Streamlit app via CSS injection.

Streamlit can't be pixel-matched to a hand-built HTML mockup — this is a
faithful port of the design LANGUAGE (color tokens, spacing, the specific
question/answer typography spec from the Goal doc), not a literal recreation
of every mockup element. Base theme colors also live in .streamlit/config.toml;
this module handles everything Streamlit's theme config can't reach directly
(panel shadows, badges, the accent-bordered answer treatment, etc.).

Call inject_custom_css() once, near the top of app.py, before rendering
anything else.
"""

import streamlit as st

# Color tokens — kept in sync with .streamlit/config.toml and the mockup's
# :root CSS variables. Single source of truth for anything referenced in
# Python (e.g. f-string-built HTML snippets elsewhere).
COLORS = {
    "bg": "#EEF0F3",
    "bg_alt": "#F7F8FA",
    "text": "#31333F",
    "text_muted": "#6E7079",
    "accent": "#0D9488",
    "accent_soft": "#E3F7F4",
    "border": "#E6E6E6",
    "card": "#FFFFFF",
    "green": "#1DB954",
    "blue": "#3B82F6",
    "gold": "#B8860B",
    "red": "#d9544f",
    "positive": "#15803D",  # solid dark green — used for positive numbers in
                            # LLM-generated text; kept in sync with
                            # prompts/markdown_style.py's POSITIVE_COLOR
    "negative": "#C0392B",  # solid red — same, kept in sync with
                            # prompts/markdown_style.py's NEGATIVE_COLOR
}

CUSTOM_CSS = f"""
<style>
  /* ---- Base page ---- */
  .stApp {{
    background: {COLORS['bg']};
  }}
  html, body, [class*="css"] {{
    font-family: "Source Sans Pro", "Segoe UI", -apple-system, sans-serif;
  }}

  /* ---- Panel / card treatment (matches mockup .panel) ---- */
  .i360-panel {{
    background: {COLORS['card']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 18px;
    box-shadow: 0 1px 2px rgba(0,0,0,.04);
  }}

  /* ---- Overview stat cards (matches mockup .metric) — explicit white
     background via custom class, NOT st.container(border=True). That
     native container's fill is unreliable across Streamlit versions
     (see the note below on why bordered containers are otherwise left
     alone) — same reasoning that already led show_work's expander and
     the chat Q&A boxes to use custom CSS instead of native styling. ---- */
  .i360-card {{
    background: {COLORS['card']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 14px 16px;
    box-shadow: 0 1px 2px rgba(0,0,0,.04);
    margin-bottom: 8px;
  }}
  .i360-card-label {{
    color: {COLORS['text_muted']};
    font-size: 12.5px;
    margin-bottom: 6px;
  }}
  .i360-card-value {{
    color: {COLORS['text']};
    font-size: 26px;
    font-weight: 700;
    line-height: 1.2;
  }}
  .i360-card-error {{
    color: {COLORS['red']};
    font-size: 11px;
    margin-top: 4px;
  }}
  .i360-card-delta {{
    font-size: 12px;
    font-weight: 700;
    margin-top: 4px;
  }}
  .i360-card-delta.positive {{ color: {COLORS['positive']}; }}
  .i360-card-delta.negative {{ color: {COLORS['negative']}; }}
  .i360-card-delta.neutral {{ color: {COLORS['text_muted']}; font-weight: 400; }}

  /* ---- Callout box (matches mockup .callout) ---- */
  .i360-callout {{
    background: {COLORS['accent_soft']};
    border-left: 3px solid {COLORS['accent']};
    padding: 12px 14px;
    border-radius: 4px;
    font-size: 13.5px;
    margin-bottom: 18px;
  }}

  /* ---- AI-generated badge (matches mockup .ai-badge) ---- */
  .i360-ai-badge {{
    display: inline-flex; align-items: center; gap: 4px; font-size: 10px;
    font-weight: 700; color: {COLORS['accent']}; background: {COLORS['accent_soft']};
    padding: 2px 8px; border-radius: 10px; margin-left: 8px; vertical-align: middle;
    letter-spacing: .2px;
  }}

  /* ---- In-scope / out-of-scope badges ---- */
  .i360-scope-in {{
    background: #E6F7EC; color: #12793F; font-size: 12.5px; font-weight: 700;
    padding: 7px 13px; border-radius: 8px; display: inline-flex; align-items: center;
    gap: 7px; width: fit-content;
  }}
  .i360-scope-out {{
    background: #FDEAEA; color: #B42318; font-size: 12.5px; font-weight: 700;
    padding: 7px 13px; border-radius: 8px; display: inline-flex; align-items: center;
    gap: 7px; width: fit-content;
  }}

  /* ---- Question / Answer: both as titled white containers, left-aligned.
     Answer is indented slightly and keeps a left accent border so it's
     visually distinguishable as the response, without heavy styling. ---- */
  .i360-qa-box {{
    background: {COLORS['card']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 14px 16px;
    margin-bottom: 14px;
    box-shadow: 0 1px 2px rgba(0,0,0,.04);
  }}
  .i360-qa-box.answer {{
    margin-left: 32px;
    border-left: 3px solid {COLORS['accent']};
  }}
  .i360-qa-title {{
    font-weight: 700;
    color: {COLORS['text']};
    text-align: left;
    font-size: 13px;
    margin-bottom: 6px;
  }}
  .i360-qa-content {{
    color: {COLORS['text']};
    font-size: 14px;
    font-weight: 400;
    line-height: 1.55;
    text-align: left;
  }}
  .i360-qa-content p {{ margin: 0 0 8px; }}
  .i360-qa-content > *:last-child {{ margin-bottom: 0; }}
  .i360-qa-content ul, .i360-qa-content ol {{ margin: 8px 0; padding-left: 22px; }}

  /* ---- Buttons (Streamlit's own st.button, restyled) ---- */
  .stButton > button {{
    background: {COLORS['accent']}; color: #fff; border: none; border-radius: 6px;
    padding: 8px 14px; font-size: 13px;
  }}
  .stButton > button:hover {{
    background: {COLORS['accent']}; opacity: 0.9; color: #fff;
  }}

  /* Bordered containers (st.container(border=True)) are left entirely to
     Streamlit's own native styling. Two things were tried and reverted:
     (1) restyling ALL of them via the shared
     [data-testid="stVerticalBlockBorderWrapper"] selector caused a visible
     double border/shadow; (2) scoping via a per-container key= and
     .st-key-<name> class crashed outright, because this app's Streamlit
     version predates the key= parameter on st.container(). Given two
     failed attempts without the ability to visually verify a fix here,
     this is intentionally left unstyled rather than risking a third. */

  /* ---- Expander ("Show work") styled like a panel ---- */
  div[data-testid="stExpander"] {{
    background: {COLORS['card']};
    border: 1px solid {COLORS['border']} !important;
    border-radius: 8px;
    box-shadow: 0 1px 2px rgba(0,0,0,.04);
  }}
  /* Bigger, bolder expander header text app-wide (Show work, Subject-Area
     Intelligence, Testing page tiles) — selector covers the summary text
     element across Streamlit versions that render it slightly differently. */
  div[data-testid="stExpander"] summary,
  div[data-testid="stExpander"] summary p {{
    font-size: 17px !important;
    font-weight: 700 !important;
  }}

  /* ---- Divider between turns, lighter than Streamlit default ---- */
  hr {{
    border-color: {COLORS['border']} !important;
  }}
  /* ---- Self-Service: decision line under a theme, and the evidence tables ---- */
  .i360-decision {{
    background: #FDECEC;
    border-left: 3px solid {COLORS['negative']};
    border-radius: 4px;
    padding: 12px 14px;
    margin: 10px 0 6px;
    font-size: 14.5px;
    line-height: 1.55;
  }}
  table.i360-evidence {{
    width: 100%; border-collapse: collapse; font-size: 12.5px; margin-bottom: 12px;
  }}
  table.i360-evidence th {{
    text-align: left; color: {COLORS['text_muted']}; font-weight: 700;
    border-bottom: 1px solid {COLORS['border']}; padding: 4px 8px;
  }}
  table.i360-evidence td {{ padding: 4px 8px; border-bottom: 1px solid {COLORS['bg_alt']}; }}
  /* ---- Strong section divider (Overview subject areas, Self-Service sections) ---- */
  hr.i360-divider-strong {{
    border: 0 !important;
    border-top: 3px solid #B7BDC6 !important;
    margin: 18px 0 22px !important;
    opacity: 1;
  }}

  /* ---- Main navigation (the top-level app.py tab bar) now lives entirely in
     ui/navbar.py — that file replaced st.tabs() with a real-state button row so
     inactive tabs' Python code (and queries) genuinely don't execute, which
     st.tabs() could never do. BYOV's own INTERNAL st.tabs() (Dimensions/Measures)
     still uses Streamlit's default nested-tab look below, untouched. ---- */

  /* ---- Storylines: Generate insights button pinned to the right of its row ---- */
  [class*="st-key-ss_generate"] {{ width: 100% !important; display: flex; justify-content: flex-end; }}

  /* ---- Self-Service theme tiles ----
     Unselected tiles are real st.button()s (so a click selects the theme), made to look like white cards.
     They are scoped with a hidden marker element rendered immediately BEFORE each button, so the Testing
     page's primary buttons and every other button in the app keep their normal teal style. The selected
     tile is a plain <div> with the same box, in the callout's light green. Uses :has(), supported by
     current Chrome / Edge / Safari / Firefox; on a browser without it the tiles simply stay teal buttons. */
  [data-testid="element-container"]:has(.i360-tile-marker),
  [data-testid="stElementContainer"]:has(.i360-tile-marker),
  .element-container:has(.i360-tile-marker) {{ display: none; }}

  [data-testid="element-container"]:has(.i360-tile-marker) + [data-testid="element-container"] button,
  [data-testid="stElementContainer"]:has(.i360-tile-marker) + [data-testid="stElementContainer"] button,
  .element-container:has(.i360-tile-marker) + .element-container button {{
    background: {COLORS['card']} !important; color: {COLORS['text']} !important;
    border: 1px solid {COLORS['border']} !important; border-radius: 8px;
    width: 100%; min-height: 66px; padding: 10px 12px;
    font-size: 14px; font-weight: 600; line-height: 1.3; opacity: 1;
    box-shadow: 0 1px 2px rgba(0,0,0,.04);
  }}
  [data-testid="element-container"]:has(.i360-tile-marker) + [data-testid="element-container"] button:hover,
  [data-testid="stElementContainer"]:has(.i360-tile-marker) + [data-testid="stElementContainer"] button:hover,
  .element-container:has(.i360-tile-marker) + .element-container button:hover {{
    border-color: {COLORS['accent']} !important; color: {COLORS['accent']} !important;
  }}
  .i360-tile-selected {{
    background: {COLORS['accent_soft']}; border: 1.5px solid {COLORS['accent']}; border-radius: 8px;
    min-height: 66px; padding: 10px 12px; box-sizing: border-box;
    display: flex; align-items: center; justify-content: center; text-align: center;
    font-size: 14px; font-weight: 700; line-height: 1.3; color: {COLORS['text']};
  }}

  /* ---- Chat page: "Popular questions" rail — small, clickable pills that stand out with a
     teal outline but stay light (no bold, no big button) so they read as quick suggestions,
     not primary actions. Same hidden-marker scoping technique as the theme tiles above, so
     only these buttons are affected. */
  [data-testid="element-container"]:has(.i360-popq-marker),
  [data-testid="stElementContainer"]:has(.i360-popq-marker),
  .element-container:has(.i360-popq-marker) {{ display: none; }}

  [data-testid="element-container"]:has(.i360-popq-marker) + [data-testid="element-container"] button,
  [data-testid="stElementContainer"]:has(.i360-popq-marker) + [data-testid="stElementContainer"] button,
  .element-container:has(.i360-popq-marker) + .element-container button {{
    background: {COLORS['card']} !important; color: {COLORS['accent']} !important;
    border: 1px solid {COLORS['accent']} !important; border-radius: 999px !important;
    padding: 3px 12px !important; font-size: 12px !important; font-weight: 400 !important;
    box-shadow: none !important; min-height: 0 !important; line-height: 1.6;
  }}
  [data-testid="element-container"]:has(.i360-popq-marker) + [data-testid="element-container"] button:hover,
  [data-testid="stElementContainer"]:has(.i360-popq-marker) + [data-testid="stElementContainer"] button:hover,
  .element-container:has(.i360-popq-marker) + .element-container button:hover {{
    background: {COLORS['accent_soft']} !important; opacity: 1 !important;
  }}

  /* ---- Self-Service "Ask" box: the one st.form in the app, styled to stand out ---- */
  [data-testid="stForm"], .i360-ask-box {{
    background: {COLORS['accent_soft']};
    border: 2px solid {COLORS['accent']} !important;
    border-radius: 10px;
    padding: 16px 18px;
    box-shadow: 0 2px 6px rgba(13,148,136,.15);
  }}
  .i360-ask-box {{ margin-bottom: 14px; }}
</style>
"""


def inject_custom_css() -> None:
    """Call once near the top of app.py, before any other rendering."""
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def callout(html_content: str, ai_generated: bool = False) -> None:
    badge = '<span class="i360-ai-badge">✨ AI-generated</span>' if ai_generated else ""
    st.markdown(f'<div class="i360-callout">{html_content}{badge}</div>', unsafe_allow_html=True)