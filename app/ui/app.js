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

async function send(message, file, provider) {
  const resp = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, file: file || null, provider }),
  });
  if (!resp.ok) { addMsg("Server error: " + resp.status, "assistant", "warn"); return; }

  const thinking = addMsg("…", "assistant", "thinking");
  for await (const { event, data } of sse(resp)) {
    if (event === "panel") {
      renderPanel(JSON.parse(data));
    } else if (event === "stage") {
      renderStage(JSON.parse(data));
    } else if (event === "prose") {
      thinking.classList.remove("thinking");
      thinking.textContent = JSON.parse(data).text;
      log.scrollTop = log.scrollHeight;
    }
  }
}

// ---- right-hand data panel ----
function renderPanel(p) {
  panelEmpty.hidden = true;
  panel.hidden = false;
  panel.innerHTML = "";
  panel.dataset.mode = "profile";

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

// ---- wire up ----
$("composer").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = $("message").value.trim();
  if (!msg) return;
  const file = $("file").value.trim();
  const provider = $("provider").value;
  addMsg(msg, "user");
  $("message").value = "";
  $("send").disabled = true;
  try { await send(msg, file, provider); }
  catch (err) { addMsg("Error: " + err.message, "assistant", "warn"); }
  finally { $("send").disabled = false; $("message").focus(); }
});
