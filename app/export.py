"""Excel (one sheet per table) and CSV export."""

from __future__ import annotations

import csv
import io
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .tables import parse_number

HEADER_FILL = PatternFill("solid", fgColor="E6E8EC")
TOTAL_FILL = PatternFill("solid", fgColor="F4F5F7")
THIN = Side(style="thin", color="B8BEC6")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
PERCENT = re.compile(r"^-?\d+(\.\d+)?\s?%$")


def typed(text: str):
    """A number, a percentage or the text as printed, with an Excel number format."""
    number = parse_number(text)
    if number is not None:
        decimals = len(text.split(".")[-1]) if "." in text else 0
        fmt = ("#,##0" if "," in text else "0") + ("." + "0" * decimals if decimals else "")
        return number, fmt
    if PERCENT.match(text.strip()):
        value = float(text.strip().rstrip("%").strip()) / 100
        decimals = len(text.split(".")[-1].rstrip("% ")) if "." in text else 0
        return value, "0" + ("." + "0" * decimals if decimals else "") + "%"
    return text, None


def sheet_name(title: str, used: set[str]) -> str:
    base = re.sub(r"[\[\]:*?/\\]", " ", title).strip()[:28].strip() or "Table"
    name, n = base, 2
    while name.lower() in used:
        name = f"{base[:25].strip()} {n}"
        n += 1
    used.add(name.lower())
    return name


def merges(rows: list[list[str]], header_rows: int) -> list[tuple[int, int, int, int]]:
    """Merged header cells: a header text followed by empty cells to its right, or with an
    empty cell below it in the next header row."""
    found = []
    for r in range(header_rows):
        c = 0
        while c < len(rows[r]):
            if rows[r][c]:
                span = 1
                while (c + span < len(rows[r]) and not rows[r][c + span]
                       and r + 1 < header_rows and rows[r + 1][c + span]):
                    span += 1
                down = 1
                while r + down < header_rows and not rows[r + down][c] and span == 1:
                    down += 1
                if span > 1 or down > 1:
                    found.append((r, c, r + down - 1, c + span - 1))
                c += span
            else:
                c += 1
    return found


def workbook(document: str, tables: list[dict]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    used: set[str] = set()
    for t in tables:
        ws = wb.create_sheet(sheet_name(t["title"], used))
        rows, header_rows, totals = t["rows"], t["header_rows"], set(t.get("total_rows", []))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                cell = ws.cell(row=r + 1, column=c + 1)
                if r < header_rows:
                    cell.value = text
                    cell.font = Font(bold=True)
                    cell.fill = HEADER_FILL
                    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                else:
                    value, fmt = typed(text)
                    cell.value = value
                    if fmt:
                        cell.number_format = fmt
                    cell.alignment = Alignment(vertical="top", wrap_text=isinstance(value, str) and len(value) > 40)
                    if r in totals:
                        cell.font = Font(bold=True)
                        cell.fill = TOTAL_FILL
                cell.border = BORDER
        for r0, c0, r1, c1 in merges(rows, header_rows):
            ws.merge_cells(start_row=r0 + 1, start_column=c0 + 1, end_row=r1 + 1, end_column=c1 + 1)
        for c in range(len(rows[0])):
            width = max(len(row[c]) for row in rows[header_rows:] or rows)
            ws.column_dimensions[get_column_letter(c + 1)].width = min(max(10, width + 2), 60)
        ws.freeze_panes = ws.cell(row=header_rows + 1, column=1)
        note = f"{document}, page {'-'.join(str(p) for p in (t['pages'][0], t['pages'][-1])) if len(t['pages']) > 1 else t['pages'][0]}, {t['method']}"
        ws.cell(row=len(rows) + 2, column=1, value=note).font = Font(italic=True, color="66707A")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def csv_text(table: dict) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n").writerows(table["rows"])
    return buf.getvalue()
