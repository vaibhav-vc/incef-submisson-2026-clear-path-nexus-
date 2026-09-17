"""Fail-closed, route-independent evidence assurance primitives.

The service evaluates whether stored evidence is suitable for human review. It
does not calculate movement authority, dispatch a train, or certify safety.
"""

from __future__ import annotations

import hmac
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import settings
from app.models.assurance import AssuranceCase, AssuranceFinding, AssuranceSnapshot, ReviewReceipt
from app.models.provenance import DataSource, LineageEdge, ProvenanceRecord
from app.services.provenance import (
    record_integrity_payload,
    sign_evidence_root,
    stable_checksum,
)


POLICIES: dict[str, dict[str, Any]] = {
    "GENERIC_PROVENANCE_V1": {
        "key": "GENERIC_PROVENANCE_V1",
        "version": "1.0.0",
        "title": "Generic provenance admissibility",
        "description": (
            "Fails closed when required evidence is missing, unattributed, stale, "
            "incomplete, internally inconsistent, or fails integrity verification."
        ),
        "decision_states": ["REVIEWABLE", "HOLD", "UNAVAILABLE"],
        "checks": [
            {"code": "REQUIRED_ROLE_MISSING", "rule": "Every required role is present."},
            {"code": "SOURCE_UNAVAILABLE", "rule": "Source identity is enabled and known."},
            {"code": "EVIDENCE_INTEGRITY_INVALID", "rule": "Evidence envelope checksum matches."},
            {"code": "EVIDENCE_TIME_INVALID", "rule": "Capture timestamps are plausible."},
            {"code": "EVIDENCE_EXPIRED", "rule": "Evidence remains within validity bounds."},
            {"code": "EVIDENCE_INCOMPLETE", "rule": "Completeness is at least 0.90."},
            {"code": "EVIDENCE_CONFLICT", "rule": "Duplicate assertions do not conflict."},
            {"code": "DERIVED_LINEAGE_MISSING", "rule": "Derived evidence has a case parent."},
            {
                "code": "SOURCE_AUTHENTICITY_UNVERIFIED",
                "rule": "Provider evidence comes through an authenticated server connector.",
            },
            {
                "code": "EVIDENCE_CONTEXT_MISMATCH",
                "rule": "Captured evidence remains bound to the same assurance subject.",
            },
        ],
        "limitations": [
            "REVIEWABLE means evidence passed this policy, not that an operation is authorized.",
            "The policy is non-vital and must not supply movement authority or driver commands.",
        ],
    }
}

FUTURE_TOLERANCE = timedelta(minutes=5)
MIN_COMPLETENESS = 0.90
SUPPORTED_SOURCE_TYPES = frozenset(
    {
        "LIVE_PROVIDER",
        "CACHED_PROVIDER",
        "OPERATOR_INPUT",
        "IMPORTED_DOCUMENT",
        "PUBLIC_OPEN_DATA",
        "DERIVED",
        "OFFLINE_COMPUTED",
    }
)


@dataclass(frozen=True)
class FindingValue:
    code: str
    severity: str
    message: str
    record_ids: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssessmentValue:
    state: str
    findings: tuple[FindingValue, ...]
    matrix: dict[str, Any]
    metrics: dict[str, Any]
    evidence_manifest: tuple[dict[str, Any], ...]


def get_policy(policy_key: str) -> dict[str, Any]:
    try:
        return POLICIES[policy_key]
    except KeyError as exc:
        raise ValueError(f"Unknown assurance policy: {policy_key}") from exc


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _finding(
    target: list[FindingValue],
    code: str,
    message: str,
    record: ProvenanceRecord | None = None,
    *,
    severity: str = "ERROR",
    details: dict[str, Any] | None = None,
) -> None:
    target.append(
        FindingValue(
            code=code,
            severity=severity,
            message=message,
            record_ids=(str(record.id),) if record is not None else (),
            details=details or {},
        )
    )


