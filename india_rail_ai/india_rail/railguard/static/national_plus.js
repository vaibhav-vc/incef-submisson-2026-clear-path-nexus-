"use strict";
// Sign-in, live push, every train with its route, delay advisor, freight corridors, power and readiness.
let sessionToken = null, sessionUser = null, route = null, corridors = null, focus = null;

// ---- sign-in (named accounts) ----------------------------------------------------------------------
function showUser() {
  const signedIn = Boolean(sessionUser);
  document.getElementById("signedIn").textContent = signedIn ? `${sessionUser.display_name} · ${sessionUser.role}` : "";
  for (const id of ["user", "pass", "login"]) document.getElementById(id).hidden = signedIn;
  document.getElementById("logout").hidden = !signedIn;
  document.getElementById("controllerName").parentElement.hidden = signedIn;  // the server records the person
}
async function login() {
  const username = document.getElementById("user").value.trim(), password = document.getElementById("pass").value;
  document.getElementById("pass").value = "";
  const s = await api("/auth/login", {username, password});
  sessionToken = s.token;
  sessionUser = {display_name: s.display_name, role: s.role};
  try { sessionStorage.setItem("rgSession", s.token); } catch (_) { /* storage blocked */ }
  showUser();
  document.getElementById("pwChange").hidden = !s.must_change_password;
}
async function logout() {
  try { await api("/auth/logout", {}); } catch (_) { /* already gone */ }
  sessionToken = null; sessionUser = null;
  try { sessionStorage.removeItem("rgSession"); } catch (_) { /* ignore */ }
  showUser();
}
async function changePassword() {
  await api("/auth/password", {old_password: document.getElementById("pwOld").value, new_password: document.getElementById("pwNew").value});
  document.getElementById("pwChange").hidden = true;
  sessionToken = null; sessionUser = null; showUser();
  showError(new Error("Password changed - sign in again with the new password."));
}
async function restoreSession() {
  try { sessionToken = sessionStorage.getItem("rgSession"); } catch (_) { sessionToken = null; }
  if (!sessionToken) return showUser();
  try { const me = await api("/auth/me"); sessionUser = me; } catch (_) { sessionToken = null; sessionUser = null; }
  showUser();
}

// ---- live push: positions and threats as they change (fetch stream: it can carry the auth header) -------
function setLive(on) {
  const b = document.getElementById("liveBadge");
  b.textContent = on ? "LIVE PUSH" : "polling";
  b.className = `badge s-${on ? "OK" : "INFO"}`;
}
function handleEvent(block) {
  let kind = "message", data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event: ")) kind = line.slice(7);
    else if (line.startsWith("data: ")) data += line.slice(6);
  }
  if (kind !== "state" || !data) return;
  const s = JSON.parse(data);
  positions = s.positions;
  renderThreats(s.threats);
  draw();
}
async function liveLoop() {
  for (;;) {
    try {
      const res = await fetch("/railguard/national/stream", {headers: headers()});
      if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);
      liveStream = true; setLive(true);
      const reader = res.body.getReader(), decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const {value, done} = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, {stream: true});
        let cut;
        while ((cut = buffer.indexOf("\n\n")) >= 0) { handleEvent(buffer.slice(0, cut)); buffer = buffer.slice(cut + 2); }
      }
    } catch (_) { /* fall back to polling, retry below */ }
    liveStream = false; setLive(false);
    await new Promise(r => setTimeout(r, 5000));
  }
}

// ---- power and readiness ------------------------------------------------------------------------------
async function health() {
  const b = document.getElementById("powerBadge");
  try {
    const res = await fetch("/health/ready");
    const h = await res.json();
    const level = h.power;
    b.textContent = h.read_only ? "POWER CRITICAL · approvals paused" : `power ${level.toLowerCase().replace("_", " ")}`;
    b.className = `badge s-${h.read_only ? "CRITICAL" : level === "ON_BATTERY" || level === "MONITOR_LOST" ? "WARNING" : h.ready ? "OK" : "CAUTION"}`;
  } catch (_) { b.textContent = "service unreachable"; b.className = "badge s-CRITICAL"; }
}

