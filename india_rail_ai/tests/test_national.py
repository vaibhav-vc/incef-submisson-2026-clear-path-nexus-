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


DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.mark.skipif(not (DATA / "india_rail.sqlite").exists(), reason="open timetable not ingested")
def test_open_network_scale():
    data = build_national(DATA / "india_rail.sqlite")
    assert data.stats["sections"] > 8000 and data.stats["junctions"] > 1000 and data.stats["runs_in_window"] > 7000


@pytest.mark.skipif(not (DATA / "real.sqlite").exists(), reason="real data not built (python -m india_rail real build)")
def test_real_network_runs_on_real_timetable_days_and_track_data():
    data = build_national(DATA / "real.sqlite")
    stats = data.stats
    assert stats["sections"] > 9000 and stats["junctions"] > 2000 and stats["runs_in_window"] > 3000
    assert stats["trains_with_known_running_days"] == stats["train_numbers"]  # every day from observed running
    assert stats["sections_with_osm_infrastructure"] > 0.85 * stats["sections"]
    assert stats["stations_located_from_osm"] > 8000
    # every section says where its track count came from; nothing is unlabelled
    assert all("tracks:" in s.data_quality for s in data.network.sections.values())


def test_production_runs_only_on_the_real_timetable(monkeypatch):
    from india_rail.railguard import national

    monkeypatch.setenv("RAILGUARD_MODE", "production")
    monkeypatch.setenv("RAILGUARD_TIMETABLE", "open")
    with pytest.raises(RuntimeError, match="real timetable"):
        national.timetable_source()


def test_live_reported_delay_follows_an_attached_forecast_but_a_controller_delay_does_not(data):
    calls = []

    class Forecast:
        def plan(self, twin, key, p, d_now):
            calls.append((key, p, d_now))
            return twin.propagate(twin.plan_of(key), {p: d_now + 7})  # stand-in: forecast says +7 more

    twin = NationalTwin(data, start_min=600.0)
    twin.eta = Forecast()
    twin.disrupt("12001@0", "B", 10)  # a controller's statement: carried forward as given
    assert not calls and twin.plans["12001@0"].enter[1] == twin.runs["12001@0"].s_enter[1] + 10
    twin.reset()
    twin.disrupt("12001@0", "B", 8, actor="feed:NTES", observed_arrival_delay=10)
    assert calls == [("12001@0", 1, 10.0)] and twin.plans["12001@0"].enter[1] == twin.runs["12001@0"].s_enter[1] + 17


def test_mapped_track_data_sets_line_count_length_and_positions(tmp_path, data):
    import shutil
    import sqlite3

    src = next(Path(p) for p in [tmp_path.parent] for p in p.glob("national*/rail.sqlite"))
    db = tmp_path / "rail.sqlite"
    shutil.copy(src, db)
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE osm_stations (code TEXT PRIMARY KEY, lat REAL, lon REAL, located_by TEXT, osm_node INTEGER);
        CREATE TABLE osm_sections (edge TEXT PRIMARY KEY, quality TEXT, osm_km REAL, lines INTEGER,
            lines_median REAL, single_share REAL, longest_single_km REAL, samples INTEGER, electrified_share REAL,
            electrification_known_share REAL, gauge_mm INTEGER, maxspeed_kmph REAL, maxspeed_share REAL,
            service_share REAL);
        INSERT INTO osm_stations VALUES ('B', 28.001, 77.101, 'OSM_REF', 1);
        INSERT INTO osm_sections VALUES ('B-C', 'ACCEPTED', 10.4, 2, 2, 0, 0, 20, 1.0, 1.0, 1676, NULL, 0, 0);
        INSERT INTO osm_sections VALUES ('A-B', 'REJECTED_DETOUR', 30.0, 1, 1, 1, 9, 20, 1.0, 1.0, 1676, NULL, 0, 0);
        """
    )
    con.commit()
    con.close()
    mapped = build_national(db)
    bc, ab = mapped.network.sections["B-C"], mapped.network.sections["A-B"]
    assert bc.tracks == 2 and "tracks:OSM_MULTI_2" in bc.data_quality and "length:OSM_MAPPED_PATH" in bc.data_quality
    assert bc.length_km == 10.4 and mapped.infrastructure["B-C"]["electrified_share"] == 1.0
    assert ab.tracks == 1 and "OSM" not in ab.data_quality  # a rejected path is not used
    assert mapped.network.nodes["B"] == (77.101, 28.001)  # the mapped station position
    plain = build_national(db, use_osm=False)
    assert plain.network.sections["B-C"].tracks == 1 and not plain.infrastructure


def test_a_forecast_never_replaces_a_controller_decision(data):
    from india_rail.railguard.eta import forecast_plan

    class Forecast:
        def plan(self, twin, key, p, d_now):
            return forecast_plan(twin.plan_of(key), p, {p: d_now, p + 1: 0.0})  # claims a full recovery

    twin = NationalTwin(data, start_min=600.0)
    twin.eta = Forecast()
    held = twin.propagate(twin.plan_of("12001@0"), {1: 15.0})  # stands in for an approved 15-minute hold at B
    twin._set_plan("12001@0", held)
    twin.disrupt("12001@0", "B", 5, actor="feed:NTES", observed_arrival_delay=5)
    assert twin.plans["12001@0"].enter[1] == held.enter[1] + 5  # added on top of the hold, not replaced


def test_forecast_plans_never_overlap_themselves_or_run_impossibly_fast():
    from india_rail.railguard.eta import RUN_FLOOR, forecast_plan
    from india_rail.railguard.national import Plan

    s_enter, s_exit = [0.0, 30.0, 60.0], [28.0, 58.0, 90.0]
    plan = Plan(["a", "b", "c"], ["A", "B", "C"], ["B", "C", "D"], s_enter[:], s_exit[:], s_enter, s_exit, 3)
    out = forecast_plan(plan, 0, {0: 40.0, 1: 0.0, 2: 0.0, 3: 0.0})  # the forecast recovers 40 minutes at once
    for i in range(3):
        assert out.exit[i] - out.enter[i] >= RUN_FLOOR * (s_exit[i] - s_enter[i]) - 1e-9
        if i:
            assert out.enter[i] >= out.exit[i - 1]


def test_every_departure_offered_for_a_delay_is_accepted(data):
    twin = NationalTwin(data, start_min=605.0)  # 12001 is between A and B: A is behind it
    run = next(r for r in twin.runs_for("12001") if r["run"] == "12001@0")
    stations = [d["station"] for d in run["next_departures"]]
    assert stations and stations[0] == "B"
    for station in stations:
        twin.disrupt("12001@0", station, 5)  # the console offers it: the twin accepts it
