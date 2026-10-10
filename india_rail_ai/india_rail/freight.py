"""Dedicated Freight Corridors (DFC): the real corridor network and automated, conflict-free freight pathing.

    python -m india_rail freight build --pbf data/raw/osm/india.osm.pbf   # corridors from OpenStreetMap
    python -m india_rail freight plan --corridor Western --trains 182      # plan a day at a given volume
    python -m india_rail freight verify                                    # randomised invariant checks

Network: the Eastern (Ludhiana - Sonnagar) and Western (JNPT - Dadri) corridors as mapped in OpenStreetMap
(ways named "... Dedicated Freight Corridor" or operated by DFCCIL; ODbL). For each corridor the centre-line
runs between its two track ends farthest apart; it is cut into block-like segments at the points where DFC track
physically joins Indian Railways track (interchanges) and at the nearest IR station, about every 25 km. DFC
stations are mostly not mapped, so segment names are "near <IR station>": DFCCIL's station list replaces them.
Single or double line is counted on the mapped tracks at 1 km intervals.

Published operating figures used (Lok Sabha replies and Ministry statements, see docs): ~403 freight trains per
day in FY 2025 (Eastern ~209, Western ~182 in January 2025), sectional average speeds of 99 km/h (Eastern) and
89.5 km/h (Western), 100 km/h line speed. Train-level freight timings are not public (FOIS): the planner takes
demand from the authorised FOIS interface; the verification uses randomised demand at the published volume.

Deliveries: a train may carry the delivery time promised to its customer (`due_min`, from FOIS). Within a
priority class the train with the least slack (promised time minus ready time minus its free running time) is
pathed first, so a train that can still arrive on time is not made late by one that has hours in hand; each plan
reports whether it arrives by its promised time and by how much it is late.

Planning rules (every one is checked by `check`): trains are pathed in priority order, then least slack to the
promised delivery time (trains without one after those with one), then ready time; on a
segment two same-direction trains keep `headway_min` at entry and at exit and never overtake on plain line; on a
single-line segment opposing trains never overlap; a train may wait only at segment ends (stations with loops),
at most `loops` trains at once; blocked segments (maintenance, failures) are never entered while blocked.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
from bisect import insort
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from india_rail.ingest import RAW_DIR

CORRIDORS_PATH = RAW_DIR / "osm" / "dfc_corridors.json"
PUBLISHED = {
    "trains_per_day_fy2025": 403,
    "trains_per_day_jan2025": {"Eastern": 209, "Western": 182},
    "sectional_average_speed_kmph": {"Eastern": 99.38, "Western": 89.5},
    "line_speed_kmph": 100,
    "length_km": {"Eastern": 1337, "Western": 1504},
    "sources": [
        "Ministry of Railways: average 403 DFC freight trains per day in FY 2025 (statement reported by ITLN, 2025)",
        "Lok Sabha unstarred question replies on DFC operations (eparlib.sansad.in)",
        "Wikipedia: Dedicated freight corridors in India (lengths, endpoints)",
    ],
}
SEGMENT_KM = 25.0
BRIDGE_KM = 15.0  # mapping gaps up to this long are joined (each one counted in the build report)
START_ALLOWANCE_MIN = 3.0  # extra running time when a train starts from rest (acceleration of a heavy freight)


# ---- network ---------------------------------------------------------------------------------------------
def _hv(a: tuple[float, float], b: tuple[float, float]) -> float:
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[0] - a[0]) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def build_corridors(pbf: Path, railways_npz: Path | None = None, out: Path = CORRIDORS_PATH) -> dict[str, Any]:
    """Corridor centre-lines, segments, line counts and interchanges from an OpenStreetMap extract."""

    import numpy as np
    import osmium
    from osmium.filter import IdFilter, KeyFilter
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components, dijkstra
    from scipy.spatial import cKDTree

    ways, stations = [], []
    for obj in osmium.FileProcessor(str(pbf), osmium.osm.WAY | osmium.osm.NODE).with_filter(KeyFilter("railway")):
        tags = obj.tags
        text = (tags.get("operator", "") + " " + tags.get("name", "")).lower()
        if obj.is_way() and tags.get("railway") == "rail" and ("dfc" in text or "dedicated freight" in text):
            corridor = (
                "Western"
                if ("western" in text or "wdfc" in text)
                else "Eastern"
                if ("eastern" in text or "edfc" in text)
                else None
            )
            ways.append((corridor, [n.ref for n in obj.nodes], bool(tags.get("service"))))
        elif obj.is_node() and tags.get("railway") in ("station", "halt"):
            ref = (tags.get("ref") or tags.get("railway:ref") or "").split(";")[0].strip().upper()
            stations.append((obj.location.lon, obj.location.lat, tags.get("name", ""), ref))
    needed = sorted({n for w in ways for n in w[1]})
    loc = {n.id: (n.location.lon, n.location.lat)
           for n in osmium.FileProcessor(str(pbf), osmium.osm.NODE).with_filter(IdFilter(needed))}  # fmt: skip
    dfc_nodes = set(loc)
    ir_nodes: set[int] = set()
    npz = railways_npz or pbf.with_suffix(".railways-v2.npz")
    if npz.exists():  # Indian Railways running lines (from osm_infra.extract): where DFC track joins them
        data = np.load(npz)
        counted = np.repeat(data["way_counted"].astype(bool), data["way_len"])
        ir_nodes = set(data["way_nodes"][counted].tolist()) & dfc_nodes
    st_xy = np.array([(s[0] * 102.0, s[1] * 110.6) for s in stations])
    st_tree = cKDTree(st_xy)

    result: dict[str, Any] = {
        "published": PUBLISHED,
        "licence": "ODbL-1.0, (c) OpenStreetMap contributors",
        "corridors": {},
    }
    for corridor in ("Eastern", "Western"):
        cw = [w for w in ways if w[0] in (corridor, None) and not w[2]]
        ids = sorted({n for w in cw for n in w[1] if n in loc})
        ix = {n: i for i, n in enumerate(ids)}
        u, v, d = [], [], []
        for _c, nodes, _s in cw:
            for a, b in itertools.pairwise(nodes):
                if a in ix and b in ix:
                    u.append(ix[a]), v.append(ix[b]), d.append(_hv(loc[a], loc[b]))
        n = len(ids)
        xy = np.array([(loc[i][0] * 102.0, loc[i][1] * 110.6) for i in ids])
        bridged = _bridge_gaps(n, u, v, d, xy)
        graph = coo_matrix((d + d, (u + v, v + u)), shape=(n, n)).tocsr()
        lab = connected_components(graph, directed=False)[1]
        main = int(np.bincount(lab).argmax())
        ends = np.array([i for i in np.nonzero(np.bincount(np.array(u + v), minlength=n) == 1)[0] if lab[i] == main])
        if len(ends) < 2:
            continue
        # the two track ends farthest apart on the ground are the corridor terminals
        e_xy = xy[ends]
        far = max(((int(a), int(b)) for a in range(len(ends)) for b in range(a + 1, len(ends))),
                  key=lambda ab: float(np.hypot(*(e_xy[ab[0]] - e_xy[ab[1]]))))  # fmt: skip
        A, B = int(ends[far[0]]), int(ends[far[1]])
        dist, pred = dijkstra(graph, indices=A, return_predecessors=True)
        if not np.isfinite(dist[B]):
            continue
        path = [B]
        while path[-1] != A:
            path.append(int(pred[path[-1]]))
        path.reverse()
        if loc[ids[path[0]]][1] < loc[ids[path[-1]]][1]:
            path.reverse()  # chainage from the northern end
        pts = [loc[ids[k]] for k in path]
        cum = [0.0]
        for a, b in itertools.pairwise(pts):
            cum.append(cum[-1] + _hv(a, b))
        path_xy = xy[path]
        interchanges = sorted({round(cum[k], 1) for k, node in enumerate(path) if ids[node] in ir_nodes})
        lines = _line_counts(cw, loc, pts, cum)
        track_km = sum(
            _hv(loc[a], loc[b]) for _c, ns, _s in cw for a, b in itertools.pairwise(ns) if a in loc and b in loc
        )
        cuts = _cut_points(cum[-1], interchanges)
        segments = []
        for a_km, b_km in itertools.pairwise(cuts):
            mid = [k for k in range(len(cum)) if a_km <= cum[k] <= b_km]
            single = [x for km, x in lines if a_km <= km <= b_km]
            segments.append({
                "from_km": round(a_km, 1),
                "to_km": round(b_km, 1),
                "km": round(b_km - a_km, 1),
                "lines": 1 if single and sum(1 for x in single if x == 1) > 0.3 * len(single) else 2,
                "from": _near_station(path_xy, cum, a_km, st_tree, stations),
                "to": _near_station(path_xy, cum, b_km, st_tree, stations),
                "mid_lonlat": [round(c, 5) for c in pts[mid[len(mid) // 2]]] if mid else None,
            })  # fmt: skip
        result["corridors"][corridor] = {
            "centreline_km": round(cum[-1], 1),
            "published_km": PUBLISHED["length_km"][corridor],
            "mapped_track_km": round(track_km, 1),
            "track_pieces": len(cw),
            "mapping_gaps_bridged": bridged,
            "interchanges_with_ir": len(interchanges),
            "single_line_km": round(sum(s["km"] for s in segments if s["lines"] == 1), 1),
            "ends": [list(pts[0]), list(pts[-1])],
            "segments": segments,
        }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result), encoding="utf-8")
    return {k: {x: y for x, y in c.items() if x != "segments"} | {"segments": len(c["segments"])}
            for k, c in result["corridors"].items()}  # fmt: skip


def _bridge_gaps(n: int, u: list, v: list, d: list, xy) -> int:
    """Join mapped track pieces across mapping gaps of up to BRIDGE_KM, closest track ends first (counted)."""

    import numpy as np
    from scipy.spatial import cKDTree

    parent = list(range(n))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in zip(u, v, strict=True):
        parent[root(a)] = root(b)
    ends = np.nonzero(np.bincount(np.array(u + v), minlength=n) == 1)[0]
    tree = cKDTree(xy)
    pairs = sorted(
        (float(np.hypot(*(xy[i] - xy[j]))), int(i), int(j))
        for i in ends
        for j in tree.query_ball_point(xy[i], BRIDGE_KM)
        if root(int(i)) != root(int(j))
    )
    bridged = 0
    for dist, i, j in pairs:
        if root(i) != root(j):
            u.append(i), v.append(j), d.append(dist)
            parent[root(i)] = root(j)
            bridged += 1
    return bridged


def _cut_points(total: float, interchanges: list[float]) -> list[float]:
    cuts = [0.0]
    for km in [*interchanges, total]:
        while km - cuts[-1] > SEGMENT_KM * 1.5:  # long stretch: cut about every SEGMENT_KM
            cuts.append(cuts[-1] + SEGMENT_KM)
        if km - cuts[-1] >= 5.0:
            cuts.append(km)
    if total - cuts[-1] > 0.5:
        cuts.append(total)
    else:
        cuts[-1] = total
    return cuts


def _line_counts(cw, loc, pts, cum) -> list[tuple[float, int]]:
    """Mapped DFC tracks crossing the centre-line's cross-section, every 1 km (1 = single line)."""

    segs = [(loc[a], loc[b]) for _c, ns, _s in cw for a, b in itertools.pairwise(ns) if a in loc and b in loc]
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, (a, b) in enumerate(segs):
        for gx in range(int(min(a[0], b[0]) / 0.01), int(max(a[0], b[0]) / 0.01) + 1):
            for gy in range(int(min(a[1], b[1]) / 0.01), int(max(a[1], b[1]) / 0.01) + 1):
                grid[(gx, gy)].append(i)
    out = []
    k = 1
    mark = 1.0
    while mark < cum[-1] - 1.0:
        while cum[k] < mark:
            k += 1
        (x0, y0), (x1, y1) = pts[k - 1], pts[k]
        f = (mark - cum[k - 1]) / max(cum[k] - cum[k - 1], 1e-9)
        px, py = x0 + f * (x1 - x0), y0 + f * (y1 - y0)
        mx, my = 111320.0 * math.cos(math.radians(py)), 110574.0
        ux, uy = (x1 - x0) * mx, (y1 - y0) * my
        norm = math.hypot(ux, uy) or 1.0
        ux, uy = ux / norm, uy / norm
        offsets = []
        cx, cy = int(px / 0.01), int(py / 0.01)
        cand = {i for gx in (cx - 1, cx, cx + 1) for gy in (cy - 1, cy, cy + 1) for i in grid.get((gx, gy), ())}
        for i in cand:
            (ax, ay), (bx, by) = segs[i]
            ax, ay, bx, by = (ax - px) * mx, (ay - py) * my, (bx - px) * mx, (by - py) * my
            sa, sb = ax * ux + ay * uy, bx * ux + by * uy
            if sa * sb > 0 or sa == sb:
                continue
            t = sa / (sa - sb)
            off = (-ax * uy + ay * ux) + t * ((-bx * uy + by * ux) - (-ax * uy + ay * ux))
            if abs(off) <= 60.0:
                offsets.append(off)
        offsets.sort()
        count = 1 + sum(1 for a, b in itertools.pairwise(offsets) if b - a > 2.0) if offsets else 0
        if count:
            out.append((mark, min(count, 2)))
        mark += 1.0
    return out


