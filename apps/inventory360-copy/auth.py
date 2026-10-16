"""
auth.py
=======
Single shared entry point for Databricks SDK auth. Two identities:

  get_user_client()  -> ON-BEHALF-OF the signed-in user (OBO). Used for every
                        business-data SQL query and every Genie call, so Unity
                        Catalog permissions, row filters and column masks are
                        enforced per user. Built from the X-Forwarded-Access-Token
                        header the Databricks Apps proxy injects when user
                        authorization (scopes: sql, genie) is enabled on the app.

  get_app_client()   -> the app's service principal. Used ONLY for:
                          - model-serving (LLM) calls (OBO scopes don't cover them)
                          - the app's own state tables (test_*, alert_audit,
                            overview_insight_runs, self_service_theme_runs,
                            asked_questions) via sql_client.run_app_sql()

Fail-closed: inside a Databricks App, if the user token is missing,
get_user_client() raises MissingUserTokenError instead of silently falling back
to the service principal. Outside an App (scheduled job, local dev) there is no
end user, so it uses the ambient/default credentials.

Threads: Streamlit only exposes request headers on the script thread, so the
token is bound into a contextvar once per rerun (bind_request_context(), called
from app.py) and worker threads must be started with ContextThreadPoolExecutor
so they inherit it.

Caching: st.cache_data is shared across ALL sessions of the app process. Any
cached function that reads business data through the user client must use
@user_cache_data so results are keyed per user and never served to someone
with different permissions.
"""

import contextvars
import functools
import hashlib
import os
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from databricks.sdk import WorkspaceClient

_TOKEN_HEADER = "x-forwarded-access-token"
_EMAIL_HEADERS = ("x-forwarded-email", "x-forwarded-preferred-username")
_MAX_USER_CLIENTS = 256  # LRU bound; tokens are short-lived and rotate

_user_token: contextvars.ContextVar = contextvars.ContextVar("i360_user_token", default=None)
_user_email: contextvars.ContextVar = contextvars.ContextVar("i360_user_email", default=None)

_app_client = None
_app_client_lock = threading.Lock()
_user_clients: "OrderedDict[str, WorkspaceClient]" = OrderedDict()
_user_clients_lock = threading.Lock()


class MissingUserTokenError(PermissionError):
    """Raised inside a Databricks App when no on-behalf-of user token is available."""


def running_in_databricks_app() -> bool:
    return bool(os.environ.get("DATABRICKS_APP_NAME"))


# ---------------------------------------------------------------------
# Request context (token + email), bound per Streamlit rerun
# ---------------------------------------------------------------------
def _request_headers() -> dict:
    try:
        import streamlit as st
        return {str(k).lower(): v for k, v in dict(st.context.headers).items()}
    except Exception:
        return {}


def _email_from(headers: dict) -> str | None:
    return next((str(headers[h]).strip() for h in _EMAIL_HEADERS if headers.get(h)), None)


def bind_request_context() -> None:
    """Call once at the top of every script run (app.py). Captures the caller's
    OBO token and email into contextvars so worker threads started with
    ContextThreadPoolExecutor (and LangGraph nodes) can see them."""
    headers = _request_headers()
    _user_token.set(headers.get(_TOKEN_HEADER) or None)
    _user_email.set(_email_from(headers))


def _current_token() -> str | None:
    return _user_token.get() or _request_headers().get(_TOKEN_HEADER) or None


def _token_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def current_user_scope() -> str:
    """Stable per-user key for caches. Never contains the raw token."""
    email = _user_email.get() or _email_from(_request_headers())
    if email:
        return email.lower()
    token = _current_token()
    if token:
        return "tok:" + _token_key(token)[:24]
    return "__app__"


# ---------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------
def get_app_client() -> WorkspaceClient:
    """Shared WorkspaceClient using the app's service principal (or ambient auth
    outside Apps). Double-checked locking because the first page load can hit this
    from several worker threads at once."""
    global _app_client
    if _app_client is None:
        with _app_client_lock:
            if _app_client is None:
                _app_client = WorkspaceClient()
    return _app_client


# Backward-compatible alias (dev scripts). Deliberately the SERVICE PRINCIPAL —
# do not use it for business-data reads; use get_user_client().
get_workspace_client = get_app_client


def get_user_client() -> WorkspaceClient:
    """WorkspaceClient acting on behalf of the signed-in user."""
    token = _current_token()
    if not token:
        if running_in_databricks_app():
            raise MissingUserTokenError(
                "No user access token on this request. Enable user authorization on the app "
                "(scopes: sql, genie) and make sure worker threads use ContextThreadPoolExecutor."
            )
        return get_app_client()  # scheduled job / local dev: no end user

    key = _token_key(token)
    with _user_clients_lock:
        client = _user_clients.get(key)
        if client is not None:
            _user_clients.move_to_end(key)
            return client

    # auth_type="pat" pins the SDK to the bearer token so it ignores the app's
    # DATABRICKS_CLIENT_ID/SECRET env vars (otherwise it would see two auth methods).
    client = WorkspaceClient(host=get_app_client().config.host, token=token, auth_type="pat")
    with _user_clients_lock:
        _user_clients[key] = client
        _user_clients.move_to_end(key)
        while len(_user_clients) > _MAX_USER_CLIENTS:
            _user_clients.popitem(last=False)
    return client


# ---------------------------------------------------------------------
# Helpers for threads and caches
# ---------------------------------------------------------------------
class ContextThreadPoolExecutor(ThreadPoolExecutor):
    """ThreadPoolExecutor whose tasks run in a copy of the submitter's contextvars,
    so the OBO token bound by bind_request_context() reaches worker threads.
    map() goes through submit(), so it is covered too."""

    def submit(self, fn, /, *args, **kwargs):
        ctx = contextvars.copy_context()  # one copy per task: a Context can't be entered by two threads
        return super().submit(ctx.run, fn, *args, **kwargs)


def user_cache_data(**cache_kwargs):
    """Drop-in replacement for @st.cache_data that adds the current user to the cache
    key, so one user's query results are never returned to another user."""
    import streamlit as st

    def decorator(fn):
        def _scoped(user_scope, *args, **kwargs):
            return fn(*args, **kwargs)

        # Streamlit keys its cache on module + qualname + source; give each wrapped
        # function a distinct identity so they don't share one cache.
        _scoped.__module__ = fn.__module__
        _scoped.__name__ = f"{fn.__name__}__user_scoped"
        _scoped.__qualname__ = f"{fn.__qualname__}__user_scoped"
        cached = st.cache_data(**cache_kwargs)(_scoped)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return cached(current_user_scope(), *args, **kwargs)

        wrapper.clear = cached.clear
        return wrapper

    return decorator
