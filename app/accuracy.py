"""Cell-level accuracy against the ground truth written by samples/generate_samples.py.

Rows are aligned first (a table with one row too many or too few is not scored as all
wrong): dynamic programming keeps the row order and maximises the number of equal cells.
Cells are compared after collapsing white space; everything else must be identical.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("’", "'")).strip()


def _matches(a: list[str], b: list[str]) -> int:
    return sum(1 for x, y in zip(a, b) if norm(x) == norm(y))


def score(truth: list[list[str]], found: list[list[str]]) -> dict:
    n, m = len(truth), len(found)
    best = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            best[i][j] = max(best[i - 1][j], best[i][j - 1], best[i - 1][j - 1] + _matches(truth[i - 1], found[j - 1]))
    # Walk back to list the cells that differ.
    wrong, i, j = [], n, m
    pairs = {}
    while i > 0 and j > 0:
        if best[i][j] == best[i - 1][j - 1] + _matches(truth[i - 1], found[j - 1]):
            pairs[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif best[i][j] == best[i - 1][j]:
            i -= 1
        else:
            j -= 1
    for r, row in enumerate(truth):
        for c, expected in enumerate(row):
            got = found[pairs[r]][c] if r in pairs and c < len(found[pairs[r]]) else None
            if got is None or norm(got) != norm(expected):
                wrong.append({"row": r, "col": c, "expected": expected, "found": got, "found_row": pairs.get(r)})
    cells = sum(len(r) for r in truth)
    return {"cells": cells, "correct": best[n][m], "accuracy": round(best[n][m] / cells, 4) if cells else 0.0,
            "rows_expected": n, "rows_found": m, "cols_expected": len(truth[0]) if truth else 0,
            "cols_found": len(found[0]) if found else 0, "wrong": wrong}


def load_truth(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def evaluate(document: str, tables: list[dict], truth: dict, key: str = "rows") -> list[dict]:
    """Score each ground-truth table against the extracted table that matches it best."""
    results = []
    for expected in truth.get(document, []):
        candidates = [t for t in tables if set(t["pages"]) & set(expected["pages"])] or tables
        scored = [(score(expected["rows"], t[key]), t) for t in candidates]
        if scored:
            best, table = max(scored, key=lambda st: st[0]["correct"])
        else:
            best, table = score(expected["rows"], []), None
        results.append({"title": expected["title"], "pages": expected["pages"], "table_id": table["id"] if table else None,
                        "method": table["method"] if table else None, **best})
    return results
