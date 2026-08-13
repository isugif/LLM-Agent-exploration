"use strict";

const $ = (id) => document.getElementById(id);
const log = $("log");
const panel = $("panel");
const panelEmpty = $("panel-empty");

// ---- per-question turns: each captures its own Output / Activity / Terminal ----
let turns = [];      // {q, out:[htmlCard], mode, act:[{ts,kind,text}], term:[str]}
let view = -1;       // which turn is displayed
let stream = -1;     // which turn is receiving live events

function startTurn(q) {
  turns.push({ q, out: [], mode: null, act: [], term: [] });
  stream = turns.length - 1;
  const opt = document.createElement("option");
  opt.value = String(stream);
  opt.textContent = `${stream + 1}. ${q.slice(0, 44)}`;
  $("turn-select").appendChild(opt);
  showTurn(stream);
}

function showTurn(i) {
  if (i < 0 || i >= turns.length) return;
  view = i;
  const t = turns[i];
  if (t.out.length) { panelEmpty.hidden = true; panel.hidden = false; panel.innerHTML = t.out.join(""); }
  else { panelEmpty.hidden = false; panel.hidden = true; panel.innerHTML = ""; }
  const af = $("activity");
  af.innerHTML = t.act.length ? t.act.map(actHTML).join("")
    : '<div class="act-empty">Activity for this question appears here.</div>';
  af.scrollTop = af.scrollHeight;
  const term = $("terminal");
  term.textContent = t.term.length ? t.term.join("\n") + "\n" : "";
  term.scrollTop = term.scrollHeight;
  $("turn-select").value = String(i);
}

// ---- output (Output tab) — string-based, stored per turn ----
function setOutput(html, mode) {
  const t = turns[stream]; if (!t) return;
  t.out = [html]; t.mode = mode || "profile";
  if (view === stream) { panelEmpty.hidden = true; panel.hidden = false; panel.innerHTML = html; }
}
function appendOutput(html) {
  const t = turns[stream]; if (!t) return;
  t.out.push(html);
  if (view === stream) { panelEmpty.hidden = true; panel.hidden = false; panel.insertAdjacentHTML("beforeend", html); }
}
function appendStage(ev) {
  const t = turns[stream]; if (!t) return;
  if (t.mode !== "pipeline") {
    appendOutput(`<div class="run-head"><h2>Pipeline / install</h2><div class="file-name">four-harness flow</div></div>`);
    t.mode = "pipeline";
  }
  appendOutput(stageCardHTML(ev));
}

// ---- activity (Activity tab), stored per turn ----
function actHTML(l) {
  return `<div class="act-line act-${l.kind}"><span class="ts">${l.ts}</span>` +
    `<span class="act-text">${esc(l.text)}</span></div>`;
}
function addActivity(text, kind) {
  const t = turns[stream]; if (!t) return;
  const line = { ts: new Date().toLocaleTimeString([], { hour12: false }), kind: kind || "info", text };
  t.act.push(line);
  if (view === stream) {
    const af = $("activity"); const e = af.querySelector(".act-empty"); if (e) e.remove();
    af.insertAdjacentHTML("beforeend", actHTML(line)); af.scrollTop = af.scrollHeight;
    if (currentTab !== "activity") $("act-badge").hidden = false;
  }
}

// ---- terminal (Terminal tab), stored per turn ----
function term(line) {
  const t = turns[stream]; if (!t) return;
  t.term.push(line);
  if (view === stream) {
    const el = $("terminal"); el.appendChild(document.createTextNode(line + "\n")); el.scrollTop = el.scrollHeight;
  }
}
function termStage(ev) {
  if (ev.stage === "provision") {
    term(ev.method ? "$ " + ev.method : `[provision] installed=${ev.installed}`);
    if (ev.reason) term("  " + ev.reason);
  } else if (ev.stage === "docs_check") {
    term(`[docs] have=${(ev.have || []).join(",") || "-"} missing=${(ev.missing || []).join(",") || "-"}`);
  } else if (ev.stage === "source") {
    term(`[source] ${ev.chars} chars of --help${ev.url ? " + docs" : ""}`);
  } else if (ev.stage === "curate") {
    term(`[curate:${ev.section}] ${ev.status} (items=${ev.items}, fixes=${ev.fixes})`);
  } else if (ev.stage === "execution") {
    term(`[execution] exit=${ev.exit_code}`);
    if (ev.stderr_tail) term(ev.stderr_tail.trimEnd());
    if (ev.error) term("ERROR: " + ev.error);
  } else if (ev.stage === "evaluation" || ev.stage === "diagnosis") {
    term(`[${ev.stage}] ${ev.status}`);
    (ev.findings || []).forEach((f) => term("  - " + f));
  } else {
    term(`[${ev.stage}] ${ev.title || ""}`);
  }
}

