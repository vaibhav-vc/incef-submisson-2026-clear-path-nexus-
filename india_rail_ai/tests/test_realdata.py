"""Real-life running data: parsing, running days from observations, placeholder timetables, verification maths."""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile

import numpy as np
import pandas as pd
import pytest

from india_rail import realdata, realval
from india_rail.ingest import SCHEMA

ROUTES = """stnSerialNumber,trainNumber,trainName,station_code,station_name,distance,arrivalTime,departureTime
1,12001,Test Rajdhani,A,Alpha,0,11:00 PM,11:00 PM
2,12001,Test Rajdhani,B,Bravo,40,11:50 PM,11:52 PM
3,12001,Test Rajdhani,C,Charlie,80,12:30 AM,12:30 AM
1,01164,Placeholder Special,A,Alpha,0,06:20 AM,06:20 AM
2,01164,Placeholder Special,B,Bravo,40,06:20 AM,06:20 AM
3,01164,Placeholder Special,C,Charlie,80,06:20 AM,06:20 AM
"""
DELAYS = """train,date,station,sch_arr,act_arr,arr_delay,sch_dep,act_dep,dep_delay
12001,2024-09-02,A,11:00 PM,11:00 PM,0.0,11:00 PM,11:00 PM,0.0
12001,2024-09-02,B,11:50 PM,12:00 AM,10.0,11:52 PM,12:02 AM,10.0
12001,2024-09-02,C,12:30 AM,12:45 AM,15.0,12:30 AM,12:45 AM,15.0
12001,2024-09-09,A,11:00 PM,11:00 PM,0.0,11:00 PM,11:00 PM,0.0
12001,2024-09-09,C,12:30 AM,12:30 AM,0.0,12:30 AM,12:30 AM,0.0
01164,2024-09-02,A,06:20 AM,06:30 AM,10.0,06:20 AM,06:30 AM,10.0
"""


@pytest.fixture()
def real_db(tmp_path):
    archive = tmp_path / "observed.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(realdata.MEMBER.format("train_routes_Sep2024.csv"), ROUTES)
        z.writestr(realdata.MEMBER.format("train_routes_delays_Sep2024.csv"), DELAYS)
        z.writestr(realdata.MEMBER.format("stations_zones_mapping.json"), json.dumps({"A": "NR", "C": "NR"}))
    base = tmp_path / "base.sqlite"
    con = sqlite3.connect(base)
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO stations VALUES (?,?,?,?,?,?)",
        [("A", "Alpha", None, None, 28.0, 77.0), ("B", "Bravo", None, None, 28.0, 77.4)],
    )
    con.commit()
    con.close()
    out = tmp_path / "real.sqlite"
    report = realdata.build(archive, base, out)
    return out, report


def test_twelve_hour_clock_and_midnight():
    parsed = realdata.clock12(pd.Series(["12:05 AM", "12:30 PM", "11:59 PM", "25:00 XM"]))
    assert parsed.iloc[:3].tolist() == [5, 750, 1439] and np.isnan(parsed.iloc[3])
    assert realdata._advance(1430, 30) == (1470, False)  # 23:50 -> 00:30 is the next day
    assert realdata._advance(500, 499) == (500, True)  # a one-minute step back is a source error, clamped


def test_train_type_from_name_then_numbering_scheme():
    assert realdata.train_type("12001", "Ndls Shatabdi")[0] == "Shtb"
    assert realdata.train_type("20171", "Vande Bharat Express")[0] == "Shtb"
    assert realdata.train_type("12951", "Mumbai Rajdhani")[0] == "Raj"
    assert realdata.train_type("12345", "Some Express") == ("SF", "NUMBER_SCHEME")
    assert realdata.train_type("54321", "X") == ("Pass", "NUMBER_SCHEME")
    assert realdata.train_type("13001", "Ganga Express") == ("Exp", "DEFAULT_EXPRESS")


def test_build_derives_running_days_and_actual_times_and_drops_placeholder_timetables(real_db):
    path, report = real_db
    assert report["trains"] == 1 and report["trains_with_placeholder_timetable_excluded"] == 1
    con = sqlite3.connect(path)
    days = con.execute("SELECT running_days FROM train_details WHERE number = '12001'").fetchone()[0]
    assert days == "Mon"  # seen on two Mondays only
    rows = con.execute(
        "SELECT run_date, seq, sch_arr_min, act_arr_min, delay_min FROM observed_stops ORDER BY run_date, seq"
    ).fetchall()
    # C is at 00:30 the next day: journey minute 1470; 15 late -> 1485. The 9 Sep run skipped B.
    assert rows == [("2024-09-02", 0, 1380, 1380, 0), ("2024-09-02", 1, 1430, 1440, 10),
                    ("2024-09-02", 2, 1470, 1485, 15), ("2024-09-09", 0, 1380, 1380, 0),
                    ("2024-09-09", 2, 1470, 1470, 0)]  # fmt: skip
    assert dict(con.execute("SELECT edge, km FROM official_section_km")) == {"A-B": 40.0, "B-C": 40.0}
    assert con.execute("SELECT zone FROM stations WHERE code = 'C'").fetchone()[0] == "NR"  # added from 2024 data


