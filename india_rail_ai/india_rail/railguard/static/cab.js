"use strict";
const params = new URLSearchParams(location.search);
// ?run=12951@0 shows a national-twin run; otherwise ?train=A|B shows the tabletop twin.
const run = /^[0-9A-Z]{1,10}@-?[0-3]$/.test(params.get("run") || "") ? params.get("run") : null;
const train = /^[A-Z0-9]{1,10}$/.test(params.get("train") || "") ? params.get("train") : "A";
// Credentials arrive in the URL fragment, which browsers never send to servers, and are moved out of the address bar:
// #cab=... is the capability a controller issued for this one run (this train's advisory, nothing else);
// #token=... is a viewer token (supervisor screens and the tabletop demo).
let viewerToken = "", cabToken = "";
try {
  const hash = new URLSearchParams(location.hash.slice(1));
  if (hash.get("token")) sessionStorage.setItem("rgViewer", hash.get("token"));
  if (run && hash.get("cab")) sessionStorage.setItem("rgCab:" + run, hash.get("cab"));
  if (location.hash) history.replaceState(null, "", location.pathname + location.search);
  viewerToken = sessionStorage.getItem("rgViewer") || "";
  cabToken = run ? sessionStorage.getItem("rgCab:" + run) || "" : "";
} catch (_) { /* storage blocked: run without a token */ }
const SILENCE_MS = 25000;  // the server speaks at least every 15 s (advisory or heartbeat); silence longer than this = link lost

function li(text, cls) { const n = document.createElement("li"); n.textContent = text; if (cls) n.className = cls; return n; }
function chip(text, now) { const n = document.createElement("span"); n.className = "chip" + (now ? " now" : ""); n.textContent = text; return n; }
function set(id, text) { document.getElementById(id).textContent = text; }
function list(id, items, empty) { document.getElementById(id).replaceChildren(...(items.length ? items : [li(empty)])); }
function status(s) { document.getElementById("status").className = "status st-" + s.replace(/ /g, "-"); set("statusText", s); }
function band(b) { return b ? `${b[0]}–${b[1]} km/h` : "--"; }
function threats(a) { list("threats", a.threats.map(t => li(`${t.severity}: ${t.message}`, "sev-" + t.severity)), "No current advisory threat"); }

function renderDemo(a) {
  set("title", a.train_name);
  set("fresh", `position ${a.evidence.position}${a.evidence.age_s !== null ? ` · ${a.evidence.age_s}s old` : ""} · ${a.evidence.source}`);
  status(a.status);
  set("headline", a.headline);
  set("speed", a.speed_kmph === null ? "--" : Math.round(a.speed_kmph));
  set("band", band(a.advisory_speed_band_kmph));
  set("schedule", a.schedule ? `Schedule ${a.schedule.deviation_min > 0 ? "+" : ""}${a.schedule.deviation_min} min vs timetable` : "");
  const strip = a.route_strip;
  document.getElementById("route").replaceChildren(...(strip.approved_route.length
    ? strip.approved_route.map(s => chip(s, s === strip.current_section)) : [chip("No approved plan")]));
  set("nextwp", strip.next_waypoint ? `Next waypoint ${strip.next_waypoint}` +
    (strip.planned_hold ? ` · planned hold ${strip.planned_hold.minutes} min at ${strip.planned_hold.node}` : "") : "");
  list("events", a.next_events.map(e => li(`${e.text} — in ${e.in_km} km`)), "No restriction or caution in the next 12 km");
  list("nearby", a.nearby_trains.map(n => li(`Train ${n.train_id}: ${n.relation}, ~${n.separation_km ?? "?"} km, confidence ${n.confidence}`)),
    "No other active train");
  threats(a);
  set("footer", a.footer);
}

