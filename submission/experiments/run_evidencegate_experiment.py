from __future__ import annotations

import csv
import hashlib
import json
import platform
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

if __package__:
    from .output_paths import parse_output_directory
else:
    from output_paths import parse_output_directory

from app.core.config import settings
from app.models.provenance import ProvenanceRecord, RouteDecisionSnapshot
from app.services.evidence_gate import REQUIRED_DECISION_ROLES, assess_decision_evidence
from app.services.provenance import SOURCE_IDS, seal_decision_evidence, stable_checksum


TRIALS_PER_SCENARIO = 200
EXPERIMENT_SEED = 20260831
EXPERIMENT_DIR = Path(__file__).resolve().parent
OUTPUT_FILES = ("evidencegate_experimental_results.csv", "evidencegate_experimental_summary.json")


def stable_uuid(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"evidencegate-insef:{EXPERIMENT_SEED}:{label}")


def build_snapshot(scenario: str, trial: int, captured_at: datetime) -> RouteDecisionSnapshot:
    return RouteDecisionSnapshot(
        id=stable_uuid(f"{scenario}:{trial}:snapshot"),
        route_id=stable_uuid(f"{scenario}:{trial}:route"),
        user_id="experiment-operator",
        request_id=f"experiment-{scenario}-{trial:03d}",
        decision_engine_version="6.0.0",
        routing_algorithm_version="DIJKSTRA_V1",
        scoring_version="RRI_V1",
        clearance_engine_version="CLEARANCE_V1",
        source_code="ORIGIN",
        destination_code="DEST",
        cargo_request={"height": 4.0, "width": 3.0, "weight": 50.0},
        route_segment_ids=["experimental-segment"],
        clearance_state="APPROVED",
        reliability_score=80,
        estimated_hours=12,
        score_breakdown={"weather": 80, "port": 80, "congestion": 80, "historical": 80},
        applied_weights={"weather": 0.4, "port": 0.3, "congestion": 0.15, "historical": 0.15},
        excluded_factors=[],
        environmental_alerts=[],
        traceability_summary={"experiment": True},
        final_response_summary={"experiment": True},
        created_at=captured_at,
    )


def build_record(
    role: str,
    snapshot: RouteDecisionSnapshot,
    captured_at: datetime,
) -> ProvenanceRecord:
    value = {"role": role, "measured_value": 80}
    source_id = SOURCE_IDS["open_meteo"] if role == "WEATHER" else None
    source_type = "LIVE_PROVIDER" if role == "WEATHER" else "PUBLIC_OPEN_DATA"
    return ProvenanceRecord(
        id=stable_uuid(f"{snapshot.request_id}:{role}"),
        user_id=snapshot.user_id,
        route_id=snapshot.route_id,
        decision_snapshot_id=snapshot.id,
        source_id=source_id,
        entity_type=f"{role}_EXPERIMENT_EVIDENCE",
        entity_key=f"{snapshot.request_id}:{role.lower()}",
        decision_input_role=role,
        canonical_source_type=source_type,
        raw_source_state="LIVE",
        observed_at=captured_at if role == "WEATHER" else None,
        fetched_at=captured_at,
        freshness_state="FRESH" if role == "WEATHER" else "NOT_APPLICABLE",
        cache_hit=False,
        used_in_decision=True,
        availability_state="AVAILABLE",
        checksum=stable_checksum(value),
        value_summary=value,
        metadata_json={"experiment": True, "decision_use": "included"},
    )


