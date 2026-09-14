"""Contracts for the evidence-backed speed-risk advisory.

This module deliberately contains no default railway values.  A speed number is
only calculated when the caller supplies current, traceable evidence for the
route limit, train braking performance, and the relevant headway/block rule.
The response is an operational advisory, never movement authority.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


RealSourceType = Literal[
    "LIVE_PROVIDER",
    "AUTHORIZED_FEED",
    "PUBLIC_OPEN_DATA",
    "CACHED_PROVIDER",
    "OPERATOR_INPUT",
    "IMPORTED_DOCUMENT",
    "REAL_HISTORICAL",
    "REPLAYED_SNAPSHOT",
]
AuthorityLevel = Literal["AUTHORITATIVE", "SUPPLEMENTARY", "OPERATOR_DECLARED"]


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must include a timezone offset")
    return value.astimezone(timezone.utc)


class SpeedSourceEvidence(BaseModel):
    """The provenance envelope for one real source value."""

    source_key: str = Field(..., min_length=2, max_length=80)
    source_type: RealSourceType
    authority_level: AuthorityLevel
    source_reference: str = Field(..., min_length=3, max_length=500)
    observed_at: datetime
    fetched_at: datetime
    valid_until: datetime
    # Hash the raw provider response/document at ingestion. A reference alone
    # is not enough to prove that the value displayed by the caller is the
    # value that was evaluated.
    checksum: str = Field(..., pattern=r"^[A-Fa-f0-9]{64}$")
    provider_version: str | None = Field(default=None, max_length=120)

    @field_validator("observed_at", "fetched_at", "valid_until")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def validate_lineage(self) -> "SpeedSourceEvidence":
        if self.observed_at > self.fetched_at:
            raise ValueError("observed_at cannot be after fetched_at")
        if self.source_type in {
            "PUBLIC_OPEN_DATA",
            "CACHED_PROVIDER",
            "OPERATOR_INPUT",
        } and self.authority_level == "AUTHORITATIVE":
            raise ValueError(
                "public, cached, or operator-declared evidence cannot be authoritative without an authorized feed"
            )
        return self


SpeedConstraintCategory = Literal[
    "ROUTE_LIMIT",
    "TEMPORARY_RESTRICTION",
    "TRACK_GEOMETRY",
    "GRADIENT",
    "AXLE_LOAD",
    "ENVIRONMENT",
    "HEADWAY",
    "BLOCK_OCCUPANCY",
]


class SpeedConstraintInput(BaseModel):
    category: SpeedConstraintCategory
    label: str = Field(..., min_length=2, max_length=160)
    limit_kph: float = Field(..., gt=0, le=500)
    evidence: SpeedSourceEvidence


class BrakePerformanceInput(BaseModel):
    """Measured/approved train braking data, supplied for this consist."""

    effective_deceleration_mps2: float = Field(..., gt=0, le=10)
    reaction_time_seconds: float = Field(..., gt=0, le=120)
    safety_margin_meters: float = Field(..., ge=0, le=10000)
    evidence: SpeedSourceEvidence

    @model_validator(mode="after")
    def require_authoritative_brakes(self) -> "BrakePerformanceInput":
        if self.evidence.authority_level != "AUTHORITATIVE":
            raise ValueError("braking performance must be backed by authoritative evidence")
        if self.evidence.source_type not in {"AUTHORIZED_FEED", "IMPORTED_DOCUMENT"}:
            raise ValueError(
                "braking performance requires an authorized feed or certified imported document"
            )
        return self


class SpeedRiskAdvisoryRequest(BaseModel):
    route_id: UUID | None = None
    corridor_reference: str = Field(..., min_length=2, max_length=160)
    consist_manifest_checksum: str = Field(..., pattern=r"^[A-Fa-f0-9]{64}$")
    evaluation_at: datetime
    constraints: list[SpeedConstraintInput] = Field(default_factory=list, max_length=32)
    braking: BrakePerformanceInput | None = None

    @field_validator("evaluation_at")
    @classmethod
    def evaluation_timezone_required(cls, value: datetime) -> datetime:
        return _aware(value)


class SpeedEvidenceSummary(BaseModel):
    category: str
    label: str
    limit_kph: float | None = None
    source_key: str
    source_type: str
    authority_level: str
    source_reference: str
    observed_at: datetime
    fetched_at: datetime
    valid_until: datetime
    freshness: Literal["CURRENT", "EXPIRED", "FUTURE", "INVALID"]
    used_in_decision: bool
    excluded_reason: str | None = None
    checksum: str | None = None


class SpeedRiskAdvisoryResponse(BaseModel):
    status: Literal["ADVISORY", "HOLD", "UNAVAILABLE"]
    advisory_speed_kph: float | None = None
    stopping_distance_meters: float | None = None
    limiting_constraint: str | None = None
    corridor_reference: str
    evaluation_at: datetime
    consist_manifest_checksum: str
    evidence: list[SpeedEvidenceSummary]
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "Research decision support only. This advisory is not movement authority, "
        "signalling, ATP/Kavach, automatic braking, or collision avoidance."
    )
