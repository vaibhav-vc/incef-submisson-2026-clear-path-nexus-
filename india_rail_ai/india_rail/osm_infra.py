"""Real track infrastructure from OpenStreetMap: line count, electrification, gauge, speed limits, length.

    python -m india_rail real osm --pbf data/raw/osm/india.osm.pbf

Input: an OpenStreetMap extract of India (e.g. https://download.openstreetmap.fr/extracts/asia/india.osm.pbf,
verified against its published MD5). Data (c) OpenStreetMap contributors, ODbL 1.0: any database derived from
it keeps that licence and attribution. The derived tables stay in the git-ignored data/ directory.

For every section between two consecutive halts of a train:
  1. both stations are located: by their Indian Railways code in the OSM `ref` tag (93% of mapped stations
     carry one), else by the open-timetable coordinate; then snapped to the nearest mapped running line;
  2. the shortest path along mapped running lines joins them; it is accepted only if it is plausible
     (no longer than 1.6 x straight line + 3 km, and within 20% / 3 km of the timetable's rail distance);
  3. along the accepted path, every 400 m outside the 1.5 km station areas, the parallel running lines are
     counted (separately mapped lines whose perpendicular offsets differ by more than 2 m). The section's
     line count is the *minimum* over those samples: one single-line stretch makes the whole section single
     line for opposing moves, which is the safe reading;
  4. electrified share, dominant gauge, tagged speed limits and true path length are summed by length.

OSM is volunteer-mapped. A missing parallel line reads as single line (conservative). The twin uses an OSM
double-line reading only where the path was accepted, and labels every attribute with its evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

RUNNING = {"rail", "narrow_gauge"}
STATIONS = {"station", "halt"}
ELECTRIFIED_YES = {"contact_line", "yes", "rail", "4th_rail", "contact_line;rail"}
NOT_A_RUNNING_LINE = {"industrial", "military", "freight", "tourism", "test"}  # usage values not counted
SEPARATE_OPERATORS = ("dfc", "dedicated freight", "metro", "rapid rail", "rrts")  # parallel but separate systems
SAMPLE_STEP_KM = 0.4
STATION_AREA_KM = 1.5
PARALLEL_RADIUS_M = 30.0
SEPARATED_ALIGNMENT_M = 150.0  # a double line mapped further apart (separate bridges, cuttings) still counts
SINGLE_RUN_KM = 2.0  # a section is single line if it has a single-line stretch longer than this ...
SINGLE_SHARE = 0.10  # ... or single line over more than this share of its length
PARALLEL_MAX_ANGLE_DEG = 25.0
SAME_LINE_OFFSET_M = 2.0
SNAP_REF_KM = 1.5
SNAP_COORD_KM = 1.0
CELL_DEG = 0.005


def _gauge(value: str | None) -> int | None:
    try:
        return int(str(value).split(";")[0].strip())
    except ValueError:
        return None


def _speed(value: str | None) -> float | None:
    if not value:
        return None
    text = str(value).split(";")[0].strip().lower()
    factor = 1.609 if text.endswith("mph") else 1.0
    try:
        return float(text.replace("km/h", "").replace("mph", "").strip()) * factor
    except ValueError:
        return None


def extract(pbf: Path, cache: Path | None = None) -> dict[str, Any]:
    """Running-line ways (geometry and tags) and station nodes from an OSM extract (cached as .npz)."""

    import osmium
    from osmium.filter import IdFilter, KeyFilter

    cache = cache or pbf.with_suffix(".railways-v2.npz")
    if cache.exists() and cache.stat().st_mtime >= pbf.stat().st_mtime:
        data = np.load(cache, allow_pickle=False)
        return {k: data[k] for k in data.files} | {"stations": json.loads(str(data["stations_json"]))}

    way_nodes: list[np.ndarray] = []
    way_attr: list[tuple] = []
    stations: list[dict[str, Any]] = []
    for obj in osmium.FileProcessor(str(pbf), osmium.osm.WAY | osmium.osm.NODE).with_filter(KeyFilter("railway")):
        kind = obj.tags.get("railway")
        if obj.is_way() and kind in RUNNING:
            refs = np.fromiter((n.ref for n in obj.nodes), dtype=np.int64)
            if len(refs) < 2:
                continue
            electrified = obj.tags.get("electrified")
            operator = (obj.tags.get("operator", "") + " " + obj.tags.get("name", "")).lower()
            counted = not obj.tags.get("service") and obj.tags.get("usage") not in NOT_A_RUNNING_LINE
            counted = counted and not any(op in operator for op in SEPARATE_OPERATORS)
            way_nodes.append(refs)
            way_attr.append(
                (
                    obj.id,
                    1 if obj.tags.get("service") else 0,
                    -1 if electrified is None else int(electrified in ELECTRIFIED_YES),
                    _gauge(obj.tags.get("gauge")) or -1,
                    _speed(obj.tags.get("maxspeed")) or -1.0,
                    int(counted),
                )
            )
        elif obj.is_node() and kind in STATIONS:
            refs = obj.tags.get("ref") or obj.tags.get("railway:ref") or ""
            stations.append(
                {
                    "id": obj.id,
                    "lon": obj.location.lon,
                    "lat": obj.location.lat,
                    "refs": [r.strip().upper() for r in refs.replace(",", ";").split(";") if r.strip()],
                    "name": obj.tags.get("name", ""),
                }
            )
    needed = np.unique(np.concatenate(way_nodes))
    lon = np.full(len(needed), np.nan)
    lat = np.full(len(needed), np.nan)
    for node in osmium.FileProcessor(str(pbf), osmium.osm.NODE).with_filter(IdFilter(needed.tolist())):
        i = int(np.searchsorted(needed, node.id))
        lon[i], lat[i] = node.location.lon, node.location.lat
    lengths = np.array([len(w) for w in way_nodes], dtype=np.int64)
    attr = np.array([a[1:] for a in way_attr], dtype=np.float64)
    result = {
        "node_id": needed,
        "lon": lon,
        "lat": lat,
        "way_id": np.array([a[0] for a in way_attr], dtype=np.int64),
        "way_len": lengths,
        "way_nodes": np.concatenate(way_nodes),
        "way_service": attr[:, 0].astype(np.int8),
        "way_electrified": attr[:, 1].astype(np.int8),
        "way_gauge": attr[:, 2].astype(np.int32),
        "way_maxspeed": attr[:, 3],
        "way_counted": attr[:, 4].astype(np.int8),
        "stations_json": np.array(json.dumps(stations)),
    }
    np.savez_compressed(cache, **result)
    result["stations"] = stations
    return result


class RailGraph:
    """Mapped running lines as a weighted graph, with a segment grid for counting parallel lines."""

    def __init__(self, osm: dict[str, Any]):
        from scipy.sparse import coo_matrix
        from scipy.spatial import cKDTree

        ok = ~np.isnan(osm["lon"])
        self.lon, self.lat = osm["lon"], osm["lat"]
        node_index = osm["way_nodes"]
        idx = np.searchsorted(osm["node_id"], node_index)
        starts = np.concatenate([[0], np.cumsum(osm["way_len"])[:-1]])
        way_of = np.repeat(np.arange(len(osm["way_len"])), osm["way_len"])
        last = np.zeros(len(idx), dtype=bool)
        last[np.cumsum(osm["way_len"]) - 1] = True
        u, v, w = idx[:-1][~last[:-1]], idx[1:][~last[:-1]], way_of[:-1][~last[:-1]]
        keep = ok[u] & ok[v] & (u != v)
        u, v, w = u[keep], v[keep], w[keep]
        km = _haversine(self.lon[u], self.lat[u], self.lon[v], self.lat[v])
        self.service = osm["way_service"].astype(bool)
        cost = km * np.where(self.service[w], 2.0, 1.0)  # prefer running lines over sidings and yards
        n = len(self.lon)
        self.matrix = coo_matrix((np.concatenate([cost, cost]), (np.concatenate([u, v]), np.concatenate([v, u]))),
                                 shape=(n, n)).tocsr()  # fmt: skip
        self.edge_way = {(min(a, b), max(a, b)): c for a, b, c in zip(u.tolist(), v.tolist(), w.tolist(), strict=True)}
        self.electrified, self.gauge = osm["way_electrified"], osm["way_gauge"]
        self.maxspeed = osm["way_maxspeed"]
        del starts
        # Nearest-node search on running-line nodes (projected to km).
        used = np.unique(np.concatenate([u, v]))
        main = np.unique(np.concatenate([u[~self.service[w]], v[~self.service[w]]]))
        self.kx = 111.32 * np.cos(np.radians(22.0))
        self._tree_all = (cKDTree(np.c_[self.lon[used] * self.kx, self.lat[used] * 110.57]), used)
        self._tree_main = (cKDTree(np.c_[self.lon[main] * self.kx, self.lat[main] * 110.57]), main)
        # Segment grid of counted running lines (no sidings, freight corridors or metros) for the line count.
        m = osm["way_counted"].astype(bool)[w] & ~self.service[w]
        self.sx1, self.sy1, self.sx2, self.sy2 = self.lon[u[m]], self.lat[u[m]], self.lon[v[m]], self.lat[v[m]]
        self.grid: dict[tuple[int, int], list[int]] = defaultdict(list)
        for i, (x1, y1, x2, y2) in enumerate(zip(self.sx1, self.sy1, self.sx2, self.sy2, strict=True)):
            for gx in range(int(min(x1, x2) // CELL_DEG), int(max(x1, x2) // CELL_DEG) + 1):
                for gy in range(int(min(y1, y2) // CELL_DEG), int(max(y1, y2) // CELL_DEG) + 1):
                    self.grid[(gx, gy)].append(i)

    def snap(self, lon: float, lat: float, max_km: float) -> int | None:
        for tree, ids in (self._tree_main, self._tree_all):
            dist, i = tree.query([lon * self.kx, lat * 110.57])
            if dist <= max_km:
                return int(ids[i])
        return None

    def lines_at(self, lon: float, lat: float, dx: float, dy: float) -> int:
        """Running lines crossing the cross-section through a point (track direction dx, dy in degrees).

        Every counted line segment that crosses the perpendicular through the point, runs within 25 degrees of
        the track direction and lies within 150 m gives one perpendicular offset. Offsets within 30 m are
        clustered (closer than 2 m = the same line); a lone line with another parallel line 30-150 m away
        reads 2 (a double line mapped apart, e.g. on separate bridges). Returns 0 where nothing is mapped.
        """

        span = int(SEPARATED_ALIGNMENT_M / 111000 / CELL_DEG) + 1
        cx, cy = int(lon // CELL_DEG), int(lat // CELL_DEG)
        cand = sorted(
            {
                i
                for gx in range(cx - span, cx + span + 1)
                for gy in range(cy - span, cy + span + 1)
                for i in self.grid.get((gx, gy), ())
            }
        )
        if not cand:
            return 0
        c = np.array(cand)
        mx, my = 111320.0 * math.cos(math.radians(lat)), 110574.0
        ax, ay = (self.sx1[c] - lon) * mx, (self.sy1[c] - lat) * my
        bx, by = (self.sx2[c] - lon) * mx, (self.sy2[c] - lat) * my
        ux, uy = dx * mx, dy * my
        norm = math.hypot(ux, uy) or 1.0
        ux, uy = ux / norm, uy / norm
        sa, sb = ax * ux + ay * uy, bx * ux + by * uy  # along-track coordinates of the segment ends
        na, nb = -ax * uy + ay * ux, -bx * uy + by * ux  # perpendicular offsets of the segment ends
        crosses = (sa * sb <= 0) & (sa != sb)
        length = np.maximum(np.hypot(bx - ax, by - ay), 1e-6)
        parallel = np.abs(sb - sa) / length >= math.cos(math.radians(PARALLEL_MAX_ANGLE_DEG))
        ok = crosses & parallel
        if not ok.any():
            return 0
        t = sa[ok] / (sa[ok] - sb[ok])
        offsets = na[ok] + t * (nb[ok] - na[ok])
        near = np.sort(offsets[np.abs(offsets) <= PARALLEL_RADIUS_M])
        if not len(near):
            return 0
        lines = int(1 + np.count_nonzero(np.diff(near) > SAME_LINE_OFFSET_M))
        apart = (np.abs(offsets) > PARALLEL_RADIUS_M) & (np.abs(offsets) <= SEPARATED_ALIGNMENT_M)
        return 2 if lines == 1 and apart.any() else lines


def _haversine(lon1, lat1, lon2, lat2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * np.arcsin(np.sqrt(a))


def locate_stations(graph: RailGraph, osm: dict[str, Any], coords: dict[str, tuple]) -> dict[str, dict[str, Any]]:
    """Station code -> OSM location and snapped graph node (by OSM ref, else by the open-data coordinate)."""

    by_ref: dict[str, list[dict]] = defaultdict(list)
    for st in osm["stations"]:
        for ref in st["refs"]:
            by_ref[ref].append(st)
    located = {}
    for code, (lat, lon) in coords.items():
        options = by_ref.get(code.upper(), [])
        if options:
            if lat is not None and len(options) > 1:
                options = sorted(options, key=lambda s: (s["lat"] - lat) ** 2 + (s["lon"] - lon) ** 2)
            st = options[0]
            node = graph.snap(st["lon"], st["lat"], SNAP_REF_KM)
            if node is not None:
                located[code] = {"lat": st["lat"], "lon": st["lon"], "node": node, "by": "OSM_REF", "osm_id": st["id"]}
                continue
        if lat is not None:
            node = graph.snap(lon, lat, SNAP_COORD_KM)
            if node is not None:
                located[code] = {"lat": lat, "lon": lon, "node": node, "by": "OPEN_DATA_COORD", "osm_id": None}
    return located


def section_attributes(
    graph: RailGraph, located: dict[str, dict], edges: dict[str, float | None]
) -> dict[str, dict[str, Any]]:
    """Attributes along the mapped path of every section `a-b` (value: timetable rail km or None)."""

    from scipy.sparse.csgraph import dijkstra

    by_source: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for edge in edges:
        a, b = edge.split("-", 1)
        if a in located and b in located:
            by_source[a].append((edge, b))
    out: dict[str, dict[str, Any]] = {}
    for a, targets in by_source.items():
        src = located[a]["node"]
        crow = {
            b: float(
                _haversine(graph.lon[src], graph.lat[src], graph.lon[located[b]["node"]], graph.lat[located[b]["node"]])
            )
            for _, b in targets
        }
        limit = max(2.0 * max(1.6 * crow[b] + 3.0, (edges[e] or 0) * 1.3) for e, b in targets)  # cost units
        dist, pred = dijkstra(graph.matrix, indices=src, limit=limit, return_predecessors=True)
        for edge, b in targets:
            out[edge] = _path_attributes(graph, src, located[b]["node"], dist, pred, crow[b], edges[edge])
    return out


def _path_attributes(graph, src, dst, dist, pred, crow_km, timetable_km) -> dict[str, Any]:
    if not np.isfinite(dist[dst]):
        return {"quality": "NO_MAPPED_PATH"}
    path = [dst]
    while path[-1] != src:
        path.append(int(pred[path[-1]]))
    path.reverse()
    if len(path) < 2:
        return {"quality": "STATIONS_SNAP_TO_SAME_POINT"}
    lon, lat = graph.lon[path], graph.lat[path]
    seg_km = _haversine(lon[:-1], lat[:-1], lon[1:], lat[1:])
    ways = np.array([graph.edge_way[(min(p, q), max(p, q))] for p, q in pairwise(path)], dtype=np.int64)
    length = float(seg_km.sum())
    quality = "ACCEPTED"
    if length > 1.6 * crow_km + 3.0:
        quality = "REJECTED_DETOUR"
    elif timetable_km and abs(length - timetable_km) > max(3.0, 0.2 * timetable_km):
        quality = "REJECTED_DISAGREES_WITH_TIMETABLE_KM"
    el = graph.electrified[ways]
    known = el >= 0
    gauges = graph.gauge[ways]
    speeds = graph.maxspeed[ways]
    service = graph.service[ways]
    gauge = None
    if (gauges > 0).any():
        totals: dict[int, float] = defaultdict(float)
        for g, k in zip(gauges[gauges > 0].tolist(), seg_km[gauges > 0].tolist(), strict=True):
            totals[g] += k
        gauge = max(totals, key=totals.get)
    lines = _sample_lines(graph, lon, lat, seg_km, length)
    single_share, single_run_km = _single_stretches(lines)
    double = bool(lines) and single_share <= SINGLE_SHARE and single_run_km <= SINGLE_RUN_KM
    return {
        "quality": quality,
        "osm_km": round(length, 2),
        "lines": (max(2, int(np.percentile(lines, 10))) if double else 1) if lines else None,
        "lines_median": float(np.median(lines)) if lines else None,
        "single_share": round(single_share, 3) if lines else None,
        "longest_single_km": round(single_run_km, 2) if lines else None,
        "samples": len(lines),
        "electrified_share": round(float(seg_km[known & (el == 1)].sum() / length), 3) if length else None,
        "electrification_known_share": round(float(seg_km[known].sum() / length), 3) if length else None,
        "gauge_mm": gauge,
        "maxspeed_kmph": float(speeds[speeds > 0].min()) if (speeds > 0).any() else None,
        "maxspeed_share": round(float(seg_km[speeds > 0].sum() / length), 3) if length else None,
        "service_share": round(float(seg_km[service].sum() / length), 3) if length else None,
    }


def _single_stretches(lines: list[int]) -> tuple[float, float]:
    """Share of samples reading one line, and the longest run of consecutive single-line samples (km)."""

    if not lines:
        return 1.0, 0.0
    longest = run = 0
    for n in lines:
        run = run + 1 if n == 1 else 0
        longest = max(longest, run)
    return sum(1 for n in lines if n == 1) / len(lines), longest * SAMPLE_STEP_KM


def _sample_lines(graph, lon, lat, seg_km, length) -> list[int]:
    if length <= 0:
        return []
    if length < 2 * STATION_AREA_KM + SAMPLE_STEP_KM:
        marks = [length / 2]
    else:
        marks = list(np.arange(STATION_AREA_KM, length - STATION_AREA_KM, SAMPLE_STEP_KM))
    cum = np.concatenate([[0.0], np.cumsum(seg_km)])
    out = []
    for m in marks:
        i = min(int(np.searchsorted(cum, m, side="right")) - 1, len(seg_km) - 1)
        f = (m - cum[i]) / seg_km[i] if seg_km[i] > 0 else 0.0
        px, py = lon[i] + f * (lon[i + 1] - lon[i]), lat[i] + f * (lat[i + 1] - lat[i])
        n = graph.lines_at(px, py, lon[i + 1] - lon[i], lat[i + 1] - lat[i])
        if n:
            out.append(n)
    return out


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def apply_to_database(pbf: Path, db_path: Path) -> dict[str, Any]:
    """Write `osm_stations` and `osm_sections` into a timetable database (e.g. data/real.sqlite)."""

    osm = extract(pbf)
    graph = RailGraph(osm)
    con = sqlite3.connect(db_path)
    coords = {c: (lat, lon) for c, lat, lon in con.execute("SELECT code, lat, lon FROM stations")}
    try:
        km = dict(con.execute("SELECT edge, km FROM official_section_km").fetchall())
    except sqlite3.OperationalError:
        km = {}
    pairs = {(a, b) if a < b else (b, a) for a, b in con.execute("SELECT DISTINCT from_code, to_code FROM sections")}
    edges = {f"{a}-{b}": km.get(f"{a}-{b}") for a, b in pairs}
    located = locate_stations(graph, osm, coords)
    attrs = section_attributes(graph, located, edges)
    con.executescript(
        """
        DROP TABLE IF EXISTS osm_stations; DROP TABLE IF EXISTS osm_sections;
        CREATE TABLE osm_stations (code TEXT PRIMARY KEY, lat REAL, lon REAL, located_by TEXT, osm_node INTEGER);
        CREATE TABLE osm_sections (edge TEXT PRIMARY KEY, quality TEXT, osm_km REAL, lines INTEGER,
            lines_median REAL, single_share REAL, longest_single_km REAL, samples INTEGER, electrified_share REAL,
            electrification_known_share REAL, gauge_mm INTEGER, maxspeed_kmph REAL, maxspeed_share REAL,
            service_share REAL);
        """
    )
    con.executemany(
        "INSERT INTO osm_stations VALUES (?,?,?,?,?)",
        [(c, v["lat"], v["lon"], v["by"], v["osm_id"]) for c, v in located.items()],
    )
    cols = ("quality", "osm_km", "lines", "lines_median", "single_share", "longest_single_km", "samples",
            "electrified_share",
            "electrification_known_share", "gauge_mm", "maxspeed_kmph", "maxspeed_share", "service_share")  # fmt: skip
    # edge + the 13 columns above (sqlite refuses a row whose length does not match)
    con.executemany(
        "INSERT INTO osm_sections VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(e, *(a.get(c) for c in cols)) for e, a in attrs.items()],
    )
    accepted = [a for a in attrs.values() if a["quality"] == "ACCEPTED"]
    summary = {
        "source": {
            "file": pbf.name,
            "sha256": _file_sha256(pbf),
            "licence": "ODbL-1.0, (c) OpenStreetMap contributors",
            "running_line_ways": int(len(osm["way_id"])),
            "station_nodes": len(osm["stations"]),
        },
        "stations": len(coords),
        "stations_located_by_osm_ref": sum(1 for v in located.values() if v["by"] == "OSM_REF"),
        "stations_located_by_open_data_coordinate": sum(1 for v in located.values() if v["by"] == "OPEN_DATA_COORD"),
        "stations_not_located": len(coords) - len(located),
        "sections": len(edges),
        "sections_with_path": len(attrs),
        "sections_accepted": len(accepted),
        "quality": {
            q: sum(1 for a in attrs.values() if a["quality"] == q) for q in {a["quality"] for a in attrs.values()}
        },
        "accepted_lines": {
            str(n): sum(1 for a in accepted if a["lines"] == n) for n in sorted({a["lines"] for a in accepted}, key=str)
        },
        "accepted_electrified_over_90pct": sum(1 for a in accepted if (a["electrified_share"] or 0) >= 0.9),
        "accepted_gauge": {
            str(g): sum(1 for a in accepted if a["gauge_mm"] == g) for g in {a["gauge_mm"] for a in accepted}
        },
        "accepted_with_tagged_speed": sum(1 for a in accepted if a["maxspeed_kmph"]),
    }
    con.execute("DELETE FROM metadata WHERE key = 'osm_summary'")
    con.execute("INSERT INTO metadata VALUES ('osm_summary', ?)", (json.dumps(summary),))
    con.commit()
    con.close()
    return summary
