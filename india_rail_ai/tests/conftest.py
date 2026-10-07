"""Miniature hand-made network shared by the offline tests (no downloads)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from india_rail.ingest import build_database, connect

STATIONS = {"AAA": (77.0, 28.0), "BBB": (77.1, 28.0), "CCC": (77.2, 28.0)}


def _station_features():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": list(xy)},
                "properties": {"code": code, "name": f"Station {code}", "zone": "NR", "state": "Delhi"},
            }
            for code, xy in STATIONS.items()
        ],
    }


def _train(number, ttype, stops):
    return {
        "type": "Feature",
        "geometry": None,
        "properties": {
            "number": number,
            "name": f"Train {number}",
            "type": ttype,
            "zone": "NR",
            "distance": 25,
            "return_train": "",
            "from_station_code": stops[0][0],
            "to_station_code": stops[-1][0],
        },
    }


TRAINS = {
    # number, type, [(station, arrival, departure, day)]
    "12001": (
        "Raj",
        [("AAA", "None", "10:05:00", 1), ("BBB", "10:15:00", "10:16:00", 1), ("CCC", "10:30:00", "None", 1)],
    ),
    "54001": (
        "Pass",
        [("AAA", "None", "10:00:00", 1), ("BBB", "10:14:00", "10:20:00", 1), ("CCC", "10:40:00", "None", 1)],
    ),
    "19001": (
        "Exp",
        [("AAA", "None", "23:50:00", 1), ("BBB", "00:05:00", "00:06:00", 2), ("CCC", "00:20:00", "None", 2)],
    ),
}


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    schedules, row_id = [], 1
    for number, (_type, stops) in TRAINS.items():
        for code, arr, dep, day in stops:
            schedules.append(
                {
                    "id": row_id,
                    "train_number": number,
                    "train_name": f"Train {number}",
                    "station_code": code,
                    "station_name": f"Station {code}",
                    "arrival": arr,
                    "departure": dep,
                    "day": day,
                }
            )
            row_id += 1
    # A verbatim duplicate listing of one train must not create a loop.
    for row in [r for r in schedules if r["train_number"] == "12001"]:
        schedules.append({**row, "id": row_id})
        row_id += 1
    paths = {}
    payloads = {
        "stations": _station_features(),
        "trains": {"type": "FeatureCollection", "features": [_train(n, t, s) for n, (t, s) in TRAINS.items()]},
        "schedules": schedules,
    }
    for key, payload in payloads.items():
        paths[key] = tmp_path / f"{key}.json"
        paths[key].write_text(json.dumps(payload))
    db_path = tmp_path / "rail.sqlite"
    report = build_database(paths, db_path)
    assert report.duplicate_rows == 3
    return db_path


@pytest.fixture()
def db(db_path: Path) -> sqlite3.Connection:
    return connect(db_path)
