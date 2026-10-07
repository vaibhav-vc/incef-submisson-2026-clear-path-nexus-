"""Official open data: Government of India / Indian Railways publications.

    python -m india_rail official --list                      # what is registered, and its licence
    python -m india_rail official --file timetable.csv        # ingest a file you downloaded
    python -m india_rail official --download ogd_timetable    # fetch it (needs a connection the portal accepts)

The open timetable used elsewhere (DataMeet) is a community extract of Indian
Railways data. This module adds the Government's own releases next to it:

* every source is registered with its publisher, licence and landing page;
* a downloaded file is pinned by SHA-256 and recorded in `official_provenance`;
* the data.gov.in timetable (train-wise arrival, departure and *cumulative rail
  distance* at each stop) is parsed into `official_stops`, and per-section rail
  distances into `official_section_km`, which the national twin then prefers to
  straight-line estimates;
* a reconciliation report says where the official file and the community
  extract agree, so neither is trusted blindly.

Government portals refuse some foreign or cloud networks; download from a
connection in India, or place the file by hand and use --file.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sqlite3
import statistics
import urllib.request
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from india_rail.ingest import DB_PATH, RAW_DIR


@dataclass(frozen=True)
class OfficialSource:
    key: str
    title: str
    publisher: str
    licence: str
    landing_page: str
    download_url: str | None
    kind: str


SOURCES: dict[str, OfficialSource] = {
    "ogd_timetable": OfficialSource(
        "ogd_timetable",
        "Indian Railways Train Time Table",
        "Ministry of Railways, Government of India (via Open Government Data Platform India)",
        "Government Open Data License - India (GODL); attribution required",
        "https://www.data.gov.in/catalog/indian-railways-train-time-table",
        None,  # the portal issues per-user download links; use --file with the CSV it gives you
        "timetable_csv",
    ),
    "trains_at_a_glance": OfficialSource(
        "trains_at_a_glance",
        "Trains at a Glance (all-India timetable of the Railway Board)",
        "Railway Board, Ministry of Railways",
        "Government publication; reuse subject to the publisher's terms",
        "https://indianrailways.gov.in/railwayboard/view_section.jsp?lang=0&id=0,1,304,366,1530",
        None,
        "timetable_pdf",
    ),
    "station_codes": OfficialSource(
        "station_codes",
        "Indian Railways station code list",
        "Ministry of Railways, Government of India",
        "Government publication; reuse subject to the publisher's terms",
        "https://indianrailways.gov.in/",
        None,
        "station_list",
    ),
}

# Header spellings seen in the data.gov.in timetable releases, normalised (lower case, no spaces/punctuation).
COLUMNS = {
    "train": ("trainno", "trainnumber", "train"),
    "name": ("trainname", "name"),
    "seq": ("seq", "sequence", "sno", "islno"),
    "code": ("stationcode", "code", "stncode"),
    "station": ("stationname", "station"),
    "arr": ("arrivaltime", "arrival", "arr"),
    "dep": ("departuretime", "departure", "dep"),
    "km": ("distance", "distancekm", "km"),
}
TIME = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")


def _norm(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.lower())


def _minutes(value: str) -> int | None:
    match = TIME.match((value or "").strip())
    if not match:
        return None
    hours, minutes = int(match.group(1)), int(match.group(2))
    return hours * 60 + minutes if hours < 24 and minutes < 60 else None


def parse_timetable(text: str) -> list[dict[str, Any]]:
    """Parse the data.gov.in timetable CSV into stop rows. Unparseable rows are skipped, not guessed."""

    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    index: dict[str, int] = {}
    for i, name in enumerate(header):
        for field, spellings in COLUMNS.items():
            if field not in index and _norm(name) in spellings:
                index[field] = i
    missing = {"train", "code", "seq", "km"} - index.keys()
    if missing:
        raise ValueError(f"not an Indian Railways timetable file: missing columns {sorted(missing)}")
    rows = []
    for raw in reader:
        if len(raw) < len(header):
            continue
        values = {f: raw[i].strip() for f, i in index.items()}
        get = values.get
        try:
            seq, km = int(float(get("seq"))), float(get("km"))
        except ValueError:
            continue
        code = get("code").upper()
        train = get("train").lstrip("'")
        name, station = values.get("name", ""), values.get("station", "")
        if not code or not train or km < 0:
            continue
        rows.append(
            {
                "train_number": train,
                "train_name": name,
                "seq": seq,
                "station_code": code,
                "station_name": station,
                "arr_min": _minutes(values.get("arr", "")),
                "dep_min": _minutes(values.get("dep", "")),
                "distance_km": km,
            }
        )
    # The release writes 00:00:00 for "no arrival" at the origin and "no departure" at the terminus.
    by_train: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_train[row["train_number"]].append(row)
    for stops in by_train.values():
        first, last = min(stops, key=lambda r: r["seq"]), max(stops, key=lambda r: r["seq"])
        if first["arr_min"] == 0:
            first["arr_min"] = None
        if last["dep_min"] == 0:
            last["dep_min"] = None
    return rows


def section_km(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Median rail distance between consecutive stops across all trains, keyed like the twin's sections."""

    by_train: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_train[row["train_number"]].append(row)
    samples: dict[str, list[float]] = defaultdict(list)
    for stops in by_train.values():
        stops.sort(key=lambda r: r["seq"])
        for a, b in pairwise(stops):
            km = b["distance_km"] - a["distance_km"]
            if 0 < km < 1000 and a["station_code"] != b["station_code"]:
                x, y = sorted((a["station_code"], b["station_code"]))
                samples[f"{x}-{y}"].append(km)
    return {edge: round(statistics.median(v), 2) for edge, v in samples.items()}