// ---- SSE-over-fetch: POST then parse the text/event-stream body ----
async function* sse(resp) {
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, i);
      buf = buf.slice(i + 2);
      let event = "message", data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      yield { event, data };
    }
  }
}

let convo = [];   // [{role, content}] conversation memory (a bounded window is sent each turn)

// ---- persistent session id: points at the current on-disk session (server holds the run-log) ----
function newSid() {
  const u = (crypto.randomUUID && crypto.randomUUID()) ||
    "xxxxxxxxxxxx4xxxyxxxxxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0; return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  return u.replace(/-/g, "");
}
let sid = localStorage.getItem("bioSid") || newSid();
localStorage.setItem("bioSid", sid);

function addMsg(text, who, cls) {
  const div = document.createElement("div");
  div.className = "msg " + who + (cls ? " " + cls : "");
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

// One render path for BOTH live streaming and replay. `ctx` carries the assistant bubble + a
// mutable planSteps holder; `replay` skips live-only affordances (progress bar, sid adoption).
function applyEvent(event, data, ctx, replay) {
  if (event === "meta") {
    const m = JSON.parse(data);
    if (!replay && m.sid && m.sid !== sid) { sid = m.sid; localStorage.setItem("bioSid", sid); }
    const what = m.mode === "agent" ? "mode: agent" : `intent: ${m.intent}`;
    addActivity(`${what} · model: ${m.provider}`, "meta");
    term(`[meta] ${what} model=${m.provider}`);
    const brain = $("brain");
    if (brain) brain.textContent = m.mode === "agent"
      ? `🧠 agent · ${m.provider}${m.model ? " · " + m.model : ""}`
      : "🧠 deterministic";
  } else if (event === "plan") {
    ctx.planSteps = JSON.parse(data).steps;
    if (!replay) setProgressTotal(ctx.planSteps.length);
  } else if (event === "log") {
    const t = JSON.parse(data).text;
    addActivity(t, "think"); if (!replay) setThinking(ctx.thinking, t); term("… " + t);
  } else if (event === "panel") {
    const p = JSON.parse(data);
    let html, mode, note;
    if (p.kind === "tool") { html = toolPanelHTML(p); mode = "tool"; note = "documentation ready"; }
    else if (p.kind === "catalog") { html = catalogPanelHTML(p); mode = "catalog"; note = "tool matches ready"; }
    else if (p.kind === "session") { html = sessionPanelHTML(p); mode = "session"; note = "session history ready"; }
    else if (p.kind === "folder") { html = folderPanelHTML(p); mode = "folder"; note = "folder contents ready"; setWorkdirLabel(p.workdir); }
    else { html = dataPanelHTML(p); mode = "profile"; note = "data profile ready"; }
    setOutput(html, mode);
    addActivity(note, "ok");
  } else if (event === "stage") {
    const ev = JSON.parse(data);
    appendStage(ev);
    addActivity(stageLine(ev), "stage");
    if (!replay) { setThinking(ctx.thinking, stageLine(ev)); advanceProgress(ev, ctx.planSteps); }
    termStage(ev);
  } else if (event === "prose") {
    const t = JSON.parse(data).text;
    ctx.thinking.classList.remove("thinking");
    ctx.thinking.textContent = t;
    log.scrollTop = log.scrollHeight;
    term("[response] " + t);
    convo.push({ role: "assistant", content: t });
    if (convo.length > 40) convo = convo.slice(-40);
  } else if (event === "done") {
    addActivity("done", "done");
  }
}

async function send(message, file, provider, signal, history, model) {
  const resp = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, file: file || null, provider, model: model || null,
                           history: history || [], session_id: sid }),
    signal,
  });
  if (!resp.ok) { addMsg("Server error: " + resp.status, "assistant", "warn"); return; }

  const ctx = { thinking: addMsg("…", "assistant", "thinking"), planSteps: null };
  startWork();
  try {
    for await (const { event, data } of sse(resp)) applyEvent(event, data, ctx, false);
  } catch (e) {
    if (e.name === "AbortError") {
      ctx.thinking.classList.remove("thinking");
      ctx.thinking.textContent = "⏹ Stopped. (the server may finish this step in the background)";
    }
    throw e;
  } finally {
    endWork();
  }
}

