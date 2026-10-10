"use strict";
// Station board (?station=NDLS) or one train's stops (?run=12951@0): expected times as published by the twin
// (later times at once, earlier ones once they hold, never leaving early). Information only; NTES is official.
const params = new URLSearchParams(location.search);
const station = /^[A-Za-z0-9]{1,8}$/.test(params.get("station") || "") ? params.get("station").toUpperCase() : null;
const run = /^[0-9A-Z]{1,10}@-?[0-3]$/.test(params.get("run") || "") ? params.get("run") : null;
const windowMin = /^[0-9]{2,3}$/.test(params.get("window") || "") ? params.get("window") : "180";
// A viewer token arrives in the URL fragment (never sent to servers) and is moved out of the address bar.
let viewerToken = "";
try {
  const hash = new URLSearchParams(location.hash.slice(1));
  if (hash.get("token")) sessionStorage.setItem("rgViewer", hash.get("token"));
  if (location.hash) history.replaceState(null, "", location.pathname + location.search);
  viewerToken = sessionStorage.getItem("rgViewer") || "";
} catch (_) { /* storage blocked: run without a token */ }

const POLL_MS = 30000;
const STALE_AFTER_MS = 180000;  // no fresh data for this long: times are greyed and people pointed to NTES
let lastOk = 0, timer = null;

function el(tag, text, cls) {
  const n = document.createElement(tag);
  if (text !== undefined && text !== null) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
function set(id, text) { document.getElementById(id).textContent = text; }
function show(id, on) { document.getElementById(id).hidden = !on; }
function day(clock) { const m = /day (\d+)/.exec(clock || ""); return m ? +m[1] : null; }
function hhmm(clock, today) {
  if (!clock) return "";
  const d = day(clock), t = clock.slice(0, 5);
  return d !== null && today !== null && d !== today ? `${t} (${d > today ? "+" : ""}${d - today}d)` : t;
}
function statusClass(s) {
  if (!s) return "";
  if (s.startsWith("LATE")) return "st st-late";
  if (s === "ON TIME") return "st st-ok";
  if (s === "SCHEDULED") return "st";
  if (s === "DUE") return "st st-due";
  if (s.startsWith("NOT CALLING")) return "st st-gone";
  if (s === "ARRIVED" || s === "DEPARTED") return "st st-done";
  return "st";
}
function head(cells) {
  const tr = el("tr");
  for (const [en, hi, opt] of cells) {
    const th = el("th", en, opt ? "opt" : "");
    th.append(el("small", hi));
    tr.append(th);
  }
  document.getElementById("head").replaceChildren(tr);
}
function timeCell(expected, scheduled, today, note) {
  const td = el("td", hhmm(expected || scheduled, today) || "—", "time");
  if (expected && scheduled && expected !== scheduled) td.append(el("span", `timetable ${hhmm(scheduled, today)}`, "note"));
  if (note) td.append(el("span", note, "note"));
  return td;
}

function renderBoard(b) {
  const today = day(b.now);
  set("title", `${b.station} · next ${Math.round(b.window_min / 60)} h`);
  head([["Train", "गाड़ी"], ["From → To", "से → तक", true], ["Arrives", "आगमन"], ["Departs", "प्रस्थान"],
        ["Status", "स्थिति"], ["Report", "सूचना", true]]);
  const rows = b.trains.map(t => {
    const tr = el("tr");
    tr.append(el("td", t.train), el("td", `${t.from} → ${t.to}`, "opt"));
    if (t.status) {  // not calling here any more
      tr.append(el("td", "—", "time"), timeCell(null, t.scheduled, today), el("td", t.status, statusClass(t.status)));
    } else {
      const s = t.dep_status && !t.dep_status.startsWith("DEPARTED") ? t.dep_status : t.arr_status;
      tr.append(timeCell(t.expected_arr, t.scheduled_arr, today), timeCell(t.expected_dep, t.scheduled_dep, today),
                el("td", s || "", statusClass(s)));
    }
    tr.append(el("td", t.evidence, "opt"));
    return tr;
  });
  document.getElementById("rows").replaceChildren(...rows);
  set("empty", "No trains due in this window.");
  show("empty", rows.length === 0);
  set("more", b.more ? `${b.more} more later in the window.` : "");
  show("more", !!b.more);
}

function renderTrain(t) {
  const today = day(t.now);
  set("title", t.train);
  set("subtitle", t.evidence.basis === "LIVE" ? "Live position · expected times" : t.evidence.text);
  head([["Station", "स्टेशन"], ["Arrives", "आगमन"], ["Departs", "प्रस्थान"], ["Status", "स्थिति"]]);
  const rows = t.stops.map(s => {
    const tr = el("tr");
    const status = s.arr_status && s.arr_status !== "ARRIVED" ? s.arr_status : (s.dep_status || s.arr_status);
    const likely = s.likely_arrival ? `likely ${hhmm(s.likely_arrival[0], today)}–${hhmm(s.likely_arrival[1], today)}` : null;
    tr.append(el("td", s.station), timeCell(s.expected_arr, s.scheduled_arr, today, likely),
              timeCell(s.expected_dep, s.scheduled_dep, today), el("td", status || "", statusClass(status)));
    return tr;
  });
  document.getElementById("rows").replaceChildren(...rows);
  show("empty", false);
  show("more", false);
}

function markStale() {
  const age = lastOk ? Date.now() - lastOk : Infinity;
  const banner = document.getElementById("banner");
  if (age < POLL_MS * 1.5) { banner.hidden = true; document.body.classList.remove("stale"); return; }
  banner.hidden = false;
  if (age > STALE_AFTER_MS || !lastOk) {
    banner.textContent = lastOk ? "Information not current. Please check NTES (139) or the enquiry office."
                                : "Information unavailable. Please check NTES (139) or the enquiry office.";
    for (const tr of document.querySelectorAll("#rows tr")) tr.className = "stale";
  } else {
    banner.textContent = `Not updated since ${new Date(lastOk).toLocaleTimeString()}: reconnecting…`;
  }
}

async function refresh() {
  if (!station && !run) {
    set("title", "Station board");
    set("empty", "Enter a station code to see the trains due there.");
    show("empty", true);
    return;
  }
  try {
    const url = run ? `/railguard/national/expected/${encodeURIComponent(run)}`
                    : `/railguard/national/board/${encodeURIComponent(station)}?window=${windowMin}`;
    const res = await fetch(url, {headers: viewerToken ? {Authorization: "Bearer " + viewerToken} : {}, cache: "no-store"});
    if (res.status === 404) { set("empty", run ? "Unknown train run." : "Unknown station code."); show("empty", true);
                              document.getElementById("rows").replaceChildren(); lastOk = Date.now(); markStale(); return; }
    if (!res.ok) throw new Error(String(res.status));
    (run ? renderTrain : renderBoard)(await res.json());
    lastOk = Date.now();
    set("fresh", `Updated ${new Date(lastOk).toLocaleTimeString()}`);
  } catch (_) {
    /* keep what is on screen; the banner says how old it is */
  }
  markStale();
}

function schedule() {
  clearInterval(timer);
  timer = setInterval(() => { if (!document.hidden) refresh(); }, POLL_MS);
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
document.getElementById("pick").addEventListener("submit", e => {
  e.preventDefault();
  const code = document.getElementById("station").value.trim().toUpperCase();
  if (/^[A-Z0-9]{1,8}$/.test(code)) location.search = "?station=" + encodeURIComponent(code);
});
if (station) document.getElementById("station").value = station;
refresh();
schedule();
