"""Extract every table of a PDF.

1. The Nutrient Python SDK exports the document (Markdown with HTML tables, page layout,
   page images, OCR text of scanned pages). This runs in a fresh worker process per
   document.
2. Text tables come from the Markdown export. A two-level header squeezed into one row is
   split again, and a table that continues on the next page is joined.
3. Pages without a text layer, and pictures on text pages, are read by the vision model.
   On scans, the SDK's OCR text checks every cell the model read.
4. Totals are recomputed and compared with the printed total rows.
5. The rows and cells are located on the page image, for the click-to-highlight.
"""

from __future__ import annotations

import json
import multiprocessing
import re
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Callable

from . import vision
from .config import settings
from .grid import cell_boxes
from .sdk import analyse, split_pages
from .tables import check_totals, stitch, tables_from_markdown, total_rows

Progress = Callable[[str], None]


def doc_id(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", path.stem).strip("-")


def output_dir(path: Path) -> Path:
    return settings.output / doc_id(path)


def run_sdk(path: Path, out: Path) -> dict:
    """The SDK work in a new process: each one starts its own (one-hour) evaluation session."""
    ctx = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=1, mp_context=ctx) as pool:
        return pool.submit(analyse, str(path), str(out), settings.render_dpi).result()


def _area(b: dict) -> float:
    return b["w"] * b["h"]


def _union(boxes: list[dict]) -> dict:
    x0 = min(b["x"] for b in boxes)
    y0 = min(b["y"] for b in boxes)
    x1 = max(b["x"] + b["w"] for b in boxes)
    y1 = max(b["y"] + b["h"] for b in boxes)
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def locate(table: dict, out: Path, dpi: int, deskew: bool) -> None:
    """Rows and cells of every page segment of the table, in points on its page."""
    cols = len(table["rows"][0])
    table["row_boxes"] = [None] * len(table["rows"])
    table["cell_boxes"] = [[None] * cols for _ in table["rows"]]
    for seg in table["segments"]:
        if not seg.get("box"):
            continue
        printed = seg["rows"] + seg["skip"]
        found = cell_boxes(str(out / f"page-{seg['page']}.png"), seg["box"], dpi, printed, cols, deskew)
        seg["grid"] = {"rows_found": found["rows_found"], "cols_found": found["cols_found"], "angle": found["angle"]}
        if found["rows"] and table["method"].startswith("vision"):
            # The vision model read a region; the rows found on the image give the table itself.
            seg["box"] = {"page": seg["page"], **_union(found["rows"])}
        for k, row_box in enumerate(found["rows"][seg["skip"]:]):
            r = seg["first_row"] + k
            table["row_boxes"][r] = {"page": seg["page"], **row_box}
            if found["cells"]:
                table["cell_boxes"][r] = [{"page": seg["page"], **c} for c in found["cells"][seg["skip"] + k]]


def finish(table: dict) -> None:
    """Totals check and the list of cells to review."""
    table["total_rows"] = total_rows(table["rows"], table["header_rows"])
    table["checks"] = check_totals(table["rows"], table["header_rows"])
    flags = [f for f in table.get("ocr_flags", [])]
    for check in table["checks"]:
        if not check["ok"]:
            flags.append({"row": check["row"], "col": check["col"],
                          "reason": f"total check: the rows add up to {check['expected']:,.2f}"})
    table["flags"] = flags


