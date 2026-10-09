"""Trains with different stopping patterns share track: separation is checked on the pieces they share.

Line A-B-C-D (single line) with a bypass B-X-C. 12951 (Rajdhani) runs A->D non-stop, so its one section A-D is
the track of the locals' A-B, B-C and C-D. 59001 follows it A->D stopping everywhere, 59002 and 59004 run D->A,
19001 uses the bypass (a different track, longer than B-C, so B-C is not split).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from india_rail.ingest import build_database
from india_rail.railguard.national import NationalTwin, build_national

STATIONS = {"A": (77.0, 28.0), "B": (77.1, 28.0), "C": (77.2, 28.0), "D": (77.3, 28.0), "X": (77.15, 28.06)}
TRAINS = {
    "12951": ("Raj", [("A", "None", "10:00"), ("D", "10:24", "None")]),
    "59001": (
        "Pass",
        [("A", "None", "10:30"), ("B", "10:42", "10:43"), ("C", "10:55", "10:56"), ("D", "11:08", "None")],
    ),
    "59002": (
        "Pass",
        [("D", "None", "09:00"), ("C", "09:12", "09:13"), ("B", "09:25", "09:26"), ("A", "09:38", "None")],
    ),
    "59004": (
        "Pass",
        [("D", "None", "11:30"), ("C", "11:42", "11:43"), ("B", "11:55", "11:56"), ("A", "12:08", "None")],
    ),
    "19001": ("Exp", [("B", "None", "08:00"), ("X", "08:08", "08:09"), ("C", "08:20", "None")]),
}
RAJ, LOCAL, OPPOSING = "12951@0", "59001@0", "59004@0"


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    return _build(tmp_path_factory.mktemp("shared"), STATIONS, TRAINS)


def _build(tmp: Path, station_xy: dict, train_stops: dict, register: dict | None = None):
    stations = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": list(xy)},
                "properties": {"code": c, "name": f"Station {c}", "zone": "NR", "state": "Delhi"},
            }
            for c, xy in station_xy.items()
        ],
    }
    trains = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": None,
                "properties": {
                    "number": n,
                    "name": f"Train {n}",
                    "type": t,
                    "zone": "NR",
                    "distance": 30,
                    "return_train": "",
                },
            }  # fmt: skip
            for n, (t, _stops) in train_stops.items()
        ],
    }
    schedules, row_id = [], 1
    for number, (_t, stops) in train_stops.items():
        for code, arr, dep in stops:
            schedules.append(
                {
                    "id": row_id,
                    "train_number": number,
                    "train_name": number,
                    "station_code": code,
                    "station_name": code,
                    "arrival": arr if arr == "None" else arr + ":00",
                    "departure": dep if dep == "None" else dep + ":00",
                    "day": 1,
                }
            )
            row_id += 1
    paths = {}
    for key, payload in {"stations": stations, "trains": trains, "schedules": schedules}.items():
        paths[key] = tmp / f"{key}.json"
        paths[key].write_text(json.dumps(payload))
    build_database(paths, tmp / "rail.sqlite")
    return build_national(tmp / "rail.sqlite", register=register)


@pytest.fixture()
def twin(data) -> NationalTwin:
    return NationalTwin(data, start_min=590.0)


def test_a_section_over_shorter_sections_is_split_into_them(data):
    forward, backward = data.parts["A-D"]
    assert [(p[0], p[3]) for p in forward] == [("A-B", "A"), ("B-C", "B"), ("C-D", "C")]
    assert [(p[0], p[3]) for p in backward] == [("C-D", "D"), ("B-C", "C"), ("A-B", "B")]
    assert forward[0][1] == 0.0 and forward[-1][2] == 1.0
    assert "B-C" not in data.parts  # the bypass via X is other track, and much longer
    assert data.stats["sections_over_shorter_sections"] == 1
    # The Rajdhani occupies each piece in turn; nothing is registered on its stop-to-stop section itself.
    assert RAJ in data.occupancy["B-C"].keys and "A-D" not in data.occupancy


def test_the_timetable_is_clear_on_shared_track(twin):
    for key in twin.runs:
        assert not [c for c in twin.conflicts(key, twin.plan_of(key), 0) if c["is_conflict"]]


def test_a_late_express_conflicts_with_the_local_on_the_track_they_share(twin):
    result = twin.disrupt(RAJ, "A", 30)
    shared = {c["section_id"] for c in result["conflicts"] if c["other"] == LOCAL}
    assert "A-B" in shared  # A-B is not one of the Rajdhani's own sections: invisible before
    # Seen from the local too: the changed run is indexed on the pieces of track it runs over.
    seen = twin.conflicts(LOCAL, twin.plan_of(LOCAL), 0)
    assert any(c["other"] == RAJ and c["section_id"] == "A-B" and c["is_conflict"] for c in seen)
    assert any(t.type == "CONVERGING_PATH" and t.section_id == "A-B" for t in twin.threats.active())
    assert any(entry[1] == RAJ for entry in twin.changed_index["C-D"])


def test_every_ranked_plan_is_clear_on_shared_track(twin):
    twin.disrupt(RAJ, "A", 30)
    rec = twin.recommend(RAJ)
    assert rec["ranking"]["state"] == "RANKED"
    for (key, _cid), cand in twin._cache.items():
        overrides = {k: p for k, (p, _hold) in cand["yields"].items()}
        found = twin.conflicts(key, cand["plan"], twin.position(key)["index"], overrides=overrides)
        assert not [c for c in found if c["is_conflict"]], cand["label"]


def test_path_through_waits_for_the_local_on_every_piece(twin):
    twin.disrupt(RAJ, "A", 30)
    pathed = twin._path_through(RAJ, twin.plan_of(RAJ), 0)
    assert pathed is not None and pathed.enter[0] > twin.plan_of(RAJ).enter[0]
    assert not [c for c in twin.conflicts(RAJ, pathed, 0) if c["is_conflict"]]


def test_closing_a_piece_closes_the_express_section_and_reopening_reopens_it(twin):
    twin.update_section("B-C", available=False)
    assert not twin.physical("A-D").available
    run = twin.runs[RAJ]
    assert "A-D closed" in twin._violations(twin.plan_of(RAJ), 0, run)
    rec = twin.recommend(RAJ)
    assert rec["ranking"]["state"] == "RANKED"
    for cand in rec["ranking"]["candidates"]:
        assert "A-D" not in cand["route_ahead"] and "B-C" not in cand["route_ahead"]
        assert "C-X" in cand["route_ahead"]  # round the closure by the bypass
    twin.update_section("B-C", available=True)
    assert twin.physical("A-D").available


def test_a_closure_of_the_express_section_reaches_every_local_on_it(twin):
    twin.update_section("A-D", obstacle=True)
    assert all(twin.section(p).obstacle for p in ("A-B", "B-C", "C-D"))
    blocked = {(t.section_id, *t.train_ids) for t in twin.threats.active() if t.type == "OBSTACLE"}
    assert ("A-B", RAJ) in blocked and ("A-B", LOCAL) in blocked
    assert all(sid != "A-D" for sid, *_ in blocked)  # reported on the pieces, once each


def test_opposing_trains_on_one_single_line_piece_are_critical(twin):
    twin.disrupt(RAJ, "A", 80)  # now meets 59004 head-on between C and D
    twin.tick(108)  # 11:38: the Rajdhani is on its A-D section, on the C-D piece; 59004 is on C-D too
    assert twin.position(RAJ)["section_id"] == "A-D"
    head_on = [t for t in twin.threats.active() if t.type == "OPPOSING_SAME_SECTION"]
    assert head_on and head_on[0].section_id == "C-D" and set(head_on[0].train_ids) == {RAJ, OPPOSING}
    assert OPPOSING in {n["run"] for n in twin.cab(RAJ)["nearby_trains"]}


def test_the_changed_run_index_follows_the_plans(twin):
    twin.disrupt(RAJ, "A", 30)
    twin.disrupt(LOCAL, "B", 10)
    twin.disrupt(RAJ, "A", 5)  # replaced again: the old entries must go
    expected = sorted(
        (piece, k, i, round(p.enter[i] + f0 * (p.exit[i] - p.enter[i]), 6), pfrm)
        for k, p in twin.plans.items()
        for i, sid in enumerate(p.sections)
        for piece, f0, _f1, pfrm in twin.parts(sid, p.frm[i])
    )
    actual = sorted(
        (piece, k, i, round(e, 6), pfrm) for piece, es in twin.changed_index.items() for e, k, i, _x, pfrm, *_ in es
    )
    assert expected == actual
    assert all(es == sorted(es) for es in twin.changed_index.values())  # time order: windows found by bisection
    # A window query sees exactly the changed occupations overlapping it.
    e, x = twin.plans[RAJ].enter[0], twin.plans[RAJ].exit[0]
    assert RAJ in {k for k, *_ in twin.occupants("B-C", e, x)}
    assert RAJ not in {k for k, *_ in twin.occupants("B-C", x + 60, x + 120)}


def test_with_no_way_round_a_closure_the_controller_is_told_where_to_hold(twin):
    twin.update_section("B-C", available=False)  # closes the Rajdhani's A-D too
    twin.update_section("C-X", available=False)  # and the bypass
    rec = twin.recommend(RAJ)
    assert rec["state"] == "NO_FEASIBLE_PLAN"
    assert rec["ranking"]["fallback"].startswith(f"Hold {RAJ} at A, the last stop before A-D")
    assert "until the section reopens" in rec["reason"]


def test_a_diverted_train_may_wait_for_paths_on_the_diversion(twin):
    twin.update_section("B-C", available=False)  # the Rajdhani must go by the bypass
    cands = twin.candidates(RAJ, twin.first_open(RAJ))
    labels = [c["label"] for c in cands]
    assert any(label.startswith("REROUTE ") for label in labels)
    for c in cands:  # every feasible option avoids the closed track, waits or not
        if c["feasible"]:
            assert "B-C" not in c["plan"].sections and "A-D" not in c["plan"].sections


def test_a_chain_that_doubles_back_is_not_the_section_track(tmp_path):
    # B lies 1.5 km beyond A: B-D runs through A, so B-D is B-A then A-D - but A-D is not B-D "through" B.
    stations = {"A": (77.0, 28.0), "B": (76.985, 28.0), "D": (77.5, 28.0)}
    trains = {
        "12001": ("Raj", [("A", "None", "10:00"), ("D", "10:40", "None")]),
        "12002": ("Raj", [("B", "None", "11:00"), ("D", "11:26", "None")]),
        "59001": ("Pass", [("B", "None", "08:00"), ("A", "08:05", "None")]),
    }
    data = _build(tmp_path, stations, trains)
    assert "A-D" not in data.parts  # its chain via B doubles back
    assert [p[0] for p in data.parts["B-D"][0]] == ["A-B", "A-D"]
    for forward, backward in data.parts.values():  # every piece is physical track, once
        for pieces in (forward, backward):
            assert len({p[0] for p in pieces}) == len(pieces) and not {p[0] for p in pieces} & set(data.parts)
    twin = NationalTwin(data, start_min=590.0)
    twin.disrupt("12001@0", "A", 45)  # now on A-D 10:45-11:25 while 12002 runs through A from about 11:01
    found = twin.conflicts("12001@0", twin.plan_of("12001@0"), 0)
    assert any(c["other"] == "12002@0" and c["section_id"] == "A-D" and c["is_conflict"] for c in found)


def test_a_closure_ahead_on_the_section_the_train_is_running_on_is_not_ignored(tmp_path):
    trains = dict(TRAINS)
    trains["12951"] = ("Raj", [("A", "None", "10:00"), ("D", "13:00", "None")])  # slow: C-D far ahead
    trains["59001"] = ("Pass", [("A", "None", "14:30"), ("B", "14:42", "14:43"), ("C", "14:55", "14:56"),
                                ("D", "15:08", "None")])  # fmt: skip
    twin = NationalTwin(_build(tmp_path, STATIONS, trains), start_min=603.0)  # 10:03, on the A-B piece of A-D
    assert twin.position(RAJ)["section_id"] == "A-D" and twin.first_open(RAJ) == 1
    twin.update_section("C-D", available=False)
    rec = twin.recommend(RAJ)
    assert rec["state"] == "NO_FEASIBLE_PLAN" and not rec["approvable"]
    assert any("C-D closed, ahead on the section the train is running on" in r for x in rec["ranking"]["rejected"]
               for r in x["reasons"])  # fmt: skip
    assert rec["ranking"]["fallback"].startswith(f"Stop {RAJ} at C, the last station before C-D on its run over A-D")


def test_trains_told_to_wait_may_not_wait_where_there_is_no_loop(tmp_path):
    register = {"sections": {}, "stations": {c: {"loops": 0, "source": "IR_SWR"} for c in "AB"}, "checksum": "t"}
    twin = NationalTwin(_build(tmp_path, STATIONS, TRAINS, register), start_min=590.0)
    twin.disrupt(RAJ, "A", 30)
    rec = twin.recommend(RAJ)
    for (_key, _cid), cand in twin._cache.items():
        for okey, (oplan, _h) in cand["yields"].items():
            current = twin.plan_of(okey)
            for i, v in oplan.sources.items():
                if v > current.sources.get(i, 0.0) + 1e-6:
                    assert oplan.frm[i] not in "AB", (cand["label"], okey, oplan.frm[i])
    rejected = [r for x in rec["ranking"]["rejected"] for r in x["reasons"]]
    assert any("(told to wait): no loop at A" in r for r in rejected)


def test_clearing_the_express_section_keeps_an_obstacle_reported_on_a_piece(twin):
    twin.update_section("B-C", obstacle=True)
    twin.update_section("A-D", obstacle=True)
    twin.update_section("A-D", obstacle=False)
    assert twin.section("B-C").obstacle and twin.physical("A-D").obstacle
    assert not twin.section("A-B").obstacle and not twin.section("C-D").obstacle
    twin.update_section("B-C", obstacle=False)  # the piece itself inspected and cleared
    assert not twin.physical("A-D").obstacle


def test_a_register_row_for_an_express_path_is_not_applied(tmp_path):
    register = {"sections": {"A-D": {"tracks": 2, "headway_min": 1.0, "source": "IR_WTT"}}, "stations": {},
                "checksum": "t"}  # fmt: skip
    data = _build(tmp_path, STATIONS, TRAINS, register)
    assert "A-D" not in data.headway and data.network.sections["A-D"].tracks == 1
    assert data.stats["register_rows_not_applied"] == ["A-D"]
