"""
self_service/export.py
========================
Excel download for the pivot table. Numbers are written as real numbers
(percentages as fractions with a % cell format, currency with $), not as
formatted text, so the file works in Excel formulas / pivots. A second sheet
records the date range, selections and data notes so the file is
self-explanatory after it is emailed around.

Needs `openpyxl` (added to requirements.txt). If it isn't installed the
download falls back to CSV rather than failing.
"""

import datetime as dt
import io

from self_service.dates import format_range
from self_service.pivot_engine import PivotResult

_NUMBER_FORMATS = {
    "pct1": "0.0%", "pct2": "0.0%", "int": "#,##0", "num1": "#,##0.0",
    "num2": "#,##0.00", "cur0": "$#,##0", "cur2": "$#,##0.00",
}
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def to_download(result: PivotResult, start: dt.date, end: dt.date) -> tuple[bytes, str, str]:
    """Returns (file bytes, file extension, mime type)."""
    try:
        import openpyxl  # noqa: F401
        from openpyxl.utils import get_column_letter
    except ImportError:
        return result.df.to_csv(index=False).encode("utf-8"), "csv", "text/csv"

    import pandas as pd

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        result.df.to_excel(writer, sheet_name="Data", index=False)
        ws = writer.sheets["Data"]
        kinds = dict(result.measure_cols)
        for idx, col in enumerate(result.df.columns, start=1):
            letter = get_column_letter(idx)
            width = max(len(str(col)), *(len(str(v)) for v in result.df[col].head(200))) if len(result.df) else len(str(col))
            ws.column_dimensions[letter].width = min(max(width + 2, 12), 45)
            if col in kinds:
                for cell in ws[letter][1:]:
                    cell.number_format = _NUMBER_FORMATS.get(kinds[col], "General")
        ws.freeze_panes = "A2"

        about = [
            ("Source", "Inventory360 Self-Service"),
            ("Date range", format_range(start, end)),
            ("Rows (dimensions)", ", ".join(result.dim_cols)),
            ("Values (measures)", ", ".join(n for n, _ in result.measure_cols)),
            ("Row count", len(result.df)),
            ("Exported", dt.datetime.now().strftime("%Y-%m-%d %H:%M")),
        ] + [("Note", n) for n in result.notes]
        pd.DataFrame(about, columns=["Item", "Value"]).to_excel(writer, sheet_name="About", index=False)
        writer.sheets["About"].column_dimensions["A"].width = 22
        writer.sheets["About"].column_dimensions["B"].width = 110
    return buf.getvalue(), "xlsx", XLSX_MIME
