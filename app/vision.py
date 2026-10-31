"""Read tables from page images with a vision model, through an OpenAI-compatible API.

Used for scanned pages and for tables pasted as pictures, which have no text layer, and on
request for any table. The SDK's OCR text of a scanned page is used afterwards to check
each cell the model read.
"""

from __future__ import annotations

import base64
import io
import json
import re

from openai import OpenAI
from PIL import Image

from .config import settings

PROMPT = """Read every table in this image.
Return JSON: {"tables": [{"title": "<short heading of the table, in bold or larger type above it, or empty>", "header_rows": <number of header rows>, "rows": [["cell", "cell", ...], ...]}]}
Rules:
- One inner list per printed row, including the header row(s) and any total row. Keep the columns in printed order; every row has the same number of cells.
- Copy each cell exactly as printed: digits, thousands separators, decimals, signs, dates, capitals. Use "" for an empty cell.
- A cell printed on two lines is one string with a space.
- A merged cell: put its text in the first cell it covers and "" in the cells it covers.
- Do not add rows or columns that are not printed. If there is no table, return {"tables": []}."""


def client() -> OpenAI:
    return OpenAI(base_url=settings.vision_base_url, api_key=settings.vision_api_key or "not-needed",
                  timeout=settings.vision_timeout)


def crop_png(page_png: str, box: dict | None, dpi: int, pad: float = 6) -> bytes:
    """The page image, or the part of it inside box (points), as PNG bytes."""
    image = Image.open(page_png).convert("RGB")
    if box:
        s = dpi / 72
        image = image.crop((max(0, int((box["x"] - pad) * s)), max(0, int((box["y"] - pad) * s)),
                            min(image.width, int((box["x"] + box["w"] + pad) * s)),
                            min(image.height, int((box["y"] + box["h"] + pad) * s))))
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


def _json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        return json.loads(m.group(0)) if m else {"tables": []}


def read_tables(png: bytes) -> list[dict]:
    """Tables the model reads in the image: [{title, header_rows, rows}]."""
    b64 = base64.b64encode(png).decode()
    response = client().chat.completions.create(
        model=settings.vision_model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": PROMPT},
        ]}],
    )
    data = _json(response.choices[0].message.content or "{}")
    tables = []
    for t in data.get("tables") or []:
        rows = [[_cell(c) for c in row] for row in t.get("rows") or [] if isinstance(row, list)]
        rows = [r for r in rows if any(c for c in r)]
        if len(rows) < 2:
            continue
        rows = [_fit(r, len(rows[0])) for r in rows]
        width = max(len(r) for r in rows)
        if width < 2:
            continue
        rows = [r + [""] * (width - len(r)) for r in rows]
        header_rows = t.get("header_rows")
        tables.append({"title": str(t.get("title") or "").strip(), "rows": rows,
                       "header_rows": header_rows if isinstance(header_rows, int) and 0 < header_rows < len(rows) else 1})
    return tables


def _fit(row: list[str], width: int) -> list[str]:
    """A row longer than the header usually has one blank too many where a label spans
    several empty cells (a total row): drop blanks from the longest run of blanks."""
    row = list(row)
    while len(row) > width and "" in row:
        best, best_len, start = 0, 0, None
        for i, v in enumerate(row + ["x"]):
            if v == "" and start is None:
                start = i
            elif v != "" and start is not None:
                if i - start > best_len:
                    best, best_len = start, i - start
                start = None
        del row[best]
    return row


def _cell(value) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"\s+", " ", text.replace("’", "'")).strip()


# --------------------------------------------------------------------------- OCR cross-check


def _squash(text: str) -> str:
    return re.sub(r"[\s,'’]+", "", text).lower()


def _tokens(text: str) -> set[str]:
    return {_squash(t) for t in text.split() if _squash(t)}


def _confirmed(cell: str, line: str, line_tokens: set[str]) -> bool:
    """Every word of the cell is a word of the line; longer cells may also be glued to
    their neighbours by the OCR ("Weight(kg)")."""
    words = _tokens(cell)
    return bool(words) and (words <= line_tokens or (len(_squash(cell)) >= 4 and _squash(cell) in _squash(line)))


def cross_check(rows: list[list[str]], ocr_text: str) -> list[dict]:
    """Numbers the SDK's OCR text does not confirm.

    For each row, the OCR line that confirms most of the row's cells is taken as its
    reading. A cell with digits is flagged when its digits are not in that line: the
    vision model and the OCR disagree, and one of them misread it. Text cells are not
    flagged: OCR misspellings of words would bury the few useful flags.
    """
    lines = [(ln, _tokens(ln)) for ln in ocr_text.splitlines() if ln.strip()]
    flags = []
    for r, row in enumerate(rows):
        cells = [(c, v) for c, v in enumerate(row) if v.strip()]
        if not cells or not lines:
            continue
        line, tokens = max(lines, key=lambda lt: sum(_confirmed(v, *lt) for _, v in cells))
        if sum(_confirmed(v, line, tokens) for _, v in cells) < max(1, len(cells) // 3):
            continue  # no OCR line clearly belongs to this row
        digits_in_line = {re.sub(r"\D", "", t) for t in line.split()} - {""}
        for c, v in cells:
            digits = re.sub(r"\D", "", v)
            if digits and not re.search(r"[A-Za-z]", v) and digits not in digits_in_line:
                flags.append({"row": r, "col": c, "reason": "the vision model and the OCR disagree",
                              "ocr": re.sub(r"\s{2,}", "  ", line.strip())})
    return flags
