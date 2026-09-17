from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provenance import DataSource, LineageEdge, ProvenanceRecord, RouteDecisionSnapshot
from app.services.provenance import (
    CanonicalSourceType,
    SOURCE_IDS,
    calculate_freshness,
    record_integrity_payload,
    stable_checksum,
    verify_evidence_root,
)


class DecisionState(str, Enum):
    """Canonical, fail-safe state exposed by every route decision."""

    HARD_BLOCKED = "HARD_BLOCKED"
    UNAVAILABLE = "UNAVAILABLE"
    HOLD = "HOLD"
    READY = "READY"


class EvidenceKitStatus(str, Enum):
    """Operational availability of a stored evidence kit."""

    HOT = "HOT"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class EvidenceReasonCode(str, Enum):
    HARD_CLEARANCE_BLOCK = "HARD_CLEARANCE_BLOCK"
    CLEARANCE_NOT_APPROVED = "CLEARANCE_NOT_APPROVED"
    NO_STORED_DECISION_EVIDENCE = "NO_STORED_DECISION_EVIDENCE"
    REQUIRED_ROLE_MISSING = "REQUIRED_ROLE_MISSING"
    REQUIRED_INPUT_EXCLUDED = "REQUIRED_INPUT_EXCLUDED"
    EVIDENCE_AGING = "EVIDENCE_AGING"
    EVIDENCE_STALE = "EVIDENCE_STALE"
    EVIDENCE_FRESHNESS_UNKNOWN = "EVIDENCE_FRESHNESS_UNKNOWN"
    EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
    EVIDENCE_DEGRADED = "EVIDENCE_DEGRADED"
    EVIDENCE_AVAILABILITY_UNKNOWN = "EVIDENCE_AVAILABILITY_UNKNOWN"
    EVIDENCE_SOURCE_UNKNOWN = "EVIDENCE_SOURCE_UNKNOWN"
    CRITICAL_CLEARANCE_SIMULATED = "CRITICAL_CLEARANCE_SIMULATED"
    CRITICAL_CLEARANCE_SEEDED = "CRITICAL_CLEARANCE_SEEDED"
    EVIDENCE_SIMULATED = "EVIDENCE_SIMULATED"
    EVIDENCE_SEEDED = "EVIDENCE_SEEDED"
    OPERATOR_EVIDENCE_UNVERIFIED = "OPERATOR_EVIDENCE_UNVERIFIED"
    CHECKSUM_MISSING = "CHECKSUM_MISSING"
    CHECKSUM_INVALID = "CHECKSUM_INVALID"
    RECORD_ENVELOPE_MISSING = "RECORD_ENVELOPE_MISSING"
    RECORD_ENVELOPE_INVALID = "RECORD_ENVELOPE_INVALID"
    EVIDENCE_CONTEXT_MISMATCH = "EVIDENCE_CONTEXT_MISMATCH"
    EVIDENCE_SEMANTIC_CONTEXT_MISMATCH = "EVIDENCE_SEMANTIC_CONTEXT_MISMATCH"
    EVIDENCE_SOURCE_ID_MISSING = "EVIDENCE_SOURCE_ID_MISSING"
    EVIDENCE_SOURCE_ID_UNKNOWN = "EVIDENCE_SOURCE_ID_UNKNOWN"
    EVIDENCE_SOURCE_ID_MISMATCH = "EVIDENCE_SOURCE_ID_MISMATCH"
    EVIDENCE_SOURCE_POLICY_MISSING = "EVIDENCE_SOURCE_POLICY_MISSING"
    EVIDENCE_SOURCE_DISABLED = "EVIDENCE_SOURCE_DISABLED"
    EVIDENCE_ROLE_SOURCE_NOT_ALLOWED = "EVIDENCE_ROLE_SOURCE_NOT_ALLOWED"
    EVIDENCE_LINEAGE_INCOMPLETE = "EVIDENCE_LINEAGE_INCOMPLETE"
    EVIDENCE_LINEAGE_INVALID = "EVIDENCE_LINEAGE_INVALID"
    EVIDENCE_PAYLOAD_EMPTY = "EVIDENCE_PAYLOAD_EMPTY"
    EVIDENCE_PAYLOAD_INCOMPLETE = "EVIDENCE_PAYLOAD_INCOMPLETE"
    EVIDENCE_PAYLOAD_SCHEMA_INVALID = "EVIDENCE_PAYLOAD_SCHEMA_INVALID"
    EVIDENCE_ROLE_CONFLICT = "EVIDENCE_ROLE_CONFLICT"
    EVIDENCE_SNAPSHOT_CONFLICT = "EVIDENCE_SNAPSHOT_CONFLICT"
    EVIDENCE_TIME_SCOPE_MISSING = "EVIDENCE_TIME_SCOPE_MISSING"
    EVIDENCE_TIMESTAMP_INVALID = "EVIDENCE_TIMESTAMP_INVALID"
    EVIDENCE_TIMESTAMP_IN_FUTURE = "EVIDENCE_TIMESTAMP_IN_FUTURE"
    EVIDENCE_ROOT_MISSING = "EVIDENCE_ROOT_MISSING"
    EVIDENCE_ROOT_INVALID = "EVIDENCE_ROOT_INVALID"
    ALL_REQUIRED_EVIDENCE_TRUSTWORTHY = "ALL_REQUIRED_EVIDENCE_TRUSTWORTHY"


