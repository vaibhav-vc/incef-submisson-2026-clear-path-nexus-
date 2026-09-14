"""Fail-closed speed-risk advisory calculations.

The service consumes real source envelopes supplied by an authorized caller.
It does not call a provider, invent a speed restriction, or issue a control
command.  Missing, stale, future-dated, or non-authoritative inputs result in
an unavailable/hold response with no numeric speed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.speed import (
    SpeedEvidenceSummary,
    SpeedRiskAdvisoryRequest,
    SpeedRiskAdvisoryResponse,
)


REQUIRED_CATEGORIES = {"ROUTE_LIMIT", "HEADWAY"}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _freshness(
    evaluation_at: datetime,
    observed_at: datetime,
    fetched_at: datetime,
    valid_until: datetime,
    source_type: str | None = None,
) -> str:
    evaluation = _utc(evaluation_at)
    if str(source_type or "").upper() in {"REAL_HISTORICAL", "REPLAYED_SNAPSHOT"}:
        return "EXPIRED"
    observed = _utc(observed_at)
    valid_until = _utc(valid_until)
    # A source cannot be used before it was observed or fetched.  Treating a
    # future-dated fetch as current would allow clock/fixture errors to leak a
    # value into an operational decision.
    if observed > evaluation or _utc(fetched_at) > evaluation:
        return "FUTURE"
    if valid_until < evaluation:
        return "EXPIRED"
    return "CURRENT"


def _constraint_summary(item, evaluation_at: datetime, *, used: bool, reason: str | None = None):
    evidence = item.evidence
    return SpeedEvidenceSummary(
        category=item.category,
        label=item.label,
        limit_kph=item.limit_kph,
        source_key=evidence.source_key,
        source_type=evidence.source_type,
        authority_level=evidence.authority_level,
        source_reference=evidence.source_reference,
        observed_at=evidence.observed_at,
        fetched_at=evidence.fetched_at,
        valid_until=evidence.valid_until,
        freshness=_freshness(
            evaluation_at,
            evidence.observed_at,
            evidence.fetched_at,
            evidence.valid_until,
            evidence.source_type,
        ),
        used_in_decision=used,
        excluded_reason=reason,
        checksum=evidence.checksum,
    )


def _brake_summary(payload: SpeedRiskAdvisoryRequest, *, used: bool, reason: str | None = None):
    if payload.braking is None:
        return None
    evidence = payload.braking.evidence
    return SpeedEvidenceSummary(
        category="BRAKING",
        label="Consist braking performance",
        limit_kph=None,
        source_key=evidence.source_key,
        source_type=evidence.source_type,
        authority_level=evidence.authority_level,
        source_reference=evidence.source_reference,
        observed_at=evidence.observed_at,
        fetched_at=evidence.fetched_at,
        valid_until=evidence.valid_until,
        freshness=_freshness(
            payload.evaluation_at,
            evidence.observed_at,
            evidence.fetched_at,
            evidence.valid_until,
            evidence.source_type,
        ),
        used_in_decision=used,
        excluded_reason=reason,
        checksum=evidence.checksum,
    )


def calculate_stopping_distance_meters(
    speed_kph: float,
    reaction_time_seconds: float,
    effective_deceleration_mps2: float,
    safety_margin_meters: float,
) -> float:
    """Calculate a transparent advisory stopping-distance estimate."""

    speed_mps = speed_kph / 3.6
    return round(
        speed_mps * reaction_time_seconds
        + (speed_mps * speed_mps) / (2 * effective_deceleration_mps2)
        + safety_margin_meters,
        2,
    )


def calculate_speed_risk_advisory(
    payload: SpeedRiskAdvisoryRequest,
) -> SpeedRiskAdvisoryResponse:
    """Return an evidence-backed advisory or a truthful no-number result."""

    evaluation_at = _utc(payload.evaluation_at)
    summaries: list[SpeedEvidenceSummary] = []
    usable: list[tuple[object, float]] = []
    reasons: list[str] = []
    warnings: list[str] = []

    if not payload.constraints:
        reasons.append("No real route, restriction, geometry, or headway constraints were supplied")

    for item in payload.constraints:
        freshness = _freshness(
            evaluation_at,
            item.evidence.observed_at,
            item.evidence.fetched_at,
            item.evidence.valid_until,
            item.evidence.source_type,
        )
        is_authoritative = item.evidence.authority_level == "AUTHORITATIVE"
        usable_item = freshness == "CURRENT" and is_authoritative
        reason = None
        if freshness != "CURRENT":
            reason = f"Source evidence is {freshness.lower()} at evaluation time"
        elif not is_authoritative:
            reason = "Supplementary/operator-declared evidence cannot establish an operational cap"
        required = item.category in REQUIRED_CATEGORIES
        if usable_item:
            usable.append((item, item.limit_kph))
        elif required:
            reasons.append(f"{item.label}: {reason}")
        else:
            # Optional environmental/geometry observations are retained for
            # traceability but cannot block a result merely because they are
            # supplementary or unavailable.  They also cannot lower the
            # advisory speed unless an authority explicitly supplies them.
            warnings.append(f"{item.label}: {reason}")
        summaries.append(_constraint_summary(item, evaluation_at, used=usable_item, reason=reason))

    if payload.braking is None:
        reasons.append("Authoritative consist braking evidence is missing")
        brake = None
    else:
        brake_freshness = _freshness(
            evaluation_at,
            payload.braking.evidence.observed_at,
            payload.braking.evidence.fetched_at,
            payload.braking.evidence.valid_until,
            payload.braking.evidence.source_type,
        )
        brake = payload.braking
        brake_usable = brake_freshness == "CURRENT"
        brake_reason = None if brake_usable else f"Source evidence is {brake_freshness.lower()} at evaluation time"
        if not brake_usable:
            reasons.append(f"Consist braking performance: {brake_reason}")
        summaries.append(_brake_summary(payload, used=brake_usable, reason=brake_reason))

    categories = {item.category for item, _ in usable}
    missing = REQUIRED_CATEGORIES - categories
    if missing:
        reasons.append(
            "Authoritative evidence is missing for: " + ", ".join(sorted(missing))
        )
    if brake is None or not summaries[-1].used_in_decision:
        reasons.append("A numeric advisory is withheld until current braking evidence is available")

    if reasons:
        deduplicated = list(dict.fromkeys(reasons))
        return SpeedRiskAdvisoryResponse(
            status="UNAVAILABLE" if not payload.constraints or payload.braking is None else "HOLD",
            advisory_speed_kph=None,
            stopping_distance_meters=None,
            limiting_constraint=None,
            corridor_reference=payload.corridor_reference,
            evaluation_at=evaluation_at,
            consist_manifest_checksum=payload.consist_manifest_checksum,
            evidence=summaries,
            warnings=list(dict.fromkeys(deduplicated + warnings)),
        )

    limiting_item, advisory_speed = min(usable, key=lambda pair: pair[1])
    stopping_distance = calculate_stopping_distance_meters(
        advisory_speed,
        brake.reaction_time_seconds,
        brake.effective_deceleration_mps2,
        brake.safety_margin_meters,
    )
    return SpeedRiskAdvisoryResponse(
        status="ADVISORY",
        advisory_speed_kph=round(advisory_speed, 2),
        stopping_distance_meters=stopping_distance,
        limiting_constraint=limiting_item.label,
        corridor_reference=payload.corridor_reference,
        evaluation_at=evaluation_at,
        consist_manifest_checksum=payload.consist_manifest_checksum,
        evidence=summaries,
        warnings=list(dict.fromkeys(warnings + [
            "Confirm the current authorized timetable, block state, train formation, and railway rules before any movement decision"
        ])),
    )
