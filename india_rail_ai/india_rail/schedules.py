"""Working schedule of every train: stop-by-stop matrix, per-train metrics and a completeness audit.

    python -m india_rail schedules --train 12951        # one train's working schedule and metrics
    python -m india_rail schedules --audit              # check every train; writes the audit evidence JSON
    python -m india_rail schedules --export DIR         # CSVs: every stop of every train, and one row per train

The audit covers all trains in the published train list, including those with no usable timetable, and states
for each train what is present, what is missing and what is inconsistent, so nothing is assumed silently.
Distances per stop come from the official data.gov.in timetable when it has been ingested
(`python -m india_rail official --file ...`); otherwise they are straight-line distances scaled so the route
adds up to the published train distance, and labelled as such.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from india_rail.ingest import DB_PATH, PACKAGE_ROOT
from india_rail.network import clock

AUDIT_PATH = PACKAGE_ROOT / "seva2026" / "evidence" / "schedules" / "schedule_audit.json"
DURATION_TOLERANCE_MIN = 30
MAX_PLAUSIBLE_KMPH = 160  # straight-line speed above this between stops points to a data error
ROUNDING_ALLOWANCE_MIN = 1  # timetables are whole minutes: judge speed against run time + 1 min
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _frame(con: sqlite3.Connection, sql: str, params: tuple = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, con, params=params)


def _official_km(con: sqlite3.Connection) -> pd.DataFrame | None:
    try:
        return _frame(con, "SELECT train_number, station_code, distance_km FROM official_stops")
    except (sqlite3.OperationalError, pd.errors.DatabaseError):
        return None


def stop_matrix(con: sqlite3.Connection, number: str) -> list[dict[str, Any]]:
    """Every stop of one train: times, day, dwell, cumulative distance, section run time and speed."""

    stops = _frame(
        con,
        "SELECT seq, station_code, station_name, arr_min, dep_min, dwell_min FROM stops "
        "WHERE train_number = ? ORDER BY seq",
        (number,),
    )
    if stops.empty:
        return []
    sections = _frame(
        con, "SELECT seq, runtime_min, crow_km FROM sections WHERE train_number = ? ORDER BY seq", (number,)
    ).set_index("seq")
    sections["crow_km"] = pd.to_numeric(sections["crow_km"], errors="coerce")  # stations without coordinates: NaN
    details = _frame(con, "SELECT published_distance_km FROM train_details WHERE number = ?", (number,))
    published = float(details.iloc[0, 0]) if not details.empty and pd.notna(details.iloc[0, 0]) else None
    crow = [float(sections["crow_km"].get(s, float("nan"))) for s in stops["seq"][:-1]]
    known = sum(c for c in crow if c == c)
    scale, source = 1.03, "STRAIGHT_LINE_X1.03"
    if published and known > 0 and 0.8 <= published / known <= 2.5:
        scale, source = published / known, "STRAIGHT_LINE_SCALED_TO_PUBLISHED_DISTANCE"
    official = _official_km(con)
    official_km = {}
    if official is not None:
        rows = official[official["train_number"] == number]
        official_km = dict(zip(rows["station_code"], rows["distance_km"], strict=False))
    out, cumulative = [], 0.0
    for i, row in enumerate(stops.itertuples(index=False)):
        if i:
            step = crow[i - 1]
            cumulative += step * scale if step == step else 0.0
        section = sections.loc[row.seq] if row.seq in sections.index and i < len(stops) - 1 else None
        km = official_km.get(row.station_code)
        next_km = None
        if section is not None and section["crow_km"] == section["crow_km"]:
            next_km = float(section["crow_km"]) * scale
        out.append(
            {
                "seq": int(row.seq),
                "station_code": row.station_code,
                "station_name": row.station_name,
                "day": int(row.dep_min // 1440) + 1,
                "arrival": None if i == 0 else clock(int(row.arr_min)),
                "departure": None if i == len(stops) - 1 else clock(int(row.dep_min)),
                "dwell_min": int(row.dwell_min),
                "km_from_origin": round(float(km), 1) if km is not None else round(cumulative, 1),
                "km_source": "OFFICIAL_TIMETABLE" if km is not None else source,
                "section_runtime_min": int(section["runtime_min"]) if section is not None else None,
                "section_speed_kmph": round(next_km / section["runtime_min"] * 60, 1)
                if section is not None and next_km and section["runtime_min"] > 0
                else None,
            }
        )
    return out


def train_metrics(con: sqlite3.Connection) -> pd.DataFrame:
    """One row per published train (all of them), with quality flags."""

    details = _frame(con, "SELECT * FROM train_details")
    trains = _frame(con, "SELECT number, n_stops, journey_min FROM trains")
    stops = _frame(con, "SELECT train_number, COUNT(*) AS halts FROM stops WHERE dwell_min > 0 GROUP BY train_number")
    sections = _frame(
        con,
        "SELECT train_number, COUNT(*) AS sections, SUM(crow_km) AS crow_km, "
        "SUM(CASE WHEN crow_km IS NULL THEN 1 ELSE 0 END) AS no_coordinates, "
        "MAX(CASE WHEN runtime_min > 0 THEN crow_km * 60.0 / (runtime_min + ?) END) AS max_crow_kmph, "
        "MAX(arr_min) / 1440 + 1 AS days_spanned "
        "FROM sections GROUP BY train_number",
        (ROUNDING_ALLOWANCE_MIN,),
    )
    df = details.merge(trains, on="number", how="left").merge(
        stops.rename(columns={"train_number": "number"}), on="number", how="left"
    )
    df = df.merge(sections.rename(columns={"train_number": "number"}), on="number", how="left")
    numbers = set(df["number"])
    df["duration_diff_min"] = df["journey_min"] - df["published_duration_min"]
    df["avg_speed_kmph"] = (df["published_distance_km"] / (df["journey_min"] / 60)).where(df["journey_min"] > 0)
    df["avg_speed_kmph"] = df["avg_speed_kmph"].round(1)

    def flags(r: Any) -> str:
        out = []
        if not r.has_schedule:
            out.append("NO_USABLE_TIMETABLE")
        else:
            if pd.notna(r.duration_diff_min) and abs(r.duration_diff_min) > DURATION_TOLERANCE_MIN:
                out.append("DURATION_DIFFERS_FROM_PUBLISHED")
            if pd.isna(r.published_duration_min):
                out.append("NO_PUBLISHED_DURATION")
            if r.no_coordinates and r.no_coordinates > 0:
                out.append("STOPS_WITHOUT_COORDINATES")
            if pd.notna(r.max_crow_kmph) and r.max_crow_kmph > MAX_PLAUSIBLE_KMPH:
                out.append("DISTANCE_INCONSISTENT_WITH_TIME")
        if pd.isna(r.published_distance_km) or not r.published_distance_km:
            out.append("NO_PUBLISHED_DISTANCE")
        if r.return_train and r.return_train not in numbers:
            out.append("RETURN_TRAIN_NOT_LISTED")
        if not r.classes:
            out.append("NO_CLASS_INFORMATION")
        if not r.running_days:
            out.append("RUNNING_DAYS_UNKNOWN")
        return ",".join(out)

    df["flags"] = df.apply(flags, axis=1)
    return df


def suspect_stations(con: sqlite3.Connection, min_sections: int = 3) -> list[dict[str, Any]]:
    """Stations at the end of several physically impossible sections: their published coordinates are likely wrong."""

    bad = _frame(
        con,
        "SELECT from_code, to_code FROM sections WHERE crow_km IS NOT NULL AND runtime_min > 0 "
        "AND crow_km * 60.0 / (runtime_min + ?) > ?",
        (ROUNDING_ALLOWANCE_MIN, MAX_PLAUSIBLE_KMPH),
    )
    counts = pd.concat([bad["from_code"], bad["to_code"]]).value_counts()
    names = dict(con.execute("SELECT code, name FROM stations").fetchall())
    return [
        {"station_code": code, "name": names.get(code), "impossible_sections": int(n)}
        for code, n in counts[counts >= min_sections].items()
    ]


_METRICS_CACHE: dict[int, pd.DataFrame] = {}


def working_schedule(con: sqlite3.Connection, number: str) -> dict[str, Any] | None:
    """One train's published record, metrics, quality flags and stop matrix (metrics cached per connection)."""

    metrics = _METRICS_CACHE.get(id(con))
    if metrics is None:
        metrics = _METRICS_CACHE[id(con)] = train_metrics(con)
    row = metrics[metrics["number"] == number]
    if row.empty:
        return None
    record = json.loads(row.to_json(orient="records"))[0]
    record["flags"] = [f for f in record["flags"].split(",") if f]
    return {"train": record, "stops": stop_matrix(con, number)}