// Repaint a saved session: replay each turn's stored event stream through the same render path.
async function replaySession(targetSid) {
  let turns = [];
  try { turns = (await (await fetch(`/api/sessions/${targetSid}/transcript`)).json()).turns || []; }
  catch (e) { return false; }
  if (!turns.length) return false;
  log.innerHTML = "";                                 // drop the greeting / any prior chat
  for (const t of turns) {
    if (t.question) { addMsg(t.question, "user"); convo.push({ role: "user", content: t.question }); }
    startTurn(t.question || "(session)");
    const ctx = { thinking: addMsg("…", "assistant", "thinking"), planSteps: null };
    for (const ev of (t.events || [])) applyEvent(ev.event, ev.data, ctx, true);   // prose pushes assistant → convo
  }
  return turns.length > 0;
}

function stageLine(ev) {
  if (ev.stage === "docs_check") {
    return ev.title + " — " + ((ev.missing && ev.missing.length) ? ev.missing.length + " missing" : "complete");
  }
  const extra = ev.action || ev.status || (ev.installed === false ? "blocked" : "") ||
    (ev.section ? ev.status : "");
  return ev.title + (extra ? " — " + extra : "");
}

// ---- working state: progress bar + live "current step" spinner in the chat bubble ----
function setThinking(bubble, text) {
  bubble.classList.add("thinking");
  bubble.innerHTML = `<span class="spin"></span><span class="cur"></span>`;
  bubble.querySelector(".cur").textContent = text;
  log.scrollTop = log.scrollHeight;
}
function startWork() {
  const p = $("progress"), f = $("progress-fill");
  p.hidden = false; p.classList.add("indeterminate"); f.style.width = "0%";
  p.dataset.total = "0"; p.dataset.done = "0";
}
function setProgressTotal(n) { $("progress").classList.remove("indeterminate"); $("progress").dataset.total = String(n); }
function advanceProgress(ev, planSteps) {
  if (!planSteps) return;
  const key = ev.section ? `curate:${ev.section}` : ev.stage;
  const idx = planSteps.indexOf(key);
  const p = $("progress");
  const done = idx >= 0 ? idx + 1 : Number(p.dataset.done || 0);
  p.dataset.done = String(done);
  $("progress-fill").style.width = Math.round((done / planSteps.length) * 100) + "%";
}
function endWork() {
  const p = $("progress"), f = $("progress-fill");
  p.classList.remove("indeterminate");
  f.style.width = "100%";
  setTimeout(() => { p.hidden = true; f.style.width = "0%"; }, 500);
}

// ---- output HTML builders (return strings; stored per turn) ----
function dataPanelHTML(p) {
  let h = `<div><h2>Data profile</h2><div class="file-name">${esc(p.file || "")}</div></div>`;
  if (p.error) return h + cardHTML("Error", `<span class="warn">${esc(p.error)}</span>`);
  const rows = (p.facts || []).map((r) =>
    `<tr><td class="k">${esc(r.label)}</td><td class="v">${esc(fmt(r.value))}</td></tr>`).join("");
  h += cardHTML("Measured facts", `<table class="facts"><tbody>${rows}</tbody></table>`);
  if (p.disagreements && p.disagreements.length) {
    h += cardHTML("Needs a double-check", chips(p.disagreements));
  } else if (p.declared && Object.keys(p.declared).length) {
    h += cardHTML("Declared vs measured",
      `<span class="ok">No conflicts between what you stated and what was measured.</span>`);
  }
  if (p.length_hist && Object.keys(p.length_hist).length) h += cardHTML("Read-length distribution", barChart(p.length_hist));
  if (p.qual_by_pos && p.qual_by_pos.length) h += cardHTML("Mean quality by position", lineChart(p.qual_by_pos));
  return h;
}

