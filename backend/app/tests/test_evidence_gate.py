from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.provenance import LineageEdge, ProvenanceRecord, RouteDecisionSnapshot
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

TEST_NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


def _snapshot(*, clearance: str = "APPROVED") -> RouteDecisionSnapshot:
    return RouteDecisionSnapshot(
        id=uuid4(),
        route_id=uuid4(),
        user_id="owner-a",
        request_id="request-a",
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
        created_at=TEST_NOW,
    )


def _record(
    role: str | None,
    *,
    source_key: str,
    source_type: str,
    entity_type: str | None = None,
    freshness: str = "NOT_APPLICABLE",
    availability: str = "AVAILABLE",
    checksum: str | None = None,
    observed_at: datetime | None = None,
    valid_until: datetime | None = None,
    metadata: dict | None = None,
    value: dict | None = None,
) -> ProvenanceRecord:
    value = value or {"role": role, "value": 80}
    if observed_at is None and source_type in {
        "LIVE_PROVIDER",
        "CACHED_PROVIDER",
        "OPERATOR_INPUT",
        "IMPORTED_DOCUMENT",
    }:
        observed_at = TEST_NOW
    return ProvenanceRecord(
        id=uuid4(),
        user_id="owner-a",
        route_id=uuid4(),
        decision_snapshot_id=uuid4(),
        source_id=SOURCE_IDS[source_key],
        entity_type=entity_type or f"{role}_EVIDENCE",
        entity_key=(role or entity_type or "evidence").lower(),
        decision_input_role=role,
        canonical_source_type=source_type,
        raw_source_state=source_type,
        observed_at=observed_at,
        fetched_at=TEST_NOW,
        valid_until=valid_until,
        freshness_state=freshness,
        cache_hit=False,
        used_in_decision=True,
        availability_state=availability,
        completeness=1.0,
        checksum=checksum or stable_checksum(value),
        value_summary=value,
        request_id="request-a",
        metadata_json=metadata or {},
    )


def _ready_records() -> list[ProvenanceRecord]:
    direct = [
        _record(
            "CLEARANCE_DECISION",
            source_key="clearpath_derived",
            source_type="DERIVED",
            entity_type="CLEARANCE_RESULT",
            value={"status": "APPROVED", "blocking_segment_id": None},
        ),
        _record(
            "WEATHER",
            source_key="clearpath_derived",
            source_type="DERIVED",
            entity_type="WEATHER_SCORE",
            value={"score": 80, "provider_unavailable": False, "weight": 0.4},
        ),
        _record(
            "PORT_ALIGNMENT",
            source_key="maritime_feed",
            source_type="LIVE_PROVIDER",
            entity_type="PORT_ALIGNMENT_SCORE",
            freshness="FRESH",
            observed_at=TEST_NOW,
            valid_until=TEST_NOW + timedelta(hours=2),
            value={
                "score": 80,
                "available": True,
                "aligned": True,
                "port_id": "INNSA",
                "vessel_id": "IMO1234567",
                "evaluated_at": TEST_NOW.isoformat(),
                "train_arrival_hours": 12,
                "loading_window": {
                    "start": (TEST_NOW + timedelta(hours=1)).isoformat(),
                    "end": (TEST_NOW + timedelta(hours=2)).isoformat(),
                },
            },
        ),
        _record(
            "CONGESTION",
            source_key="clearpath_derived",
            source_type="DERIVED",
            entity_type="CONGESTION_SCORE",
            value={"score": 80, "static_score": 80, "live_weight": 0.0},
        ),
        _record(
            "HISTORICAL_DELAY",
            source_key="clearpath_derived",
            source_type="DERIVED",
            entity_type="HISTORICAL_DELAY_SCORE",
            value={"score": 80, "segment_delay_hours": [1.0], "weight": 0.15},
        ),
    ]
    parents = [
        _record(
            None,
            source_key="operator_input",
            source_type="OPERATOR_INPUT",
            entity_type="CARGO_DECLARATION",
            value={"height": 4.0, "width": 3.0, "weight": 50.0},
        ),
        _record(
            None,
            source_key="imported_engineering",
            source_type="IMPORTED_DOCUMENT",
            entity_type="ENGINEERING_LIMITS",
            metadata={
                "verified": True,
                "signature_verified": True,
                "issuer_authentication": "DETACHED_SIGNATURE",
            },
            value={
                "certification": "VERIFIED",
                "segments": [
                    {
                        "id": "segment-a",
                        "source_code": "NGP",
                        "destination_code": "JNPT",
                        "max_height": 5.0,
                        "max_width": 4.0,
                        "max_weight": 100.0,
                        "source_reference": "authority.example/notice/1",
                        "certified_by": "Test authority",
                        "certified_at": TEST_NOW.isoformat(),
                        "verified": True,
                        "declared_checksum": "a" * 64,
                        "computed_checksum": "a" * 64,
                    }
                ],
            },
        ),
        _record(
            None,
            source_key="open_meteo",
            source_type="LIVE_PROVIDER",
            entity_type="WEATHER_OBSERVATION",
            freshness="FRESH",
            observed_at=TEST_NOW,
            value={
                "weather": [{"id": 800}],
                "wind": {"speed": 2.0},
                "main": {"visibility": 10_000},
            },
        ),
        _record(
            None,
            source_key="imported_engineering",
            source_type="IMPORTED_DOCUMENT",
            entity_type="CONGESTION_BASELINE",
            value={"score": 80, "segment_factors": [1.0]},
        ),
    ]
    return direct + parents


