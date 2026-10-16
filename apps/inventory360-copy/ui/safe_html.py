"""
ui/safe_html.py
================
The two helpers every st.markdown(..., unsafe_allow_html=True) call must use for
anything that is not a hard-coded literal:

  esc(value)               -> for user input, query results, UC metadata (table/column
                              comments), exception text. Everything is escaped; no
                              markup survives.

  sanitize_llm_html(text)  -> for LLM output that is SUPPOSED to contain the small set
                              of formatting tags prompts/markdown_style.py asks for
                              (<b>, <span style="color:..; font-weight:..">, <p>, <ul>,
                              <li> ...). Allowlist-based: every other tag is removed,
                              every attribute except a filtered `style` on <span> is
                              removed, script/style/iframe/svg/... are removed together
                              with their contents, and all text is HTML-escaped.
                              Markdown images (![](url)) are neutralised so a
                              prompt-injected answer can't load a tracking/exfiltration
                              URL.

Why not rely on the router / prompt: the user's question is rendered before the router
runs, an injection payload can be wrapped in an on-topic question, and LLM output can be
steered by the input. Output encoding at the render site is the control that holds.

Standard library only (no new dependency to vet for the Marketplace review).
"""

import html
import re
from html.parser import HTMLParser

ALLOWED_TAGS = {"p", "br", "ul", "ol", "li", "b", "strong", "i", "em", "u", "span", "code", "sup", "sub"}
VOID_TAGS = {"br"}
# Removed together with everything inside them.
DROP_CONTENT_TAGS = {
    "script", "style", "iframe", "frame", "frameset", "object", "embed", "noscript",
    "template", "svg", "math", "textarea", "select", "title", "head",
}
_ALLOWED_CSS_PROPS = {"color", "font-weight", "font-style", "background-color", "text-decoration"}
# Hex colours, keywords (bold, italic, red, underline), numeric weights, rgb()/rgba().
# No parentheses other than rgb/rgba, so url(), expression(), var() etc. can't pass.
_CSS_VALUE_RE = re.compile(r"^(#[0-9a-fA-F]{3,8}|[a-zA-Z-]{1,20}|[1-9]00|rgba?\(\s*[\d.\s,%]+\))$")


def esc(value) -> str:
    """Escape any value for safe insertion into HTML text or a quoted attribute."""
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _clean_style(style: str) -> str:
    kept = []
    for decl in (style or "").split(";"):
        if ":" not in decl:
            continue
        prop, val = decl.split(":", 1)
        prop, val = prop.strip().lower(), val.strip()
        if prop in _ALLOWED_CSS_PROPS and _CSS_VALUE_RE.match(val):
            kept.append(f"{prop}:{val}")
    return "; ".join(kept)


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[str] = []
        self.drop_depth = 0

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t in DROP_CONTENT_TAGS:
            self.drop_depth += 1
            return
        if self.drop_depth or t not in ALLOWED_TAGS:
            return
        attr_str = ""
        if t == "span":
            style = next((v for k, v in attrs if k.lower() == "style" and v), "")
            cleaned = _clean_style(style)
            if cleaned:
                attr_str = f' style="{html.escape(cleaned, quote=True)}"'
        self.out.append(f"<{t}{attr_str}>")
        if t not in VOID_TAGS:
            self.stack.append(t)

    def handle_startendtag(self, tag, attrs):
        t = tag.lower()
        if t in DROP_CONTENT_TAGS:
            return  # self-closing <svg/> etc.: nothing to drop, and must not open a drop scope
        self.handle_starttag(tag, attrs)
        if t in ALLOWED_TAGS and t not in VOID_TAGS and not self.drop_depth:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in DROP_CONTENT_TAGS:
            self.drop_depth = max(0, self.drop_depth - 1)
            return
        if self.drop_depth or t not in self.stack:
            return
        while self.stack:  # close anything left open inside it, keeping the output well-formed
            top = self.stack.pop()
            self.out.append(f"</{top}>")
            if top == t:
                break

    def handle_data(self, data):
        if self.drop_depth:
            return
        text = html.escape(data, quote=False)
        self.out.append(text.replace("![", "!\\["))  # neutralise markdown images

    # Comments, doctypes, processing instructions: dropped (default handlers do nothing).

    def result(self) -> str:
        return "".join(self.out) + "".join(f"</{t}>" for t in reversed(self.stack))


def sanitize_llm_html(text) -> str:
    """Allowlist-sanitise LLM output that may legitimately contain simple formatting HTML."""
    if not text:
        return ""
    parser = _Sanitizer()
    parser.feed(str(text))
    parser.close()
    return parser.result()