def source_integrity_payload(source: DataSource) -> dict[str, Any]:
    """Fields that establish who supplied evidence and under which terms."""

    return {
        "id": source.id,
        "key": source.key,
        "display_name": source.display_name,
        "category": source.category,
        "provider_domain": source.provider_domain,
        "reference_url": source.reference_url,
        "license_name": source.license_name,
        "license_url": source.license_url,
        "attribution_text": source.attribution_text,
        "terms_note": source.terms_note,
        "authority_level": source.authority_level,
        "official": source.official,
        "requires_key": source.requires_key,
        "default_fresh_seconds": source.default_fresh_seconds,
        "aging_after_seconds": source.aging_after_seconds,
        "stale_after_seconds": source.stale_after_seconds,
        "enabled": source.enabled,
        "limitations": source.limitations,
    }


def assess_case_evidence(
    case: AssuranceCase,
    evidence: list[tuple[ProvenanceRecord, DataSource | None, str, bool]],
    lineage_edges: list[LineageEdge],
    *,
    now: datetime | None = None,
) -> AssessmentValue:
    """Evaluate one captured case without contacting any external provider."""

    get_policy(case.policy_key)
    assessed_at = _utc(now or datetime.now(timezone.utc))
    findings: list[FindingValue] = []
    role_rows: dict[str, list[tuple[ProvenanceRecord, DataSource | None, bool]]] = defaultdict(list)
    required_role_list = tuple(dict.fromkeys(role.strip().upper() for role in case.required_roles))
    required_roles = set(required_role_list)
    record_ids = {record.id for record, _source, _role, _required in evidence}
    record_rows = {row[0].id: row for row in evidence}
    parents_by_child: dict[Any, set[Any]] = defaultdict(set)
    children_by_parent: dict[Any, set[Any]] = defaultdict(set)
    external_parents_by_child: dict[Any, set[Any]] = defaultdict(set)
    lineage_relationships = {"DERIVED_FROM", "INPUT_TO"}
    for edge in lineage_edges:
        if edge.child_record_id not in record_ids or edge.relationship not in lineage_relationships:
            continue
        if edge.parent_record_id in record_ids:
            parents_by_child[edge.child_record_id].add(edge.parent_record_id)
            children_by_parent[edge.parent_record_id].add(edge.child_record_id)
        else:
            external_parents_by_child[edge.child_record_id].add(edge.parent_record_id)

    # Kahn's algorithm is iterative and bounded by the number of records plus
    # edges. Records left unresolved are in, or depend on, a lineage cycle and
    # therefore cannot establish an independent trust root.
    remaining_parent_count = {
        record_id: len(parents_by_child.get(record_id, set())) for record_id in record_ids
    }
    lineage_queue = deque(
        sorted(
            (record_id for record_id, count in remaining_parent_count.items() if count == 0),
            key=str,
        )
    )
    resolved_lineage: set[Any] = set()
    lineage_order: list[Any] = []
    while lineage_queue:
        record_id = lineage_queue.popleft()
        if record_id in resolved_lineage:
            continue
        resolved_lineage.add(record_id)
        lineage_order.append(record_id)
        for child_id in sorted(children_by_parent.get(record_id, set()), key=str):
            remaining_parent_count[child_id] -= 1
            if remaining_parent_count[child_id] == 0:
                lineage_queue.append(child_id)
    cyclic_or_cycle_dependent_records = record_ids - resolved_lineage

    evidence_manifest: list[dict[str, Any]] = []
    errors_by_role: dict[str, set[str]] = defaultdict(set)
    warnings_by_role: dict[str, set[str]] = defaultdict(set)
    invalid_codes_by_record: dict[Any, set[str]] = defaultdict(set)
    expected_context_checksum = stable_checksum(case.context_json)

    for record, source, role_value, link_required in evidence:
        role = role_value.strip().upper()
        role_required = link_required or role in required_roles
        role_rows[role].append((record, source, role_required))
        actual_integrity = stable_checksum(record_integrity_payload(record))
        evidence_manifest.append(
            {
                "record_id": str(record.id),
                "source_id": str(record.source_id) if record.source_id else None,
                "role": role,
                "required": role_required,
                "integrity_checksum": record.integrity_checksum,
                "source_metadata_checksum": (
                    stable_checksum(source_integrity_payload(source)) if source is not None else None
                ),
            }
        )

        record_findings: list[tuple[str, str]] = []
        if record.user_id != case.user_id:
            record_findings.append(("EVIDENCE_OWNER_MISMATCH", "Evidence owner differs from case owner."))
        if record.decision_input_role != role:
            record_findings.append(("EVIDENCE_ROLE_MISMATCH", "Evidence role binding is inconsistent."))
        if source is None or record.source_id is None or not source.enabled:
            record_findings.append(("SOURCE_UNAVAILABLE", "Evidence source is unknown or disabled."))
        elif record.source_id != source.id:
            record_findings.append(
                ("SOURCE_ID_MISMATCH", "Evidence source identifier does not match its source metadata.")
            )
        if record.canonical_source_type not in SUPPORTED_SOURCE_TYPES:
            record_findings.append(
                (
                    "EVIDENCE_SOURCE_TYPE_UNSUPPORTED",
                    "Evidence uses a source type that is not supported by this assurance policy.",
                )
            )
        if not record.used_in_decision or record.excluded_reason:
            record_findings.append(
                (
                    "EVIDENCE_EXCLUDED",
                    "Evidence excluded from the decision cannot satisfy an assurance role.",
                )
            )
        metadata = record.metadata_json if isinstance(record.metadata_json, dict) else {}
        provider_source_types = {"LIVE_PROVIDER", "CACHED_PROVIDER", "PUBLIC_OPEN_DATA"}
        if record.canonical_source_type in provider_source_types and not (
            record.raw_source_state == "AUTHENTICATED_CONNECTOR"
            and metadata.get("connector_authenticated") is True
        ):
            record_findings.append(
                (
                    "SOURCE_AUTHENTICITY_UNVERIFIED",
                    "Provider evidence was not produced by an authenticated server connector.",
                )
            )
        if record.canonical_source_type == "IMPORTED_DOCUMENT" and not (
            record.raw_source_state == "AUTHENTICATED_IMPORT"
            and metadata.get("signature_verified") is True
        ):
            record_findings.append(
                (
                    "SOURCE_AUTHENTICITY_UNVERIFIED",
                    "The imported document has no independently authenticated issuer receipt.",
                )
            )
        if (
            record.canonical_source_type == "OPERATOR_INPUT"
            or record.raw_source_state == "USER_DECLARED_OPERATOR_INPUT"
        ):
            record_findings.append(
                (
                    "SOURCE_USER_DECLARED",
                    "Operator input is a human declaration and has not been independently verified.",
                )
            )
        bound_case_id = metadata.get("assurance_case_id")
        if bound_case_id and bound_case_id != str(case.id):
            record_findings.append(
                ("EVIDENCE_CONTEXT_MISMATCH", "Evidence is bound to a different assurance case.")
            )
        bound_subject_type = metadata.get("assurance_subject_type")
        bound_subject_key = metadata.get("assurance_subject_key")
        bound_context_checksum = metadata.get("assurance_context_checksum")
        if (
            bound_subject_type != case.subject_type
            or bound_subject_key != case.subject_key
            or bound_context_checksum != expected_context_checksum
        ):
            record_findings.append(
                (
                    "EVIDENCE_CONTEXT_MISMATCH",
                    "Evidence is missing or mismatches the assurance subject and context binding.",
                )
            )
        if not record.integrity_checksum or not hmac.compare_digest(
            record.integrity_checksum, actual_integrity
        ):
            record_findings.append(
                ("EVIDENCE_INTEGRITY_INVALID", "Evidence envelope checksum does not match.")
            )
        observed = _utc(record.observed_at or record.fetched_at)
        fetched = _utc(record.fetched_at)
        if observed > fetched or fetched > assessed_at + FUTURE_TOLERANCE:
            record_findings.append(("EVIDENCE_TIME_INVALID", "Evidence timestamps are implausible."))
        if record.valid_until is not None and _utc(record.valid_until) < assessed_at:
            record_findings.append(("EVIDENCE_EXPIRED", "Evidence validity window has expired."))
        stale_after_seconds = getattr(source, "stale_after_seconds", None) if source else None
        if (
            record.canonical_source_type in provider_source_types
            and record.valid_until is None
            and stale_after_seconds is None
        ):
            record_findings.append(
                ("EVIDENCE_FRESHNESS_UNBOUNDED", "Provider evidence has no bounded freshness policy.")
            )
        if (
            stale_after_seconds is not None
            and (assessed_at - observed).total_seconds() > stale_after_seconds
        ):
            record_findings.append(
                ("EVIDENCE_EXPIRED", "Evidence exceeds the registered source freshness policy.")
            )
        if record.freshness_state not in {"FRESH", "NOT_APPLICABLE"}:
            record_findings.append(("EVIDENCE_NOT_FRESH", "Evidence is not currently fresh."))
        if record.availability_state != "AVAILABLE":
            record_findings.append(("EVIDENCE_UNAVAILABLE", "Evidence is not fully available."))
        completeness = float(record.completeness or 0)
        if completeness < MIN_COMPLETENESS:
            record_findings.append(
                (
                    "EVIDENCE_INCOMPLETE",
                    f"Evidence completeness {completeness:.3f} is below {MIN_COMPLETENESS:.2f}.",
                )
            )
        if not record.value_summary:
            record_findings.append(("EVIDENCE_PAYLOAD_EMPTY", "Evidence payload is empty."))
        if record.canonical_source_type in {"DERIVED", "OFFLINE_COMPUTED"} and not parents_by_child.get(record.id):
            record_findings.append(
                ("DERIVED_LINEAGE_MISSING", "Derived evidence has no parent record in this case.")
            )
        if record.canonical_source_type in {"DERIVED", "OFFLINE_COMPUTED"} and external_parents_by_child.get(record.id):
            record_findings.append(
                (
                    "DERIVED_LINEAGE_INCOMPLETE",
                    "Derived evidence has a required parent that is not linked to this case.",
                )
            )

        for code, message in record_findings:
            severity = "ERROR" if role_required else "WARNING"
            _finding(findings, code, message, record, severity=severity)
            target = errors_by_role if severity == "ERROR" else warnings_by_role
            target[role].add(code)
            invalid_codes_by_record[record.id].add(code)

    for record_id in sorted(cyclic_or_cycle_dependent_records, key=str):
        record, _source, role_value, link_required = record_rows[record_id]
        role = role_value.strip().upper()
        severity = "ERROR" if link_required or role in required_roles else "WARNING"
        _finding(
            findings,
            "DERIVED_LINEAGE_CYCLE",
            "Evidence derivation contains a cycle and cannot establish independent lineage.",
            record,
            severity=severity,
        )
        target = errors_by_role if severity == "ERROR" else warnings_by_role
        target[role].add("DERIVED_LINEAGE_CYCLE")
        invalid_codes_by_record[record_id].add("DERIVED_LINEAGE_CYCLE")

    assertion_groups: dict[tuple[str, str, str], list[ProvenanceRecord]] = defaultdict(list)
    for record, _source, role, _required in evidence:
        assertion_groups[(role.strip().upper(), record.entity_type, record.entity_key)].append(record)
    for rows in assertion_groups.values():
        if len({stable_checksum(row.value_summary) for row in rows}) > 1:
            for row in rows:
                invalid_codes_by_record[row.id].add("EVIDENCE_CONFLICT")

    # Propagate trust failure to every derived descendant in topological order.
    # This is independent of input ordering and treats optional invalid parents
    # as invalid trust inputs even though their own matrix row is only a warning.
    invalid_record_ids = set(invalid_codes_by_record)
    invalid_ancestors_by_record: dict[Any, set[Any]] = defaultdict(set)
    for child_id in lineage_order:
        child_record = record_rows[child_id][0]
        if child_record.canonical_source_type not in {"DERIVED", "OFFLINE_COMPUTED"}:
            continue
        for parent_id in parents_by_child.get(child_id, set()):
            if parent_id in invalid_record_ids:
                invalid_ancestors_by_record[child_id].add(parent_id)
                invalid_ancestors_by_record[child_id].update(
                    invalid_ancestors_by_record.get(parent_id, set())
                )
        if invalid_ancestors_by_record[child_id]:
            invalid_record_ids.add(child_id)

    for record_id in sorted(invalid_ancestors_by_record, key=str):
        if record_id in cyclic_or_cycle_dependent_records or not invalid_ancestors_by_record[record_id]:
            continue
        record, _source, role_value, link_required = record_rows[record_id]
        role = role_value.strip().upper()
        severity = "ERROR" if link_required or role in required_roles else "WARNING"
        invalid_ancestor_ids = sorted(
            (str(ancestor_id) for ancestor_id in invalid_ancestors_by_record[record_id]),
        )
        _finding(
            findings,
            "DERIVED_LINEAGE_INVALID",
            "Derived evidence depends transitively on evidence that failed assurance checks.",
            record,
            severity=severity,
            details={"invalid_ancestor_record_ids": invalid_ancestor_ids},
        )
        target = errors_by_role if severity == "ERROR" else warnings_by_role
        target[role].add("DERIVED_LINEAGE_INVALID")

    for normalized in required_role_list:
        if not role_rows.get(normalized):
            _finding(
                findings,
                "REQUIRED_ROLE_MISSING",
                f"Required evidence role {normalized} is missing.",
                details={"role": normalized},
            )
            errors_by_role[normalized].add("REQUIRED_ROLE_MISSING")

    for (role, entity_type, entity_key), rows in assertion_groups.items():
        value_digests = {stable_checksum(row.value_summary) for row in rows}
        if len(value_digests) > 1:
            ids = tuple(str(row.id) for row in rows)
            conflict_required = role in required_roles or any(row[2] for row in role_rows[role])
            findings.append(
                FindingValue(
                    code="EVIDENCE_CONFLICT",
                    severity="ERROR" if conflict_required else "WARNING",
                    message="Multiple records make conflicting assertions for the same subject.",
                    record_ids=ids,
                    details={"role": role, "entity_type": entity_type, "entity_key": entity_key},
                )
            )
            target = errors_by_role if conflict_required else warnings_by_role
            target[role].add("EVIDENCE_CONFLICT")

    all_roles = sorted(required_roles | set(role_rows))
    matrix_roles: list[dict[str, Any]] = []
    for role in all_roles:
        rows = role_rows.get(role, [])
        status = "PASS"
        if not rows:
            status = "MISSING"
        elif errors_by_role.get(role):
            status = "FAIL"
        elif warnings_by_role.get(role):
            status = "WARNING"
        matrix_roles.append(
            {
                "role": role,
                "required": role in required_roles or any(row[2] for row in rows),
                "status": status,
                "record_ids": [str(row[0].id) for row in rows],
                "source_keys": sorted({row[1].key for row in rows if row[1] is not None}),
                "reason_codes": sorted(errors_by_role[role] | warnings_by_role[role]),
            }
        )

    error_count = sum(item.severity == "ERROR" for item in findings)
    warning_count = sum(item.severity == "WARNING" for item in findings)
    state = "UNAVAILABLE" if not evidence else ("HOLD" if error_count else "REVIEWABLE")
    metrics = {
        "evidence_record_count": len(evidence),
        "required_role_count": len(required_roles),
        "satisfied_required_role_count": sum(
            item["required"] and item["status"] == "PASS" for item in matrix_roles
        ),
        "error_count": error_count,
        "warning_count": warning_count,
    }
    return AssessmentValue(
        state=state,
        findings=tuple(findings),
        matrix={"roles": matrix_roles},
        metrics=metrics,
        evidence_manifest=tuple(sorted(evidence_manifest, key=lambda item: item["record_id"])),
    )


