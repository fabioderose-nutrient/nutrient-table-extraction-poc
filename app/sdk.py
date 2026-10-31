"""Everything that touches the Nutrient Python SDK.

analyse() runs in a short-lived worker process (see pipeline.py), so each document gets a
fresh SDK session; an evaluation session of the SDK is limited to one hour.

For one document it returns:
- the Markdown export, with a marker at the start of every page and tables as HTML
  (<table>, colspan, rowspan, <br/> for a line break inside a cell);
- the page geometry from the HTML export in page layout: the position of every table and
  picture on each page, in PDF points from the top left corner;
- a PNG of every page;
- for pages without a text layer (scans): OCR in memory with PdfEditor.make_searchable(),
  then the layout text export of the page and the table positions found on the OCR text.
  Nothing is saved: a saved copy would carry the evaluation watermark.
"""

from __future__ import annotations

import os
import re
import tempfile
from html.parser import HTMLParser
from pathlib import Path

PAGE_MARKER = re.compile(r"<!--\s*nutrient-page-start:\s*(\d+)\s*-->")
# Below this many letters and digits, a page is treated as a scan and read with OCR.
MIN_CHARS_PER_PAGE = 40


def _register_license(ns) -> None:
    key = os.environ.get("NUTRIENT_LICENSE_KEY", "").strip()
    if key:
        ns.License.register_key(key)


def split_pages(text: str) -> dict[int, str]:
    parts = PAGE_MARKER.split(text)
    pages: dict[int, str] = {}
    for i in range(1, len(parts), 2):
        pages[int(parts[i])] = parts[i + 1]
    return pages


def text_chars(text: str) -> int:
    return sum(ch.isalnum() for ch in re.sub(r"<[^>]+>", "", text))


# --------------------------------------------------------------------------- geometry

class _LayoutParser(HTMLParser):
    """Reads the absolute positions of the HTML export in page layout.

    Every positioned element has a CSS rule #id { position: absolute; top; left; width;
    height } relative to its positioned parent.
    """

    def __init__(self, css: dict[str, dict[str, float]]):
        super().__init__()
        self.css = css
        self.stack: list[tuple[str, float, float]] = [("root", 0.0, 0.0)]
        self.tables: list[dict] = []
        self.images: list[dict] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        _, px, py = self.stack[-1]
        rule = self.css.get(attrs.get("id", ""), {})
        x = px + rule.get("left", 0.0) if rule.get("absolute") else px
        y = py + rule.get("top", 0.0) if rule.get("absolute") else py
        box = {"x": x, "y": y, "w": rule.get("width", 0.0), "h": rule.get("height", 0.0)}
        if tag == "table":
            self.tables.append(box)
        elif tag == "img":
            self.images.append(box)
        if tag not in ("img", "br", "path", "meta", "link"):
            self.stack.append((tag, x, y))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def _css_rules(html: str) -> dict[str, dict[str, float]]:
    rules: dict[str, dict[str, float]] = {}
    for ident, body in re.findall(r"#(\w+)\s*\{([^}]*)\}", html):
        rule: dict[str, float] = {"absolute": 1.0 if "position: absolute" in body else 0.0}
        for prop in ("top", "left", "width", "height"):
            m = re.search(rf"(?<![-\w]){prop}:\s*(-?[\d.]+)px", body)
            if m:
                rule[prop] = float(m.group(1))
        rules[ident] = rule
    return rules


