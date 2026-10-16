"""
app.py
======
Streamlit entrypoint for Inventory360 — horizontal top tabs (Home,
Overview, Ask Inventory360, Storylines, BYOV, Smart Alerts, AI Accuracy,
Lineage, Glossary, Coming Soon).

Navigation is ui/navbar.py, NOT st.tabs(). st.tabs() is a purely visual
switch — Streamlit runs the code inside every `with tab:` block on every
single rerun regardless of which tab is actually visible, which meant
EVERY tab's queries (Glossary's DESCRIBE EXTENDED calls, Storylines/BYOV's
data-window queries, etc.) were firing on every single page load. navbar's
render_navbar() returns which tab is active via st.session_state, a real
value app.py can branch on below — so only the active tab's render
function, and therefore its queries, actually executes.

st.set_page_config() and inject_custom_css() must run exactly once, as
the first Streamlit calls in the whole script.

Ask Inventory360 and AI Accuracy are unchanged scripts (a sequence of
top-level Streamlit calls) — run in place via runpy so their logic
doesn't need to be rewritten into functions.
"""

import os
import runpy

import streamlit as st

from auth import bind_request_context
from ui.theme import inject_custom_css
from ui.navbar import render_navbar
from page_modules import (
    home_page, overview_page, self_service_page, alerts_page, ontology_page, glossary_page, coming_soon_page,
)

APP_DIR = os.path.dirname(os.path.abspath(__file__))

st.set_page_config(page_title="Inventory360", layout="wide")
# Capture this request's on-behalf-of user token (X-Forwarded-Access-Token) before any
# data access, so every SQL/Genie call in this rerun runs with the signed-in user's permissions.
bind_request_context()
inject_custom_css()

active_tab = render_navbar()

if active_tab == "home":
    home_page.render()

elif active_tab == "overview":
    overview_page.render()

elif active_tab == "chat":
    runpy.run_path(os.path.join(APP_DIR, "page_modules", "chat_page.py"), run_name="chat_page")

elif active_tab == "storylines":
    self_service_page.render_storylines()

elif active_tab == "byov":
    self_service_page.render_byov()

elif active_tab == "alerts":
    alerts_page.render()

elif active_tab == "testing":
    runpy.run_path(os.path.join(APP_DIR, "page_modules", "testing_page.py"), run_name="testing_page")

elif active_tab == "ontology":
    ontology_page.render()

elif active_tab == "glossary":
    glossary_page.render()

elif active_tab == "coming_soon":
    coming_soon_page.render()