function toolPanelHTML(p) {
  const rev = p.reviewed ? "" : ` · <span class="warn">contract pending review</span>`;
  let h = `<div><h2>${esc(p.tool)}${p.version ? " " + esc(p.version) : ""}</h2>
    <div class="file-name">documented tool${rev}</div></div>`;
  if (p.summary) h += cardHTML("Summary", `<p>${esc(p.summary)}</p>`);
  if (p.usage && p.usage.length) {
    h += cardHTML("Usage", p.usage.map((e) =>
      `<div class="usage-ex"><div class="ux-desc">${esc(e.description || "")}</div><code>${esc(e.command || "")}</code></div>`).join(""));
  }
  if (p.options && p.options.length) {
    const rows = p.options.map((o) =>
      `<tr><td class="k">${esc(o.flag)}</td><td class="v">${esc(o.description || "")}` +
      `${o.default ? ` <span class="muted">(default ${esc(o.default)})</span>` : ""}</td></tr>`).join("");
    h += cardHTML(`Parameters (${p.options.length})`, `<table class="facts"><tbody>${rows}</tbody></table>`);
  }
  if (p.boundaries && p.boundaries.length) h += cardHTML("Off-label boundaries", list(p.boundaries));
  if (p.citation) h += cardHTML("Citation", `<code>${esc(p.citation)}</code>`);
  return h;
}

function sessionPanelHTML(p) {
  const idline = [p.sid ? `session ${esc(p.sid.slice(0, 8))}…` : "this analysis session",
    p.created ? `started ${esc(p.created)}` : "",
    (p.tools && p.tools.length) ? `tools: ${esc(p.tools.join(", "))}` : ""].filter(Boolean).join(" · ");
  let h = `<div><h2>Session runs${p.count != null ? ` (${p.count})` : ""}</h2>
    <div class="file-name">${idline}</div></div>`;
  if (!p.runs || !p.runs.length) {
    return h + cardHTML("No runs yet", `<span class="muted">Run a tool and it will be recorded here.</span>`);
  }
  for (const r of p.runs) {
    const v = r.verdict || r.action || "?";
    const cls = v === "ok" ? "badge-ok" : (v === "refuse" || v === "failure") ? "badge-bad" : "badge-warn";
    const body = `<span class="badge ${cls}">${esc(v)}</span>` +
      kvTable({ when: r.when, output: r.out_dir, question: r.question }) +
      reportControls(r.out_name);
    h += cardHTML(esc(r.tool || "run"), body);
  }
  return h;
}

function folderPanelHTML(p) {
  let h = `<div><h2>Working directory</h2><div class="file-name">${esc(p.workdir || "")}</div></div>`;
  if (!p.groups || !p.groups.length) {
    return h + cardHTML("Empty", `<span class="muted">No recognizable data files here yet.</span>`);
  }
  for (const g of p.groups) {
    const shown = (g.files || []).length;
    const more = g.count > shown ? `<div class="muted">+${g.count - shown} more</div>` : "";
    h += cardHTML(`${esc(g.kind)} (${g.count})`, list(g.files) + more);
  }
  return h;
}

function catalogPanelHTML(p) {
  const q = p.query || {};
  const crit = [q.category && q.category.replace(/_/g, " "), q.input_format && `input: ${q.input_format}`]
    .filter(Boolean).join(" · ");
  let h = `<div><h2>Tool matches${p.count != null ? ` (${p.count})` : ""}</h2>
    <div class="file-name">${esc(crit || "catalog")}</div></div>`;
  if (!p.tools || !p.tools.length) {
    return h + cardHTML("No match", `<span class="warn">No documented tool fits — try "install &lt;tool&gt;".</span>`);
  }
  for (const t of p.tools) {
    const badge = t.reviewed ? `<span class="badge badge-ok">reviewed</span>`
      : `<span class="badge badge-warn">pending review</span>`;
    const cats = (t.categories || []).map((c) => `<span class="chip">${esc(c.replace(/_/g, " "))}</span>`).join("");
    const fmts = [(t.input_formats || []).length ? `in: ${t.input_formats.join(", ")}` : "",
      (t.output_formats || []).length ? `out: ${t.output_formats.join(", ")}` : ""].filter(Boolean).join(" · ");
    const body = `${badge}${t.summary ? `<p>${esc(t.summary)}</p>` : ""}${cats}` +
      `${fmts ? `<div class="file-name">${esc(fmts)}</div>` : ""}`;
    h += cardHTML(esc(t.tool), body);
  }
  return h;
}