REQUIRED_DECISION_ROLES = (
    "CLEARANCE_DECISION",
    "WEATHER",
    "PORT_ALIGNMENT",
    "CONGESTION",
    "HISTORICAL_DELAY",
)
EVIDENCE_GATE_POLICY_VERSION = "EVIDENCE_GATE_V2"

# These relationships mean the parent affected, validated, or substituted for
# the role record. EXCLUDED_FROM/REFERENCES are intentionally not trusted inputs.
_TRUST_RELEVANT_RELATIONSHIPS = {
    "INPUT_TO",
    "DERIVED_FROM",
    "OVERRIDES",
    "VALIDATES",
    "FALLBACK_FOR",
}


@dataclass(frozen=True)
class RecordIntegrity:
    record_id: UUID
    stored_checksum: str | None
    computed_checksum: str
    stored_integrity_checksum: str | None
    computed_integrity_checksum: str
    valid: bool


@dataclass(frozen=True)
class EvidenceAssessment:
    decision_state: DecisionState
    kit_status: EvidenceKitStatus
    reason_codes: tuple[str, ...]
    role_status: dict[str, dict[str, Any]] = field(default_factory=dict)
    integrity: dict[UUID, RecordIntegrity] = field(default_factory=dict)
    root_integrity_valid: bool = False
    computed_root_checksum: str | None = None


def verify_record_integrity(record: ProvenanceRecord) -> RecordIntegrity:
    computed = stable_checksum(record.value_summary)
    stored = record.checksum
    computed_integrity = stable_checksum(record_integrity_payload(record))
    stored_integrity = record.integrity_checksum
    return RecordIntegrity(
        record_id=record.id,
        stored_checksum=stored,
        computed_checksum=computed,
        stored_integrity_checksum=stored_integrity,
        computed_integrity_checksum=computed_integrity,
        valid=(
            bool(stored)
            and stored == computed
            and bool(stored_integrity)
            and stored_integrity == computed_integrity
        ),
    )


def _ancestors_for_role(
    direct_ids: set[UUID], edges: Iterable[LineageEdge], available_ids: set[UUID]
) -> set[UUID]:
    parents_by_child: dict[UUID, set[UUID]] = {}
    for edge in edges:
        if edge.relationship not in _TRUST_RELEVANT_RELATIONSHIPS:
            continue
        parents_by_child.setdefault(edge.child_record_id, set()).add(edge.parent_record_id)
    included = set(direct_ids)
    pending = list(direct_ids)
    while pending:
        child_id = pending.pop()
        for parent_id in parents_by_child.get(child_id, set()):
            if parent_id in available_ids and parent_id not in included:
                included.add(parent_id)
                pending.append(parent_id)
    return included


_SOURCE_KEY_BY_ID = {value: key for key, value in SOURCE_IDS.items()}

_LIVE_SOURCE_KEYS = {
    "open_meteo",
    "openweather",
    "noaa_swpc",
    "railradar",
    "aisstream",
    "maritime_feed",
    "ixigo_partner",
}
_ALLOWED_TYPES_BY_SOURCE_KEY = {
    **{
        key: {"LIVE_PROVIDER", "CACHED_PROVIDER", "UNAVAILABLE"}
        for key in _LIVE_SOURCE_KEYS
    },
    "operator_input": {"OPERATOR_INPUT"},
    "demo_engineering": {"SEEDED_BASELINE"},
    "route_baseline": {"SEEDED_BASELINE"},
    "clearpath_derived": {"DERIVED", "OFFLINE_COMPUTED", "UNAVAILABLE"},
    "imported_engineering": {"IMPORTED_DOCUMENT"},
}
_ALLOWED_DIRECT_TYPES_BY_ROLE = {
    "CLEARANCE_DECISION": {"DERIVED"},
    "WEATHER": {"DERIVED"},
    "PORT_ALIGNMENT": {"LIVE_PROVIDER", "CACHED_PROVIDER"},
    "CONGESTION": {"DERIVED"},
    "HISTORICAL_DELAY": {"DERIVED"},
}
_EXPECTED_DIRECT_ENTITY_BY_ROLE = {
    "CLEARANCE_DECISION": "CLEARANCE_RESULT",
    "WEATHER": "WEATHER_SCORE",
    "PORT_ALIGNMENT": "PORT_ALIGNMENT_SCORE",
    "CONGESTION": "CONGESTION_SCORE",
    "HISTORICAL_DELAY": "HISTORICAL_DELAY_SCORE",
}


