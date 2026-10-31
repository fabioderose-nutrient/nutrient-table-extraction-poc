"""Web API and static page of the table extraction demo."""

from __future__ import annotations

import io
import re
import threading
import zipfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import pipeline
from .accuracy import evaluate, load_truth
from .config import ROOT, settings
from .export import csv_text, workbook

app = FastAPI(title="Table extraction")
jobs: dict[str, dict] = {}
lock = threading.Lock()


def documents() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for folder in (settings.documents, settings.uploads):
        if folder.exists():
            for p in sorted(folder.glob("*.pdf")):
                found[pipeline.doc_id(p)] = p
    return found


def document(doc: str) -> Path:
    path = documents().get(doc)
    if not path:
        raise HTTPException(404, "Unknown document.")
    return path


def accuracy(path: Path, result: dict) -> dict | None:
    truth = load_truth(settings.ground_truth)
    if path.name not in truth or path.parent != settings.documents:
        return None
    extracted = evaluate(path.name, result["tables"], truth, key="extracted_rows")
    current = evaluate(path.name, result["tables"], truth, key="rows")

    def total(items: list[dict]) -> dict:
        cells = sum(i["cells"] for i in items)
        correct = sum(i["correct"] for i in items)
        return {"cells": cells, "correct": correct, "accuracy": round(correct / cells, 4) if cells else 0}

    for e, c in zip(extracted, current):
        e["after_review"] = {k: c[k] for k in ("correct", "accuracy")}
        e["wrong_now"] = c["wrong"]
    return {"tables": extracted, "extracted": total(extracted), "after_review": total(current)}


@app.get("/api/config")
def config():
    return {"web_sdk_license_key": settings.web_sdk_license_key, "vision_model": settings.vision_model}


@app.get("/api/documents")
def list_documents():
    items = []
    for doc, path in documents().items():
        result = pipeline.load(path)
        acc = accuracy(path, result) if result else None
        items.append({"id": doc, "name": path.name, "sample": path.parent == settings.documents,
                      "tables": len(result["tables"]) if result else None,
                      "accuracy": acc["after_review"]["accuracy"] if acc else None,
                      "job": jobs.get(doc)})
    return items


@app.post("/api/documents")
async def upload(request: Request, name: str):
    body = await request.body()
    if not body.startswith(b"%PDF"):
        raise HTTPException(400, "Send a PDF file as the request body.")
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", Path(name).name)
    if not safe.lower().endswith(".pdf"):
        safe += ".pdf"
    settings.uploads.mkdir(parents=True, exist_ok=True)
    (settings.uploads / safe).write_bytes(body)
    return {"id": pipeline.doc_id(settings.uploads / safe)}


@app.get("/api/documents/{doc}/file")
def file(doc: str):
    return FileResponse(document(doc), media_type="application/pdf")


@app.get("/api/documents/{doc}")
def result(doc: str):
    path = document(doc)
    data = pipeline.load(path)
    return {"id": doc, "name": path.name, "job": jobs.get(doc), "result": data,
            "accuracy": accuracy(path, data) if data else None}


def _run(doc: str, path: Path) -> None:
    def progress(step: str) -> None:
        jobs[doc]["step"] = step

    try:
        with lock:  # one document at a time: the vision model is the bottleneck
            pipeline.process(path, progress)
        jobs[doc] = {"state": "done"}
    except Exception as exc:  # reported to the page
        jobs[doc] = {"state": "error", "error": str(exc)}


@app.post("/api/documents/{doc}/extract")
def extract(doc: str):
    path = document(doc)
    if jobs.get(doc, {}).get("state") == "running":
        return jobs[doc]
    jobs[doc] = {"state": "running", "step": "Waiting for the previous document"}
    threading.Thread(target=_run, args=(doc, path), daemon=True).start()
    return jobs[doc]


class Rows(BaseModel):
    rows: list[list[str]]
    header_rows: int | None = None


@app.put("/api/documents/{doc}/tables/{table_id}")
def save_table(doc: str, table_id: int, body: Rows):
    path = document(doc)
    data = pipeline.load(path)
    if not data:
        raise HTTPException(404, "Extract the document first.")
    table = next((t for t in data["tables"] if t["id"] == table_id), None)
    if not table:
        raise HTTPException(404, "Unknown table.")
    if len(body.rows) != len(table["rows"]) or any(len(r) != len(table["rows"][0]) for r in body.rows):
        raise HTTPException(400, "Rows and columns must stay the same.")
    table["rows"] = body.rows
    if body.header_rows is not None:
        table["header_rows"] = max(0, min(body.header_rows, len(body.rows)))
    pipeline.finish(table)
    pipeline.save(path, data)
    return {"table": table, "accuracy": accuracy(path, data)}


@app.post("/api/documents/{doc}/tables/{table_id}/vision")
def reread(doc: str, table_id: int):
    path = document(doc)
    data = pipeline.load(path)
    if not data:
        raise HTTPException(404, "Extract the document first.")
    try:
        with lock:
            table = pipeline.reread_with_vision(path, data, table_id)
    except StopIteration:
        raise HTTPException(404, "Unknown table.")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"table": table, "accuracy": accuracy(path, data)}


@app.post("/api/documents/{doc}/tables/{table_id}/revert")
def revert(doc: str, table_id: int):
    path = document(doc)
    data = pipeline.load(path)
    table = next((t for t in (data or {}).get("tables", []) if t["id"] == table_id), None)
    if not table or not table.get("previous"):
        raise HTTPException(404, "Nothing to revert.")
    prev = table.pop("previous")
    table.update(prev)
    table["extracted_rows"] = [list(r) for r in table["rows"]]
    pipeline.finish(table)
    pipeline.locate_after_reread(table, path)
    pipeline.save(path, data)
    return {"table": table, "accuracy": accuracy(path, data)}


@app.get("/api/documents/{doc}/tables.xlsx")
def xlsx(doc: str):
    path = document(doc)
    data = pipeline.load(path)
    if not data or not data["tables"]:
        raise HTTPException(404, "No tables.")
    return Response(workbook(path.name, data["tables"]),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{doc}-tables.xlsx"'})


@app.get("/api/documents/{doc}/tables.zip")
def csv_zip(doc: str):
    path = document(doc)
    data = pipeline.load(path)
    if not data or not data["tables"]:
        raise HTTPException(404, "No tables.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for t in data["tables"]:
            slug = re.sub(r"[^a-z0-9]+", "-", t["title"].lower()).strip("-") or "table"
            z.writestr(f"{t['id']:02d}-{slug}.csv", csv_text(t))
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{doc}-tables-csv.zip"'})


@app.get("/api/documents/{doc}/tables/{table_id}.csv")
def csv_one(doc: str, table_id: int):
    data = pipeline.load(document(doc))
    table = next((t for t in (data or {}).get("tables", []) if t["id"] == table_id), None)
    if not table:
        raise HTTPException(404, "Unknown table.")
    return Response(csv_text(table), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{doc}-table-{table_id}.csv"'})


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
