"""Nexus RailGuard: planning, threats, EvidenceGate fail-closed, authority separation, audit."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from india_rail.railguard import api as rg_api
from india_rail.railguard.cab import build_advisory
from india_rail.railguard.engine import RailGuardEngine
from india_rail.railguard.evidence import checksum
from india_rail.railguard.scenarios import SCENARIOS, run_all


def _types(engine: RailGuardEngine) -> set[str]:
    return {t.type for t in engine.threats.active()}


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(rg_api.router)
    return TestClient(app)


def _top(rec):
    return rec["ranking"]["candidates"][0]


@pytest.fixture()
def engine() -> RailGuardEngine:
    return RailGuardEngine()


# ---- ranking -----------------------------------------------------------------
def test_normal_timetable_is_recommended_unchanged(engine):
    rec = engine.recommend()
    assert rec["state"] == "REVIEWABLE" and rec["approvable"]
    assert _top(rec)["action"] == "CONTINUE"
    assert "CONVERGING_PATH" not in _types(engine)


def test_every_factor_is_exposed_and_sums_to_score(engine):
    for cand in engine.recommend()["ranking"]["candidates"]:
        assert set(cand["factors"]) == {"delay", "conflict", "infra", "energy", "threat", "evidence", "complexity"}
        assert all(0 <= v <= 1 for v in cand["factors"].values())
        assert abs(sum(cand["contributions"].values()) - cand["score"]) < 0.01


def test_losers_explain_why_they_lost(engine):
    candidates = engine.recommend()["ranking"]["candidates"]
    assert candidates[0]["why_lost"] == []
    assert all(c["why_lost"] for c in candidates[1:])


def test_infrastructure_stress_changes_ranking(engine):
    assert "S02" in _top(engine.recommend())["train_plans"]["A"]["route"]
    engine.update_section("S02", condition=0.3)
    balanced = _top(engine.recommend())
    assert "S02" not in balanced["train_plans"]["A"]["route"]
    engine.set_weights("FASTEST")
    fastest = _top(engine.recommend())
    assert "S02" in fastest["train_plans"]["A"]["route"]
    assert balanced["raw"]["infra"] < fastest["raw"]["infra"]


def test_heavier_axle_load_scores_more_stress():
    from india_rail.railguard.model import demo_network, demo_trains
    from india_rail.railguard.stress import section_stress

    net, trains = demo_network(), demo_trains()
    freight = section_stress(trains["A"], net.sections["S02"], 75)["stress"]
    express = section_stress(trains["B"], net.sections["S02"], 75)["stress"]
    assert freight > express


@pytest.mark.parametrize(
    "change,reason",
    [({"available": False}, "closed"), ({"obstacle": True}, "obstacle")],
)
def test_hard_constraints_reject_routes(engine, change, reason):
    engine.update_section("S05", **change)
    for threat in engine.threats.active():
        if threat.severity == "CRITICAL":
            engine.acknowledge(threat.id, "controller")
    rec = engine.recommend()
    assert all("S05" not in c["train_plans"]["A"]["route"] for c in rec["ranking"]["candidates"])
    assert any(reason in " ".join(r["reasons"]) for r in rec["ranking"]["rejected_routes"])


def test_axle_limit_is_a_hard_constraint(engine):
    engine.net.sections["S02"].axle_limit_t = 22.5
    rec = engine.recommend()
    assert all("S02" not in c["train_plans"]["A"]["route"] for c in rec["ranking"]["candidates"])


def test_recommended_plans_never_conflict(engine):
    engine.trains["A"].departure_delay_min = 5
    for cand in engine.recommend()["ranking"]["candidates"]:
        assert all(sep["gap_min"] >= 3 for sep in cand["closest_separations"])


# ---- threats -------------------------------------------------------------------
def test_converging_path_detected_for_late_train(engine):
    engine.trains["A"].departure_delay_min = 5
    engine.refresh()
    threat = next(t for t in engine.threats.active() if t.type == "CONVERGING_PATH")
    assert threat.severity == "WARNING" and threat.section_id == "S06"
    assert set(threat.train_ids) == {"A", "B"}
    assert threat.controller_recommendation and threat.driver_message


def test_no_converging_threat_for_diverging_trains(engine):
    # Express leaves after the freight has long cleared the shared single line.
    engine.trains["B"].departure_delay_min = 30
    engine.refresh()
    assert "CONVERGING_PATH" not in _types(engine)


def test_threat_lifecycle_open_ack_cleared(engine):
    engine.inject_fault("obstacle", section_id="S05")
    threat = next(t for t in engine.threats.active() if t.type == "OBSTACLE")
    assert threat.lifecycle == "OPEN"
    engine.acknowledge(threat.id, "controller")
    assert threat.lifecycle == "ACKNOWLEDGED"
    engine.inject_fault("clear_obstacle", section_id="S05")
    assert threat.lifecycle == "CLEARED" and "OBSTACLE" not in _types(engine)


def test_impossible_jump_rejected_and_flagged(engine):
    engine.tick(10)
    result = engine.ingest_position(
        {"train_id": "A", "section_id": "S06", "from_node": "J3", "offset_km": 1, "t": engine.t, "speed_kmph": 70}
    )
    assert result == {"accepted": False, "reason": "implausible movement"}
    assert "IMPOSSIBLE_MOVEMENT" in _types(engine)
    assert engine.trains["A"].section_id is None  # twin did not move


def test_contradictory_gnss_is_flagged_not_trusted(engine):
    engine.tick(10)
    result = engine.ingest_position(
        {"train_id": "A", "section_id": "S02", "from_node": "J1", "offset_km": 5, "t": engine.t, "source": "GNSS_SIM"}
    )
    assert result["applied"] is False
    assert "EVIDENCE_CONFLICT" in _types(engine)
    assert engine.trains["A"].section_id is None


@pytest.mark.parametrize(
    "obs,reason",
    [
        ({"section_id": "S99", "from_node": "W"}, "unknown section or endpoint"),
        ({"section_id": "S01", "from_node": "W", "offset_km": 50}, "offset outside section"),
        ({"from_node": "W", "t": 10_000}, "timestamp in the future"),
        ({"from_node": "W", "speed_kmph": 900}, "speed outside 0-250 km/h"),
    ],
)
def test_feed_validation(engine, obs, reason):
    result = engine.ingest_position({"train_id": "A", **obs})
    assert result == {"accepted": False, "reason": reason}


# ---- EvidenceGate fail-closed --------------------------------------------------
def test_stale_position_fails_closed(engine):
    rec = engine.recommend()
    engine.approve(rec["snapshot_id"], "C1", "controller")
    engine.tick(300)
    engine.inject_fault("freeze_feed", train_id="A")
    engine.tick(45)
    held = engine.recommend()
    assert held["state"] == "HOLD" and not held["approvable"]
    assert "position:A" in held["assessment"]["stale"]
    with pytest.raises(ValueError):
        engine.approve(held["snapshot_id"], "C1", "controller")
    assert build_advisory(engine, "A")["status"] == "DATA UNAVAILABLE"
    assert build_advisory(engine, "A")["advisory_speed_band_kmph"] is None


def test_missing_mandatory_evidence_is_unavailable(engine):
    engine.evidence.remove("condition:S06")
    rec = engine.recommend()
    assert rec["state"] == "UNAVAILABLE" and not rec["approvable"]
    assert rec["assessment"]["missing"] == ["condition:S06"]


def test_critical_threat_blocks_approval_until_acknowledged(engine):
    engine.inject_fault("obstacle", section_id="S05")
    assert engine.recommend()["state"] == "REVIEW"
    for t in engine.threats.active():
        engine.acknowledge(t.id, "controller")
    assert engine.recommend()["approvable"]


# ---- authority separation ------------------------------------------------------------
def test_cab_shows_only_the_approved_plan(engine):
    cab = build_advisory(engine, "A")
    assert cab["status"] == "HOLD-FOR-CONTROLLER" and cab["route_strip"]["approved_route"] == []
    first = engine.recommend()
    engine.approve(first["snapshot_id"], "C1", "controller")
    approved = build_advisory(engine, "A")["route_strip"]["approved_route"]
    engine.update_section("S02", condition=0.3)
    newer = engine.recommend()  # a different recommendation, not yet approved
    assert _top(newer)["train_plans"]["A"]["route"] != approved
    assert build_advisory(engine, "A")["route_strip"]["approved_route"] == approved
    assert build_advisory(engine, "A")["footer"].startswith("ADVISORY PROTOTYPE")


def test_superseded_snapshot_cannot_be_approved(engine):
    old = engine.recommend()
    engine.recommend()
    with pytest.raises(ValueError, match="superseded"):
        engine.approve(old["snapshot_id"], "C1", "controller")


def test_approval_needs_named_controller(engine):
    rec = engine.recommend()
    with pytest.raises(PermissionError):
        engine.approve(rec["snapshot_id"], "C1", "")


def test_api_cab_is_read_only_and_controller_token_enforced(monkeypatch):
    monkeypatch.setattr(rg_api, "ENGINE", RailGuardEngine())
    monkeypatch.setenv("RAILGUARD_CONTROLLER_TOKEN", "secret-token")
    client = _client()
    assert client.get("/railguard/cab/A").status_code == 200
    assert client.post("/railguard/cab/A").status_code == 405
    assert client.post("/railguard/recommend", json={}).status_code == 403
    rec = client.post("/railguard/recommend", json={}, headers={"X-Controller-Token": "secret-token"}).json()
    body = {"snapshot_id": rec["snapshot_id"], "candidate_id": "C1", "controller": "driver"}
    assert client.post("/railguard/approve", json=body).status_code == 403
    ok = client.post("/railguard/approve", json=body, headers={"X-Controller-Token": "secret-token"})
    assert ok.status_code == 200 and ok.json()["authority"] == "ADVISORY_ONLY"


def test_feed_cannot_approve_and_needs_feed_token(monkeypatch):
    monkeypatch.setattr(rg_api, "ENGINE", RailGuardEngine())
    monkeypatch.setenv("RAILGUARD_FEED_TOKEN", "feed-token")
    client = _client()
    report = {"train_id": "A", "from_node": "W", "speed_kmph": 0}
    assert client.post("/railguard/twintrack/position", json=report).status_code == 403
    accepted = client.post("/railguard/twintrack/position", json=report, headers={"X-Feed-Token": "feed-token"})
    assert accepted.json()["accepted"] is True


def test_obstacle_sensor_raises_but_cannot_clear(monkeypatch):
    monkeypatch.setattr(rg_api, "ENGINE", RailGuardEngine())
    client = _client()
    assert client.post("/railguard/twintrack/obstacle", json={"section_id": "S05"}).status_code == 200
    assert "OBSTACLE" in _types(rg_api.ENGINE)
    client.post("/railguard/twintrack/obstacle", json={"section_id": "S05", "detected": False})
    assert rg_api.ENGINE.net.sections["S05"].obstacle is True  # only a controller inspection clears it
    assert client.get("/railguard/cab/A/compact").text.endswith("ADVISORY ONLY")


# ---- audit and determinism -------------------------------------------------------
def test_snapshot_replay_reproduces_and_detects_tampering(engine):
    rec = engine.recommend()
    replay = engine.replay(rec["snapshot_id"])
    assert replay["integrity_ok"] and replay["replay_matches"]
    engine.audit.snapshots[rec["snapshot_id"]]["outputs"]["ranking"]["candidates"][0]["score"] = 0.0
    assert not engine.audit.verify_snapshot(rec["snapshot_id"])


def test_audit_chain_detects_edits(engine):
    engine.recommend()
    assert engine.audit.verify_chain()
    engine.audit.events[0]["actor"] = "someone-else"
    assert not engine.audit.verify_chain()


def test_scenarios_are_deterministic():
    def fingerprint():
        engine = RailGuardEngine()
        result = SCENARIOS["delay_conflict"]["run"](engine)
        return checksum([s["checksum"] for s in engine.audit.snapshots.values()]), result["passed"]

    assert fingerprint() == fingerprint()


def test_all_six_judge_scenarios_pass():
    results = run_all()
    assert len(results) == 6
    failed = {name: [k for k, v in r["checks"].items() if not v] for name, r in results.items() if not r["passed"]}
    assert failed == {}