def _is_number(value: Any, *, minimum: float | None = None, maximum: float | None = None) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    numeric = float(value)
    if minimum is not None and numeric < minimum:
        return False
    if maximum is not None and numeric > maximum:
        return False
    return True


def _is_nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _score_payload(value: dict[str, Any]) -> bool:
    return _is_number(value.get("score"), minimum=0, maximum=100)


def _payload_matches_entity(record: ProvenanceRecord) -> bool:
    """Validate the minimum semantic contract for evidence used by policy v2."""

    value = record.value_summary
    if not isinstance(value, dict):
        return False
    entity_type = record.entity_type
    if entity_type == "CARGO_DECLARATION":
        return all(_is_number(value.get(key), minimum=0.001) for key in ("height", "width", "weight"))
    if entity_type == "ENGINEERING_LIMITS":
        segments = value.get("segments")
        return (
            value.get("certification") == "VERIFIED"
            and isinstance(segments, list)
            and bool(segments)
            and all(
                isinstance(segment, dict)
                and _is_nonempty_text(segment.get("id"))
                and _is_number(segment.get("max_height"), minimum=0.001)
                and _is_number(segment.get("max_width"), minimum=0.001)
                and _is_number(segment.get("max_weight"), minimum=0.001)
                and _is_nonempty_text(segment.get("source_reference"))
                and _is_nonempty_text(segment.get("certified_by"))
                and _is_nonempty_text(segment.get("certified_at"))
                and segment.get("verified") is True
                and _is_nonempty_text(segment.get("declared_checksum"))
                and segment.get("declared_checksum") == segment.get("computed_checksum")
                for segment in segments
            )
        )
    if entity_type == "CLEARANCE_RESULT":
        return value.get("status") in {"APPROVED", "HARD_BLOCKED"} and (
            value.get("blocking_segment_id") is None
            or _is_nonempty_text(value.get("blocking_segment_id"))
        )
    if entity_type == "WEATHER_OBSERVATION":
        wind = value.get("wind")
        main = value.get("main")
        weather = value.get("weather")
        return (
            isinstance(wind, dict)
            and _is_number(wind.get("speed"), minimum=0)
            and isinstance(main, dict)
            and _is_number(main.get("visibility"), minimum=0)
            and isinstance(weather, list)
            and bool(weather)
            and isinstance(weather[0], dict)
            and _is_number(weather[0].get("id"), minimum=0)
        )
    if entity_type == "WEATHER_SCORE":
        return _score_payload(value) and value.get("provider_unavailable") is False
    if entity_type == "PORT_ALIGNMENT_SCORE":
        window = value.get("loading_window")
        return (
            _score_payload(value)
            and value.get("available") is True
            and isinstance(value.get("aligned"), bool)
            and _is_nonempty_text(value.get("port_id"))
            and _is_nonempty_text(value.get("vessel_id"))
            and _is_nonempty_text(value.get("evaluated_at"))
            and _is_number(value.get("train_arrival_hours"), minimum=0)
            and isinstance(window, dict)
            and _is_nonempty_text(window.get("start"))
            and _is_nonempty_text(window.get("end"))
        )
    if entity_type == "CONGESTION_BASELINE":
        factors = value.get("segment_factors")
        return (
            _score_payload(value)
            and isinstance(factors, list)
            and bool(factors)
            and all(_is_number(item, minimum=0) for item in factors)
        )
    if entity_type == "RAIL_CONGESTION_SIGNAL":
        return (
            _score_payload(value)
            and isinstance(value.get("stations_live"), int)
            and isinstance(value.get("stations_total"), int)
            and 0 <= value["stations_live"] <= value["stations_total"]
        )
    if entity_type == "AIS_PORT_ACTIVITY":
        return _is_number(value.get("congestion_pct"), minimum=0, maximum=100) and _is_number(
            value.get("penalty"), minimum=0
        )
    if entity_type == "CONGESTION_SCORE":
        return _score_payload(value) and _is_number(value.get("static_score"), minimum=0, maximum=100)
    if entity_type == "HISTORICAL_DELAY_SCORE":
        delays = value.get("segment_delay_hours")
        return (
            _score_payload(value)
            and isinstance(delays, list)
            and bool(delays)
            and all(_is_number(item, minimum=0) for item in delays)
        )
    return False


def _is_aware(value: datetime | None) -> bool:
    return bool(value is not None and value.tzinfo is not None and value.utcoffset() is not None)


