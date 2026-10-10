"""The six scripted judge scenarios.

Each scenario has a `setup` (puts the twin in the starting condition so a
presenter can drive it from Nexus Control) and a `run` (the full scripted
sequence with pass/fail checks, used by tests, metrics and rehearsal).
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from india_rail.railguard.cab import build_advisory
from india_rail.railguard.engine import RailGuardEngine


class Script:
    def __init__(self, engine: RailGuardEngine, name: str, title: str):
        self.engine, self.name, self.title = engine, name, title
        self.steps: list[dict[str, Any]] = []
        self.checks: dict[str, bool] = {}

    def log(self, action: str, observation: Any) -> None:
        self.steps.append({"t_min": round(self.engine.t / 60, 2), "action": action, "observation": observation})

    def check(self, name: str, ok: bool) -> None:
        self.checks[name] = bool(ok)

    def run_until_arrival(self, limit_min: int = 120) -> None:
        while not all(t.finished for t in self.engine.trains.values()) and self.engine.t < limit_min * 60:
            self.engine.tick(60)

    def result(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "steps": self.steps,
            "checks": self.checks,
            "passed": all(self.checks.values()),
            "snapshots": sorted(self.engine.audit.snapshots),
        }


def _types(engine: RailGuardEngine) -> set[str]:
    return {t.type for t in engine.threats.active()}


def _uses(rec: dict[str, Any], section: str, train: str = "A") -> bool:
    return section in rec["ranking"]["candidates"][0]["train_plans"][train]["route"]


# ---- setups (starting conditions only) -----------------------------------------
def setup_normal(engine: RailGuardEngine) -> None:
    engine.reset()


def setup_delay_conflict(engine: RailGuardEngine) -> None:
    engine.reset()
    engine.trains["A"].departure_delay_min = 5
    engine.audit.record(engine.t, "SCENARIO_INPUT", "demo", {"train": "A", "departure_delay_min": 5})
    engine.refresh()


def setup_infrastructure(engine: RailGuardEngine) -> None:
    engine.reset()


def setup_threat(engine: RailGuardEngine) -> None:
    engine.reset()


def setup_stale(engine: RailGuardEngine) -> None:
    engine.reset()


# ---- full scripted runs ----------------------------------------------------------
def run_normal(engine: RailGuardEngine) -> dict[str, Any]:
    setup_normal(engine)
    s = Script(engine, "normal", "Normal operation: non-conflicting paths, everything traceable")
    rec = engine.recommend()
    top = rec["ranking"]["candidates"][0]
    s.log("recommend", {"state": rec["state"], "top": top["summary"], "action": top["action"]})
    s.check("evidence_reviewable", rec["state"] == "REVIEWABLE")
    s.check("continue_on_timetable", top["action"] == "CONTINUE")
    s.check("no_warning_threats", not [t for t in engine.threats.active() if t.severity in ("WARNING", "CRITICAL")])
    engine.approve(rec["snapshot_id"], top["candidate_id"], "controller-demo")
    s.log("approve", top["candidate_id"])
    s.run_until_arrival()
    s.log("run", {tid: t.finished for tid, t in engine.trains.items()})
    s.check("both_trains_arrived", all(t.finished for t in engine.trains.values()))
    s.check("audit_chain_intact", engine.audit.verify_chain())
    return s.result()


def run_delay_conflict(engine: RailGuardEngine) -> dict[str, Any]:
    setup_delay_conflict(engine)
    s = Script(engine, "delay_conflict", "Delay conflict: late freight would meet the express on single line S06")
    s.log("threats", sorted(_types(engine)))
    s.check("converging_path_detected", "CONVERGING_PATH" in _types(engine))
    rec = engine.recommend()
    top = rec["ranking"]["candidates"][0]
    s.log("recommend", {"state": rec["state"], "top": top["summary"], "why": top["factors"]})
    s.check("alternative_offered", top["action"] != "CONTINUE")
    s.check("conflict_free", all(c["gap_min"] >= rec["ranking"]["headway_min"] for c in top["closest_separations"]))
    engine.approve(rec["snapshot_id"], top["candidate_id"], "controller-demo")
    opposing = False
    while not all(t.finished for t in engine.trains.values()) and engine.t < 120 * 60:
        engine.tick(30)
        opposing |= "OPPOSING_SAME_SECTION" in _types(engine)
    s.log("run", {tid: t.finished for tid, t in engine.trains.items()})
    s.check("never_opposing_on_single_line", not opposing)
    s.check("both_trains_arrived", all(t.finished for t in engine.trains.values()))
    return s.result()


def run_infrastructure(engine: RailGuardEngine) -> dict[str, Any]:
    setup_infrastructure(engine)
    s = Script(engine, "infrastructure_protection", "Infrastructure protection: degraded bridge section re-ranks")
    base = engine.recommend()
    s.log("recommend_healthy", base["ranking"]["candidates"][0]["summary"])
    s.check("healthy_uses_fast_bridge", _uses(base, "S02"))
    engine.update_section("S02", condition=0.3)
    s.log("degrade", "S02 TrackSense condition 0.90 -> 0.30")
    balanced = engine.recommend()
    s.log("recommend_degraded_balanced", balanced["ranking"]["candidates"][0]["summary"])
    s.check("balanced_avoids_degraded_section", not _uses(balanced, "S02"))
    engine.set_weights("FASTEST")
    fastest = engine.recommend()
    s.log("recommend_degraded_fastest", fastest["ranking"]["candidates"][0]["summary"])
    s.check("fastest_preset_keeps_bridge", _uses(fastest, "S02"))
    stress_fast = fastest["ranking"]["candidates"][0]["raw"]["infra"]
    stress_bal = balanced["ranking"]["candidates"][0]["raw"]["infra"]
    delay_fast = fastest["ranking"]["candidates"][0]["raw"]["delay"]
    delay_bal = balanced["ranking"]["candidates"][0]["raw"]["delay"]
    s.log(
        "trade_off",
        {
            "stress_reduction_pct": round(100 * (1 - stress_bal / stress_fast), 1),
            "delay_cost_min": round(delay_bal - delay_fast, 2),
        },
    )
    s.check("stress_reduced", stress_bal < stress_fast)
    engine.set_weights("BALANCED")
    return s.result()


def run_threat(engine: RailGuardEngine) -> dict[str, Any]:
    setup_threat(engine)
    s = Script(engine, "threat_awareness", "Threat awareness: obstacle report ahead of Train A")
    rec = engine.recommend()
    engine.approve(rec["snapshot_id"], rec["ranking"]["candidates"][0]["candidate_id"], "controller-demo")
    engine.tick(6 * 60)
    engine.inject_fault("obstacle", section_id="S05")
    s.log("inject", "TwinTrack obstacle sensor event on S05")
    s.check("obstacle_threat_open", "OBSTACLE" in _types(engine))
    cab = build_advisory(engine, "A")
    s.log("cab_A", {"status": cab["status"], "headline": cab["headline"]})
    s.check("cab_requests_controller", cab["status"] == "HOLD-FOR-CONTROLLER")
    blocked = engine.recommend()
    s.log("recommend_before_ack", {"state": blocked["state"], "reason": blocked["reason"]})
    s.check("critical_threat_blocks_approval", not blocked["approvable"])
    for threat in engine.threats.active():
        if threat.type == "OBSTACLE":
            engine.acknowledge(threat.id, "controller-demo")
    rerouted = engine.recommend()
    s.log("recommend_after_ack", rerouted["ranking"]["candidates"][0]["summary"])
    s.check("reroute_avoids_obstacle", not _uses(rerouted, "S05"))
    engine.approve(rerouted["snapshot_id"], rerouted["ranking"]["candidates"][0]["candidate_id"], "controller-demo")
    s.run_until_arrival()
    s.check("both_trains_arrived", all(t.finished for t in engine.trains.values()))
    return s.result()


def run_stale(engine: RailGuardEngine) -> dict[str, Any]:
    setup_stale(engine)
    s = Script(engine, "stale_position", "Stale position: Train A's feed freezes; the system fails closed")
    rec = engine.recommend()
    engine.approve(rec["snapshot_id"], rec["ranking"]["candidates"][0]["candidate_id"], "controller-demo")
    engine.tick(10 * 60)
    engine.inject_fault("freeze_feed", train_id="A")
    engine.tick(45)
    s.log("freeze", "Train A position feed frozen for 45 s")
    s.check("stale_threat", "STALE_POSITION" in _types(engine))
    cab_a, cab_b = build_advisory(engine, "A"), build_advisory(engine, "B")
    s.log("cabs", {"A": cab_a["status"], "B_nearby_confidence": cab_b["nearby_trains"][0]["confidence"]})
    s.check("cab_a_data_unavailable", cab_a["status"] == "DATA UNAVAILABLE")
    s.check("cab_a_no_speed_advice", cab_a["advisory_speed_band_kmph"] is None)
    s.check("nearby_awareness_low_confidence", cab_b["nearby_trains"][0]["confidence"] == "LOW")
    held = engine.recommend()
    s.log("recommend", {"state": held["state"], "reason": held["reason"]})
    s.check("recommendation_fails_closed", held["state"] == "HOLD" and not held["approvable"])
    try:
        engine.approve(held["snapshot_id"], "C1", "controller-demo")
        refused = False
    except ValueError:
        refused = True
    s.check("approval_refused", refused)
    engine.inject_fault("unfreeze_feed", train_id="A")
    engine.tick(10)
    recovered = engine.recommend()
    s.log("recover", recovered["state"])
    s.check("recovers_when_fresh", recovered["state"] == "REVIEWABLE")
    return s.result()


def run_audit_replay(engine: RailGuardEngine) -> dict[str, Any]:
    run_delay_conflict(engine)
    s = Script(engine, "audit_replay", "Audit replay: every decision reconstructs exactly")
    results = [engine.replay(sid) for sid in sorted(engine.audit.snapshots)]
    s.log("replay", [{k: r[k] for k in ("snapshot_id", "integrity_ok", "replay_matches")} for r in results])
    s.check("all_snapshots_intact", all(r["integrity_ok"] for r in results))
    s.check("all_replays_match", all(r["replay_matches"] for r in results))
    s.check("audit_chain_intact", engine.audit.verify_chain())
    first = sorted(engine.audit.snapshots)[0]
    tampered = copy.deepcopy(engine.audit.snapshots[first])
    tampered["inputs"]["weights"]["delay"] = 9.0
    original = engine.audit.snapshots[first]
    engine.audit.snapshots[first] = tampered
    s.check("tampering_detected", not engine.audit.verify_snapshot(first))
    engine.audit.snapshots[first] = original
    approvals = [e for e in engine.audit.events if e["type"] == "PLAN_APPROVED_FOR_DEMO"]
    s.log("approvals", [{"by": e["actor"], "snapshot": e["details"]["snapshot_id"]} for e in approvals])
    s.check(
        "approval_names_controller_and_snapshot", all(e["actor"] and e["details"]["snapshot_id"] for e in approvals)
    )
    return s.result()


SCENARIOS: dict[str, dict[str, Any]] = {
    "normal": {"title": "Normal operation", "setup": setup_normal, "run": run_normal},
    "delay_conflict": {"title": "Delay conflict", "setup": setup_delay_conflict, "run": run_delay_conflict},
    "infrastructure_protection": {
        "title": "Infrastructure protection",
        "setup": setup_infrastructure,
        "run": run_infrastructure,
    },
    "threat_awareness": {"title": "Threat awareness", "setup": setup_threat, "run": run_threat},
    "stale_position": {"title": "Stale position evidence", "setup": setup_stale, "run": run_stale},
    "audit_replay": {"title": "Audit replay", "setup": setup_delay_conflict, "run": run_audit_replay},
}


def run_all() -> dict[str, dict[str, Any]]:
    results = {}
    for name, spec in SCENARIOS.items():
        runner: Callable[[RailGuardEngine], dict[str, Any]] = spec["run"]
        results[name] = runner(RailGuardEngine())
    return results
