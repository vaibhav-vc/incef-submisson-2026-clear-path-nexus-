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


def test_a_control_office_export_is_imported_row_by_row(data):  # noqa: F811
    from india_rail.railguard.eta import twin_service_date

    twin = NationalTwin(data, start_min=600.0)
    trial = ShadowTrial(twin)
    day = twin_service_date(twin).isoformat()
    text = "\n".join([
        "train_number,start_date,action,decided_at,station,hold_min,desk,note",
        f"12001,{day},HOLD,{day}T10:05:00+05:30,C,6,SCR-Desk-3,crossing",
        f"12001,{day},TELEPORT,{day}T10:06:00+05:30,C,,,",
        f"99999,{day},HOLD,{day}T10:07:00+05:30,C,,,",
        f"12001,{day},CONTINUE,{day}T10:08:00,,,,",
        f"12001,{day},HOLD,{day}T10:09:00+05:30,C,900,,",
    ])  # fmt: skip
    result = trial.import_csv(text, "controller-1", twin_service_date(twin))
    assert result["recorded"] == 1 and result["refused"] == 4
    reasons = [r.get("reason", "") for r in result["rows"]]
    assert "action must be one of" in reasons[1] and "no run" in reasons[2]
    assert "time zone" in reasons[3] and "0-720" in reasons[4]
    assert trial.decisions[0].at_min == 605.0 and trial.decisions[0].by == "controller-1 (SCR-Desk-3)"
    with pytest.raises(ValueError, match="header"):
        trial.import_csv("train,when\n1,2", "controller-1", twin_service_date(twin))


def test_the_report_survives_restarts_from_the_persisted_audit(data, tmp_path, monkeypatch):  # noqa: F811
    from india_rail.railguard.shadow import report_from_audit_dir

    monkeypatch.setenv("RAILGUARD_AUDIT_DIR", str(tmp_path))
    twin = NationalTwin(data, start_min=600.0)
    twin.disrupt("12001@0", "C", 6)
    top = twin.recommend("12001@0")["ranking"]["candidates"][0]["action"].split("+")[0]
    ShadowTrial(twin).record(ActualDecision("12001@0", top, twin.now, "controller-1"))
    restarted = NationalTwin(data, start_min=600.0)  # a new process: memory is empty, the files remain
    assert ShadowTrial(restarted).report()["decisions_logged"] == 0
    report = report_from_audit_dir(tmp_path)
    assert report["decisions_with_a_prior_recommendation"] == 1 and report["top1_agreement_pct"] == 100.0
    assert report["by_actual_action"][top]["decisions"] == 1
    assert report["median_minutes_from_recommendation_to_decision"] is not None


def test_a_decision_matches_only_a_recommendation_made_before_it_the_same_day():
    from india_rail.railguard.shadow import build_report

    snap = {"snapshot_id": "SNAP-0001", "at": "2026-10-07T04:00:00+00:00", "inputs": {"run": "1@0", "now": 570.0},
            "outputs": {"state": "PLANNING_ONLY", "ranking": {"candidates": [{"action": "HOLD"}]}}}  # fmt: skip
    before = {"run": "1@0", "action": "HOLD", "at_min": 560.0, "at": "2026-10-07T03:59:00+00:00"}
    next_day = {"run": "1@0", "action": "HOLD", "at_min": 575.0, "at": "2026-10-08T04:10:00+00:00"}
    in_time = {"run": "1@0", "action": "HOLD", "at_min": 575.0, "at": "2026-10-07T04:05:00+00:00"}
    report = build_report([before, next_day, in_time], [snap])
    assert [r["matched"] for r in report["rows"]] == [False, False, True]
    assert report["decisions_without_a_recommendation"]["count"] == 2