def _context_failure_codes(
    record: ProvenanceRecord,
    snapshot: RouteDecisionSnapshot,
) -> list[str]:
    if (
        record.route_id != snapshot.route_id
        or record.decision_snapshot_id != snapshot.id
        or record.user_id != snapshot.user_id
        or record.request_id != snapshot.request_id
    ):
        return [EvidenceReasonCode.EVIDENCE_CONTEXT_MISMATCH.value]

    value = record.value_summary if isinstance(record.value_summary, dict) else {}
    if record.entity_type == "CARGO_DECLARATION":
        for key in ("height", "width", "weight"):
            expected = snapshot.cargo_request.get(key)
            actual = value.get(key)
            if not (_is_number(expected) and _is_number(actual)) or abs(
                float(expected) - float(actual)
            ) > 1e-6:
                return [EvidenceReasonCode.EVIDENCE_SEMANTIC_CONTEXT_MISMATCH.value]
    elif record.entity_type == "ENGINEERING_LIMITS":
        segments = value.get("segments")
        if not isinstance(segments, list) or not segments:
            return []
        supplied_ids = {
            str(segment.get("id")) for segment in segments if isinstance(segment, dict)
        }
        if supplied_ids != {str(item) for item in snapshot.route_segment_ids}:
            return [EvidenceReasonCode.EVIDENCE_SEMANTIC_CONTEXT_MISMATCH.value]
        first = segments[0]
        last = segments[-1]
        if (
            not isinstance(first, dict)
            or not isinstance(last, dict)
            or first.get("source_code") != snapshot.source_code
            or last.get("destination_code") != snapshot.destination_code
        ):
            return [EvidenceReasonCode.EVIDENCE_SEMANTIC_CONTEXT_MISMATCH.value]
    return []


def _source_identity_failure_codes(record: ProvenanceRecord) -> list[str]:
    if record.source_id is None:
        return [EvidenceReasonCode.EVIDENCE_SOURCE_ID_MISSING.value]
    source_key = _SOURCE_KEY_BY_ID.get(record.source_id)
    if source_key is None:
        return [EvidenceReasonCode.EVIDENCE_SOURCE_ID_UNKNOWN.value]
    source_type = (record.canonical_source_type or "").upper()
    if source_type not in _ALLOWED_TYPES_BY_SOURCE_KEY.get(source_key, set()):
        return [EvidenceReasonCode.EVIDENCE_SOURCE_ID_MISMATCH.value]
    return []


def _source_catalog_failure_codes(
    record: ProvenanceRecord,
    sources_by_id: Mapping[UUID, DataSource] | None,
) -> list[str]:
    if sources_by_id is None or record.source_id is None:
        return []
    source = sources_by_id.get(record.source_id)
    if source is None:
        return [EvidenceReasonCode.EVIDENCE_SOURCE_POLICY_MISSING.value]
    expected_key = _SOURCE_KEY_BY_ID.get(record.source_id)
    if source.key != expected_key:
        return [EvidenceReasonCode.EVIDENCE_SOURCE_ID_MISMATCH.value]
    if source.enabled is not True:
        return [EvidenceReasonCode.EVIDENCE_SOURCE_DISABLED.value]
    return []


def _timestamp_failure_codes(record: ProvenanceRecord, now: datetime) -> list[str]:
    reasons: list[str] = []
    if not _is_aware(record.fetched_at):
        reasons.append(EvidenceReasonCode.EVIDENCE_TIMESTAMP_INVALID.value)
        return reasons

    tolerance_seconds = 300
    if (record.fetched_at - now).total_seconds() > tolerance_seconds:
        reasons.append(EvidenceReasonCode.EVIDENCE_TIMESTAMP_IN_FUTURE.value)

    source_key = _SOURCE_KEY_BY_ID.get(record.source_id)
    source_type = (record.canonical_source_type or "").upper()
    if source_key in _LIVE_SOURCE_KEYS and not _is_aware(record.observed_at):
        reasons.append(EvidenceReasonCode.EVIDENCE_TIMESTAMP_INVALID.value)
    elif record.observed_at is not None:
        if not _is_aware(record.observed_at):
            reasons.append(EvidenceReasonCode.EVIDENCE_TIMESTAMP_INVALID.value)
        else:
            if (record.observed_at - now).total_seconds() > tolerance_seconds:
                reasons.append(EvidenceReasonCode.EVIDENCE_TIMESTAMP_IN_FUTURE.value)
            if (record.observed_at - record.fetched_at).total_seconds() > tolerance_seconds:
                reasons.append(EvidenceReasonCode.EVIDENCE_TIMESTAMP_INVALID.value)

    if record.valid_until is not None:
        if not _is_aware(record.valid_until):
            reasons.append(EvidenceReasonCode.EVIDENCE_TIMESTAMP_INVALID.value)
        elif record.observed_at is not None and _is_aware(record.observed_at):
            if record.valid_until < record.observed_at:
                reasons.append(EvidenceReasonCode.EVIDENCE_TIMESTAMP_INVALID.value)

    # Operator and imported records need an issue/observation time.  Without
    # an issuer-provided expiry, policy v2 applies a conservative maximum age
    # instead of treating NOT_APPLICABLE as indefinite validity.
    if source_type in {"OPERATOR_INPUT", "IMPORTED_DOCUMENT"}:
        if not _is_aware(record.observed_at):
            reasons.append(EvidenceReasonCode.EVIDENCE_TIME_SCOPE_MISSING.value)
        elif record.valid_until is None:
            max_age_seconds = 86_400 if source_type == "OPERATOR_INPUT" else 31_622_400
            if (now - record.observed_at).total_seconds() > max_age_seconds:
                reasons.append(EvidenceReasonCode.EVIDENCE_STALE.value)
    return reasons