def snapshot_manifest_payload(
    case: AssuranceCase,
    snapshot: AssuranceSnapshot,
    findings: list[AssuranceFinding],
) -> dict[str, Any]:
    """Canonical payload sealed by an assurance snapshot."""

    return {
        "format_version": "clearpath.assurance-manifest.v1",
        "case": {
            "id": case.id,
            "user_id": case.user_id,
            "assigned_reviewer_id": case.assigned_reviewer_id,
            "title": case.title,
            "purpose": case.purpose,
            "subject_type": case.subject_type,
            "subject_key": case.subject_key,
            "context": case.context_json,
            "required_roles": case.required_roles,
            "policy_key": case.policy_key,
            "policy_version": case.policy_version,
        },
        "snapshot": {
            "id": snapshot.id,
            "sequence_no": snapshot.sequence_no,
            "decision_state": snapshot.decision_state,
            "policy_key": snapshot.policy_key,
            "policy_version": snapshot.policy_version,
            "assessed_at": snapshot.assessed_at,
            "evidence_manifest": snapshot.evidence_manifest,
            "matrix": snapshot.matrix_json,
            "metrics": snapshot.metrics_json,
        },
        "findings": [
            {
                "id": item.id,
                "code": item.code,
                "severity": item.severity,
                "message": item.message,
                "evidence_record_ids": item.evidence_record_ids,
                "details": item.details_json,
            }
            for item in sorted(findings, key=lambda value: str(value.id))
        ],
    }


