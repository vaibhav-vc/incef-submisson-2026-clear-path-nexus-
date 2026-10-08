"""Real-life running data: the September 2024 timetable and the trains' *actual* arrival times.

    python -m india_rail real fetch       # download and verify (SHA-256) the observed-running dataset
    python -m india_rail real build       # build data/real.sqlite: timetable, real running days, observations
    python -m india_rail real osm --pbf data/raw/osm/india.osm.pbf   # add real track data (see osm_infra.py)
    python -m india_rail real validate    # verify the system against what actually happened

Source: K. Chowdhury, P. Koley, A. Chakraborty, S. Ghosh (IIT Kharagpur), "Indian Railway Network and
Delays", published with "RSTGCN", IEEE Transactions on Intelligent Transportation Systems, 2026. For
57,485 train runs in September 2024 it lists, at every reporting station, the scheduled and the *actual*
arrival time, as collected by the authors from a public running-status service.

Licence position: the authors publish it "for research and development" and ask for citation; no licence
file is attached, and the underlying observations come from Indian Railways' NTES, whose terms restrict
reuse. The file is therefore downloaded by the user, verified by its pinned digest, kept under data/
(git-ignored) and never redistributed. Only aggregate validation results derived from it are published.
For operation, the authorised NTES/COA feed (railguard/livefeed.py) replaces it.

What the data can and cannot show (checked on the file, see `profile`):
  * actual *arrival* times are observed; the departure columns equal arrival + scheduled halt at every one
    of the 1.28M rows, so they are derived and are not used;
  * early running is recorded as 0 minutes late (delays are clipped at zero);
  * freight and suburban trains are not included.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sqlite3
import urllib.request
import zipfile
from collections import defaultdict
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Any

from india_rail.ingest import DATA_DIR, DB_PATH, RAW_DIR, SCHEMA, haversine_km

REAL_DB_PATH = DATA_DIR / "real.sqlite"
OBSERVED = {
    "key": "observed_running_sep2024",
    "url": (
        "https://raw.githubusercontent.com/KoyenaChowdhury/RSTGCN/"
        "160da04cd3b5dd72588b6cc72b08e84e0b7210b4/Indian-Railway-Network-and-Delays.zip"
    ),
    "sha256": "f8a6fe9e70972acb8ad98bbe5b7eb594c5b6b3475e21efd6d3b9e19049bdaf91",
    "publisher": "Chowdhury, Koley, Chakraborty, Ghosh - IIT Kharagpur (IEEE T-ITS 2026, arXiv:2510.01262)",
    "licence": "No licence stated; published for research with a citation request. Not redistributed.",
    "period": "2024-09-01 to 2024-09-30",
}
MEMBER = "Indian-Railway-Network-and-Delays/{}"
MAX_ZIP_BYTES = 64 * 1024 * 1024
EXTREME_DELAY_MIN = 720  # a reported delay above 12 h is kept but excluded from accuracy statistics
DAILY_MIN_DAYS = 26  # observed on at least this many of the 30 days: runs daily
PLACEHOLDER_SHARE = 0.3  # a timetable with more zero-minute sections than this lists placeholder times
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Train type from the 2024 name, then from Indian Railways' five-digit numbering scheme. Numbers are reused
# over the years (12790 was a Kanyakumari train in 2016 and a Secunderabad one in 2024), so the type is not
# taken from an older timetable by number.
NAME_TYPES = (
    (r"rajdhani", "Raj"),
    (r"jan ?shat", "JShtb"),
    (r"shatabdi|shatbdi|vande ?bharat|tejas|gatimaan", "Shtb"),
    (r"duronto", "Drnt"),
    (r"garib rath", "GR"),
    (r"sampark|smprk", "SKr"),
    (r"memu", "MEMU"),
    (r"demu", "DEMU"),
    (r"passenger|\bpass\b|local", "Pass"),
    (r"\bmail\b", "Mail"),
    (r"\bsf\b|superfast|humsafar|antyodaya|uday|amrit bharat", "SF"),
)
NUMBER_TYPES = {"5": "Pass", "6": "MEMU", "7": "DEMU"}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(raw_dir: Path = RAW_DIR) -> Path:
    """Download the observed-running archive once and verify its pinned SHA-256."""

    target = raw_dir / "observed_running_sep2024.zip"
    if not target.exists():
        raw_dir.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(OBSERVED["url"], timeout=300) as response:  # nosec B310 - pinned https URL
            data = response.read(MAX_ZIP_BYTES + 1)
        if len(data) > MAX_ZIP_BYTES:
            raise ValueError("observed-running archive exceeds the size limit")
        if _sha256(data) != OBSERVED["sha256"]:
            raise ValueError("observed-running archive does not match its pinned SHA-256; not used")
        target.write_bytes(data)
    elif _sha256(target.read_bytes()) != OBSERVED["sha256"]:
        raise ValueError(f"{target} does not match the pinned SHA-256; delete it and fetch again")
    return target


def _read_csv(archive: zipfile.ZipFile, name: str):
    import pandas as pd

    with archive.open(MEMBER.format(name)) as handle:  # fixed member names only: no path from the archive
        return pd.read_csv(io.BytesIO(handle.read()), dtype=str)


def clock12(series) -> Any:
    """'08:05 PM' -> minutes after midnight (NaN when unparsable)."""

    import pandas as pd

    parsed = pd.to_datetime(series, format="%I:%M %p", errors="coerce")
    return parsed.dt.hour * 60 + parsed.dt.minute


def _advance(previous_abs: int, clock: int) -> tuple[int, bool]:
    """Place a clock time at or after `previous_abs` (a backward step over 12 h is a midnight crossing)."""

    delta = clock - previous_abs % 1440
    if delta >= 0:
        return previous_abs + delta, False
    if delta <= -720:
        return previous_abs + delta + 1440, False
    return previous_abs, True  # small backward step: a source error, clamped (counted)


def train_type(number: str, name: str) -> tuple[str, str]:
    lowered = (name or "").lower()
    for pattern, ttype in NAME_TYPES:
        if re.search(pattern, lowered):
            return ttype, "NAME"
    if number[:1] in NUMBER_TYPES:
        return NUMBER_TYPES[number[:1]], "NUMBER_SCHEME"
    if number[:1] in "12" and number[1:2] == "2":
        return "SF", "NUMBER_SCHEME"  # 12xxx / 22xxx are superfast services
    return "Exp", "DEFAULT_EXPRESS"


def build(zip_path: Path, base_db: Path = DB_PATH, out_db: Path = REAL_DB_PATH) -> dict[str, Any]:
    """Build a database with the September 2024 timetable, real running days and actual arrivals.

    It has the same tables as the open-data database, so the national twin builds from it unchanged.
    """

    import pandas as pd

    archive = zipfile.ZipFile(zip_path)
    routes = _read_csv(archive, "train_routes_Sep2024.csv")
    observed = _read_csv(archive, "train_routes_delays_Sep2024.csv")
    zones = json.loads(archive.read(MEMBER.format("stations_zones_mapping.json")))
    report: dict[str, Any] = {"source": OBSERVED, "clamped_backward_times": 0, "duplicate_stops_dropped": 0,
                              "trains_with_placeholder_timetable_excluded": []}  # fmt: skip

    base = sqlite3.connect(f"file:{base_db}?mode=ro", uri=True)
    stations = {r[0]: list(r) for r in base.execute("SELECT code, name, zone, state, lat, lon FROM stations")}
    base.close()

    # ---- timetable (September 2024) ----------------------------------------------------------------
    routes["seq_src"] = routes["stnSerialNumber"].astype(int)
    routes["arr"] = clock12(routes["arrivalTime"])
    routes["dep"] = clock12(routes["departureTime"])
    routes["km"] = pd.to_numeric(routes["distance"], errors="coerce")
    routes = routes.sort_values(["trainNumber", "seq_src"])
    stop_rows, section_rows, train_rows, km_by_edge = [], [], [], defaultdict(list)
    seq_of: dict[str, dict[str, list[int]]] = {}
    sched_abs: dict[tuple[str, int], int] = {}
    type_sources: dict[str, int] = defaultdict(int)
    for number, g in routes.groupby("trainNumber", sort=False):
        timed, previous = [], None
        for code, sname, arr, dep, km in zip(g.station_code, g.station_name, g.arr, g.dep, g.km, strict=True):
            if pd.isna(arr) and pd.isna(dep):
                continue
            arr = int(dep if pd.isna(arr) else arr)
            dep = int(arr if pd.isna(dep) else dep)
            if previous is None:
                abs_arr = arr
            else:
                abs_arr, clamped = _advance(previous, arr)
                report["clamped_backward_times"] += clamped
            abs_dep, clamped = _advance(abs_arr, dep)
            report["clamped_backward_times"] += clamped
            if timed and timed[-1][0] == code:
                report["duplicate_stops_dropped"] += 1
                continue
            timed.append((code, sname, abs_arr, abs_dep, None if pd.isna(km) else float(km)))
            previous = abs_dep
        if len(timed) < 2:
            continue
        zero = sum(1 for x, y in pairwise(timed) if y[2] == x[3])
        if zero / (len(timed) - 1) > PLACEHOLDER_SHARE:
            # e.g. 18236 in this file: all 43 stops at 06:20. Its "actual" times (scheduled + delay) mean nothing.
            report["trains_with_placeholder_timetable_excluded"].append(number)
            continue
        seqs: dict[str, list[int]] = defaultdict(list)
        for seq, (code, sname, arr, dep, _km) in enumerate(timed):
            stop_rows.append((number, seq, code, sname, arr, dep, dep - arr))
            seqs[code].append(seq)
            sched_abs[(number, seq)] = arr
            if code not in stations:
                stations[code] = [code, sname, zones.get(code), None, None, None]
            elif not stations[code][2] and zones.get(code):
                stations[code][2] = zones[code]
        seq_of[number] = seqs
        for seq in range(len(timed) - 1):
            (a, _, _, a_dep, a_km), (b, _, b_arr, _, b_km) = timed[seq], timed[seq + 1]
            sa, sb = stations.get(a), stations.get(b)
            crow = haversine_km(sa[4], sa[5], sb[4], sb[5]) if sa and sb and sa[4] is not None and sb[4] else None
            section_rows.append((number, seq, a, b, a_dep, b_arr, b_arr - a_dep, crow))
            if a_km is not None and b_km is not None and b_km > a_km:
                edge = f"{a}-{b}" if a < b else f"{b}-{a}"
                km_by_edge[edge].append(b_km - a_km)
        name = g.trainName.iloc[0]
        ttype, src = train_type(number, name)
        type_sources[src] += 1
        last_km = timed[-1][4]
        train_rows.append(
            (
                number,
                name,
                ttype,
                None,
                timed[0][0],
                timed[-1][0],
                last_km,
                None,
                len(timed),
                timed[-1][2] - timed[0][3],
            )
        )

    # ---- observed actual arrivals -------------------------------------------------------------------
    observed["delay"] = pd.to_numeric(observed["arr_delay"], errors="coerce")
    excluded = set(report["trains_with_placeholder_timetable_excluded"])
    report["observations_of_excluded_trains"] = int(observed.train.isin(excluded).sum())
    observed = observed[~observed.train.isin(excluded)]
    obs_rows, misaligned = [], 0
    days_seen: dict[str, set[str]] = defaultdict(set)
    for (number, day), g in observed.groupby(["train", "date"], sort=False):
        seqs = seq_of.get(number)
        if not seqs:
            misaligned += len(g)
            continue
        days_seen[number].add(day)
        cursor = -1
        for code, delay in zip(g.station, g.delay, strict=True):
            after = [s for s in seqs.get(code, ()) if s > cursor]
            if not after or pd.isna(delay):
                misaligned += 1
                continue
            cursor = after[0]
            sch = sched_abs[(number, cursor)]
            obs_rows.append((number, day, cursor, code, sch, sch + int(delay), int(delay)))
    report["observations_not_aligned_to_timetable"] = misaligned

    # ---- real running days: the weekdays on which each train was actually seen starting its journey --
    details = []
    for number, name, ttype, *_ in train_rows:
        seen = days_seen.get(number, set())
        weekdays = sorted({date.fromisoformat(d).weekday() for d in seen})
        if len(seen) >= DAILY_MIN_DAYS:
            running = "Daily"
        elif weekdays:
            running = ",".join(WEEKDAYS[w] for w in weekdays)
        else:
            running = None  # never observed: unknown (the twin then treats it as daily, the safe side)
        details.append((number, name, ttype, None, None, None, None, None, None, None, None, None, running, 1))

    if out_db.exists():
        out_db.unlink()
    out_db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(out_db)
    con.executescript(SCHEMA)
    con.executescript(
        """
        CREATE TABLE official_section_km (edge TEXT PRIMARY KEY, km REAL);
        CREATE TABLE observed_stops (train_number TEXT NOT NULL, run_date TEXT NOT NULL, seq INTEGER NOT NULL,
            station_code TEXT NOT NULL, sch_arr_min INTEGER NOT NULL, act_arr_min INTEGER NOT NULL,
            delay_min INTEGER NOT NULL, PRIMARY KEY (train_number, run_date, seq));
        CREATE INDEX observed_run ON observed_stops(run_date, train_number);
        """
    )
    con.executemany("INSERT INTO stations VALUES (?,?,?,?,?,?)", [tuple(v) for v in stations.values()])
    con.executemany("INSERT INTO trains VALUES (?,?,?,?,?,?,?,?,?,?)", train_rows)
    con.executemany("INSERT INTO train_details VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", details)
    con.executemany("INSERT INTO stops VALUES (?,?,?,?,?,?,?)", stop_rows)
    con.executemany("INSERT INTO sections VALUES (?,?,?,?,?,?,?,?)", section_rows)
    # Rail distance per section from the timetable's cumulative km (median over the trains that list it).
    con.executemany(
        "INSERT INTO official_section_km VALUES (?,?)",
        [(edge, sorted(v)[len(v) // 2]) for edge, v in km_by_edge.items()],
    )
    con.executemany("INSERT INTO observed_stops VALUES (?,?,?,?,?,?,?)", obs_rows)
    runs = len({(r[0], r[1]) for r in obs_rows})
    report["trains_with_placeholder_timetable_excluded"] = len(excluded)
    report.update(
        trains=len(train_rows),
        stops=len(stop_rows),
        sections=len(section_rows),
        section_edges_with_rail_km=len(km_by_edge),
        stations=len(stations),
        stations_without_coordinates=sum(1 for v in stations.values() if v[4] is None),
        train_type_source=dict(type_sources),
        observed_runs=runs,
        observed_arrivals=len(obs_rows),
        trains_with_running_days=sum(1 for d in details if d[12]),
        trains_daily=sum(1 for d in details if d[12] == "Daily"),
    )
    con.executemany(
        "INSERT INTO metadata VALUES (?,?)",
        [("real_source", json.dumps(OBSERVED)), ("real_build_report", json.dumps(report, default=str))],
    )
    con.commit()
    con.close()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="india_rail real", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch", help="download and verify the observed-running dataset")
    sub.add_parser("build", help="build data/real.sqlite")
    osm = sub.add_parser("osm", help="add real infrastructure from an OpenStreetMap extract")
    osm.add_argument("--pbf", type=Path, required=True)
    validate = sub.add_parser("validate", help="verify the system against the real running data")
    validate.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.command == "fetch":
        print(fetch())
    elif args.command == "build":
        print(json.dumps(build(fetch()), indent=2, default=str))
    elif args.command == "osm":
        from india_rail.osm_infra import apply_to_database

        print(json.dumps(apply_to_database(args.pbf, REAL_DB_PATH), indent=2))
    else:
        from india_rail.realval import validate_all

        print(json.dumps(validate_all(out=args.out), indent=2, default=str))
    return 0
