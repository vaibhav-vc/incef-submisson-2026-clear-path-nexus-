"use strict";
const FACTORS = ["delay", "conflict", "infra", "energy", "threat", "evidence", "complexity"];
const PRESETS = ["FASTEST", "INFRA_PROTECT", "LOWEST_RISK", "BALANCED"];
let net = null, positions = [], selected = null, planCoords = null, latest = null;
let liveStream = false;      // true while the server pushes positions and threats (national_plus.js)
const overlays = [];         // extra map layers drawn after the network (national_plus.js)
const view = {lon: 82.8, lat: 22.5, scale: 26};  // pixels per degree
const canvas = document.getElementById("map");
const ctx = canvas.getContext("2d");

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "style") node.style.cssText = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) node.append(c instanceof Node ? c : document.createTextNode(String(c ?? "")));
  return node;
}
function headers() {
  const h = {"Content-Type": "application/json"};
  const token = (typeof sessionToken === "string" && sessionToken) || document.getElementById("token").value;
  if (token) h.Authorization = "Bearer " + token;
  return h;
}
async function api(path, body) {
  const init = body === undefined ? {headers: headers()} : {method: "POST", headers: headers(), body: JSON.stringify(body)};
  const absolute = /^\/(railguard|auth|health)\//.test(path);
  const res = await fetch(absolute ? path : "/railguard/national" + path, init);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || res.statusText));
  return data;
}
function badge(text, cls) { return el("span", {class: `badge s-${cls || text}`}, text); }
function who() { return document.getElementById("controllerName").value.trim() || "controller"; }  // ignored by the server for a signed-in person
function showError(e) { document.getElementById("err").textContent = e ? e.message : ""; }
async function act(fn) { showError(null); try { await fn(); } catch (e) { showError(e); } await refresh(); }

// ---- map ---------------------------------------------------------------------------------------
function project(lon, lat) {
  return [canvas.width / 2 + (lon - view.lon) * view.scale, canvas.height / 2 - (lat - view.lat) * view.scale];
}
function draw() {
  if (!net) return;
  ctx.fillStyle = "#0b1015";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  for (const multi of [false, true]) {
    ctx.beginPath();
    for (const [a, b, tracks] of net.sections) {
      if ((tracks > 1) !== multi) continue;
      const pa = net.nodes[a], pb = net.nodes[b];
      if (!pa || !pb) continue;
      const [x1, y1] = project(pa[0], pa[1]), [x2, y2] = project(pb[0], pb[1]);
      ctx.moveTo(x1, y1); ctx.lineTo(x2, y2);
    }
    ctx.strokeStyle = multi ? "#3d5a73" : "#2a3540";
    ctx.lineWidth = multi ? 1.6 : 0.8;
    ctx.stroke();
  }
  if (planCoords && planCoords.length) {
    ctx.beginPath();
    planCoords.forEach(([lon, lat], i) => { const [x, y] = project(lon, lat); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.strokeStyle = "#58a6ff"; ctx.lineWidth = 3.5; ctx.stroke();
  }
  for (const [key, lon, lat, priority, changed] of positions) {
    const [x, y] = project(lon, lat);
    if (x < -5 || y < -5 || x > canvas.width + 5 || y > canvas.height + 5) continue;
    ctx.fillStyle = key === selected ? "#ffffff" : changed ? "#f0883e" : priority <= 1 ? "#f85149" : "#3fb950";
    const r = key === selected ? 5 : changed ? 3.5 : 1.8;
    ctx.fillRect(x - r / 2, y - r / 2, r, r);
  }
}
const drawNetwork = draw;
draw = function () { drawNetwork(); if (net) for (const layer of overlays) layer(); };  // eslint-disable-line no-func-assign
function fit(coords) {
  if (!coords || !coords.length) return;
  const lons = coords.map(c => c[0]), lats = coords.map(c => c[1]);
  const [minLon, maxLon, minLat, maxLat] = [Math.min(...lons), Math.max(...lons), Math.min(...lats), Math.max(...lats)];
  view.lon = (minLon + maxLon) / 2; view.lat = (minLat + maxLat) / 2;
  view.scale = Math.min(400, 0.85 * canvas.width / Math.max(maxLon - minLon, maxLat - minLat, 0.2));
  draw();
}
canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  view.scale = Math.min(2000, Math.max(10, view.scale * (e.deltaY < 0 ? 1.25 : 0.8)));
  draw();
}, {passive: false});
let drag = null;
canvas.addEventListener("pointerdown", (e) => { drag = {x: e.clientX, y: e.clientY}; canvas.setPointerCapture(e.pointerId); });
canvas.addEventListener("pointermove", (e) => {
  if (!drag) return;
  const k = canvas.width / canvas.getBoundingClientRect().width;
  view.lon -= (e.clientX - drag.x) * k / view.scale; view.lat += (e.clientY - drag.y) * k / view.scale;
  drag = {x: e.clientX, y: e.clientY}; draw();
});
canvas.addEventListener("pointerup", () => { drag = null; });

