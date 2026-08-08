"use strict";

const $ = (id) => document.getElementById(id);
const log = $("log");
const panel = $("panel");
const panelEmpty = $("panel-empty");

function addMsg(text, who, cls) {
  const div = document.createElement("div");
  div.className = "msg " + who + (cls ? " " + cls : "");
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
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

async function send(message, file, provider, signal) {
  const resp = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, file: file || null, provider }),
    signal,
  });
  if (!resp.ok) { addMsg("Server error: " + resp.status, "assistant", "warn"); return; }

  const thinking = addMsg("…", "assistant", "thinking");
  startWork();
  let planSteps = null;
  try {
    for await (const { event, data } of sse(resp)) {
      if (event === "meta") {
        const m = JSON.parse(data);
        addActivity(`intent: ${m.intent} · model: ${m.provider}`, "meta");
        term(`[meta] intent=${m.intent} model=${m.provider}`);
      } else if (event === "plan") {
        planSteps = JSON.parse(data).steps;
        setProgressTotal(planSteps.length);
      } else if (event === "log") {
        const t = JSON.parse(data).text;
        addActivity(t, "think"); setThinking(thinking, t); term("… " + t);
      } else if (event === "panel") {
        renderPanel(JSON.parse(data));
        addActivity("data profile ready", "ok");
      } else if (event === "stage") {
        const ev = JSON.parse(data);
        renderStage(ev);
        addActivity(stageLine(ev), "stage");
        setThinking(thinking, stageLine(ev));
        advanceProgress(ev, planSteps);
        termStage(ev);
      } else if (event === "prose") {
        const t = JSON.parse(data).text;
        thinking.classList.remove("thinking");
        thinking.textContent = t;
        log.scrollTop = log.scrollHeight;
        term("[response] " + t);
      } else if (event === "done") {
        addActivity("done", "done");
      }
    }
  } catch (e) {
    if (e.name === "AbortError") {
      thinking.classList.remove("thinking");
      thinking.textContent = "⏹ Stopped. (the server may finish this step in the background)";
    }
    throw e;
  } finally {
    endWork();
  }
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
function setProgressTotal(n) {
  const p = $("progress");
  p.classList.remove("indeterminate");
  p.dataset.total = String(n);
}
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

