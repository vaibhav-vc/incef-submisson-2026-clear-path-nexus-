"""Carriage-level train consist and section-occupation persistence.

These tables deliberately keep source identity next to every operational input.
The conflict engine is allowed to produce a trusted result only after the
source metadata has been validated; database rows without an attributable
source are therefore never treated as live movement data.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.route import Base

if TYPE_CHECKING:
    from app.models.route import TrainSchedule


class TrainConsist(Base):
    """One immutable-at-decision-time manifest for a scheduled train."""

    __tablename__ = "train_consists"
    __table_args__ = (
        CheckConstraint("manifest_checksum ~ '^[0-9A-Fa-f]{64}$'", name="ck_train_consist_checksum"),
        UniqueConstraint("schedule_id", name="uq_train_consist_schedule"),
        Index("ix_train_consists_owner_observed", "user_id", "observed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("train_schedules.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    manifest_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verification_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default="UNVERIFIED", index=True
    )
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    carriages: Mapped[list["CarriageLoad"]] = relationship(
        "CarriageLoad",
        back_populates="consist",
        cascade="all, delete-orphan",
        order_by="CarriageLoad.position_in_train",
    )
    schedule: Mapped["TrainSchedule"] = relationship("TrainSchedule", back_populates="consist")

    @property
    def total_gross_weight_tons(self) -> float:
        return sum(float(item.gross_weight_tons) for item in self.carriages)

    @property
    def total_length_m(self) -> float:
        return sum(float(item.length_m) for item in self.carriages)

    @property
    def maximum_height_m(self) -> float:
        return max(float(item.height_m) for item in self.carriages) if self.carriages else 0.0

    @property
    def maximum_width_m(self) -> float:
        return max(float(item.width_m) for item in self.carriages) if self.carriages else 0.0

    @property
    def maximum_axle_load_tons(self) -> float:
        return max(float(item.axle_load_tons) for item in self.carriages) if self.carriages else 0.0


class CarriageLoad(Base):
    """A single real carriage/wagon entry from the consist manifest."""

    __tablename__ = "carriage_loads"
    __table_args__ = (
        CheckConstraint("position_in_train > 0", name="ck_carriage_position_positive"),
        CheckConstraint("tare_weight_tons > 0", name="ck_carriage_tare_positive"),
        CheckConstraint("cargo_weight_tons >= 0", name="ck_carriage_cargo_nonnegative"),
        CheckConstraint("gross_weight_tons > 0", name="ck_carriage_gross_positive"),
        CheckConstraint("length_m > 0", name="ck_carriage_length_positive"),
        CheckConstraint("width_m > 0", name="ck_carriage_width_positive"),
        CheckConstraint("height_m > 0", name="ck_carriage_height_positive"),
        CheckConstraint("axle_count > 0", name="ck_carriage_axles_positive"),
        CheckConstraint("brake_percentage IS NULL OR brake_percentage >= 0", name="ck_carriage_brake_nonnegative"),
        UniqueConstraint("consist_id", "position_in_train", name="uq_carriage_consist_position"),
        Index("ix_carriage_loads_consist_position", "consist_id", "position_in_train"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    consist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("train_consists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position_in_train: Mapped[int] = mapped_column(Integer, nullable=False)
    carriage_identifier: Mapped[str] = mapped_column(String(80), nullable=False)
    carriage_type: Mapped[str] = mapped_column(String(80), nullable=False)
    tare_weight_tons: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    cargo_weight_tons: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    gross_weight_tons: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    length_m: Mapped[float] = mapped_column(Numeric(8, 3), nullable=False)
    width_m: Mapped[float] = mapped_column(Numeric(8, 3), nullable=False)
    height_m: Mapped[float] = mapped_column(Numeric(8, 3), nullable=False)
    axle_count: Mapped[int] = mapped_column(Integer, nullable=False)
    brake_percentage: Mapped[float | None] = mapped_column(Numeric(8, 3))
    load_distribution: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    hazardous_material_class: Mapped[str | None] = mapped_column(String(40))
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    source_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    consist: Mapped[TrainConsist] = relationship("TrainConsist", back_populates="carriages")

    @property
    def axle_load_tons(self) -> float:
        """Derived axle load; no independently supplied value is trusted."""

        return float(self.gross_weight_tons) / self.axle_count


class RouteOccupationWindow(Base):
    """Evidence-backed time interval in which a train occupies a segment."""

    __tablename__ = "route_occupation_windows"
    __table_args__ = (
        CheckConstraint("sequence_in_route >= 0", name="ck_occupation_sequence_nonnegative"),
        CheckConstraint("entry_time < exit_time", name="ck_occupation_time_order"),
        CheckConstraint("train_length_m > 0", name="ck_occupation_length_positive"),
        CheckConstraint(
            "expected_speed_kmh IS NULL OR expected_speed_kmh > 0",
            name="ck_occupation_speed_positive",
        ),
        UniqueConstraint("schedule_id", "sequence_in_route", name="uq_occupation_schedule_sequence"),
        Index("ix_occupation_segment_window", "segment_id", "entry_time", "exit_time"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("train_schedules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("line_segments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_in_route: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    train_length_m: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    expected_speed_kmh: Mapped[float | None] = mapped_column(Numeric(8, 3))
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    source_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    schedule: Mapped["TrainSchedule"] = relationship(
        "TrainSchedule", back_populates="occupation_windows"
    )


class TrackSectionPolicy(Base):
    """Authorized policy describing capacity/headway for one line segment."""

    __tablename__ = "track_section_policies"
    __table_args__ = (
        CheckConstraint(
            "minimum_headway_seconds IS NULL OR minimum_headway_seconds >= 0",
            name="ck_policy_headway_nonnegative",
        ),
        CheckConstraint("source_checksum ~ '^[0-9A-Fa-f]{64}$'", name="ck_policy_checksum"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("line_segments.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    single_track: Mapped[bool] = mapped_column(Boolean, nullable=False)
    minimum_headway_seconds: Mapped[float | None] = mapped_column(Numeric(12, 3))
    policy_version: Mapped[str | None] = mapped_column(String(80))
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    source_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
