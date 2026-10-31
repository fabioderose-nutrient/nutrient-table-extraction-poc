// Table extraction demo: documents, viewer with highlights, editable tables.

const SDK_BASE = "https://cdn.cloud.pspdfkit.com/pspdfkit-web@1.24.0/";
const $ = (id) => document.getElementById(id);
const state = { config: null, docs: [], current: null, data: null, instance: null, marks: [], poll: null };

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pct = (v) => (v * 100).toFixed(1) + "%";

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch { /* not JSON */ }
    throw new Error(msg);
  }
  return res.json();
}

// ---------------------------------------------------------------- documents

async function loadDocs() {
  state.docs = await api("/api/documents");
  $("doc-list").innerHTML = state.docs.map((d) => {
    const running = d.job && d.job.state === "running";
    const status = running ? `<span class="badge run">extracting</span>`
      : d.tables == null ? `<span class="muted small">not extracted</span>`
      : `<span class="small">${d.tables} table${d.tables === 1 ? "" : "s"}</span>` +
        (d.accuracy != null ? ` <span class="badge ok" title="Cell accuracy against the ground truth">${pct(d.accuracy)}</span>` : "");
    return `<li class="${d.id === state.current ? "active" : ""}" data-id="${d.id}">
      <div class="doc-name">${esc(d.name)}</div><div>${status}</div></li>`;
  }).join("");
  for (const li of $("doc-list").querySelectorAll("li")) li.onclick = () => openDoc(li.dataset.id);
}

async function openDoc(id) {
  state.current = id;
  await loadDocs();
  const doc = state.docs.find((d) => d.id === id);
  $("doc-title").textContent = doc.name;
  await loadViewer(`/api/documents/${id}/file`);
  await refresh();
}

async function refresh() {
  const id = state.current;
  const data = await api(`/api/documents/${id}`);
  if (id !== state.current) return;
  state.data = data;
  const job = data.job;
  const running = job && job.state === "running";
  $("extract-btn").hidden = running;
  $("extract-btn").textContent = data.result ? "Extract again" : "Extract tables";
  $("progress").hidden = !running && !(job && job.state === "error");
  $("progress").innerHTML = running ? `<span class="spinner"></span> ${esc(job.step || "Working")}`
    : job && job.state === "error" ? `<span class="error">${esc(job.error)}</span>` : "";
  clearInterval(state.poll);
  if (running) state.poll = setInterval(async () => { await refresh(); if (!(state.data.job && state.data.job.state === "running")) loadDocs(); }, 2000);
  renderResult();
}

function renderResult() {
  const { result, accuracy } = state.data;
  const has = result && result.tables.length > 0;
  $("xlsx-btn").hidden = $("csv-btn").hidden = !has;
  $("xlsx-btn").href = `/api/documents/${state.current}/tables.xlsx`;
  $("csv-btn").href = `/api/documents/${state.current}/tables.zip`;
  $("truth-toggle").hidden = !accuracy;
  if (!result) {
    $("doc-meta").textContent = "";
    $("accuracy").hidden = true;
    $("tables").innerHTML = `<div class="empty small">Click <b>Extract tables</b>. Scanned pages and pictures are read by the vision model, which can take a minute or two per page on a local model.</div>`;
    return;
  }
  const scanned = result.pages.filter((p) => p.scanned).length;
  $("doc-meta").textContent = `${result.pages.length} page${result.pages.length === 1 ? "" : "s"}${scanned ? `, ${scanned} scanned` : ""} · ${result.tables.length} table${result.tables.length === 1 ? "" : "s"} · SDK ${result.seconds.sdk} s, vision model ${result.seconds.vision} s`;
  renderAccuracy(accuracy);
  $("tables").innerHTML = result.tables.map(renderTable).join("") || `<div class="empty small">No table found.</div>`;
  bindTables();
}

function renderAccuracy(acc) {
  if (!acc) { $("accuracy").hidden = true; return; }
  $("accuracy").hidden = false;
  const e = acc.extracted, r = acc.after_review;
  $("accuracy").innerHTML = `<b>Cell accuracy against the ground truth:</b> ${pct(e.accuracy)} extracted (${e.correct}/${e.cells} cells)` +
    (r.correct !== e.correct ? ` · <b>${pct(r.accuracy)}</b> after your corrections` : "");
}

// ---------------------------------------------------------------- tables

function truthFor(table) {
  const acc = state.data.accuracy;
  return acc ? acc.tables.find((t) => t.table_id === table.id) : null;
}

