from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models.provenance import ProvenanceRecord, RouteDecisionSnapshot
from app.services.evidence_gate import (
    DecisionState,
    EvidenceKitStatus,
    REQUIRED_DECISION_ROLES,
    assess_decision_evidence,
    build_manifest,
)
from app.services.provenance import (
    SOURCE_IDS,
    seal_decision_evidence,
    stable_checksum,
    verify_evidence_root,
)
from app.services.provenance import sign_evidence_root


def _snapshot(*, clearance: str = "APPROVED") -> RouteDecisionSnapshot:
    return RouteDecisionSnapshot(
        id=uuid4(),
        route_id=uuid4(),
        user_id="owner-a",
        decision_engine_version="6.1.0",
        routing_algorithm_version="DIJKSTRA_V1",
        scoring_version="RRI_V1",
        clearance_engine_version="CLEARANCE_V1",
        source_code="NGP",
        destination_code="JNPT",
        cargo_request={"height": 4.0, "width": 3.0, "weight": 50.0},
        route_segment_ids=["segment-a"],
        clearance_state=clearance,
        reliability_score=80,
        estimated_hours=12,
        score_breakdown={"weather": 80, "port": 80, "congestion": 80, "historical": 80},
        applied_weights={"weather": 0.4, "port": 0.3, "congestion": 0.15, "historical": 0.15},
        excluded_factors=[],
        environmental_alerts=[],
        traceability_summary={},
        final_response_summary={},
        created_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
    )


def _record(
    role: str,
    *,
    source_type: str = "PUBLIC_OPEN_DATA",
    freshness: str = "FRESH",
    availability: str = "AVAILABLE",
    checksum: str | None = None,
) -> ProvenanceRecord:
    value = {"role": role, "value": 80}
    return ProvenanceRecord(
        id=uuid4(),
        user_id="owner-a",
        route_id=uuid4(),
        decision_snapshot_id=uuid4(),
        entity_type=f"{role}_EVIDENCE",
        entity_key=role.lower(),
        decision_input_role=role,
        canonical_source_type=source_type,
        raw_source_state=source_type,
        fetched_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
        freshness_state=freshness,
        cache_hit=False,
        used_in_decision=True,
        availability_state=availability,
        checksum=checksum or stable_checksum(value),
        value_summary=value,
        metadata_json={},
    )


def _ready_records() -> list[ProvenanceRecord]:
    return [_record(role) for role in REQUIRED_DECISION_ROLES]


def _sealed_assessment(
    snapshot: RouteDecisionSnapshot,
    records: list[ProvenanceRecord],
):
    seal_decision_evidence(snapshot, records, [])
    return assess_decision_evidence(snapshot, records)


def test_no_snapshot_is_truthfully_unavailable() -> None:
    result = assess_decision_evidence(None, [])
    assert result.decision_state is DecisionState.UNAVAILABLE
    assert result.kit_status is EvidenceKitStatus.UNAVAILABLE


def test_evidence_sealing_requires_dedicated_key(monkeypatch) -> None:
    from app.services.provenance import settings

    monkeypatch.setattr(settings, "SECRET_KEY", "legacy-session-secret-that-must-not-sign-evidence")
    monkeypatch.setattr(settings, "EVIDENCE_SIGNING_KEY", "")
    with pytest.raises(RuntimeError, match="EVIDENCE_SIGNING_KEY"):
        sign_evidence_root("a" * 64)


def test_sealed_snapshot_persists_signer_metadata_and_survives_rotation(monkeypatch) -> None:
    from app.services.provenance import settings

    old_key = "old-test-evidence-signing-key-0123456789"
    new_key = "new-test-evidence-signing-key-0123456789"
    monkeypatch.setattr(settings, "EVIDENCE_SIGNING_KEY_ID", "old-key")
    monkeypatch.setattr(settings, "EVIDENCE_SIGNING_KEY", old_key)
    snapshot = _snapshot()
    records = _ready_records()
    seal_decision_evidence(snapshot, records, [])

    assert snapshot.evidence_root_key_id == "old-key"
    assert snapshot.evidence_root_algorithm == "HMAC-SHA256"

    monkeypatch.setattr(settings, "EVIDENCE_SIGNING_KEY_ID", "new-key")
    monkeypatch.setattr(settings, "EVIDENCE_SIGNING_KEY", new_key)
    monkeypatch.setattr(settings, "EVIDENCE_VERIFICATION_KEYS", {"old-key": old_key})
    assert verify_evidence_root(snapshot, records, [])[0] is True


def test_unknown_or_missing_historical_signer_fails_closed(monkeypatch) -> None:
    from app.services.provenance import settings

    snapshot = _snapshot()
    records = _ready_records()
    seal_decision_evidence(snapshot, records, [])
    snapshot.evidence_root_key_id = "retired-but-not-configured"
    monkeypatch.setattr(settings, "EVIDENCE_VERIFICATION_KEYS", {})
    assert verify_evidence_root(snapshot, records, [])[0] is False

    snapshot.evidence_root_key_id = None
    assert verify_evidence_root(snapshot, records, [])[0] is False


def test_snapshot_model_contains_rotation_metadata_columns() -> None:
    columns = RouteDecisionSnapshot.__table__.columns
    assert "evidence_root_key_id" in columns
    assert "evidence_root_algorithm" in columns


def test_hard_block_has_absolute_precedence() -> None:
    result = _sealed_assessment(_snapshot(clearance="HARD_BLOCKED"), [])
    assert result.decision_state is DecisionState.HARD_BLOCKED
    assert "HARD_CLEARANCE_BLOCK" in result.reason_codes


