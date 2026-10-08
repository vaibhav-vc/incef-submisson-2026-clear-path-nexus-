"""Delay-minimisation advisor: chronic losses, junction congestion, late starts and unachievable timings."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from india_rail import delay_advisor

STATIONS = [("AAA", "Alpha", "NR"), ("BBB", "Bravo", "NR"), ("CCC", "Charlie Jn", "NR"), ("DDD", "Delta", "NR")]


@pytest.fixture()
def built(tmp_path, monkeypatch):
    """30 days of real-style running. 12001 starts 15 min late and loses 12 min on BBB-CCC every day, then
    recovers 8 min on CCC-DDD; 12002 runs to time; 12003 loses on BBB-CCC only once (an incident, not chronic)."""

    db = tmp_path / "real.sqlite"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE observed_stops (train_number TEXT, run_date TEXT, seq INTEGER, station_code TEXT,
            sch_arr_min INTEGER, act_arr_min INTEGER, delay_min INTEGER);
        CREATE TABLE trains (number TEXT, name TEXT, type TEXT, zone TEXT);
        CREATE TABLE stations (code TEXT, name TEXT, zone TEXT);
        CREATE TABLE osm_sections (edge TEXT, quality TEXT, lines INTEGER, electrified_share REAL,
            maxspeed_kmph REAL, osm_km REAL);
        """
    )
    con.executemany("INSERT INTO stations VALUES (?,?,?)", STATIONS)
    con.executemany("INSERT INTO trains VALUES (?,?,?,?)", [("12001", "Late Exp", "Exp", "NR"),
                    ("12002", "Punctual Exp", "Exp", "NR"), ("12003", "Once Exp", "Exp", "NR")])  # fmt: skip
    con.execute("INSERT INTO osm_sections VALUES ('BBB-CCC','ACCEPTED',1,1.0,110,40)")
    rows = []
    for k in range(30):
        day = (date(2024, 9, 1) + timedelta(days=k)).isoformat()
        for train, delays in (("12001", [15, 15, 27, 19]), ("12002", [0, 1, 0, 0]),
                              ("12003", [0, 0, 40 if k == 3 else 0, 30 if k == 3 else 0])):  # fmt: skip
            for seq, (code, _n, _z) in enumerate(STATIONS):
                sch = 600 + 60 * seq
                rows.append((train, day, seq, code, sch, sch + delays[seq], delays[seq]))
    con.executemany("INSERT INTO observed_stops VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    out = tmp_path / "advisor.json"
    monkeypatch.setattr(delay_advisor, "ADVISOR_PATH", out)
    monkeypatch.setattr(delay_advisor, "MIN_TRAVERSALS", 5)
    report = delay_advisor.build(db, out)
    yield report
    delay_advisor.registry.cache_clear()


def test_chronic_section_loss_is_found_with_its_lever(built):
    top = built["sections"][0]
    assert top["section"] == "BBB-CCC" and top["chronic"] and top["lines"] == 1
    assert top["lost_min_per_day"] == pytest.approx(12 + 40 / 30, abs=0.1)
    assert "crossing loops" in top["lever"]  # single line: a capacity lever
    assert built["summary"]["persistence"]["sections"]["rank_correlation"] > 0.5


def test_late_starts_and_unachievable_timing_and_late_trains(built):
    assert [x["train"] for x in built["late_starts"]] == ["12001"]
    timing = next(x for x in built["timetable"] if x["train"] == "12001")
    assert timing["section"] == "BBB-CCC" and timing["median_loss_min"] == 12 and timing["recovery_elsewhere_min"] == 8
    assert "move 8 min" in timing["lever"]
    late = next(x for x in built["trains"] if x["train"] == "12001")
    assert late["on_time_pct"] == 0 and late["worst_sections"][0]["section"] == "BBB-CCC"
    assert all(x["train"] != "12003" for x in built["timetable"])  # one bad day is not an unachievable timing


def test_incidents_over_three_hours_are_kept_out_of_patterns(tmp_path, built):
    assert built["summary"]["incidents_over_3h_excluded"]["traversals"] == 0  # 40 min is not an incident
    assert delay_advisor.for_train("12001")["late_start"][0]["late_share_pct"] == 100


def test_advisor_api(built):
    from india_rail import api

    client = TestClient(api.app)
    summary = client.get("/railguard/national/advisor").json()
    assert summary["summary"]["late_starting_trains"] == 1
    sections = client.get("/railguard/national/advisor/sections?limit=1").json()["findings"]
    assert sections[0]["section"] == "BBB-CCC"
    assert client.get("/railguard/national/advisor/train/12001").json()["chronic_lateness"]["train"] == "12001"
    assert client.get("/railguard/national/advisor/passwords").status_code == 422