// ---- every train: number, name, operator, PIN codes, route on mapped track -------------------------------
async function searchTrains() {
  const q = document.getElementById("tq").value.trim(), op = document.getElementById("top").value;
  const params = new URLSearchParams({q, limit: "40"});
  if (op) params.set("operator", op);
  const r = await api(`/trains?${params}`);
  const box = document.getElementById("tresults");
  box.replaceChildren(...(r.trains.length ? r.trains.map(t => el("div", {class: "runitem", onclick: () => act(() => showTrain(t.number))},
    el("b", {}, t.number), ` ${t.name} · ${t.operator} · ${t.running_days || "days n/a"}`,
    t.in_twin ? "" : el("span", {class: "muted"}, " · not in today's twin"))) : [el("div", {class: "muted"}, "No train matches.")]));
}
async function showTrain(number) {
  const t = await api(`/trains/${encodeURIComponent(number)}`);
  const rs = t.route_summary || {};
  const stops = el("table", {}, el("thead", {}, el("tr", {}, ...["#", "Station", "PIN", "Arr", "Dep", "Zone"].map(h => el("th", {}, h)))),
    el("tbody", {}, ...t.stops.map(s => el("tr", {}, el("td", {}, s.seq + 1), el("td", {}, `${s.code} ${s.name || ""}`),
      el("td", {title: s.pin_source || ""}, s.pin || "—"), el("td", {}, s.arrival), el("td", {}, s.departure), el("td", {}, s.zone || "")))));
  document.getElementById("tdetail").replaceChildren(
    el("div", {class: "row"}, el("b", {}, `${t.number} ${t.name}`), badge(t.operator, t.operator === "Indian Railways" ? "INFO" : "CAUTION"),
      el("span", {class: "muted"}, `${t.type || ""} · ${t.running_days || ""} · valid ${t.valid_from || "?"}–${t.valid_to || "?"}`)),
    el("div", {class: "muted"}, `Route: ${rs.sections || 0} sections · ${rs.mapped_track_km || 0} km on mapped track · ${rs.unmapped_straight_line_km || 0} km not mapped (straight) · ${rs.single_line_km || 0} km single line · ${rs.electrified_km || 0} km electrified`),
    el("div", {class: "row"}, el("button", {onclick: () => { document.getElementById("number").value = t.number; act(findTrain); }}, "Runs in the twin"),
      el("button", {onclick: () => act(() => trainAdvice(t.number))}, "Delay advice for this train")),
    el("div", {class: "scroll"}, stops),
    el("div", {class: "muted"}, "PIN codes from OpenStreetMap postcodes near the station (approximate); track (c) OpenStreetMap contributors, ODbL."));
  const geo = await api(`/trains/${encodeURIComponent(number)}/route`);
  route = geo.geometry.coordinates;
  fit(route); draw();
}
function drawRoute() {
  if (!route || route.length < 2) return;
  ctx.beginPath();
  route.forEach(([lon, lat], i) => { const [x, y] = project(lon, lat); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y); });
  ctx.strokeStyle = "#f0883e"; ctx.lineWidth = 2.5; ctx.stroke();
}

// ---- delay-minimisation advisor -----------------------------------------------------------------------
const ADVICE_COLUMNS = {
  sections: [["section", "Section"], ["between", "Between"], ["lost_min_per_day", "Lost min/day"], ["lines", "Lines"], ["chronic", "Chronic"], ["lever", "Lever"]],
  stations: [["station", "Station"], ["name", "Name"], ["lost_min_per_day_arriving", "Lost min/day"], ["worst_hour", "Worst hour"], ["lever", "Lever"]],
  late_starts: [["train", "Train"], ["name", "Name"], ["late_share_pct", "Late %"], ["median_start_delay_min", "Median min"], ["lever", "Lever"]],
  timetable: [["train", "Train"], ["section", "Section"], ["median_loss_min", "Loses min"], ["recovery_elsewhere_min", "Recovers elsewhere"], ["lever", "Lever"]],
  trains: [["train", "Train"], ["name", "Name"], ["on_time_pct", "On time %"], ["median_arrival_delay_min", "Median late"], ["median_start_delay_min", "Starts late"]],
};
async function loadAdvice() {
  const kind = document.getElementById("akind").value;
  const [summary, rows] = await Promise.all([api("/advisor"), api(`/advisor/${kind}?limit=15`)]);
  const s = summary.summary, p = s.persistence.sections;
  document.getElementById("asummary").textContent = `Network loses ${s.network_lost_min_per_day.toLocaleString()} train-minutes a day (recovers ${s.network_recovered_min_per_day.toLocaleString()}). ` +
    `Findings persist: ${p.top_50_found_again_in_top_100_pct}% of the worst 50 sections on 1-15 Sep are again among the worst 100 on 16-30 Sep.`;
  const cols = ADVICE_COLUMNS[kind];
  document.getElementById("atable").replaceChildren(el("thead", {}, el("tr", {}, ...cols.map(([, h]) => el("th", {}, h)))),
    el("tbody", {}, ...rows.findings.map(r => el("tr", {class: r.section ? "clickable" : "", onclick: () => focusSection(r.section)},
      ...cols.map(([k]) => el("td", {class: k === "lever" ? "muted" : ""}, typeof r[k] === "boolean" ? (r[k] ? "yes" : "no") : r[k] ?? "—"))))));
}
async function trainAdvice(number) {
  const a = await api(`/advisor/train/${encodeURIComponent(number)}`);
  const lines = [];
  if (a.chronic_lateness) lines.push(`Late at destination on ${(100 - a.chronic_lateness.on_time_pct).toFixed(0)}% of days (median ${a.chronic_lateness.median_arrival_delay_min} min).`);
  for (const l of a.late_start) lines.push(`Starts late ${l.late_share_pct}% of days: ${l.lever}.`);
  for (const t of a.timetable.slice(0, 3)) lines.push(`${t.section}: ${t.lever}.`);
  for (const h of a.hotspots_on_its_route.slice(0, 3)) lines.push(`Hotspot ${h.section} (${h.lost_min_per_day} min/day network-wide): ${h.lever}.`);
  document.getElementById("asummary").textContent = lines.length ? `${number}: ` + lines.join(" ") : `${number}: no chronic finding in the observed running.`;
}
function focusSection(section) {
  if (!section || !net) return;
  const [a, b] = section.split("-");
  if (!net.nodes[a] || !net.nodes[b]) return;
  focus = [net.nodes[a], net.nodes[b]];
  fit(focus); draw();
}
function drawFocus() {
  if (!focus) return;
  const [p1, p2] = focus.map(([lon, lat]) => project(lon, lat));
  ctx.beginPath(); ctx.moveTo(...p1); ctx.lineTo(...p2);
  ctx.strokeStyle = "#f85149"; ctx.lineWidth = 5; ctx.stroke();
}

