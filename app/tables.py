"""Tables from the Markdown export: parse, repair, stitch across pages, check totals.

A table is a list of rows, each row a list of cell strings, all rows the same length.
A merged cell keeps its text in its first (top-left) cell; the cells it covers are "".
"""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

from .sdk import split_pages

# --------------------------------------------------------------------------- parsing


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables: list[list[list[dict]]] = []
        self.depth = 0
        self.row: list[dict] | None = None
        self.cell: dict | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            self.depth += 1
            if self.depth == 1:
                self.tables.append([])
        elif tag == "tr" and self.depth == 1:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = {"text": "", "colspan": int(attrs.get("colspan") or 1), "rowspan": int(attrs.get("rowspan") or 1),
                         "header": tag == "th"}
        elif tag == "br" and self.cell is not None:
            self.cell["text"] += "\n"

    def handle_endtag(self, tag):
        if tag == "table":
            self.depth -= 1
        elif tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None and self.depth == 1:
            self.tables[-1].append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"] += data


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text)).strip()


def expand(raw_rows: list[list[dict]]) -> tuple[list[list[str]], list[list[str | None]], int]:
    """Expand colspan and rowspan into a rectangular grid.

    Returns the grid (merged cells keep their text in the first cell), the raw cell texts
    with their line breaks (for the header repair) and the number of leading header rows.
    """
    grid: dict[tuple[int, int], tuple[str, str]] = {}
    for r, row in enumerate(raw_rows):
        c = 0
        for cell in row:
            while (r, c) in grid:
                c += 1
            for dr in range(cell["rowspan"]):
                for dc in range(cell["colspan"]):
                    first = dr == 0 and dc == 0
                    # Covered cells keep None as raw text, to tell them from empty cells.
                    grid[(r + dr, c + dc)] = (clean(cell["text"]) if first else "", cell["text"] if first else None)
            c += cell["colspan"]
    rows = max((r for r, _ in grid), default=-1) + 1
    cols = max((c for _, c in grid), default=-1) + 1
    cells = [[grid.get((r, c), ("", ""))[0] for c in range(cols)] for r in range(rows)]
    raw = [[grid.get((r, c), ("", ""))[1] for c in range(cols)] for r in range(rows)]
    header_rows = 0
    for row in raw_rows:
        # A header row is all <th>; a first column of <th> alone marks row labels, not a header.
        if row and all(cell["header"] for cell in row):
            header_rows += 1
        else:
            break
    return cells, raw, max(header_rows, 1)


def split_merged_header(cells: list[list[str]], raw: list[list[str | None]], header_rows: int) -> tuple[list[list[str]], int, bool]:
    """Undo a two-level header squeezed into one row.

    The Markdown export can return a group header and its sub-headers as one merged cell,
    for example "Headcount (FTE)<br/>2025 2026" over two columns. When the last line of a
    merged header cell holds exactly one word per covered column, it becomes a second
    header row.
    """
    if not cells or header_rows != 1:
        return cells, header_rows, False
    top, raw_top = cells[0], raw[0]
    cols = len(top)
    second = [""] * cols
    changed = False
    c = 0
    while c < cols:
        span = 1
        while c + span < cols and raw_top[c + span] is None:
            span += 1
        lines = [ln.strip() for ln in (raw_top[c] or "").split("\n") if ln.strip()]
        if span > 1 and len(lines) >= 2:
            words = lines[-1].split()
            if len(words) == span:
                cells[0][c] = clean(" ".join(lines[:-1]))
                second[c:c + span] = words
                changed = True
        c += span
    if not changed:
        return cells, header_rows, False
    return [cells[0], second] + cells[1:], 2, True


def tables_from_markdown(markdown: str, repair: bool = True) -> list[dict]:
    """Every table of the Markdown export, with its page and its position on the page."""
    found = []
    for page, text in sorted(split_pages(markdown).items()):
        parser = _TableParser()
        parser.feed(text)
        # Text that follows the last table on the page: tells whether the table ends the page.
        tail = text[text.rfind("</table>") + len("</table>"):] if "</table>" in text else text
        head = text[:text.find("<table")] if "<table" in text else text
        for index, raw_rows in enumerate(parser.tables):
            cells, raw, header_rows = expand(raw_rows)
            if len(cells) < 2 or len(cells[0]) < 2:
                continue
            repaired = False
            if repair:
                cells, header_rows, repaired = split_merged_header(cells, raw, header_rows)
            found.append({
                "page": page,
                "index_on_page": index,
                "tables_on_page": len(parser.tables),
                "rows": cells,
                "header_rows": header_rows,
                "repaired_header": repaired,
                "title": _title_before(text, index),
                "text_after": _body_words(tail) if index == len(parser.tables) - 1 else 99,
                "text_before": _body_words(head) if index == 0 else 99,
            })
    return found


def _title_before(page_text: str, index: int) -> str:
    """The last heading before the table, without its number."""
    starts = [m.start() for m in re.finditer(r"<table", page_text)]
    before = page_text[:starts[index]] if index < len(starts) else page_text
    headings = re.findall(r"^#{1,6}\s+(.+)$", before, flags=re.M)
    if not headings:
        return ""
    return re.sub(r"^\d+(\.\d+)*\.?\s+", "", headings[-1]).strip()