def test_fetch_refuses_a_file_that_does_not_match_the_pinned_digest(tmp_path, monkeypatch):
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(realdata.urllib.request, "urlopen", lambda *a, **k: Response(b"not the dataset"))
    with pytest.raises(ValueError, match="pinned SHA-256"):
        realdata.fetch(tmp_path)
    assert not (tmp_path / "observed_running_sep2024.zip").exists()
    (tmp_path / "observed_running_sep2024.zip").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="pinned SHA-256"):
        realdata.fetch(tmp_path)


# ---- verification maths on small frames -------------------------------------------------------------------
def _frames() -> dict[str, pd.DataFrame]:
    obs = pd.DataFrame(
        {
            "train": ["1", "1", "1", "2", "2", "2"],
            "date": ["2024-09-02"] * 3 + ["2024-09-22"] * 3,
            "seq": [0, 1, 2, 0, 1, 2],
            "station": list("ABCABC"),
            "sch": [0, 30, 60, 0, 30, 60],
            "delay": [0, 8, 20, 0, 0, 3],
        }
    )
    obs["act"] = obs.sch + obs.delay
    obs["run"] = obs.train + "|" + obs.date
    stops = pd.DataFrame(
        {"train": ["1"] * 3 + ["2"] * 3, "seq": [0, 1, 2] * 2, "station": list("ABCABC"), "arr_min": [0, 30, 60] * 2,
         "dep_min": [0, 32, 60] * 2, "dwell_min": [0, 2, 0] * 2}
    )  # fmt: skip
    sections = pd.DataFrame({"train": ["1", "1", "2", "2"], "seq": [0, 1, 0, 1], "km": [30.0, 30.0, 30.0, 30.0],
                             "single": [True, False, True, False], "osm_lines": [1, 2, 1, 2]})  # fmt: skip
    trains = pd.DataFrame({"train": ["1", "2"], "type": ["Exp", "Pass"], "priority": [3, 4]})
    return {"obs": obs, "stops": stops, "sections": sections, "trains": trains}


def test_destination_punctuality_uses_the_fifteen_minute_rule_on_mail_express_only():
    result = realval.credibility(_frames())
    assert result["destination_on_time_pct_mail_express"] == 0.0  # train 1 (Exp) arrived 20 late; 2 is Pass
    assert result["official_figure"]["value_pct"] == 77.12


def test_section_running_splits_single_and_double_line():
    result = realval.section_running(_frames())
    assert result["osm_single_line"]["traversals"] == 2 and result["osm_double_or_more"]["traversals"] == 2
    assert result["osm_double_or_more"]["lost_5_min_or_more_pct"] == 50.0  # 1: 8 -> 20 on the double section


def test_forecast_history_never_contains_the_rows_own_answer():
    d = _frames()
    lookups = realval.Lookups(d)
    # train 1 ran only on a training date: with its own day left out there is no history at all
    row = lookups.rows("1", "2024-09-02", 0, 0.0, [2], own={0: 0.0, 1: 8.0, 2: 20.0})
    assert np.isnan(row["hist_q"][0]) and row["hist_n_q"][0] == 0
    # the same train on a later (test) date sees the training day's delay as history
    later = lookups.rows("1", "2024-09-25", 0, 0.0, [2])
    assert later["hist_q"][0] == 20.0 and later["km_gap"][0] == 60.0 and later["single_km_gap"][0] == 30.0


def test_flag_scores_compare_with_trains_in_the_same_state():
    frame = pd.DataFrame(
        {
            "late": [True, True, False, True, True, False, False, False],
            "role": ["gives_way", "gives_way", "gives_way", "none", "none", "none", "none", "keeps_way"],
            "loss": [10, 0, 6, 10, 0, 0, 0, 0],
            "single": [True] * 8,
        }
    )
    scores = realval._flag_scores(frame)
    assert scores["gives_way_lost_5_min_pct"] == pytest.approx(66.67)
    # baseline weighted 2/3 late (50% lost) + 1/3 not late (0% lost) = 33.3%
    assert scores["comparable_unflagged_lost_5_min_pct"] == pytest.approx(33.33)
    assert scores["lift"] == 2.0


def test_bootstrap_gain_reports_the_improvement_and_an_interval():
    runs = np.array(["a", "a", "b", "b", "c"])
    gain = realval._bootstrap_gain(runs, np.array([10.0, 10, 8, 8, 6]), np.array([5.0, 5, 4, 4, 3]), seed=1)
    assert gain["mae_reduction_min"] == pytest.approx(4.2) and gain["ci95_min"][0] <= 4.2 <= gain["ci95_min"][1]
