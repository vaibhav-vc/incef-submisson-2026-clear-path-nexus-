"""Loop and block-section register: the engineering data Indian Railways holds and the twin cannot infer.

    python -m india_rail register template --out-dir register/ [--pbf data/raw/osm/india.osm.pbf]
    python -m india_rail register validate --dir register/
    python -m india_rail register build --dir register/ --out register.json
    RAILGUARD_REGISTER=register.json python -m india_rail serve

`template` writes two CSV files for every station and every physical section of the twin's network (sections that
are only an express's stop-to-stop path over shorter sections are left out: they take their state from those):

* stations.csv - station_code, name, loops, crossing_allowed (Y/N), platform_lines, interlocking, source,
  effective_from, and hints: the number of parallel tracks OpenStreetMap maps at the station, and how many trains
  halt there;
* sections.csv - section_id, from_code, to_code, length_km, tracks, block_system (ABSOLUTE | AUTOMATIC | IBS |
  TOKEN), headway_min, source, effective_from, and hints: the track count the twin uses now and its evidence.

The operational columns start empty: Indian Railways fills them from its Station Working Rules, working time
table, signalling plans and engineering registers, and names that source. `build` takes only rows whose source is
one of IR_SOURCES - hints from OpenStreetMap or the timetable never become operational data by being copied.

What the twin does with a built register:
* a section's track count replaces the inferred one (labelled IR_REGISTER);
* a section's minimum signalled headway replaces the default separation on that track;
* on single line, a planned wait (a hold or a wait for a path) at a station with no loop is refused: the train
  could not stand clear of the line there.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

IR_SOURCES = ("IR_SWR", "IR_WTT", "IR_SIGNALLING_PLAN", "IR_ENGINEERING")
BLOCK_SYSTEMS = ("ABSOLUTE", "AUTOMATIC", "IBS", "TOKEN")
STATION_COLUMNS = ("station_code", "name", "loops", "crossing_allowed", "platform_lines", "interlocking", "source",
                   "effective_from", "hint_osm_tracks_at_station", "hint_trains_halting")  # fmt: skip
SECTION_COLUMNS = ("section_id", "from_code", "to_code", "length_km", "tracks", "block_system", "headway_min",
                   "source", "effective_from", "hint_twin_tracks", "hint_evidence")  # fmt: skip
STATION_TRACK_WINDOW_M = 120.0  # parallel tracks counted within this distance either side of the station point


# ---- template ---------------------------------------------------------------------------------------------------
def osm_tracks_at_stations(pbf: Path, located: dict[str, tuple[float, float]]) -> dict[str, int]:
    """Parallel tracks (running lines, loops and sidings alike) OpenStreetMap maps across each station point.

    A hint only: a yard or a neighbouring line within the window is counted too, an unmapped loop is not."""

    import numpy as np
    from scipy.spatial import cKDTree

    from india_rail.osm_infra import PARALLEL_MAX_ANGLE_DEG, SAME_LINE_OFFSET_M, extract

    osm = extract(pbf)
    idx = np.searchsorted(osm["node_id"], osm["way_nodes"])
    last = np.zeros(len(idx), dtype=bool)
    last[np.cumsum(osm["way_len"]) - 1] = True
    u, v = idx[:-1][~last[:-1]], idx[1:][~last[:-1]]
    lon, lat = osm["lon"], osm["lat"]
    ok = ~np.isnan(lon[u]) & ~np.isnan(lon[v]) & (u != v)
    x1, y1, x2, y2 = lon[u[ok]], lat[u[ok]], lon[v[ok]], lat[v[ok]]
    kx = 111.32 * math.cos(math.radians(22.0))
    tree = cKDTree(np.c_[(x1 + x2) / 2 * kx, (y1 + y2) / 2 * 110.57])
    out = {}
    for code, (s_lat, s_lon) in sorted(located.items()):
        near = tree.query_ball_point([s_lon * kx, s_lat * 110.57], r=0.4)
        if not near:
            continue
        c = np.array(near)
        mx, my = 111320.0 * math.cos(math.radians(s_lat)), 110574.0
        ax, ay, bx, by = (x1[c] - s_lon) * mx, (y1[c] - s_lat) * my, (x2[c] - s_lon) * mx, (y2[c] - s_lat) * my
        seg = np.hypot(bx - ax, by - ay)
        mid = np.hypot((ax + bx) / 2, (ay + by) / 2)
        k = int(np.argmin(mid))  # the track nearest the station gives the direction of the line
        ux, uy = (bx[k] - ax[k]) / max(seg[k], 1e-6), (by[k] - ay[k]) / max(seg[k], 1e-6)
        sa, sb = ax * ux + ay * uy, bx * ux + by * uy
        na, nb = -ax * uy + ay * ux, -bx * uy + by * ux
        crosses = (sa * sb <= 0) & (sa != sb)
        parallel = np.abs(sb - sa) / np.maximum(seg, 1e-6) >= math.cos(math.radians(PARALLEL_MAX_ANGLE_DEG))
        hit = crosses & parallel
        if not hit.any():
            continue
        t = sa[hit] / (sa[hit] - sb[hit])
        offsets = np.sort(na[hit] + t * (nb[hit] - na[hit]))
        offsets = offsets[np.abs(offsets) <= STATION_TRACK_WINDOW_M]
        if len(offsets):
            out[code] = int(1 + np.count_nonzero(np.diff(offsets) > SAME_LINE_OFFSET_M))
    return out


def template(out_dir: Path, db_path: Path | None = None, pbf: Path | None = None) -> dict[str, Any]:
    import sqlite3

    from india_rail.railguard.national import build_national, timetable_source

    name, default_db = timetable_source()
    db_path = db_path or default_db
    data = build_national(db_path)
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    names = dict(con.execute("SELECT code, name FROM stations"))
    try:
        located = {c: (la, lo) for c, la, lo in con.execute("SELECT code, lat, lon FROM osm_stations")}
    except sqlite3.OperationalError:
        located = {}
    con.close()
    halts: dict[str, set[str]] = {}
    for run in data.runs.values():
        for code in (*run.frm, run.to[-1]):
            halts.setdefault(code, set()).add(run.number)
    physical = sorted(sid for sid in data.network.sections if sid not in data.parts)
    stations = sorted({c for sid in physical for c in sid.split("-", 1)})
    hints = osm_tracks_at_stations(pbf, {c: located[c] for c in stations if c in located}) if pbf else {}
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "stations.csv").open("w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle)
        w.writerow(STATION_COLUMNS)
        for c in stations:
            w.writerow([c, names.get(c, ""), "", "", "", "", "", "", hints.get(c, ""), len(halts.get(c, ()))])
    with (out_dir / "sections.csv").open("w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle)
        w.writerow(SECTION_COLUMNS)
        for sid in physical:
            sec = data.network.sections[sid]
            evidence = next((p.split(":", 1)[1] for p in sec.data_quality.split("|") if p.startswith("tracks:")), "")
            w.writerow([sid, sec.a, sec.b, sec.length_km, "", "", "", "", "", sec.tracks, evidence])
    return {
        "timetable": name,
        "stations": len(stations),
        "stations_with_osm_track_hint": len(hints),
        "physical_sections": len(physical),
        "sections_left_out_as_paths_over_shorter_sections": len(data.parts),
        "files": [str(out_dir / "stations.csv"), str(out_dir / "sections.csv")],
    }


# ---- validate and build -----------------------------------------------------------------------------------------
def _rows(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != columns:
            raise ValueError(f"{path.name}: header must be exactly {','.join(columns)}")
        return [{k: (v or "").strip() for k, v in row.items()} for row in reader]


def _int(value: str, lo: int, hi: int, what: str, problems: list[str]) -> int | None:
    if value == "":
        return None
    try:
        n = int(value)
    except ValueError:
        problems.append(f"{what} must be a whole number")
        return None
    if not lo <= n <= hi:
        problems.append(f"{what} must be {lo}-{hi}")
    return n


def check(folder: Path) -> dict[str, Any]:
    """Every row checked on its own and for consistency; returns the usable rows and every problem found."""

    stations, sections, problems = {}, {}, []
    for row in _rows(folder / "stations.csv", STATION_COLUMNS):
        p: list[str] = []
        code = row["station_code"]
        loops = _int(row["loops"], 0, 30, "loops", p)
        platforms = _int(row["platform_lines"], 0, 40, "platform_lines", p)
        crossing = row["crossing_allowed"].upper() or None
        if crossing not in (None, "Y", "N"):
            p.append("crossing_allowed must be Y or N")
        if crossing == "Y" and loops == 0:
            p.append("crossing_allowed=Y with no loop: two trains cannot cross where neither can stand clear")
        filled = any(v is not None for v in (loops, platforms, crossing)) or row["interlocking"]
        if filled and row["source"] not in IR_SOURCES:
            p.append(f"source must be one of {IR_SOURCES} (an Indian Railways document) for a value to be used")
        if filled:
            try:
                date.fromisoformat(row["effective_from"])
            except ValueError:
                p.append("effective_from must be YYYY-MM-DD")
        if code in stations:
            p.append("station listed twice")
        problems += [f"stations.csv {code}: {x}" for x in p]
        if filled and not p:
            stations[code] = {"loops": loops, "crossing_allowed": crossing, "platform_lines": platforms,
                              "interlocking": row["interlocking"] or None, "source": row["source"],
                              "effective_from": row["effective_from"]}  # fmt: skip
    for row in _rows(folder / "sections.csv", SECTION_COLUMNS):
        p = []
        sid = row["section_id"]
        a, b = sid.split("-", 1) if "-" in sid else (sid, "")
        if f"{min(a, b)}-{max(a, b)}" != sid:
            p.append("section_id must be the two station codes sorted, joined by '-'")
        tracks = _int(row["tracks"], 1, 8, "tracks", p)
        block = row["block_system"].upper() or None
        if block not in (None, *BLOCK_SYSTEMS):
            p.append(f"block_system must be one of {BLOCK_SYSTEMS}")
        headway = None
        if row["headway_min"]:
            try:
                headway = float(row["headway_min"])
                if not 1.0 <= headway <= 30.0:
                    p.append("headway_min must be 1-30")
            except ValueError:
                p.append("headway_min must be a number")
        if block == "TOKEN" and tracks not in (None, 1):
            p.append("TOKEN working is single-line working")
        filled = any(v is not None for v in (tracks, block, headway))
        if filled and row["source"] not in IR_SOURCES:
            p.append(f"source must be one of {IR_SOURCES} (an Indian Railways document) for a value to be used")
        if filled:
            try:
                date.fromisoformat(row["effective_from"])
            except ValueError:
                p.append("effective_from must be YYYY-MM-DD")
        if sid in sections:
            p.append("section listed twice")
        problems += [f"sections.csv {sid}: {x}" for x in p]
        if filled and not p:
            sections[sid] = {"tracks": tracks, "block_system": block, "headway_min": headway,
                             "source": row["source"], "effective_from": row["effective_from"]}  # fmt: skip
    return {"stations": stations, "sections": sections, "problems": problems}


def build(folder: Path, out: Path) -> dict[str, Any]:
    result = check(folder)
    if result["problems"]:
        raise ValueError(f"{len(result['problems'])} problems; first: {result['problems'][0]}")
    digest = {n: hashlib.sha256((folder / n).read_bytes()).hexdigest() for n in ("stations.csv", "sections.csv")}
    register = {
        "kind": "Clear Path Nexus loop and block-section register",
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_files_sha256": digest,
        "stations": result["stations"],
        "sections": result["sections"],
    }
    out.write_text(json.dumps(register, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return {"stations": len(register["stations"]), "sections": len(register["sections"]), "out": str(out)}


def load(path: Path) -> dict[str, Any]:
    register = json.loads(path.read_text(encoding="utf-8"))
    if register.get("kind") != "Clear Path Nexus loop and block-section register":
        raise ValueError(f"{path} is not a register built by `python -m india_rail register build`")
    for row in (*register["stations"].values(), *register["sections"].values()):
        if row.get("source") not in IR_SOURCES:
            raise ValueError("register rows must come from Indian Railways sources")
    register["checksum"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return register


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m india_rail register", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("template", help="write stations.csv and sections.csv for Indian Railways to fill in")
    t.add_argument("--out-dir", type=Path, required=True)
    t.add_argument("--db", type=Path, help="timetable database (default: the configured one)")
    t.add_argument("--pbf", type=Path, help="OpenStreetMap extract, for the track-count hint at stations")
    v = sub.add_parser("validate", help="check a filled register")
    v.add_argument("--dir", type=Path, required=True)
    b = sub.add_parser("build", help="write the register file the twin loads (RAILGUARD_REGISTER)")
    b.add_argument("--dir", type=Path, required=True)
    b.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "template":
        print(json.dumps(template(args.out_dir, args.db, args.pbf), indent=2))
        return 0
    if args.command == "validate":
        result = check(args.dir)
        print(json.dumps({"stations_usable": len(result["stations"]), "sections_usable": len(result["sections"]),
                          "problems": len(result["problems"])}, indent=2))  # fmt: skip
        for p in result["problems"][:200]:
            print(p)
        return 1 if result["problems"] else 0
    print(json.dumps(build(args.dir, args.out), indent=2))
    return 0
