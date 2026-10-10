"""Official (data.gov.in format) timetable ingestion, reconciliation and use of official rail distances."""

from __future__ import annotations

import sqlite3

import pytest

from india_rail import official
from india_rail.railguard.national import build_national

HEADER = (
    "Train No,Train Name,SEQ,Station Code,Station Name,Arrival time,Departure Time,Distance,"
    "Source Station,Source Station Name,Destination Station,Destination Station Name"
)
CSV = (
    HEADER
    + """
'12001,Train 12001,1,AAA,Station AAA,00:00:00,10:05:00,0,AAA,Station AAA,CCC,Station CCC
'12001,Train 12001,2,BBB,Station BBB,10:15:00,10:16:00,12.4,AAA,Station AAA,CCC,Station CCC
'12001,Train 12001,3,CCC,Station CCC,10:30:00,00:00:00,25,AAA,Station AAA,CCC,Station CCC
54001,Train 54001,1,AAA,Station AAA,00:00:00,10:00:00,0,AAA,Station AAA,CCC,Station CCC
54001,Train 54001,2,BBB,Station BBB,10:14:00,10:20:00,12.6,AAA,Station AAA,CCC,Station CCC
54001,Train 54001,3,DDD,Station DDD,10:40:00,00:00:00,30,AAA,Station AAA,DDD,Station DDD
bad,row,x,EEE,,,,not-a-number,,,,
"""
)


def test_parse_and_section_distances():
    rows = official.parse_timetable(CSV)
    assert len(rows) == 6  # the malformed row is skipped, not guessed
    assert rows[0]["train_number"] == "12001" and rows[0]["dep_min"] == 605
    km = official.section_km(rows)
    assert km["AAA-BBB"] == pytest.approx(12.5)  # median of 12.4 and 12.6
    assert km["BBB-CCC"] == pytest.approx(12.6)


def test_rejects_files_that_are_not_timetables():
    with pytest.raises(ValueError, match="missing columns"):
        official.parse_timetable("a,b,c\n1,2,3\n")


def test_ingest_records_provenance_reconciles_and_twin_uses_rail_km(db_path, tmp_path):
    path = tmp_path / "timetable.csv"
    path.write_text(CSV)
    report = official.ingest(path, db_path=db_path)
    assert report["rows"] == 6 and len(report["sha256"]) == 64
    assert report["trains_in_both"] == 2 and report["stations_only_official"] == 1  # DDD is new
    assert report["identical_departure_times_pct"] == 100.0
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT publisher FROM official_provenance").fetchone()[0].startswith("Ministry of Railways")
    con.close()
    data = build_national(db_path)
    section = data.network.sections["AAA-BBB"]
    assert section.length_km == pytest.approx(12.5) and "OFFICIAL_TIMETABLE_KM" in section.data_quality
    assert data.stats["sections_official_length"] >= 1


def test_download_without_published_url_points_to_the_portal():
    with pytest.raises(SystemExit, match="data.gov.in"):
        official.download("ogd_timetable")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Daily", "Daily"),
        ("Mon, Wed, Fri", "Mon,Wed,Fri"),
        ("YNYNYNN", "Mon,Wed,Fri"),
        ("1111111", "Daily"),
        ("1,3,5", "Mon,Wed,Fri"),
        ("Tue/Thu/Sat", "Tue,Thu,Sat"),
        ("Monday and Thursday", "Mon,Thu"),
        ("M T W", None),  # T could be Tuesday or Thursday: refuse to guess
        ("weekly?", None),
        ("", None),
    ],
)
def test_running_days_are_parsed_or_refused(text, expected):
    assert official.parse_running_days(text) == expected


def test_twin_runs_trains_only_on_their_days(db_path, tmp_path):
    from datetime import date

    path = tmp_path / "timetable.csv"
    lines = CSV.strip().splitlines()
    tagged = [lines[0] + ",Days of Run"] + [line + (",Mon" if line.startswith("'12001") else ",") for line in lines[1:]]
    path.write_text("\n".join(tagged) + "\n")
    report = official.ingest(path, db_path=db_path)
    assert report["trains_with_running_days"] == 1
    monday = build_national(db_path, service_date=date(2026, 10, 5))
    tuesday = build_national(db_path, service_date=date(2026, 10, 6))
    assert "12001@0" in monday.runs and "12001@0" not in tuesday.runs  # 12001 runs on Mondays only
    assert "54001@0" in tuesday.runs  # unknown days: treated as daily (and flagged by the schedule audit)
    assert monday.stats["trains_with_known_running_days"] == 1
