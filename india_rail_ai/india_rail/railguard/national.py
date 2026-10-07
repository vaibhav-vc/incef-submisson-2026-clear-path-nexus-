"""Nexus RailGuard on the full national network: every station, junction, section and train.

Static data (built once from the ingested open timetable, shared, never mutated):
  * the network: every station pair the timetable connects (8,738 sections, 1,454
    junctions), with length, timetable-implied line speed and track count *inferred*
    and labelled with how each value was derived;
  * every train run (a train number on a start day) with its scheduled section
    occupations, and a per-section index of those occupations.

Dynamic state (small, per twin): delays, holds, reroutes, section overrides,
live-feed evidence, threats, approvals and the audit log. Resetting or replaying
touches only what changed, so millions of simulated episodes stay cheap.

Without authorised RTIS/COA access, positions are timetable *projections*
(state PROJECTED); plans built on them are PLANNING_ONLY (rehearsal). A live
feed replaces the projection; a stale live feed fails closed to HOLD.
"""

from __future__ import annotations

import heapq
import sqlite3
import statistics
import threading
from bisect import bisect_left, bisect_right, insort
from collections import defaultdict
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

from india_rail.ingest import DB_PATH
from india_rail.network import DEFAULT_PRIORITY, UNKNOWN_PRIORITY, clock
from india_rail.railguard import scoring
from india_rail.railguard.audit import AuditLog
from india_rail.railguard.evidence import AGING, FRESH, STALE, EvidenceStore, checksum
from india_rail.railguard.model import AUTHORITY, CAB_FOOTER, Network, Section
from india_rail.railguard.stress import restart_energy, section_energy, section_stress
from india_rail.railguard.threats import ACKNOWLEDGED, Threat, ThreatRegistry, _threat

DETOUR_FACTOR = 1.03  # published train distance / summed straight-line distance (median of 5,187 trains)
FALLBACK_SPEED_KMPH = 45.0  # for the few sections without station coordinates
MIN_DWELL_MIN = 2.0
WINDOW_MIN = 2880  # the twin covers two days of departures from 00:00 day 0
HORIZON_MIN = 240.0  # conflicts are checked this far ahead
# A pair of occupations is in the horizon if either starts inside it, so scans run this much further
# (longest plausible section occupation plus separation) to see pairs from both sides alike.
HORIZON_SCAN_MARGIN_MIN = 150.0
HOLD_STEPS = (3, 5, 8, 12, 15, 20, 30, 45, 60)
YIELD_STEPS = (2, 4, 6, 8, 10, 15, 20, 30)
MAX_YIELDS = 10
MAX_CASCADE = 30  # runs a priority path may re-path
NATIONAL_DELAY_SCALE_MIN = 180.0
DELAY_WEIGHT = {1: 1.5, 2: 1.3, 3: 1.0, 4: 0.8, 5: 0.5}
# Type defaults: (max speed km/h, axle load t, train mass t). Assumptions, not consist data.
TYPE_PROFILE = {
    "Raj": (130, 17.0, 900),
    "Shtb": (130, 17.0, 700),
    "Drnt": (130, 17.0, 900),
    "SKr": (130, 17.0, 900),
    "JShtb": (110, 17.0, 700),
    "GR": (110, 17.0, 900),
    "Del": (110, 17.0, 900),
    "SF": (110, 20.3, 1100),
    "Mail": (110, 20.3, 1100),
    "Exp": (110, 20.3, 1100),
    "Pass": (80, 20.3, 800),
    "MEMU": (100, 17.0, 600),
    "DEMU": (100, 17.0, 600),
    "Hyd": (100, 17.0, 500),
    "Toy": (25, 10.0, 100),
}
DEFAULT_PROFILE = (100, 20.3, 900)


@dataclass(slots=True)
class Run:
    """One train number on one start day, with its scheduled occupations (immutable once built)."""

    key: str
    number: str
    name: str
    type: str
    priority: int
    delay_weight: float
    vmax_kmph: float
    axle_load_t: float
    mass_t: float
    sections: tuple[str, ...]
    frm: tuple[str, ...]
    to: tuple[str, ...]
    s_enter: tuple[float, ...]
    s_exit: tuple[float, ...]


@dataclass(slots=True)
class Plan:
    """A run's current plan. `s_enter`/`s_exit` hold the timetable times (None on unplanned detours)."""

    sections: list[str]
    frm: list[str]
    to: list[str]
    enter: list[float]
    exit: list[float]
    s_enter: list[float | None]
    s_exit: list[float | None]
    prefix: int  # indexes below this are identical to the run's timetable (index entries stay valid)
    sources: dict[int, float] = field(default_factory=dict)  # extra minutes added at departure from frm[i]
    note: str = ""


# ---- static data ---------------------------------------------------------------------------
@dataclass(slots=True)
class SectionOccupancy:
    """Timetabled occupations of one section, sorted by scheduled entry, as parallel arrays."""

    keys: list[str]
    idx: list[int]
    enter: list[float]
    exit: list[float]
    frm: list[str]
    max_duration: float


@dataclass
class NationalData:
    network: Network
    runs: dict[str, Run]
    occupancy: dict[str, SectionOccupancy]
    stats: dict[str, Any]
    checksum: str
    # Stations with no scheduled halt, placed on the section they lie along: section -> [(code, fraction)]
    passing_points: dict[str, list[tuple[str, float]]] = field(default_factory=dict)


def _section_id(a: str, b: str) -> str:
    return f"{a}-{b}" if a < b else f"{b}-{a}"


def build_national(db_path: Path = DB_PATH) -> NationalData:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    stations = {code: (lat, lon) for code, lat, lon in con.execute("SELECT code, lat, lon FROM stations")}
    official_km = _official_section_km(con)
    trains = {row[0]: row[1:] for row in con.execute("SELECT number, name, type FROM trains")}
    rows = con.execute(
        "SELECT train_number, seq, from_code, to_code, dep_min, arr_min, runtime_min, crow_km "
        "FROM sections ORDER BY train_number, seq"
    ).fetchall()
    con.close()

    sections, by_train, inferred_multi = _build_sections(rows, official_km)
    nodes_used = {n for sid in sections for n in sid.split("-", 1)}
    neighbours: dict[str, set[str]] = defaultdict(set)
    for sid in sections:
        a, b = sid.split("-", 1)
        neighbours[a].add(b)
        neighbours[b].add(a)
    network = Network(nodes=_place_nodes(stations, nodes_used, neighbours), sections=sections)
    runs, index = _build_runs(by_train, trains)
    occupancy = _build_occupancy(runs, index)

    own = {n for n in nodes_used if stations.get(n, (None,))[0] is not None}
    passing, unplaced = _place_passing_points(stations, nodes_used, sections, network.nodes, own)
    stats = {
        "stations_total": len(stations),
        "stations": len(nodes_used),
        "stations_without_halt_placed_on_sections": sum(len(v) for v in passing.values()),
        "stations_without_halt_not_placed": unplaced,
        "sections_official_length": sum(1 for s in sections.values() if "OFFICIAL" in s.data_quality),
        "sections": len(sections),
        "junctions": sum(1 for v in neighbours.values() if len(v) >= 3),
        "sections_inferred_multi_track": inferred_multi,
        "sections_assumed_single": len(sections) - inferred_multi,
        "stations_placed_from_neighbours": len(nodes_used - own),
        "train_numbers": len(by_train),
        "runs_in_window": len(runs),
        "occupations": sum(len(v) for v in index.values()),
    }
    digest = checksum(
        {
            "sections": [(s.id, s.length_km, s.vmax_kmph, s.tracks) for s in sections.values()],
            "runs": [(r.key, r.sections, r.s_enter) for r in runs.values()],
        }
    )
    return NationalData(network, runs, occupancy, stats, digest, passing)