function stageCardHTML(ev) {
  let body = "";
  if (ev.stage === "onboarding") {
    body = kvTable(ev.facts) + chips(ev.disagreements);
  } else if (ev.stage === "judgment") {
    const cls = ev.action === "run" ? "badge-ok" : "badge-bad";
    body = `<span class="badge ${cls}">${esc(ev.action || "?")}</span><p>${esc(ev.rationale || "")}</p>` +
      chips([...(ev.precondition_failures || []), ...(ev.action === "refuse" ? ev.boundary_hits || [] : [])]);
  } else if (ev.stage === "execution") {
    const cls = ev.ok ? "badge-ok" : "badge-bad";
    body = `<span class="badge ${cls}">exit ${fmt(ev.exit_code)}</span>` +
      (ev.out_dir ? `<div class="file-name">${esc(ev.out_dir)}</div>` : "") +
      (ev.ok ? reportControls(ev.out_name) : "") +
      (ev.error ? `<p class="warn">${esc(ev.error)}</p>` : "") +
      (ev.stderr_tail ? `<pre class="tail">${esc(ev.stderr_tail)}</pre>` : "");
  } else if (ev.stage === "evaluation") {
    const cls = ev.status === "ok" ? "badge-ok" : "badge-warn";
    body = `<span class="badge ${cls}">${esc(ev.status)}</span>` + metricsTable(ev.metrics) + list(ev.findings) +
      (ev.explanation ? `<p class="ok">${esc(ev.explanation)}</p>` : "");
  } else if (ev.stage === "diagnosis") {
    body = `<span class="badge badge-bad">${esc(ev.status)}</span>` + list(ev.findings) +
      (ev.proposed_fix ? `<p><b>Fix:</b> ${esc(ev.proposed_fix)}</p>` : "");
  } else if (ev.stage === "provision") {
    body = ev.installed
      ? `<span class="badge badge-ok">installed</span>` + kvTable({ version: ev.version, binary: ev.binary, via: ev.method })
      : `<span class="badge badge-bad">blocked</span><p class="warn">${esc(ev.reason || "")}</p>`;
  } else if (ev.stage === "docs_check") {
    const miss = ev.missing || [];
    body = miss.length
      ? `<span class="badge badge-warn">missing</span><p>Creating docs: ${esc(miss.join(", "))}</p>` +
        (ev.have && ev.have.length ? `<p class="ok">Already present: ${esc(ev.have.join(", "))}</p>` : "")
      : `<span class="badge badge-ok">complete</span><p class="ok">All section docs already exist.</p>`;
  } else if (ev.stage === "source") {
    body = `<p>${esc(fmt(ev.chars))} chars of --help${ev.url ? " + docs" : ""} captured.</p>`;
  } else if (ev.stage === "curate") {
    const cls = ev.status === "valid" ? "badge-ok" : "badge-warn";
    body = `<span class="badge ${cls}">${esc(ev.status)}</span>` + kvTable({ items: ev.items, fixes: ev.fixes });
  } else if (ev.stage === "persist") {
    body = list([...(ev.sections_written || []), ev.manifest].filter(Boolean));
  } else if (ev.stage === "scaffold") {
    body = list(ev.hrr_files);
  } else if (ev.stage === "hrr_gate") {
    body = `<span class="badge badge-warn">review required</span>
      <p>${esc(fmt(ev.markers))} HRR marker(s) — the tool is documented but the judgment harness
      will refuse to run it until a human reviews its safety contract.</p>`;
  } else {
    body = `<span class="warn">${esc(ev.error || "unknown stage")}</span>`;
  }
  return cardHTML(ev.title || ev.stage, body);
}

// ---- small HTML helpers ----
function cardHTML(title, inner) { return `<div class="card"><h3>${esc(title)}</h3>${inner}</div>`; }
function kvTable(obj) {
  const rows = Object.entries(obj || {})
    .map(([k, v]) => `<tr><td class="k">${esc(k)}</td><td class="v">${esc(fmt(v))}</td></tr>`).join("");
  return rows ? `<table class="facts"><tbody>${rows}</tbody></table>` : "";
}
function metricsTable(metrics) {
  const rows = Object.entries(metrics || {}).map(([k, s]) =>
    `<tr><td class="k">${esc(k)}</td><td class="v">${esc(fmt(s && s.value))}</td>` +
    `<td class="v tier-${esc(s && s.tier)}">${esc(s && s.tier || "")}</td></tr>`).join("");
  return rows ? `<table class="facts"><tbody>${rows}</tbody></table>` : "";
}
function chips(arr) { return (arr || []).map((d) => `<span class="chip">⚠ ${esc(d)}</span>`).join(""); }
function list(arr) { return (arr && arr.length) ? "<ul>" + arr.map((x) => `<li>${esc(x)}</li>`).join("") + "</ul>" : ""; }

