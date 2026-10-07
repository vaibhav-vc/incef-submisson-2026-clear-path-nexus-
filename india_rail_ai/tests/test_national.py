"""National-network RailGuard on a synthetic network built through the real ingest path.

Main line A-B-C-D (single line, no opposing overlaps in the timetable) with a
bypass B-X-C. 12001 (Rajdhani) runs A->D, 54001 (Passenger) runs D->A five
minutes behind it on C-D, 19001 (Express) uses the bypass.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from india_rail.ingest import build_database
from india_rail.railguard.national import NationalTwin, build_national, gap

STATIONS = {"A": (77.0, 28.0), "B": (77.1, 28.0), "C": (77.2, 28.0), "D": (77.3, 28.0), "X": (77.15, 28.05)}
TRAINS = {
    "12001": (
        "Raj",
        [("A", "None", "10:00"), ("B", "10:10", "10:11"), ("C", "10:25", "10:26"), ("D", "10:40", "None")],
    ),
    "54001": (
        "Pass",
        [("D", "None", "10:45"), ("C", "10:59", "11:00"), ("B", "11:14", "11:15"), ("A", "11:25", "None")],
    ),
    "19001": ("Exp", [("B", "None", "09:00"), ("X", "09:08", "09:09"), ("C", "09:20", "None")]),
}


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    tmp: Path = tmp_path_factory.mktemp("national")
    stations = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": list(xy)},
                "properties": {"code": c, "name": f"Station {c}", "zone": "NR", "state": "Delhi"},
            }
            for c, xy in STATIONS.items()
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
                    "distance": 40,
                    "return_train": "",
                },
            }
            for n, (t, _stops) in TRAINS.items()
        ],
    }
    schedules, row_id = [], 1
    for number, (_t, stops) in TRAINS.items():
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
    return build_national(tmp / "rail.sqlite")


@pytest.fixture()
def twin(data) -> NationalTwin:
    return NationalTwin(data, start_min=600.0)


def _types(twin):
    return {t.type for t in twin.threats.active()}


def test_build_labels_inferred_attributes(data):
    assert data.stats["sections"] == 5 and data.stats["junctions"] == 2
    section = data.network.sections["C-D"]
    assert section.tracks == 1 and "ASSUMED_SINGLE_NO_EVIDENCE" in section.data_quality
    assert "CROW_X1.03" in section.data_quality and section.utilisation == 2
    assert {"12001@0", "54001@0", "19001@0"} <= set(data.runs)


def test_gap_rules():
    assert gap(1, False, 0, 10, 12, 20) == 2  # single line: opposing moves conflict
    assert gap(2, False, 0, 10, 5, 15) is None  # multi-track opposing: separate tracks
    assert gap(2, True, 0, 10, 2, 8) == -1.0  # overtake on plain line


def test_timetable_itself_has_no_conflicts(twin):
    for key in twin.runs:
        assert not [c for c in twin.conflicts(key, twin.plan_of(key), 0) if c["is_conflict"]]


def test_late_priority_train_gets_feasible_ranked_alternatives(twin):
    result = twin.disrupt("12001@0", "C", 6)
    assert result["conflicts"] and result["conflicts"][0]["other"] == "54001@0"
    assert "CONVERGING_PATH" in _types(twin)
    assert twin.cab("12001@0")["status"] == "HOLD-FOR-CONTROLLER"
    rec = twin.recommend("12001@0")
    assert rec["state"] == "PLANNING_ONLY" and rec["approvable"]
    labels = " | ".join(c["summary"] for c in rec["ranking"]["candidates"])
    assert "PRIORITY" in labels and "yields" in labels
    top = rec["ranking"]["candidates"][0]
    # A 6-minute-late Rajdhani is not held for long when a passenger train can give way.
    assert top["final_delay_min"] <= 10 and "54001@0" in top["yields"]
    twin.approve(rec["snapshot_id"], top["candidate_id"], "controller")
    for key, plan in twin.plans.items():
        assert not [c for c in twin.conflicts(key, plan, 0) if c["is_conflict"]]
    assert "CONVERGING_PATH" not in _types(twin)
    assert twin.cab("12001@0")["plan_source"] == top["summary"]


def test_obstacle_blocks_until_acknowledged_and_reroute_uses_bypass(twin):
    twin.update_section("B-C", obstacle=True)
    assert "OBSTACLE" in _types(twin)
    twin.disrupt("12001@0", "A", 1)
    rec = twin.recommend("12001@0")
    assert rec["state"] == "REVIEW" and not rec["approvable"]
    for threat in twin.threats.active():
        twin.threats.acknowledge(threat.id, "controller")
    rec = twin.recommend("12001@0")
    reroutes = [c for c in rec["ranking"]["candidates"] if c["summary"].startswith("12001@0: REROUTE")]
    assert reroutes and "B-X" in reroutes[0]["route_ahead"] and "B-C" not in reroutes[0]["route_ahead"]
    assert any("obstacle" in " ".join(r["reasons"]) for r in rec["ranking"]["rejected"])


def test_stale_live_feed_fails_closed(twin):
    twin.disrupt("12001@0", "C", 6)
    assert twin.ingest_position("12001@0", "A-B", 1.0)["accepted"]
    twin.tick(4)  # 240 s > 180 s stale policy
    rec = twin.recommend("12001@0")
    assert rec["state"] == "HOLD" and not rec["approvable"]
    assert "STALE_POSITION" in _types(twin)
    assert twin.cab("12001@0")["status"] == "DATA UNAVAILABLE"
    assert twin.cab("12001@0")["advisory_speed_band_kmph"] is None


def test_off_plan_observation_is_flagged(twin):
    assert not twin.ingest_position("12001@0", "B-X", 0.5)["accepted"]
    assert "ROUTE_DEVIATION" in _types(twin)


def test_superseded_recommendation_cannot_be_approved(twin):
    twin.disrupt("12001@0", "C", 6)
    rec = twin.recommend("12001@0")
    twin.tick(1)
    with pytest.raises(ValueError, match="superseded"):
        twin.approve(rec["snapshot_id"], rec["ranking"]["candidates"][0]["candidate_id"], "controller")


def test_replay_reproduces_after_later_changes(twin):
    twin.disrupt("12001@0", "C", 6)
    rec = twin.recommend("12001@0")
    twin.approve(rec["snapshot_id"], rec["ranking"]["candidates"][0]["candidate_id"], "controller")
    twin.update_section("A-B", condition=0.3)
    replay = twin.replay(rec["snapshot_id"])
    assert replay["integrity_ok"] and replay["replay_matches"] and replay["data_matches"]
    assert twin.audit.verify_chain()


def test_reset_restores_timetable(twin):
    twin.disrupt("12001@0", "C", 6)
    twin.reset()
    assert not twin.plans and not twin.pending and not twin.threats.active()


REAL_DB = Path(__file__).resolve().parent.parent / "data" / "india_rail.sqlite"


@pytest.mark.skipif(not REAL_DB.exists(), reason="real timetable not ingested (run python -m india_rail ingest)")
def test_real_network_scale():
    from india_rail.railguard.national import national_data

    data = national_data()
    assert data.stats["sections"] > 8000 and data.stats["junctions"] > 1000 and data.stats["runs_in_window"] > 7000