def _body_words(text: str) -> int:
    """Words of running text, ignoring page footers such as "Page 2" or the company line."""
    lines = [ln.strip() for ln in re.sub(r"<[^>]+>", " ", text).splitlines() if ln.strip()]
    lines = [ln for ln in lines if not re.fullmatch(r"(page\s*)?\d+(\s*(of|/)\s*\d+)?", ln, flags=re.I)]
    return sum(len(ln.split()) for ln in lines)


# --------------------------------------------------------------------------- stitching


def norm(text: str) -> str:
    return re.sub(r"[\s,]+", "", text).lower()


def stitch(tables: list[dict]) -> list[dict]:
    """Join a table that continues on the next page.

    A table continues when it is the last thing on its page (apart from footers), the next
    page starts with a table of the same number of columns, and that table either repeats
    the header or has no header of its own. A repeated header is dropped.
    """
    out: list[dict] = []
    for t in tables:
        t = dict(t)
        t["segments"] = [{"page": t["page"], "first_row": 0, "rows": len(t["rows"]), "skip": 0,
                          "index_on_page": t["index_on_page"]}]
        prev = out[-1] if out else None
        if (prev and t["page"] == prev["segments"][-1]["page"] + 1 and t["index_on_page"] == 0
                and prev["text_after_last"] <= 12 and t["text_before"] <= 12
                and len(t["rows"][0]) == len(prev["rows"][0])):
            header = prev["rows"][:prev["header_rows"]]
            repeated = [norm(" ".join(r)) for r in t["rows"][:len(header)]] == [norm(" ".join(r)) for r in header]
            skip = len(header) if repeated else 0
            if repeated or not _looks_like_header(t["rows"][0]):
                prev["segments"].append({"page": t["page"], "first_row": len(prev["rows"]), "rows": len(t["rows"]) - skip,
                                         "skip": skip, "index_on_page": 0})
                prev["rows"] = prev["rows"] + t["rows"][skip:]
                prev["text_after_last"] = t["text_after"]
                continue
        t["text_after_last"] = t["text_after"]
        out.append(t)
    for t in out:
        t["pages"] = sorted({s["page"] for s in t["segments"]})
    return out


def _looks_like_header(row: list[str]) -> bool:
    return not any(parse_number(c) is not None for c in row if c)


# --------------------------------------------------------------------------- numbers and totals

NUMBER = re.compile(r"^\(?[-+−]?\s*(?:EUR|USD|GBP|€|\$|£)?\s*\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?\)?$|^\(?[-+−]?\d+(?:\.\d+)?\)?$")
TOTAL_LABEL = re.compile(r"\b(total|subtotal|sub-total|grand total|sum)\b", re.I)


def parse_number(text: str) -> float | None:
    t = text.strip()
    if not t or "%" in t or "/" in t or not NUMBER.match(t):
        return None
    negative = t.startswith("(") or t.lstrip("(").startswith(("-", "−"))
    digits = re.sub(r"[^\d.]", "", t)
    try:
        value = float(digits)
    except ValueError:
        return None
    return -value if negative else value


def total_rows(rows: list[list[str]], header_rows: int) -> list[int]:
    return [i for i, row in enumerate(rows) if i >= header_rows and any(TOTAL_LABEL.search(c) for c in row[:3] if c)]


def check_totals(rows: list[list[str]], header_rows: int) -> list[dict]:
    """Compare every number of a total row with the sum of the rows it totals.

    A total row may sum the item rows since the previous total row, the subtotal rows above
    it, or the previous total row and the rows after it (subtotal + VAT = total).
    """
    totals = total_rows(rows, header_rows)
    checks = []
    for k, ti in enumerate(totals):
        prev = totals[k - 1] if k else header_rows - 1
        items = [i for i in range(prev + 1, ti) if i not in totals]
        subtotals = [i for i in totals[:k] if TOTAL_LABEL.search(" ".join(rows[i][:3])) and "sub" in " ".join(rows[i][:3]).lower()]
        chained = ([prev] if k else []) + items
        for c, cell in enumerate(rows[ti]):
            printed = parse_number(cell)
            if printed is None:
                continue
            column = [parse_number(rows[i][c]) for i in range(header_rows, ti) if i not in totals]
            if not column or any(v is None for v in column if v is not None) or all(v is None for v in column):
                continue
            candidates = []
            for group in (items, subtotals, chained):
                vals = [parse_number(rows[i][c]) for i in group]
                vals = [v for v in vals if v is not None]
                if vals:
                    candidates.append(round(sum(vals), 2))
            if not candidates:
                continue
            ok = any(abs(v - printed) < 0.011 for v in candidates)
            checks.append({"row": ti, "col": c, "printed": printed, "expected": candidates[0] if not ok else
                           next(v for v in candidates if abs(v - printed) < 0.011), "ok": ok})
    return checks