def _ready_edges(records: list[ProvenanceRecord]) -> list[LineageEdge]:
    by_type = {record.entity_type: record for record in records}
    by_role = {
        record.decision_input_role: record
        for record in records
        if record.decision_input_role is not None
    }
    edges = [
        LineageEdge(
            parent_record_id=by_type["CARGO_DECLARATION"].id,
            child_record_id=by_role["CLEARANCE_DECISION"].id,
            relationship="INPUT_TO",
        ),
        LineageEdge(
            parent_record_id=by_type["ENGINEERING_LIMITS"].id,
            child_record_id=by_role["CLEARANCE_DECISION"].id,
            relationship="VALIDATES",
        ),
        LineageEdge(
            parent_record_id=by_type["WEATHER_OBSERVATION"].id,
            child_record_id=by_role["WEATHER"].id,
            relationship="DERIVED_FROM",
        ),
        LineageEdge(
            parent_record_id=by_type["CONGESTION_BASELINE"].id,
            child_record_id=by_role["CONGESTION"].id,
            relationship="DERIVED_FROM",
        ),
    ]
    if "HISTORICAL_DELAY" in by_role:
        edges.append(
            LineageEdge(
                parent_record_id=by_type["ENGINEERING_LIMITS"].id,
                child_record_id=by_role["HISTORICAL_DELAY"].id,
                relationship="DERIVED_FROM",
            )
        )
    return edges


def _bind_context(snapshot: RouteDecisionSnapshot, records: list[ProvenanceRecord]) -> None:
    for record in records:
        record.user_id = snapshot.user_id
        record.route_id = snapshot.route_id
        record.decision_snapshot_id = snapshot.id
        record.request_id = snapshot.request_id


def _sealed_assessment(
    snapshot: RouteDecisionSnapshot,
    records: list[ProvenanceRecord],
):
    _bind_context(snapshot, records)
    edges = _ready_edges(records) if len(records) > len(REQUIRED_DECISION_ROLES) else []
    seal_decision_evidence(snapshot, records, edges)
    return assess_decision_evidence(snapshot, records, edges, now=TEST_NOW)


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
    records = [
        record for record in _ready_records() if record.decision_input_role != "HISTORICAL_DELAY"
    ]
    result = _sealed_assessment(_snapshot(), records)
    assert result.decision_state is DecisionState.HOLD
    assert "REQUIRED_ROLE_MISSING" in result.reason_codes


def test_seeded_clearance_cannot_be_ready() -> None:
    records = _ready_records()
    records[0] = _record(
        "CLEARANCE_DECISION",
        source_key="demo_engineering",
        source_type="SEEDED_BASELINE",
    )
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


def test_signed_wrong_context_bundle_cannot_be_ready() -> None:
    snapshot = _snapshot()
    records = _ready_records()
    _bind_context(snapshot, records)
    records[0].route_id = uuid4()
    edges = _ready_edges(records)
    seal_decision_evidence(snapshot, records, edges)

    result = assess_decision_evidence(snapshot, records, edges, now=TEST_NOW)

    assert result.root_integrity_valid is True
    assert result.decision_state is DecisionState.HOLD
    assert "EVIDENCE_CONTEXT_MISMATCH" in result.reason_codes


def test_signed_source_less_bundle_cannot_be_ready() -> None:
    snapshot = _snapshot()
    records = _ready_records()
    _bind_context(snapshot, records)
    for record in records:
        record.source_id = None
    edges = _ready_edges(records)
    seal_decision_evidence(snapshot, records, edges)

    result = assess_decision_evidence(snapshot, records, edges, now=TEST_NOW)

    assert result.root_integrity_valid is True
    assert result.decision_state is DecisionState.HOLD
    assert "EVIDENCE_SOURCE_ID_MISSING" in result.reason_codes


