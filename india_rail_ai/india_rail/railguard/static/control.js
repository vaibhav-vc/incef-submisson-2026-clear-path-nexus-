"use strict";
const FACTORS = ["delay", "conflict", "infra", "energy", "threat", "evidence", "complexity"];
const PRESETS = ["FASTEST", "INFRA_PROTECT", "LOWEST_RISK", "BALANCED"];
let state = null, latest = null, playing = null;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "style") node.style.cssText = v;  // CSSOM: allowed under the strict CSP
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) node.append(c instanceof Node ? c : document.createTextNode(String(c ?? "")));
  return node;
}
function svg(tag, attrs = {}, text) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  return node;
}
function headers() {
  const h = {"Content-Type": "application/json"};
  const token = document.getElementById("token").value;
  if (token) h["Authorization"] = "Bearer " + token;
  return h;
}
async function api(path, body) {
  const res = await fetch("/railguard" + path, body === undefined ? {headers: headers()} : {method: "POST", headers: headers(), body: JSON.stringify(body)});
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : res.statusText);
  return data;
}
function fmtClock(t) { const m = Math.floor(t / 60), s = t % 60; return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`; }
function badge(text, cls) { return el("span", {class: `badge s-${cls || text}`}, text); }
function condColour(c) { return c < 0.5 ? "#f85149" : c < 0.75 ? "#d29922" : "#3fb950"; }

function trainXY(train, net) {
  if (!train.section_id) { const n = net.nodes[train.from_node]; return [n.x, n.y]; }
  const s = net.sections[train.section_id];
  const from = net.nodes[train.from_node], to = net.nodes[train.from_node === s.a ? s.b : s.a];
  const f = Math.min(Math.max(train.offset_km / s.length_km, 0), 1);
  return [from.x + (to.x - from.x) * f, from.y + (to.y - from.y) * f];
}

function drawMap() {
  const map = document.getElementById("map");
  map.replaceChildren();
  const net = state.network;
  const proposal = latest && latest.ranking && latest.ranking.candidates && latest.ranking.candidates[0];
  for (const [id, s] of Object.entries(net.sections)) {
    const a = net.nodes[s.a], b = net.nodes[s.b];
    const colour = s.available ? condColour(s.condition) : "#6e7681";
    if (s.tracks === 2) {
      const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy), ox = -dy / len * 3, oy = dx / len * 3;
      map.append(svg("line", {x1: a.x + ox, y1: a.y + oy, x2: b.x + ox, y2: b.y + oy, stroke: colour, "stroke-width": 3}));
      map.append(svg("line", {x1: a.x - ox, y1: a.y - oy, x2: b.x - ox, y2: b.y - oy, stroke: colour, "stroke-width": 3}));
    } else {
      map.append(svg("line", {x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: colour, "stroke-width": 4}));
    }
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    let label = `${id} ${s.length_km}km${s.tracks === 1 ? " single" : ""}`;
    if (s.asset) label += ` ${s.asset}`;
    map.append(svg("text", {x: mx + 6, y: my - 8, fill: "#8b98a5", "font-size": 11}, label));
    const marks = [];
    if (s.temp_restriction_kmph) marks.push(`${s.temp_restriction_kmph} km/h`);
    if (s.weather_alert) marks.push(s.weather_alert);
    if (s.obstacle) marks.push("OBSTACLE");
    if (marks.length) map.append(svg("text", {x: mx + 6, y: my + 16, fill: "#f0883e", "font-size": 11, "font-weight": 700}, marks.join(" · ")));
  }
  const overlay = (route, _startNode, colour, dashed) => {
    for (const sid of route) {
      const s = net.sections[sid], a = net.nodes[s.a], b = net.nodes[s.b];
      map.append(svg("line", {x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: colour, "stroke-width": 9, opacity: 0.35,
        "stroke-dasharray": dashed ? "10 8" : "none", "stroke-linecap": "round"}));
    }
  };
  if (proposal) for (const [tid, p] of Object.entries(proposal.train_plans)) overlay(p.traversals.map(t => t.section_id), p.start_node, tid === "A" ? "#58a6ff" : "#d2a8ff", true);
  for (const [tid, t] of Object.entries(state.trains)) {
    if (t.approved_route && t.approved_route.length && !t.finished) overlay(t.approved_route, null, tid === "A" ? "#58a6ff" : "#d2a8ff", false);
  }
  for (const [name, n] of Object.entries(net.nodes)) {
    map.append(svg("circle", {cx: n.x, cy: n.y, r: 7, fill: "#0b1015", stroke: "#8b98a5", "stroke-width": 2}));
    map.append(svg("text", {x: n.x - 8, y: n.y + 24, fill: "#e6edf3", "font-size": 12, "font-weight": 600}, name));
  }
  for (const [tid, t] of Object.entries(state.trains)) {
    const [x, y] = trainXY(t, net);
    const colour = tid === "A" ? "#58a6ff" : "#d2a8ff";
    const stale = t.position_evidence !== "FRESH" && t.position_evidence !== "AGING";
    map.append(svg("circle", {cx: x, cy: y - 14, r: 12, fill: stale ? "#3c1618" : colour, stroke: stale ? "#f85149" : "#0b1015",
      "stroke-width": 3, "stroke-dasharray": stale ? "3 3" : "none"}));
    map.append(svg("text", {x: x - 5, y: y - 10, fill: "#0b1015", "font-size": 12, "font-weight": 800}, tid));
    map.append(svg("text", {x: x - 22, y: y - 32, fill: colour, "font-size": 11},
      `${Math.round(t.speed_kmph)} km/h${stale ? " STALE" : ""}${t.finished ? " arrived" : ""}`));
  }
}

function drawThreats() {
  const body = document.getElementById("threats");
  body.replaceChildren();
  if (!state.threats.length) body.append(el("tr", {}, el("td", {colspan: 7, class: "muted"}, "No active threats.")));
  for (const t of state.threats) {
    const ack = t.lifecycle === "OPEN" ? el("button", {onclick: () => act(() => api(`/threats/${t.id}/ack`, {by: who()}))}, "Ack") : "";
    body.append(el("tr", {}, el("td", {}, t.id), el("td", {}, t.type, el("div", {class: "muted"}, t.detail)), el("td", {}, badge(t.severity)),
      el("td", {}, t.train_ids.join(",") + (t.section_id ? ` @${t.section_id}` : "")), el("td", {}, t.controller_recommendation,
        el("div", {class: "muted"}, `confidence ${t.confidence}`)), el("td", {}, badge(t.lifecycle)), el("td", {}, ack)));
  }
}

function drawEvidence() {
  const body = document.getElementById("evidence");
  body.replaceChildren();
  const items = latest ? latest.assessment.items.filter(i => i.mandatory) : [];
  if (!items.length) { body.append(el("tr", {}, el("td", {colspan: 4, class: "muted"}, "Rank alternatives to assess evidence."))); return; }
  for (const i of items) body.append(el("tr", {}, el("td", {}, i.key), el("td", {}, badge(i.state)), el("td", {}, i.source || "-"), el("td", {}, i.age_s === null ? "-" : `${i.age_s}s`)));
}

async function drawAudit() {
  const data = await api("/audit?limit_events=12");
  const body = document.getElementById("audit");
  body.replaceChildren();
  for (const e of data.events.slice().reverse()) body.append(el("tr", {}, el("td", {}, e.seq), el("td", {}, fmtClock(e.t)), el("td", {}, e.type),
    el("td", {}, e.actor), el("td", {class: "muted"}, e.hash.slice(0, 10))));
}

function drawRecommendation() {
  const box = document.getElementById("candidates");
  box.replaceChildren();
  document.getElementById("recError").textContent = "";
  if (!latest) return;
  const st = document.getElementById("recState");
  st.textContent = latest.state; st.className = `badge s-${latest.state}`;
  document.getElementById("recReason").textContent = latest.reason;
  document.getElementById("snapshot").textContent = `Snapshot ${latest.snapshot_id} · checksum ${latest.checksum.slice(0, 16)}… · preset ${latest.preset} · t=${fmtClock(latest.t)}`;
  const ranking = latest.ranking;
  if (!ranking.candidates || !ranking.candidates.length) { box.append(el("div", {class: "muted"}, "No feasible candidate.")); return; }
  box.append(el("div", {class: "muted"}, `${ranking.feasible_count} feasible plans ranked · ${ranking.conflicting_combinations} rejected for occupation conflicts · headway ${ranking.headway_min} min`));
  ranking.candidates.forEach((c, i) => {
    const bars = el("div", {class: "bars"});
    for (const f of FACTORS) {
      const w = Math.round(c.factors[f] * 100);
      bars.append(el("span", {}, f), el("div", {class: "bar"}, el("span", {style: `width:${w}%`})), el("span", {class: "muted"}, `+${c.contributions[f].toFixed(2)}`));
    }
    const lost = c.why_lost.length ? el("div", {class: "muted"}, "Lost on: " + c.why_lost.map(l => `${l.factor} (+${l.extra})`).join(", ")) : el("div", {class: "muted"}, "Winner");
    const sep = c.closest_separations.length ? el("div", {class: "muted"}, "Closest separation: " +
      c.closest_separations.map(s => `${s.section_id} ${s.gap_min} min`).join(", ")) : "";
    const approve = el("button", {class: "primary", onclick: () => act(() => api("/approve", {snapshot_id: latest.snapshot_id, candidate_id: c.candidate_id, controller: who()}))}, "APPROVE FOR DEMO");
    if (!latest.approvable) { approve.disabled = true; approve.title = `Not approvable: ${latest.state}`; }
    box.append(el("div", {class: "card" + (i === 0 ? " top" : "")},
      el("div", {class: "row"}, el("b", {}, c.candidate_id), ...c.labels.map(l => badge(l, "INFO")), badge(c.action, "OK"), el("span", {class: "grow"}), el("b", {}, `score ${c.score.toFixed(3)}`)),
      el("div", {}, c.summary),
      el("div", {class: "muted"}, `delay ${c.raw.delay} min·weighted · infra stress ${c.raw.infra} · energy ${c.raw.energy}`),
      bars, lost, sep, el("div", {class: "row"}, approve)));
  });
}

function drawControls() {
  const presets = document.getElementById("presets");
  presets.replaceChildren(el("span", {class: "muted"}, "Preset:"));
  for (const p of PRESETS) presets.append(el("button", {class: state.preset === p ? "active" : "", onclick: () => act(() => api("/recommend", {preset: p}).then(r => (latest = r)))}, p.replace("_", " ")));
  const sliders = document.getElementById("sliders");
  if (!sliders.dataset.ready) {
    for (const f of FACTORS) {
      const out = el("span", {class: "muted", id: `w-${f}-v`});
      const input = el("input", {type: "range", min: 0, max: 2, step: 0.05, id: `w-${f}`});
      input.addEventListener("input", () => { out.textContent = input.value; });
      input.addEventListener("change", () => act(() => api("/recommend", {weights: {[f]: Number(input.value)}}).then(r => (latest = r))));
      sliders.append(el("div", {class: "slider"}, el("span", {}, f), input, out));
    }
    sliders.dataset.ready = "1";
  }
  for (const f of FACTORS) { document.getElementById(`w-${f}`).value = state.weights[f]; document.getElementById(`w-${f}-v`).textContent = state.weights[f]; }
}

function who() { return document.getElementById("controllerName").value.trim() || "controller"; }

async function refresh() {
  try {
    state = await api("/state");
    latest = state.latest_recommendation;
    document.getElementById("clock").textContent = fmtClock(state.t);
    const chain = document.getElementById("chainBadge");
    chain.textContent = state.audit_chain_ok ? `audit chain OK (${state.audit_events})` : "AUDIT CHAIN BROKEN";
    chain.className = `badge s-${state.audit_chain_ok ? "OK" : "BAD"}`;
    const ev = document.getElementById("evidenceBadge");
    ev.textContent = latest ? `evidence ${latest.assessment.state}` : "evidence: not assessed";
    ev.className = `badge s-${latest ? latest.assessment.state : "INFO"}`;
    drawMap(); drawThreats(); drawEvidence(); drawRecommendation(); drawControls(); await drawAudit();
    document.getElementById("simError").textContent = "";
  } catch (e) { document.getElementById("simError").textContent = e.message; }
}

async function act(fn) {
  try { await fn(); } catch (e) { document.getElementById("recError").textContent = e.message; document.getElementById("simError").textContent = e.message; return; }
  await refresh();
}

async function init() {
  const scenarios = await api("/scenarios");
  const sel = document.getElementById("scenario");
  for (const s of scenarios) sel.append(el("option", {value: s.name}, s.title));
  document.getElementById("loadScenario").onclick = () => act(() => api(`/scenarios/${sel.value}/load`, {}).then(() => { latest = null; }));
  document.querySelectorAll("[data-tick]").forEach(b => b.onclick = () => act(() => api("/tick", {seconds: Number(b.dataset.tick)})));
  document.querySelectorAll("[data-fault]").forEach(b => b.onclick = () => act(() => api("/fault", {kind: b.dataset.fault, train_id: b.dataset.train || null, section_id: b.dataset.section || null})));
  document.querySelectorAll("[data-condition]").forEach(b => b.onclick = () => { const [sid, v] = b.dataset.condition.split(":"); act(() => api("/console/section", {section_id: sid, condition: Number(v)})); });
  document.querySelectorAll("[data-weather]").forEach(b => b.onclick = () => { const [sid, v] = b.dataset.weather.split(":"); act(() => api("/console/section", {section_id: sid, weather_alert: v})); });
  document.getElementById("recommend").onclick = () => act(() => api("/recommend", {}).then(r => (latest = r)));
  document.getElementById("holdAll").onclick = () => act(() => api("/hold", {controller: who(), reason: "Controller hold from Nexus Control"}));
  document.getElementById("reject").onclick = () => latest && act(() => api("/reject", {snapshot_id: latest.snapshot_id, controller: who(), reason: "Rejected in Nexus Control"}));
  document.getElementById("replay").onclick = () => latest && act(async () => {
    const r = await api(`/audit/${latest.snapshot_id}/replay`);
    alert(`Replay ${r.snapshot_id}\nIntegrity: ${r.integrity_ok ? "OK" : "FAILED"}\nRanking reproduced: ${r.replay_matches ? "YES" : "NO"}\nRecorded: ${r.recorded_top}\nReplayed: ${r.replayed_top}\n\n${r.note}`);
  });
  document.getElementById("play").onclick = (e) => {
    if (playing) { clearInterval(playing); playing = null; e.target.textContent = "▶ Auto"; return; }
    e.target.textContent = "⏸ Pause";
    playing = setInterval(() => act(() => api("/tick", {seconds: 30})), 1000);
  };
  try { document.getElementById("token").value = localStorage.getItem("rgToken") || ""; } catch (_) { /* storage blocked */ }
  document.getElementById("token").addEventListener("change", (e) => { try { localStorage.setItem("rgToken", e.target.value); } catch (_) { /* ignore */ } });
  await refresh();
  setInterval(() => { if (!playing) refresh(); }, 3000);
}
init();
