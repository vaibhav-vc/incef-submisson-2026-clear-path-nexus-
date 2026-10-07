"""Download the public datasets and normalise them into one SQLite database.

Times in the source are local (IST) clock times plus an optional journey day.
The day field is missing on ~5% of rows, so absolute journey minutes are
reconstructed from route order: whenever the clock goes backwards the train has
crossed midnight. Disagreements with the published day are counted in the
quality report rather than silently corrected.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from india_rail.sources import SOURCES

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PACKAGE_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "india_rail.sqlite"
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024

SCHEMA = """
CREATE TABLE stations (
    code TEXT PRIMARY KEY,
    name TEXT,
    zone TEXT,
    state TEXT,
    lat REAL,
    lon REAL
);
CREATE TABLE trains (
    number TEXT PRIMARY KEY,
    name TEXT,
    type TEXT,
    zone TEXT,
    from_code TEXT,
    to_code TEXT,
    distance_km REAL,
    return_train TEXT,
    n_stops INTEGER,
    journey_min INTEGER
);
CREATE TABLE stops (
    train_number TEXT NOT NULL,
    seq INTEGER NOT NULL,
    station_code TEXT NOT NULL,
    station_name TEXT,
    arr_min INTEGER NOT NULL,
    dep_min INTEGER NOT NULL,
    dwell_min INTEGER NOT NULL,
    PRIMARY KEY (train_number, seq)
);
CREATE TABLE sections (
    train_number TEXT NOT NULL,
    seq INTEGER NOT NULL,
    from_code TEXT NOT NULL,
    to_code TEXT NOT NULL,
    dep_min INTEGER NOT NULL,
    arr_min INTEGER NOT NULL,
    runtime_min INTEGER NOT NULL,
    crow_km REAL,
    PRIMARY KEY (train_number, seq)
);
CREATE TABLE train_details (
    number TEXT PRIMARY KEY,
    name TEXT,
    type TEXT,
    zone TEXT,
    from_code TEXT,
    to_code TEXT,
    published_departure TEXT,
    published_arrival TEXT,
    published_duration_min INTEGER,
    published_distance_km REAL,
    classes TEXT,
    return_train TEXT,
    running_days TEXT,
    has_schedule INTEGER NOT NULL
);
CREATE INDEX stops_station ON stops(station_code);
CREATE INDEX sections_edge ON sections(from_code, to_code);
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@dataclass
class QualityReport:
    schedule_rows: int = 0
    duplicate_rows: int = 0
    trains_with_schedule: int = 0
    trains_skipped_too_short: int = 0
    stops_written: int = 0
    sections_written: int = 0
    rows_missing_time: int = 0
    day_field_disagreements: int = 0
    non_monotonic_times_clamped: int = 0
    sections_without_coordinates: int = 0
    negative_runtime_sections_dropped: int = 0
    notes: list[str] = field(default_factory=list)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def parse_clock(value: Any) -> int | None:
    """Return minutes after local midnight for 'HH:MM[:SS]', else None."""

    if not isinstance(value, str) or value in {"None", ""}:
        return None
    parts = value.split(":")
    try:
        hours, minutes = int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return None
    if not (0 <= hours < 24 and 0 <= minutes < 60):
        return None
    return hours * 60 + minutes


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_sources(*, allow_unpinned: bool = False, raw_dir: Path = RAW_DIR) -> dict[str, Path]:
    """Fetch each registered source once and verify its pinned digest."""

    raw_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for source in SOURCES.values():
        target = raw_dir / f"{source.key}.json"
        if not target.exists():
            if not source.url.startswith("https://"):
                raise ValueError(f"{source.key}: only https sources are downloaded")
            partial = target.with_suffix(".part")
            with urllib.request.urlopen(source.url, timeout=300) as response, partial.open("wb") as out:  # nosec B310
                total = 0
                while chunk := response.read(1 << 20):
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise ValueError(f"{source.key}: download exceeds {MAX_DOWNLOAD_BYTES} bytes")
                    out.write(chunk)
            partial.replace(target)
        actual = _sha256(target)
        if source.sha256 and actual != source.sha256 and not allow_unpinned:
            raise ValueError(
                f"{source.key}: SHA-256 {actual} does not match pinned {source.sha256}. "
                "The upstream file changed; rerun with --allow-unpinned to accept it."
            )
        paths[source.key] = target
    return paths


def _stop_minutes(rows: list[dict[str, Any]], report: QualityReport) -> list[tuple[dict, int, int]]:
    """Convert ordered rows into absolute (arrival, departure) journey minutes."""

    result: list[tuple[dict, int, int]] = []
    previous: int | None = None
    for row in rows:
        arr = parse_clock(row.get("arrival"))
        dep = parse_clock(row.get("departure"))
        if arr is None and dep is None:
            report.rows_missing_time += 1
            continue
        arr = dep if arr is None else arr
        dep = arr if dep is None else dep
        abs_arr = arr if previous is None else _advance(previous, arr, report)
        abs_dep = _advance(abs_arr, dep, report)
        day = row.get("day")
        if isinstance(day, int) and day != abs_arr // 1440 + 1:
            report.day_field_disagreements += 1
        result.append((row, abs_arr, abs_dep))
        previous = abs_dep
    return result


def _advance(previous_abs: int, clock: int, report: QualityReport) -> int:
    """Place a clock time at or after previous_abs on the journey timeline.

    A backward step larger than 12 hours is a midnight crossing. A smaller
    backward step is a source error (e.g. 08:30 then 08:29); the time is clamped
    to the previous one instead of inventing a 24-hour section.
    """

    delta = clock - previous_abs % 1440
    if delta >= 0:
        return previous_abs + delta
    if delta <= -720:
        return previous_abs + delta + 1440
    report.non_monotonic_times_clamped += 1
    return previous_abs