def test_signed_empty_payload_cannot_be_ready() -> None:
    snapshot = _snapshot()
    records = _ready_records()
    _bind_context(snapshot, records)
    records[0].value_summary = {}
    records[0].checksum = stable_checksum({})
    edges = _ready_edges(records)
    seal_decision_evidence(snapshot, records, edges)

    result = assess_decision_evidence(snapshot, records, edges, now=TEST_NOW)

    assert result.root_integrity_valid is True
    assert result.decision_state is DecisionState.HOLD
    assert "EVIDENCE_PAYLOAD_EMPTY" in result.reason_codes


def test_signed_direct_derivations_without_lineage_cannot_be_ready() -> None:
    snapshot = _snapshot()
    records = _ready_records()[: len(REQUIRED_DECISION_ROLES)]
    _bind_context(snapshot, records)
    seal_decision_evidence(snapshot, records, [])

    result = assess_decision_evidence(snapshot, records, [], now=TEST_NOW)

    assert result.root_integrity_valid is True
    assert result.decision_state is DecisionState.HOLD
    assert "EVIDENCE_LINEAGE_INCOMPLETE" in result.reason_codes


def test_signed_operator_assertions_cannot_impersonate_derived_roles() -> None:
    snapshot = _snapshot()
    records = _ready_records()
    _bind_context(snapshot, records)
    for record in records[: len(REQUIRED_DECISION_ROLES)]:
        record.source_id = SOURCE_IDS["operator_input"]
        record.canonical_source_type = "OPERATOR_INPUT"
    edges = _ready_edges(records)
    seal_decision_evidence(snapshot, records, edges)

    result = assess_decision_evidence(snapshot, records, edges, now=TEST_NOW)

    assert result.root_integrity_valid is True
    assert result.decision_state is DecisionState.HOLD
    assert "EVIDENCE_ROLE_SOURCE_NOT_ALLOWED" in result.reason_codes


def test_signed_future_provider_timestamp_cannot_be_ready() -> None:
    snapshot = _snapshot()
    records = _ready_records()
    _bind_context(snapshot, records)
    weather = next(record for record in records if record.entity_type == "WEATHER_OBSERVATION")
    weather.observed_at = TEST_NOW + timedelta(hours=1)
    weather.fetched_at = TEST_NOW + timedelta(hours=1)
    edges = _ready_edges(records)
    seal_decision_evidence(snapshot, records, edges)

    result = assess_decision_evidence(snapshot, records, edges, now=TEST_NOW)

    assert result.root_integrity_valid is True
    assert result.decision_state is DecisionState.HOLD
    assert "EVIDENCE_TIMESTAMP_IN_FUTURE" in result.reason_codes


@pytest.mark.parametrize("role", REQUIRED_DECISION_ROLES)
def test_signed_nonempty_malformed_role_payload_cannot_be_ready(role: str) -> None:
    snapshot = _snapshot()
    records = _ready_records()
    _bind_context(snapshot, records)
    direct = next(record for record in records if record.decision_input_role == role)
    direct.value_summary = {"garbage": 1}
    direct.checksum = stable_checksum(direct.value_summary)
    edges = _ready_edges(records)
    seal_decision_evidence(snapshot, records, edges)

    result = assess_decision_evidence(snapshot, records, edges, now=TEST_NOW)

    assert result.root_integrity_valid is True
    assert result.decision_state is DecisionState.HOLD
    assert "EVIDENCE_PAYLOAD_SCHEMA_INVALID" in result.reason_codes


def test_signed_expired_imports_cannot_be_ready() -> None:
    snapshot = _snapshot()
    records = _ready_records()
    _bind_context(snapshot, records)
    old = datetime(2020, 1, 1, tzinfo=timezone.utc)
    for record in records:
        if record.canonical_source_type == "IMPORTED_DOCUMENT":
            record.observed_at = old
            record.fetched_at = old
    edges = _ready_edges(records)
    seal_decision_evidence(snapshot, records, edges)

    result = assess_decision_evidence(snapshot, records, edges, now=TEST_NOW)

    assert result.root_integrity_valid is True
    assert result.decision_state is DecisionState.HOLD
    assert "EVIDENCE_STALE" in result.reason_codes


