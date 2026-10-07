"""Shadow-mode trial: actual controller decisions compared with the recommendations shown at the time."""

from __future__ import annotations

import pytest
from test_national import data  # noqa: F401 - shared synthetic national network fixture

from india_rail.railguard.national import NationalTwin
from india_rail.railguard.shadow import ActualDecision, ShadowTrial


def test_agreement_is_measured_against_the_recommendation_shown_at_the_time(data):  # noqa: F811
    twin = NationalTwin(data, start_min=600.0)
    trial = ShadowTrial(twin)
    twin.disrupt("12001@0", "C", 6)
    rec = twin.recommend("12001@0")
    top = rec["ranking"]["candidates"][0]["action"].split("+")[0]
    assert top in ("CONTINUE", "HOLD", "PATH", "PRIORITY", "REROUTE")
    plans_before = dict(twin.plans)
    trial.record(ActualDecision("12001@0", top, twin.now, "controller-1"))
    other = next(a for a in ("CONTINUE", "HOLD", "REROUTE") if a != top)
    trial.record(ActualDecision("12001@0", other, twin.now, "controller-1"))
    report = trial.report()
    assert report["decisions_with_a_prior_recommendation"] == 2
    assert report["top1_agreement_pct"] == 50.0
    assert twin.plans == plans_before  # shadow mode changes nothing
    assert any(e["type"] == "SHADOW_ACTUAL_DECISION" for e in twin.audit.events)


def test_decisions_before_any_recommendation_and_bad_input(data):  # noqa: F811
    trial = ShadowTrial(NationalTwin(data, start_min=600.0))
    trial.record(ActualDecision("12001@0", "HOLD", 590.0, "controller-1", hold_min=5))
    assert trial.report()["decisions_with_a_prior_recommendation"] == 0
    with pytest.raises(ValueError):
        trial.record(ActualDecision("12001@0", "TELEPORT", 600.0, "controller-1"))
    with pytest.raises(KeyError):
        trial.record(ActualDecision("99999@0", "HOLD", 600.0, "controller-1"))