def seal_snapshot(
    case: AssuranceCase,
    snapshot: AssuranceSnapshot,
    findings: list[AssuranceFinding],
) -> None:
    checksum = stable_checksum(snapshot_manifest_payload(case, snapshot, findings))
    snapshot.bundle_checksum = checksum
    snapshot.signing_key_id = settings.EVIDENCE_SIGNING_KEY_ID
    snapshot.signing_algorithm = settings.EVIDENCE_SIGNING_ALGORITHM
    snapshot.bundle_signature = sign_evidence_root(checksum)


def verify_snapshot(
    case: AssuranceCase,
    snapshot: AssuranceSnapshot,
    findings: list[AssuranceFinding],
) -> tuple[bool, bool, str]:
    computed = stable_checksum(snapshot_manifest_payload(case, snapshot, findings))
    checksum_valid = hmac.compare_digest(snapshot.bundle_checksum, computed)
    try:
        expected_signature = sign_evidence_root(
            computed,
            key_id=snapshot.signing_key_id,
            algorithm=snapshot.signing_algorithm,
        )
    except RuntimeError:
        return checksum_valid, False, computed
    return checksum_valid, hmac.compare_digest(snapshot.bundle_signature, expected_signature), computed


def receipt_payload(receipt: ReviewReceipt) -> dict[str, Any]:
    return {
        "id": receipt.id,
        "case_id": receipt.case_id,
        "snapshot_id": receipt.snapshot_id,
        "reviewer_id": receipt.reviewer_id,
        "reviewer_role": receipt.reviewer_role,
        "outcome": receipt.outcome,
        "statement": receipt.statement,
        "snapshot_checksum": receipt.snapshot_checksum,
        "reviewed_at": receipt.reviewed_at,
    }


def seal_receipt(receipt: ReviewReceipt) -> None:
    checksum = stable_checksum(receipt_payload(receipt))
    receipt.receipt_checksum = checksum
    receipt.signing_key_id = settings.EVIDENCE_SIGNING_KEY_ID
    receipt.signing_algorithm = settings.EVIDENCE_SIGNING_ALGORITHM
    receipt.receipt_signature = sign_evidence_root(checksum)


def verify_receipt(receipt: ReviewReceipt) -> bool:
    computed = stable_checksum(receipt_payload(receipt))
    if not hmac.compare_digest(receipt.receipt_checksum, computed):
        return False
    try:
        expected = sign_evidence_root(
            computed,
            key_id=receipt.signing_key_id,
            algorithm=receipt.signing_algorithm,
        )
    except RuntimeError:
        return False
    return hmac.compare_digest(receipt.receipt_signature, expected)
