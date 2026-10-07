"""Offline unit tests for ingestion, network queries and the disruption planner."""

from __future__ import annotations

import pytest

from india_rail.ingest import QualityReport, _advance, parse_clock
from india_rail.network import RailNetwork
from india_rail.planner import DisruptionPlanner, circular_gap


def test_parse_clock():
    assert parse_clock("07:55:00") == 475
    assert parse_clock("None") is None
    assert parse_clock("25:00") is None


def test_advance_crosses_midnight_but_clamps_small_backsteps():
    report = QualityReport()
    assert _advance(23 * 60 + 50, 5, report) == 1440 + 5
    assert _advance(8 * 60 + 30, 8 * 60 + 29, report) == 8 * 60 + 30
    assert report.non_monotonic_times_clamped == 1


def test_circular_gap():
    assert circular_gap(5, 1435) == 10
    assert circular_gap(1435, 5) == -10


def test_overnight_train_times(db):
    net = RailNetwork(db)
    stops = net.schedule("19001")
    assert [s["arr_min"] for s in stops] == [1430, 1445, 1460]
    assert stops[-1]["arrival"] == "00:20 (day 2)"


def test_duplicate_listing_removed(db):
    assert len(RailNetwork(db).schedule("12001")) == 3


def test_trains_between_and_path(db):
    net = RailNetwork(db)
    numbers = [t["number"] for t in net.trains_between("AAA", "CCC")]
    assert numbers == ["54001", "12001", "19001"]
    path = net.fastest_path("AAA", "CCC")
    assert path["stations"] == ["AAA", "BBB", "CCC"]


def test_low_priority_train_yields(db):
    # Passenger delayed 3 min would enter AAA->BBB 2 min ahead of the Rajdhani.
    plan = DisruptionPlanner(db).plan("54001", "AAA", 3, headway_min=6)
    assert plan["status"] == "PROPOSED_FOR_CONTROLLER_REVIEW"
    holds = {(a["train_number"], a["station_code"]): a["minutes"] for a in plan["actions"]}
    # The timetable plans these two 5 min apart, so 5 min (not the 6 min
    # headway) is the separation to restore: enters 10:10 = Rajdhani 10:05 + 5.
    assert holds[("54001", "AAA")] == 7
    assert ("12001", "AAA") not in holds


def test_high_priority_delay_holds_lower_priority(db):
    # Rajdhani delayed 0->3: enters 10:08; passenger scheduled 10:00 is outside
    # headway, but at BBB->CCC the passenger (10:20) is within 6 min of 10:19.
    plan = DisruptionPlanner(db).plan("12001", "AAA", 3, headway_min=6)
    trains_held = {a["train_number"] for a in plan["actions"]}
    assert "12001" not in trains_held
    assert "54001" in trains_held


def test_planned_close_running_is_not_a_conflict(db):
    # A 1-minute delay shrinks the planned 5 min gap to 4, so a hold is needed.
    plan = DisruptionPlanner(db).plan("54001", "AAA", 1, headway_min=6)
    assert ("54001", "AAA") in {(a["train_number"], a["station_code"]) for a in plan["actions"]}
    # An 11-minute delay puts the passenger 6 min behind the Rajdhani, which
    # satisfies the 5 min planned separation: no hold at AAA.
    plan = DisruptionPlanner(db).plan("54001", "AAA", 11, headway_min=6)
    assert not [a for a in plan["actions"] if a["station_code"] == "AAA"]


def test_no_resolution_reports_conflicts(db):
    plan = DisruptionPlanner(db).plan("54001", "AAA", 3, headway_min=6, resolve=False)
    assert plan["actions"] == []
    assert plan["unresolved"]


def test_rejects_unknown_station(db):
    with pytest.raises(ValueError):
        DisruptionPlanner(db).plan("54001", "ZZZ", 5)