def _build_sections(rows: list[tuple], official_km: dict[str, float]) -> tuple[dict[str, Section], dict, int]:
    """Sections between consecutive stops, with every attribute inferred from the timetable and labelled."""

    crow: dict[str, float] = {}
    runtimes: dict[str, list[int]] = defaultdict(list)
    occupations: dict[str, list[tuple[float, float, bool]]] = defaultdict(list)
    users: dict[str, set[str]] = defaultdict(set)
    by_train: dict[str, list[tuple]] = defaultdict(list)
    for number, _seq, a, b, dep, arr, runtime, crow_km in rows:
        sid = _section_id(a, b)
        if crow_km is not None:
            crow[sid] = crow_km
        if runtime > 0:
            runtimes[sid].append(runtime)
        occupations[sid].append((dep % 1440, dep % 1440 + (arr - dep), a < b))
        users[sid].add(number)
        by_train[number].append((sid, a, b, float(dep), float(arr)))

    sections: dict[str, Section] = {}
    inferred_multi = 0
    for sid in sorted(users):
        a, b = sid.split("-", 1)
        if sid in official_km:
            length, length_src = max(official_km[sid], 0.2), "OFFICIAL_TIMETABLE_KM"
        elif sid in crow:
            length, length_src = max(crow[sid] * DETOUR_FACTOR, 0.2), "CROW_X1.03"
        else:
            minutes = statistics.median(runtimes[sid]) if runtimes[sid] else 3
            length, length_src = minutes / 60 * FALLBACK_SPEED_KMPH, "RUNTIME_X45KMPH"
        fastest = min(runtimes[sid]) if runtimes[sid] else None
        vmax = min(max(length / fastest * 60, 20.0), 130.0) if fastest else 100.0
        multi = _opposing_overlap(occupations[sid])
        inferred_multi += multi
        sections[sid] = Section(
            sid,
            a,
            b,
            round(length, 2),
            round(vmax, 1),
            2 if multi else 1,
            utilisation=float(len(users[sid])),
            condition=0.9,
            data_quality=(
                f"length:{length_src}|speed:{'TIMETABLE_FASTEST' if fastest else 'DEFAULT'}|"
                f"tracks:{'INFERRED_MULTI_FROM_TIMETABLE' if multi else 'ASSUMED_SINGLE_NO_EVIDENCE'}|"
                "condition:NO_FEED_DEFAULT"
            ),
        )
    return sections, by_train, inferred_multi


def _place_nodes(
    stations: dict[str, tuple[float | None, float | None]], nodes_used: set[str], neighbours: dict[str, set[str]]
) -> dict[str, tuple[float, float]]:
    """Station coordinates as (lon, lat); stations without coordinates sit at the mean of placed neighbours."""

    coords = {n: (stations[n][1], stations[n][0]) for n in nodes_used if stations.get(n, (None,))[0] is not None}
    for _ in range(6):
        for n in nodes_used - coords.keys():
            placed = [coords[m] for m in neighbours[n] if m in coords]
            if placed:
                coords[n] = (sum(p[0] for p in placed) / len(placed), sum(p[1] for p in placed) / len(placed))
    for n in nodes_used - coords.keys():
        coords[n] = (78.9, 22.0)  # unconnected to any placed station: centre of India, counted in the stats
    return {n: (round(lon, 5), round(lat, 5)) for n, (lon, lat) in coords.items()}


def _build_runs(by_train: dict[str, list[tuple]], trains: dict[str, tuple]) -> tuple[dict[str, Run], dict]:
    """One run per train number and start day that touches the two-day window."""

    runs: dict[str, Run] = {}
    index: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for number, legs in by_train.items():
        name, ttype = trains.get(number, (number, ""))
        ttype = ttype or ""
        vmax, axle, mass = TYPE_PROFILE.get(ttype, DEFAULT_PROFILE)
        priority = DEFAULT_PRIORITY.get(ttype, UNKNOWN_PRIORITY)
        for day in (0, -1, -2, -3):
            off = day * 1440
            if legs[-1][4] + off < 0 or legs[0][3] + off > WINDOW_MIN:
                continue
            key = f"{number}@{day}"
            runs[key] = Run(
                key,
                number,
                name or number,
                ttype,
                priority,
                DELAY_WEIGHT.get(priority, 1.0),
                vmax,
                axle,
                mass,
                tuple(leg[0] for leg in legs),
                tuple(leg[1] for leg in legs),
                tuple(leg[2] for leg in legs),
                tuple(leg[3] + off for leg in legs),
                tuple(leg[4] + off for leg in legs),
            )
            for i, sid in enumerate(runs[key].sections):
                index[sid].append((key, i))
    return runs, index


def _build_occupancy(runs: dict[str, Run], index: dict[str, list[tuple[str, int]]]) -> dict[str, SectionOccupancy]:
    occupancy = {}
    for sid, entries in index.items():
        entries.sort(key=lambda e: runs[e[0]].s_enter[e[1]])
        rows_ = [(k, i, runs[k].s_enter[i], runs[k].s_exit[i], runs[k].frm[i]) for k, i in entries]
        occupancy[sid] = SectionOccupancy(
            [r[0] for r in rows_],
            [r[1] for r in rows_],
            [r[2] for r in rows_],
            [r[3] for r in rows_],
            [r[4] for r in rows_],
            max((r[3] - r[2] for r in rows_), default=0.0),
        )
    return occupancy


PASSING_MAX_OFFSET_KM = 2.0  # a station further than this from every section line is not placed


def _official_section_km(con: sqlite3.Connection) -> dict[str, float]:
    """Section lengths from the official timetable's cumulative distances, if that file has been ingested."""

    try:
        rows = con.execute("SELECT edge, km FROM official_section_km").fetchall()
    except sqlite3.OperationalError:
        return {}
    return {edge: float(km) for edge, km in rows if km and km > 0}


def _place_passing_points(
    stations: dict[str, tuple[float | None, float | None]],
    halts: set[str],
    sections: dict[str, Section],
    nodes: dict[str, tuple[float, float]],
    located: set[str],
) -> tuple[dict[str, list[tuple[str, float]]], int]:
    """Put each station that no train stops at onto the section line it lies along (inferred from coordinates).

    Only sections whose two ends have their own coordinates are used, and a station must project inside the
    section, within PASSING_MAX_OFFSET_KM of it. Returns (section -> [(code, fraction)], stations not placed).
    """

    import numpy as np

    candidates = [(c, lat, lon) for c, (lat, lon) in stations.items() if c not in halts and lat is not None]
    usable = [s for s in sections.values() if s.a in located and s.b in located]
    if not candidates or not usable:
        return {}, len([c for c in stations if c not in halts])
    kx, ky = 111.32 * np.cos(np.radians(22.0)), 110.57  # km per degree near India's centre
    ax = np.array([nodes[s.a][0] for s in usable]) * kx
    ay = np.array([nodes[s.a][1] for s in usable]) * ky
    dx = np.array([nodes[s.b][0] for s in usable]) * kx - ax
    dy = np.array([nodes[s.b][1] for s in usable]) * ky - ay
    seg2 = np.maximum(dx * dx + dy * dy, 1e-9)
    placed: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for code, lat, lon in candidates:
        px, py = lon * kx, lat * ky
        t = ((px - ax) * dx + (py - ay) * dy) / seg2
        dist = np.hypot(ax + t * dx - px, ay + t * dy - py)
        dist[(t <= 0.02) | (t >= 0.98) | (seg2 < 0.25)] = np.inf
        best = int(np.argmin(dist))
        if dist[best] <= PASSING_MAX_OFFSET_KM:
            placed[usable[best].id].append((code, round(float(t[best]), 3)))
    for points in placed.values():
        points.sort(key=lambda p: p[1])
    not_placed = len([c for c in stations if c not in halts]) - sum(len(v) for v in placed.values())
    return dict(placed), not_placed


def _opposing_overlap(occ: list[tuple[float, float, bool]]) -> bool:
    """True if the timetable has opposing trains on the section at the same time (so >= 2 tracks)."""

    up = sorted((s, e) for s, e, d in occ if d and e > s)
    down = sorted((s, e) for s, e, d in occ if not d and e > s)
    i = j = 0
    while i < len(up) and j < len(down):
        (s1, e1), (s2, e2) = up[i], down[j]
        if s1 < e2 and s2 < e1:
            return True
        if e1 < e2:
            i += 1
        else:
            j += 1
    return False


