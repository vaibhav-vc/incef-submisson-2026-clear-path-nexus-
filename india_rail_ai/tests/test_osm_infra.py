"""Real track data from OpenStreetMap: counting parallel lines, single-line stretches, path acceptance."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("scipy")

from india_rail import osm_infra  # noqa: E402

DEG_PER_M = 1 / 111_320  # near the equator: metres to degrees (latitude 0 keeps the arithmetic plain)


def _osm(ways: list[dict], stations: list[dict] | None = None) -> dict:
    """Build the arrays `extract` returns from simple way descriptions: lines of (lon, lat) points."""

    node_ids, lon, lat, way_nodes, lengths = [], [], [], [], []
    for w in ways:
        ids = [len(node_ids) + k + 1 for k in range(len(w["points"]))]
        if w.get("join_to") is not None:  # share the first node with an earlier way
            ids[0] = w["join_to"]
        for nid, (x, y) in zip(ids, w["points"], strict=True):
            if nid > len(node_ids):
                node_ids.append(nid)
                lon.append(x)
                lat.append(y)
        way_nodes.extend(ids)
        lengths.append(len(ids))
        w["ids"] = ids
    order = np.argsort(node_ids)
    return {
        "node_id": np.array(node_ids)[order],
        "lon": np.array(lon)[order],
        "lat": np.array(lat)[order],
        "way_id": np.arange(len(ways)),
        "way_len": np.array(lengths),
        "way_nodes": np.array(way_nodes),
        "way_service": np.array([w.get("service", 0) for w in ways], dtype=np.int8),
        "way_electrified": np.array([w.get("electrified", 1) for w in ways], dtype=np.int8),
        "way_gauge": np.array([1676] * len(ways)),
        "way_maxspeed": np.array([w.get("maxspeed", -1.0) for w in ways]),
        "way_counted": np.array([w.get("counted", 1) for w in ways], dtype=np.int8),
        "stations": stations or [],
    }


def _line(offset_m: float, km: float = 20.0, **extra) -> dict:
    xs = np.linspace(0, km * 1000 * DEG_PER_M, 21)
    return {"points": [(float(x), offset_m * DEG_PER_M) for x in xs], **extra}


MID = (10_000 * DEG_PER_M, 0.0)
EAST = (1.0, 0.0)


def test_two_lines_five_metres_apart_are_a_double_line():
    graph = osm_infra.RailGraph(_osm([_line(0), _line(5)]))
    assert graph.lines_at(*MID, *EAST) == 2


def test_one_line_is_single_and_freight_corridors_and_sidings_do_not_count():
    graph = osm_infra.RailGraph(_osm([_line(0), _line(12, counted=0), _line(-6, service=1)]))
    assert graph.lines_at(*MID, *EAST) == 1


def test_a_double_line_mapped_far_apart_still_reads_double():
    graph = osm_infra.RailGraph(_osm([_line(0), _line(80)]))  # e.g. two separate bridges
    assert graph.lines_at(*MID, *EAST) == 2


def test_the_same_line_curving_away_is_not_a_second_line():
    # one line that bends 40 degrees just past the sample point: its next segment is near but not parallel
    bend = [(0.0, 0.0), (10_000 * DEG_PER_M, 0.0), (10_000 * DEG_PER_M + 0.0005, 0.00042)]
    graph = osm_infra.RailGraph(_osm([{"points": bend}]))
    assert graph.lines_at(10_000 * DEG_PER_M - 20 * DEG_PER_M, 0.0, *EAST) == 1


def test_single_line_stretches_decide_the_section():
    assert osm_infra._single_stretches([2, 2, 2, 2, 2, 2, 2, 2, 2, 2]) == (0.0, 0.0)
    share, run = osm_infra._single_stretches([2, 1, 1, 1, 1, 1, 1, 2, 2, 2])
    assert share == 0.6 and run == pytest.approx(6 * osm_infra.SAMPLE_STEP_KM)


def test_section_path_is_accepted_and_measured_or_rejected_when_implausible():
    stations = [
        {"id": 1, "lon": 0.0, "lat": 0.0, "refs": ["AAA"], "name": "A"},
        {"id": 2, "lon": 20_000 * DEG_PER_M, "lat": 0.0, "refs": ["BBB"], "name": "B"},
    ]
    osm = _osm([_line(0, maxspeed=110.0), _line(5)], stations)
    graph = osm_infra.RailGraph(osm)
    located = osm_infra.locate_stations(graph, osm, {"AAA": (None, None), "BBB": (None, None), "ZZZ": (None, None)})
    assert set(located) == {"AAA", "BBB"} and located["AAA"]["by"] == "OSM_REF"
    good = osm_infra.section_attributes(graph, located, {"AAA-BBB": 20.0})["AAA-BBB"]
    assert good["quality"] == "ACCEPTED" and good["lines"] == 2 and good["osm_km"] == pytest.approx(20.0, abs=0.1)
    assert good["electrified_share"] == 1.0 and good["gauge_mm"] == 1676
    wrong_km = osm_infra.section_attributes(graph, located, {"AAA-BBB": 60.0})["AAA-BBB"]
    assert wrong_km["quality"] == "REJECTED_DISAGREES_WITH_TIMETABLE_KM"


def test_tag_parsers():
    assert osm_infra._gauge("1676;1000") == 1676 and osm_infra._gauge("broad") is None
    assert osm_infra._speed("110") == 110.0 and osm_infra._speed("60 mph") == pytest.approx(96.54)
    assert osm_infra._speed("signals") is None
