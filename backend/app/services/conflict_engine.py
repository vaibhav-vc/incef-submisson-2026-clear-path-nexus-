"""Network section-occupation and headway conflict evaluation.

The engine is deliberately pure: providers/importers persist normalized
records, then this module compares those records without contacting a provider
or inventing railway rules.  A conflict-free result is only returned when the
candidate and the relevant network coverage have attributable real sources
and every candidate section has a source-backed policy.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID


REAL_SOURCE_TYPES = {
    "LIVE_PROVIDER",
    "AUTHORIZED_FEED",
    "IMPORTED_DOCUMENT",
    "OPERATOR_INPUT",
    "REAL_HISTORICAL",
    "REPLAYED_SNAPSHOT",
}
CURRENT_SOURCE_TYPES = {
    "LIVE_PROVIDER",
    "AUTHORIZED_FEED",
    "IMPORTED_DOCUMENT",
    "OPERATOR_INPUT",
}
HISTORICAL_SOURCE_TYPES = {"REAL_HISTORICAL", "REPLAYED_SNAPSHOT"}
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def canonical_manifest_checksum(payload: Any) -> str:
    """Return the deterministic digest for a normalized carriage manifest.

    The checksum excludes the submitted checksum and top-level UI metadata,
    but includes every carriage field in position order.  This gives the
    client and API a shared tamper-evident representation without treating a
    checksum as proof that the underlying document is authoritative.
    """

    if hasattr(payload, "model_dump"):
        data = payload.model_dump(mode="json", exclude={"manifest_checksum", "metadata"})
    elif isinstance(payload, dict):
        data = dict(payload)
        data.pop("manifest_checksum", None)
        data.pop("metadata", None)
    else:
        raise TypeError("manifest payload must be a Pydantic model or object")
    carriages = data.get("carriages")
    if not isinstance(carriages, list):
        raise ValueError("manifest payload must contain carriages")
    data["carriages"] = sorted(
        carriages,
        key=lambda item: int(item["position_in_train"])
        if isinstance(item, dict) and "position_in_train" in item
        else 0,
    )
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ScheduleConflict:
    conflict_type: str
    candidate_schedule_id: UUID
    conflicting_schedule_id: UUID
    segment_id: UUID
    conflict_start: datetime
    conflict_end: datetime
    required_headway_seconds: float | None
    detail: str
    candidate_train_code: str
    conflicting_train_code: str
    policy_source_reference: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "conflict_type": self.conflict_type,
            "candidate_schedule_id": self.candidate_schedule_id,
            "conflicting_schedule_id": self.conflicting_schedule_id,
            "segment_id": self.segment_id,
            "conflict_start": self.conflict_start,
            "conflict_end": self.conflict_end,
            "required_headway_seconds": self.required_headway_seconds,
            "detail": self.detail,
            "candidate_train_code": self.candidate_train_code,
            "conflicting_train_code": self.conflicting_train_code,
            "policy_source_reference": self.policy_source_reference,
        }


@dataclass(frozen=True)
class NetworkConflictAssessment:
    status: str
    schedule_id: UUID
    conflicts: tuple[ScheduleConflict, ...]
    missing_evidence: tuple[str, ...]
    assessed_window_count: int
    assessed_schedule_count: int
    evidence_state: str
    explanation: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "schedule_id": self.schedule_id,
            "conflicts": [item.as_dict() for item in self.conflicts],
            "missing_evidence": list(self.missing_evidence),
            "assessed_window_count": self.assessed_window_count,
            "assessed_schedule_count": self.assessed_schedule_count,
            "evidence_state": self.evidence_state,
            "explanation": self.explanation,
        }


def _as_aware(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _identifier(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _source_errors(record: Any, *, label: str) -> list[str]:
    source_type = str(getattr(record, "source_type", "")).upper()
    source_reference = getattr(record, "source_reference", None)
    source_checksum = getattr(record, "source_checksum", None)
    verification_state = str(getattr(record, "verification_state", "")).upper()
    observed = _as_aware(getattr(record, "observed_at", None))
    fetched = _as_aware(getattr(record, "fetched_at", None))
    errors: list[str] = []
    if source_type not in REAL_SOURCE_TYPES:
        errors.append(f"{label}:SOURCE_NOT_REAL")
    if not isinstance(source_reference, str) or len(source_reference.strip()) < 3:
        errors.append(f"{label}:SOURCE_REFERENCE_MISSING")
    if not isinstance(source_checksum, str) or not SHA256_RE.fullmatch(source_checksum):
        errors.append(f"{label}:SOURCE_CHECKSUM_INVALID")
    if verification_state != "VERIFIED":
        errors.append(f"{label}:SOURCE_AUTHENTICATION_UNVERIFIED")
    if observed is None:
        errors.append(f"{label}:OBSERVED_AT_INVALID")
    if fetched is None:
        errors.append(f"{label}:FETCHED_AT_INVALID")
    elif observed is not None and fetched < observed:
        errors.append(f"{label}:FETCHED_BEFORE_OBSERVED")
    return errors


def assess_network_conflicts(
    candidate_schedule: Any,
    candidate_windows: Iterable[Any],
    other_schedules: Iterable[Any],
    policies: Iterable[Any],
    *,
    network_schedule_ids: Iterable[UUID] | None = None,
) -> NetworkConflictAssessment:
    """Assess one candidate against all supplied network movement windows.

    ``network_schedule_ids`` is an optional completeness assertion from the
    API/query layer.  When present, every non-cancelled schedule must have
    occupation windows; otherwise returning ``CLEAR`` would falsely imply
    that an unseen train cannot interrupt this candidate.
    """

    candidate_id = _identifier(getattr(candidate_schedule, "id", None))
    if candidate_id is None:
        raise ValueError("candidate_schedule.id must be a UUID")
    candidate_code = str(getattr(candidate_schedule, "train_code", candidate_id))

    candidate_windows = list(candidate_windows)
    other_schedules = [
        item
        for item in other_schedules
        if _identifier(getattr(item, "id", None)) != candidate_id
        and str(getattr(item, "schedule_status", "PLANNED")).upper() != "CANCELLED"
    ]
    policy_by_segment: dict[UUID, Any] = {}
    for policy in policies:
        segment_id = _identifier(getattr(policy, "segment_id", None))
        if segment_id is not None:
            policy_by_segment[segment_id] = policy

    missing: list[str] = []
    all_sources: list[Any] = []
    window_sources: list[Any] = []
    if not candidate_windows:
        missing.append("CANDIDATE_OCCUPATION_WINDOWS_MISSING")

    windows_by_schedule: dict[UUID, list[Any]] = {candidate_id: candidate_windows}
    for schedule in other_schedules:
        schedule_id = _identifier(getattr(schedule, "id", None))
        if schedule_id is None:
            missing.append("NETWORK_SCHEDULE_ID_INVALID")
            continue
        windows = list(getattr(schedule, "occupation_windows", ()) or ())
        windows_by_schedule[schedule_id] = windows
        if not windows:
            missing.append(f"OCCUPATION_WINDOWS_MISSING:{schedule_id}")

    if network_schedule_ids is not None:
        known_ids = set(windows_by_schedule)
        for schedule_id in network_schedule_ids:
            parsed_id = _identifier(schedule_id)
            if parsed_id is not None and parsed_id not in known_ids:
                missing.append(f"OCCUPATION_WINDOWS_MISSING:{parsed_id}")

    candidate_segment_ids: set[UUID] = set()
    for window in candidate_windows:
        segment_id = _identifier(getattr(window, "segment_id", None))
        if segment_id is None:
            missing.append("CANDIDATE_SEGMENT_ID_INVALID")
        else:
            candidate_segment_ids.add(segment_id)
        label = f"WINDOW:{getattr(window, 'id', 'new')}"
        missing.extend(_source_errors(window, label=label))
        if str(getattr(window, "source_type", "")).upper() in HISTORICAL_SOURCE_TYPES:
            missing.append(f"{label}:HISTORICAL_REPLAY")

    for schedule_id, windows in windows_by_schedule.items():
        all_sources.extend(windows)
        window_sources.extend(windows)
        if schedule_id == candidate_id:
            continue
        for window in windows:
            label = f"WINDOW:{getattr(window, 'id', schedule_id)}"
            missing.extend(_source_errors(window, label=label))
            if str(getattr(window, "source_type", "")).upper() in HISTORICAL_SOURCE_TYPES:
                missing.append(f"{label}:HISTORICAL_REPLAY")

    for segment_id in sorted(candidate_segment_ids, key=str):
        policy = policy_by_segment.get(segment_id)
        if policy is None:
            missing.append(f"TRACK_POLICY_MISSING:{segment_id}")
            continue
        all_sources.append(policy)
        missing.extend(_source_errors(policy, label=f"POLICY:{segment_id}"))
        source_type = str(getattr(policy, "source_type", "")).upper()
        if source_type in HISTORICAL_SOURCE_TYPES:
            missing.append(f"TRACK_POLICY_HISTORICAL:{segment_id}")
        if getattr(policy, "minimum_headway_seconds", None) is None:
            missing.append(f"MINIMUM_HEADWAY_POLICY_MISSING:{segment_id}")

    # If the candidate has malformed times, avoid an exception and fail closed.
    for window in window_sources:
        entry = _as_aware(getattr(window, "entry_time", None))
        exit_time = _as_aware(getattr(window, "exit_time", None))
        if entry is None or exit_time is None or exit_time <= entry:
            missing.append(f"WINDOW_TIME_INVALID:{getattr(window, 'id', 'unknown')}")

    conflicts: list[ScheduleConflict] = []
    seen: set[tuple[str, UUID, UUID, UUID]] = set()
    entries_by_segment: dict[UUID, list[tuple[UUID, Any, Any]]] = {}
    schedule_by_id: dict[UUID, Any] = {candidate_id: candidate_schedule}
    schedule_by_id.update(
        {
            schedule_id: schedule
            for schedule in other_schedules
            if (schedule_id := _identifier(getattr(schedule, "id", None))) is not None
        }
    )
    for schedule_id, windows in windows_by_schedule.items():
        for window in windows:
            segment_id = _identifier(getattr(window, "segment_id", None))
            entry = _as_aware(getattr(window, "entry_time", None))
            exit_time = _as_aware(getattr(window, "exit_time", None))
            if segment_id is not None and entry is not None and exit_time is not None and exit_time > entry:
                entries_by_segment.setdefault(segment_id, []).append((schedule_id, window, entry))

    for segment_id, entries in entries_by_segment.items():
        if segment_id not in candidate_segment_ids:
            continue
        policy = policy_by_segment.get(segment_id)
        policy_reference = str(getattr(policy, "source_reference", "")) if policy else ""
        single_track = bool(getattr(policy, "single_track", False)) if policy else False
        min_headway = getattr(policy, "minimum_headway_seconds", None) if policy else None
        min_headway = float(min_headway) if min_headway is not None else None

        for index, (left_schedule_id, left_window, left_entry) in enumerate(entries):
            left_exit = _as_aware(getattr(left_window, "exit_time", None))
            if left_exit is None:
                continue
            for right_schedule_id, right_window, right_entry in entries[index + 1 :]:
                if left_schedule_id == right_schedule_id:
                    continue
                right_exit = _as_aware(getattr(right_window, "exit_time", None))
                if right_exit is None:
                    continue
                left_direction = str(getattr(left_window, "direction", "")).upper()
                right_direction = str(getattr(right_window, "direction", "")).upper()
                overlap_start = max(left_entry, right_entry)
                overlap_end = min(left_exit, right_exit)
                conflict_type: str | None = None
                if overlap_start < overlap_end:
                    if single_track and left_direction != right_direction:
                        conflict_type = "OPPOSING_SINGLE_TRACK"
                    else:
                        conflict_type = "SAME_SECTION_OVERLAP"

                if conflict_type is not None and candidate_id in {left_schedule_id, right_schedule_id}:
                    other_id = right_schedule_id if left_schedule_id == candidate_id else left_schedule_id
                    key = (conflict_type, other_id, segment_id, candidate_id)
                    if key not in seen:
                        seen.add(key)
                        other = schedule_by_id.get(other_id)
                        conflicts.append(
                            ScheduleConflict(
                                conflict_type=conflict_type,
                                candidate_schedule_id=candidate_id,
                                conflicting_schedule_id=other_id,
                                segment_id=segment_id,
                                conflict_start=overlap_start,
                                conflict_end=overlap_end,
                                required_headway_seconds=min_headway,
                                detail=(
                                    f"{candidate_code} conflicts with "
                                    f"{getattr(other, 'train_code', other_id)} on section {segment_id}"
                                ),
                                candidate_train_code=candidate_code,
                                conflicting_train_code=str(getattr(other, "train_code", other_id)),
                                policy_source_reference=policy_reference,
                            )
                        )

                # Headway is checked on entry times for trains in the same
                # direction, and on a single-track section for opposing
                # movements.  The minimum comes from the persisted policy.
                if min_headway is not None:
                    same_direction = left_direction == right_direction
                    if same_direction or single_track:
                        earlier_id, earlier_entry, later_id, later_entry = (
                            (left_schedule_id, left_entry, right_schedule_id, right_entry)
                            if left_entry <= right_entry
                            else (right_schedule_id, right_entry, left_schedule_id, left_entry)
                        )
                        separation = (later_entry - earlier_entry).total_seconds()
                        if separation < min_headway and candidate_id in {left_schedule_id, right_schedule_id}:
                            other_id = later_id if earlier_id == candidate_id else earlier_id
                            key = ("MINIMUM_HEADWAY", other_id, segment_id, candidate_id)
                            if key not in seen:
                                seen.add(key)
                                other = schedule_by_id.get(other_id)
                                conflicts.append(
                                    ScheduleConflict(
                                        conflict_type="MINIMUM_HEADWAY",
                                        candidate_schedule_id=candidate_id,
                                        conflicting_schedule_id=other_id,
                                        segment_id=segment_id,
                                        conflict_start=earlier_entry,
                                        conflict_end=later_entry,
                                        required_headway_seconds=min_headway,
                                        detail=(
                                            f"Entry separation is {separation:.3f}s; "
                                            f"policy requires {min_headway:.3f}s on section {segment_id}"
                                        ),
                                        candidate_train_code=candidate_code,
                                        conflicting_train_code=str(getattr(other, "train_code", other_id)),
                                        policy_source_reference=policy_reference,
                                    )
                                )

    unique_missing = tuple(sorted(set(missing)))
    historical = any(
        str(getattr(source, "source_type", "")).upper() in HISTORICAL_SOURCE_TYPES
        for source in all_sources
    )
    if conflicts:
        status = "BLOCKED"
        evidence_state = (
            "HISTORICAL_REPLAY"
            if historical
            else ("INCOMPLETE" if unique_missing else "CURRENT_REAL")
        )
        explanation = (
            "Potential network section occupancy or headway conflict detected in the captured "
            "snapshot; retain the hold and obtain authenticated operational evidence."
            if unique_missing
            else "Network section occupancy or headway conflict detected in the captured snapshot."
        )
    elif historical:
        # A replay is useful for research and judge demonstrations, but it is
        # never evidence that the live network is clear at the current time.
        status = "UNAVAILABLE"
        evidence_state = "HISTORICAL_REPLAY"
        explanation = "Historical/replayed evidence cannot establish a current network-clear result."
    elif unique_missing:
        status = "UNAVAILABLE"
        evidence_state = "HISTORICAL_REPLAY" if historical else "INCOMPLETE"
        explanation = "A conflict-free result cannot be asserted because real network evidence is incomplete."
    else:
        status = "CLEAR"
        evidence_state = "CURRENT_REAL"
        explanation = (
            "No conflict was found among the authenticated section windows in this captured "
            "snapshot; this is not movement authority or proof of national-network completeness."
        )

    return NetworkConflictAssessment(
        status=status,
        schedule_id=candidate_id,
        conflicts=tuple(conflicts),
        missing_evidence=unique_missing,
        # Policies participate in provenance validation but are not movement
        # windows; report the latter count accurately to the API consumer.
        assessed_window_count=sum(len(windows) for windows in windows_by_schedule.values()),
        assessed_schedule_count=len(windows_by_schedule),
        evidence_state=evidence_state,
        explanation=explanation,
    )