def _role_policy_failure_codes(
    role: str,
    direct_records: list[ProvenanceRecord],
    relevant_records: list[ProvenanceRecord],
    snapshot: RouteDecisionSnapshot,
) -> list[str]:
    reasons: list[str] = []
    allowed_direct = _ALLOWED_DIRECT_TYPES_BY_ROLE[role]
    if any(
        (record.canonical_source_type or "").upper() not in allowed_direct
        for record in direct_records
    ):
        reasons.append(EvidenceReasonCode.EVIDENCE_ROLE_SOURCE_NOT_ALLOWED.value)
    if len(direct_records) != 1:
        reasons.append(EvidenceReasonCode.EVIDENCE_ROLE_CONFLICT.value)
    if any(
        record.entity_type != _EXPECTED_DIRECT_ENTITY_BY_ROLE[role]
        for record in direct_records
    ):
        reasons.append(EvidenceReasonCode.EVIDENCE_PAYLOAD_SCHEMA_INVALID.value)

    score_keys = {
        "WEATHER": "weather",
        "PORT_ALIGNMENT": "port",
        "CONGESTION": "congestion",
        "HISTORICAL_DELAY": "historical",
    }
    for record in direct_records:
        if role == "CLEARANCE_DECISION":
            if record.value_summary.get("status") != (snapshot.clearance_state or "").upper():
                reasons.append(EvidenceReasonCode.EVIDENCE_SNAPSHOT_CONFLICT.value)
        else:
            score_key = score_keys[role]
            expected = snapshot.score_breakdown.get(score_key)
            actual = record.value_summary.get("score")
            if not (_is_number(expected) and _is_number(actual)) or abs(
                float(expected) - float(actual)
            ) > 1e-6:
                reasons.append(EvidenceReasonCode.EVIDENCE_SNAPSHOT_CONFLICT.value)

    ancestors = [record for record in relevant_records if record not in direct_records]
    if role == "CLEARANCE_DECISION":
        has_cargo = any(
            record.entity_type == "CARGO_DECLARATION"
            and record.source_id == SOURCE_IDS["operator_input"]
            and record.canonical_source_type == "OPERATOR_INPUT"
            for record in ancestors
        )
        has_verified_engineering = any(
            record.entity_type == "ENGINEERING_LIMITS"
            and record.source_id == SOURCE_IDS["imported_engineering"]
            and record.canonical_source_type == "IMPORTED_DOCUMENT"
            and record.metadata_json.get("verified") is True
            and record.metadata_json.get("signature_verified") is True
            and record.metadata_json.get("issuer_authentication")
            in {"DETACHED_SIGNATURE", "AUTHENTICATED_CONNECTOR"}
            for record in ancestors
        )
        if not has_cargo or not has_verified_engineering:
            reasons.append(EvidenceReasonCode.EVIDENCE_LINEAGE_INCOMPLETE.value)
    elif role == "WEATHER":
        has_weather_observation = any(
            record.entity_type == "WEATHER_OBSERVATION"
            and record.source_id in {SOURCE_IDS["open_meteo"], SOURCE_IDS["openweather"]}
            and record.canonical_source_type in {"LIVE_PROVIDER", "CACHED_PROVIDER"}
            for record in ancestors
        )
        if not has_weather_observation:
            reasons.append(EvidenceReasonCode.EVIDENCE_LINEAGE_INCOMPLETE.value)
    elif role == "CONGESTION":
        has_measured_or_approved_input = any(
            record.canonical_source_type
            in {"LIVE_PROVIDER", "CACHED_PROVIDER", "IMPORTED_DOCUMENT", "OPERATOR_INPUT"}
            for record in ancestors
        )
        if not has_measured_or_approved_input:
            reasons.append(EvidenceReasonCode.EVIDENCE_LINEAGE_INCOMPLETE.value)
    elif role == "PORT_ALIGNMENT":
        for record in direct_records:
            source_type = record.canonical_source_type
            if source_type in {"LIVE_PROVIDER", "CACHED_PROVIDER"} and record.source_id != SOURCE_IDS[
                "maritime_feed"
            ]:
                reasons.append(EvidenceReasonCode.EVIDENCE_ROLE_SOURCE_NOT_ALLOWED.value)
    elif role == "HISTORICAL_DELAY":
        has_verified_history = any(
            record.entity_type == "ENGINEERING_LIMITS"
            and record.source_id == SOURCE_IDS["imported_engineering"]
            and record.canonical_source_type == "IMPORTED_DOCUMENT"
            and record.metadata_json.get("verified") is True
            and record.metadata_json.get("signature_verified") is True
            and record.metadata_json.get("issuer_authentication")
            in {"DETACHED_SIGNATURE", "AUTHENTICATED_CONNECTOR"}
            for record in ancestors
        )
        if not has_verified_history:
            reasons.append(EvidenceReasonCode.EVIDENCE_LINEAGE_INCOMPLETE.value)
    return reasons