def test_missing_required_role_fails_closed_to_hold() -> None:
    records = _ready_records()[:-1]
    result = _sealed_assessment(_snapshot(), records)
    assert result.decision_state is DecisionState.HOLD
    assert "REQUIRED_ROLE_MISSING" in result.reason_codes


def test_seeded_clearance_cannot_be_ready() -> None:
    records = _ready_records()
    records[0] = _record("CLEARANCE_DECISION", source_type="SEEDED_BASELINE")
    result = _sealed_assessment(_snapshot(), records)
    assert result.decision_state is DecisionState.HOLD
    assert "CRITICAL_CLEARANCE_SEEDED" in result.reason_codes


def test_checksum_failure_degrades_kit_and_holds_decision() -> None:
    records = _ready_records()
    records[-1].checksum = "0" * 64
    result = _sealed_assessment(_snapshot(), records)
    assert result.decision_state is DecisionState.HOLD
    assert result.kit_status is EvidenceKitStatus.DEGRADED
    assert "CHECKSUM_INVALID" in result.reason_codes


def test_complete_trustworthy_evidence_is_hot_and_ready() -> None:
    result = _sealed_assessment(_snapshot(), _ready_records())
    assert result.decision_state is DecisionState.READY
    assert result.kit_status is EvidenceKitStatus.HOT


@pytest.mark.parametrize("clearance", ["", "UNKNOWN", "HOLD", "UNAVAILABLE", "PENDING"])
def test_clearance_must_be_explicitly_approved(clearance: str) -> None:
    result = _sealed_assessment(_snapshot(clearance=clearance), _ready_records())
    assert result.decision_state is DecisionState.HOLD
    assert "CLEARANCE_NOT_APPROVED" in result.reason_codes


@pytest.mark.parametrize("freshness", ["FREHS", "VALID", " "])
def test_unrecognized_freshness_cannot_be_ready(freshness: str) -> None:
    records = _ready_records()
    records[1].freshness_state = freshness
    result = _sealed_assessment(_snapshot(), records)
    assert result.decision_state is DecisionState.HOLD
    assert "EVIDENCE_FRESHNESS_UNKNOWN" in result.reason_codes


@pytest.mark.parametrize("role", REQUIRED_DECISION_ROLES)
def test_excluded_required_input_cannot_be_ready(role: str) -> None:
    records = _ready_records()
    record = next(item for item in records if item.decision_input_role == role)
    record.used_in_decision = False
    result = _sealed_assessment(_snapshot(), records)
    assert result.decision_state is DecisionState.HOLD
    assert "REQUIRED_INPUT_EXCLUDED" in result.reason_codes
    assert result.role_status[role]["trustworthy"] is False


@pytest.mark.parametrize("source_type", ["", "UNRECOGNIZED", "UNAVAILABLE"])
def test_untrusted_source_category_cannot_be_ready(source_type: str) -> None:
    records = _ready_records()
    records[1].canonical_source_type = source_type
    result = _sealed_assessment(_snapshot(), records)
    assert result.decision_state is DecisionState.HOLD
    assert result.role_status["WEATHER"]["trustworthy"] is False


def test_live_evidence_is_reaged_at_dispatch_time() -> None:
    captured_at = datetime(2026, 8, 28, 10, tzinfo=timezone.utc)
    records = _ready_records()
    weather = next(record for record in records if record.decision_input_role == "WEATHER")
    weather.source_id = SOURCE_IDS["open_meteo"]
    weather.observed_at = captured_at
    weather.fetched_at = captured_at
    weather.freshness_state = "FRESH"
    snapshot = _snapshot()
    seal_decision_evidence(snapshot, records, [])

    result = assess_decision_evidence(
        snapshot,
        records,
        now=captured_at + timedelta(hours=2),
    )

    assert result.decision_state is DecisionState.HOLD
    assert "EVIDENCE_STALE" in result.reason_codes


def test_trust_field_tampering_breaks_signed_evidence_root() -> None:
    records = _ready_records()
    snapshot = _snapshot()
    seal_decision_evidence(snapshot, records, [])
    records[0].canonical_source_type = "IMPORTED_DOCUMENT"

    result = assess_decision_evidence(snapshot, records)

    assert result.decision_state is DecisionState.HOLD
    assert "RECORD_ENVELOPE_INVALID" in result.reason_codes
    assert "EVIDENCE_ROOT_INVALID" in result.reason_codes


def test_snapshot_timestamp_tampering_breaks_signed_evidence_root() -> None:
    records = _ready_records()
    snapshot = _snapshot()
    seal_decision_evidence(snapshot, records, [])
    snapshot.created_at = snapshot.created_at + timedelta(minutes=1)

    result = assess_decision_evidence(snapshot, records)

    assert result.decision_state is DecisionState.HOLD
    assert "EVIDENCE_ROOT_INVALID" in result.reason_codes


def test_manifest_checksum_is_reproducible() -> None:
    snapshot = _snapshot()
    records = _ready_records()
    seal_decision_evidence(snapshot, records, [])
    assessment = assess_decision_evidence(snapshot, records)
    first = build_manifest(
        route_id=snapshot.route_id,
        snapshot=snapshot,
        assessment=assessment,
        records=records,
    )
    second = build_manifest(
        route_id=snapshot.route_id,
        snapshot=snapshot,
        assessment=assessment,
        records=list(reversed(records)),
    )
    assert first == second
    manifest, checksum = first
    assert manifest["evidence_gate_policy_version"] == "EVIDENCE_GATE_V1"
    assert manifest["required_roles"] == list(REQUIRED_DECISION_ROLES)
    assert manifest["evidence_signing_key_id"] == snapshot.evidence_root_key_id
    assert manifest["signature_algorithm"] == snapshot.evidence_root_algorithm
    assert len(checksum) == 64