def _near_station(path_xy, cum, km, st_tree, stations) -> str:
    import numpy as np

    k = int(np.searchsorted(cum, km))
    k = min(k, len(cum) - 1)
    dist, i = st_tree.query(path_xy[k])
    name, ref = stations[i][2], stations[i][3]
    label = f"{name} ({ref})" if ref else name
    return f"near {label}" if dist <= 5.0 else f"km {km:.0f}"


def load_corridors(path: Path = CORRIDORS_PATH) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{path} not built: run python -m india_rail freight build --pbf <extract>")
    return json.loads(path.read_text(encoding="utf-8"))


# ---- planning ----------------------------------------------------------------------------------------------
@dataclass
class FreightTrain:
    id: str
    origin_km: float  # chainage along the corridor (from its northern end)
    destination_km: float
    ready_min: float  # earliest departure, minutes from 00:00 of the planning day
    priority: int = 3  # 1 = highest (e.g. time-tabled container), 5 = lowest
    speed_kmph: float | None = None  # sectional speed; default: the corridor's published average
    due_min: float | None = None  # delivery time promised to the customer (arrival at destination), if any

    @property
    def up(self) -> bool:  # travelling towards higher chainage
        return self.destination_km > self.origin_km


@dataclass
class Leg:
    segment: int
    enter: float
    exit: float
    wait_before: float = 0.0