@pytest.mark.parametrize(
    "entity_type",
    ["CARGO_DECLARATION", "ENGINEERING_LIMITS", "WEATHER_OBSERVATION", "CONGESTION_BASELINE"],
)
def test_signed_excluded_required_ancestor_cannot_authorize_ready(entity_type: str) -> None:
    snapshot = _snapshot()
    records = _ready_records()
    _bind_context(snapshot, records)
    ancestor = next(record for record in records if record.entity_type == entity_type)
    ancestor.used_in_decision = False
    edges = _ready_edges(records)
    seal_decision_evidence(snapshot, records, edges)

    result = assess_decision_evidence(snapshot, records, edges, now=TEST_NOW)

    assert result.root_integrity_valid is True
    assert result.decision_state is DecisionState.HOLD
    assert "REQUIRED_INPUT_EXCLUDED" in result.reason_codes


def test_signed_clearance_record_cannot_contradict_snapshot() -> None:
    snapshot = _snapshot(clearance="APPROVED")
    records = _ready_records()
    _bind_context(snapshot, records)
    clearance = next(
        record for record in records if record.decision_input_role == "CLEARANCE_DECISION"
    )
    clearance.value_summary = {"status": "HARD_BLOCKED", "blocking_segment_id": "segment-a"}
    clearance.checksum = stable_checksum(clearance.value_summary)
    edges = _ready_edges(records)
    seal_decision_evidence(snapshot, records, edges)

    result = assess_decision_evidence(snapshot, records, edges, now=TEST_NOW)

    assert result.root_integrity_valid is True
    assert result.decision_state is DecisionState.HOLD
    assert "EVIDENCE_SNAPSHOT_CONFLICT" in result.reason_codes


def test_signed_derived_score_cannot_contradict_snapshot() -> None:
    snapshot = _snapshot()
    records = _ready_records()
    _bind_context(snapshot, records)
    weather = next(record for record in records if record.decision_input_role == "WEATHER")
    weather.value_summary["score"] = 12
    weather.checksum = stable_checksum(weather.value_summary)
    edges = _ready_edges(records)
    seal_decision_evidence(snapshot, records, edges)

    result = assess_decision_evidence(snapshot, records, edges, now=TEST_NOW)

    assert result.root_integrity_valid is True
    assert result.decision_state is DecisionState.HOLD
    assert "EVIDENCE_SNAPSHOT_CONFLICT" in result.reason_codes


def test_signed_broken_lineage_edge_cannot_be_ready() -> None:
    snapshot = _snapshot()
    records = _ready_records()
    _bind_context(snapshot, records)
    edges = _ready_edges(records)
    edges.append(
        LineageEdge(
            parent_record_id=uuid4(),
            child_record_id=next(
                record.id for record in records if record.decision_input_role == "WEATHER"
            ),
            relationship="DERIVED_FROM",
        )
    )
    seal_decision_evidence(snapshot, records, edges)

    result = assess_decision_evidence(snapshot, records, edges, now=TEST_NOW)

    assert result.root_integrity_valid is True
    assert result.decision_state is DecisionState.HOLD
    assert "EVIDENCE_LINEAGE_INVALID" in result.reason_codes


def test_operator_assertion_cannot_be_authoritative_port_evidence() -> None:
    snapshot = _snapshot()
    records = _ready_records()
    _bind_context(snapshot, records)
    port = next(record for record in records if record.decision_input_role == "PORT_ALIGNMENT")
    port.source_id = SOURCE_IDS["operator_input"]
    port.canonical_source_type = "OPERATOR_INPUT"
    window = port.value_summary["loading_window"]
    window["manifest_reference"] = "abc"
    window["manifest_sha256"] = "0" * 64
    port.checksum = stable_checksum(port.value_summary)
    edges = _ready_edges(records)
    seal_decision_evidence(snapshot, records, edges)

    result = assess_decision_evidence(snapshot, records, edges, now=TEST_NOW)

    assert result.root_integrity_valid is True
    assert result.decision_state is DecisionState.HOLD
    assert "EVIDENCE_ROLE_SOURCE_NOT_ALLOWED" in result.reason_codes


def test_disabled_source_catalog_entry_cannot_authorize_ready() -> None:
    snapshot = _snapshot()
    records = _ready_records()
    _bind_context(snapshot, records)
    edges = _ready_edges(records)
    seal_decision_evidence(snapshot, records, edges)
    sources = {
        record.source_id: SimpleNamespace(
            id=record.source_id,
            key=next(key for key, value in SOURCE_IDS.items() if value == record.source_id),
            enabled=record.source_id != SOURCE_IDS["open_meteo"],
        )
        for record in records
        if record.source_id is not None
    }

    result = assess_decision_evidence(
        snapshot,
        records,
        edges,
        now=TEST_NOW,
        sources_by_id=sources,
    )

    assert result.root_integrity_valid is True
    assert result.decision_state is DecisionState.HOLD
    assert "EVIDENCE_SOURCE_DISABLED" in result.reason_codes


