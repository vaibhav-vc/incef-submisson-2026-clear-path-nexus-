"""Measure the SEVA validation metrics on the tabletop twin.

    python -m india_rail.railguard.metrics [--out seva2026/evidence/metrics/railguard_metrics.json]

Everything here is a controlled software experiment on the demo network:
synthetic delay grids, injected faults and the six scripted scenarios. None of
it is a field measurement on Indian Railways.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from india_rail.railguard.engine import RailGuardEngine
from india_rail.railguard.scenarios import SCENARIOS

HEADWAY = 3.0
# Analytic ground truth for the demo network, from section lengths and speed
# limits only (not from the planner): Train A at 75 km/h reaches single-line
# S06 after S01 10 km + S02 14 km + S05 9 km = 26.4 min and occupies it for
# 6 km = 4.8 min. Train B (80 km/h line limit) occupies S06 for 4.5 min.
A_S06_ENTER, A_S06_RUN, B_S06_RUN = 26.4, 4.8, 4.5


def truth_conflict(a_delay: float, b_delay: float) -> bool:
    a_enter = 0 + a_delay + A_S06_ENTER
    a_exit = a_enter + A_S06_RUN
    b_enter = 38 + b_delay
    b_exit = b_enter + B_S06_RUN
    gap = max(b_enter - a_exit, a_enter - b_exit)
    return gap < HEADWAY


def grid(step: float) -> list[tuple[float, float]]:
    a_values = [round(i * step, 2) for i in range(int(20 / step) + 1)]
    b_values = [round(i * step, 2) for i in range(int(10 / step) + 1)]
    return [(a, b) for a in a_values for b in b_values]


def conflict_detection(step: float) -> dict[str, Any]:
    tp = fp = fn = tn = 0
    for a_delay, b_delay in grid(step):
        engine = RailGuardEngine()
        engine.trains["A"].departure_delay_min = a_delay
        engine.trains["B"].departure_delay_min = b_delay
        engine.refresh()
        detected = any(t.type == "CONVERGING_PATH" and t.severity == "WARNING" for t in engine.threats.active())
        truth = truth_conflict(a_delay, b_delay)
        tp += detected and truth
        fp += detected and not truth
        fn += truth and not detected
        tn += not truth and not detected
    return {
        "cases": tp + fp + fn + tn,
        "true_conflicts": tp + fn,
        "recall": round(tp / (tp + fn), 4) if tp + fn else None,
        "precision": round(tp / (tp + fp), 4) if tp + fp else None,
        "missed_conflicts": fn,
        "false_alarms": fp,
        "ground_truth": "analytic single-line occupation windows on S06 from section lengths and speed limits",
    }


def executed_plans(step: float, degraded: bool) -> dict[str, Any]:
    """Approve the top recommendation for each delay case, run the twin, and audit the outcome."""

    latencies, delay_delta, stress_reduction, overlaps, approvable = [], [], [], 0, 0
    min_gap = float("inf")
    cases = grid(step)
    for a_delay, b_delay in cases:
        engine = RailGuardEngine()
        engine.trains["A"].departure_delay_min = a_delay
        engine.trains["B"].departure_delay_min = b_delay
        if degraded:
            engine.update_section("S02", condition=0.3)
        started = time.perf_counter()
        rec = engine.recommend()
        latencies.append((time.perf_counter() - started) * 1000)
        if not rec["approvable"]:
            continue
        approvable += 1
        top = rec["ranking"]["candidates"][0]
        fastest = next(c for c in rec["ranking"]["candidates"] if "FASTEST" in c["labels"])
        delay_delta.append(top["raw"]["delay"] - fastest["raw"]["delay"])
        if fastest["raw"]["infra"]:
            stress_reduction.append(1 - top["raw"]["infra"] / fastest["raw"]["infra"])
        engine.approve(rec["snapshot_id"], top["candidate_id"], "metrics")
        occupied: dict[str, dict[str, list[float]]] = {}
        while not all(t.finished for t in engine.trains.values()) and engine.t < 150 * 60:
            engine.tick(5)
            on = {tid: t.section_id for tid, t in engine.trains.items() if t.section_id}
            for tid, sid in on.items():
                occupied.setdefault(sid, {}).setdefault(tid, []).append(engine.t / 60)
            if len(on) == 2 and len(set(on.values())) == 1 and engine.net.sections[next(iter(on.values()))].tracks == 1:
                overlaps += 1
        for _sid, by_train in occupied.items():
            if len(by_train) == 2 and engine.net.sections[_sid].tracks == 1:
                (a0, a1), (b0, b1) = ((min(v), max(v)) for v in by_train.values())
                min_gap = min(min_gap, max(b0 - a1, a0 - b1))
    return {
        "cases": len(cases),
        "approvable_recommendations": approvable,
        "executed_single_line_overlaps": overlaps,
        "min_observed_single_line_separation_min": round(min_gap, 2) if min_gap != float("inf") else None,
        "latency_ms": {
            "median": round(statistics.median(latencies), 2),
            "p95": round(sorted(latencies)[int(0.95 * (len(latencies) - 1))], 2),
            "max": round(max(latencies), 2),
        },
        "delay_vs_fastest_min": {
            "mean": round(statistics.mean(delay_delta), 3) if delay_delta else None,
            "max": round(max(delay_delta), 3) if delay_delta else None,
        },
        "infra_stress_reduction_vs_fastest_pct": {
            "mean": round(100 * statistics.mean(stress_reduction), 2) if stress_reduction else None,
            "max": round(100 * max(stress_reduction), 2) if stress_reduction else None,
        },
    }


def false_clear() -> dict[str, Any]:
    """Controlled fault cases where the gate must refuse an approvable plan."""

    cases: list[tuple[str, bool]] = []
    for tid in ("A", "B"):
        for minutes in (0, 5, 15):
            engine = RailGuardEngine()
            rec = engine.recommend()
            engine.approve(rec["snapshot_id"], "C1", "metrics")
            engine.tick(minutes * 60 + 5)
            engine.inject_fault("freeze_feed", train_id=tid)
            engine.tick(40)
            cases.append((f"stale_position_{tid}_{minutes}min", engine.recommend()["approvable"]))
            engine = RailGuardEngine()
            engine.inject_fault("sensor_offline", train_id=tid)
            engine.tick(40)
            cases.append((f"sensor_offline_{tid}_{minutes}min", engine.recommend()["approvable"]))
    for sid in sorted(RailGuardEngine().net.sections):
        engine = RailGuardEngine()
        engine.evidence.remove(f"condition:{sid}")
        cases.append((f"missing_condition_{sid}", engine.recommend()["approvable"]))
        engine = RailGuardEngine()
        engine.inject_fault("obstacle", section_id=sid)
        critical_open = any(t.severity == "CRITICAL" for t in engine.threats.active())
        cases.append((f"unacknowledged_obstacle_{sid}", engine.recommend()["approvable"] and critical_open))
        engine = RailGuardEngine()
        engine.evidence.records[f"condition:{sid}"].observed_t = engine.t + 3600  # timestamp from the future
        cases.append((f"future_timestamp_{sid}", engine.recommend()["approvable"]))
    false_clears = [name for name, approvable in cases if approvable]
    return {"fault_cases": len(cases), "false_clear_count": len(false_clears), "false_clears": false_clears}


def scenario_metrics() -> dict[str, Any]:
    passed, completeness, freshness, replays, replay_ok = {}, [], [], 0, 0
    for name, spec in SCENARIOS.items():
        engine = RailGuardEngine()
        result = spec["run"](engine)
        passed[name] = result["passed"]
        for sid, snap in engine.audit.snapshots.items():
            assessment = snap["outputs"]["assessment"]
            completeness.append(assessment["completeness"])
            freshness.append(assessment["fresh_rate"])
            replay = engine.replay(sid)
            replays += 1
            replay_ok += replay["integrity_ok"] and replay["replay_matches"]
    return {
        "scenarios_passed": f"{sum(passed.values())}/{len(passed)}",
        "by_scenario": passed,
        "evidence_completeness_mean": round(statistics.mean(completeness), 4),
        "evidence_fresh_rate_mean": round(statistics.mean(freshness), 4),
        "snapshots_replayed": replays,
        "replay_success_rate": round(replay_ok / replays, 4) if replays else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--step", type=float, default=1.0, help="delay grid step in minutes")
    args = parser.parse_args()
    started = time.perf_counter()
    metrics = {
        "measured_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "platform": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
        "scope": "Controlled software experiments on the TwinTrack demo network; not field measurements.",
        "conflict_detection": conflict_detection(0.5),
        "executed_plans_healthy_network": executed_plans(args.step, degraded=False),
        "executed_plans_degraded_s02": executed_plans(args.step, degraded=True),
        "fail_closed": false_clear(),
        "scenarios": scenario_metrics(),
    }
    metrics["runtime_s"] = round(time.perf_counter() - started, 1)
    text = json.dumps(metrics, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
