"""
sharing/compose.py
===================
Builds the content behind the Overview page's "Share" feature: a
downloadable PNG summarizing the components the user selected (Key
Callouts / Metric Cards / Subject-Area Intelligence, any combination).

Subject-Area Intelligence sections can now carry real chart images, not
just text. Charts are exported server-side via vl-convert-python — a
pure Rust binary with zero browser dependency, confirmed to render
Altair/Vega-Lite specs straight to PNG bytes in-process. (We deliberately
did NOT switch the app to Plotly for this: Plotly's equivalent export
path, kaleido, requires an actual Chrome install, which is heavier and
exactly the kind of infra cost vl-convert avoids.) A failed chart export
never fails the whole download — it's just left out of that section.

Download-only by design (no mailto/email) — an earlier version's
auto-opened mailto: link caused a browser-level dialog that left card
tooltips stuck visible app-wide, and the script-triggered auto-download
was unreliable in some hosting setups. A plain st.download_button avoids
both.
"""

from __future__ import annotations

import datetime as dt
import html as _html
import io
import re

from PIL import Image, ImageDraw, ImageFont

ACCENT_RGB = (13, 148, 136)
INK_RGB = (31, 35, 40)

SELECTION_LABELS = {
    "callouts": "Key Callouts",
    "cards": "Metric Cards",
    "subject_areas": "Subject-Area Intelligence",
}

_TAG_RE = re.compile(r"<[^>]+>")

# Chart spec width before vl-convert rasterizes it (scale=2 below doubles the
# actual pixel count for crispness); the final placed size is re-scaled to fit
# the canvas exactly, so this is just a reasonable native-resolution starting point.
_CHART_SPEC_WIDTH = 760
_CHART_EXPORT_SCALE = 2


def plain_text(text: str) -> str:
    """Key Callouts / Subject-Area summaries come straight from the LLM, which is
    instructed (prompts/markdown_style.py) to wrap numbers in literal HTML — <b>…</b>,
    <span style="color:...">…</span> — for the app's own HTML-rendered boxes. That's
    correct for the app, but this image is plain-drawn text, so the raw tags/markdown
    need stripping or they show up as literal "<b>", "<span style=..." on the image.
    Public (no leading underscore) because overview_page.py also uses it to turn the
    HTML delta chip (▲ 5.9% vs last week) into plain text for the Metric Cards section."""
    if not text:
        return text
    text = _TAG_RE.sub("", text)
    text = _html.unescape(text)
    text = text.replace("**", "").replace("__", "")
    return re.sub(r"\s+", " ", text).strip()


def chart_to_png(chart, width: int = _CHART_SPEC_WIDTH) -> bytes | None:
    """Server-side Altair -> PNG export via vl-convert. `chart` is an existing
    alt.Chart object (same one the page renders with st.altair_chart) — calling
    .properties(width=...) on it returns a NEW chart object (Altair charts are
    copy-on-write), so this never mutates the chart the live page is using.
    Returns None on any failure (missing vl_convert, bad spec, empty chart) —
    charts are a nice-to-have in the share image, never worth failing the whole
    download over."""
    if chart is None:
        return None
    try:
        import vl_convert as vlc
        sized = chart.properties(width=width)
        return vlc.vegalite_to_png(sized.to_dict(), scale=_CHART_EXPORT_SCALE)
    except Exception:
        return None


# ---------------------------------------------------------------------
# Step 1: turn raw page data into sections: {"header", "lines", "charts"}.
# "charts" is a list of already-exported PNG bytes (possibly empty).
# ---------------------------------------------------------------------
def build_sections(
    selection: set[str],
    key_callouts: list[str] | None,
    card_summaries: list[dict],
    subject_area_summaries: list[dict],
) -> list[dict]:
    sections: list[dict] = []

    if "callouts" in selection:
        lines = [f"• {plain_text(c)}" for c in (key_callouts or [])] or ["No insights generated yet."]
        sections.append({"header": SELECTION_LABELS["callouts"], "lines": lines, "charts": []})

    if "cards" in selection:
        lines = [f"{c['label']}: {c['value_text']}" for c in card_summaries] or ["No card data available."]
        sections.append({"header": SELECTION_LABELS["cards"], "lines": lines, "charts": []})

    if "subject_areas" in selection:
        # One sub-section per subject area in the Overview page's
        # Subject-Area Intelligence expander (same order, same set).
        for area in subject_area_summaries:
            lines = [plain_text(area["summary"])] if area.get("summary") else []
            lines += [f"• {plain_text(b)}" for b in area.get("insights", [])]
            if not lines:
                lines = ["No insight run yet."]
            chart_pngs = [png for png in (chart_to_png(c) for c in area.get("charts", [])) if png]
            sections.append({"header": area["display_name"], "lines": lines, "charts": chart_pngs})

    return sections


# ---------------------------------------------------------------------
# Step 2: PNG share-card image
# ---------------------------------------------------------------------
def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = ["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
             else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)  # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


def build_share_image(sections: list[dict]) -> bytes:
    width = 1000
    margin = 48
    content_width = width - 2 * margin
    header_h = 118

    title_font = _font(30, bold=True)
    sub_font = _font(15)
    header_font = _font(19, bold=True)
    body_font = _font(16)

    draw_scratch = ImageDraw.Draw(Image.new("RGB", (10, 10)))

    def wrap(text: str, font: ImageFont.ImageFont, max_w: int) -> list[str]:
        words = text.split()
        lines, cur = [], ""
        for w in words:
            trial = f"{cur} {w}".strip()
            if draw_scratch.textlength(trial, font=font) <= max_w:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines or [""]

    # Pre-wrap text AND pre-decode chart images once, so we know the exact
    # canvas height before creating it (Pillow images can't grow after creation)
    # and don't have to decode each chart PNG twice.
    chart_gap = 14
    prepared = []  # [{"header", "wrapped_lines", "chart_images": [(PIL.Image, scaled_h)]}]
    for sec in sections:
        wrapped_lines = []
        for line in sec["lines"]:
            wrapped_lines.extend(wrap(line, body_font, content_width))

        chart_images = []
        for png_bytes in sec.get("charts", []):
            try:
                im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
            except Exception:
                continue
            scaled_h = int(im.height * (content_width / im.width))
            chart_images.append((im, scaled_h))

        prepared.append({"header": sec["header"], "wrapped_lines": wrapped_lines, "chart_images": chart_images})

    line_h, section_gap, header_gap = 24, 26, 10
    height = header_h + margin
    for sec in prepared:
        height += header_gap + 24 + header_gap + len(sec["wrapped_lines"]) * line_h
        for _im, scaled_h in sec["chart_images"]:
            height += chart_gap + scaled_h
        height += section_gap
    height += margin

    img = Image.new("RGB", (width, int(height)), "white")
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, width, header_h], fill=ACCENT_RGB)
    draw.text((margin, 30), "Inventory360 — Shared Insights", font=title_font, fill="white")
    draw.text((margin, 72), dt.date.today().strftime("Generated %B %d, %Y"), font=sub_font, fill="white")

    y = header_h + margin
    for sec in prepared:
        draw.text((margin, y), sec["header"].upper(), font=header_font, fill=ACCENT_RGB)
        y += 24 + header_gap
        for line in sec["wrapped_lines"]:
            draw.text((margin, y), line, font=body_font, fill=INK_RGB)
            y += line_h
        for im, scaled_h in sec["chart_images"]:
            y += chart_gap
            resized = im.resize((content_width, scaled_h))
            img.paste(resized, (margin, y))
            y += scaled_h
        y += section_gap

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