function renderNational(a) {
  const p = a.position;
  set("title", `${a.train} (${a.type})`);
  set("fresh", `position ${a.position_evidence}${a.position_evidence === "PROJECTED" ? " from timetable" : ""}`);
  status(a.status);
  const where = p.state === "RUNNING" ? `${p.from_node} → ${p.to_node}, ${p.offset_km} km in` : `${p.state.replace("_", " ")} ${p.node}`;
  set("headline", `${where} · plan: ${a.plan_source}`);
  set("speed", p.state === "RUNNING" ? Math.round(p.speed_kmph) : "0");
  set("band", band(a.advisory_speed_band_kmph));
  const d = a.schedule_deviation_min;
  set("schedule", `Arrival ${a.arrival} · ${d > 0 ? "+" : ""}${d} min vs timetable`);
  document.getElementById("route").replaceChildren(...(a.route_ahead.length
    ? a.route_ahead.map((s, i) => chip(s, i === 0 && p.state === "RUNNING")) : [chip("Journey complete")]));
  set("nextwp", a.next_station ? `Next station ${a.next_station}` : "");
  list("events", [], "Line-side restrictions come from authorised sources only");
  list("nearby", a.nearby_trains.map(n => li(`Run ${n.run}: ${n.relation}, confidence ${n.confidence}`)), "No other train in this section");
  threats(a);
  set("footer", a.footer);
}

function unavailable(why) {
  // Losing the link must never leave stale guidance on screen: everything the last advisory said is cleared.
  status("DATA UNAVAILABLE");
  set("headline", why || "Link to Nexus lost - follow signals and authorised instructions");
  set("speed", "--"); set("band", "--");
  set("fresh", "no current data"); set("schedule", ""); set("nextwp", "");
  document.getElementById("route").replaceChildren(chip("No current data"));
  for (const id of ["events", "nearby", "threats"]) list(id, [], "No current data");
}

async function refresh() {
  try {
    const url = run ? `/railguard/national/cab/${encodeURIComponent(run)}` : `/railguard/cab/${train}`;
    const res = await fetch(url, {headers: viewerToken ? {Authorization: "Bearer " + viewerToken} : {}});
    if (!res.ok) throw new Error(res.statusText);
    (run ? renderNational : renderDemo)(await res.json());
  } catch (e) {
    unavailable();
  }
}

// ---- live push for a cab unit holding this run's capability ----------------------------------------------
function handleEvent(block) {
  let kind = "message", data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event: ")) kind = line.slice(7);
    else if (line.startsWith("data: ")) data += line.slice(6);
  }
  if (kind === "advisory" && data) renderNational(JSON.parse(data));
  else if (kind === "revoked") throw new Error("revoked");
  else if (kind === "refused") throw new Error("refused");
}
async function cabLive() {
  for (;;) {
    let watchdog = null, wait = 3000;
    const abort = new AbortController();
    const arm = () => { clearTimeout(watchdog); watchdog = setTimeout(() => { unavailable(); abort.abort(); }, SILENCE_MS); };
    try {
      arm();
      const res = await fetch(`/railguard/national/cab/${encodeURIComponent(run)}/stream`,
        {headers: {Authorization: "Bearer " + cabToken}, signal: abort.signal, cache: "no-store"});
      if (res.status === 403) {
        unavailable("This cab link is not valid for this train (expired or revoked) - ask the controller for a new link");
        wait = 30000;
        throw new Error("forbidden");
      }
      if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);
      const reader = res.body.getReader(), decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const {value, done} = await reader.read();
        if (done) break;
        arm();  // any bytes (an advisory or a heartbeat) prove the link is alive
        buffer += decoder.decode(value, {stream: true});
        let cut;
        while ((cut = buffer.indexOf("\n\n")) >= 0) { handleEvent(buffer.slice(0, cut)); buffer = buffer.slice(cut + 2); }
      }
      if (wait !== 30000) unavailable();
    } catch (e) {
      if (e.message === "revoked") {
        unavailable("This cab link is not valid for this train (expired or revoked) - ask the controller for a new link");
        wait = 30000;
      } else if (wait !== 30000) unavailable();
    } finally {
      clearTimeout(watchdog);
      abort.abort();
    }
    await new Promise(r => setTimeout(r, wait));
  }
}

if (run) document.querySelector(".switch").hidden = true;
if (run && cabToken) {
  cabLive();
} else {
  refresh();
  setInterval(refresh, run ? 4000 : 1000);
}
