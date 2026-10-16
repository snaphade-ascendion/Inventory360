"""
insights/formatter.py
=======================
Supports the Key Callouts "Edit" dialog on the Overview page:

  1. to_plain_text(html) strips a callout's HTML formatting (the <b>/
     <span style="color:..."> markup prompts/markdown_style.py's rules
     produce) down to plain text, for showing in an editable textarea —
     a human editing "<b>97.9%</b>" directly would otherwise have to
     type HTML by hand, or risk breaking the markup.

  2. reformat_callouts() sends the human-edited plain-text lines back
     through an LLM call that re-applies those same formatting rules
     (bold flat numbers, green/red for better/worse changes) — same
     prompt contract insights/supervisor.py uses to generate callouts
     the first time, just pointed at edited text instead of raw agent
     output. The model is told not to change wording, only add markup,
     so the human's edit is what gets saved either way.

No version history here — the caller (overview_page.py) just
overwrites the latest run's key_callouts and re-displays it. Versioning
can be layered on later without changing this module's contract.
"""

import html
import json
import re

from llm_client import ask_llm_json
from prompts.markdown_style import MARKDOWN_STYLE_INSTRUCTIONS

_TAG_RE = re.compile(r"<[^>]+>")

REFORMAT_SYSTEM_PROMPT = f"""You are the formatting pass for Inventory360's Overview
dashboard "Key Callouts" box. You are given a JSON array of plain-text callout
sentences that a human analyst just hand-edited — the wording is final and
intentional.

Your ONLY job is to apply the output formatting rules below to numbers in each
sentence. Do not rewrite, shorten, reorder, add, or remove any sentence, and do not
change any wording or number value — only wrap numbers in the HTML markup the rules
describe. If a sentence has no numbers, return it completely unchanged (as plain text,
no markup added). Return exactly as many callouts, in the exact same order, as you
were given.

{MARKDOWN_STYLE_INSTRUCTIONS}

Respond with exactly one JSON object and nothing else:
{{"formatted_callouts": ["<callout 1>", "<callout 2>", ...]}}
"""


def to_plain_text(callout_html: str) -> str:
    """Strip HTML tags and unescape entities, e.g. '<b>97.9%</b> on-time' ->
    '97.9% on-time'. Lossy by design — the whole point is a clean, retypeable
    starting point for the edit dialog, not a round-trippable representation."""
    return html.unescape(_TAG_RE.sub("", callout_html)).strip()


def reformat_callouts(plain_texts: list[str]) -> list[str]:
    """
    Re-applies MARKDOWN_STYLE_INSTRUCTIONS formatting to a list of
    human-edited plain-text callouts. Returns the formatted list in the
    same order. Falls back to the plain text itself (unformatted, but
    never dropped) for any callout the model fails to return correctly,
    rather than failing the whole save over one bad line.
    """
    plain_texts = [t.strip() for t in plain_texts if t.strip()]
    if not plain_texts:
        return []

    messages = [
        {"role": "system", "content": REFORMAT_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(plain_texts)},
    ]

    try:
        parsed = ask_llm_json(messages, call_site="synthesis", temperature=0.0)
        formatted = parsed.get("formatted_callouts", [])
    except Exception:
        formatted = []

    if len(formatted) != len(plain_texts):
        # Model dropped/added a line, or the call failed outright — fall back
        # to the plain-text version per-line rather than losing an edit or
        # silently misaligning which formatted sentence belongs to which.
        return [formatted[i] if i < len(formatted) else plain_texts[i] for i in range(len(plain_texts))]

    return formatted
