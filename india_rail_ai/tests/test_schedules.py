"""Working schedules, per-train metrics and the all-train completeness audit."""

from __future__ import annotations

import sqlite3

import pytest

from india_rail.schedules import audit, stop_matrix, train_metrics, working_schedule


@pytest.fixture()
def con(db_path):
    con = sqlite3.connect(db_path)
    yield con
    con.close()


def test_every_published_train_is_kept_with_its_details(con):
    rows = con.execute("SELECT number, has_schedule, published_distance_km FROM train_details ORDER BY number")
    assert [(n, h) for n, h, _ in rows] == [("12001", 1), ("19001", 1), ("54001", 1)]


def test_stop_matrix_has_days_dwell_distance_and_speed(con):
    stops = stop_matrix(con, "12001")
    assert [s["station_code"] for s in stops] == ["AAA", "BBB", "CCC"]
    assert stops[0]["arrival"] is None and stops[-1]["departure"] is None
    assert stops[1]["dwell_min"] == 1 and stops[1]["day"] == 1
    assert stops[-1]["km_from_origin"] == pytest.approx(25.0)  # scaled to the published 25 km
    assert stops[0]["km_source"] == "STRAIGHT_LINE_SCALED_TO_PUBLISHED_DISTANCE"
    assert stops[0]["section_runtime_min"] == 10 and stops[0]["section_speed_kmph"] > 0
    night = stop_matrix(con, "19001")
    assert night[-1]["day"] == 2  # crosses midnight


def test_metrics_flag_what_the_open_data_lacks(con):
    metrics = train_metrics(con).set_index("number")
    flags = metrics.loc["12001", "flags"].split(",")
    assert "RUNNING_DAYS_UNKNOWN" in flags and "NO_CLASS_INFORMATION" in flags
    assert "NO_USABLE_TIMETABLE" not in flags
    assert metrics.loc["12001", "journey_min"] == 25


def test_audit_covers_all_trains(con):
    result = audit(con)
    assert result["trains_published"] == 3 and result["trains_with_usable_timetable"] == 3
    assert result["coverage_pct"]["running_days"] == 0.0
    assert result["flag_counts"]["RUNNING_DAYS_UNKNOWN"] == 3
    record = working_schedule(con, "54001")
    assert record["train"]["number"] == "54001" and len(record["stops"]) == 3
    assert working_schedule(con, "99999") is None
