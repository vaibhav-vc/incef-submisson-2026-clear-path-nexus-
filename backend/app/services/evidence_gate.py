from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provenance import LineageEdge, ProvenanceRecord, RouteDecisionSnapshot
from app.services.provenance import (
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
    NO_STORED_DECISION_EVIDENCE = "NO_STORED_DECISION_EVIDENCE"
    REQUIRED_ROLE_MISSING = "REQUIRED_ROLE_MISSING"
    EVIDENCE_AGING = "EVIDENCE_AGING"
    EVIDENCE_STALE = "EVIDENCE_STALE"
    EVIDENCE_FRESHNESS_UNKNOWN = "EVIDENCE_FRESHNESS_UNKNOWN"
    EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
    EVIDENCE_DEGRADED = "EVIDENCE_DEGRADED"
    EVIDENCE_AVAILABILITY_UNKNOWN = "EVIDENCE_AVAILABILITY_UNKNOWN"
    CRITICAL_CLEARANCE_SIMULATED = "CRITICAL_CLEARANCE_SIMULATED"
    CRITICAL_CLEARANCE_SEEDED = "CRITICAL_CLEARANCE_SEEDED"
    EVIDENCE_SIMULATED = "EVIDENCE_SIMULATED"
    EVIDENCE_SEEDED = "EVIDENCE_SEEDED"
    OPERATOR_EVIDENCE_UNVERIFIED = "OPERATOR_EVIDENCE_UNVERIFIED"
    CHECKSUM_MISSING = "CHECKSUM_MISSING"
    CHECKSUM_INVALID = "CHECKSUM_INVALID"
    RECORD_ENVELOPE_MISSING = "RECORD_ENVELOPE_MISSING"
    RECORD_ENVELOPE_INVALID = "RECORD_ENVELOPE_INVALID"
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
EVIDENCE_GATE_POLICY_VERSION = "EVIDENCE_GATE_V1"

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
    freshness = _effective_freshness(record, now)
    if freshness == "AGING":
        reasons.append(EvidenceReasonCode.EVIDENCE_AGING.value)
    elif freshness == "STALE":
        reasons.append(EvidenceReasonCode.EVIDENCE_STALE.value)
    elif freshness == "UNKNOWN":
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


def assess_decision_evidence(
    snapshot: RouteDecisionSnapshot | None,
    records: Iterable[ProvenanceRecord],
    edges: Iterable[LineageEdge] = (),
    *,
    now: datetime | None = None,
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

    hard_blocked = (snapshot.clearance_state or "").upper() == DecisionState.HARD_BLOCKED.value
    available_ids = set(integrity)
    role_status: dict[str, dict[str, Any]] = {}
    all_reasons: list[str] = []
    for role in REQUIRED_DECISION_ROLES:
        direct_ids = {record.id for record in records if record.decision_input_role == role}
        if not direct_ids:
            reasons = [EvidenceReasonCode.REQUIRED_ROLE_MISSING.value]
            relevant_ids: set[UUID] = set()
        else:
            relevant_ids = _ancestors_for_role(direct_ids, edges, available_ids)
            reasons = []
            for record in records:
                if record.id in relevant_ids:
                    reasons.extend(_record_failure_codes(record, role, integrity[record.id], now))
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
    return assess_decision_evidence(snapshot, records, edges)


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