// ---- terminal tab: raw output ----
function term(line) {
  const t = $("terminal");
  const empty = t.querySelector(".act-empty");
  if (empty) empty.remove();
  t.appendChild(document.createTextNode(line + "\n"));
  t.scrollTop = t.scrollHeight;
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

// ---- right-hand data panel ----
function renderPanel(p) {
  panelEmpty.hidden = true;
  panel.hidden = false;
  panel.innerHTML = "";
  panel.dataset.mode = "profile";

  if (p.kind === "tool") { renderToolPanel(p); return; }

  const h = document.createElement("div");
  h.innerHTML = `<h2>Data profile</h2><div class="file-name">${esc(p.file || "")}</div>`;
  panel.appendChild(h);

  if (p.error) {
    panel.appendChild(card("Error", `<span class="warn">${esc(p.error)}</span>`));
    return;
  }

  // facts table
  const rows = (p.facts || []).map(
    (r) => `<tr><td class="k">${esc(r.label)}</td><td class="v">${esc(fmt(r.value))}</td></tr>`
  ).join("");
  panel.appendChild(card("Measured facts", `<table class="facts"><tbody>${rows}</tbody></table>`));

  // disagreements (declared vs measured)
  if (p.disagreements && p.disagreements.length) {
    const chips = p.disagreements.map((d) => `<span class="chip">⚠ ${esc(d)}</span>`).join("");
    panel.appendChild(card("Needs a double-check", chips));
  } else if (p.declared && Object.keys(p.declared).length) {
    panel.appendChild(card("Declared vs measured",
      `<span class="ok">No conflicts between what you stated and what was measured.</span>`));
  }

  // plots
  if (p.length_hist && Object.keys(p.length_hist).length) {
    panel.appendChild(card("Read-length distribution", barChart(p.length_hist)));
  }
  if (p.qual_by_pos && p.qual_by_pos.length) {
    panel.appendChild(card("Mean quality by position", lineChart(p.qual_by_pos)));
  }
}

// ---- tool documentation panel (explain_tool / RAG) ----
function renderToolPanel(p) {
  const head = document.createElement("div");
  const rev = p.reviewed ? "" : ` · <span class="warn">contract pending review</span>`;
  head.innerHTML = `<h2>${esc(p.tool)}${p.version ? " " + esc(p.version) : ""}</h2>
    <div class="file-name">documented tool${rev}</div>`;
  panel.appendChild(head);

  if (p.summary) panel.appendChild(card("Summary", `<p>${esc(p.summary)}</p>`));

  if (p.usage && p.usage.length) {
    const rows = p.usage.map((e) =>
      `<div class="usage-ex"><div class="ux-desc">${esc(e.description || "")}</div>` +
      `<code>${esc(e.command || "")}</code></div>`).join("");
    panel.appendChild(card("Usage", rows));
  }
  if (p.options && p.options.length) {
    const rows = p.options.map((o) =>
      `<tr><td class="k">${esc(o.flag)}</td><td class="v">${esc(o.description || "")}` +
      `${o.default ? ` <span class="muted">(default ${esc(o.default)})</span>` : ""}</td></tr>`).join("");
    panel.appendChild(card(`Parameters (${p.options.length})`, `<table class="facts"><tbody>${rows}</tbody></table>`));
  }
  if (p.boundaries && p.boundaries.length) {
    panel.appendChild(card("Off-label boundaries", list(p.boundaries)));
  }
  if (p.citation) panel.appendChild(card("Citation", `<code>${esc(p.citation)}</code>`));
}

// ---- pipeline stage timeline (run_pipeline) ----
function renderStage(ev) {
  panelEmpty.hidden = true;
  panel.hidden = false;
  if (panel.dataset.mode !== "pipeline") {          // first stage of a run -> reset
    panel.innerHTML = `<h2>Pipeline run</h2><div class="file-name">four-harness flow</div>
      <div id="stages"></div>`;
    panel.dataset.mode = "pipeline";
  }
  document.getElementById("stages").appendChild(stageCard(ev));
}

function stageCard(ev) {
  let body = "";
  if (ev.stage === "onboarding") {
    body = kvTable(ev.facts) + chips(ev.disagreements);
  } else if (ev.stage === "judgment") {
    const cls = ev.action === "run" ? "badge-ok" : "badge-bad";
    body = `<span class="badge ${cls}">${esc(ev.action || "?")}</span>
      <p>${esc(ev.rationale || "")}</p>` +
      chips([...(ev.precondition_failures || []), ...(ev.action === "refuse" ? ev.boundary_hits || [] : [])]);
  } else if (ev.stage === "execution") {
    const cls = ev.ok ? "badge-ok" : "badge-bad";
    body = `<span class="badge ${cls}">exit ${fmt(ev.exit_code)}</span>` +
      (ev.out_dir ? `<div class="file-name">${esc(ev.out_dir)}</div>` : "") +
      (ev.error ? `<p class="warn">${esc(ev.error)}</p>` : "") +
      (ev.stderr_tail ? `<pre class="tail">${esc(ev.stderr_tail)}</pre>` : "");
  } else if (ev.stage === "evaluation") {
    const cls = ev.status === "ok" ? "badge-ok" : "badge-warn";
    body = `<span class="badge ${cls}">${esc(ev.status)}</span>` +
      metricsTable(ev.metrics) + list(ev.findings) +
      (ev.explanation ? `<p class="ok">${esc(ev.explanation)}</p>` : "");
  } else if (ev.stage === "diagnosis") {
    body = `<span class="badge badge-bad">${esc(ev.status)}</span>` + list(ev.findings) +
      (ev.proposed_fix ? `<p><b>Fix:</b> ${esc(ev.proposed_fix)}</p>` : "");
  } else if (ev.stage === "provision") {
    if (ev.installed) {
      body = `<span class="badge badge-ok">installed</span>` +
        kvTable({ version: ev.version, binary: ev.binary, via: ev.method });
    } else {
      body = `<span class="badge badge-bad">blocked</span><p class="warn">${esc(ev.reason || "")}</p>`;
    }
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
    body = `<span class="badge ${cls}">${esc(ev.status)}</span>` +
      kvTable({ items: ev.items, fixes: ev.fixes });
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
  return card(ev.title || ev.stage, body);
}

function kvTable(obj) {
  const rows = Object.entries(obj || {})
    .map(([k, v]) => `<tr><td class="k">${esc(k)}</td><td class="v">${esc(fmt(v))}</td></tr>`).join("");
  return rows ? `<table class="facts"><tbody>${rows}</tbody></table>` : "";
}
function metricsTable(metrics) {
  const rows = Object.entries(metrics || {}).map(([k, s]) =>
    `<tr><td class="k">${esc(k)}</td><td class="v">${esc(fmt(s && s.value))}</td>
     <td class="v tier-${esc(s && s.tier)}">${esc(s && s.tier || "")}</td></tr>`).join("");
  return rows ? `<table class="facts"><tbody>${rows}</tbody></table>` : "";
}
function chips(arr) {
  return (arr || []).map((d) => `<span class="chip">⚠ ${esc(d)}</span>`).join("");
}
function list(arr) {
  return (arr && arr.length) ? "<ul>" + arr.map((x) => `<li>${esc(x)}</li>`).join("") + "</ul>" : "";
}

function card(title, innerHTML) {
  const c = document.createElement("div");
  c.className = "card";
  c.innerHTML = `<h3>${esc(title)}</h3>${innerHTML}`;
  return c;
}

// ---- tiny inline-SVG charts (no external lib) ----
function barChart(hist) {
  const W = 460, H = 160, pad = 26;
  const keys = Object.keys(hist).map(Number).sort((a, b) => a - b);
  const vals = keys.map((k) => hist[k]);
  const maxV = Math.max(...vals, 1);
  const bw = (W - 2 * pad) / keys.length;
  let bars = "";
  keys.forEach((k, i) => {
    const bh = (H - 2 * pad) * (hist[k] / maxV);
    const x = pad + i * bw;
    const y = H - pad - bh;
    bars += `<rect class="bar" x="${x}" y="${y}" width="${Math.max(bw - 1, 1)}" height="${bh}"><title>${k} bp: ${hist[k]}</title></rect>`;
  });
  const xlabels = `<text x="${pad}" y="${H - 8}">${keys[0]} bp</text>` +
    `<text x="${W - pad}" y="${H - 8}" text-anchor="end">${keys[keys.length - 1]} bp</text>`;
  return `<svg viewBox="0 0 ${W} ${H}">
    <line class="axis" x1="${pad}" y1="${H - pad}" x2="${W - pad}" y2="${H - pad}"/>
    ${bars}${xlabels}
    <text x="${pad}" y="${pad - 10}">max ${maxV}</text></svg>`;
}

function lineChart(series) {
  const W = 460, H = 160, pad = 26;
  const n = series.length;
  const maxY = Math.max(...series, 40);
  const x = (i) => pad + (W - 2 * pad) * (n === 1 ? 0 : i / (n - 1));
  const y = (v) => H - pad - (H - 2 * pad) * (v / maxY);
  const pts = series.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  // Phred 30 reference line
  const y30 = y(30);
  return `<svg viewBox="0 0 ${W} ${H}">
    <line class="axis" x1="${pad}" y1="${H - pad}" x2="${W - pad}" y2="${H - pad}"/>
    <line class="axis" x1="${pad}" y1="${y30}" x2="${W - pad}" y2="${y30}" stroke-dasharray="3 3"/>
    <text x="${W - pad}" y="${y30 - 3}" text-anchor="end">Q30</text>
    <polyline class="line" points="${pts}"/>
    <text x="${pad}" y="${H - 8}">pos 1</text>
    <text x="${W - pad}" y="${H - 8}" text-anchor="end">pos ${n}</text></svg>`;
}

// ---- helpers ----
function fmt(v) {
  if (v === true) return "yes";
  if (v === false) return "no";
  if (v === null || v === undefined) return "—";
  return String(v);
}
function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---- activity feed (right-panel "Activity" tab) ----
function addActivity(text, kind) {
  const feed = $("activity");
  const empty = feed.querySelector(".act-empty");
  if (empty) empty.remove();
  const ts = new Date().toLocaleTimeString([], { hour12: false });
  const line = document.createElement("div");
  line.className = "act-line act-" + (kind || "info");
  line.innerHTML = `<span class="ts">${ts}</span><span class="act-text">${esc(text)}</span>`;
  feed.appendChild(line);
  feed.scrollTop = feed.scrollHeight;
  if (currentTab !== "activity") { $("act-badge").hidden = false; }   // nudge when not looking
}

// ---- tabs ----
let currentTab = "output";
function switchTab(name) {
  currentTab = name;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $("tab-output").hidden = name !== "output";
  $("tab-activity").hidden = name !== "activity";
  $("tab-terminal").hidden = name !== "terminal";
  if (name === "activity") $("act-badge").hidden = true;
}
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));

// ---- input history (up/down arrows), like the kgx chat ----
let inputHistory = [];
let inputHistIdx = -1;
$("message").addEventListener("keydown", (e) => {
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
  const file = $("file").value.trim();
  const provider = $("provider").value;
  inputHistory.push(msg);
  inputHistIdx = -1;
  addMsg(msg, "user");
  addActivity("▸ " + msg, "turn");
  $("message").value = "";
  inFlight = true; setStopMode(true);
  abortCtrl = new AbortController();
  try { await send(msg, file, provider, abortCtrl.signal); }
  catch (err) {
    if (err.name === "AbortError") { addActivity("stopped by user", "err"); }
    else { addMsg("Error: " + err.message, "assistant", "warn"); addActivity("error: " + err.message, "err"); }
  }
  finally { inFlight = false; setStopMode(false); abortCtrl = null; $("message").focus(); }
});