def parse_layout(html: str, sizes: list[tuple[float, float]]) -> dict:
    """Tables and pictures per page, in points from the top left corner of their page.

    sizes holds the (width, height) of every page; the export stacks the pages vertically.
    """
    parser = _LayoutParser(_css_rules(html))
    parser.feed(html)
    pages, top = [], 0.0
    for w, h in sizes:
        pages.append({"x": 0.0, "y": top, "w": w, "h": h})
        top += h

    def place(box: dict) -> dict | None:
        for number, page in enumerate(pages, start=1):
            if page["y"] - 1 <= box["y"] < page["y"] + page["h"]:
                return {"page": number, "x": round(box["x"], 1), "y": round(box["y"] - page["y"], 1),
                        "w": round(box["w"], 1), "h": round(box["h"], 1)}
        return None

    return {
        "pages": [{"width": round(p["w"], 2), "height": round(p["h"], 2)} for p in pages],
        "tables": [b for b in map(place, parser.tables) if b],
        "images": [b for b in map(place, parser.images) if b and b["w"] > 0 and b["h"] > 0],
    }


# --------------------------------------------------------------------------- analysis

def analyse(path: str, out_dir: str, dpi: int = 150) -> dict:
    import nutrient_sdk as ns

    _register_license(ns)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result: dict = {"scanned_pages": [], "ocr_text": {}, "ocr_tables": []}

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # 1. Markdown with HTML tables (keeps colspan, rowspan and line breaks in cells).
        with ns.Document.open(path) as doc:
            md = doc.settings.markdown_settings
            md.emit_page_boundary_markers = True
            md.use_html_tables = True
            md.include_headers_and_footers = False
            md.join_hyphenated_line_breaks = True
            doc.export_as_markdown(str(tmp / "doc.md"))
            page_count = doc.page_count
            editor = ns.PdfEditor.edit(doc)
            sizes = [(page.width, page.height) for page in editor.page_collection]
            editor.close()
        result["markdown"] = (tmp / "doc.md").read_text(encoding="utf-8", errors="replace")
        result["page_count"] = page_count

        # 2. Page geometry: where each table and picture sits on its page.
        with ns.Document.open(path) as doc:
            doc.settings.html_settings.layout = ns.HtmlLayoutType.PAGE_LAYOUT
            doc.settings.html_settings.image_export = ns.ImageExportMode.EMBEDDED
            doc.export_as_html(str(tmp / "layout.html"))
        result["layout"] = parse_layout((tmp / "layout.html").read_text(encoding="utf-8", errors="replace"), sizes)

        # 3. One PNG per page, for the vision model and for the page previews.
        with ns.Document.open(path) as doc:
            doc.settings.image_settings.rasterization_dpi = dpi
            doc.export_as_image(str(tmp / "page.png"))
        for i in range(1, page_count + 1):
            src = tmp / ("page.png" if page_count == 1 else f"page-{i}.png")
            if src.exists():
                src.replace(out / f"page-{i}.png")
        result["dpi"] = dpi

        # 4. Scans: OCR in memory, then layout text and table positions of the OCR text.
        pages = split_pages(result["markdown"])
        scanned = [n for n in range(1, page_count + 1) if text_chars(pages.get(n, "")) < MIN_CHARS_PER_PAGE]
        result["scanned_pages"] = scanned
        if scanned:
            with ns.Document.open(path) as doc:
                doc.settings.html_settings.layout = ns.HtmlLayoutType.PAGE_LAYOUT
                doc.settings.html_settings.image_export = ns.ImageExportMode.EMBEDDED
                doc.settings.text_settings.emit_page_boundary_markers = True
                editor = ns.PdfEditor.edit(doc)
                for n in scanned:
                    editor.page_collection[n - 1].make_searchable()
                doc.export_as_text(str(tmp / "ocr.txt"))
                doc.export_as_html(str(tmp / "ocr.html"))
                editor.close()
            ocr_pages = split_pages((tmp / "ocr.txt").read_text(encoding="utf-8", errors="replace"))
            result["ocr_text"] = {str(n): ocr_pages.get(n, "") for n in scanned}
            ocr_layout = parse_layout((tmp / "ocr.html").read_text(encoding="utf-8", errors="replace"), sizes)
            result["ocr_tables"] = [t for t in ocr_layout["tables"] if t["page"] in scanned]
    return result
