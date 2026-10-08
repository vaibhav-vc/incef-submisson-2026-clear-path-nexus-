"""Freight corridor pathing: every planning rule is enforced and independently checked."""

from __future__ import annotations

import itertools
import random

import pytest

from india_rail import freight
from india_rail.freight import FreightPlanner, FreightTrain, check, max_simultaneous

CORRIDOR = {
    "segments": [
        {"from_km": 0.0, "to_km": 25.0, "km": 25.0, "lines": 1},
        {"from_km": 25.0, "to_km": 50.0, "km": 25.0, "lines": 1},
        {"from_km": 50.0, "to_km": 75.0, "km": 25.0, "lines": 2},
        {"from_km": 75.0, "to_km": 100.0, "km": 25.0, "lines": 2},
    ]
}


def planner(**kw) -> FreightPlanner:
    return FreightPlanner(CORRIDOR, "Western", **kw)


def test_two_trains_in_one_direction_keep_headway_and_never_overtake():
    p = planner(headway_min=10)
    p.plan([FreightTrain("A", 0, 100, 0, priority=3), FreightTrain("B", 0, 100, 1, priority=3)])
    a, b = p.plans["A"], p.plans["B"]
    for la, lb in zip(a.legs, b.legs, strict=True):
        assert lb.enter - la.enter >= 10 - 1e-6 and lb.exit - la.exit >= 10 - 1e-6
    assert check(p) == []


def test_opposing_trains_never_share_a_single_line_segment():
    p = planner(headway_min=8)
    p.plan([FreightTrain("UP", 0, 100, 0), FreightTrain("DN", 100, 0, 0)])
    for seg in (0, 1):
        (e1, x1, *_), (e2, x2, *_) = p.occ[seg]
        assert e2 >= x1 + 8 - 1e-6 or e1 >= x2 + 8 - 1e-6
    assert check(p) == []


def test_higher_priority_is_pathed_first_and_blocks_are_never_entered():
    p = planner()
    p.block(2, 0, 120)
    p.plan([FreightTrain("LOW", 0, 100, 0, priority=5), FreightTrain("HIGH", 0, 100, 0, priority=1)])
    assert p.plans["HIGH"].legs[0].enter <= p.plans["LOW"].legs[0].enter
    for plan in p.plans.values():
        leg = next(leg for leg in plan.legs if leg.segment == 2)
        assert leg.enter >= 120
    assert check(p) == []


def test_the_checker_catches_an_injected_conflict():
    p = planner()
    p.plan([FreightTrain("A", 0, 100, 0)])
    p.occ[3].append((p.plans["A"].legs[3].enter + 1, p.plans["A"].legs[3].exit + 1, True, "X"))
    assert any("headway" in v for v in check(p))


def test_loops_are_never_overfilled_under_random_demand():
    rng = random.Random(7)
    for seed in range(30):
        p = planner(headway_min=rng.choice((6.0, 10.0)), loops=rng.choice((1, 2)))
        trains = [FreightTrain(f"T{i}", *rng.sample((0.0, 25.0, 50.0, 75.0, 100.0), 2), rng.uniform(0, 300),
                               rng.randint(1, 5)) for i in range(25)]  # fmt: skip
        result = p.plan(trains)
        assert result["violations"] == [], seed
        assert result["planned"] == len(trains)


def test_max_simultaneous_counts_waits_at_the_same_moment():
    assert max_simultaneous([(0, 100), (0, 10), (20, 30), (40, 50)], 0, 100) == 2
    assert max_simultaneous([(0, 10), (10, 20)], 0, 20) == 1  # one leaves as the other arrives


def test_published_figures_are_carried_with_sources():
    assert freight.PUBLISHED["trains_per_day_fy2025"] == 403 and freight.PUBLISHED["sources"]


def test_cut_points_follow_interchanges_and_a_maximum_length():
    cuts = freight._cut_points(100.0, [12.0, 60.0])
    assert cuts[0] == 0.0 and cuts[-1] == 100.0 and 12.0 in cuts and 60.0 in cuts
    assert max(b - a for a, b in itertools.pairwise(cuts)) <= freight.SEGMENT_KM * 1.5


@pytest.mark.parametrize("bad", [{"corridor": "Northern"}, {"trains": []}, {"headway_min": 1}])
def test_api_rejects_bad_freight_requests(bad):
    from fastapi.testclient import TestClient

    from india_rail.api import app

    body = {"corridor": "Western", "trains": [{"id": "F1", "origin_km": 0, "destination_km": 50, "ready_min": 0}]}
    assert TestClient(app).post("/railguard/freight/plan", json={**body, **bad}).status_code == 422
