from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from geoalchemy2.shape import to_shape
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provenance import LineageEdge, ProvenanceRecord, RouteDecisionSnapshot
from app.core.config import settings
from app.schemas.provenance import (
    DecisionUseCounts,
    FreshnessCounts,
    ProvenanceSummary,
    SourceModeCounts,
    TraceabilityCounts,
)


class CanonicalSourceType(str, Enum):
    LIVE_PROVIDER = "LIVE_PROVIDER"
    PUBLIC_OPEN_DATA = "PUBLIC_OPEN_DATA"
    CACHED_PROVIDER = "CACHED_PROVIDER"
    OPERATOR_INPUT = "OPERATOR_INPUT"
    SEEDED_BASELINE = "SEEDED_BASELINE"
    DERIVED = "DERIVED"
    SIMULATED = "SIMULATED"
    OFFLINE_COMPUTED = "OFFLINE_COMPUTED"
    IMPORTED_DOCUMENT = "IMPORTED_DOCUMENT"
    UNAVAILABLE = "UNAVAILABLE"


class FreshnessState(str, Enum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AvailabilityState(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    UNKNOWN = "UNKNOWN"


class LineageRelationship(str, Enum):
    INPUT_TO = "INPUT_TO"
    DERIVED_FROM = "DERIVED_FROM"
    OVERRIDES = "OVERRIDES"
    EXCLUDED_FROM = "EXCLUDED_FROM"
    VALIDATES = "VALIDATES"
    REFERENCES = "REFERENCES"
    FALLBACK_FOR = "FALLBACK_FOR"


SOURCE_IDS = {
    "open_meteo": uuid.UUID("10000000-0000-0000-0000-000000000001"),
    "openweather": uuid.UUID("10000000-0000-0000-0000-000000000002"),
    "noaa_swpc": uuid.UUID("10000000-0000-0000-0000-000000000003"),
    "operator_input": uuid.UUID("10000000-0000-0000-0000-000000000004"),
    "demo_engineering": uuid.UUID("10000000-0000-0000-0000-000000000005"),
    "route_baseline": uuid.UUID("10000000-0000-0000-0000-000000000006"),
    "railradar": uuid.UUID("10000000-0000-0000-0000-000000000007"),
    "aisstream": uuid.UUID("10000000-0000-0000-0000-000000000008"),
    "maritime_feed": uuid.UUID("10000000-0000-0000-0000-000000000009"),
    "clearpath_derived": uuid.UUID("10000000-0000-0000-0000-000000000010"),
    "ixigo_partner": uuid.UUID("10000000-0000-0000-0000-000000000012"),
    "imported_engineering": uuid.UUID("10000000-0000-0000-0000-000000000013"),
}

FRESHNESS_POLICIES = {
    "open_meteo": (900, 1800, 3600),
    "openweather": (900, 1800, 3600),
    # Planetary Kp observations are three-hour bins; allow publication latency
    # without presenting an older bin as indefinitely current.
    "noaa_swpc": (14400, 21600, 32400),
    "railradar": (7200, 10800, 21600),
    "aisstream": (300, 600, 1200),
    "maritime_feed": (900, 1800, 3600),
    "ixigo_partner": (300, 900, 1800),
}

DECISION_INPUT_ROLES = {
    "CLEARANCE_DECISION",
    "WEATHER",
    "PORT_ALIGNMENT",
    "CONGESTION",
    "HISTORICAL_DELAY",
}

SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "jwt",
    "password",
    "secret",
    "service_role",
    "api_key",
    "access_token",
    "refresh_token",
    "database_url",
    "connection_string",
}


def normalize_source_state(raw_state: str | None) -> CanonicalSourceType:
    normalized = (raw_state or "").upper()
    if normalized in {"LIVE", "LIVE_AIS", "LIVE_FEED"}:
        return CanonicalSourceType.LIVE_PROVIDER
    if normalized in {"CACHED", "STALE_AIS"}:
        return CanonicalSourceType.CACHED_PROVIDER
    if normalized in {"OPERATOR_INPUT", "OPERATOR_DECLARED"}:
        return CanonicalSourceType.OPERATOR_INPUT
    if normalized in {"SEEDED", "SEEDED_BASELINE", "STATIC_ONLY", "DEMO_SCHEDULED"}:
        return CanonicalSourceType.SEEDED_BASELINE
    if normalized in {"SIMULATED"}:
        return CanonicalSourceType.SIMULATED
    if normalized in {"OFFLINE", "OFFLINE_COMPUTED"}:
        return CanonicalSourceType.OFFLINE_COMPUTED
    if normalized in {"UNAVAILABLE", "NOT_CONFIGURED", "PROVIDER-UNAVAILABLE"}:
        return CanonicalSourceType.UNAVAILABLE
    return CanonicalSourceType.DERIVED


def calculate_freshness(
    source_key: str,
    observed_at: datetime | None,
    fetched_at: datetime,
    now: datetime | None = None,
) -> tuple[FreshnessState, int | None]:
    if source_key in {
        "operator_input",
        "imported_engineering",
        "demo_engineering",
        "route_baseline",
        "clearpath_derived",
    }:
        return FreshnessState.NOT_APPLICABLE, None
    if observed_at is None:
        return FreshnessState.UNKNOWN, None
    now = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    age = int((now - observed_at).total_seconds())
    if age < -300:
        return FreshnessState.UNKNOWN, None
    age = max(0, age)
    fresh, aging, stale = FRESHNESS_POLICIES.get(source_key, (900, 1800, 3600))
    if age <= fresh:
        return FreshnessState.FRESH, age
    if age <= aging:
        return FreshnessState.AGING, age
    if age > stale:
        return FreshnessState.STALE, age
    return FreshnessState.AGING, age


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (datetime, uuid.UUID, Decimal, Enum)):
        return str(value.value if isinstance(value, Enum) else value)
    if isinstance(value, float):
        return round(value, 6)
    return value