def ingest(path: Path, source_key: str = "ogd_timetable", db_path: Path = DB_PATH) -> dict[str, Any]:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    rows = parse_timetable(data.decode("utf-8-sig", errors="replace"))
    km = section_km(rows)
    con = sqlite3.connect(db_path)
    with con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS official_provenance (
                source TEXT, file TEXT, sha256 TEXT, rows INTEGER, ingested_utc TEXT, publisher TEXT, licence TEXT);
            DROP TABLE IF EXISTS official_stops;
            CREATE TABLE official_stops (train_number TEXT, train_name TEXT, seq INTEGER, station_code TEXT,
                station_name TEXT, arr_min INTEGER, dep_min INTEGER, distance_km REAL);
            DROP TABLE IF EXISTS official_section_km;
            CREATE TABLE official_section_km (edge TEXT PRIMARY KEY, km REAL);
            """
        )
        con.executemany(
            "INSERT INTO official_stops VALUES (:train_number, :train_name, :seq, :station_code, :station_name, "
            ":arr_min, :dep_min, :distance_km)",
            rows,
        )
        con.executemany("INSERT INTO official_section_km VALUES (?, ?)", sorted(km.items()))
        source = SOURCES[source_key]
        con.execute(
            "INSERT INTO official_provenance VALUES (?, ?, ?, ?, ?, ?, ?)",
            (source_key, path.name, digest, len(rows), datetime.now(UTC).isoformat(timespec="seconds"),
             source.publisher, source.licence),
        )  # fmt: skip
    report = reconcile(con)
    con.close()
    return {"file": path.name, "sha256": digest, "rows": len(rows), "sections_with_rail_km": len(km), **report}


def reconcile(con: sqlite3.Connection) -> dict[str, Any]:
    """Compare the official file with the community timetable already in the database."""

    official = {r[0] for r in con.execute("SELECT DISTINCT train_number FROM official_stops")}
    community = {r[0] for r in con.execute("SELECT number FROM trains")}
    stations_o = {r[0] for r in con.execute("SELECT DISTINCT station_code FROM official_stops")}
    stations_c = {r[0] for r in con.execute("SELECT code FROM stations")}
    same_stop = con.execute(
        """SELECT COUNT(*), SUM(CASE WHEN o.dep_min = (c.dep_min % 1440) THEN 1 ELSE 0 END)
           FROM official_stops o JOIN stops c ON c.train_number = o.train_number AND c.station_code = o.station_code
           WHERE o.dep_min IS NOT NULL AND c.dep_min IS NOT NULL"""
    ).fetchone()
    return {
        "trains_official": len(official),
        "trains_in_both": len(official & community),
        "trains_only_official": len(official - community),
        "stations_official": len(stations_o),
        "stations_only_official": len(stations_o - stations_c),
        "matched_stop_departures": same_stop[0] or 0,
        "identical_departure_times_pct": round(100 * (same_stop[1] or 0) / same_stop[0], 2) if same_stop[0] else None,
    }


def download(key: str, dest_dir: Path = RAW_DIR) -> Path:
    source = SOURCES[key]
    if not source.download_url:
        raise SystemExit(
            f"{source.title}: the publisher issues the file from {source.landing_page} - download it there "
            "and run `python -m india_rail official --file <path>`"
        )
    if not source.download_url.startswith("https://"):
        raise SystemExit("refusing a non-HTTPS source")
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"official_{key}{Path(source.download_url).suffix or '.dat'}"
    request = urllib.request.Request(source.download_url, headers={"User-Agent": "india-rail-ai/0.1"})
    with urllib.request.urlopen(request, timeout=120) as response:  # nosec B310 - https enforced above
        target.write_bytes(response.read())
    return target


def listing() -> list[dict[str, Any]]:
    return [asdict(s) for s in SOURCES.values()]


def main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="india_rail official", description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true")
    group.add_argument("--file", type=Path)
    group.add_argument("--download", choices=sorted(SOURCES))
    args = parser.parse_args(argv)
    if args.list:
        print(json.dumps(listing(), indent=2))
        return 0
    path = args.file or download(args.download)
    print(json.dumps(ingest(path), indent=2))
    return 0