// ---- tiny inline-SVG charts (no external lib) ----
function barChart(hist) {
  const W = 460, H = 160, pad = 26;
  const keys = Object.keys(hist).map(Number).sort((a, b) => a - b);
  const maxV = Math.max(...keys.map((k) => hist[k]), 1);
  const bw = (W - 2 * pad) / keys.length;
  let bars = "";
  keys.forEach((k, i) => {
    const bh = (H - 2 * pad) * (hist[k] / maxV);
    bars += `<rect class="bar" x="${pad + i * bw}" y="${H - pad - bh}" width="${Math.max(bw - 1, 1)}" height="${bh}"><title>${k} bp: ${hist[k]}</title></rect>`;
  });
  const xl = `<text x="${pad}" y="${H - 8}">${keys[0]} bp</text><text x="${W - pad}" y="${H - 8}" text-anchor="end">${keys[keys.length - 1]} bp</text>`;
  return `<svg viewBox="0 0 ${W} ${H}"><line class="axis" x1="${pad}" y1="${H - pad}" x2="${W - pad}" y2="${H - pad}"/>${bars}${xl}<text x="${pad}" y="${pad - 10}">max ${maxV}</text></svg>`;
}
function lineChart(series) {
  const W = 460, H = 160, pad = 26;
  const n = series.length, maxY = Math.max(...series, 40);
  const x = (i) => pad + (W - 2 * pad) * (n === 1 ? 0 : i / (n - 1));
  const y = (v) => H - pad - (H - 2 * pad) * (v / maxY);
  const pts = series.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const y30 = y(30);
  return `<svg viewBox="0 0 ${W} ${H}"><line class="axis" x1="${pad}" y1="${H - pad}" x2="${W - pad}" y2="${H - pad}"/>` +
    `<line class="axis" x1="${pad}" y1="${y30}" x2="${W - pad}" y2="${y30}" stroke-dasharray="3 3"/>` +
    `<text x="${W - pad}" y="${y30 - 3}" text-anchor="end">Q30</text><polyline class="line" points="${pts}"/>` +
    `<text x="${pad}" y="${H - 8}">pos 1</text><text x="${W - pad}" y="${H - 8}" text-anchor="end">pos ${n}</text></svg>`;
}

// ---- helpers ----
function fmt(v) { return v === true ? "yes" : v === false ? "no" : (v === null || v === undefined) ? "—" : String(v); }
function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---- sessions: list past sessions, reload one (explore), or start fresh (Part 2) ----
async function populateSessions() {
  let list = [];
  try { list = (await (await fetch("/api/sessions")).json()).sessions || []; } catch (e) { /* offline */ }
  const sel = $("session-select");
  const opts = [`<option value="__new__">＋ new session</option>`];
  if (!list.some((s) => s.sid === sid)) opts.push(`<option value="${sid}">current (unsaved)</option>`);
  for (const s of list) {
    const when = (s.created || "").replace("T", " ").replace("+00:00", "");
    const q = s.last_question ? " · " + esc(s.last_question.slice(0, 28)) : "";
    opts.push(`<option value="${s.sid}">${when} · ${s.n_runs} run${s.n_runs === 1 ? "" : "s"}${q}</option>`);
  }
  sel.innerHTML = opts.join("");
  sel.value = sid;
}

function runsToPanel(runs) {
  return {
    kind: "session", count: runs.length,
    runs: runs.slice().reverse().map((r) => ({
      tool: r.tool, when: (r.ts || "").replace("T", " ").replace("+00:00", " UTC"),
      action: r.action, verdict: r.verdict_status, out_dir: r.out_dir, question: r.question,
    })),
  };
}

