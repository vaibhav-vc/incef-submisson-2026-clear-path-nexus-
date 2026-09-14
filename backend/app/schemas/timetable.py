"""Contracts for externally sourced timetable feeds.

These contracts deliberately keep a timetable's source metadata next to its
normalized values.  A timetable is not treated as live merely because it was
successfully downloaded: callers must inspect ``source_type``, timestamps,
freshness, and ``validation_state`` before using it for an operational
decision.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class TimetableFeedType(str, Enum):
    GTFS_STATIC = "GTFS_STATIC"
    GTFS_REALTIME = "GTFS_REALTIME"
    INDIA_RAILWAYS_OPEN_DATA = "INDIA_RAILWAYS_OPEN_DATA"


class TimetableSourceType(str, Enum):
    LIVE_PROVIDER = "LIVE_PROVIDER"
    PUBLIC_OPEN_DATA = "PUBLIC_OPEN_DATA"
    REAL_HISTORICAL = "REAL_HISTORICAL"
    REPLAYED_SNAPSHOT = "REPLAYED_SNAPSHOT"
    UNAVAILABLE = "UNAVAILABLE"


class TimetableValidationState(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNAVAILABLE = "UNAVAILABLE"


class TimetableSourceMetadata(BaseModel):
    """Evidence identity for one downloaded/imported feed."""

    provider_key: str = Field(..., min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    provider_name: str = Field(..., min_length=2, max_length=160)
    source_url: str = Field(..., min_length=1, max_length=500)
    source_type: TimetableSourceType
    source_license: str | None = Field(default=None, max_length=160)
    source_version: str | None = Field(default=None, max_length=120)
    fetched_at: datetime
    observed_at: datetime | None = None
    checksum_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")

    @field_validator("source_url")
    @classmethod
    def source_reference_must_be_explicit(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("source_url must not be blank")
        # Local imports may use file:// references, but bare filesystem paths
        # are deliberately not accepted in API evidence envelopes.
        if not value.startswith(("https://", "http://", "file://")):
            raise ValueError("source_url must be an http(s) or file:// reference")
        return value


class GtfsStop(BaseModel):
    stop_id: str = Field(..., min_length=1, max_length=160)
    stop_name: str = Field(..., min_length=1, max_length=200)
    stop_code: str | None = Field(default=None, max_length=80)
    stop_timezone: str | None = Field(default=None, max_length=80)


class GtfsRoute(BaseModel):
    route_id: str = Field(..., min_length=1, max_length=160)
    route_short_name: str | None = Field(default=None, max_length=80)
    route_long_name: str | None = Field(default=None, max_length=200)
    route_type: int | None = Field(default=None, ge=0, le=12)


class GtfsTrip(BaseModel):
    trip_id: str = Field(..., min_length=1, max_length=160)
    route_id: str = Field(..., min_length=1, max_length=160)
    service_id: str = Field(..., min_length=1, max_length=160)
    trip_headsign: str | None = Field(default=None, max_length=200)
    direction_id: int | None = Field(default=None, ge=0, le=1)


class GtfsStopTime(BaseModel):
    trip_id: str = Field(..., min_length=1, max_length=160)
    stop_id: str = Field(..., min_length=1, max_length=160)
    stop_sequence: int = Field(..., ge=0)
    arrival_time: str = Field(..., pattern=r"^(?:[0-9]{1,3}):[0-5][0-9]:[0-5][0-9]$")
    departure_time: str = Field(..., pattern=r"^(?:[0-9]{1,3}):[0-5][0-9]:[0-5][0-9]$")
    pickup_type: int | None = Field(default=None, ge=0, le=3)
    drop_off_type: int | None = Field(default=None, ge=0, le=3)


class GtfsStaticFeed(BaseModel):
    feed_type: Literal[TimetableFeedType.GTFS_STATIC] = TimetableFeedType.GTFS_STATIC
    source: TimetableSourceMetadata
    stops: list[GtfsStop] = Field(default_factory=list)
    routes: list[GtfsRoute] = Field(default_factory=list)
    trips: list[GtfsTrip] = Field(default_factory=list)
    stop_times: list[GtfsStopTime] = Field(default_factory=list)
    calendar_rows: list[dict[str, str]] = Field(default_factory=list)
    calendar_date_rows: list[dict[str, str]] = Field(default_factory=list)
    record_count: int = Field(..., ge=0)


class GtfsRealtimeTripUpdate(BaseModel):
    trip_id: str = Field(..., min_length=1, max_length=160)
    route_id: str | None = Field(default=None, max_length=160)
    start_date: str | None = Field(default=None, max_length=32)
    schedule_relationship: str | None = Field(default=None, max_length=40)
    stop_time_updates: list[dict[str, Any]] = Field(default_factory=list)


class GtfsRealtimeVehiclePosition(BaseModel):
    vehicle_id: str | None = Field(default=None, max_length=160)
    trip_id: str | None = Field(default=None, max_length=160)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    speed_mps: float | None = Field(default=None, ge=0)
    observed_at: datetime | None = None


class GtfsRealtimeAlert(BaseModel):
    alert_id: str = Field(..., min_length=1, max_length=160)
    cause: str | None = Field(default=None, max_length=80)
    effect: str | None = Field(default=None, max_length=80)
    header_text: str | None = Field(default=None, max_length=500)
    description_text: str | None = Field(default=None, max_length=2000)


class GtfsRealtimeFeed(BaseModel):
    feed_type: Literal[TimetableFeedType.GTFS_REALTIME] = TimetableFeedType.GTFS_REALTIME
    source: TimetableSourceMetadata
    gtfs_realtime_version: str
    header_timestamp: datetime | None = None
    incrementality: str | None = None
    trip_updates: list[GtfsRealtimeTripUpdate] = Field(default_factory=list)
    vehicle_positions: list[GtfsRealtimeVehiclePosition] = Field(default_factory=list)
    alerts: list[GtfsRealtimeAlert] = Field(default_factory=list)
    record_count: int = Field(..., ge=0)


class IndiaRailwaysTimetableRow(BaseModel):
    train_code: str = Field(..., min_length=1, max_length=80)
    train_name: str = Field(..., min_length=1, max_length=200)
    source_station_code: str = Field(..., min_length=1, max_length=80)
    dest_station_code: str = Field(..., min_length=1, max_length=80)
    scheduled_departure: str = Field(..., pattern=r"^(?:[0-9]{1,3}):[0-5][0-9](?::[0-5][0-9])?$")
    scheduled_arrival: str = Field(..., pattern=r"^(?:[0-9]{1,3}):[0-5][0-9](?::[0-5][0-9])?$")
    service_date: str | None = Field(default=None, max_length=32)
    raw_record: dict[str, Any] = Field(default_factory=dict)


class IndiaRailwaysTimetableFeed(BaseModel):
    feed_type: Literal[TimetableFeedType.INDIA_RAILWAYS_OPEN_DATA] = (
        TimetableFeedType.INDIA_RAILWAYS_OPEN_DATA
    )
    source: TimetableSourceMetadata
    rows: list[IndiaRailwaysTimetableRow] = Field(default_factory=list)
    record_count: int = Field(..., ge=0)


class TimetableImportSummary(BaseModel):
    feed_type: TimetableFeedType
    provider_key: str
    source_type: TimetableSourceType
    validation_state: TimetableValidationState
    source_url: str
    checksum_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    fetched_at: datetime
    observed_at: datetime | None = None
    record_count: int = Field(..., ge=0)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class TimetableSourceCatalogItem(BaseModel):
    provider_key: str
    provider_name: str
    feed_type: TimetableFeedType
    configured: bool
    source_url: str | None = None
    source_license: str | None = None
    authority_note: str


class TimetableSourceCatalogResponse(BaseModel):
    items: list[TimetableSourceCatalogItem]
    real_data_only: bool