def redact_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(sensitive in lowered for sensitive in SENSITIVE_KEYS):
                clean[str(key)] = "[REDACTED]"
            else:
                clean[str(key)] = redact_metadata(item)
        return clean
    if isinstance(value, list):
        return [redact_metadata(item) for item in value]
    return _json_safe(value)


def stable_checksum(value: Any) -> str:
    safe = redact_metadata(value)
    canonical = json.dumps(safe, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("certification timestamp must include a timezone")
    return value.astimezone(timezone.utc).isoformat()


def engineering_evidence_payload(
    limits: dict[str, Any],
    *,
    source_type: str,
    source_reference: str,
    certified_by: str,
    certified_at: datetime,
) -> dict[str, Any]:
    """Canonical engineering envelope; certification is part of its digest."""

    return {
        **limits,
        "certification": {
            "source_type": source_type.strip().upper(),
            "source_reference": source_reference.strip(),
            "certified_by": certified_by.strip(),
            "certified_at": _canonical_datetime(certified_at),
        },
    }


def record_integrity_payload(record: ProvenanceRecord) -> dict[str, Any]:
    """Canonical envelope for every field that changes evidence trust."""

    return {
        "id": record.id,
        "user_id": record.user_id,
        "route_id": record.route_id,
        "decision_snapshot_id": record.decision_snapshot_id,
        "source_id": record.source_id,
        "entity_type": record.entity_type,
        "entity_key": record.entity_key,
        "decision_input_role": record.decision_input_role,
        "canonical_source_type": record.canonical_source_type,
        "raw_source_state": record.raw_source_state,
        "observed_at": record.observed_at,
        "fetched_at": record.fetched_at,
        "valid_until": record.valid_until,
        "freshness_state_at_capture": record.freshness_state,
        "cache_hit": record.cache_hit,
        "used_in_decision": record.used_in_decision,
        "excluded_reason": record.excluded_reason,
        "availability_state": record.availability_state,
        "confidence": record.confidence,
        "completeness": record.completeness,
        "transform_name": record.transform_name,
        "transform_version": record.transform_version,
        "formula_reference": record.formula_reference,
        "request_id": record.request_id,
        "value_checksum": record.checksum,
        "value_summary": record.value_summary,
        "metadata": record.metadata_json,
    }


def snapshot_integrity_payload(snapshot: RouteDecisionSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.id,
        "created_at": _canonical_datetime(snapshot.created_at),
        "route_id": snapshot.route_id,
        "user_id": snapshot.user_id,
        "request_id": snapshot.request_id,
        "versions": {
            "decision": snapshot.decision_engine_version,
            "routing": snapshot.routing_algorithm_version,
            "scoring": snapshot.scoring_version,
            "clearance": snapshot.clearance_engine_version,
        },
        "source_code": snapshot.source_code,
        "destination_code": snapshot.destination_code,
        "cargo_request": snapshot.cargo_request,
        "route_segment_ids": snapshot.route_segment_ids,
        "clearance_state": snapshot.clearance_state,
        "blocking_segment_id": snapshot.blocking_segment_id,
        "reliability_score": snapshot.reliability_score,
        "estimated_hours": snapshot.estimated_hours,
        "score_breakdown": snapshot.score_breakdown,
        "applied_weights": snapshot.applied_weights,
        "excluded_factors": snapshot.excluded_factors,
        "environmental_alerts": snapshot.environmental_alerts,
        "traceability_summary": snapshot.traceability_summary,
        "final_response_summary": snapshot.final_response_summary,
    }


def evidence_root_payload(
    snapshot: RouteDecisionSnapshot,
    records: list[ProvenanceRecord],
    edges: list[LineageEdge],
) -> dict[str, Any]:
    return {
        "snapshot": snapshot_integrity_payload(snapshot),
        "records": [
            {
                "id": record.id,
                "integrity_checksum": stable_checksum(record_integrity_payload(record)),
            }
            for record in sorted(records, key=lambda item: str(item.id))
        ],
        "edges": [
            {
                "parent_record_id": edge.parent_record_id,
                "child_record_id": edge.child_record_id,
                "relationship": edge.relationship,
            }
            for edge in sorted(
                edges,
                key=lambda item: (
                    str(item.parent_record_id),
                    str(item.child_record_id),
                    item.relationship,
                ),
            )
        ],
    }


def _active_evidence_signer() -> tuple[str, str, str]:
    return (
        settings.EVIDENCE_SIGNING_KEY_ID.strip(),
        settings.EVIDENCE_SIGNING_ALGORITHM,
        settings.EVIDENCE_SIGNING_KEY,
    )


def _verification_key(key_id: str, algorithm: str) -> str | None:
    if algorithm != "HMAC-SHA256" or not key_id:
        return None
    active_id, active_algorithm, active_key = _active_evidence_signer()
    if key_id == active_id and algorithm == active_algorithm:
        return active_key if len(active_key) >= 32 else None
    retained = settings.EVIDENCE_VERIFICATION_KEYS.get(key_id)
    return retained if retained and len(retained) >= 32 else None


def sign_evidence_root(
    root_checksum: str,
    *,
    key_id: str | None = None,
    algorithm: str | None = None,
) -> str:
    active_id, active_algorithm, active_key = _active_evidence_signer()
    selected_id = key_id or active_id
    selected_algorithm = algorithm or active_algorithm
    key = (
        active_key
        if selected_id == active_id and selected_algorithm == active_algorithm
        else _verification_key(selected_id, selected_algorithm)
    )
    if key is None or len(key) < 32:
        raise RuntimeError(
            "EVIDENCE_SIGNING_KEY is missing or unknown for the requested key ID"
        )
    if selected_algorithm != "HMAC-SHA256":
        raise RuntimeError("Unsupported evidence signing algorithm")
    return hmac.new(
        key.encode("utf-8"),
        root_checksum.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def seal_decision_evidence(
    snapshot: RouteDecisionSnapshot,
    records: list[ProvenanceRecord],
    edges: list[LineageEdge],
) -> str:
    """Seal record envelopes and the complete lineage graph before persistence."""

    for record in records:
        record.integrity_checksum = stable_checksum(record_integrity_payload(record))
    root = stable_checksum(evidence_root_payload(snapshot, records, edges))
    key_id, algorithm, _ = _active_evidence_signer()
    if not key_id:
        raise RuntimeError("EVIDENCE_SIGNING_KEY_ID must be configured before sealing")
    snapshot.evidence_root_checksum = root
    snapshot.evidence_root_key_id = key_id
    snapshot.evidence_root_algorithm = algorithm
    snapshot.evidence_root_signature = sign_evidence_root(
        root, key_id=key_id, algorithm=algorithm
    )
    return root


def verify_evidence_root(
    snapshot: RouteDecisionSnapshot,
    records: list[ProvenanceRecord],
    edges: list[LineageEdge],
) -> tuple[bool, str]:
    computed = stable_checksum(evidence_root_payload(snapshot, records, edges))
    key_id = getattr(snapshot, "evidence_root_key_id", None)
    algorithm = getattr(snapshot, "evidence_root_algorithm", None)
    if not key_id or not algorithm or _verification_key(key_id, algorithm) is None:
        return False, computed
    expected_signature = sign_evidence_root(computed, key_id=key_id, algorithm=algorithm)
    valid = bool(snapshot.evidence_root_checksum and snapshot.evidence_root_signature) and (
        hmac.compare_digest(snapshot.evidence_root_checksum, computed)
        and hmac.compare_digest(snapshot.evidence_root_signature, expected_signature)
    )
    return valid, computed


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _record(
    *,
    user_id: str,
    route_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    source_key: str,
    entity_type: str,
    entity_key: str,
    source_type: CanonicalSourceType,
    raw_state: str,
    value: dict,
    request_id: str | None,
    role: str | None = None,
    observed_at: datetime | None = None,
    fetched_at: datetime | None = None,
    valid_until: datetime | None = None,
    used: bool = False,
    excluded_reason: str | None = None,
    availability: AvailabilityState = AvailabilityState.AVAILABLE,
    transform_name: str | None = None,
    transform_version: str | None = None,
    formula_reference: str | None = None,
    metadata: dict | None = None,
) -> ProvenanceRecord:
    fetched_at = fetched_at or datetime.now(timezone.utc)
    freshness, age = calculate_freshness(source_key, observed_at, fetched_at)
    safe_value = redact_metadata(value)
    safe_metadata = redact_metadata(metadata or {})
    return ProvenanceRecord(
        id=uuid.uuid4(),
        user_id=user_id,
        route_id=route_id,
        decision_snapshot_id=snapshot_id,
        source_id=SOURCE_IDS[source_key],
        entity_type=entity_type,
        entity_key=entity_key,
        decision_input_role=role,
        canonical_source_type=source_type.value,
        raw_source_state=raw_state,
        observed_at=observed_at,
        fetched_at=fetched_at,
        valid_until=valid_until,
        freshness_state=freshness.value,
        freshness_seconds=age,
        cache_hit=source_type is CanonicalSourceType.CACHED_PROVIDER,
        used_in_decision=used,
        excluded_reason=excluded_reason,
        availability_state=availability.value,
        completeness=1.0 if safe_value else 0.0,
        transform_name=transform_name,
        transform_version=transform_version,
        formula_reference=formula_reference,
        request_id=request_id,
        checksum=stable_checksum(safe_value),
        value_summary=safe_value,
        metadata_json=safe_metadata,
    )


def calculate_traceability_summary(
    records: list[ProvenanceRecord],
    snapshot_id: uuid.UUID,
    warnings: list[str] | None = None,
) -> ProvenanceSummary:
    traced_roles = {
        record.decision_input_role
        for record in records
        if record.decision_input_role in DECISION_INPUT_ROLES
        and record.fetched_at is not None
        and bool(record.value_summary)
        and (record.source_id is not None or record.canonical_source_type == "UNAVAILABLE")
    }
    total = len(DECISION_INPUT_ROLES)
    traced = len(traced_roles)

    freshness = FreshnessCounts()
    source_modes = SourceModeCounts()
    use = DecisionUseCounts()
    for record in records:
        freshness_key = record.freshness_state.lower()
        if hasattr(freshness, freshness_key):
            setattr(freshness, freshness_key, getattr(freshness, freshness_key) + 1)
        source_key = record.canonical_source_type.lower()
        if hasattr(source_modes, source_key):
            setattr(source_modes, source_key, getattr(source_modes, source_key) + 1)
        decision_use = record.metadata_json.get("decision_use")
        if decision_use and hasattr(use, decision_use):
            setattr(use, decision_use, getattr(use, decision_use) + 1)
        elif record.used_in_decision:
            use.included += 1
        elif record.excluded_reason:
            use.excluded += 1
        else:
            use.informational += 1

    return ProvenanceSummary(
        decision_record_id=snapshot_id,
        traceability=TraceabilityCounts(
            traced=traced,
            total=total,
            coverage_pct=round((traced / total * 100.0) if total else 100.0, 1),
        ),
        freshness=freshness,
        source_modes=source_modes,
        decision_use=use,
        warnings=list(dict.fromkeys(warnings or [])),
    )


async def capture_route_decision(
    db: AsyncSession,
    *,
    route: Any,
    user_id: str,
    request_id: str | None,
    cargo: dict[str, float],
    segments: list[Any],
    clearance: dict[str, Any],
    weather_data: dict[str, Any],
    kp_data: dict[str, Any],
    weather_score: float | None,
    port_sync: Any,
    congestion: Any,
    historical_score: float,
    reliability: int,
    estimated_hours: float | None,
    applied_weights: dict[str, float],
    alerts: list[str],
) -> ProvenanceSummary:
    """Persist one immutable evidence set in the caller's route transaction."""
    now = datetime.now(timezone.utc)
    snapshot_id = uuid.uuid4()
    route_id = route.id
    key = f"route:{route_id}"
    warnings: list[str] = []
    records: list[ProvenanceRecord] = []
    edges: list[LineageEdge] = []

    cargo_record = _record(
        user_id=user_id,
        route_id=route_id,
        snapshot_id=snapshot_id,
        source_key="operator_input",
        entity_type="CARGO_DECLARATION",
        entity_key=f"{key}:cargo",
        source_type=CanonicalSourceType.OPERATOR_INPUT,
        raw_state="OPERATOR_INPUT",
        value=cargo,
        request_id=request_id,
        used=True,
        metadata={"decision_use": "hard_constraints"},
    )
    engineering_segments = []
    trusted_engineering_types = {"OPERATOR_INPUT", "IMPORTED_DOCUMENT"}
    for segment in segments:
        geometry = []
        if getattr(segment, "geom_path", None) is not None:
            geometry = [
                [round(float(lon), 7), round(float(lat), 7)]
                for lon, lat in to_shape(segment.geom_path).coords
            ]
        limits = {
            "id": str(segment.id),
            "source_code": getattr(getattr(segment, "source_station", None), "code", None),
            "destination_code": getattr(
                getattr(segment, "dest_station", None), "code", None
            ),
            "max_height": float(segment.max_height_clearance),
            "max_width": float(segment.max_width_clearance),
            "max_weight": float(segment.max_weight_capacity),
            "congestion_factor": float(segment.congestion_factor),
            "historical_delay_hours": float(segment.historical_delay_hours),
            "geometry_lon_lat": geometry,
        }
        source_type = str(
            getattr(segment, "engineering_source_type", "SEEDED_BASELINE")
            or "SEEDED_BASELINE"
        ).upper()
        declared_checksum = getattr(segment, "engineering_checksum", None)
        source_reference = getattr(segment, "engineering_source_reference", None)
        certified_at = getattr(segment, "engineering_certified_at", None)
        certified_by = getattr(segment, "engineering_certified_by", None)
        certification_payload = None
        if source_reference and certified_at and certified_by:
            try:
                certification_payload = engineering_evidence_payload(
                    limits,
                    source_type=source_type,
                    source_reference=source_reference,
                    certified_by=certified_by,
                    certified_at=certified_at,
                )
            except ValueError:
                certification_payload = None
        computed_checksum = (
            stable_checksum(certification_payload) if certification_payload else None
        )
        allowed_issuers = {
            issuer.strip().casefold()
            for issuer in settings.ENGINEERING_CERTIFICATION_ALLOWED_ISSUERS
            if issuer.strip()
        }
        certification_not_future = bool(
            certified_at
            and certified_at.tzinfo
            and certified_at <= datetime.now(timezone.utc)
        )
        verified = bool(
            source_type in trusted_engineering_types
            and source_reference
            and certified_at
            and certified_by
            and certified_by.strip().casefold() in allowed_issuers
            and certification_not_future
            and declared_checksum == computed_checksum
        )
        engineering_segments.append(
            {
                **limits,
                "source_type": source_type,
                "source_reference": source_reference,
                "certified_at": certified_at,
                "certified_by": certified_by,
                "declared_checksum": declared_checksum,
                "computed_checksum": computed_checksum,
                "verified": verified,
            }
        )
    engineering_verified = bool(engineering_segments) and all(
        item["verified"] for item in engineering_segments
    )
    if not engineering_verified:
        warnings.extend(
            [
            "Engineering clearance values are not backed by a checksum-verified certified import.",
            "Static congestion and historical-delay values are seeded operational baselines.",
            ]
        )
    engineering_types = {item["source_type"] for item in engineering_segments}
    engineering_source_type = (
        CanonicalSourceType.OPERATOR_INPUT
        if engineering_verified and engineering_types == {"OPERATOR_INPUT"}
        else CanonicalSourceType.IMPORTED_DOCUMENT
        if engineering_verified
        else CanonicalSourceType.SEEDED_BASELINE
    )
    engineering_value = {
        "segments": engineering_segments,
        "certification": "VERIFIED" if engineering_verified else "NOT_VERIFIED",
    }
    engineering_record = _record(
        user_id=user_id,
        route_id=route_id,
        snapshot_id=snapshot_id,
        source_key=(
            "operator_input"
            if engineering_source_type is CanonicalSourceType.OPERATOR_INPUT
            else "imported_engineering"
            if engineering_verified
            else "demo_engineering"
        ),
        entity_type="ENGINEERING_LIMITS",
        entity_key=f"{key}:engineering",
        source_type=engineering_source_type,
        raw_state="VERIFIED_ENGINEERING_IMPORT" if engineering_verified else "SEEDED_BASELINE",
        value=engineering_value,
        request_id=request_id,
        used=True,
        metadata={
            "decision_use": "hard_constraints",
            "verified": engineering_verified,
            "references": [
                item["source_reference"]
                for item in engineering_segments
                if item["source_reference"]
            ],
        },
    )
    clearance_record = _record(
        user_id=user_id,
        route_id=route_id,
        snapshot_id=snapshot_id,
        source_key="clearpath_derived",
        entity_type="CLEARANCE_RESULT",
        entity_key=f"{key}:clearance",
        source_type=CanonicalSourceType.DERIVED,
        raw_state="DERIVED",
        value={
            "status": clearance["status"],
            "blocking_segment_id": clearance.get("blocking_segment_id"),
        },
        request_id=request_id,
        role="CLEARANCE_DECISION",
        used=True,
        transform_name="cargo_clearance",
        transform_version="1.0.0",
        formula_reference="CLEARANCE_HEIGHT_WIDTH_WEIGHT_V1",
        metadata={"decision_use": "hard_constraints"},
    )
    records.extend([cargo_record, engineering_record, clearance_record])
    edges.extend(
        [
            LineageEdge(
                parent_record_id=cargo_record.id,
                child_record_id=clearance_record.id,
                relationship="INPUT_TO",
            ),
            LineageEdge(
                parent_record_id=engineering_record.id,
                child_record_id=clearance_record.id,
                relationship="VALIDATES",
            ),
        ]
    )

    weather_meta = weather_data.get("_provenance", {}) if isinstance(weather_data, dict) else {}
    weather_provider_unavailable = weather_data.get("status") == "unavailable"
    weather_unavailable = weather_score is None
    weather_provider = weather_meta.get("provider") or (
        "openweather" if weather_meta.get("adapter") == "openweather" else "open_meteo"
    )
    weather_raw_state = weather_meta.get("raw_state") or (
        "UNAVAILABLE" if weather_provider_unavailable else "LIVE"
    )
    weather_type = normalize_source_state(weather_raw_state)
    weather_observed = _parse_time(weather_meta.get("observed_at"))
    weather_fetched = _parse_time(weather_meta.get("fetched_at")) or now
    raw_weather = _record(
        user_id=user_id,
        route_id=route_id,
        snapshot_id=snapshot_id,
        source_key=weather_provider,
        entity_type="WEATHER_OBSERVATION",
        entity_key=f"{key}:weather-observation",
        source_type=weather_type,
        raw_state=weather_raw_state,
        value={k: v for k, v in weather_data.items() if k != "_provenance"},
        request_id=request_id,
        observed_at=weather_observed,
        fetched_at=weather_fetched,
        used=not weather_provider_unavailable,
        excluded_reason="Provider unavailable; weather factor excluded from scoring"
        if weather_provider_unavailable
        else None,
        availability=AvailabilityState.UNAVAILABLE
        if weather_provider_unavailable
        else AvailabilityState.AVAILABLE,
        metadata={
            "decision_use": "excluded" if weather_provider_unavailable else "included"
        },
    )
    weather_score_record = _record(
        user_id=user_id,
        route_id=route_id,
        snapshot_id=snapshot_id,
        source_key="clearpath_derived",
        entity_type="WEATHER_SCORE",
        entity_key=f"{key}:weather-score",
        source_type=CanonicalSourceType.DERIVED,
        raw_state="UNAVAILABLE" if weather_unavailable else "DERIVED",
        value={
            "score": weather_score,
            "provider_unavailable": weather_unavailable,
            "weight": applied_weights.get("weather"),
        },
        request_id=request_id,
        role="WEATHER",
        used=not weather_unavailable,
        excluded_reason=(
            "Provider unavailable; weather factor excluded and weights renormalized"
            if weather_unavailable
            else None
        ),
        availability=(
            AvailabilityState.UNAVAILABLE
            if weather_unavailable
            else AvailabilityState.AVAILABLE
        ),
        transform_name="weather_to_score",
        transform_version="1.0.0",
        formula_reference="RRI_WEATHER_V1",
        metadata={"decision_use": "excluded" if weather_unavailable else "included"},
    )
    records.extend([raw_weather, weather_score_record])
    edges.append(
        LineageEdge(
            parent_record_id=raw_weather.id,
            child_record_id=weather_score_record.id,
            relationship="DERIVED_FROM",
        )
    )
    if weather_unavailable:
        warnings.append(
            "Weather or NOAA space-weather evidence unavailable; the weather factor was excluded "
            "and RRI weights were renormalized."
        )

    kp_unavailable = kp_data.get("status") == "unavailable"
    kp_meta = kp_data.get("_provenance", {}) if isinstance(kp_data, dict) else {}
    kp_record = _record(
        user_id=user_id,
        route_id=route_id,
        snapshot_id=snapshot_id,
        source_key="noaa_swpc",
        entity_type="SPACE_WEATHER_OBSERVATION",
        entity_key=f"{key}:space-weather",
        source_type=normalize_source_state(
            kp_meta.get("raw_state") or ("UNAVAILABLE" if kp_unavailable else "LIVE")
        ),
        raw_state=kp_meta.get("raw_state") or ("UNAVAILABLE" if kp_unavailable else "LIVE"),
        value={"kp_index": kp_data.get("kp_index"), "alert_level": kp_data.get("alert_level")},
        request_id=request_id,
        observed_at=_parse_time(kp_data.get("issue_datetime")),
        fetched_at=_parse_time(kp_meta.get("fetched_at")) or now,
        used=not kp_unavailable,
        excluded_reason="NOAA feed unavailable; telemetry risk unknown" if kp_unavailable else None,
        availability=AvailabilityState.UNAVAILABLE
        if kp_unavailable
        else AvailabilityState.AVAILABLE,
        metadata={"decision_use": "informational" if kp_unavailable else "included"},
    )
    records.append(kp_record)
    edges.append(
        LineageEdge(
            parent_record_id=kp_record.id,
            child_record_id=weather_score_record.id,
            relationship="INPUT_TO",
        )
    )

    port_source = str(
        port_sync.source.value if hasattr(port_sync.source, "value") else port_sync.source
    )
    port_available = bool(port_sync.available)
    port_source_key = "operator_input" if port_source == "OPERATOR_INPUT" else "maritime_feed"
    port_type = normalize_source_state(port_source if port_available else "UNAVAILABLE")
    port_record = _record(
        user_id=user_id,
        route_id=route_id,
        snapshot_id=snapshot_id,
        source_key=port_source_key,
        entity_type="PORT_ALIGNMENT_SCORE",
        entity_key=f"{key}:port",
        source_type=port_type,
        raw_state=port_source,
        value={
            "score": port_sync.score if port_available else None,
            "available": port_available,
            "aligned": port_sync.aligned,
            "port_id": port_sync.port_id,
            "vessel_id": port_sync.vessel_id,
            "evaluated_at": port_sync.evaluated_at,
            "train_arrival_hours": port_sync.train_arrival_hours,
            "estimated_train_arrival_at": (
                port_sync.evaluated_at
                + timedelta(hours=port_sync.train_arrival_hours)
                if port_sync.evaluated_at is not None
                and port_sync.train_arrival_hours is not None
                else None
            ),
            "loading_window": {
                "start": port_sync.window.start,
                "end": port_sync.window.end,
                "manifest_reference": port_sync.manifest_reference,
                "manifest_sha256": port_sync.manifest_sha256,
            }
            if port_sync.window
            else None,
            "berth_id": port_sync.berth_id,
            "vessel_status": port_sync.vessel_status,
            "weight": applied_weights.get("port"),
        },
        request_id=request_id,
        role="PORT_ALIGNMENT",
        observed_at=port_sync.observed_at or port_sync.evaluated_at,
        fetched_at=port_sync.fetched_at or port_sync.evaluated_at or now,
        valid_until=(port_sync.valid_until or port_sync.window.end)
        if port_sync.window
        else None,
        used=port_available,
        excluded_reason=None
        if port_available
        else "No verified berth window; factor excluded and weights renormalized",
        availability=AvailabilityState.AVAILABLE
        if port_available
        else AvailabilityState.NOT_CONFIGURED,
        transform_name="port_sync",
        transform_version="1.0.0",
        formula_reference="PORT_ALIGNMENT_V1",
        metadata={"decision_use": "included" if port_available else "excluded"},
    )
    records.append(port_record)
    if not port_available:
        warnings.append(
            "Port alignment was unavailable and excluded; RRI weights were renormalized."
        )

    static_record = _record(
        user_id=user_id,
        route_id=route_id,
        snapshot_id=snapshot_id,
        source_key=(
            "operator_input"
            if engineering_source_type is CanonicalSourceType.OPERATOR_INPUT
            else "imported_engineering"
            if engineering_verified
            else "route_baseline"
        ),
        entity_type="CONGESTION_BASELINE",
        entity_key=f"{key}:congestion-baseline",
        source_type=engineering_source_type,
        raw_state="VERIFIED_ENGINEERING_IMPORT" if engineering_verified else "SEEDED_BASELINE",
        value={
            "score": congestion.static_score,
            "segment_factors": [float(s.congestion_factor) for s in segments],
        },
        request_id=request_id,
        used=True,
        metadata={"decision_use": "included"},
    )
    congestion_parents = [static_record]
    if congestion.live_rail_score is not None:
        rail_state = str(congestion.detail.get("rail_source", "LIVE"))
        congestion_parents.append(
            _record(
                user_id=user_id,
                route_id=route_id,
                snapshot_id=snapshot_id,
                source_key="railradar",
                entity_type="RAIL_CONGESTION_SIGNAL",
                entity_key=f"{key}:rail-congestion",
                source_type=normalize_source_state(rail_state),
                raw_state=rail_state,
                value={
                    "score": congestion.live_rail_score,
                    "stations_live": congestion.detail.get("stations_live"),
                    "stations_total": congestion.detail.get("stations_total"),
                },
                request_id=request_id,
                observed_at=_parse_time(congestion.detail.get("rail_observed_at")),
                fetched_at=_parse_time(congestion.detail.get("rail_fetched_at")) or now,
                used=True,
                metadata={
                    "decision_use": "included",
                    "authority": "SECONDARY_NON_OFFICIAL_PASSENGER",
                },
            )
        )
    if congestion.port_congestion_pct is not None:
        ais_state = str(congestion.detail.get("port_source") or "UNAVAILABLE")
        congestion_parents.append(
            _record(
                user_id=user_id,
                route_id=route_id,
                snapshot_id=snapshot_id,
                source_key="aisstream",
                entity_type="AIS_PORT_ACTIVITY",
                entity_key=f"{key}:ais",
                source_type=normalize_source_state(ais_state),
                raw_state=ais_state,
                value={
                    "congestion_pct": congestion.port_congestion_pct,
                    "penalty": congestion.port_penalty,
                },
                request_id=request_id,
                observed_at=_parse_time(congestion.detail.get("port_observed_at")),
                used=True,
                metadata={
                    "decision_use": "included",
                    "limitation": "AIS activity is not a berth schedule",
                },
            )
        )
    congestion_record = _record(
        user_id=user_id,
        route_id=route_id,
        snapshot_id=snapshot_id,
        source_key="clearpath_derived",
        entity_type="CONGESTION_SCORE",
        entity_key=f"{key}:congestion",
        source_type=CanonicalSourceType.DERIVED,
        raw_state=str(congestion.source.value),
        value={
            "score": congestion.score,
            "static_score": congestion.static_score,
            "live_rail_score": congestion.live_rail_score,
            "live_weight": congestion.live_weight,
            "port_penalty": congestion.port_penalty,
            "weight": applied_weights.get("congestion"),
        },
        request_id=request_id,
        role="CONGESTION",
        used=True,
        transform_name="congestion_blend",
        transform_version="1.0.0",
        formula_reference="CONGESTION_BLEND_V1",
        metadata={"decision_use": "included"},
    )
    records.extend(congestion_parents + [congestion_record])
    edges.extend(
        LineageEdge(
            parent_record_id=p.id, child_record_id=congestion_record.id, relationship="DERIVED_FROM"
        )
        for p in congestion_parents
    )

    historical_record = _record(
        user_id=user_id,
        route_id=route_id,
        snapshot_id=snapshot_id,
        source_key=(
            "operator_input"
            if engineering_source_type is CanonicalSourceType.OPERATOR_INPUT
            else "imported_engineering"
            if engineering_verified
            else "route_baseline"
        ),
        entity_type="HISTORICAL_DELAY_SCORE",
        entity_key=f"{key}:historical",
        source_type=engineering_source_type,
        raw_state="VERIFIED_ENGINEERING_IMPORT" if engineering_verified else "SEEDED_BASELINE",
        value={
            "score": historical_score,
            "segment_delay_hours": [float(s.historical_delay_hours) for s in segments],
            "weight": applied_weights.get("historical"),
        },
        request_id=request_id,
        role="HISTORICAL_DELAY",
        used=True,
        transform_name="historical_delay_aggregation",
        transform_version="1.0.0",
        formula_reference="HISTORICAL_DELAY_V1",
        metadata={"decision_use": "included"},
    )
    records.append(historical_record)

    rri_record = _record(
        user_id=user_id,
        route_id=route_id,
        snapshot_id=snapshot_id,
        source_key="clearpath_derived",
        entity_type="FINAL_RRI",
        entity_key=f"{key}:rri",
        source_type=CanonicalSourceType.DERIVED,
        raw_state="DERIVED",
        value={
            "score": reliability,
            "applied_weights": applied_weights,
            "clearance_override": clearance["status"] == "HARD_BLOCKED",
        },
        request_id=request_id,
        used=True,
        transform_name="route_reliability_index",
        transform_version="1.0.0",
        formula_reference="RRI_V1",
        metadata={"decision_use": "included"},
    )
    records.append(rri_record)
    for parent in (weather_score_record, congestion_record, historical_record):
        edges.append(
            LineageEdge(
                parent_record_id=parent.id, child_record_id=rri_record.id, relationship="INPUT_TO"
            )
        )
    edges.append(
        LineageEdge(
            parent_record_id=port_record.id,
            child_record_id=rri_record.id,
            relationship="INPUT_TO" if port_available else "EXCLUDED_FROM",
        )
    )
    if clearance["status"] == "HARD_BLOCKED":
        edges.append(
            LineageEdge(
                parent_record_id=clearance_record.id,
                child_record_id=rri_record.id,
                relationship="OVERRIDES",
            )
        )

    summary = calculate_traceability_summary(records, snapshot_id, warnings)
    excluded = []
    if weather_unavailable:
        excluded.append("weather")
    if not port_available:
        excluded.append("port")
    snapshot = RouteDecisionSnapshot(
        id=snapshot_id,
        created_at=now,
        route_id=route_id,
        user_id=user_id,
        request_id=request_id,
        decision_engine_version="5.0.0",
        routing_algorithm_version="DIJKSTRA_V1",
        scoring_version="RRI_V1",
        clearance_engine_version="CLEARANCE_V1",
        source_code=route.source_station_code,
        destination_code=route.dest_station_code,
        cargo_request=redact_metadata(cargo),
        route_segment_ids=[str(s.id) for s in segments],
        clearance_state=clearance["status"],
        blocking_segment_id=clearance.get("blocking_segment_id"),
        reliability_score=reliability,
        estimated_hours=estimated_hours,
        score_breakdown={
            "weather": weather_score,
            "port": port_sync.score if port_available else None,
            "congestion": congestion.score,
            "historical": historical_score,
        },
        applied_weights=applied_weights,
        excluded_factors=excluded,
        environmental_alerts=alerts,
        traceability_summary=summary.model_dump(mode="json"),
        final_response_summary={
            "route_id": str(route_id),
            "status": clearance["status"],
            "reliability_score": reliability,
            "estimated_hours": estimated_hours,
        },
    )
    seal_decision_evidence(snapshot, records, edges)
    db.add(snapshot)
    db.add_all(records)
    db.add_all(edges)
    await db.flush()
    return summary