@dataclass
class TrainPlan:
    id: str
    up: bool
    priority: int
    ready_min: float
    legs: list[Leg] = field(default_factory=list)
    status: str = "PLANNED"
    due_min: float | None = None

    @property
    def late_min(self) -> float | None:
        """Minutes after the promised delivery time (0 = on time); None without a promise."""

        return None if self.due_min is None or not self.legs else round(max(self.legs[-1].exit - self.due_min, 0.0), 1)

    @property
    def departure(self) -> float:
        return self.legs[0].enter if self.legs else self.ready_min

    @property
    def arrival(self) -> float:
        return self.legs[-1].exit if self.legs else self.ready_min

    @property
    def waiting(self) -> float:
        return sum(leg.wait_before for leg in self.legs)


class FreightPlanner:
    """Conflict-free pathing on one corridor (see the module docstring for the rules)."""

    def __init__(self, corridor: dict[str, Any], name: str, headway_min: float = 10.0, loops: int = 3):
        self.name = name
        self.segments = corridor["segments"]
        self.headway = headway_min
        self.loops = loops
        self.default_speed = PUBLISHED["sectional_average_speed_kmph"].get(name, 80.0)
        self.blocks: dict[int, list[tuple[float, float]]] = defaultdict(list)
        self.reset()

    def reset(self) -> None:
        self.occ: dict[int, list[tuple[float, float, bool, str]]] = defaultdict(list)  # seg -> (enter, exit, up, id)
        self.waits: dict[int, list[tuple[float, float]]] = defaultdict(list)  # station index -> waiting intervals
        self.plans: dict[str, TrainPlan] = {}

    def block(self, segment: int, start: float, end: float) -> None:
        """Close a segment for [start, end) minutes (maintenance block, failure); re-plan to apply."""

        self.blocks[segment].append((start, end))

    def _segment_range(self, t: FreightTrain) -> list[int]:
        lo, hi = sorted((t.origin_km, t.destination_km))
        idx = [i for i, s in enumerate(self.segments) if s["to_km"] > lo + 0.5 and s["from_km"] < hi - 0.5]
        return idx if t.up else idx[::-1]

    def _run_min(self, seg: dict, speed: float, starting: bool) -> float:
        return seg["km"] / min(speed, PUBLISHED["line_speed_kmph"]) * 60 + (START_ALLOWANCE_MIN if starting else 0.0)

    def _conflict_free_from(self, seg_i: int, t0: float, run: float, up: bool) -> float:
        """Earliest entry time >= t0 at which the segment can be used for `run` minutes."""

        h, single = self.headway, self.segments[seg_i]["lines"] == 1
        tol = 1e-7  # a slot exactly one headway away is fine; floating-point noise must not reject it
        t = t0
        for _ in range(10_000):
            bump = None
            for a, b in self.blocks.get(seg_i, ()):
                if t < b - tol and t + run > a + tol:
                    bump = max(bump or 0.0, b)
            for e, x, other_up, _id in self.occ[seg_i]:
                if other_up == up:
                    # same direction: headway at entry and exit, and no overtaking on plain line
                    if abs(t - e) < h - tol or abs(t + run - x) < h - tol or (t < e) != (t + run < x):
                        bump = max(bump or 0.0, max(e + h, x + h - run))
                elif single and t < x + h - tol and t + run > e - h + tol:
                    bump = max(bump or 0.0, x + h)  # opposing on single line: wait for it to clear
            if bump is None:
                return t
            t = max(bump, t + tol)
        raise RuntimeError("no conflict-free slot found")

    def _loop_free(self, station: int, start: float, end: float) -> bool:
        """True if at every moment of [start, end) fewer than `loops` other trains wait at the station."""

        return end - start <= 1e-6 or max_simultaneous(self.waits[station], start, end) < self.loops

    def path(self, t: FreightTrain) -> TrainPlan:
        speed = t.speed_kmph or self.default_speed
        segs = self._segment_range(t)
        plan = TrainPlan(t.id, t.up, t.priority, t.ready_min, due_min=t.due_min)
        if not segs:
            plan.status = "NO_SEGMENTS"
            return plan
        for attempt in range(200):  # each attempt delays the departure if a loop on the way is full
            legs, now, ok = [], t.ready_min + attempt * self.headway, True
            for k, seg_i in enumerate(segs):
                run = self._run_min(self.segments[seg_i], speed, starting=(k == 0))
                enter = self._conflict_free_from(seg_i, now, run, t.up)
                wait = enter - now
                station = seg_i if t.up else seg_i + 1  # the station (segment end) the train waits at
                if k > 0 and wait > 1e-6:
                    run = self._run_min(self.segments[seg_i], speed, starting=True)  # restarting from a stop
                    enter = self._conflict_free_from(seg_i, enter, run, t.up)
                    if not self._loop_free(station, now, enter):  # the whole wait, after the restart allowance
                        ok = False
                        break
                legs.append(Leg(seg_i, enter, enter + run, enter - now if k > 0 else 0.0))
                now = enter + run
            if ok:
                break
        else:
            plan.status = "NO_PATH"
            return plan
        for k, leg in enumerate(legs):
            insort(self.occ[leg.segment], (leg.enter, leg.exit, t.up, t.id))
            if k > 0 and leg.wait_before > 1e-6:
                station = leg.segment if t.up else leg.segment + 1
                self.waits[station].append((leg.enter - leg.wait_before, leg.enter))
        plan.legs = legs
        self.plans[t.id] = plan
        return plan

    def plan(self, trains: list[FreightTrain], order: str = "slack") -> dict[str, Any]:
        """Path every train. `order`: "slack" (priority, then least slack to the promised delivery time, then
        ready time) or "ready" (priority, then ready time: promised times ignored, for comparison)."""

        self.reset()
        free = {t.id: sum(self._run_min(self.segments[i], t.speed_kmph or self.default_speed, k == 0)
                          for k, i in enumerate(self._segment_range(t))) for t in trains}  # fmt: skip

        def slack(t: FreightTrain) -> float:
            return math.inf if t.due_min is None or order != "slack" else t.due_min - t.ready_min - free[t.id]

        for t in sorted(trains, key=lambda x: (x.priority, slack(x), x.ready_min, x.id)):
            self.path(t)
        planned = [p for p in self.plans.values() if p.status == "PLANNED"]
        delays = [p.arrival - p.ready_min - free[p.id] for p in planned]
        promised = [t for t in trains if t.due_min is not None]
        late = sorted((p for p in planned if p.late_min), key=lambda p: -(p.late_min or 0))
        on_time = sum(1 for t in promised if t.id in self.plans and self.plans[t.id].late_min == 0)
        return {
            "corridor": self.name,
            "trains": len(trains),
            "planned": len(planned),
            "not_planned": [t.id for t in trains if t.id not in self.plans],
            "mean_delay_min": round(sum(delays) / len(delays), 1) if delays else None,
            "max_delay_min": round(max(delays), 1) if delays else None,
            "on_free_path_pct": round(100 * sum(1 for x in delays if x < 1) / len(delays), 1) if delays else None,
            "deliveries": {
                "with_promised_time": len(promised),
                "on_time": on_time,
                "on_time_pct": round(100 * on_time / len(promised), 1) if promised else None,
                "late": [{"id": p.id, "late_min": p.late_min} for p in late[:20]],
                "mean_late_min_of_late": round(sum(p.late_min or 0 for p in late) / len(late), 1) if late else 0.0,
                "order": "priority, then least slack to the promised time" if order == "slack" else "priority, ready",
            },
            "violations": check(self),
            "capacity": capacity(self),
        }


