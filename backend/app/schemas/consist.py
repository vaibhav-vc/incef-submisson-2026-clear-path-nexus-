"""API contracts for real train manifests and network section conflicts.

The contracts intentionally do not accept demo/simulated source types. A
historical or replayed record can be imported for research, but the conflict
engine will not report it as a current operational ``CLEAR`` result.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


RealSourceType = Literal[
    "LIVE_PROVIDER",
    "AUTHORIZED_FEED",
    "IMPORTED_DOCUMENT",
    "OPERATOR_INPUT",
    "REAL_HISTORICAL",
    "REPLAYED_SNAPSHOT",
]

CurrentSourceType = Literal["LIVE_PROVIDER", "AUTHORIZED_FEED", "IMPORTED_DOCUMENT", "OPERATOR_INPUT"]


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value


class CarriageLoadCreate(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, str_strip_whitespace=True)

    position_in_train: int = Field(..., ge=1, le=4096)
    carriage_identifier: str = Field(..., min_length=1, max_length=80)
    carriage_type: str = Field(..., min_length=1, max_length=80)
    tare_weight_tons: float = Field(..., gt=0)
    cargo_weight_tons: float = Field(..., ge=0)
    gross_weight_tons: float = Field(..., gt=0)
    length_m: float = Field(..., gt=0)
    width_m: float = Field(..., gt=0)
    height_m: float = Field(..., gt=0)
    axle_count: int = Field(..., ge=1, le=64)
    brake_percentage: float | None = Field(default=None, ge=0)
    load_distribution: dict = Field(default_factory=dict)
    hazardous_material_class: str | None = Field(default=None, max_length=40)
    source_type: RealSourceType
    source_reference: str = Field(..., min_length=3, max_length=500)
    source_checksum: str = Field(..., pattern=r"^[A-Fa-f0-9]{64}$")
    observed_at: datetime

    @model_validator(mode="after")
    def validate_manifest_values(self) -> "CarriageLoadCreate":
        if abs(self.gross_weight_tons - (self.tare_weight_tons + self.cargo_weight_tons)) > 0.001:
            raise ValueError("gross_weight_tons must equal tare_weight_tons + cargo_weight_tons")
        _require_aware(self.observed_at, "observed_at")
        if not isinstance(self.load_distribution, dict):
            raise ValueError("load_distribution must be an object")
        return self


class TrainConsistCreate(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, str_strip_whitespace=True)

    manifest_checksum: str = Field(..., pattern=r"^[A-Fa-f0-9]{64}$")
    expected_carriage_count: int = Field(..., ge=1, le=4096)
    source_type: RealSourceType
    source_reference: str = Field(..., min_length=3, max_length=500)
    observed_at: datetime
    fetched_at: datetime
    # Public API submissions are declarations, not authenticated connector
    # output. Trusted importers may persist VERIFIED rows through an internal
    # ingestion path after validating issuer identity and source bytes.
    verification_state: Literal["UNVERIFIED"] = "UNVERIFIED"
    metadata: dict = Field(default_factory=dict)
    carriages: list[CarriageLoadCreate] = Field(..., min_length=1, max_length=4096)

    @model_validator(mode="after")
    def validate_consist(self) -> "TrainConsistCreate":
        _require_aware(self.observed_at, "observed_at")
        _require_aware(self.fetched_at, "fetched_at")
        if self.fetched_at < self.observed_at:
            raise ValueError("fetched_at cannot be before observed_at")
        positions = [item.position_in_train for item in self.carriages]
        identifiers = [item.carriage_identifier for item in self.carriages]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("carriage identifiers must be unique")
        if len(set(positions)) != len(positions):
            raise ValueError("carriage positions must be unique")
        if sorted(positions) != list(range(1, len(positions) + 1)):
            raise ValueError("carriage positions must be contiguous starting at 1")
        if len(self.carriages) != self.expected_carriage_count:
            raise ValueError(
                "carriage manifest is incomplete: expected_carriage_count must "
                "equal the number of carriage rows"
            )
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be an object")
        return self


class CarriageLoadResponse(CarriageLoadCreate):
    id: UUID
    consist_id: UUID
    gross_weight_tons: float
    axle_load_tons: float

    model_config = {"from_attributes": True}


class TrainConsistResponse(BaseModel):
    id: UUID
    schedule_id: UUID
    user_id: str
    source_type: str
    source_reference: str
    manifest_checksum: str
    expected_carriage_count: int
    manifest_complete: bool
    observed_at: datetime
    fetched_at: datetime
    verification_state: str
    metadata: dict = Field(validation_alias="metadata_json", serialization_alias="metadata")
    total_gross_weight_tons: float
    total_length_m: float
    maximum_height_m: float
    maximum_width_m: float
    maximum_axle_load_tons: float
    carriages: list[CarriageLoadResponse]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OccupationWindowCreate(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, str_strip_whitespace=True)

    segment_id: UUID
    sequence_in_route: int = Field(..., ge=0, le=4096)
    entry_time: datetime
    exit_time: datetime
    direction: Literal["FORWARD", "REVERSE"]
    train_length_m: float = Field(..., gt=0)
    expected_speed_kmh: float | None = Field(default=None, gt=0)
    source_type: RealSourceType
    source_reference: str = Field(..., min_length=3, max_length=500)
    source_checksum: str = Field(..., pattern=r"^[A-Fa-f0-9]{64}$")
    verification_state: Literal["UNVERIFIED"] = "UNVERIFIED"
    observed_at: datetime
    fetched_at: datetime

    @model_validator(mode="after")
    def validate_window(self) -> "OccupationWindowCreate":
        if self.exit_time <= self.entry_time:
            raise ValueError("exit_time must be after entry_time")
        _require_aware(self.entry_time, "entry_time")
        _require_aware(self.exit_time, "exit_time")
        _require_aware(self.observed_at, "observed_at")
        _require_aware(self.fetched_at, "fetched_at")
        if self.fetched_at < self.observed_at:
            raise ValueError("fetched_at cannot be before observed_at")
        return self


class OccupationWindowBatch(BaseModel):
    windows: list[OccupationWindowCreate] = Field(..., min_length=1, max_length=4096)

    @model_validator(mode="after")
    def validate_sequences(self) -> "OccupationWindowBatch":
        sequences = [item.sequence_in_route for item in self.windows]
        if len(set(sequences)) != len(sequences):
            raise ValueError("occupation window sequence values must be unique")
        if sorted(sequences) != list(range(len(sequences))):
            raise ValueError("occupation window sequence values must be contiguous starting at 0")
        return self


class OccupationWindowResponse(OccupationWindowCreate):
    id: UUID
    schedule_id: UUID
    verification_state: str

    model_config = {"from_attributes": True}


class TrackSectionPolicyCreate(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, str_strip_whitespace=True)

    segment_id: UUID
    single_track: bool
    minimum_headway_seconds: float | None = Field(default=None, ge=0)
    policy_version: str | None = Field(default=None, max_length=80)
    source_type: CurrentSourceType
    source_reference: str = Field(..., min_length=3, max_length=500)
    source_checksum: str = Field(..., pattern=r"^[A-Fa-f0-9]{64}$")
    verification_state: Literal["UNVERIFIED"] = "UNVERIFIED"
    observed_at: datetime
    fetched_at: datetime

    @model_validator(mode="after")
    def validate_policy(self) -> "TrackSectionPolicyCreate":
        _require_aware(self.observed_at, "observed_at")
        _require_aware(self.fetched_at, "fetched_at")
        if self.fetched_at < self.observed_at:
            raise ValueError("fetched_at cannot be before observed_at")
        if self.single_track and self.minimum_headway_seconds is None:
            raise ValueError("single-track policy requires minimum_headway_seconds")
        return self


class TrackSectionPolicyResponse(TrackSectionPolicyCreate):
    id: UUID
    verification_state: str

    model_config = {"from_attributes": True}


class ScheduleConflictResponse(BaseModel):
    conflict_type: Literal[
        "SAME_SECTION_OVERLAP",
        "OPPOSING_SINGLE_TRACK",
        "MINIMUM_HEADWAY",
    ]
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


class NetworkConflictResponse(BaseModel):
    status: Literal["CLEAR", "BLOCKED", "UNAVAILABLE"]
    schedule_id: UUID
    conflicts: list[ScheduleConflictResponse] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    assessed_window_count: int = Field(ge=0)
    assessed_schedule_count: int = Field(ge=0)
    evidence_state: Literal["CURRENT_REAL", "INCOMPLETE", "HISTORICAL_REPLAY"]
    explanation: str
