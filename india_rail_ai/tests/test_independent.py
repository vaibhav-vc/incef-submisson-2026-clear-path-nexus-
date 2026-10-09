"""The independent separation checker agrees with the planner's own conflict search, from separate code."""

from __future__ import annotations

import random

from test_national import data  # noqa: F401 - shared synthetic national network fixture
from test_shared_track import data as shared  # noqa: F401 - the express-and-local network

from india_rail.railguard import independent
from india_rail.railguard.national import NationalTwin, gap


def test_the_separation_rule_matches_the_twins():
    rng = random.Random(7)
    for _ in range(20000):
        tracks, same = rng.choice((1, 2, 3)), rng.random() < 0.5
        ae, be = rng.uniform(0, 60), rng.uniform(0, 60)
        a, b = (ae, ae + rng.uniform(0.5, 30)), (be, be + rng.uniform(0.5, 30))
        assert independent.separation(tracks, same, a, b) == gap(tracks, same, a[0], a[1], b[0], b[1])


def _agree(twin: NationalTwin) -> int:
    seen = 0
    for key, plan in twin.plans.items():
        start = twin.position(key)["index"]
        theirs = {(c["other"], c["other_index"]) for c in twin.conflicts(key, plan, start) if c["is_conflict"]}
        ours = {(c["other"], c["other_index"]) for c in independent.check(twin, {key: (plan, start)})["conflicts"]}
        assert ours == theirs, key
        seen += len(ours)
    return seen


def test_both_find_the_same_conflicts_after_random_disruptions(data, shared):  # noqa: F811
    found = 0
    for network in (data, shared):
        for seed in range(12):
            rng = random.Random(seed)
            twin = NationalTwin(network, start_min=rng.uniform(560, 700))
            for _ in range(3):
                running = sorted(twin.running()) or sorted(twin.runs)
                key = rng.choice(running)
                plan, first = twin.plan_of(key), twin.first_open(key)
                if first < len(plan.sections):
                    twin.disrupt(key, plan.frm[first], rng.uniform(3, 90), at_index=first)
            found += _agree(twin)
    assert found > 0  # the disruptions did create conflicts for the two to agree on


def test_a_closure_ahead_on_the_current_section_is_seen(shared):  # noqa: F811
    twin = NationalTwin(shared, start_min=603.0)  # the Rajdhani is on A-D, on its A-B piece
    twin.update_section("C-D", available=False)
    assert independent.blocked_ahead(twin, "12951@0", twin.plan_of("12951@0")) == ["C-D"]
    twin.update_section("C-D", available=True)
    twin.update_section("A-B", obstacle=True)  # the piece it is on: still ahead of it until it leaves
    assert independent.blocked_ahead(twin, "12951@0", twin.plan_of("12951@0")) == ["A-B"]