function renderTable(t) {
  const flags = new Map(t.flags.map((f) => [`${f.row},${f.col}`, f.reason]));
  const totals = new Set(t.total_rows);
  const failed = t.checks.filter((c) => !c.ok).length;
  const checks = t.checks.length === 0 ? `<span class="muted">no total row to check</span>`
    : failed ? `<span class="bad">totals: ${failed} of ${t.checks.length} do not add up</span>`
    : `<span class="good">totals add up (${t.checks.length})</span>`;
  const truth = truthFor(t);
  const tAcc = truth ? `<span class="badge ${truth.after_review.accuracy === 1 ? "ok" : "warn"}" title="Cell accuracy against the ground truth">${pct(truth.after_review.accuracy)}</span>` : "";
  const pages = t.pages.length > 1 ? `pages ${t.pages[0]}-${t.pages[t.pages.length - 1]}` : `page ${t.pages[0]}`;
  const body = t.rows.map((row, r) => `<tr class="${r < t.header_rows ? "hdr" : ""}${totals.has(r) ? " total" : ""}">` +
    `<td class="rn">${r + 1}</td>` + row.map((cell, c) => {
      const flag = flags.get(`${r},${c}`);
      const edited = t.extracted_rows[r] && t.extracted_rows[r][c] !== cell;
      const num = r >= t.header_rows && /^[-+(]?[\d.,]+%?\)?$/.test(cell.trim());
      const cls = [flag ? "flag" : "", edited ? "edited" : "", num ? "num" : ""].join(" ").trim();
      return `<td contenteditable="true" spellcheck="false" data-r="${r}" data-c="${c}" class="${cls}" title="${esc(flag || "")}">${esc(cell)}</td>`;
    }).join("") + "</tr>").join("");
  return `<article class="card" data-id="${t.id}">
    <header class="card-head" data-id="${t.id}">
      <div class="card-title">${esc(t.title)} ${tAcc}</div>
      <div class="small muted">${pages} · ${t.rows.length} × ${t.rows[0].length} · <span class="method">${esc(t.method)}</span> · ${checks}${t.flags.length ? ` · <span class="bad">${t.flags.length} cell${t.flags.length === 1 ? "" : "s"} to check</span>` : ""}</div>
    </header>
    <div class="grid-wrap"><table class="grid">${body}</table></div>
    ${t.flags.length ? `<ul class="flags">${t.flags.map((f) => `<li data-r="${f.row}" data-c="${f.col}"><b>Row ${f.row + 1}, ${esc(t.rows[0][f.col] || `column ${f.col + 1}`)}:</b> ${esc(t.rows[f.row][f.col])} · ${esc(f.reason)}${f.ocr ? `. OCR line: <code>${esc(f.ocr)}</code>` : ""}</li>`).join("")}</ul>` : ""}
    <footer class="card-actions">
      <button class="secondary small-btn" data-act="vision" data-id="${t.id}">Re-read with vision model</button>
      ${t.previous ? `<button class="secondary small-btn" data-act="revert" data-id="${t.id}">Back to ${esc(t.previous.method)}</button>` : ""}
      <a class="small" href="/api/documents/${state.current}/tables/${t.id}.csv">CSV</a>
    </footer>
  </article>`;
}

function bindTables() {
  const tables = state.data.result.tables;
  for (const card of document.querySelectorAll(".card")) {
    const t = tables.find((x) => x.id === Number(card.dataset.id));
    card.querySelector(".card-head").onclick = () => highlight(t, null, null);
    for (const td of card.querySelectorAll("td[data-r]")) {
      td.onfocus = () => highlight(t, Number(td.dataset.r), Number(td.dataset.c));
      td.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); td.blur(); } };
      td.onblur = () => saveCell(t, td);
    }
    for (const btn of card.querySelectorAll("button[data-act]")) btn.onclick = () => tableAction(btn, t);
    for (const li of card.querySelectorAll(".flags li")) {
      li.onclick = () => card.querySelector(`td[data-r="${li.dataset.r}"][data-c="${li.dataset.c}"]`).focus();
    }
  }
  markTruth();
}

function markTruth() {
  const on = $("show-truth").checked;
  for (const card of document.querySelectorAll(".card")) {
    const t = state.data.result.tables.find((x) => x.id === Number(card.dataset.id));
    const truth = truthFor(t);
    for (const td of card.querySelectorAll("td[data-r]")) td.classList.remove("wrong");
    if (!on || !truth) continue;
    const wrong = currentWrong(t, truth);
    for (const [r, c] of wrong) {
      const td = card.querySelector(`td[data-r="${r}"][data-c="${c}"]`);
      if (td) td.classList.add("wrong");
    }
  }
}

function currentWrong(t, gt) {
  // Cells of the current rows that differ from the ground-truth cell they are aligned with.
  return gt.wrong_now.filter((w) => w.found_row !== null).map((w) => [w.found_row, w.col]);
}

