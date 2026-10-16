"""
self_service/ask.py
=====================
"Ask the data": send the pivot table the user built (plus the date range,
the row/value selections and the data notes) to the synthesis LLM together
with their question. Text answers only for now — chart generation is a
later step (a request for a chart gets a text answer plus a pointer).

The model is told to answer ONLY from the table it is given, and is given
the number of rows it was NOT shown, so it can't present a top-N excerpt
as a full total.
"""

import datetime as dt

from llm_client import ask_llm
from prompts.markdown_style import MARKDOWN_STYLE_INSTRUCTIONS
from self_service.dates import format_range
from self_service.pivot_engine import PivotResult, format_value

MAX_PROMPT_ROWS = 150

ASK_SYSTEM_PROMPT = f"""You are a data analyst inside Inventory360, a sporting goods retailer's inventory analytics app.
The user built a table (rows = dimensions, values = measures) and is asking a question about it.

Rules:
- Answer ONLY from the table provided. Do not use outside knowledge of the company, and do not guess values that
  are not in the table.
- If the table cannot answer the question, say so in one sentence and say which dimension or measure the user
  would need to add (use the names as shown in the app).
- If the table was truncated (you are told how many rows were not shown), never present a total, average or
  ranking as covering all rows; say it is based on the rows shown.
- Percentages are shown as percentages. Do not do arithmetic on already-averaged rates unless you say it is a
  simple (unweighted) average.
- If the user asks for a chart or graph, say chart generation is coming soon, then answer their underlying
  question in text.
- Be concise: at most about 120 words. Lead with the answer.

Output format: short HTML only — use <p> paragraphs and, if needed, <ul><li> lists. No Markdown.

{MARKDOWN_STYLE_INSTRUCTIONS}
Your response is plain text (HTML tags, not JSON), so a single \\$ is correct for a dollar sign.
"""


def _table_csv(result: PivotResult, max_rows: int) -> tuple[str, int]:
    kinds = dict(result.measure_cols)
    df = result.df.head(max_rows)
    lines = [" | ".join(df.columns)]
    for _, row in df.iterrows():
        cells = []
        for col in df.columns:
            cells.append(format_value(row[col], kinds[col]) if col in kinds else str(row[col]))
        lines.append(" | ".join(cells))
    return "\n".join(lines), max(len(result.df) - len(df), 0)


def ask_about_table(question: str, result: PivotResult, start: dt.date, end: dt.date) -> str:
    table_text, hidden = _table_csv(result, MAX_PROMPT_ROWS)
    context = (
        f"Date range selected: {format_range(start, end)}\n"
        f"Rows (dimensions): {', '.join(result.dim_cols)}\n"
        f"Values (measures): {', '.join(name for name, _ in result.measure_cols)}\n"
        f"Total rows in the table: {len(result.df)}; rows not shown to you: {hidden}\n"
        f"Data notes: {' '.join(result.notes) if result.notes else 'none'}\n\n"
        f"Table:\n{table_text}"
    )
    messages = [
        {"role": "system", "content": ASK_SYSTEM_PROMPT},
        {"role": "user", "content": f"{context}\n\nQuestion: {question}"},
    ]
    return ask_llm(messages, call_site="synthesis", temperature=0.0, max_tokens=1024).strip()