def process(path: Path, progress: Progress = lambda _: None) -> dict:
    started = time.time()
    out = output_dir(path)
    out.mkdir(parents=True, exist_ok=True)
    progress("Nutrient SDK: Markdown, page layout, page images and OCR")
    sdk = run_sdk(path, out)
    (out / "document.md").write_text(sdk["markdown"], encoding="utf-8")
    for page, text in sdk["ocr_text"].items():
        (out / f"ocr-page-{page}.txt").write_text(text, encoding="utf-8")
    dpi = sdk["dpi"]
    layout = sdk["layout"]
    sdk_seconds = round(time.time() - started, 1)

    # 1. Text tables from the Markdown export.
    tables = stitch(tables_from_markdown(sdk["markdown"]))
    for t in tables:
        t["method"] = "markdown + header repair" if t["repaired_header"] else "markdown"
        for seg in t["segments"]:
            # The page layout lists the same tables, top to bottom.
            on_page = sorted([b for b in layout["tables"] if b["page"] == seg["page"]], key=lambda b: b["y"])
            if seg["index_on_page"] < len(on_page):
                seg["box"] = on_page[seg["index_on_page"]]

    # 2. Pictures on text pages: tables pasted as images.
    vision_seconds = 0.0
    md_pages = split_pages(sdk["markdown"])
    page_area = {i + 1: p["width"] * p["height"] for i, p in enumerate(layout["pages"])}
    for img in layout["images"]:
        if img["page"] in sdk["scanned_pages"] or _area(img) > 0.6 * page_area.get(img["page"], 1) or img["w"] < 80 or img["h"] < 40:
            continue
        progress(f"Vision model: picture on page {img['page']}")
        t0 = time.time()
        found = vision.read_tables(vision.crop_png(str(out / f"page-{img['page']}.png"), img, dpi))
        vision_seconds += time.time() - t0
        titles = headings_without_table(md_pages.get(img["page"], ""))
        for v in found:
            t = _vision_table(v, img["page"], img, "vision (picture)")
            t["title"] = titles.pop(0) if titles else v["title"]
            tables.append(t)

    # 3. Scanned pages.
    for page in sdk["scanned_pages"]:
        boxes = [b for b in sdk["ocr_tables"] if b["page"] == page]
        size = layout["pages"][page - 1]
        # The OCR finds roughly where the table is; read a band of the full page width around it.
        region = None
        if boxes:
            u = _union(boxes)
            region = {"x": 0, "y": max(0, u["y"] - 40), "w": size["width"], "h": min(size["height"], u["h"] + 80)}
        progress(f"Vision model: scanned page {page}")
        t0 = time.time()
        found = vision.read_tables(vision.crop_png(str(out / f"page-{page}.png"), region, dpi))
        vision_seconds += time.time() - t0
        for v in found:
            t = _vision_table(v, page, region or {"x": 0, "y": 0, "w": size["width"], "h": size["height"]}, "vision (scan)")
            ocr = sdk["ocr_text"].get(str(page), "")
            t["ocr_flags"] = vision.cross_check(t["rows"], ocr)
            if len(t["title"]) > 60:  # a sentence, not a heading: use the first short OCR line
                t["title"] = next((ln.strip() for ln in ocr.splitlines() if 0 < len(ln.strip()) <= 60), "")
            tables.append(t)

    # 4. Order, name, check and locate.
    tables.sort(key=lambda t: (t["pages"][0], (t["segments"][0].get("box") or {}).get("y", 0)))
    for i, t in enumerate(tables, start=1):
        t["id"] = i
        t["title"] = t.get("title") or f"Table {i}"
        finish(t)
        locate(t, out, dpi, deskew=t["method"] == "vision (scan)")
        for key in ("text_after", "text_before", "text_after_last", "page", "index_on_page", "tables_on_page"):
            t.pop(key, None)
        t["extracted_rows"] = [list(r) for r in t["rows"]]

    result = {
        "document": path.name,
        "id": doc_id(path),
        "pages": [{"number": i + 1, "width": p["width"], "height": p["height"],
                   "scanned": (i + 1) in sdk["scanned_pages"]} for i, p in enumerate(layout["pages"])],
        "tables": tables,
        "seconds": {"sdk": sdk_seconds, "vision": round(vision_seconds, 1), "total": round(time.time() - started, 1)},
        "vision_model": settings.vision_model,
    }
    save(path, result)
    return result


def headings_without_table(page_text: str) -> list[str]:
    """Headings of the page whose section holds no text table: titles for picture tables."""
    parts = re.split(r"^(#{1,6}\s+.+)$", page_text, flags=re.M)
    titles = []
    for i in range(1, len(parts), 2):
        if "<table" not in parts[i + 1]:
            titles.append(re.sub(r"^#+\s+(\d+(\.\d+)*\.?\s+)?", "", parts[i]).strip())
    return titles


def _vision_table(v: dict, page: int, box: dict, method: str) -> dict:
    return {"title": v["title"], "rows": v["rows"], "header_rows": v["header_rows"], "method": method,
            "repaired_header": False, "pages": [page],
            "segments": [{"page": page, "first_row": 0, "rows": len(v["rows"]), "skip": 0, "box": box}]}


def reread_with_vision(path: Path, result: dict, table_id: int) -> dict:
    """Read one table again with the vision model, from its region on each page."""
    out = output_dir(path)
    table = next(t for t in result["tables"] if t["id"] == table_id)
    rows: list[list[str]] = []
    header_rows = table["header_rows"]
    for k, seg in enumerate(table["segments"]):
        box = seg.get("box")
        found = vision.read_tables(vision.crop_png(str(out / f"page-{seg['page']}.png"), box, settings.render_dpi))
        if not found:
            continue
        best = max(found, key=lambda v: len(v["rows"]))
        part = best["rows"]
        if k == 0:
            header_rows = best["header_rows"]
        elif rows and [vision._squash(" ".join(r)) for r in part[:header_rows]] == [vision._squash(" ".join(r)) for r in rows[:header_rows]]:
            part = part[header_rows:]
        width = max(len(rows[0]) if rows else 0, max(len(r) for r in part))
        rows = [r + [""] * (width - len(r)) for r in rows] + [r + [""] * (width - len(r)) for r in part]
    if not rows:
        raise ValueError("The vision model found no table in this region.")
    table["previous"] = {"rows": table["rows"], "header_rows": table["header_rows"], "method": table["method"]}
    table["rows"], table["header_rows"], table["method"] = rows, header_rows, "vision (re-read)"
    table["extracted_rows"] = [list(r) for r in rows]
    table["ocr_flags"] = []
    finish(table)
    locate_after_reread(table, path)
    save(path, result)
    return table


def locate_after_reread(table: dict, path: Path) -> None:
    if len(table["segments"]) == 1:
        seg = table["segments"][0]
        seg["rows"], seg["skip"], seg["first_row"] = len(table["rows"]), 0, 0
        locate(table, output_dir(path), settings.render_dpi, deskew=False)
    else:
        table["row_boxes"] = [None] * len(table["rows"])
        table["cell_boxes"] = [[None] * len(table["rows"][0]) for _ in table["rows"]]


def result_path(path: Path) -> Path:
    return output_dir(path) / "result.json"


def save(path: Path, result: dict) -> None:
    result_path(path).write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")


def load(path: Path) -> dict | None:
    p = result_path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