// ---- Dedicated Freight Corridors ----------------------------------------------------------------------
async function loadCorridors() {
  const d = await api("/railguard/freight/corridors");
  corridors = d.corridors;
  const pub = d.published || {};
  document.getElementById("fsummary").replaceChildren(...Object.entries(corridors).map(([name, c]) =>
    el("div", {}, el("b", {}, `${name} DFC`), ` · ${c.centreline_km} km mapped (published ${c.published_km}) · ${c.single_line_km} km single line · ${c.segments.length} segments · ${c.interchanges_with_ir} interchanges with IR`)),
    el("div", {class: "muted"}, pub.trains_per_day_fy2025 ? `Published: ${pub.trains_per_day_fy2025} trains a day across both corridors (FY2025).` : ""));
  draw();
}
function drawCorridors() {
  if (!corridors || !document.getElementById("showDfc").checked) return;
  for (const c of Object.values(corridors)) {
    for (let i = 1; i < c.segments.length; i++) {
      const [x1, y1] = project(...c.segments[i - 1].mid_lonlat), [x2, y2] = project(...c.segments[i].mid_lonlat);
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2);
      ctx.strokeStyle = c.segments[i].lines === 1 ? "#d29922" : "#3fb950"; ctx.lineWidth = 3; ctx.stroke();
    }
  }
}
async function planFreight() {
  const name = document.getElementById("fcorr").value, n = Math.min(Math.max(Number(document.getElementById("fn").value) || 50, 1), 600);
  const c = corridors[name], length = c.segments[c.segments.length - 1].to_km;
  const trains = Array.from({length: n}, (_, i) => {
    const a = Math.random() * length, b = Math.random() * length;
    return {id: `F${i + 1}`, origin_km: Math.round(Math.min(a, b)), destination_km: Math.round(Math.max(a, b)) + 1, ready_min: Math.round(Math.random() * 1440)};
  }).map(t => ({...t, destination_km: Math.min(t.destination_km, Math.floor(length))})).filter(t => t.destination_km > t.origin_km);
  const r = await api("/railguard/freight/plan", {corridor: name, trains});
  document.getElementById("fresult").textContent = `${r.planned}/${r.trains} trains pathed · mean wait ${r.mean_delay_min} min · ${r.on_free_path_pct}% on their free path · ` +
    `${r.violations.length} conflicts in the independent check · busiest segment ${r.capacity.busiest_segment.occupied_pct_of_day}% of the day occupied · advisory only`;
}

// ---- start --------------------------------------------------------------------------------------------
async function startPlus() {
  overlays.push(drawRoute, drawCorridors, drawFocus);
  document.getElementById("login").onclick = () => act(login);
  document.getElementById("pass").addEventListener("keydown", (e) => { if (e.key === "Enter") act(login); });
  document.getElementById("logout").onclick = () => act(logout);
  document.getElementById("pwSave").onclick = () => act(changePassword);
  document.getElementById("tsearch").onclick = () => act(searchTrains);
  document.getElementById("tq").addEventListener("keydown", (e) => { if (e.key === "Enter") act(searchTrains); });
  document.getElementById("akind").onchange = () => act(loadAdvice);
  document.getElementById("fplan").onclick = () => act(planFreight);
  document.getElementById("showDfc").onchange = () => draw();
  await restoreSession();
  try {
    const ops = await api("/operators");
    document.getElementById("top").append(...ops.by_operator.map(o => el("option", {value: o.operator}, `${o.operator} (${o.trains})`)));
  } catch (e) { document.getElementById("tdetail").textContent = e.message; }
  try { await loadAdvice(); } catch (e) { document.getElementById("asummary").textContent = e.message; }
  try { await loadCorridors(); } catch (e) { document.getElementById("fsummary").textContent = e.message; }
  health(); setInterval(health, 10000);
  liveLoop();
}
startPlus();