def _effective_freshness(record: ProvenanceRecord, now: datetime) -> str:
    if record.valid_until is not None:
        valid_until = record.valid_until
        if valid_until.tzinfo is None:
            valid_until = valid_until.replace(tzinfo=timezone.utc)
        if now > valid_until:
            return "STALE"
    source_key = _SOURCE_KEY_BY_ID.get(record.source_id)
    if source_key is None:
        return (record.freshness_state or "UNKNOWN").upper()
    state, _age = calculate_freshness(source_key, record.observed_at, record.fetched_at, now)
    return state.value


def _record_failure_codes(
    record: ProvenanceRecord,
    role: str,
    integrity: RecordIntegrity,
    now: datetime,
) -> list[str]:
    reasons: list[str] = []
    if not isinstance(record.value_summary, dict) or not record.value_summary:
        reasons.append(EvidenceReasonCode.EVIDENCE_PAYLOAD_EMPTY.value)
    try:
        completeness = float(record.completeness) if record.completeness is not None else None
    except (TypeError, ValueError):
        completeness = None
    if completeness is None or completeness < 1.0:
        reasons.append(EvidenceReasonCode.EVIDENCE_PAYLOAD_INCOMPLETE.value)
    if not _payload_matches_entity(record):
        reasons.append(EvidenceReasonCode.EVIDENCE_PAYLOAD_SCHEMA_INVALID.value)
    freshness = _effective_freshness(record, now)
    if freshness == "AGING":
        reasons.append(EvidenceReasonCode.EVIDENCE_AGING.value)
    elif freshness == "STALE":
        reasons.append(EvidenceReasonCode.EVIDENCE_STALE.value)
    elif freshness not in {"FRESH", "NOT_APPLICABLE"}:
        reasons.append(EvidenceReasonCode.EVIDENCE_FRESHNESS_UNKNOWN.value)

    availability = (record.availability_state or "UNKNOWN").upper()
    if availability in {"UNAVAILABLE", "NOT_CONFIGURED"}:
        reasons.append(EvidenceReasonCode.EVIDENCE_UNAVAILABLE.value)
    elif availability == "DEGRADED":
        reasons.append(EvidenceReasonCode.EVIDENCE_DEGRADED.value)
    elif availability != "AVAILABLE":
        reasons.append(EvidenceReasonCode.EVIDENCE_AVAILABILITY_UNKNOWN.value)

    if not record.checksum:
        reasons.append(EvidenceReasonCode.CHECKSUM_MISSING.value)
    elif record.checksum != stable_checksum(record.value_summary):
        reasons.append(EvidenceReasonCode.CHECKSUM_INVALID.value)
    if not integrity.stored_integrity_checksum:
        reasons.append(EvidenceReasonCode.RECORD_ENVELOPE_MISSING.value)
    elif integrity.stored_integrity_checksum != integrity.computed_integrity_checksum:
        reasons.append(EvidenceReasonCode.RECORD_ENVELOPE_INVALID.value)

    source_type = (record.canonical_source_type or "").upper()
    if source_type == CanonicalSourceType.UNAVAILABLE.value:
        reasons.append(EvidenceReasonCode.EVIDENCE_UNAVAILABLE.value)
    elif source_type not in {item.value for item in CanonicalSourceType}:
        reasons.append(EvidenceReasonCode.EVIDENCE_SOURCE_UNKNOWN.value)
    if source_type == "SIMULATED":
        reasons.append(EvidenceReasonCode.EVIDENCE_SIMULATED.value)
    elif source_type == "SEEDED_BASELINE":
        reasons.append(EvidenceReasonCode.EVIDENCE_SEEDED.value)
    if role == "CLEARANCE_DECISION" and source_type == "SIMULATED":
        reasons.append(EvidenceReasonCode.CRITICAL_CLEARANCE_SIMULATED.value)
    elif role == "CLEARANCE_DECISION" and source_type == "SEEDED_BASELINE":
        reasons.append(EvidenceReasonCode.CRITICAL_CLEARANCE_SEEDED.value)
    if role == "PORT_ALIGNMENT" and source_type == "OPERATOR_INPUT":
        window = record.value_summary.get("loading_window")
        reference = window.get("manifest_reference") if isinstance(window, dict) else None
        checksum = window.get("manifest_sha256") if isinstance(window, dict) else None
        if not isinstance(reference, str) or len(reference.strip()) < 3 or not (
            isinstance(checksum, str)
            and len(checksum) == 64
            and all(char in "0123456789abcdefABCDEF" for char in checksum)
        ):
            reasons.append(EvidenceReasonCode.OPERATOR_EVIDENCE_UNVERIFIED.value)
    return reasons


