"""
prompts/markdown_style.py
============================
Shared output-formatting instructions, appended to every system prompt
whose output is rendered directly in the app (chat synthesis, the 5
insight agents, the supervisor's Key Callouts). One place to change the
rule/colors so all 3 stay visually consistent — see llm_client.py's
ENDPOINTS pattern for why "one shared place" matters here too.

Every render site for this text uses unsafe_allow_html=True (chat's
qa-box, the Key Callouts box, the Subject-Area Intelligence summaries/
bullets), so HTML spans in the LLM's own output render directly — this
is deliberately NOT a Python post-processing regex. Sentiment ("is this
number good or bad news") is exactly the kind of judgment an LLM makes
far more reliably than a keyword-matching heuristic would.

Colors match ui/theme.py — POSITIVE_COLOR/NEGATIVE_COLOR there are the
single source of truth; keep this string in sync if those change.
"""

POSITIVE_COLOR = "#15803D"  # solid dark green
NEGATIVE_COLOR = "#C0392B"  # solid red

MARKDOWN_STYLE_INSTRUCTIONS = f"""
## Output Formatting (apply throughout your entire response)

Your response is inserted directly inside a raw HTML container in the app (a <div>),
not rendered as a normal standalone Markdown document. IMPORTANT CONSEQUENCE: Markdown
syntax like **bold** or *italic* will NOT render inside that container — it will show
up as literal asterisks on the page, which looks broken. For this reason:

- NEVER use Markdown emphasis syntax (**bold**, *italic*, __bold__) anywhere in your
  response, for any reason, including for words as well as numbers. Zero exceptions.
- Use ONLY literal HTML tags for all emphasis — <b>...</b>, <span style="...">...</span>.
  These always render correctly in this container, unlike Markdown syntax.
- Escape every literal dollar sign as \\$ (backslash immediately before the $) — even
  inside an HTML tag, a bare $ can trigger Markdown math-mode. Write \\$1.2M, never $1.2M.
  EXCEPTION — if your entire response must be a single JSON object (see any other
  instructions in this prompt about JSON output): JSON syntax itself requires a literal
  backslash to be written as two backslashes (\\\\). So inside a JSON string value, write
  \\\\$ (backslash, backslash, dollar) to produce the single escaped \\$ that survives
  JSON parsing. A single backslash directly before $ inside JSON text is INVALID JSON
  and will make your entire response fail to parse. If your response is plain text (not
  JSON), a single \\$ is correct as described above.
- If a number represents a positive change, increase, growth, or improvement, wrap it
  (the number and its unit/%/\\$ sign only, not surrounding words) in:
  <span style="color:{POSITIVE_COLOR}; font-weight:700">1.2%</span>
- If a number represents a negative change, decrease, decline, or drop, wrap it the same
  way in:
  <span style="color:{NEGATIVE_COLOR}; font-weight:700">1.2%</span>
- Every OTHER number — a flat snapshot value with no inherent positive/negative
  direction (e.g. "97.9% on-time" with no trend implied) — wrap in <b>97.9%</b> instead.
  Never leave a bare, unstyled number anywhere in your response.
- Wrap only the number + its unit, never the whole surrounding sentence or clause.
- Do not apply any of this to non-numeric text.

Example of correct output (note: zero ** anywhere, only real HTML tags):
"On-time ship rate is <b>97.9%</b>, up from last period at
<span style="color:{POSITIVE_COLOR}; font-weight:700">96.1%</span>. Ship-from-store fell
to <span style="color:{NEGATIVE_COLOR}; font-weight:700">6.3%</span> from 9.1%."
"""