def check(planner: FreightPlanner) -> list[str]:
    """Independent check of every planning rule over the whole plan (empty list = safe)."""

    problems = []
    h = planner.headway - 1e-6
    for seg_i, occ in planner.occ.items():
        single = planner.segments[seg_i]["lines"] == 1
        for i, (e1, x1, up1, id1) in enumerate(occ):
            if x1 < e1:
                problems.append(f"{id1} exits segment {seg_i} before entering")
            for a, b in planner.blocks.get(seg_i, ()):
                if e1 < b and x1 > a:
                    problems.append(f"{id1} uses blocked segment {seg_i}")
            for e2, x2, up2, id2 in occ[i + 1 :]:
                if up1 == up2:
                    if abs(e1 - e2) < h or abs(x1 - x2) < h or (e1 < e2) != (x1 < x2):
                        problems.append(f"{id1}/{id2} headway or overtaking on segment {seg_i}")
                elif single and e1 < x2 + h and e2 < x1 + h:
                    problems.append(f"{id1}/{id2} opposing on single-line segment {seg_i}")
    for station, waits in planner.waits.items():
        if waits and max_simultaneous(waits, min(a for a, _ in waits), max(b for _, b in waits)) > planner.loops:
            problems.append(f"more than {planner.loops} trains waiting at once at station {station}")
    for plan in planner.plans.values():
        for prev, leg in zip(plan.legs, plan.legs[1:], strict=False):
            if leg.enter < prev.exit - 1e-6:
                problems.append(f"{plan.id} enters a segment before leaving the previous one")
    return problems