// wipe the whole workspace back to a blank slate — used when switching to another session so no
// old chat/tab/report content leaks across sessions.
function resetWorkspace() {
  turns = []; view = -1; stream = -1;
  convo = [];
  $("turn-select").innerHTML = "";
  log.innerHTML = "";
  panel.innerHTML = ""; panel.hidden = true; panelEmpty.hidden = false;
  $("activity").innerHTML = '<div class="act-empty">Activity — what the agent is thinking and doing — appears here.</div>';
  $("terminal").innerHTML = '<span class="act-empty">Raw output from each step appears here.</span>';
  const rf = $("report-frame"); rf.src = "about:blank"; rf.hidden = true;
  const re = $("report-empty"); if (re) re.hidden = false;
  $("act-badge").hidden = true;
  switchTab("output");
}

async function switchSession(target) {
  if (target === "__new__") {
    sid = newSid(); localStorage.setItem("bioSid", sid);
    resetWorkspace();
    addMsg("Started a new session.", "assistant");
    await populateSessions();
    return;
  }
  sid = target; localStorage.setItem("bioSid", sid);
  resetWorkspace();
  const had = await replaySession(sid);               // repaint chat + all tabs from the transcript
  if (!had) {
    // no saved transcript (older/empty session) — fall back to the run-log output panel
    addMsg(`Loaded session ${sid.slice(0, 8)}… (no chat history saved)`, "assistant");
    try {
      const runs = (await (await fetch(`/api/sessions/${sid}/runs`)).json()).runs || [];
      if (runs.length) { startTurn(`session ${sid.slice(0, 8)}`); setOutput(sessionPanelHTML(runsToPanel(runs)), "session"); }
    } catch (e) { /* ignore */ }
  }
  switchTab("output");
  await populateSessions();
}

$("session-select").addEventListener("change", (e) => switchSession(e.target.value));

// ---- data settings: consent flag + local dataset stats (collection is always-on, local) ----
async function refreshDatasetStats() {
  try {
    const s = await (await fetch("/api/dataset/stats")).json();
    $("dataset-count").textContent = `${s.rows} interaction${s.rows === 1 ? "" : "s"} logged locally`;
  } catch (e) { /* ignore */ }
}
async function loadSettings() {
  try {
    const s = await (await fetch("/api/settings")).json();
    $("contribute").checked = !!s.contribute_data;
  } catch (e) { /* ignore */ }
}
$("contribute").addEventListener("change", (e) => {
  fetch("/api/settings", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ contribute_data: e.target.checked }),
  }).catch(() => {});
});
$("settings").addEventListener("toggle", (e) => { if (e.target.open) refreshDatasetStats(); });

// ---- working directory: header label + fetch (data paths resolve against this folder) ----
function setWorkdirLabel(wd) {
  const el = $("workdir"); if (!el || !wd) return;
  el.textContent = "📁 " + wd; el.title = "working directory: " + wd;
}
async function loadWorkdir() {
  try { setWorkdirLabel((await (await fetch("/api/workdir")).json()).workdir); } catch (e) { /* offline */ }
}

// ---- model picker: per-provider model list from /api/models ----
let MODELS = { ollama: [], claude: [], defaults: {} };
async function loadModels() {
  try { MODELS = await (await fetch("/api/models")).json(); } catch (e) { /* offline */ }
  populateModels();
}
function populateModels() {
  const prov = $("provider").value;
  const list = prov === "ollama" ? (MODELS.ollama || []) : prov === "claude" ? (MODELS.claude || []) : [];
  const def = prov === "ollama" && MODELS.defaults ? MODELS.defaults.ollama : "";
  const opts = [`<option value="">default${def ? " (" + esc(def) + ")" : ""}</option>`];
  for (const m of list) opts.push(`<option value="${esc(m)}">${esc(m)}</option>`);
  $("model").innerHTML = opts.join("");
}
$("provider").addEventListener("change", populateModels);

// on load: list sessions, repaint the current one, load settings + stats + workdir + models
(async () => { await populateSessions(); await replaySession(sid); await loadSettings(); await refreshDatasetStats(); await loadWorkdir(); await loadModels(); })();

// ---- tabs (Output / Activity / Terminal) ----
let currentTab = "output";
function switchTab(name) {
  currentTab = name;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $("tab-output").hidden = name !== "output";
  $("tab-activity").hidden = name !== "activity";
  $("tab-terminal").hidden = name !== "terminal";
  $("tab-report").hidden = name !== "report";
  if (name === "activity") $("act-badge").hidden = true;
}
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));

