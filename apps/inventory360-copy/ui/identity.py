"""
ui/identity.py
================
Who is using the app? Databricks Apps puts the signed-in user's identity in request headers
(X-Forwarded-Email / X-Forwarded-Preferred-Username). Streamlit exposes request headers as
st.context.headers (1.37+); older versions expose them through a private websocket-headers helper.
Falls back to "app_user" (the value the testing rows already use) if neither yields a header,
e.g. when running locally.
"""

import streamlit as st

ANONYMOUS = "app_user"
_HEADER_NAMES = ("x-forwarded-email", "x-forwarded-preferred-username")


def _headers() -> dict:
    try:
        return dict(st.context.headers)  # Streamlit >= 1.37
    except Exception:
        pass
    try:
        from streamlit.web.server.websocket_headers import _get_websocket_headers  # older Streamlit
        return dict(_get_websocket_headers() or {})
    except Exception:
        return {}


def email_from_headers(headers: dict) -> str:
    lowered = {str(k).lower(): v for k, v in headers.items()}
    for name in _HEADER_NAMES:
        value = lowered.get(name)
        if value:
            return str(value).strip()
    return ANONYMOUS


def display_name_from_email(email: str) -> str:
    """Best-effort friendly label from an email's local part ('jane.doe' -> 'Jane Doe').
    Not verified directory data — there is no name field in the forwarded headers."""
    if email == ANONYMOUS or "@" not in email:
        return email
    local = email.split("@", 1)[0]
    return " ".join(w.capitalize() for w in local.replace(".", " ").replace("_", " ").split()) or email


def get_current_user_email() -> str:
    """Cached per browser session (headers don't change mid-session)."""
    if "current_user_email" not in st.session_state:
        st.session_state["current_user_email"] = email_from_headers(_headers())
    return st.session_state["current_user_email"]