def audit(con: sqlite3.Connection) -> dict[str, Any]:
    df = train_metrics(con)
    flag_counts: dict[str, int] = {}
    for value in df["flags"]:
        for flag in filter(None, value.split(",")):
            flag_counts[flag] = flag_counts.get(flag, 0) + 1
    scheduled = df[df["has_schedule"] == 1]
    quality = json.loads(con.execute("SELECT value FROM metadata WHERE key = 'quality_report'").fetchone()[0])
    total = len(df)
    return {
        "trains_published": total,
        "trains_with_usable_timetable": int(len(scheduled)),
        "stops_in_timetables": int(scheduled["n_stops"].sum()),
        "halts_with_dwell": int(scheduled["halts"].fillna(0).sum()),
        "coverage_pct": {
            "timetable": round(100 * len(scheduled) / total, 2),
            "published_duration": round(100 * df["published_duration_min"].notna().mean(), 2),
            "published_distance": round(100 * (df["published_distance_km"].fillna(0) > 0).mean(), 2),
            "class_information": round(100 * df["classes"].notna().mean(), 2),
            "return_train": round(100 * df["return_train"].notna().mean(), 2),
            "running_days": round(100 * df["running_days"].notna().mean(), 2),
        },
        "timetable_vs_published_duration": {
            "within_tolerance": int((scheduled["duration_diff_min"].abs() <= DURATION_TOLERANCE_MIN).sum()),
            "tolerance_min": DURATION_TOLERANCE_MIN,
            "median_abs_diff_min": float(diff.abs().median())
            if (diff := scheduled["duration_diff_min"]).notna().any()
            else None,
        },
        "trains_with_no_flags": int((df["flags"] == "").sum()),
        "trains_with_no_flags_except_running_days": int((df["flags"] == "RUNNING_DAYS_UNKNOWN").sum()),
        "suspect_station_coordinates": suspect_stations(con),
        "flag_counts": dict(sorted(flag_counts.items(), key=lambda kv: -kv[1])),
        "trains_by_type": {str(k): int(v) for k, v in df["type"].value_counts().items()},
        "trains_by_zone": {str(k): int(v) for k, v in df["zone"].value_counts().items()},
        "ingest_cleaning": quality,
        "notes": [
            "RUNNING_DAYS_UNKNOWN: the open data has no days of service; the twin treats such trains as daily. "
            "Ingest the official timetable (Trains at a Glance / NTES) to fill them.",
            "Straight-line distances are scaled to the published train distance; official per-stop distances "
            "replace them once the data.gov.in timetable is ingested.",
            "DISTANCE_INCONSISTENT_WITH_TIME: straight-line speed between two stops above 160 km/h even allowing a "
            "minute of timetable rounding. Almost always a wrong station coordinate in the open station list; "
            "suspect_station_coordinates names the stations involved.",
        ],
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="india_rail schedules", description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--train")
    group.add_argument("--audit", action="store_true")
    group.add_argument("--export", type=Path)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args(argv)
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    if args.train:
        result = working_schedule(con, args.train)
        if result is None:
            print(f"Unknown train {args.train}")
            return 1
        print(json.dumps(result, indent=2))
    elif args.audit:
        result = audit(con)
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        AUDIT_PATH.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({k: result[k] for k in ("trains_published", "coverage_pct", "flag_counts")}, indent=2))
    else:
        args.export.mkdir(parents=True, exist_ok=True)
        metrics = train_metrics(con)
        metrics.to_csv(args.export / "train_metrics.csv", index=False)
        rows = [{"train_number": n, **s} for n in metrics.loc[metrics["has_schedule"] == 1, "number"]
                for s in stop_matrix(con, n)]  # fmt: skip
        pd.DataFrame(rows).to_csv(args.export / "train_working_schedules.csv", index=False)
        print(f"{len(metrics)} trains, {len(rows)} stops written to {args.export}")
    con.close()
    return 0
