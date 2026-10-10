"""Alerts that do not flicker: a threat missing for a moment is not a new alert, an escalation is never hidden."""

from __future__ import annotations

from india_rail.railguard.threats import (
    ACKNOWLEDGED,
    CLEAR_AFTER_S,
    CLEARED,
    OPEN,
    REOPEN_S,
    Threat,
    ThreatRegistry,
)


def _t(severity: str = "WARNING", key: str = "CONFLICT:A:B") -> Threat:
    return Threat(key, "CONFLICT", severity, ["A", "B"], "S1", ["twin"], 1.0, "look", "caution", "detail")


def test_a_warning_missing_for_a_moment_is_kept_and_not_raised_again():
    reg = ThreatRegistry()
    reg.update([_t()], 0)
    first = reg.active()[0]
    reg.update([], 10)  # one evaluation without it
    assert reg.active() == [first] and first.absent_since_t == 10 and first.lifecycle == OPEN
    reg.update([_t()], 20)
    assert reg.active()[0] is first and first.absent_since_t is None and reg.raised == 1


def test_a_warning_gone_long_enough_clears_and_coming_back_keeps_its_id_and_acknowledgement():
    reg = ThreatRegistry()
    reg.update([_t()], 0)
    threat = reg.active()[0]
    reg.acknowledge(threat.id, "SCR controller")
    reg.update([], 10)
    reg.update([], 10 + CLEAR_AFTER_S)
    assert threat.lifecycle == CLEARED and reg.active() == []
    reg.update([_t()], 10 + CLEAR_AFTER_S + 30)
    assert reg.active()[0] is threat and threat.lifecycle == ACKNOWLEDGED and threat.reopened == 1
    assert reg.raised == 1 and reg.came_back == 1


def test_a_threat_back_after_the_reopen_window_is_a_new_alert():
    reg = ThreatRegistry()
    reg.update([_t()], 0)
    old = reg.active()[0]
    reg.update([], 0, settled=True)
    reg.update([_t()], REOPEN_S + 1)
    assert reg.active()[0] is not old and reg.raised == 2


def test_an_acknowledged_warning_that_becomes_critical_must_be_acknowledged_again():
    reg = ThreatRegistry()
    reg.update([_t()], 0)
    threat = reg.active()[0]
    reg.acknowledge(threat.id, "SCR controller")
    reg.update([_t("CAUTION")], 10)
    assert threat.lifecycle == ACKNOWLEDGED  # less severe: the acknowledgement stands
    reg.update([_t("CRITICAL")], 20)
    assert threat.lifecycle == OPEN and threat.acknowledged_by is None and threat.severity == "CRITICAL"


def test_a_critical_threat_clears_at_once_and_comes_back_open():
    reg = ThreatRegistry()
    reg.update([_t("CRITICAL")], 0)
    threat = reg.active()[0]
    reg.acknowledge(threat.id, "SCR controller")
    reg.update([], 5)
    assert threat.lifecycle == CLEARED
    reg.update([_t("CRITICAL")], 10)
    assert reg.active()[0] is threat and threat.lifecycle == OPEN  # a danger back again is looked at again


def test_after_a_deliberate_change_what_is_gone_clears_at_once():
    reg = ThreatRegistry()
    reg.update([_t()], 0)
    threat = reg.active()[0]
    reg.update([], 5, settled=True)  # e.g. the plan that resolves it was approved
    assert threat.lifecycle == CLEARED and reg.held == 0


def test_an_approved_plan_clears_its_conflict_warning_at_once(tmp_path):
    from india_rail.railguard.national import NationalTwin
    from tests.test_shared_track import LOCAL, RAJ, STATIONS, TRAINS, _build

    twin = NationalTwin(_build(tmp_path, STATIONS, TRAINS), start_min=590.0)
    twin.disrupt(RAJ, "A", 25)
    assert any(LOCAL in t.train_ids for t in twin.threats.active())
    rec = twin.recommend(RAJ)
    twin.approve(rec["snapshot_id"], rec["ranking"]["candidates"][0]["candidate_id"], "controller")
    assert not [t for t in twin.threats.active() if t.type in ("CONVERGING_PATH", "CONFLICT")]