@lru_cache(maxsize=1)
def national_data() -> NationalData:
    return build_national()


def gap(tracks: int, same_direction: bool, ae: float, ax: float, be: float, bx: float) -> float | None:
    """Separation in minutes between two occupations of one section (negative = overlap/overtake).

    Single line: any two occupations conflict. Multi-track: only same-direction moves
    (headway or overtake on plain line) conflict; opposing moves use separate tracks.
    """

    if tracks == 1:
        return max(be - ax, ae - bx)
    if not same_direction:
        return None
    if (ae - be) * (ax - bx) < 0:
        return -1.0
    return min(abs(ae - be), abs(ax - bx))


# ---- the dynamic twin ---------------------------------------------------------------------------
class NationalTwin:
    def __init__(self, data: NationalData | None = None, start_min: float = 480.0, headway: float = 3.0):
        self.data = data or national_data()
        self.net = self.data.network
        self.runs = self.data.runs
        self.headway = headway
        self.lock = threading.RLock()
        self.start_min = start_min
        self.reset()

    # ---- state ----------------------------------------------------------------------------
    def reset(self) -> None:
        self.now = self.start_min
        self.version = 0  # bumped by every state change; an approval must match the version it was ranked on
        self.plans: dict[str, Plan] = {}  # changed runs only
        self.changed_index: dict[str, list[tuple[str, int]]] = defaultdict(list)  # occupations of changed runs
        self.section_overrides: dict[str, Section] = {}
        self.evidence = EvidenceStore()  # live-feed positions only; absence = PROJECTED
        self.threats = ThreatRegistry()
        self.audit = AuditLog()
        self.flags: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.pending: dict[str, dict[str, Any]] = {}  # disrupted runs awaiting a controller decision
        self.approved: dict[str, dict[str, Any]] = {}
        self.latest: dict[str, Any] | None = None
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}
        self.weights = dict(scoring.PRESETS["BALANCED"])
        self.preset = "BALANCED"
        self.audit.record(
            int(self.now * 60),
            "NATIONAL_TWIN_INITIALISED",
            "system",
            {"data_checksum": self.data.checksum, **self.data.stats},
        )

    def section(self, sid: str) -> Section:
        return self.section_overrides.get(sid) or self.net.sections[sid]

    def plan_of(self, key: str) -> Plan:
        plan = self.plans.get(key)
        if plan is None:
            run = self.runs[key]
            plan = Plan(
                list(run.sections),
                list(run.frm),
                list(run.to),
                list(run.s_enter),
                list(run.s_exit),
                list(run.s_enter),
                list(run.s_exit),
                len(run.sections),
            )
        return plan

    def occupants(
        self,
        sid: str,
        lo: float,
        hi: float,
        exclude: frozenset[str] = frozenset(),
        overrides: dict[str, Plan] | None = None,
    ):
        """Occupations of `sid` that may overlap [lo, hi]: (run, index, enter, exit, from, s_enter, s_exit).

        Timetabled runs come from the sorted static arrays (binary-searched window);
        changed runs and trial overrides come from their current plans.
        """

        overrides = overrides or {}
        occ = self.data.occupancy.get(sid)
        if occ is not None:
            for n in range(bisect_left(occ.enter, lo - occ.max_duration), bisect_right(occ.enter, hi)):
                key = occ.keys[n]
                if key in self.plans or key in overrides or key in exclude:
                    continue
                yield key, occ.idx[n], occ.enter[n], occ.exit[n], occ.frm[n], occ.enter[n], occ.exit[n]
        for key, j in self.changed_index.get(sid, ()):
            if key not in overrides and key not in exclude:
                p = self.plans[key]
                yield key, j, p.enter[j], p.exit[j], p.frm[j], p.s_enter[j], p.s_exit[j]
        for key, p in overrides.items():
            if key not in exclude:
                for j, other_sid in enumerate(p.sections):
                    if other_sid == sid:
                        yield key, j, p.enter[j], p.exit[j], p.frm[j], p.s_enter[j], p.s_exit[j]

    # ---- timelines --------------------------------------------------------------------------
    @staticmethod
    def propagate(plan: Plan, extra: dict[int, float]) -> Plan:
        """Add delays (minutes at departure from frm[i]) on top of the current plan.

        A delay carries forward and is recovered only from dwell above 2 minutes,
        so composing a disruption, a hold and a yield never double-counts.
        """

        enter, exit_ = list(plan.enter), list(plan.exit)
        start, last = min(extra), max(extra)
        delay = 0.0
        for i in range(start, len(enter)):
            if i > start and delay > 0:
                delay = max(delay - max(plan.enter[i] - plan.exit[i - 1] - MIN_DWELL_MIN, 0.0), 0.0)
            delay += extra.get(i, 0.0)
            if delay <= 0 and i > last:
                break
            enter[i] += delay
            exit_[i] += delay
        sources = dict(plan.sources)
        for i, v in extra.items():
            sources[i] = sources.get(i, 0.0) + v
        return replace(plan, enter=enter, exit=exit_, sources=sources)

    def conflicts(
        self,
        key: str,
        plan: Plan,
        start: int,
        ignore: frozenset[str] = frozenset(),
        overrides: dict[str, Plan] | None = None,
    ) -> list[dict[str, Any]]:
        """Occupation conflicts and near misses of `plan` (from index `start`) against every other run."""

        found = []
        h = self.headway
        overrides = overrides or {}
        limit = self.now + HORIZON_MIN
        exclude = frozenset(ignore | {key})
        for i in range(start, len(plan.sections)):
            e, x = plan.enter[i], plan.exit[i]
            if e > limit + HORIZON_SCAN_MARGIN_MIN:
                break
            if x < self.now:
                continue
            sid, frm = plan.sections[i], plan.frm[i]
            tracks = self.section(sid).tracks
            for okey, j, oe, ox, ofrm, ose, osx in self.occupants(sid, e - 2 * h, x + 2 * h, exclude, overrides):
                if ox + 2 * h < e or oe - 2 * h > x or min(e, oe) > limit:
                    continue
                same = ofrm == frm
                g = gap(tracks, same, e, x, oe, ox)
                if g is None or g >= 2 * h:
                    continue
                se, sx = plan.s_enter[i], plan.s_exit[i]
                planned = gap(tracks, same, se, sx, ose, osx) if None not in (se, sx, ose, osx) else None
                required = h if planned is None else min(h, planned)
                found.append(
                    {
                        "section_id": sid,
                        "index": i,
                        "other": okey,
                        "other_index": j,
                        "gap_min": round(g, 2),
                        "required_min": round(required, 2),
                        "is_conflict": g < required - 1e-6,
                        "opposing": not same,
                        "single_line": tracks == 1,
                    }
                )
        return found

    # ---- positions ---------------------------------------------------------------------------
    def position(self, key: str, t: float | None = None) -> dict[str, Any]:
        t = self.now if t is None else t
        plan = self.plans.get(key)
        enter = plan.enter if plan else self.runs[key].s_enter
        exit_ = plan.exit if plan else self.runs[key].s_exit
        sections = plan.sections if plan else self.runs[key].sections
        frm, to = (plan.frm, plan.to) if plan else (self.runs[key].frm, self.runs[key].to)
        i = bisect_right(enter, t) - 1
        if i < 0:
            return {"state": "NOT_STARTED", "node": frm[0], "section_id": None, "index": 0, "speed_kmph": 0.0}
        if t < exit_[i]:
            length = self.section(sections[i]).length_km
            run_min = max(exit_[i] - enter[i], 1e-6)
            return {
                "state": "RUNNING",
                "section_id": sections[i],
                "from_node": frm[i],
                "to_node": to[i],
                "offset_km": round(length * (t - enter[i]) / run_min, 3),
                "index": i,
                "speed_kmph": round(length / run_min * 60, 1),
            }
        if i == len(sections) - 1:
            return {"state": "ARRIVED", "node": to[i], "section_id": None, "index": i, "speed_kmph": 0.0}
        return {"state": "AT_STATION", "node": to[i], "section_id": None, "index": i + 1, "speed_kmph": 0.0}

    def first_open(self, key: str) -> int:
        """First section index whose entry can still be planned (a running train's current section is fixed)."""

        pos = self.position(key)
        return pos["index"] + 1 if pos["state"] == "RUNNING" and pos["offset_km"] > 0 else pos["index"]

    def running(self) -> list[str]:
        out = []
        for key, run in self.runs.items():
            plan = self.plans.get(key)
            first = plan.enter[0] if plan else run.s_enter[0]
            last = plan.exit[-1] if plan else run.s_exit[-1]
            if first <= self.now < last:
                out.append(key)
        return out

    def position_state(self, key: str) -> str:
        if f"position:{key}" not in self.evidence.records:
            return "PROJECTED"
        return self.evidence.state_of(f"position:{key}", int(self.now * 60))

    # ---- disruption, candidates and recommendation ------------------------------------------------
    def disrupt(
        self, key: str, station: str, delay_min: float, actor: str = "controller", at_index: int | None = None
    ) -> dict[str, Any]:
        """Record that `key` will leave `station` late. Its timeline changes now; others wait for a decision.

        `at_index` pins the stop when a live observation says where the train really is (the projection may
        already have it past that station).
        """

        with self.lock:
            if key not in self.runs:
                raise KeyError(f"Unknown train run {key}")
            if not 1 <= delay_min <= 720:
                raise ValueError("delay_min must be 1-720")
            plan = self.plan_of(key)
            first = self.first_open(key) if at_index is None else at_index
            candidates = [i for i in range(first, len(plan.sections)) if plan.frm[i] == station.upper()]
            if not candidates:
                raise ValueError(f"{key} has no departure from {station} ahead of its current position")
            k = candidates[0]
            self._set_plan(key, self.propagate(plan, {k: float(delay_min)}))
            self.pending[key] = {"index": k, "station": station.upper(), "delay_min": float(delay_min)}
            self.audit.record(
                int(self.now * 60),
                "DISRUPTION_RECORDED",
                actor,
                {"run": key, "station": station.upper(), "delay_min": delay_min},
            )
            self.refresh()
            return {
                "run": key,
                "index": k,
                "conflicts": [c for c in self.conflicts(key, self.plans[key], k) if c["is_conflict"]],
            }

    def _set_plan(self, key: str, plan: Plan) -> None:
        old = self.plans.get(key)
        if old is not None:
            for i, sid in enumerate(old.sections):
                self.changed_index[sid].remove((key, i))
        self.plans[key] = plan
        for i, sid in enumerate(plan.sections):
            # Kept sorted, so conflict search (and therefore ranking) never depends on the order of decisions.
            insort(self.changed_index[sid], (key, i))

    def _violations(self, plan: Plan, start: int, run: Run) -> list[str]:
        out = []
        for sid in plan.sections[start:]:
            sec = self.section(sid)
            if not sec.available:
                out.append(f"{sid} closed")
            if sec.obstacle:
                out.append(f"{sid} obstacle pending inspection")
            if run.axle_load_t > sec.axle_limit_t:
                out.append(f"{sid} axle limit")
        return out

    def _detours(self, key: str, plan: Plan, start: int, f: int, banned: set[str]) -> list[Plan]:
        """Local bypasses around section f: leave at frm[f] or one of the two previous junctions, rejoin within
        15 sections downstream. Dijkstra on train-specific running time, bounded by 2.5x the replaced segment."""

        run, adj = self.runs[key], self.net.adjacency
        rejoin = {plan.to[g]: g for g in range(f, min(f + 15, len(plan.sections)))}
        junctions = [i for i in range(f - 1, max(start, f - 6) - 1, -1) if len(adj[plan.frm[i]]) >= 3][:2]
        out: list[Plan] = []
        for s in [f, *junctions]:
            origin = plan.frm[s]
            budget = max((plan.exit[min(f + 14, len(plan.sections) - 1)] - plan.enter[s]) * 2.5, 30.0)
            best: dict[str, tuple[float, list[str]]] = {origin: (0.0, [])}
            heap = [(0.0, origin)]
            while heap:
                cost, node = heapq.heappop(heap)
                if cost > budget or cost > best[node][0]:
                    continue
                for sid in adj[node]:
                    sec = self.section(sid)
                    if sid in banned or not sec.available or sec.obstacle or run.axle_load_t > sec.axle_limit_t:
                        continue
                    nxt, nc = sec.other(node), cost + sec.length_km / min(run.vmax_kmph, sec.vmax_kmph) * 60
                    if nc < best.get(nxt, (1e18,))[0]:
                        best[nxt] = (nc, best[node][1] + [sid])
                        heapq.heappush(heap, (nc, nxt))
            options = sorted(
                (best[node][0] + plan.exit[-1] - plan.exit[g], g, best[node][1])
                for node, g in rejoin.items()
                if node in best and best[node][1] and best[node][1] != plan.sections[s : g + 1]
            )
            if options:
                out.append(self._splice(key, plan, s, options[0][1], options[0][2]))
        return out

    def _splice(self, key: str, plan: Plan, s: int, g: int, route: list[str]) -> Plan:
        """Replace sections s..g with `route`; the suffix keeps timetable times, carrying any lateness forward."""

        run = self.runs[key]
        sections, frm, to = list(plan.sections[:s]), list(plan.frm[:s]), list(plan.to[:s])
        enter, exit_ = list(plan.enter[:s]), list(plan.exit[:s])
        se, sx = list(plan.s_enter[:s]), list(plan.s_exit[:s])
        t, node = plan.enter[s], plan.frm[s]
        for sid in route:
            sec = self.section(sid)
            run_min = sec.length_km / min(run.vmax_kmph, sec.vmax_kmph) * 60
            sections.append(sid)
            frm.append(node)
            node = sec.other(node)
            to.append(node)
            enter.append(t)
            exit_.append(t + run_min)
            se.append(None)
            sx.append(None)
            t += run_min
        delay = max(t - plan.exit[g], 0.0)
        for i in range(g + 1, len(plan.sections)):
            if delay > 0 and i > g + 1:
                delay = max(delay - max(plan.enter[i] - plan.exit[i - 1] - MIN_DWELL_MIN, 0.0), 0.0)
            sections.append(plan.sections[i])
            frm.append(plan.frm[i])
            to.append(plan.to[i])
            enter.append(plan.enter[i] + delay)
            exit_.append(plan.exit[i] + delay)
            se.append(plan.s_enter[i])
            sx.append(plan.s_exit[i])
        return Plan(
            sections,
            frm,
            to,
            enter,
            exit_,
            se,
            sx,
            min(plan.prefix, s),
            dict(plan.sources),
            note=f"reroute {plan.frm[s]}->{plan.to[g]} via {len(route)} sections",
        )

    def _path_through(
        self,
        key: str,
        plan: Plan,
        start: int,
        overrides: dict[str, Plan] | None = None,
        max_priority: int | None = None,
    ) -> Plan | None:
        """Earliest conflict-free path against every other run, waiting at stations where needed.

        What a controller does for a late train in dense traffic: run it in the next
        free paths. Each section entry is pushed back until the required separation
        from every other occupation holds; returns None if that fails within the horizon.
        """

        h, n = self.headway, len(plan.sections)
        overrides = {k: v for k, v in (overrides or {}).items() if k != key}
        enter, exit_, sources = list(plan.enter), list(plan.exit), dict(plan.sources)
        exclude, limit, extra = frozenset({key}), self.now + HORIZON_MIN, 0.0
        for i in range(start, n):
            if i > start and extra > 0:
                extra = max(extra - max(plan.enter[i] - plan.exit[i - 1] - MIN_DWELL_MIN, 0.0), 0.0)
            e, x = plan.enter[i] + extra, plan.exit[i] + extra
            if e <= self.now or e > limit + HORIZON_SCAN_MARGIN_MIN:
                enter[i], exit_[i] = e, x
                continue
            sid, frm, tracks = plan.sections[i], plan.frm[i], self.section(plan.sections[i]).tracks
            se, sx = plan.s_enter[i], plan.s_exit[i]
            for _attempt in range(30):
                need = 0.0
                for okey, _j, oe, ox, ofrm, ose, osx in self.occupants(sid, e - 2 * h, x + 2 * h, exclude, overrides):
                    if min(e, oe) > limit:
                        continue  # both beyond the horizon: planned when they come into view
                    if max_priority is not None and self.runs[okey].priority > max_priority:
                        continue  # lower-priority traffic will be re-pathed around this train
                    same = ofrm == frm
                    g = gap(tracks, same, e, x, oe, ox)
                    if g is None:
                        continue
                    planned = gap(tracks, same, se, sx, ose, osx) if None not in (se, sx, ose, osx) else None
                    required = h if planned is None else min(h, planned)
                    if g < required - 1e-6:
                        # Follow the other train: enter after it clears (single line) or keep headway
                        # without overtaking (multi-track, same direction).
                        shift = ox + required - e if tracks == 1 else max(oe + required - e, ox + required - x)
                        need = max(need, shift)
                if need <= 1e-6:
                    break
                e, x, extra = e + need, x + need, extra + need
                sources[i] = sources.get(i, 0.0) + need
            else:
                return None
            enter[i], exit_[i] = e, x
        waits = sum(1 for i, v in sources.items() if i >= start and v > plan.sources.get(i, 0.0))
        total = sum(v - plan.sources.get(i, 0.0) for i, v in sources.items() if i >= start)
        return replace(
            plan,
            enter=enter,
            exit=exit_,
            sources=sources,
            note=f"path through: waits at {waits} stations ({total:.0f} min)",
        )

    def _priority_path(
        self, key: str, base: Plan, start: int, here: int
    ) -> tuple[Plan, dict[str, tuple[Plan, float]]] | None:
        """Path a train through equal/higher-priority traffic only, then re-path every lower-priority run it
        blocks (cascading, bounded). Returns the train's plan and the re-pathed runs, or None."""

        run = self.runs[key]
        pathed = self._path_through(key, base, start, max_priority=run.priority)
        if pathed is None:
            return None
        overrides: dict[str, Plan] = {key: pathed}
        queue = [c["other"] for c in self.conflicts(key, pathed, here, overrides=overrides) if c["is_conflict"]]
        steps = 0
        while queue:
            okey = queue.pop(0)
            steps += 1
            # Distinct runs are capped, and so are re-visits: two runs re-pathing around each other is no plan.
            if self.runs[okey].priority < run.priority or len(overrides) > MAX_CASCADE or steps > 4 * MAX_CASCADE:
                return None
            current = overrides.get(okey) or self.plan_of(okey)
            ostart = self.position(okey)["index"]
            repathed = self._path_through(okey, current, ostart, overrides)
            if repathed is None:
                return None
            overrides[okey] = repathed
            queue += [
                c["other"]
                for c in self.conflicts(okey, repathed, ostart, overrides=overrides)
                if c["is_conflict"] and c["other"] not in queue
            ]
        for k, p in overrides.items():  # independent re-check of the whole joint plan
            k_start = here if k == key else self.position(k)["index"]
            if any(c["is_conflict"] for c in self.conflicts(k, p, k_start, overrides=overrides)):
                return None
        yields = {
            k: (p, round(p.exit[-1] - self.plan_of(k).exit[-1], 1))
            for k, p in overrides.items()
            if k != key and p.enter != self.plan_of(k).enter  # only runs whose timings actually change
        }
        # The cascade may have re-pathed this train again; return the plan the re-check above validated.
        return overrides[key], yields

    def _yield(
        self, okey: str, oindex: int, protected: Plan, pkey: str, overrides: dict[str, Plan], buffer: float
    ) -> tuple[Plan, float] | None:
        """Smallest hold of another run before section `oindex` that restores separation (plus `buffer`
        minutes from the protected train) without creating new conflicts."""

        base = overrides.get(okey) or self.plan_of(okey)
        if base.enter[oindex] <= self.now:
            return None  # already entered the section: it can no longer be held before it
        for hold in YIELD_STEPS:
            trial = self.propagate(base, {oindex: float(hold)})
            found = self.conflicts(okey, trial, oindex, overrides={**overrides, pkey: protected, okey: trial})
            if not any(
                c["is_conflict"] or (c["other"] == pkey and c["gap_min"] < c["required_min"] + buffer) for c in found
            ):
                return trial, float(hold)
        return None

    def _resolve(self, key: str, plan: Plan, start: int, buffer: float) -> tuple[dict, list] | str:
        """Make lower-priority runs yield to `plan`. Returns (yields, pairs) or the reason it is impossible."""

        run = self.runs[key]
        yields: dict[str, tuple[Plan, float]] = {}
        for c in [c for c in self.conflicts(key, plan, start) if c["is_conflict"]]:
            if c["other"] in yields:
                continue
            if self.runs[c["other"]].priority < run.priority or len(yields) >= MAX_YIELDS:
                return f"conflict with {c['other']} on {c['section_id']}"
            result = self._yield(c["other"], c["other_index"], plan, key, {k: v[0] for k, v in yields.items()}, buffer)
            if result is None:
                return f"{c['other']} cannot yield before {c['section_id']}"
            yields[c["other"]] = result
        found = self.conflicts(key, plan, start, overrides={k: v[0] for k, v in yields.items()})
        if any(c["is_conflict"] for c in found):
            return "residual conflict after yields"
        return yields, found

    def candidates(self, key: str, start: int) -> list[dict[str, Any]]:
        """Generate controller alternatives for a disrupted run, from index `start` onwards."""

        run = self.runs[key]
        base = self.plan_of(key)
        here = self.position(key)["index"]  # conflicts count from the occupied section: others may need to wait
        options: list[tuple[str, Plan, int]] = [("CONTINUE", base, 0)]
        first = next((c for c in self.conflicts(key, base, here) if c["is_conflict"]), None)
        if first is not None and base.enter[first["index"]] > self.now:
            f = first["index"]
            for hold in HOLD_STEPS:
                options.append((f"HOLD {hold} min at {base.frm[f]}", self.propagate(base, {f: float(hold)}), 1))
        priority_option = self._priority_path(key, base, start, here) if first is not None else None
        if first is not None:
            pathed = self._path_through(key, base, start)
            if pathed is not None:
                waits = sum(1 for i, v in pathed.sources.items() if v > base.sources.get(i, 0.0))
                options.append((f"PATH {pathed.note}", pathed, waits))
        banned = {first["section_id"]} if first and first["index"] >= start else set()
        banned |= {
            sid for sid in base.sections[start:] if not self.section(sid).available or self.section(sid).obstacle
        }
        if banned:
            bad = min(i for i in range(start, len(base.sections)) if base.sections[i] in banned)
            for detour in self._detours(key, base, start, bad, banned):
                options.append((f"REROUTE {detour.note}", detour, 0))
        out = []
        for label, plan, holds in options:
            violations = self._violations(plan, start, run)
            if violations:
                out.append({"label": label, "feasible": False, "reasons": violations})
                continue
            buffers = (0.0, self.headway) if any(c["is_conflict"] for c in self.conflicts(key, plan, here)) else (0.0,)
            for buffer in buffers:
                resolved = self._resolve(key, plan, here, buffer)
                if isinstance(resolved, str):
                    if buffer == 0.0:
                        out.append({"label": label, "feasible": False, "reasons": [resolved]})
                    continue
                yields, found = resolved
                text = label
                if yields:
                    text += "; " + ", ".join(f"{k} yields {h:g} min" for k, (_p, h) in yields.items())
                    text += " (with buffer)" if buffer else ""
                out.append(
                    {"label": text, "feasible": True, "plan": plan, "yields": yields, "pairs": found, "holds": holds}
                )
        if priority_option is not None:
            plan, yields = priority_option
            overrides = {k: v[0] for k, v in yields.items()}
            waits = sum(1 for i, v in plan.sources.items() if v > base.sources.get(i, 0.0))
            out.append(
                {
                    "label": f"PRIORITY path, {len(yields)} lower-priority trains re-pathed",
                    "feasible": True,
                    "plan": plan,
                    "yields": yields,
                    "holds": waits,
                    "pairs": self.conflicts(key, plan, here, overrides=overrides),
                }
            )
        # Every option must avoid closed, obstructed or axle-limited sections (yields only re-time other trains
        # on their unchanged routes, so they cannot add such a section).
        for cand in out:
            if cand["feasible"] and (reasons := self._violations(cand["plan"], start, run)):
                cand.update(feasible=False, reasons=reasons)
        return out

    def _raw(self, key: str, start: int, cand: dict[str, Any]) -> dict[str, float]:
        run, plan = self.runs[key], cand["plan"]
        h = self.headway
        final = lambda p, r: max(p.exit[-1] - r.s_exit[-1], 0.0)  # noqa: E731
        delay = run.delay_weight * final(plan, run)
        for okey, (oplan, _hold) in cand["yields"].items():
            orun = self.runs[okey]
            delay += orun.delay_weight * (final(oplan, orun) - final(self.plan_of(okey), orun))
        stress = energy = threat = 0.0
        for i in range(start, len(plan.sections)):
            sec = self.section(plan.sections[i])
            speed = min(run.vmax_kmph, sec.vmax_kmph)
            stress += section_stress(run, sec, speed)["stress"]
            energy += section_energy(run, sec, speed)
            threat += (
                (0.5 if sec.weather_alert else 0)
                + (0.25 if sec.temp_restriction_kmph else 0)
                + (0.25 if sec.condition < 0.5 else 0)
            )
        holds = cand["holds"]
        energy += restart_energy(run) * (holds + len(cand["yields"]))
        involved = [key, *cand["yields"]]
        penalty = {FRESH: 0.0, AGING: 0.5, "PROJECTED": 0.5}
        ev = [penalty.get(self.position_state(k), 1.0) for k in involved]
        rerouted = plan.prefix < len(plan.sections) and plan.note.startswith("reroute")
        return {
            "delay": delay,
            "conflict": sum(max(0.0, (2 * h - c["gap_min"]) / h) for c in cand["pairs"] if not c["is_conflict"]),
            "infra": stress,
            "energy": energy,
            "threat": threat,
            "evidence": sum(ev) / len(ev),
            "complexity": holds + len(cand["yields"]) + (1 if rerouted else 0),
        }

    def recommend(self, key: str | None = None, actor: str = "controller", top: int = 6) -> dict[str, Any]:
        with self.lock:
            key = key or next(iter(self.pending), None)
            if key is None:
                raise ValueError("No disrupted train to plan for: record a disruption first")
            # Plan from the first section the train can still change, not from the disruption station:
            # a closure or conflict before that station matters just as much.
            start = self.first_open(key)
            cands = self.candidates(key, start)
            feasible = [c for c in cands if c["feasible"]]
            involved = {key, *(k for c in feasible for k in c["yields"])}
            states = {self.position_state(k) for k in involved}
            involved_state = STALE if STALE in states else ("PROJECTED" if "PROJECTED" in states else FRESH)
            if not feasible:
                ranking: dict[str, Any] = {
                    "state": "NO_FEASIBLE_PLAN",
                    "candidates": [],
                    "rejected": [{"label": c["label"], "reasons": c["reasons"]} for c in cands],
                }
            else:
                scored = scoring.score(
                    [self._raw(key, start, c) for c in feasible], self.weights, NATIONAL_DELAY_SCALE_MIN
                )
                shown = scoring.rank(scored, top)
                ranking = {
                    "state": "RANKED",
                    "candidates": [],
                    "feasible_count": len(feasible),
                    "rejected": [{"label": c["label"], "reasons": c["reasons"]} for c in cands if not c["feasible"]],
                    "headway_min": self.headway,
                }
                for n, s in enumerate(shown, start=1):
                    cand = feasible[s["index"]]
                    plan = cand["plan"]
                    ranking["candidates"].append(
                        {
                            "candidate_id": f"N{n}",
                            "action": cand["label"].split(" ")[0] + ("+YIELD" if cand["yields"] else ""),
                            "summary": f"{key}: {cand['label']}",
                            **scoring.public(s),
                            "final_delay_min": round(max(plan.exit[-1] - self.runs[key].s_exit[-1], 0), 1),
                            "route_ahead": plan.sections[start : start + 25],
                            "yields": {k: h for k, (_p, h) in cand["yields"].items()},
                            "closest_separations": sorted(cand["pairs"], key=lambda c: c["gap_min"])[:3],
                        }
                    )
                self._cache = {
                    (key, c["candidate_id"]): feasible[s["index"]]
                    for c, s in zip(ranking["candidates"], shown, strict=True)
                }
            critical = [
                t
                for t in self.threats.active()
                if t.severity == "CRITICAL" and t.lifecycle == "OPEN" and key in t.train_ids
            ]
            if involved_state == STALE:
                state, reason = "HOLD", "Live position of an involved train is stale"
            elif ranking["state"] != "RANKED":
                state, reason = "NO_FEASIBLE_PLAN", "No conflict-free alternative within the planning options"
            elif critical:
                state, reason = "REVIEW", "Critical threat open: " + ", ".join(sorted({t.type for t in critical}))
            elif involved_state == "PROJECTED":
                state, reason = (
                    "PLANNING_ONLY",
                    (
                        "Positions are timetable projections (no authorised live feed): "
                        "approval rehearses the plan, it is not live operation"
                    ),
                )
            else:
                state, reason = "REVIEWABLE", "Live evidence fresh; alternatives ranked for controller review"
            dynamic = self.dynamic_state()
            inputs = {
                "data_checksum": self.data.checksum,
                "now": self.now,
                "run": key,
                "start": start,
                "weights": dict(self.weights),
                "headway": self.headway,
                "dynamic": dynamic,
            }
            snap = self.audit.add_snapshot(inputs, {"ranking": _strip(ranking), "state": state}, int(self.now * 60))
            self.latest = {
                "snapshot_id": snap["snapshot_id"],
                "checksum": snap["checksum"],
                "state": state,
                "now": self.now,
                "version": self.version,
                "reason": reason,
                "approvable": state in ("REVIEWABLE", "PLANNING_ONLY"),
                "run": key,
                "ranking": ranking,
                "preset": self.preset,
                "authority": AUTHORITY,
                "data_quality": "Network attributes inferred from the open timetable; see stats",
            }
            self.audit.record(
                int(self.now * 60),
                "RECOMMENDATION_ISSUED",
                actor,
                {"snapshot_id": snap["snapshot_id"], "state": state, "run": key},
            )
            return self.latest

    def approve(self, snapshot_id: str, candidate_id: str, controller: str) -> dict[str, Any]:
        with self.lock:
            if not controller:
                raise PermissionError("A named controller must approve")
            latest = self.latest
            if latest is None or latest["snapshot_id"] != snapshot_id or latest["version"] != self.version:
                raise ValueError("Recommendation superseded: re-rank, then approve the latest snapshot")
            if not latest["approvable"]:
                raise ValueError(f"Not approvable: {latest['state']} - {latest['reason']}")
            cand = self._cache.get((latest["run"], candidate_id))
            if cand is None:
                raise KeyError(candidate_id)
            key = latest["run"]
            self._set_plan(key, cand["plan"])
            for okey, (oplan, _hold) in cand["yields"].items():
                self._set_plan(okey, oplan)
            self.pending.pop(key, None)
            summary = next(c["summary"] for c in latest["ranking"]["candidates"] if c["candidate_id"] == candidate_id)
            for k in [key, *cand["yields"]]:
                self.approved[k] = {"snapshot_id": snapshot_id, "summary": summary, "by": controller}
            event = self.audit.record(
                int(self.now * 60),
                "PLAN_APPROVED",
                controller,
                {
                    "snapshot_id": snapshot_id,
                    "candidate": candidate_id,
                    "summary": summary,
                    "evidence_state": latest["state"],
                    "authority": AUTHORITY,
                },
            )
            self.refresh()
            return {
                "status": "APPROVED_FOR_" + ("REHEARSAL" if latest["state"] == "PLANNING_ONLY" else "DEMO"),
                "authority": AUTHORITY,
                "event_hash": event["hash"],
                "note": "Advisory plan approval. Not movement authority.",
            }

    def dynamic_state(self) -> dict[str, Any]:
        """Everything that differs from the static timetable (enough to reproduce a recommendation)."""

        return {
            "plans": {
                k: {
                    "sections": p.sections,
                    "frm": p.frm,
                    "to": p.to,
                    "enter": p.enter,
                    "exit": p.exit,
                    "s_enter": p.s_enter,
                    "s_exit": p.s_exit,
                    "prefix": p.prefix,
                    "note": p.note,
                    "sources": {str(i): v for i, v in sorted(p.sources.items())},
                }
                for k, p in sorted(self.plans.items())
            },
            "sections": {
                s: {
                    "condition": v.condition,
                    "available": v.available,
                    "obstacle": v.obstacle,
                    "temp_restriction_kmph": v.temp_restriction_kmph,
                    "weather_alert": v.weather_alert,
                }
                for s, v in sorted(self.section_overrides.items())
            },
            "pending": self.pending,
            "evidence": [r.to_dict() for _k, r in sorted(self.evidence.records.items())],
            "flags": {k: v for k, v in sorted(self.flags.items()) if v},
            "acknowledged": sorted(k for k, t in self.threats.threats.items() if t.lifecycle == ACKNOWLEDGED),
        }

    def replay(self, snapshot_id: str) -> dict[str, Any]:
        """Rebuild a twin from the snapshot's dynamic state and re-rank: the result must match."""

        snap = self.audit.snapshots[snapshot_id]
        inputs = snap["inputs"]
        twin = NationalTwin(self.data, inputs["now"], inputs["headway"])
        twin.weights = dict(inputs["weights"])
        twin.restore(inputs["dynamic"])
        rerun = twin.recommend(inputs["run"], actor="replay")
        return {
            "snapshot_id": snapshot_id,
            "integrity_ok": self.audit.verify_snapshot(snapshot_id),
            "data_matches": inputs["data_checksum"] == self.data.checksum,
            "replay_matches": checksum(_strip(rerun["ranking"])) == checksum(snap["outputs"]["ranking"])
            and rerun["state"] == snap["outputs"]["state"],
            "note": "Integrity and reproducibility of the record; not proof that the inputs were true.",
        }

    def restore(self, dynamic: dict[str, Any]) -> None:
        from india_rail.railguard.evidence import EvidenceRecord

        for key, p in dynamic["plans"].items():
            self._set_plan(
                key,
                Plan(
                    list(p["sections"]),
                    list(p["frm"]),
                    list(p["to"]),
                    list(p["enter"]),
                    list(p["exit"]),
                    list(p["s_enter"]),
                    list(p["s_exit"]),
                    p["prefix"],
                    {int(i): v for i, v in p["sources"].items()},
                    p["note"],
                ),
            )
        for sid, v in dynamic["sections"].items():
            self.section_overrides[sid] = replace(self.net.sections[sid], **v)
        self.pending = {k: dict(v) for k, v in dynamic["pending"].items()}
        for record in dynamic["evidence"]:
            self.evidence.records[record["key"]] = EvidenceRecord(**record)
        for key, flags in dynamic.get("flags", {}).items():
            self.flags[key] = [dict(f) for f in flags]
        self.refresh()  # threats are derived state: rebuild them, then re-apply the controller's acknowledgements
        for key in dynamic.get("acknowledged", []):
            if key in self.threats.threats:
                self.threats.threats[key].lifecycle = ACKNOWLEDGED

    # ---- section events, live feed and simulation ------------------------------------------------
    def update_section(self, sid: str, source: str = "TRACKSENSE_FEED", **changes: Any) -> Section:
        with self.lock:
            allowed = {"condition", "temp_restriction_kmph", "weather_alert", "obstacle", "available"}
            if set(changes) - allowed:
                raise ValueError(f"fields {sorted(set(changes) - allowed)} cannot be changed")
            self.section_overrides[sid] = replace(self.section(sid), **changes)
            self.audit.record(int(self.now * 60), "SECTION_UPDATED", source, {"section": sid, **changes})
            self.refresh()
            return self.section_overrides[sid]

    def ingest_position(
        self, key: str, section_id: str, offset_km: float, source: str = "AUTHORISED_FEED"
    ) -> dict[str, Any]:
        """A live observation (e.g. an authorised RTIS-style feed). Compared with the plan, never trusted blindly."""

        with self.lock:
            if key not in self.runs:
                return {"accepted": False, "reason": "unknown run"}
            plan = self.plan_of(key)
            if section_id not in plan.sections or not 0 <= offset_km <= self.section(section_id).length_km:
                self.flags[key].append({"type": "ROUTE_DEVIATION", "until": self.now + 5, "section": section_id})
                self.refresh()
                return {"accepted": False, "reason": "observation not on the planned route"}
            self.evidence.put(
                f"position:{key}",
                "POSITION",
                source,
                int(self.now * 60),
                {"section": section_id, "offset": offset_km},
                fresh_s=60,
                stale_s=180,
                mandatory=True,
            )
            self.refresh()
            return {"accepted": True}

    def tick(self, minutes: float = 1.0) -> None:
        with self.lock:
            self.now += max(float(minutes), 0.0)
            self.refresh()

    # ---- threats (scalable: O(changed runs + flagged sections + running runs)) -----------------------
    def refresh(self) -> None:
        self.version += 1
        self.threats.update(self._evaluate(), int(self.now * 60))

    def _evaluate(self) -> list[Threat]:
        found: list[Threat] = []
        for key in list(self.plans):
            plan = self.plans[key]
            start = self.position(key)["index"]
            seen = set()
            for c in self.conflicts(key, plan, start):
                if not c["is_conflict"] or (c["other"], c["section_id"]) in seen:
                    continue
                seen.add((c["other"], c["section_id"]))
                found.append(
                    _threat(
                        "CONVERGING_PATH",
                        "WARNING",
                        [key, c["other"]],
                        c["section_id"],
                        [f"plan:{key}", "timetable"],
                        0.5 if self.position_state(key) == "PROJECTED" else 1.0,
                        "Resequence, hold or reroute - see ranked alternatives.",
                        "Converging traffic - controller review",
                        f"Separation {c['gap_min']} min < required {c['required_min']} min on {c['section_id']}.",
                    )
                )
        for key in self.evidence.records:
            run_key = key.split(":", 1)[1]
            if self.evidence.state_of(key, int(self.now * 60)) == STALE:
                found.append(
                    _threat(
                        "STALE_POSITION",
                        "WARNING",
                        [run_key],
                        None,
                        [key],
                        0.2,
                        "Do not rely on this train's position; confirm through authorised means.",
                        "Position data stale - controller review",
                        "Live feed older than policy.",
                    )
                )
        for key, flags in self.flags.items():
            for flag in flags:
                if flag["until"] >= self.now:
                    found.append(
                        _threat(
                            flag["type"],
                            "WARNING",
                            [key],
                            flag.get("section"),
                            [f"feed:{key}"],
                            0.3,
                            "Re-plan: train observed outside its plan.",
                            "Off plan - controller review",
                            "Live observation not on the planned route.",
                        )
                    )
        flagged = {
            sid: sec
            for sid, sec in self.section_overrides.items()
            if sec.obstacle
            or not sec.available
            or sec.condition < 0.5
            or sec.weather_alert
            or sec.temp_restriction_kmph
        }
        for sid, sec in flagged.items():
            for key, _i, e, _x, *_rest in self.occupants(sid, self.now, self.now + 60):
                if not self.now <= e <= self.now + 60:
                    continue
                if sec.obstacle or not sec.available:
                    found.append(
                        _threat(
                            "OBSTACLE" if sec.obstacle else "SECTION_CLOSED",
                            "CRITICAL",
                            [key],
                            sid,
                            [f"condition:{sid}"],
                            1.0,
                            f"Re-plan {key} around {sid}.",
                            f"{sid} ahead blocked - expect controller instructions",
                            "Section blocked.",
                        )
                    )
                elif sec.condition < 0.5:
                    found.append(
                        _threat(
                            "INFRA_CAUTION",
                            "CAUTION",
                            [key],
                            sid,
                            [f"condition:{sid}"],
                            1.0,
                            "Consider the lower-stress alternative.",
                            f"Track caution on {sid}",
                            f"Condition {sec.condition:.2f}.",
                        )
                    )
                if sec.weather_alert:
                    found.append(
                        _threat(
                            "WEATHER",
                            "CAUTION",
                            [key],
                            sid,
                            [f"weather:{sid}"],
                            1.0,
                            "Check weather instructions.",
                            f"{sec.weather_alert} on {sid}",
                            "Weather.",
                        )
                    )
                if sec.temp_restriction_kmph:
                    found.append(
                        _threat(
                            "RESTRICTION_AHEAD",
                            "INFO",
                            [key],
                            sid,
                            [f"restriction:{sid}"],
                            1.0,
                            "Reflected in plan.",
                            f"{sec.temp_restriction_kmph:g} km/h on {sid}",
                            "Temporary restriction.",
                        )
                    )
        occupied: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for key in self.plans:  # timetabled runs cannot meet head-on (the timetable is feasible); changed ones can
            pos = self.position(key)
            if pos["state"] == "RUNNING" and self.section(pos["section_id"]).tracks == 1:
                occupied[pos["section_id"]].append((key, pos["from_node"]))
        for sid, here in occupied.items():
            for okey, _j, e, x, frm, *_rest in self.occupants(sid, self.now, self.now, frozenset(self.plans)):
                if e <= self.now < x:
                    here.append((okey, frm))
            dirs = {frm for _k, frm in here}
            if len(dirs) > 1:
                found.append(
                    _threat(
                        "OPPOSING_SAME_SECTION",
                        "CRITICAL",
                        [k for k, _ in here],
                        sid,
                        [f"plan:{k}" for k, _ in here],
                        0.5,
                        "Immediate controller attention: opposing runs on one single line.",
                        "Opposing train mapped ahead - follow signals and controller",
                        "Twin shows opposing occupancy.",
                    )
                )
        return found

    # ---- cab ---------------------------------------------------------------------------------------
    def cab(self, key: str) -> dict[str, Any]:
        with self.lock:
            if key not in self.runs:
                raise KeyError(key)
            run, plan = self.runs[key], self.plan_of(key)
            pos = self.position(key)
            state = self.position_state(key)
            threats = self.threats.for_train(key)
            top = max((t.severity for t in threats), key=["INFO", "CAUTION", "WARNING", "CRITICAL"].index, default=None)
            if state == STALE:
                status = "DATA UNAVAILABLE"
            elif pos["state"] == "ARRIVED":
                status = "NORMAL"
            elif key in self.pending or top == "CRITICAL":
                status = "HOLD-FOR-CONTROLLER"
            elif top in ("CAUTION", "WARNING"):
                status = "CAUTION"
            else:
                status = "NORMAL"
            i = pos["index"]
            ahead = plan.sections[i : i + 6]
            sec = self.section(plan.sections[min(i, len(plan.sections) - 1)])
            band = None
            if status in ("NORMAL", "CAUTION") and pos["state"] == "RUNNING":
                v = min(run.vmax_kmph, sec.vmax_kmph, sec.temp_restriction_kmph or 1e9)
                band = [round(v * 0.9), round(v)]
            nearby = []
            if pos["section_id"]:
                for okey, _j, e, x, *_rest in self.occupants(pos["section_id"], self.now, self.now, frozenset({key})):
                    if e <= self.now < x:
                        nearby.append(
                            {
                                "run": okey,
                                "relation": "SAME SECTION",
                                "confidence": "LOW" if self.position_state(okey) in (STALE, "PROJECTED") else "HIGH",
                            }
                        )
            delay = plan.exit[-1] - run.s_exit[-1]
            return {
                "run": key,
                "train": f"{run.number} {run.name}",
                "type": run.type,
                "status": status,
                "position_evidence": state,
                "position": pos,
                "advisory_speed_band_kmph": band if state != STALE else None,
                "route_ahead": ahead,
                "next_station": plan.to[i] if i < len(plan.to) else None,
                "schedule_deviation_min": round(delay, 1),
                "arrival": clock(plan.exit[-1]),
                "plan_source": self.approved.get(key, {}).get("summary")
                or ("AWAITING CONTROLLER DECISION" if key in self.pending else "PUBLISHED TIMETABLE"),
                "nearby_trains": nearby[:5],
                "threats": [{"type": t.type, "severity": t.severity, "message": t.driver_message} for t in threats],
                "authority": AUTHORITY,
                "footer": CAB_FOOTER,
            }

    def set_weights(self, preset: str | None = None, weights: dict[str, float] | None = None) -> dict[str, float]:
        with self.lock:
            name, self.weights = scoring.choose_weights(self.weights, preset, weights)
            self.preset = name or self.preset
            return self.weights

    def acknowledge(self, threat_id: str, by: str) -> dict[str, Any]:
        with self.lock:
            threat = self.threats.acknowledge(threat_id, by)
            self.audit.record(int(self.now * 60), "THREAT_ACKNOWLEDGED", by, {"threat": threat_id, "type": threat.type})
            return threat.to_dict()

    def lonlat(self, key: str) -> tuple[float, float] | None:
        pos = self.position(key)
        nodes = self.net.nodes
        if pos["section_id"] is None:
            return nodes.get(pos["node"])
        (x1, y1), (x2, y2) = nodes[pos["from_node"]], nodes[pos["to_node"]]
        f = min(pos["offset_km"] / max(self.section(pos["section_id"]).length_km, 1e-6), 1.0)
        return round(x1 + (x2 - x1) * f, 4), round(y1 + (y2 - y1) * f, 4)

    def positions(self) -> list[list[Any]]:
        """Compact live picture: [run, lon, lat, priority, changed, position evidence] for running runs."""

        with self.lock:
            out = []
            for key in self.running():
                ll = self.lonlat(key)
                if ll:
                    out.append(
                        [key, ll[0], ll[1], self.runs[key].priority, key in self.plans, self.position_state(key)]
                    )
            return out

    def runs_for(self, number: str) -> list[dict[str, Any]]:
        with self.lock:
            out = []
            for day in (0, -1, -2, -3):
                key = f"{number}@{day}"
                if key in self.runs:
                    plan, pos = self.plan_of(key), self.position(key)
                    out.append(
                        {
                            "run": key,
                            "name": self.runs[key].name,
                            "type": self.runs[key].type,
                            "state": pos["state"],
                            "position": pos,
                            "next_departures": [
                                {"station": plan.frm[i], "time": clock(plan.enter[i])}
                                for i in range(pos["index"], min(pos["index"] + 12, len(plan.sections)))
                            ],
                        }
                    )
            return out

    def plan_geometry(self, key: str) -> dict[str, Any]:
        with self.lock:
            plan = self.plan_of(key)
            i = self.position(key)["index"]
            nodes = [plan.frm[i], *plan.to[i:]] if i < len(plan.sections) else [plan.to[-1]]
            return {"run": key, "nodes": nodes, "coords": [self.net.nodes[n] for n in nodes]}

    def network_geometry(self) -> dict[str, Any]:
        """Static map layer: node coordinates and sections as [a, b, tracks, trains per day]."""

        return {
            "nodes": self.net.nodes,
            "stats": self.data.stats,
            "sections": [[s.a, s.b, s.tracks, int(s.utilisation)] for s in self.net.sections.values()],
            "passing_points": self.data.passing_points,
        }

    def summary(self) -> dict[str, Any]:
        with self.lock:
            return {
                "now_min": self.now,
                "clock": clock(self.now),
                "stats": self.data.stats,
                "running": len(self.running()),
                "changed_runs": len(self.plans),
                "pending": self.pending,
                "threats": [t.to_dict() for t in self.threats.active()[:100]],
                "threat_count": len(self.threats.active()),
                "latest": self.latest,
                "audit_chain_ok": self.audit.verify_chain(),
                "authority": AUTHORITY,
            }


def _strip(ranking: dict[str, Any]) -> dict[str, Any]:
    """Ranking without bulky/unstable fields, for snapshots and replay comparison."""

    return {
        **ranking,
        "candidates": [
            {k: v for k, v in c.items() if k != "closest_separations"} for c in ranking.get("candidates", [])
        ],
    }