// ---- reports: view a run's HTML output in the Report tab (or open it in a new browser tab) ----
function reportUrl(outName) {
  return `/api/sessions/${encodeURIComponent(sid)}/report?run=${encodeURIComponent(outName)}`;
}
function reportControls(outName) {
  if (!outName) return "";
  return `<div class="report-ctl"><button class="rpt-btn" data-run="${esc(outName)}">View report</button>` +
    ` <a class="rpt-link" href="${reportUrl(outName)}" target="_blank" rel="noopener">open in new tab ↗</a></div>`;
}
function viewReport(outName) {
  const f = $("report-frame"), e = $("report-empty");
  f.src = reportUrl(outName); f.hidden = false; if (e) e.hidden = true;
  switchTab("report");
}
// delegated: report buttons live inside dynamically-rebuilt panel HTML
$("panel").addEventListener("click", (ev) => {
  const b = ev.target.closest(".rpt-btn");
  if (b && b.dataset.run) viewReport(b.dataset.run);
});

// ---- navigation: ⌘↑/⌘↓ = question history, ⌘←/⌘→ = Output/Activity/Terminal/Report tabs ----
const TAB_ORDER = ["output", "activity", "terminal", "report"];
function cycleTab(dir) {
  const i = Math.max(0, Math.min(TAB_ORDER.length - 1, TAB_ORDER.indexOf(currentTab) + dir));
  switchTab(TAB_ORDER[i]);
}
$("turn-select").addEventListener("change", (e) => showTurn(parseInt(e.target.value, 10)));
document.addEventListener("keydown", (e) => {
  if (!(e.metaKey || e.ctrlKey)) return;
  if (e.key === "ArrowUp") { e.preventDefault(); showTurn(view - 1); }
  else if (e.key === "ArrowDown") { e.preventDefault(); showTurn(view + 1); }
  else if (e.key === "ArrowLeft") { e.preventDefault(); cycleTab(-1); }
  else if (e.key === "ArrowRight") { e.preventDefault(); cycleTab(1); }
});

// ---- input history (plain up/down arrows), like the kgx chat ----
let inputHistory = [];
let inputHistIdx = -1;
$("message").addEventListener("keydown", (e) => {
  if (e.metaKey || e.ctrlKey) return;         // ⌘↑/⌘↓ are for turn navigation
  const el = e.target;
  if (e.key === "ArrowUp" && inputHistory.length > 0) {
    e.preventDefault();
    if (inputHistIdx === -1) inputHistIdx = inputHistory.length;
    if (inputHistIdx > 0) { inputHistIdx--; el.value = inputHistory[inputHistIdx]; }
  } else if (e.key === "ArrowDown" && inputHistIdx >= 0) {
    e.preventDefault();
    inputHistIdx++;
    if (inputHistIdx >= inputHistory.length) { inputHistIdx = -1; el.value = ""; }
    else { el.value = inputHistory[inputHistIdx]; }
  }
});

// ---- wire up (Send doubles as Stop while a request is in flight) ----
let inFlight = false;
let abortCtrl = null;
function setStopMode(on) {
  const b = $("send");
  b.textContent = on ? "Stop" : "Send";
  b.classList.toggle("stop", on);
}
$("composer").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (inFlight) { if (abortCtrl) abortCtrl.abort(); return; }   // button is "Stop"
  const msg = $("message").value.trim();
  if (!msg) return;
  const provider = $("provider").value;
  const model = $("model").value;
  inputHistory.push(msg);
  inputHistIdx = -1;
  addMsg(msg, "user");
  startTurn(msg);
  addActivity("▸ " + msg, "turn");
  $("message").value = "";
  const history = convo.slice(-6);
  convo.push({ role: "user", content: msg });
  inFlight = true; setStopMode(true);
  abortCtrl = new AbortController();
  try { await send(msg, null, provider, abortCtrl.signal, history, model); }
  catch (err) {
    if (err.name === "AbortError") { addActivity("stopped by user", "err"); }
    else { addMsg("Error: " + err.message, "assistant", "warn"); addActivity("error: " + err.message, "err"); }
  }
  finally {
    inFlight = false; setStopMode(false); abortCtrl = null; $("message").focus();
    populateSessions();          // pick up a newly-recorded run / the now-saved session
  }
});
