"""Cell-level accuracy of the extraction on the samples, against samples/ground-truth.json.

Usage:
  python evaluate.py            extract the samples that have no result yet, then score
  python evaluate.py --fresh    extract every sample again

Writes output/evaluation.json and prints one line per table.
"""

from __future__ import annotations

import argparse
import json
import time

from app import pipeline
from app.accuracy import evaluate, load_truth
from app.config import settings
from app.tables import tables_from_markdown


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fresh", action="store_true", help="extract again even if a result exists")
    args = parser.parse_args()

    truth = load_truth(settings.ground_truth)
    report, cells, correct = [], 0, 0
    for name in truth:
        path = settings.documents / name
        result = None if args.fresh else pipeline.load(path)
        if result is None:
            started = time.time()
            print(f"Extracting {name} ...", flush=True)
            result = pipeline.process(path, lambda step: print(f"  {step}", flush=True))
            print(f"  {time.time() - started:.1f} s", flush=True)
        scores = evaluate(name, result["tables"], truth, key="extracted_rows")
        for s in scores:
            cells += s["cells"]
            correct += s["correct"]
            print(f"{name:32} {s['title'][:38]:38} {s['method'] or '-':26} {s['correct']:4}/{s['cells']:<4} {s['accuracy']:.1%}")
            for w in s["wrong"][:8]:
                print(f"{'':34}row {w['row'] + 1}, column {w['col'] + 1}: expected {w['expected']!r}, found {w['found']!r}")
        report.append({"document": name, "seconds": result["seconds"], "tables_found": len(result["tables"]),
                       "tables": [{k: v for k, v in s.items()} for s in scores]})

    # Baseline: the tables of the Markdown export as they come, one per page, without the
    # header repair, the page stitching or the vision model.
    print("\nMarkdown export alone (no header repair, no stitching, no vision model):")
    base_cells = base_correct = 0
    for name in truth:
        md = pipeline.output_dir(settings.documents / name) / "document.md"
        found = [{"id": i, "pages": [t["page"]], "rows": t["rows"], "method": "markdown as exported"}
                 for i, t in enumerate(tables_from_markdown(md.read_text(encoding="utf-8"), repair=False), start=1)]
        for s in evaluate(name, found, truth):
            base_cells += s["cells"]
            base_correct += s["correct"]
            print(f"{name:32} {s['title'][:38]:38} {s['correct']:4}/{s['cells']:<4} {s['accuracy']:.1%}")
        report[[r["document"] for r in report].index(name)]["markdown_only"] = [
            {k: s[k] for k in ("title", "cells", "correct", "accuracy")} for s in evaluate(name, found, truth)]
    baseline = {"cells": base_cells, "correct": base_correct, "accuracy": round(base_correct / base_cells, 4) if base_cells else 0}

    total = {"cells": cells, "correct": correct, "accuracy": round(correct / cells, 4) if cells else 0}
    print(f"\nAll tables, full pipeline: {correct}/{cells} cells, {total['accuracy']:.1%}")
    print(f"All tables, Markdown export alone: {base_correct}/{base_cells} cells, {baseline['accuracy']:.1%}")
    settings.output.mkdir(parents=True, exist_ok=True)
    (settings.output / "evaluation.json").write_text(
        json.dumps({"vision_model": settings.vision_model, "total": total, "markdown_only": baseline, "documents": report}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