async function saveCell(t, td) {
  const r = Number(td.dataset.r), c = Number(td.dataset.c);
  const value = td.textContent.replace(/\s+/g, " ").trim();
  if (value === t.rows[r][c]) return;
  const rows = t.rows.map((row) => row.slice());
  rows[r][c] = value;
  try {
    const res = await api(`/api/documents/${state.current}/tables/${t.id}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rows }),
    });
    Object.assign(t, res.table);
    state.data.accuracy = res.accuracy;
    td.classList.toggle("edited", t.extracted_rows[r][c] !== value);
    renderAccuracy(res.accuracy);
    const card = td.closest(".card");
    card.outerHTML = renderTable(t);
    bindTables();
    loadDocs();
  } catch (err) {
    alert(err.message);
  }
}

async function tableAction(btn, t) {
  const act = btn.dataset.act;
  btn.disabled = true;
  btn.innerHTML = act === "vision" ? `<span class="spinner"></span> Reading the page image…` : "Reverting…";
  try {
    const res = await api(`/api/documents/${state.current}/tables/${t.id}/${act}`, { method: "POST" });
    Object.assign(t, res.table);
    if (act === "revert") delete t.previous;
    state.data.accuracy = res.accuracy;
    renderResult();
    loadDocs();
  } catch (err) {
    alert(err.message);
    btn.disabled = false;
    btn.textContent = "Re-read with vision model";
  }
}

$("show-truth").onchange = markTruth;

// ---------------------------------------------------------------- viewer and highlights

async function loadViewer(url) {
  const NV = window.NutrientViewer;
  if (state.instance) { NV.unload("#viewer"); state.instance = null; state.marks = []; }
  $("viewer-empty").hidden = true;
  state.instance = await NV.load({
    container: "#viewer",
    document: url,
    baseUrl: SDK_BASE,
    licenseKey: state.config.web_sdk_license_key || undefined,
    toolbarItems: NV.defaultToolbarItems.filter((i) => ["sidebar-thumbnails", "pager", "zoom-out", "zoom-in", "zoom-mode", "search"].includes(i.type)),
    isEditableAnnotation: () => false,
    initialViewState: new NV.ViewState({ zoom: NV.ZoomMode.FIT_TO_WIDTH }),
  });
}

async function highlight(table, r, c) {
  const NV = window.NutrientViewer;
  const inst = state.instance;
  if (!inst) return;
  if (state.marks.length) { try { await inst.delete(state.marks); } catch { /* gone */ } state.marks = []; }
  const make = (b, fill) => new NV.Annotations.RectangleAnnotation({
    pageIndex: b.page - 1,
    boundingBox: new NV.Geometry.Rect({ left: b.x, top: b.y, width: b.w, height: b.h }),
    strokeColor: fill ? new NV.Color({ r: 230, g: 140, b: 0 }) : new NV.Color({ r: 59, g: 91, b: 122 }),
    strokeWidth: fill ? 1.5 : 2,
    fillColor: fill ? new NV.Color({ r: 255, g: 214, b: 0 }) : null,
    opacity: fill ? 0.45 : 1,
  });
  const annots = [];
  for (const seg of table.segments) if (seg.box) annots.push(make({ page: seg.page, ...seg.box }, false));
  let focus = annots[0];
  if (r !== null) {
    const cell = table.cell_boxes[r] && table.cell_boxes[r][c];
    const row = table.row_boxes[r];
    if (cell) { focus = make(cell, true); annots.push(focus); }
    else if (row) { focus = make(row, true); annots.push(focus); }
  }
  if (!annots.length) return;
  const created = await inst.create(annots);
  state.marks = created.map((a) => a.id);
  // Zoom to the table part on the page of the focused cell, with a margin.
  const page = focus.pageIndex;
  const seg = table.segments.find((s) => s.page - 1 === page && s.box);
  const area = seg ? seg.box : { x: focus.boundingBox.left, y: focus.boundingBox.top, w: focus.boundingBox.width, h: focus.boundingBox.height };
  const pad = 24;
  inst.jumpAndZoomToRect(page, new NV.Geometry.Rect({ left: area.x - pad, top: area.y - pad, width: area.w + 2 * pad, height: area.h + 2 * pad }));
}

// ---------------------------------------------------------------- start

$("extract-btn").onclick = async () => {
  await api(`/api/documents/${state.current}/extract`, { method: "POST" });
  await refresh();
  loadDocs();
};

$("upload").onchange = async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const res = await api(`/api/documents?name=${encodeURIComponent(file.name)}`, { method: "POST", body: file });
  e.target.value = "";
  await openDoc(res.id);
};

(async () => {
  state.config = await api("/api/config");
  $("model-chip").textContent = `Vision model: ${state.config.vision_model}`;
  await loadDocs();
  const wanted = new URLSearchParams(location.search).get("doc");
  const first = state.docs.find((d) => d.id === wanted) || state.docs[0];
  if (first) openDoc(first.id);
})();
