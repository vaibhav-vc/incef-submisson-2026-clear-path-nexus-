"""Loop and block-section register: template, validation, IR-only build, and what the twin does with it."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from test_shared_track import STATIONS, TRAINS  # the synthetic network: an express over a local's track

from india_rail.ingest import build_database
from india_rail.railguard import register
from india_rail.railguard.national import NationalTwin, build_national

RAJ = "12951@0"


@pytest.fixture(scope="module")
def db(tmp_path_factory) -> Path:
    """The synthetic network's timetable database (as test_shared_track builds it)."""

    tmp = tmp_path_factory.mktemp("register_db")
    stations = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": list(xy)},
         "properties": {"code": c, "name": f"Station {c}", "zone": "NR", "state": "Delhi"}}
        for c, xy in STATIONS.items()]}  # fmt: skip
    trains = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": None, "properties": {"number": n, "name": f"Train {n}", "type": t,
                                                             "zone": "NR", "distance": 30, "return_train": ""}}
        for n, (t, _s) in TRAINS.items()]}  # fmt: skip
    schedules, row_id = [], 1
    for number, (_t, stops) in TRAINS.items():
        for code, arr, dep in stops:
            schedules.append({"id": row_id, "train_number": number, "train_name": number, "station_code": code,
                              "station_name": code, "arrival": arr if arr == "None" else arr + ":00",
                              "departure": dep if dep == "None" else dep + ":00", "day": 1})  # fmt: skip
            row_id += 1
    paths = {}
    for key, payload in {"stations": stations, "trains": trains, "schedules": schedules}.items():
        paths[key] = tmp / f"{key}.json"
        paths[key].write_text(json.dumps(payload))
    build_database(paths, tmp / "rail.sqlite")
    return tmp / "rail.sqlite"


def _fill(folder: Path, stations: dict[str, dict], sections: dict[str, dict]) -> None:
    for name, filled in (("stations.csv", stations), ("sections.csv", sections)):
        rows = list(csv.DictReader((folder / name).open(encoding="utf-8")))
        key = "station_code" if name == "stations.csv" else "section_id"
        for row in rows:
            row.update(filled.get(row[key], {}))
        with (folder / name).open("w", newline="", encoding="utf-8") as handle:
            w = csv.DictWriter(handle, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)


def test_the_template_lists_physical_track_with_hints_and_empty_operational_columns(db, tmp_path):
    summary = register.template(tmp_path, db)
    sections = list(csv.DictReader((tmp_path / "sections.csv").open(encoding="utf-8")))
    ids = {r["section_id"] for r in sections}
    assert "A-D" not in ids and {"A-B", "B-C", "C-D", "B-X", "C-X"} <= ids  # A-D is only a path over A-B-C-D
    assert summary["sections_left_out_as_paths_over_shorter_sections"] == 1
    assert all(r["tracks"] == "" and r["source"] == "" and r["hint_twin_tracks"] for r in sections)
    result = register.check(tmp_path)
    assert result["problems"] == [] and result["sections"] == {}  # nothing usable until IR fills it in


def test_values_without_an_indian_railways_source_are_never_used(db, tmp_path):
    register.template(tmp_path, db)
    _fill(
        tmp_path, {"B": {"loops": "2", "source": "OSM"}}, {"A-B": {"tracks": "2", "source": "", "effective_from": ""}}
    )
    problems = register.check(tmp_path)["problems"]
    assert any("stations.csv B" in p and "Indian Railways" in p for p in problems)
    assert any("sections.csv A-B" in p and "Indian Railways" in p for p in problems)
    with pytest.raises(ValueError, match="problems"):
        register.build(tmp_path, tmp_path / "register.json")


def test_inconsistent_rows_are_refused(db, tmp_path):
    register.template(tmp_path, db)
    _fill(
        tmp_path,
        {"C": {"loops": "0", "crossing_allowed": "Y", "source": "IR_SWR", "effective_from": "2026-04-01"}},
        {"B-C": {"tracks": "2", "block_system": "TOKEN", "source": "IR_WTT", "effective_from": "2026-04-01"},
         "C-D": {"headway_min": "45", "source": "IR_WTT", "effective_from": "2026-04-01"}},
    )  # fmt: skip
    problems = " ".join(register.check(tmp_path)["problems"])
    assert "cannot cross" in problems and "single-line working" in problems and "headway_min must be 1-30" in problems


def test_a_built_register_overrides_tracks_and_headway_and_blocks_waits_with_no_loop(db, tmp_path):
    register.template(tmp_path, db)
    ir = {"source": "IR_SWR", "effective_from": "2026-04-01"}
    _fill(
        tmp_path,
        {"B": {"loops": "0", "crossing_allowed": "N", **ir}, "C": {"loops": "2", "crossing_allowed": "Y", **ir}},
        {"C-D": {"tracks": "2", "block_system": "AUTOMATIC", "headway_min": "5", **ir}},
    )
    assert register.build(tmp_path, tmp_path / "register.json") == {
        "stations": 2, "sections": 1, "out": str(tmp_path / "register.json")}  # fmt: skip
    loaded = register.load(tmp_path / "register.json")
    built = build_national(db, register=loaded)
    assert (
        built.network.sections["C-D"].tracks == 2
        and "IR_REGISTER(IR_SWR)" in built.network.sections["C-D"].data_quality
    )
    assert built.headway == {"C-D": 5.0} and built.loops == {"B": 0, "C": 2}
    assert built.stats["register"] == loaded["checksum"] and built.checksum != build_national(db).checksum
    twin = NationalTwin(built, start_min=590.0)
    plan = twin.plan_of("59001@0")  # the local: A -> B -> C -> D
    held_at_b = twin.propagate(plan, {1: 10.0})  # a planned 10-min wait at B, single line, no loop
    held_at_c = twin.propagate(plan, {2: 10.0})  # at C, which has loops
    run = twin.runs["59001@0"]
    assert "no loop at B to wait in on single line" in twin._violations(held_at_b, 0, run)
    assert not [v for v in twin._violations(held_at_c, 0, run) if "no loop" in v]


def test_a_register_with_foreign_rows_is_not_loaded(tmp_path):
    bad = {"kind": "Clear Path Nexus loop and block-section register", "stations": {"A": {"loops": 1, "source": "OSM"}},
           "sections": {}}  # fmt: skip
    (tmp_path / "r.json").write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="Indian Railways"):
        register.load(tmp_path / "r.json")
    (tmp_path / "x.json").write_text(json.dumps({"stations": {}, "sections": {}}))
    with pytest.raises(ValueError, match="not a register"):
        register.load(tmp_path / "x.json")