def max_simultaneous(intervals: list[tuple[float, float]], start: float, end: float) -> int:
    """Most intervals open at the same moment within [start, end) (sweep over interval ends)."""

    events = []
    for a, b in intervals:
        if a < end and start < b:
            events += [(max(a, start), 1), (min(b, end), -1)]
    events.sort(key=lambda e: (e[0], e[1]))  # an interval ending at t frees the loop for one starting at t
    best = now = 0
    for _t, step in events:
        now += step
        best = max(best, now)
    return best


def random_demand(corridor: dict[str, Any], n: int, seed: int = 0) -> list[FreightTrain]:
    """Test demand at a given daily volume (train-level freight demand is not public; FOIS supplies it)."""

    rng = random.Random(seed)  # nosec B311 - test demand, not security
    cuts = [s["from_km"] for s in corridor["segments"]] + [corridor["segments"][-1]["to_km"]]
    out = []
    for i in range(n):  # origin and destination uniform over the corridor's stations (an assumption: OD is not public)
        a, b = rng.sample(range(len(cuts)), 2)
        out.append(FreightTrain(f"F{i:04d}", cuts[a], cuts[b], rng.uniform(0, 1440), rng.choice((1, 2, 3, 3, 4, 5))))
    return out


def capacity(planner: FreightPlanner) -> dict[str, Any]:
    """Measured occupation of each segment over the day: share of the 1,440 minutes a track is occupied (single
    line: by either direction; double line: the busier direction's track)."""

    rows = []
    for i, seg in enumerate(planner.segments):
        occ = planner.occ.get(i, [])
        directions = [[(e, x) for e, x, up, _ in occ]] if seg["lines"] == 1 else [
            [(e, x) for e, x, up, _ in occ if up], [(e, x) for e, x, up, _ in occ if not up]]  # fmt: skip
        busy = max(_union_minutes(d) for d in directions) if occ else 0.0
        rows.append({"segment": i, "lines": seg["lines"], "km": seg["km"], "trains": len(occ),
                     "occupied_pct_of_day": round(100 * busy / 1440, 1)})  # fmt: skip
    worst = max(rows, key=lambda r: r["occupied_pct_of_day"])
    return {"busiest_segment": worst, "segments_over_70pct": sum(1 for r in rows if r["occupied_pct_of_day"] > 70)}