// ---- panels ---------------------------------------------------------------------------------------
async function findTrain() {
  const number = document.getElementById("number").value.trim().toUpperCase();
  if (!/^[A-Z0-9]{1,10}$/.test(number)) { showError(new Error("Enter a train number")); return; }
  const runs = await api(`/runs/${number}`);
  const box = document.getElementById("runs");
  box.replaceChildren(...(runs.length ? runs.map(r => el("div", {class: "runitem" + (r.run === selected ? " sel" : ""),
    onclick: () => selectRun(r)}, el("b", {}, r.run), ` ${r.name} (${r.type}) — ${r.state}`)) : [el("div", {class: "muted"}, "No runs in the twin window.")]));
}
async function selectRun(r) {
  selected = r.run;
  document.getElementById("selRun").textContent = r.run;
  const station = document.getElementById("station");
  station.replaceChildren(...r.next_departures.map(d => el("option", {value: d.station}, `${d.station} (${d.time})`)));
  document.getElementById("cabLink").href = `/cab?run=${encodeURIComponent(r.run)}`;
  document.getElementById("cabIssued").hidden = true;  // a link issued for the previous train
  planCoords = (await api(`/plan/${encodeURIComponent(r.run)}`)).coords;
  fit(planCoords);
  await findTrain();
}
function drawCandidates() {
  const box = document.getElementById("candidates");
  box.replaceChildren();
  if (!latest) return;
  const st = document.getElementById("recState");
  st.textContent = latest.state; st.className = `badge s-${latest.state === "PLANNING_ONLY" ? "INFO" : latest.state}`;
  document.getElementById("recReason").textContent = latest.reason;
  document.getElementById("snapshot").textContent = `Snapshot ${latest.snapshot_id} · checksum ${latest.checksum.slice(0, 16)}… · preset ${latest.preset}`;
  const ranking = latest.ranking;
  if (!ranking.candidates || !ranking.candidates.length) {
    box.append(el("div", {class: "muted"}, "No feasible alternative."),
      ...(ranking.rejected || []).slice(0, 5).map(r => el("div", {class: "muted"}, `✗ ${r.label}: ${r.reasons.join("; ")}`)));
    return;
  }
  box.append(el("div", {class: "muted"}, `${ranking.feasible_count} feasible · ${(ranking.rejected || []).length} rejected · headway ${ranking.headway_min} min`));
  ranking.candidates.forEach((c, i) => {
    const bars = el("div", {class: "bars"});
    for (const f of FACTORS) bars.append(el("span", {}, f), el("div", {class: "bar"}, el("span", {style: `width:${Math.round(c.factors[f] * 100)}%`})),
      el("span", {class: "muted"}, `+${c.contributions[f].toFixed(2)}`));
    const approve = el("button", {class: "primary", onclick: () => act(() => api("/approve", {snapshot_id: latest.snapshot_id, candidate_id: c.candidate_id, controller: who()}))},
      latest.state === "PLANNING_ONLY" ? "APPROVE (REHEARSAL)" : "APPROVE FOR DEMO");
    if (!latest.approvable) { approve.disabled = true; approve.title = `Not approvable: ${latest.state}`; }
    box.append(el("div", {class: "card" + (i === 0 ? " top" : "")},
      el("div", {class: "row"}, el("b", {}, c.candidate_id), ...c.labels.map(l => badge(l, "INFO")), el("span", {class: "grow"}), el("b", {}, `score ${c.score.toFixed(3)}`)),
      el("div", {}, c.summary),
      el("div", {class: "muted"}, `train arrives +${c.final_delay_min} min · weighted delay incl. other trains ${c.raw.delay} min · stress ${c.raw.infra}`),
      bars, el("div", {class: "muted"}, c.why_lost.length ? "Lost on: " + c.why_lost.map(l => `${l.factor} (+${l.extra})`).join(", ") : "Winner"),
      el("div", {class: "row"}, approve)));
  });
}
function renderThreats(threats) {
  const body = document.getElementById("threats");
  body.replaceChildren(...(threats.length ? threats.slice(0, 40).map(t => el("tr", {},
    el("td", {}, t.id), el("td", {}, t.type), el("td", {}, badge(t.severity)), el("td", {}, t.train_ids.join(", ")),
    el("td", {class: "muted"}, t.detail + (t.reopened ? ` (back ${t.reopened}x)` : "")),
    el("td", {}, t.absent_since_t !== null && t.absent_since_t !== undefined ? el("span", {class: "muted"}, "clearing") :
      t.lifecycle === "OPEN" ? el("button", {onclick: () => act(() => api(`/threats/${t.id}/ack`, {by: who()}))}, "Ack") : t.lifecycle))) :
    [el("tr", {}, el("td", {colspan: 6, class: "muted"}, "No active threats."))]));
}
async function refresh() {
  try {
    const s = await api("/summary");
    latest = s.latest || latest;
    document.getElementById("clock").textContent = s.clock;
    document.getElementById("running").textContent = `${s.running} running · ${s.changed_runs} re-planned`;
    const chain = document.getElementById("chainBadge");
    chain.textContent = s.audit_chain_ok ? "audit chain OK" : "AUDIT CHAIN BROKEN";
    chain.className = `badge s-${s.audit_chain_ok ? "OK" : "BAD"}`;
    document.getElementById("netStats").textContent = `${s.stats.stations} stations · ${s.stats.junctions} junctions · ${s.stats.sections} sections · ${s.stats.runs_in_window} train runs`;
    document.getElementById("quality").replaceChildren(...Object.entries(s.stats).map(([k, v]) => el("tr", {}, el("td", {}, k.replaceAll("_", " ")), el("td", {}, v))));
    renderThreats(s.threats);
    if (!liveStream) positions = await api("/positions");
    if (selected) planCoords = (await api(`/plan/${encodeURIComponent(selected)}`)).coords;
    draw(); drawCandidates();
  } catch (e) { showError(e); }
}
async function init() {
  const presets = document.getElementById("presets");
  presets.append(el("span", {class: "muted"}, "Preset:"), ...PRESETS.map(p => el("button", {onclick: () => act(async () => { latest = await api("/recommend", {preset: p, run: selected}); })}, p.replace("_", " "))));
  document.getElementById("find").onclick = () => act(findTrain);
  document.getElementById("number").addEventListener("keydown", (e) => { if (e.key === "Enter") act(findTrain); });
  document.getElementById("disrupt").onclick = () => act(async () => {
    if (!selected) throw new Error("Select a train run first");
    await api("/disrupt", {run: selected, station: document.getElementById("station").value, delay_min: Number(document.getElementById("delay").value)});
  });
  document.getElementById("recommend").onclick = () => act(async () => { latest = await api("/recommend", {run: selected}); });
  document.getElementById("replay").onclick = () => latest && act(async () => {
    const r = await api(`/audit/${latest.snapshot_id}/replay`);
    alert(`Replay ${r.snapshot_id}\nIntegrity: ${r.integrity_ok ? "OK" : "FAILED"}\nSame data: ${r.data_matches ? "YES" : "NO"}\nRanking reproduced: ${r.replay_matches ? "YES" : "NO"}\n\n${r.note}`);
  });
  document.querySelectorAll("[data-tick]").forEach(b => b.onclick = () => act(() => api("/tick", {minutes: Number(b.dataset.tick)})));
  document.getElementById("reset").onclick = () => act(async () => { latest = null; await api("/reset", {}); });
  document.querySelectorAll("[data-section]").forEach(b => b.onclick = () => act(() => api("/section", {section_id: document.getElementById("section").value.trim().toUpperCase(), ...JSON.parse(b.dataset.section)})));
  document.getElementById("zoomRun").onclick = () => fit(planCoords);
  document.getElementById("zoomAll").onclick = () => { view.lon = 82.8; view.lat = 22.5; view.scale = 26; draw(); };
  try { document.getElementById("token").value = sessionStorage.getItem("rgToken") || ""; } catch (_) { /* storage blocked */ }
  document.getElementById("token").addEventListener("change", (e) => { try { sessionStorage.setItem("rgToken", e.target.value); } catch (_) { /* ignore */ } });
  try { net = await api("/network"); } catch (e) { showError(e); }
  await refresh();
  setInterval(refresh, 4000);
}
init();