def build_database(paths: dict[str, Path], db_path: Path = DB_PATH) -> QualityReport:
    report = QualityReport()
    stations_raw = json.loads(paths["stations"].read_text(encoding="utf-8"))
    trains_raw = json.loads(paths["trains"].read_text(encoding="utf-8"))
    schedules_raw = json.loads(paths["schedules"].read_text(encoding="utf-8"))
    report.schedule_rows = len(schedules_raw)

    stations: dict[str, tuple] = {}
    for feature in stations_raw["features"]:
        props = feature.get("properties") or {}
        code = props.get("code")
        if not code:
            continue
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates") if geometry.get("type") == "Point" else None
        lon, lat = (coords[0], coords[1]) if coords else (None, None)
        stations[code] = (code, props.get("name"), props.get("zone"), props.get("state"), lat, lon)

    by_train: dict[str, dict[int, dict]] = defaultdict(dict)
    # Some trains appear twice under different row ids. A repeated
    # (station, arrival, departure, day) tuple is a duplicate listing, not a
    # second visit; keeping it would splice two copies into a looping train.
    seen: dict[str, set[tuple]] = defaultdict(set)
    for row in sorted(schedules_raw, key=lambda r: r["id"]):
        number = str(row["train_number"])
        signature = (row["station_code"], row["arrival"], row["departure"], row["day"])
        if signature in seen[number]:
            report.duplicate_rows += 1
            continue
        seen[number].add(signature)
        by_train[number][row["id"]] = row
    report.trains_with_schedule = len(by_train)

    train_props = {str(f["properties"]["number"]): f["properties"] for f in trains_raw["features"]}

    if db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO stations VALUES (?,?,?,?,?,?)", stations.values())

    train_rows, stop_rows, section_rows = [], [], []
    for number, rows_by_id in by_train.items():
        timed = _stop_minutes([rows_by_id[k] for k in sorted(rows_by_id)], report)
        if len(timed) < 2:
            report.trains_skipped_too_short += 1
            continue
        for seq, (row, arr, dep) in enumerate(timed):
            stop_rows.append((number, seq, row["station_code"], row.get("station_name"), arr, dep, dep - arr))
        for seq in range(len(timed) - 1):
            (a, _a_arr, a_dep), (b, b_arr, _b_dep) = timed[seq], timed[seq + 1]
            runtime = b_arr - a_dep
            if runtime < 0:
                report.negative_runtime_sections_dropped += 1
                continue
            sa, sb = stations.get(a["station_code"]), stations.get(b["station_code"])
            crow = None
            if sa and sb and sa[4] is not None and sb[4] is not None:
                crow = haversine_km(sa[4], sa[5], sb[4], sb[5])
            else:
                report.sections_without_coordinates += 1
            section_rows.append((number, seq, a["station_code"], b["station_code"], a_dep, b_arr, runtime, crow))
        props = train_props.get(number, {})
        first, last = timed[0], timed[-1]
        train_rows.append(
            (
                number,
                props.get("name") or first[0].get("train_name"),
                props.get("type") or "",
                props.get("zone"),
                first[0]["station_code"],
                last[0]["station_code"],
                props.get("distance"),
                props.get("return_train"),
                len(timed),
                last[1] - first[2],
            )
        )

    con.executemany("INSERT INTO trains VALUES (?,?,?,?,?,?,?,?,?,?)", train_rows)
    scheduled = {row[0] for row in train_rows}
    con.executemany(
        "INSERT INTO train_details VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [_details(number, props, number in scheduled) for number, props in sorted(train_props.items())],
    )
    con.executemany("INSERT INTO stops VALUES (?,?,?,?,?,?,?)", stop_rows)
    con.executemany("INSERT INTO sections VALUES (?,?,?,?,?,?,?,?)", section_rows)
    report.stops_written = len(stop_rows)
    report.sections_written = len(section_rows)
    report.notes.append("Times are journey minutes from 00:00 IST on the origin day.")
    report.notes.append(
        "day_field_disagreements counts rows whose published day contradicts the "
        "clock sequence; spot checks show the published day is the faulty field "
        "(e.g. train 59298 increments its day at most stops within four hours)."
    )
    metadata = {
        "sources": json.dumps(
            {k: {"url": s.url, "sha256": _sha256(paths[k]), "licence": s.licence} for k, s in SOURCES.items()}
        ),
        "quality_report": json.dumps(report.__dict__),
    }
    con.executemany("INSERT INTO metadata VALUES (?,?)", metadata.items())
    con.commit()
    con.close()
    return report


CLASS_FIELDS = (("first_ac", "1A"), ("second_ac", "2A"), ("third_ac", "3A"), ("sleeper", "SL"),
                ("chair_car", "CC"), ("first_class", "FC"))  # fmt: skip


def _details(number: str, props: dict, has_schedule: bool) -> tuple:
    """Everything the published train record says, kept for every train (with or without a timetable)."""

    hours, minutes = props.get("duration_h"), props.get("duration_m")
    duration = (hours or 0) * 60 + (minutes or 0) if hours is not None or minutes is not None else None
    classes = [code for field, code in CLASS_FIELDS if props.get(field)]
    return (
        number,
        props.get("name"),
        props.get("type") or "",
        props.get("zone"),
        props.get("from_station_code"),
        props.get("to_station_code"),
        props.get("departure"),
        props.get("arrival"),
        duration,
        props.get("distance"),
        ",".join(classes) or (props.get("classes") or None),
        props.get("return_train") or None,
        None,  # running days are not in the open data; official.py fills them when a source provides them
        int(has_schedule),
    )


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"{db_path} does not exist. Run `python -m india_rail ingest` first.")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con
