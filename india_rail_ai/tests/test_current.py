"""Every train running now: current timetable (GTFS) ingest, operators, registry and the routes trains follow."""

from __future__ import annotations

import json
import sqlite3
import zipfile

import pytest

from india_rail import current
from india_rail.ingest import SCHEMA

GTFS = {
    "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\n1,Indian Railways,https://indianrailways.gov.in/,Asia/Kolkata\n",
    "feed_info.txt": "feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date,feed_end_date\nX,https://x,en,20260830,20260930\n",
    "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\nLJN,LUCKNOW,26.83,80.92\nCNB,KANPUR CENTRAL,26.45,80.35\n"
    "NDLS,NEW DELHI,28.64,77.22\n",
    "routes.txt": "route_id,agency_id,route_short_name,route_long_name,route_type\n"
    "82501,1,82501,IRCTC TEJAS EXP,2\n00290,1,00290,PALACE ON WHEEL,2\n12004,1,12004,LJN SHATABDI,2\n",
    "trips.txt": "route_id,service_id,trip_id\n82501,S1,82501\n00290,S2,00290\n12004,S1,12004\n",
    "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
    "S1,1,0,1,1,1,1,1,20260305,20270830\nS2,0,0,1,0,0,0,0,20260101,20260915\n",
    "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence,shape_dist_traveled\n"
    "82501,06:10:00,06:10:00,LJN,1,0\n82501,07:25:00,07:30:00,CNB,2,72\n82501,12:25:00,12:25:00,NDLS,3,511\n"
    "00290,22:00:00,22:00:00,NDLS,1,0\n00290,25:30:00,25:40:00,CNB,2,440\n"
    "12004,15:35:00,15:35:00,LJN,1,0\n12004,16:40:00,16:45:00,CNB,2,72\n",
}


@pytest.fixture()
def built(tmp_path):
    archive = tmp_path / "gtfs.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for name, text in GTFS.items():
            z.writestr(name, text)
    old = tmp_path / "open.sqlite"
    con = sqlite3.connect(old)
    con.executescript(SCHEMA)
    con.execute("INSERT INTO stations VALUES ('NDLS','New Delhi','NR','Delhi',28.64,77.22)")
    con.execute("INSERT INTO trains VALUES ('12345','Old Express','Exp','NR','NDLS','CNB',440,NULL,2,400)")
    con.commit()
    con.close()
    out = tmp_path / "current.sqlite"
    report = current.build(archive, out, open_db=old, real_db=tmp_path / "absent.sqlite")
    return out, report


def test_operators_mark_private_tourist_and_parcel_trains():
    assert current.operator_of("82501", "IRCTC TEJAS EXP") == "IRCTC (private operation)"
    assert current.operator_of("06553", "YPR-GAYA BHARAT GAURAV") == "Bharat Gaurav (service provider operated)"
    assert current.operator_of("00290", "PALACE ON WHEEL") == "Luxury tourist train"
    assert current.operator_of("00111", "BIRD-SGTY RAPID CARGO") == "Parcel / cargo"
    assert current.operator_of("12951", "NDLS TEJAS RAJ") == "Indian Railways"  # a Tejas Rajdhani is not private


def test_times_past_midnight_and_running_days():
    assert current._minutes("25:30:00") == 1530 and current._minutes("bad") is None
    assert current._days({d: "1" for d in current.WEEKDAYS}) == "Daily"
    assert current._days({"wednesday": "1"}) == "Wed"


def test_build_takes_every_train_with_days_validity_and_a_registry_of_all_sources(built):
    out, report = built
    assert report["trains_in_twin"] == 3 and report["operators"]["IRCTC (private operation)"] == 1
    con = sqlite3.connect(out)
    stops = con.execute("SELECT seq, station_code, arr_min, dep_min FROM stops WHERE train_number='00290'").fetchall()
    assert stops == [(0, "NDLS", 1320, 1320), (1, "CNB", 1530, 1540)]  # 25:30 is 01:30 on day 2
    reg = {r[0]: r for r in con.execute("SELECT number, operator, running_days, valid_to, in_current_2026, "
                                        "in_open_2016, note FROM train_registry")}  # fmt: skip
    assert reg["82501"][1:4] == ("IRCTC (private operation)", "Mon,Wed,Thu,Fri,Sat,Sun", "20270830")
    assert reg["00290"][3] == "20260915"  # validity carried so the twin stops running it after that day
    assert reg["12345"][4:] == (0, 1, "open data 2016 only")  # older numbers stay in the registry, flagged
    assert dict(con.execute("SELECT edge, km FROM official_section_km"))["CNB-LJN"] == 72.0


def test_registry_serves_trains_routes_and_stations(built, monkeypatch):
    from india_rail import registry as reg_module

    out, _ = built
    con = sqlite3.connect(out)
    con.executescript(
        """
        CREATE TABLE osm_stations (code TEXT PRIMARY KEY, lat REAL, lon REAL, located_by TEXT, osm_node INTEGER);
        CREATE TABLE osm_sections (edge TEXT PRIMARY KEY, quality TEXT, osm_km REAL, lines INTEGER,
            lines_median REAL, single_share REAL, longest_single_km REAL, samples INTEGER, electrified_share REAL,
            electrification_known_share REAL, gauge_mm INTEGER, maxspeed_kmph REAL, maxspeed_share REAL,
            service_share REAL, geometry TEXT);
        """
    )
    path = [[80.35, 26.45], [80.6, 26.6], [80.92, 26.83]]  # CNB -> LJN, the edge's own order
    con.execute("INSERT INTO osm_sections (edge, quality, osm_km, lines, electrified_share, geometry) "
                "VALUES ('CNB-LJN','ACCEPTED',74.0,2,1.0,?)", (json.dumps(path),))  # fmt: skip
    con.execute("INSERT INTO station_pin VALUES ('LJN','226004','OSM_POSTCODES_WITHIN_0.5_KM',4)")
    con.commit()
    con.close()
    reg = reg_module.Registry(out)
    train = reg.train("82501")
    assert train["operator"] == "IRCTC (private operation)" and train["stops"][0]["pin"] == "226004"
    route = reg.route("82501")
    assert route["geometry"]["coordinates"][:3] == path[::-1]  # LJN -> CNB follows the mapped track, reversed
    assert route["properties"]["sections_on_mapped_track"] == 1
    assert route["properties"]["evidence"][1]["track"] == "STRAIGHT_LINE"  # CNB-NDLS not mapped: said so
    assert [t["number"] for t in reg.search("tejas")] == ["82501"]
    assert reg.station("CNB")["trains_calling"] == 3
    assert reg.train("99999") is None