@pytest.mark.parametrize("mutation", ["cargo", "segment"])
def test_signed_semantic_context_replay_cannot_authorize_ready(mutation: str) -> None:
    snapshot = _snapshot()
    records = _ready_records()
    _bind_context(snapshot, records)
    if mutation == "cargo":
        record = next(item for item in records if item.entity_type == "CARGO_DECLARATION")
        record.value_summary["weight"] = 999
    else:
        record = next(item for item in records if item.entity_type == "ENGINEERING_LIMITS")
        record.value_summary["segments"][0]["id"] = "different-segment"
    record.checksum = stable_checksum(record.value_summary)
    edges = _ready_edges(records)
    seal_decision_evidence(snapshot, records, edges)

    result = assess_decision_evidence(snapshot, records, edges, now=TEST_NOW)

    assert result.root_integrity_valid is True
    assert result.decision_state is DecisionState.HOLD
    assert "EVIDENCE_SEMANTIC_CONTEXT_MISMATCH" in result.reason_codes


@pytest.mark.parametrize("clearance", ["", "UNKNOWN", "HOLD", "UNAVAILABLE", "PENDING"])
def test_clearance_must_be_explicitly_approved(clearance: str) -> None:
    result = _sealed_assessment(_snapshot(clearance=clearance), _ready_records())
    assert result.decision_state is DecisionState.HOLD
    assert "CLEARANCE_NOT_APPROVED" in result.reason_codes


@pytest.mark.parametrize("freshness", ["FREHS", "VALID", " "])
def test_unrecognized_freshness_cannot_be_ready(freshness: str) -> None:
    records = _ready_records()
    historical = next(
        record for record in records if record.decision_input_role == "HISTORICAL_DELAY"
    )
    historical.source_id = uuid4()
    historical.freshness_state = freshness
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
    snapshot = _snapshot()
    records = _ready_records()
    weather = next(record for record in records if record.entity_type == "WEATHER_OBSERVATION")
    weather.observed_at = captured_at
    weather.fetched_at = captured_at
    weather.freshness_state = "FRESH"
    _bind_context(snapshot, records)
    edges = _ready_edges(records)
    seal_decision_evidence(snapshot, records, edges)

    result = assess_decision_evidence(
        snapshot,
        records,
        edges,
        now=captured_at + timedelta(hours=2),
    )

    assert result.decision_state is DecisionState.HOLD
    assert "EVIDENCE_STALE" in result.reason_codes


def test_trust_field_tampering_breaks_signed_evidence_root() -> None:
    records = _ready_records()
    snapshot = _snapshot()
    _bind_context(snapshot, records)
    edges = _ready_edges(records)
    seal_decision_evidence(snapshot, records, edges)
    records[0].canonical_source_type = "IMPORTED_DOCUMENT"

    result = assess_decision_evidence(snapshot, records, edges, now=TEST_NOW)

    assert result.decision_state is DecisionState.HOLD
    assert "RECORD_ENVELOPE_INVALID" in result.reason_codes
    assert "EVIDENCE_ROOT_INVALID" in result.reason_codes


def test_snapshot_timestamp_tampering_breaks_signed_evidence_root() -> None:
    records = _ready_records()
    snapshot = _snapshot()
    _bind_context(snapshot, records)
    edges = _ready_edges(records)
    seal_decision_evidence(snapshot, records, edges)
    snapshot.created_at = snapshot.created_at + timedelta(minutes=1)

    result = assess_decision_evidence(snapshot, records, edges, now=TEST_NOW)

    assert result.decision_state is DecisionState.HOLD
    assert "EVIDENCE_ROOT_INVALID" in result.reason_codes


def test_manifest_checksum_is_reproducible() -> None:
    snapshot = _snapshot()
    records = _ready_records()
    _bind_context(snapshot, records)
    edges = _ready_edges(records)
    seal_decision_evidence(snapshot, records, edges)
    assessment = assess_decision_evidence(snapshot, records, edges, now=TEST_NOW)
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
    assert manifest["evidence_gate_policy_version"] == "EVIDENCE_GATE_V2"
    assert manifest["required_roles"] == list(REQUIRED_DECISION_ROLES)
    assert manifest["evidence_signing_key_id"] == snapshot.evidence_root_key_id
    assert manifest["signature_algorithm"] == snapshot.evidence_root_algorithm
    assert len(checksum) == 64
