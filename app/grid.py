"""Find the rows and columns of a table on the rendered page, to highlight cells.

The table position comes from the SDK; inside it, the ruling lines (or, for a table
without lines, the white gaps) of the page image give the row and column boundaries.
A scan is straightened first: its skew angle is the one that makes the rows sharpest.
When the number of rows found differs from the table, cells are not located; the table
is still outlined.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

INK = 150          # grey level below which a pixel is text
LINE_INK = 215     # thin ruling lines are rendered light grey; light cell fills stay above this
LINE_SHARE = 0.45  # a ruling line covers at least this share of the table width or height
MAX_LINE = 8       # thicker dark bands are filled cells (a dark header), not lines


def _bands(mask: np.ndarray) -> list[tuple[int, int]]:
    bands, start = [], None
    for i, on in enumerate(mask):
        if on and start is None:
            start = i
        elif not on and start is not None:
            bands.append((start, i - 1))
            start = None
    if start is not None:
        bands.append((start, len(mask) - 1))
    return bands


def _longest_runs(mask: np.ndarray) -> np.ndarray:
    """Longest run of consecutive ink pixels in each row. A ruling line is one long run;
    a line of text is broken by the gaps between letters and words. Each row is merged
    with its neighbours first, so a line slightly off horizontal stays one run."""
    m = mask.copy()
    m[1:] |= mask[:-1]
    m[:-1] |= mask[1:]
    runs = np.zeros(m.shape[0], dtype=np.int64)
    for i, row in enumerate(m):
        padded = np.concatenate(([0], row.astype(np.int8), [0]))
        edges = np.flatnonzero(np.diff(padded))
        if len(edges):
            runs[i] = int((edges[1::2] - edges[::2]).max())
    return runs


def _bounds_from_lines(mask: np.ndarray) -> tuple[list[float], int]:
    """Boundaries from the ruling lines of a mask whose rows are scanned (transpose it for
    the columns), and the number of thin lines among them."""
    length = mask.shape[1]
    bounds: list[float] = []
    thin = 0
    for a, b in _bands(_longest_runs(mask) > LINE_SHARE * length):
        if b - a + 1 <= MAX_LINE:
            bounds.append((a + b) / 2)
            thin += 1
        else:
            bounds += [a, b + 1]
    return bounds, thin


def _bounds_from_gaps(profile: np.ndarray, min_gap: int) -> list[float]:
    gaps = [(a, b) for a, b in _bands(profile == 0) if b - a + 1 >= min_gap]
    return [(a + b) / 2 for a, b in gaps]


def _clean(bounds: list[float], size: int, ruled: bool, margin: int = 8) -> list[float]:
    """Sort the boundaries, add the outer edges of a table without ruling lines, and merge
    slivers (an interval under a third of the median one, such as a line next to a filled
    header)."""
    bounds = sorted(bounds)
    if not ruled:
        if not bounds or bounds[0] > margin:
            bounds = [0.0] + bounds
        if bounds[-1] < size - 1 - margin:
            bounds = bounds + [float(size - 1)]
    if len(bounds) < 3:
        return bounds
    median = float(np.median(np.diff(bounds)))
    merged = [bounds[0]]
    for v in bounds[1:]:
        if v - merged[-1] < median / 3:
            if v == bounds[-1]:
                merged[-1] = v
            continue
        merged.append(v)
    return merged


def _skew(ink: np.ndarray) -> float:
    small = Image.fromarray((~ink * 255).astype(np.uint8)).reduce(2)
    best, best_score = 0.0, -1.0
    for angle in np.arange(-2.0, 2.01, 0.1):
        rotated = np.array(small.rotate(angle, resample=Image.BILINEAR, fillcolor=255)) < 128
        score = float((rotated.sum(axis=1).astype(np.float64) ** 2).sum())
        if score > best_score:
            best, best_score = float(angle), score
    return best


def cell_boxes(page_png: str, box: dict, dpi: int, rows: int, cols: int, deskew: bool = False) -> dict:
    """Row and cell rectangles, in points, for a table of rows x cols inside box (points)."""
    scale = dpi / 72
    image = Image.open(page_png).convert("L")
    x0, y0 = max(0, int(box["x"] * scale) - 3), max(0, int(box["y"] * scale) - 3)
    x1 = min(image.width, int((box["x"] + box["w"]) * scale) + 3)
    y1 = min(image.height, int((box["y"] + box["h"]) * scale) + 3)
    crop = image.crop((x0, y0, x1, y1))
    angle = _skew(np.array(crop) < INK) if deskew else 0.0
    if angle:
        crop = crop.rotate(angle, resample=Image.BICUBIC, fillcolor=255)
    pixels = np.array(crop)
    ink, line_ink = pixels < INK, pixels < LINE_INK
    h, w = ink.shape

    ys, thin = _bounds_from_lines(line_ink)
    ruled_rows = thin >= 3
    if not ruled_rows:
        ys = _bounds_from_gaps(ink.sum(axis=1), 3)
    ys = _clean(ys, h, ruled_rows)

    xs, thin = _bounds_from_lines(line_ink.T)
    ruled_cols = thin >= 3
    if not ruled_cols:
        # Ignore ruling lines and filled rows (a dark header with light text) for the gaps.
        lines = (_longest_runs(line_ink) > LINE_SHARE * w) | (ink.sum(axis=1) > 0.5 * w)
        xs = _bounds_from_gaps(ink[~lines].sum(axis=0), int(8 * scale / 2))
    xs = _clean(xs, w, ruled_cols)

    def to_points(ax: float, ay: float, bx: float, by: float) -> dict:
        corners = np.array([[ax, ay], [bx, ay], [ax, by], [bx, by]])
        if angle:
            # Undo the straightening: rotate the corners back around the crop centre.
            t = np.radians(angle)
            c = np.array([w / 2, h / 2])
            rot = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
            corners = (corners - c) @ rot.T + c
        left, top = corners.min(axis=0)
        right, bottom = corners.max(axis=0)
        return {"x": round((x0 + left) / scale, 1), "y": round((y0 + top) / scale, 1),
                "w": round((right - left) / scale, 1), "h": round((bottom - top) / scale, 1)}

    result: dict = {"angle": round(angle, 1), "rows_found": len(ys) - 1, "cols_found": len(xs) - 1, "rows": [], "cells": []}
    if len(ys) - 1 != rows:
        return result
    result["rows"] = [to_points(xs[0], ys[r], xs[-1], ys[r + 1]) for r in range(rows)]
    if len(xs) - 1 == cols:
        result["cells"] = [[to_points(xs[c], ys[r], xs[c + 1], ys[r + 1]) for c in range(cols)] for r in range(rows)]
    return result