def _lineage_failure_codes(
    edges: Iterable[LineageEdge], available_ids: set[UUID]
) -> list[str]:
    graph: dict[UUID, set[UUID]] = {}
    for edge in edges:
        if edge.relationship not in _TRUST_RELEVANT_RELATIONSHIPS:
            continue
        if (
            edge.parent_record_id not in available_ids
            or edge.child_record_id not in available_ids
            or edge.parent_record_id == edge.child_record_id
        ):
            return [EvidenceReasonCode.EVIDENCE_LINEAGE_INVALID.value]
        graph.setdefault(edge.parent_record_id, set()).add(edge.child_record_id)

    visiting: set[UUID] = set()
    visited: set[UUID] = set()

    def has_cycle(node: UUID) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(has_cycle(child) for child in graph.get(node, set())):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    if any(has_cycle(node) for node in graph):
        return [EvidenceReasonCode.EVIDENCE_LINEAGE_INVALID.value]
    return []


def assess_decision_evidence(
    snapshot: RouteDecisionSnapshot | None,
    records: Iterable[ProvenanceRecord],
    edges: Iterable[LineageEdge] = (),
    *,
    now: datetime | None = None,
    sources_by_id: Mapping[UUID, DataSource] | None = None,
) -> EvidenceAssessment:
    """Evaluate only stored evidence; never contacts an external provider.

    HARD_BLOCKED always wins. With no snapshot there is no stored decision and
    the state is UNAVAILABLE. Every other uncertainty fails closed to HOLD.
    """

    records = list(records)
    edges = list(edges)
    now = now or datetime.now(timezone.utc)
    integrity = {record.id: verify_record_integrity(record) for record in records}
    if snapshot is None:
        return EvidenceAssessment(
            decision_state=DecisionState.UNAVAILABLE,
            kit_status=EvidenceKitStatus.UNAVAILABLE,
            reason_codes=(EvidenceReasonCode.NO_STORED_DECISION_EVIDENCE.value,),
            integrity=integrity,
        )

    clearance_state = (snapshot.clearance_state or "").upper()
    hard_blocked = clearance_state == DecisionState.HARD_BLOCKED.value
    available_ids = set(integrity)
    role_status: dict[str, dict[str, Any]] = {}
    all_reasons: list[str] = []
    all_reasons.extend(_lineage_failure_codes(edges, available_ids))
    for record in records:
        all_reasons.extend(_context_failure_codes(record, snapshot))
        all_reasons.extend(_source_identity_failure_codes(record))
        all_reasons.extend(_source_catalog_failure_codes(record, sources_by_id))
        all_reasons.extend(_timestamp_failure_codes(record, now))
    if clearance_state not in {"APPROVED", DecisionState.HARD_BLOCKED.value}:
        all_reasons.append(EvidenceReasonCode.CLEARANCE_NOT_APPROVED.value)
    for role in REQUIRED_DECISION_ROLES:
        direct_records = [record for record in records if record.decision_input_role == role]
        direct_ids = {record.id for record in direct_records}
        if not direct_ids:
            reasons = [EvidenceReasonCode.REQUIRED_ROLE_MISSING.value]
            relevant_ids: set[UUID] = set()
        else:
            relevant_ids = _ancestors_for_role(direct_ids, edges, available_ids)
            reasons = []
            relevant_records = [record for record in records if record.id in relevant_ids]
            for record in records:
                if record.id in relevant_ids and record.used_in_decision is not True:
                    reasons.append(EvidenceReasonCode.REQUIRED_INPUT_EXCLUDED.value)
                if record.id in relevant_ids:
                    reasons.extend(_record_failure_codes(record, role, integrity[record.id], now))
            reasons.extend(
                _role_policy_failure_codes(role, direct_records, relevant_records, snapshot)
            )
        reasons = sorted(set(reasons))
        all_reasons.extend(reasons)
        role_status[role] = {
            "trustworthy": not reasons,
            "record_ids": sorted(str(record.id) for record in records if record.id in relevant_ids),
            "reason_codes": reasons,
        }

    root_valid, computed_root = verify_evidence_root(snapshot, records, edges)
    if not snapshot.evidence_root_checksum or not snapshot.evidence_root_signature:
        all_reasons.append(EvidenceReasonCode.EVIDENCE_ROOT_MISSING.value)
    elif not root_valid:
        all_reasons.append(EvidenceReasonCode.EVIDENCE_ROOT_INVALID.value)
    all_reasons = sorted(set(all_reasons))
    if hard_blocked:
        reasons = [EvidenceReasonCode.HARD_CLEARANCE_BLOCK.value, *all_reasons]
        state = DecisionState.HARD_BLOCKED
    elif all_reasons:
        reasons = all_reasons
        state = DecisionState.HOLD
    else:
        reasons = [EvidenceReasonCode.ALL_REQUIRED_EVIDENCE_TRUSTWORTHY.value]
        state = DecisionState.READY

    # A complete, integrity-valid stored kit remains HOT even when it proves a
    # hard physical block. Any evidence-quality failure makes the kit DEGRADED.
    kit_status = EvidenceKitStatus.DEGRADED if all_reasons else EvidenceKitStatus.HOT
    return EvidenceAssessment(
        decision_state=state,
        kit_status=kit_status,
        reason_codes=tuple(reasons),
        role_status=role_status,
        integrity=integrity,
        root_integrity_valid=root_valid,
        computed_root_checksum=computed_root,
    )


