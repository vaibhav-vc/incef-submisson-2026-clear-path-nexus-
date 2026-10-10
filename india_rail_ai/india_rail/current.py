"""Every train running now: the current all-India timetable, a registry of all trains, and station PIN codes.

    python -m india_rail current fetch     # download the current timetable (GTFS), pinned by SHA-256
    python -m india_rail current build     # data/current.sqlite: all trains, stops, running days, registry
    python -m india_rail real osm --pbf data/raw/osm/india.osm.pbf --db current   # real track for every section
    python -m india_rail current pins --pbf data/raw/osm/india.osm.pbf           # station PIN codes

Source: "Indian Railways GTFS", published by P. Radha Krishna (github.com/Neo2308/indianrailways-gtfs), the
community feed used by Transitous and the Mobility Database. The pinned version is valid 30 August to
30 September 2026 and lists 10,594 trains with every halt, time, running days and validity dates. It is
unofficial and carries no licence: like the observed-running data it is fetched by the user, verified by SHA-256,
kept in git-ignored data/ and never redistributed. The official CRIS timetable replaces it when authorised.

The registry joins every train number seen in any source (current 2026, observed 2024, open 2016) with its name,
type, operator (Indian Railways, IRCTC-operated private trains, Bharat Gaurav, luxury tourist, parcel/cargo,
rapid rail), route, running days, and whether real running was observed for it.

Station PIN codes come from OpenStreetMap postcodes (ODbL): the station's own postcode, else the most common
postcode among tagged places within 2 km, and only if its first digit matches the India Post zone of the
station's state. These are approximate (the PIN of the locality around the station) until India Post or IR
station records are loaded. Passenger booking records (PNR) are personal data held by IRCTC/CRIS and are not collected.
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
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from india_rail.ingest import DATA_DIR, DB_PATH, RAW_DIR, SCHEMA, haversine_km
from india_rail.realdata import PLACEHOLDER_SHARE, REAL_DB_PATH, train_type

CURRENT_DB_PATH = DATA_DIR / "current.sqlite"
FEED = {
    "key": "current_timetable_gtfs",
    "url": (
        "https://raw.githubusercontent.com/Neo2308/indianrailways-gtfs/"
        "b340b7048e99c18330ad333e8210d61161ac7a43/gtfs/gtfs.zip"
    ),
    "sha256": "a0347d046ccc66b182f08df88dd5eb6153fd19610a58c87d14e1e6910c937be8",
    "publisher": "P. Radha Krishna, Indian Railways GTFS (github.com/Neo2308/indianrailways-gtfs)",
    "licence": "No licence stated; community feed. Used locally, not redistributed; replaced by the CRIS timetable.",
}
MAX_ZIP_BYTES = 32 * 1024 * 1024
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Who runs the train. Numbers 82xxx are IRCTC-operated ("private") trains; the rest follow the name.
OPERATORS = (
    (r"^82\d{3}$", None, "IRCTC (private operation)"),
    (None, r"bharat gaurav", "Bharat Gaurav (service provider operated)"),
    (None, r"palace on wheel|maharaja|deccan odyssey|golden chariot|royal rajasthan", "Luxury tourist train"),
    (None, r"cargo|parcel|goods|freight|kisan rail", "Parcel / cargo"),
    (None, r"namo bharat|rapid rail|rrts", "Rapid rail"),
)
# First digit of the PIN code by state (India Post postal zones).
PIN_ZONE = {
    "1": {
        "Delhi",
        "Haryana",
        "Punjab",
        "Himachal Pradesh",
        "Jammu and Kashmir",
        "Jammu & Kashmir",
        "Chandigarh",
        "Ladakh",
    },
    "2": {"Uttar Pradesh", "Uttarakhand"},
    "3": {"Rajasthan", "Gujarat", "Daman and Diu", "Dadra and Nagar Haveli"},
    "4": {"Maharashtra", "Madhya Pradesh", "Chhattisgarh", "Goa"},
    "5": {"Andhra Pradesh", "Telangana", "Karnataka"},
    "6": {"Tamil Nadu", "Kerala", "Puducherry", "Lakshadweep"},
    "7": {
        "West Bengal",
        "Odisha",
        "Orissa",
        "Assam",
        "Arunachal Pradesh",
        "Manipur",
        "Meghalaya",
        "Mizoram",
        "Nagaland",
        "Tripura",
        "Sikkim",
        "Andaman and Nicobar Islands",
    },  # fmt: skip
    "8": {"Bihar", "Jharkhand"},
}
PIN = re.compile(r"^[1-9]\d{5}$")
PIN_RINGS_KM = (0.5, 1.0, 2.0)
PIN_MIN_VOTES_TO_OVERRULE_TAG = 5


def operator_of(number: str, name: str) -> str:
    lowered = (name or "").lower()
    for number_pattern, name_pattern, label in OPERATORS:
        if number_pattern and re.match(number_pattern, number):
            return label
        if name_pattern and re.search(name_pattern, lowered):
            return label
    return "Indian Railways"


def fetch(raw_dir: Path = RAW_DIR) -> Path:
    target = raw_dir / "current_timetable_gtfs.zip"
    if not target.exists():
        raw_dir.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(FEED["url"], timeout=300) as response:  # nosec B310 - pinned https URL
            data = response.read(MAX_ZIP_BYTES + 1)
        if len(data) > MAX_ZIP_BYTES or hashlib.sha256(data).hexdigest() != FEED["sha256"]:
            raise ValueError("current timetable does not match its pinned SHA-256 (or is too large); not used")
        target.write_bytes(data)
    elif hashlib.sha256(target.read_bytes()).hexdigest() != FEED["sha256"]:
        raise ValueError(f"{target} does not match the pinned SHA-256; delete it and fetch again")
    return target


def _minutes(value: Any) -> int | None:
    """GTFS 'HH:MM:SS' (hours may exceed 24 on later journey days) -> journey minutes."""

    if not isinstance(value, str) or ":" not in value:
        return None
    hours, minutes, *_ = value.split(":")
    try:
        return int(hours) * 60 + int(minutes)
    except ValueError:
        return None


def _days(row: dict[str, Any]) -> str | None:
    flags = [row.get(day) == "1" for day in WEEKDAYS]
    if all(flags):
        return "Daily"
    return ",".join(name for name, on in zip(DAY_NAMES, flags, strict=True) if on) or None


def build(
    zip_path: Path, out_db: Path = CURRENT_DB_PATH, open_db: Path = DB_PATH, real_db: Path = REAL_DB_PATH
) -> dict:
    """All trains in the current timetable, in the schema the national twin reads, plus the registry."""

    import pandas as pd

    archive = zipfile.ZipFile(zip_path)

    def table(name: str):
        return pd.read_csv(io.BytesIO(archive.read(name)), dtype=str, keep_default_na=False)

    stops_txt, routes, trips, times, calendar = (
        table(f"{n}.txt") for n in ("stops", "routes", "trips", "stop_times", "calendar")
    )
    feed_info = table("feed_info.txt").iloc[0].to_dict()
    report: dict[str, Any] = {"source": FEED, "feed_valid": [feed_info["feed_start_date"], feed_info["feed_end_date"]]}

    zone_state: dict[str, tuple] = {}
    for db in (open_db, real_db):
        if db.exists():
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            for code, zone, state in con.execute("SELECT code, zone, state FROM stations"):
                old = zone_state.get(code, (None, None))
                zone_state[code] = (old[0] or zone, old[1] or state)
            con.close()
    stations = {}
    for row in stops_txt.itertuples():
        lat, lon = (float(row.stop_lat), float(row.stop_lon)) if row.stop_lat and row.stop_lon else (None, None)
        zone, state = zone_state.get(row.stop_id, (None, None))
        stations[row.stop_id] = [row.stop_id, row.stop_name.strip(), zone, state, lat, lon]

    trip_meta = trips.merge(routes, on="route_id").merge(calendar, on="service_id", how="left")
    times["seq"] = times.stop_sequence.astype(int)
    times = times.sort_values(["trip_id", "seq"])
    by_trip = dict(list(times.groupby("trip_id", sort=False)))  # (key, frame) pairs
    train_rows, details, stop_rows, section_rows, km_by_edge = [], [], [], [], defaultdict(list)
    placeholder, operators, types = [], Counter(), Counter()
    for meta in trip_meta.to_dict("records"):
        number, name = meta["route_short_name"], meta["route_long_name"].strip()
        g = by_trip.get(meta["trip_id"])
        if g is None or len(g) < 2:
            continue
        arr = [_minutes(a) if a else _minutes(d) for a, d in zip(g.arrival_time, g.departure_time, strict=True)]
        dep = [_minutes(d) if d else a for d, a in zip(g.departure_time, arr, strict=True)]
        codes, km = g.stop_id.tolist(), pd.to_numeric(g.shape_dist_traveled, errors="coerce").tolist()
        if any(x is None for x in arr + dep):
            continue
        zero = sum(1 for k in range(len(codes) - 1) if arr[k + 1] == dep[k])
        ttype, _src = train_type(number, name)
        operator = operator_of(number, name)
        operators[operator] += 1
        types[ttype] += 1
        running = _days(meta)
        details.append((number, name, ttype, None, codes[0], codes[-1], None, None, None, None, None, None, running, 1))
        if zero / (len(codes) - 1) > PLACEHOLDER_SHARE:
            placeholder.append(number)  # listed in the registry, kept out of the time-based twin
            continue
        for k, code in enumerate(codes):
            stop_rows.append((number, k, code, stations.get(code, [code, code])[1], arr[k], dep[k], dep[k] - arr[k]))
        for k in range(len(codes) - 1):
            a, b = codes[k], codes[k + 1]
            sa, sb = stations.get(a), stations.get(b)
            crow = (
                haversine_km(sa[4], sa[5], sb[4], sb[5])
                if sa and sb and sa[4] is not None and sb[4] is not None
                else None
            )
            section_rows.append((number, k, a, b, dep[k], arr[k + 1], arr[k + 1] - dep[k], crow))
            if km[k] == km[k] and km[k + 1] == km[k + 1] and km[k + 1] > km[k]:
                km_by_edge[f"{a}-{b}" if a < b else f"{b}-{a}"].append(km[k + 1] - km[k])
        train_rows.append((number, name, ttype, stations.get(codes[0], [None] * 3)[2], codes[0], codes[-1],
                           km[-1] if km[-1] == km[-1] else None, None, len(codes), arr[-1] - dep[0]))  # fmt: skip

    if out_db.exists():
        out_db.unlink()
    out_db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(out_db)
    con.executescript(SCHEMA)
    con.executescript(
        """
        CREATE TABLE official_section_km (edge TEXT PRIMARY KEY, km REAL);
        CREATE TABLE train_registry (number TEXT PRIMARY KEY, name TEXT, type TEXT, operator TEXT,
            from_code TEXT, to_code TEXT, n_stops INTEGER, running_days TEXT, valid_from TEXT, valid_to TEXT,
            in_current_2026 INTEGER, in_timetable_2024 INTEGER, in_open_2016 INTEGER, real_running_observed INTEGER,
            in_twin INTEGER, note TEXT);
        CREATE TABLE station_pin (code TEXT PRIMARY KEY, pin TEXT, source TEXT, votes INTEGER);
        """
    )
    con.executemany("INSERT INTO stations VALUES (?,?,?,?,?,?)", [tuple(v) for v in stations.values()])
    con.executemany("INSERT INTO trains VALUES (?,?,?,?,?,?,?,?,?,?)", train_rows)
    con.executemany("INSERT INTO train_details VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", details)
    con.executemany("INSERT INTO stops VALUES (?,?,?,?,?,?,?)", stop_rows)
    con.executemany("INSERT INTO sections VALUES (?,?,?,?,?,?,?,?)", section_rows)
    con.executemany("INSERT INTO official_section_km VALUES (?,?)",
                    [(e, sorted(v)[len(v) // 2]) for e, v in km_by_edge.items()])  # fmt: skip

    registry = _registry(trip_meta, set(placeholder), {r[0] for r in train_rows}, open_db, real_db,
                         feed_info["feed_start_date"])  # fmt: skip
    con.executemany("INSERT INTO train_registry VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", registry)
    report.update(
        trains_in_feed=len(details),
        trains_in_twin=len(train_rows),
        trains_with_placeholder_times=len(placeholder),
        stops=len(stop_rows),
        sections=len(section_rows),
        stations=len(stations),
        operators=dict(operators),
        types=dict(types),
        registry_total=len(registry),
        registry_only_older_sources=sum(1 for r in registry if not r[10]),
        registry_with_real_running_observed=sum(1 for r in registry if r[13]),
    )
    con.execute("INSERT INTO metadata VALUES ('current_build_report', ?)", (json.dumps(report, default=str),))
    con.commit()
    con.close()
    return report


def _registry(
    trip_meta, placeholder: set[str], in_twin: set[str], open_db: Path, real_db: Path, feed_start: str
) -> list[tuple]:
    def numbers(db: Path, sql: str) -> dict[str, tuple]:
        if not db.exists():
            return {}
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return {r[0]: r[1:] for r in con.execute(sql)}
        finally:
            con.close()

    open_trains = numbers(open_db, "SELECT number, name, type, from_code, to_code, n_stops FROM trains")
    real_trains = numbers(real_db, "SELECT number, name, type, from_code, to_code, n_stops FROM trains")
    observed = numbers(real_db, "SELECT DISTINCT train_number, 1 FROM observed_stops")
    rows: dict[str, tuple] = {}
    for m in trip_meta.to_dict("records"):
        number, name = m["route_short_name"], m["route_long_name"].strip()
        note = "placeholder times in source" if number in placeholder else None
        if isinstance(m.get("end_date"), str) and m["end_date"] < feed_start:
            note = "service ended before the feed period"
        rows[number] = (number, name, train_type(number, name)[0], operator_of(number, name), None, None, None,
                        _days(m), _text(m.get("start_date")), _text(m.get("end_date")), 1, int(number in real_trains),
                        int(number in open_trains), int(number in observed), int(number in in_twin), note)  # fmt: skip
    for source, flag in ((real_trains, "timetable 2024 only"), (open_trains, "open data 2016 only")):
        for number, (name, ttype, frm, to, n_stops) in source.items():
            if number not in rows:
                rows[number] = (number, name, ttype, operator_of(number, name or ""), frm, to, n_stops, None, None,
                                None, 0, int(number in real_trains), int(number in open_trains),
                                int(number in observed), 0, flag)  # fmt: skip
    return list(rows.values())


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def station_pins(pbf: Path, db: Path = CURRENT_DB_PATH) -> dict[str, Any]:
    """PIN code of every station from OpenStreetMap postcodes (own tag, else majority within 2 km), zone-checked."""

    import numpy as np
    import osmium
    from osmium.filter import KeyFilter
    from scipy.spatial import cKDTree

    own: dict[str, str] = {}
    pts, codes = [], []
    for obj in osmium.FileProcessor(str(pbf), osmium.osm.NODE).with_filter(KeyFilter("addr:postcode", "postal_code")):
        pin = (obj.tags.get("addr:postcode") or obj.tags.get("postal_code") or "").replace(" ", "")
        if not PIN.match(pin):
            continue
        if obj.tags.get("railway") in ("station", "halt"):
            for ref in re.split(r"[;,]", obj.tags.get("ref", "") + ";" + obj.tags.get("railway:ref", "")):
                if ref.strip():
                    own[ref.strip().upper()] = pin
        pts.append((obj.location.lon * 102.0, obj.location.lat * 110.6))  # km-ish projection for India
        codes.append(pin)
    tree = cKDTree(np.array(pts))
    con = sqlite3.connect(db)
    found, rejected = [], 0
    for code, state, lat, lon in con.execute("SELECT code, state, lat, lon FROM stations"):
        pin, source, votes = None, None, 0
        if lat is not None:
            for radius in PIN_RINGS_KM:  # the closest ring with any postcode decides: locality over volume
                near = tree.query_ball_point((lon * 102.0, lat * 110.6), radius)
                if near:
                    pin, votes = Counter(codes[i] for i in near).most_common(1)[0]
                    source = f"OSM_POSTCODES_WITHIN_{radius:g}_KM"
                    break
        tagged = own.get(code)
        if tagged and (pin is None or tagged == pin or votes < PIN_MIN_VOTES_TO_OVERRULE_TAG):
            pin, source, votes = tagged, "OSM_STATION_TAG", max(votes, 1)
        elif tagged:
            source += "_OVERRULING_STATION_TAG"  # e.g. Guwahati tagged 784001 (Tezpur); its locality says 781001
        if pin is None:
            continue
        if state and not any(state.strip().lower() == s.lower() for s in PIN_ZONE.get(pin[0], ())):
            rejected += 1  # postcode zone disagrees with the station's state: not trusted
            continue
        found.append((code, pin, source, votes))
    con.execute("DELETE FROM station_pin")
    con.executemany("INSERT INTO station_pin VALUES (?,?,?,?)", found)
    total = con.execute("SELECT COUNT(*) FROM stations").fetchone()[0]
    summary = {
        "stations": total,
        "with_pin": len(found),
        "from_station_tag": sum(1 for f in found if f[2] == "OSM_STATION_TAG"),
        "from_nearby_postcodes": sum(1 for f in found if f[2].startswith("OSM_POSTCODES")),
        "accuracy": "approximate: the locality's PIN near the station; India Post / IR station records replace it",
        "rejected_zone_mismatch": rejected,
        "postcode_points": len(codes),
        "licence": "ODbL-1.0, (c) OpenStreetMap contributors",
    }
    con.execute("DELETE FROM metadata WHERE key = 'pin_summary'")
    con.execute("INSERT INTO metadata VALUES ('pin_summary', ?)", (json.dumps(summary),))
    con.commit()
    con.close()
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="india_rail current", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch", help="download and verify the current timetable")
    sub.add_parser("build", help="build data/current.sqlite with every train and the registry")
    pins = sub.add_parser("pins", help="station PIN codes from an OpenStreetMap extract")
    pins.add_argument("--pbf", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "fetch":
        print(fetch())
    elif args.command == "build":
        print(json.dumps(build(fetch()), indent=2, default=str))
    else:
        print(json.dumps(station_pins(args.pbf), indent=2))
    return 0