def run_trial(scenario: str, trial: int, captured_at: datetime) -> dict[str, object]:
    snapshot = build_snapshot(scenario, trial, captured_at)
    records = [build_record(role, snapshot, captured_at) for role in REQUIRED_DECISION_ROLES]
    expected_state = "READY"

    if scenario == "missing_weather_role":
        records = [record for record in records if record.decision_input_role != "WEATHER"]
        expected_state = "HOLD"
    elif scenario == "stale_weather":
        weather = next(record for record in records if record.decision_input_role == "WEATHER")
        weather.observed_at = captured_at - timedelta(hours=2)
        expected_state = "HOLD"
    elif scenario == "future_weather":
        weather = next(record for record in records if record.decision_input_role == "WEATHER")
        weather.observed_at = captured_at + timedelta(hours=1)
        expected_state = "HOLD"
    elif scenario == "hard_blocked":
        snapshot.clearance_state = "HARD_BLOCKED"
        expected_state = "HARD_BLOCKED"
    elif scenario == "seeded_clearance":
        clearance = next(
            record for record in records if record.decision_input_role == "CLEARANCE_DECISION"
        )
        clearance.canonical_source_type = "SEEDED_BASELINE"
        expected_state = "HOLD"

    seal_decision_evidence(snapshot, records, [])

    if scenario == "snapshot_timestamp_tamper":
        snapshot.created_at = snapshot.created_at + timedelta(minutes=1)
        expected_state = "HOLD"
    elif scenario == "record_source_tamper":
        records[0].canonical_source_type = "SIMULATED"
        expected_state = "HOLD"

    started = time.perf_counter_ns()
    assessment = assess_decision_evidence(snapshot, records, now=captured_at)
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    return {
        "scenario": scenario,
        "trial": trial,
        "expected_state": expected_state,
        "actual_state": assessment.decision_state.value,
        "passed": assessment.decision_state.value == expected_state,
        "reason_codes": "|".join(assessment.reason_codes),
        "elapsed_ms": round(elapsed_ms, 6),
    }


def percentile(values: list[float], percentile_value: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile_value))))
    return ordered[index]


def main() -> int:
    output_dir = parse_output_directory(EXPERIMENT_DIR, "evidencegate", OUTPUT_FILES)
    settings.EVIDENCE_SIGNING_KEY_ID = "insef-experiment-key"
    settings.EVIDENCE_SIGNING_ALGORITHM = "HMAC-SHA256"
    settings.EVIDENCE_SIGNING_KEY = "insef-experiment-only-key-2026-08-31-do-not-deploy"
    settings.EVIDENCE_VERIFICATION_KEYS = {}

    scenarios = [
        "baseline_ready",
        "snapshot_timestamp_tamper",
        "record_source_tamper",
        "missing_weather_role",
        "stale_weather",
        "future_weather",
        "seeded_clearance",
        "hard_blocked",
    ]
    captured_at = datetime.now(timezone.utc)
    rows = [
        run_trial(scenario, trial, captured_at)
        for scenario in scenarios
        for trial in range(1, TRIALS_PER_SCENARIO + 1)
    ]

    csv_path = output_dir / OUTPUT_FILES[0]
    with csv_path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    aggregates: list[dict[str, object]] = []
    for scenario in scenarios:
        scenario_rows = [row for row in rows if row["scenario"] == scenario]
        latencies = [float(row["elapsed_ms"]) for row in scenario_rows]
        passed = sum(bool(row["passed"]) for row in scenario_rows)
        actual_states: dict[str, int] = {}
        for row in scenario_rows:
            state = str(row["actual_state"])
            actual_states[state] = actual_states.get(state, 0) + 1
        aggregates.append(
            {
                "scenario": scenario,
                "trials": len(scenario_rows),
                "passed": passed,
                "pass_rate_pct": round(passed * 100 / len(scenario_rows), 2),
                "actual_states": actual_states,
                "latency_ms_mean": round(statistics.fmean(latencies), 6),
                "latency_ms_median": round(statistics.median(latencies), 6),
                "latency_ms_p95": round(percentile(latencies, 0.95), 6),
            }
        )

    csv_sha256 = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    summary = {
        "experiment": "EvidenceGate fail-closed integrity validation",
        "executed_at_utc": captured_at.isoformat(),
        "experiment_seed": EXPERIMENT_SEED,
        "software_version": "EvidenceGate 6.0.0",
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "trials_per_scenario": TRIALS_PER_SCENARIO,
        "total_trials": len(rows),
        "total_passed": sum(bool(row["passed"]) for row in rows),
        "overall_pass_rate_pct": round(
            sum(bool(row["passed"]) for row in rows) * 100 / len(rows), 2
        ),
        "csv_sha256": csv_sha256,
        "scenarios": aggregates,
        "limitations": [
            "This experiment validates software decision-gate behavior, not railway physics.",
            "No authenticated railway or maritime provider credential was available during execution.",
            "No claim is made that seeded corridor engineering limits are certified operational data.",
        ],
    }
    summary_path = output_dir / OUTPUT_FILES[1]
    with summary_path.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2)
    print(f"Measured outputs saved to: {output_dir}")
    print(json.dumps(summary, indent=2))
    return 0 if all(bool(row["passed"]) for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