async def load_stored_evidence_assessment(
    db: AsyncSession, route_id: UUID, user_id: str
) -> EvidenceAssessment:
    """Load an owner's immutable snapshot and assess it without live refetches."""

    snapshot_result = await db.execute(
        select(RouteDecisionSnapshot).where(
            RouteDecisionSnapshot.route_id == route_id,
            RouteDecisionSnapshot.user_id == user_id,
        )
    )
    snapshot = snapshot_result.scalar_one_or_none()
    if snapshot is None:
        return assess_decision_evidence(None, [])
    record_result = await db.execute(
        select(ProvenanceRecord).where(
            ProvenanceRecord.decision_snapshot_id == snapshot.id,
            ProvenanceRecord.user_id == user_id,
        )
    )
    records = list(record_result.scalars().all())
    source_ids = {record.source_id for record in records if record.source_id is not None}
    sources_by_id: dict[UUID, DataSource] = {}
    if source_ids:
        source_result = await db.execute(select(DataSource).where(DataSource.id.in_(source_ids)))
        sources_by_id = {source.id: source for source in source_result.scalars().all()}
    record_ids = [record.id for record in records]
    edges: list[LineageEdge] = []
    if record_ids:
        edge_result = await db.execute(
            select(LineageEdge).where(
                LineageEdge.parent_record_id.in_(record_ids),
                LineageEdge.child_record_id.in_(record_ids),
            )
        )
        edges = list(edge_result.scalars().all())
    return assess_decision_evidence(
        snapshot,
        records,
        edges,
        sources_by_id=sources_by_id,
    )


def build_manifest(
    *,
    route_id: UUID,
    snapshot: RouteDecisionSnapshot | None,
    assessment: EvidenceAssessment,
    records: Iterable[ProvenanceRecord],
) -> tuple[dict[str, Any], str]:
    """Build a deterministic manifest and digest for incident export/verification."""

    records = list(records)
    manifest = {
        "schema_version": "clearpath.evidence-kit.v1",
        "evidence_gate_policy_version": EVIDENCE_GATE_POLICY_VERSION,
        "hash_algorithm": "SHA-256",
        "signature_algorithm": snapshot.evidence_root_algorithm if snapshot else None,
        "evidence_signing_key_id": snapshot.evidence_root_key_id if snapshot else None,
        "route_id": str(route_id),
        "snapshot_id": str(snapshot.id) if snapshot else None,
        "snapshot_created_at": str(snapshot.created_at) if snapshot else None,
        "decision_state": assessment.decision_state.value,
        "kit_status": assessment.kit_status.value,
        "reason_codes": list(assessment.reason_codes),
        "required_roles": list(REQUIRED_DECISION_ROLES),
        "role_status": assessment.role_status,
        "snapshot_digest": stable_checksum(
            {
                "clearance_state": snapshot.clearance_state,
                "blocking_segment_id": snapshot.blocking_segment_id,
                "reliability_score": snapshot.reliability_score,
                "estimated_hours": snapshot.estimated_hours,
                "score_breakdown": snapshot.score_breakdown,
                "applied_weights": snapshot.applied_weights,
                "excluded_factors": snapshot.excluded_factors,
                "algorithm_versions": {
                    "decision": snapshot.decision_engine_version,
                    "routing": snapshot.routing_algorithm_version,
                    "scoring": snapshot.scoring_version,
                    "clearance": snapshot.clearance_engine_version,
                },
            }
        )
        if snapshot
        else None,
        "records": [
            {
                "record_id": str(record.id),
                "stored_checksum": assessment.integrity[record.id].stored_checksum,
                "computed_checksum": assessment.integrity[record.id].computed_checksum,
                "stored_integrity_checksum": assessment.integrity[
                    record.id
                ].stored_integrity_checksum,
                "computed_integrity_checksum": assessment.integrity[
                    record.id
                ].computed_integrity_checksum,
                "integrity_valid": assessment.integrity[record.id].valid,
            }
            for record in sorted(records, key=lambda item: str(item.id))
        ],
        "stored_evidence_root_checksum": (
            snapshot.evidence_root_checksum if snapshot else None
        ),
        "computed_evidence_root_checksum": assessment.computed_root_checksum,
        "evidence_root_signature": snapshot.evidence_root_signature if snapshot else None,
        "root_integrity_valid": assessment.root_integrity_valid,
    }
    return manifest, stable_checksum(manifest)