def _union_minutes(intervals: list[tuple[float, float]]) -> float:
    total, end = 0.0, float("-inf")
    for a, b in sorted(intervals):
        if b > end:
            total += b - max(a, end)
            end = b
    return total


def verify(seeds: int = 200) -> dict[str, Any]:
    """Randomised verification: many demand sets per corridor, every plan checked against every rule."""

    data = load_corridors()
    out: dict[str, Any] = {}
    for name, corridor in data["corridors"].items():
        volume = PUBLISHED["trains_per_day_jan2025"][name]
        totals = {"plans": 0, "trains": 0, "violations": 0, "not_planned": 0, "blocked_cases": 0}
        rng = random.Random(name)  # nosec B311 - test scenario choice
        for seed in range(seeds):
            planner = FreightPlanner(corridor, name, headway_min=rng.choice((6.0, 8.0, 10.0)), loops=rng.choice((2, 3)))
            if seed % 3 == 0:  # a maintenance block or failure somewhere in the day
                seg = rng.randrange(len(corridor["segments"]))
                start = rng.uniform(0, 1200)
                planner.block(seg, start, start + rng.uniform(30, 240))
                totals["blocked_cases"] += 1
            trains = random_demand(corridor, rng.randint(volume // 2, int(volume * 1.2)), seed)
            result = planner.plan(trains)
            totals["plans"] += 1
            totals["trains"] += len(trains)
            totals["violations"] += len(result["violations"])
            totals["not_planned"] += len(result["not_planned"])
        day = FreightPlanner(corridor, name).plan(random_demand(corridor, volume, seed=2025))
        out[name] = {**totals, "published_daily_volume": volume, "day_at_published_volume": day,
                     "deliveries": delivery_comparison(corridor, name, volume, seeds=max(seeds // 10, 1))}  # fmt: skip
    return out


def with_promises(corridor: dict[str, Any], name: str, trains: list[FreightTrain], seed: int) -> list[FreightTrain]:
    """Test promised delivery times (real ones come from FOIS): free running time plus a slack of 0-3 hours."""

    rng = random.Random(seed)  # nosec B311 - test demand, not security
    planner = FreightPlanner(corridor, name)
    out = []
    for t in trains:
        speed = t.speed_kmph or planner.default_speed
        legs = enumerate(planner._segment_range(t))
        free = sum(planner._run_min(planner.segments[i], speed, k == 0) for k, i in legs)
        out.append(FreightTrain(t.id, t.origin_km, t.destination_km, t.ready_min, t.priority, t.speed_kmph,
                                due_min=t.ready_min + free + rng.uniform(0, 180)))  # fmt: skip
    return out


def delivery_comparison(corridor: dict[str, Any], name: str, volume: int, seeds: int = 20) -> dict[str, Any]:
    """Deliveries on time when trains are pathed by least slack to their promised time, against by ready time
    alone, on the same test demand at the published daily volume; both plans checked against every rule."""

    totals = {"slack": [0, 0, 0], "ready": [0, 0, 0]}  # on time, promised, violations
    for seed in range(seeds):
        trains = with_promises(corridor, name, random_demand(corridor, volume, seed=10_000 + seed), seed)
        for order in totals:
            result = FreightPlanner(corridor, name).plan(trains, order=order)
            totals[order][0] += result["deliveries"]["on_time"]
            totals[order][1] += result["deliveries"]["with_promised_time"]
            totals[order][2] += len(result["violations"])
    pct = {k: round(100 * v[0] / max(v[1], 1), 1) for k, v in totals.items()}
    return {
        "days": seeds,
        "promised_deliveries": totals["slack"][1],
        "on_time_pct_least_slack_first": pct["slack"],
        "on_time_pct_by_ready_time": pct["ready"],
        "violations": totals["slack"][2] + totals["ready"][2],
        "promises": "test promises: free running time plus 0-3 h slack (train-level FOIS promises are not public)",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="india_rail freight", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--pbf", type=Path, required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--corridor", choices=("Eastern", "Western"), required=True)
    plan.add_argument("--trains", type=int, default=None)
    plan.add_argument("--headway", type=float, default=10.0)
    verify_cmd = sub.add_parser("verify")
    verify_cmd.add_argument("--seeds", type=int, default=200)
    verify_cmd.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.command == "build":
        print(json.dumps(build_corridors(args.pbf), indent=2))
    elif args.command == "plan":
        corridor = load_corridors()["corridors"][args.corridor]
        n = args.trains or PUBLISHED["trains_per_day_jan2025"][args.corridor]
        print(
            json.dumps(FreightPlanner(corridor, args.corridor, args.headway).plan(random_demand(corridor, n)), indent=2)
        )
    else:
        result = verify(args.seeds)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
    return 0


def plan_to_dict(plan: TrainPlan) -> dict[str, Any]:
    return asdict(plan) | {"departure": plan.departure, "arrival": plan.arrival, "waiting": plan.waiting,
                           "late_min": plan.late_min}  # fmt: skip
