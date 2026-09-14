"""Strict, provenance-preserving timetable feed ingestion.

The adapters in this module intentionally do not ship a default timetable or
invent one when a provider is unavailable.  Static GTFS is validated as a
referentially complete snapshot, GTFS-Realtime accepts the standard protobuf
wire format (and a JSON representation for test/authorized gateways), and
the India Open Government Data adapter accepts the documented ``records``
envelope or a CSV export.  Each result contains the source URL, retrieval and
observation timestamps, and a SHA-256 digest of the exact downloaded bytes.

This is an ingestion boundary, not a movement-authority implementation.
Public timetable data can support research and decision support but cannot
authorize a train to enter a block or replace railway signalling.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
import zipfile
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from app.core.config import settings
from app.schemas.timetable import (
    GtfsRealtimeAlert,
    GtfsRealtimeFeed,
    GtfsRealtimeTripUpdate,
    GtfsRealtimeVehiclePosition,
    GtfsRoute,
    GtfsStaticFeed,
    GtfsStop,
    GtfsStopTime,
    GtfsTrip,
    IndiaRailwaysTimetableFeed,
    IndiaRailwaysTimetableRow,
    TimetableSourceMetadata,
    TimetableSourceType,
)

logger = logging.getLogger(__name__)

MAX_FEED_BYTES = 100 * 1024 * 1024
MAX_FEED_ROWS = 1_000_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TIME = re.compile(r"^(?P<hour>[0-9]{1,3}):(?P<minute>[0-5][0-9])(?::(?P<second>[0-5][0-9]))?$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "api-key",
    "apikey",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "service_role",
    "token",
}
_NORMALIZED_SENSITIVE_KEYS = {re.sub(r"[^a-z0-9]+", "_", item.casefold()).strip("_") for item in _SENSITIVE_KEYS}


class TimetableIngestionError(ValueError):
    """A feed did not satisfy the strict source contract."""

    def __init__(self, message: str, *, code: str = "INVALID_FEED") -> None:
        super().__init__(message)
        self.code = code


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _ensure_feed_size(payload: bytes) -> None:
    if not payload:
        raise TimetableIngestionError("timetable feed is empty", code="EMPTY_FEED")
    max_bytes = min(MAX_FEED_BYTES, settings.TIMETABLE_MAX_FEED_BYTES)
    if len(payload) > max_bytes:
        raise TimetableIngestionError(
            f"timetable feed exceeds the {max_bytes} byte safety limit",
            code="FEED_TOO_LARGE",
        )


def _ensure_source_metadata(source: TimetableSourceMetadata) -> TimetableSourceMetadata:
    fetched_at = source.fetched_at
    if fetched_at.tzinfo is None:
        raise TimetableIngestionError("fetched_at must include a timezone", code="BAD_TIMESTAMP")
    if source.observed_at is not None and source.observed_at.tzinfo is None:
        raise TimetableIngestionError("observed_at must include a timezone", code="BAD_TIMESTAMP")
    if not _SHA256.fullmatch(source.checksum_sha256):
        raise TimetableIngestionError("checksum_sha256 must be lowercase SHA-256", code="BAD_CHECKSUM")
    return source.model_copy(
        update={
            "fetched_at": fetched_at.astimezone(timezone.utc),
            "observed_at": source.observed_at.astimezone(timezone.utc)
            if source.observed_at
            else None,
        }
    )


def _ensure_payload_checksum(payload: bytes, source: TimetableSourceMetadata) -> None:
    actual = sha256_bytes(payload)
    if source.checksum_sha256 != actual:
        raise TimetableIngestionError(
            "source checksum does not match the exact feed bytes",
            code="BAD_CHECKSUM",
        )


def source_metadata(
    *,
    provider_key: str,
    provider_name: str,
    source_url: str,
    source_type: TimetableSourceType,
    payload: bytes,
    fetched_at: datetime | None = None,
    observed_at: datetime | None = None,
    source_license: str | None = None,
    source_version: str | None = None,
) -> TimetableSourceMetadata:
    """Build the evidence identity from the exact downloaded bytes."""

    return TimetableSourceMetadata(
        provider_key=provider_key,
        provider_name=provider_name,
        source_url=source_url,
        source_type=source_type,
        source_license=source_license,
        source_version=source_version,
        fetched_at=fetched_at or utc_now(),
        observed_at=observed_at,
        checksum_sha256=sha256_bytes(payload),
    )


def _decode_csv(payload: bytes, *, filename: str) -> list[dict[str, str]]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TimetableIngestionError(
            f"{filename} is not valid UTF-8", code="INVALID_ENCODING"
        ) from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if not reader.fieldnames:
        raise TimetableIngestionError(f"{filename} has no header", code="MISSING_HEADER")
    raw_fieldnames = [str(item) for item in reader.fieldnames]
    fieldnames = [item.strip() for item in raw_fieldnames]
    if any(not field for field in fieldnames):
        raise TimetableIngestionError(f"{filename} contains a blank column name", code="BAD_HEADER")
    if len(set(fieldnames)) != len(fieldnames):
        raise TimetableIngestionError(f"{filename} contains duplicate column names", code="BAD_HEADER")
    rows: list[dict[str, str]] = []
    for row_number, row in enumerate(reader, start=2):
        if row is None:
            continue
        normalized = {
            field: (row.get(raw_field) or "").strip()
            for raw_field, field in zip(raw_fieldnames, fieldnames)
        }
        # Empty trailing lines are harmless; an otherwise empty data row is
        # not evidence and is rejected rather than silently dropped.
        if not any(normalized.values()):
            continue
        if None in row:
            raise TimetableIngestionError(
                f"{filename} row {row_number} has more fields than its header",
                code="BAD_ROW",
            )
        rows.append(normalized)
        if len(rows) > MAX_FEED_ROWS:
            raise TimetableIngestionError("feed has too many rows", code="TOO_MANY_ROWS")
    return rows


def _required(row: dict[str, str], field: str, *, filename: str, row_number: int) -> str:
    value = row.get(field, "").strip()
    if not value:
        raise TimetableIngestionError(
            f"{filename} row {row_number} is missing {field}", code="MISSING_FIELD"
        )
    return value


def _optional_int(
    row: dict[str, str], field: str, *, filename: str, row_number: int, minimum: int = 0
) -> int | None:
    value = row.get(field, "").strip()
    if not value:
        return None
    try:
        result = int(value)
    except ValueError as exc:
        raise TimetableIngestionError(
            f"{filename} row {row_number} has invalid integer {field}", code="BAD_VALUE"
        ) from exc
    if result < minimum:
        raise TimetableIngestionError(
            f"{filename} row {row_number} has out-of-range {field}", code="BAD_VALUE"
        )
    return result


def parse_gtfs_time(value: str, *, field: str = "time") -> int:
    """Return seconds after midnight for a GTFS service time.

    GTFS deliberately permits hours above 24 for trips after midnight.  We
    preserve that value and only enforce the format/range required to prevent
    ambiguous schedule arithmetic.
    """

    match = _TIME.fullmatch(value.strip())
    if not match:
        raise TimetableIngestionError(
            f"{field} must use HH:MM[:SS] with a 0-167 hour range", code="BAD_TIME"
        )
    hour = int(match.group("hour"))
    if hour > 167:
        raise TimetableIngestionError(f"{field} hour exceeds GTFS service-day range", code="BAD_TIME")
    return hour * 3600 + int(match.group("minute")) * 60 + int(match.group("second") or 0)


def _validate_unique_ids(rows: Iterable[dict[str, str]], field: str, *, filename: str) -> None:
    seen: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        value = _required(row, field, filename=filename, row_number=row_number)
        if value in seen:
            raise TimetableIngestionError(
                f"{filename} contains duplicate {field} {value!r}", code="DUPLICATE_ID"
            )
        seen.add(value)


def parse_gtfs_static(payload: bytes, source: TimetableSourceMetadata) -> GtfsStaticFeed:
    """Parse and validate a GTFS static ZIP snapshot."""

    _ensure_feed_size(payload)
    source = _ensure_source_metadata(source)
    _ensure_payload_checksum(payload, source)
    if source.source_type not in {
        TimetableSourceType.LIVE_PROVIDER,
        TimetableSourceType.PUBLIC_OPEN_DATA,
        TimetableSourceType.REAL_HISTORICAL,
        TimetableSourceType.REPLAYED_SNAPSHOT,
    }:
        raise TimetableIngestionError("GTFS static source is not available", code="UNAVAILABLE")
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise TimetableIngestionError("GTFS static feed is not a valid ZIP", code="BAD_ARCHIVE") from exc

    try:
        names = {info.filename for info in archive.infolist()}
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts:
                raise TimetableIngestionError("GTFS ZIP contains a path traversal entry", code="BAD_ARCHIVE")
            if info.is_dir() or info.file_size > MAX_FEED_BYTES:
                raise TimetableIngestionError("GTFS ZIP contains an unsafe member", code="BAD_ARCHIVE")
        required_files = {"stops.txt", "routes.txt", "trips.txt", "stop_times.txt"}
        missing = required_files - names
        if missing:
            raise TimetableIngestionError(
                f"GTFS feed is missing required files: {', '.join(sorted(missing))}",
                code="MISSING_FILE",
            )
        if "calendar.txt" not in names and "calendar_dates.txt" not in names:
            raise TimetableIngestionError(
                "GTFS feed must contain calendar.txt or calendar_dates.txt", code="MISSING_FILE"
            )

        def rows(name: str) -> list[dict[str, str]]:
            return _decode_csv(archive.read(name), filename=name)

        stop_rows = rows("stops.txt")
        route_rows = rows("routes.txt")
        trip_rows = rows("trips.txt")
        stop_time_rows = rows("stop_times.txt")
        calendar_rows = rows("calendar.txt") if "calendar.txt" in names else []
        calendar_date_rows = rows("calendar_dates.txt") if "calendar_dates.txt" in names else []
    finally:
        archive.close()

    for row in stop_rows:
        if "stop_id" not in row or "stop_name" not in row:
            raise TimetableIngestionError("stops.txt requires stop_id and stop_name", code="MISSING_FIELD")
    for row in route_rows:
        if "route_id" not in row:
            raise TimetableIngestionError("routes.txt requires route_id", code="MISSING_FIELD")
    for row in trip_rows:
        if not {"route_id", "service_id", "trip_id"}.issubset(row):
            raise TimetableIngestionError(
                "trips.txt requires route_id, service_id, and trip_id", code="MISSING_FIELD"
            )
    for row in stop_time_rows:
        if not {"trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time"}.issubset(row):
            raise TimetableIngestionError(
                "stop_times.txt requires trip_id, stop_id, stop_sequence, arrival_time, and departure_time",
                code="MISSING_FIELD",
            )

    _validate_unique_ids(stop_rows, "stop_id", filename="stops.txt")
    _validate_unique_ids(route_rows, "route_id", filename="routes.txt")
    _validate_unique_ids(trip_rows, "trip_id", filename="trips.txt")

    stop_ids = {row["stop_id"] for row in stop_rows}
    route_ids = {row["route_id"] for row in route_rows}
    trip_ids = {row["trip_id"] for row in trip_rows}
    trip_route: dict[str, str] = {}
    for number, row in enumerate(trip_rows, start=2):
        route_id = _required(row, "route_id", filename="trips.txt", row_number=number)
        if route_id not in route_ids:
            raise TimetableIngestionError(
                f"trips.txt row {number} references unknown route_id {route_id!r}", code="BAD_REFERENCE"
            )
        trip_route[row["trip_id"]] = route_id

    stop_times: list[GtfsStopTime] = []
    per_trip_last_sequence: dict[str, int] = {}
    per_trip_last_departure: dict[str, int] = {}
    for number, row in enumerate(stop_time_rows, start=2):
        trip_id = _required(row, "trip_id", filename="stop_times.txt", row_number=number)
        stop_id = _required(row, "stop_id", filename="stop_times.txt", row_number=number)
        if trip_id not in trip_ids or stop_id not in stop_ids:
            raise TimetableIngestionError(
                f"stop_times.txt row {number} references an unknown trip or stop", code="BAD_REFERENCE"
            )
        sequence = _optional_int(row, "stop_sequence", filename="stop_times.txt", row_number=number)
        if sequence is None:
            raise TimetableIngestionError(
                f"stop_times.txt row {number} is missing stop_sequence", code="MISSING_FIELD"
            )
        arrival = _required(row, "arrival_time", filename="stop_times.txt", row_number=number)
        departure = _required(row, "departure_time", filename="stop_times.txt", row_number=number)
        arrival_seconds = parse_gtfs_time(arrival, field=f"stop_times.txt row {number} arrival_time")
        departure_seconds = parse_gtfs_time(departure, field=f"stop_times.txt row {number} departure_time")
        if departure_seconds < arrival_seconds:
            raise TimetableIngestionError(
                f"stop_times.txt row {number} departs before it arrives", code="BAD_TIME"
            )
        if trip_id in per_trip_last_sequence and sequence <= per_trip_last_sequence[trip_id]:
            raise TimetableIngestionError(
                f"stop_times.txt row {number} has non-increasing stop_sequence", code="BAD_ORDER"
            )
        if trip_id in per_trip_last_departure and arrival_seconds < per_trip_last_departure[trip_id]:
            raise TimetableIngestionError(
                f"stop_times.txt row {number} moves backwards in time", code="BAD_ORDER"
            )
        per_trip_last_sequence[trip_id] = sequence
        per_trip_last_departure[trip_id] = departure_seconds
        stop_times.append(
            GtfsStopTime(
                trip_id=trip_id,
                stop_id=stop_id,
                stop_sequence=sequence,
                arrival_time=arrival,
                departure_time=departure,
                pickup_type=_optional_int(row, "pickup_type", filename="stop_times.txt", row_number=number),
                drop_off_type=_optional_int(row, "drop_off_type", filename="stop_times.txt", row_number=number),
            )
        )

    stops = [
        GtfsStop(
            stop_id=row["stop_id"],
            stop_name=row["stop_name"],
            stop_code=row.get("stop_code") or None,
            stop_timezone=row.get("stop_timezone") or None,
        )
        for row in stop_rows
    ]
    routes = [
        GtfsRoute(
            route_id=row["route_id"],
            route_short_name=row.get("route_short_name") or None,
            route_long_name=row.get("route_long_name") or None,
            route_type=_optional_int(row, "route_type", filename="routes.txt", row_number=index),
        )
        for index, row in enumerate(route_rows, start=2)
    ]
    trips = [
        GtfsTrip(
            trip_id=row["trip_id"],
            route_id=row["route_id"],
            service_id=row["service_id"],
            trip_headsign=row.get("trip_headsign") or None,
            direction_id=_optional_int(row, "direction_id", filename="trips.txt", row_number=index),
        )
        for index, row in enumerate(trip_rows, start=2)
    ]
    return GtfsStaticFeed(
        source=source,
        stops=stops,
        routes=routes,
        trips=trips,
        stop_times=stop_times,
        calendar_rows=calendar_rows,
        calendar_date_rows=calendar_date_rows,
        record_count=len(stops) + len(routes) + len(trips) + len(stop_times)
        + len(calendar_rows) + len(calendar_date_rows),
    )


def _snake_case(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().casefold()).strip("_")


def _redact_record(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]"
            if _snake_case(str(key)) in _NORMALIZED_SENSITIVE_KEYS
            else _redact_record(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_record(item) for item in value]
    return value


def _as_snake(value: Any) -> Any:
    if isinstance(value, dict):
        return {_snake_case(str(key)): _as_snake(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_as_snake(item) for item in value]
    return value


def _json_or_protobuf_realtime(payload: bytes) -> dict[str, Any]:
    try:
        decoded = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        decoded = None
    if decoded is not None:
        if not isinstance(decoded, dict):
            raise TimetableIngestionError("GTFS-Realtime JSON root must be an object", code="BAD_PAYLOAD")
        return _as_snake(decoded)

    try:
        from google.protobuf.json_format import MessageToDict
        from google.transit import gtfs_realtime_pb2
    except ImportError as exc:
        raise TimetableIngestionError(
            "binary GTFS-Realtime requires the gtfs-realtime-bindings dependency",
            code="MISSING_DEPENDENCY",
        ) from exc
    message = gtfs_realtime_pb2.FeedMessage()
    try:
        message.ParseFromString(payload)
    except Exception as exc:
        raise TimetableIngestionError("invalid GTFS-Realtime protobuf payload", code="BAD_PAYLOAD") from exc
    return _as_snake(MessageToDict(message, preserving_proto_field_name=True))


def _unix_datetime(value: Any, *, field: str) -> datetime:
    try:
        timestamp = int(value)
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError) as exc:
        raise TimetableIngestionError(f"{field} is not a valid Unix timestamp", code="BAD_TIMESTAMP") from exc


def _optional_float(value: Any, *, field: str, minimum: float | None = None) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise TimetableIngestionError(f"{field} is not numeric", code="BAD_VALUE") from exc
    if minimum is not None and result < minimum:
        raise TimetableIngestionError(f"{field} is below its allowed range", code="BAD_VALUE")
    return result


def parse_gtfs_realtime(payload: bytes, source: TimetableSourceMetadata) -> GtfsRealtimeFeed:
    """Parse standard GTFS-Realtime protobuf or an equivalent JSON gateway payload."""

    _ensure_feed_size(payload)
    source = _ensure_source_metadata(source)
    _ensure_payload_checksum(payload, source)
    if source.source_type not in {
        TimetableSourceType.LIVE_PROVIDER,
        TimetableSourceType.PUBLIC_OPEN_DATA,
        TimetableSourceType.REPLAYED_SNAPSHOT,
    }:
        raise TimetableIngestionError("GTFS-Realtime source is not available", code="UNAVAILABLE")
    root = _json_or_protobuf_realtime(payload)
    header = root.get("header")
    if not isinstance(header, dict):
        raise TimetableIngestionError("GTFS-Realtime payload has no header", code="MISSING_FIELD")
    version = str(header.get("gtfs_realtime_version") or "").strip()
    if not version:
        raise TimetableIngestionError("GTFS-Realtime header has no version", code="MISSING_FIELD")
    header_timestamp = (
        _unix_datetime(header["timestamp"], field="header.timestamp")
        if header.get("timestamp") is not None
        else None
    )
    if header_timestamp and source.observed_at is None:
        source = source.model_copy(update={"observed_at": header_timestamp})
    entities = root.get("entity") or []
    if not isinstance(entities, list):
        raise TimetableIngestionError("GTFS-Realtime entity must be a list", code="BAD_PAYLOAD")

    trip_updates: list[GtfsRealtimeTripUpdate] = []
    vehicle_positions: list[GtfsRealtimeVehiclePosition] = []
    alerts: list[GtfsRealtimeAlert] = []
    seen_ids: set[str] = set()
    for index, entity in enumerate(entities):
        if not isinstance(entity, dict):
            raise TimetableIngestionError(f"entity {index} is not an object", code="BAD_PAYLOAD")
        entity_id = str(entity.get("id") or "").strip()
        if not entity_id:
            raise TimetableIngestionError(f"entity {index} has no id", code="MISSING_FIELD")
        if entity_id in seen_ids:
            raise TimetableIngestionError(f"duplicate GTFS-Realtime entity id {entity_id!r}", code="DUPLICATE_ID")
        seen_ids.add(entity_id)

        trip_update = entity.get("trip_update")
        if isinstance(trip_update, dict):
            trip = trip_update.get("trip") or {}
            trip_id = str(trip.get("trip_id") or "").strip()
            if not trip_id:
                raise TimetableIngestionError(
                    f"trip_update entity {entity_id!r} has no trip_id", code="MISSING_FIELD"
                )
            updates: list[dict[str, Any]] = []
            raw_updates = trip_update.get("stop_time_update") or []
            if not isinstance(raw_updates, list):
                raise TimetableIngestionError(
                    f"trip_update entity {entity_id!r} stop_time_update is not a list", code="BAD_PAYLOAD"
                )
            for update in raw_updates:
                if not isinstance(update, dict):
                    raise TimetableIngestionError(
                        f"trip_update entity {entity_id!r} contains an invalid stop update", code="BAD_PAYLOAD"
                    )
                normalized = dict(update)
                for side in ("arrival", "departure"):
                    if isinstance(normalized.get(side), dict) and normalized[side].get("time") is not None:
                        normalized[side] = dict(normalized[side])
                        normalized[side]["time_iso"] = _unix_datetime(
                            normalized[side]["time"], field=f"{side}.time"
                        ).isoformat()
                updates.append(normalized)
            trip_updates.append(
                GtfsRealtimeTripUpdate(
                    trip_id=trip_id,
                    route_id=str(trip.get("route_id") or "").strip() or None,
                    start_date=str(trip.get("start_date") or "").strip() or None,
                    schedule_relationship=str(trip.get("schedule_relationship") or "").strip() or None,
                    stop_time_updates=updates,
                )
            )

        vehicle = entity.get("vehicle")
        if isinstance(vehicle, dict):
            vehicle_descriptor = vehicle.get("vehicle") or {}
            vehicle_trip = vehicle.get("trip") or {}
            position = vehicle.get("position") or {}
            observed = (
                _unix_datetime(vehicle["timestamp"], field="vehicle.timestamp")
                if vehicle.get("timestamp") is not None
                else None
            )
            latitude = _optional_float(position.get("latitude"), field="vehicle.position.latitude")
            longitude = _optional_float(position.get("longitude"), field="vehicle.position.longitude")
            if latitude is not None and not -90 <= latitude <= 90:
                raise TimetableIngestionError("vehicle latitude is out of range", code="BAD_VALUE")
            if longitude is not None and not -180 <= longitude <= 180:
                raise TimetableIngestionError("vehicle longitude is out of range", code="BAD_VALUE")
            vehicle_positions.append(
                GtfsRealtimeVehiclePosition(
                    vehicle_id=str(vehicle_descriptor.get("id") or "").strip() or None,
                    trip_id=str(vehicle_trip.get("trip_id") or "").strip() or None,
                    latitude=latitude,
                    longitude=longitude,
                    speed_mps=_optional_float(position.get("speed"), field="vehicle.position.speed", minimum=0),
                    observed_at=observed,
                )
            )

        alert = entity.get("alert")
        if isinstance(alert, dict):
            def text_value(value: Any) -> str | None:
                if isinstance(value, str):
                    return value[:2000] or None
                if isinstance(value, dict):
                    translations = value.get("translation") or []
                    if translations and isinstance(translations[0], dict):
                        text = translations[0].get("text")
                        return str(text)[:2000] if text else None
                return None

            alerts.append(
                GtfsRealtimeAlert(
                    alert_id=entity_id,
                    cause=str(alert.get("cause") or "").strip() or None,
                    effect=str(alert.get("effect") or "").strip() or None,
                    header_text=text_value(alert.get("header_text")),
                    description_text=text_value(alert.get("description_text")),
                )
            )

    return GtfsRealtimeFeed(
        source=source,
        gtfs_realtime_version=version,
        header_timestamp=header_timestamp,
        incrementality=str(header.get("incrementality") or "").strip() or None,
        trip_updates=trip_updates,
        vehicle_positions=vehicle_positions,
        alerts=alerts,
        record_count=len(entities),
    )


def _json_records(payload: bytes) -> list[dict[str, Any]]:
    try:
        root = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TimetableIngestionError("India Open Data payload is not valid JSON", code="BAD_PAYLOAD") from exc
    if isinstance(root, list):
        records = root
    elif isinstance(root, dict):
        records = root.get("records") or root.get("data") or root.get("results")
        if not isinstance(records, list):
            raise TimetableIngestionError(
                "India Open Data JSON must contain a records/data/results array", code="BAD_PAYLOAD"
            )
    else:
        raise TimetableIngestionError("India Open Data JSON root must be an object or list", code="BAD_PAYLOAD")
    if len(records) > MAX_FEED_ROWS:
        raise TimetableIngestionError("feed has too many rows", code="TOO_MANY_ROWS")
    if not all(isinstance(row, dict) for row in records):
        raise TimetableIngestionError("India Open Data records must be objects", code="BAD_PAYLOAD")
    return [{str(key): value for key, value in row.items()} for row in records]


_INDIA_ALIASES = {
    "train_code": ("train_code", "train_no", "train_number", "train_num", "train"),
    "train_name": ("train_name", "name", "train_title"),
    "source_station_code": (
        "source_station_code",
        "from_station_code",
        "origin_station_code",
        "source_code",
        "from_code",
    ),
    "dest_station_code": (
        "dest_station_code",
        "destination_station_code",
        "to_station_code",
        "dest_code",
        "to_code",
    ),
    "scheduled_departure": ("scheduled_departure", "departure_time", "departure", "dep_time"),
    "scheduled_arrival": ("scheduled_arrival", "arrival_time", "arrival", "arr_time"),
    "service_date": ("service_date", "date", "journey_date", "travel_date"),
}


def _canonical_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = {_snake_case(key): value for key, value in record.items()}
    result: dict[str, Any] = {}
    for canonical, aliases in _INDIA_ALIASES.items():
        for alias in aliases:
            value = normalized.get(alias)
            if value is not None and str(value).strip():
                result[canonical] = str(value).strip()
                break
    return result


def _normalize_schedule_value(value: str, *, field: str) -> tuple[str, str | None]:
    value = value.strip()
    time_match = _TIME.fullmatch(value)
    if time_match:
        hour = int(time_match.group("hour"))
        if hour > 167:
            raise TimetableIngestionError(f"{field} hour exceeds allowed range", code="BAD_TIME")
        return (
            f"{hour:02d}:{int(time_match.group('minute')):02d}:{int(time_match.group('second') or 0):02d}",
            None,
        )
    # An explicit ISO date/time is retained as a date plus normalized local
    # time.  A timezone offset is not discarded silently; the source date is
    # still recorded and consumers can apply the agency's timezone.
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TimetableIngestionError(
            f"{field} must be HH:MM[:SS] or an ISO date/time", code="BAD_TIME"
        ) from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%H:%M:%S"), parsed.date().isoformat()


def parse_india_open_data(
    payload: bytes,
    source: TimetableSourceMetadata,
    *,
    content_type: str | None = None,
) -> IndiaRailwaysTimetableFeed:
    """Parse a real India Open Government Data JSON or CSV export.

    The catalog contains multiple releases with varying column names.  We
    accept only an explicit alias mapping and fail if any required operational
    field is absent; no station, train, or time is filled from repository
    defaults.
    """

    _ensure_feed_size(payload)
    source = _ensure_source_metadata(source)
    _ensure_payload_checksum(payload, source)
    if source.source_type not in {
        TimetableSourceType.PUBLIC_OPEN_DATA,
        TimetableSourceType.LIVE_PROVIDER,
        TimetableSourceType.REAL_HISTORICAL,
        TimetableSourceType.REPLAYED_SNAPSHOT,
    }:
        raise TimetableIngestionError("India Open Data source is not available", code="UNAVAILABLE")
    if "csv" in (content_type or "").casefold() or payload.lstrip().startswith(b"train"):
        rows: list[dict[str, Any]] = [dict(row) for row in _decode_csv(payload, filename="india-timetable.csv")]
    else:
        rows = _json_records(payload)
    if not rows:
        raise TimetableIngestionError("India Open Data feed contains no records", code="EMPTY_FEED")

    normalized_rows: list[IndiaRailwaysTimetableRow] = []
    for index, raw in enumerate(rows, start=1):
        canonical = _canonical_record(raw)
        required = (
            "train_code",
            "train_name",
            "source_station_code",
            "dest_station_code",
            "scheduled_departure",
            "scheduled_arrival",
        )
        missing = [field for field in required if not canonical.get(field)]
        if missing:
            available = ", ".join(sorted(_snake_case(key) for key in raw))
            raise TimetableIngestionError(
                f"India Open Data record {index} is missing {', '.join(missing)}; available fields: {available}",
                code="MISSING_FIELD",
            )
        departure, departure_date = _normalize_schedule_value(
            canonical["scheduled_departure"], field=f"record {index} departure"
        )
        arrival, arrival_date = _normalize_schedule_value(
            canonical["scheduled_arrival"], field=f"record {index} arrival"
        )
        service_date = canonical.get("service_date") or departure_date or arrival_date
        if service_date and not _DATE.fullmatch(service_date):
            raise TimetableIngestionError(
                f"record {index} service_date must be YYYY-MM-DD", code="BAD_DATE"
            )
        normalized_rows.append(
            IndiaRailwaysTimetableRow(
                train_code=canonical["train_code"],
                train_name=canonical["train_name"],
                source_station_code=canonical["source_station_code"],
                dest_station_code=canonical["dest_station_code"],
                scheduled_departure=departure,
                scheduled_arrival=arrival,
                service_date=service_date,
                raw_record=_redact_record({str(key): value for key, value in raw.items()}),
            )
        )
    return IndiaRailwaysTimetableFeed(source=source, rows=normalized_rows, record_count=len(normalized_rows))


def _configured_url(provider_key: str) -> str:
    value = {
        "gtfs_static": settings.GTFS_STATIC_FEED_URL,
        "gtfs_realtime": settings.GTFS_REALTIME_FEED_URL,
        "india_open_data": settings.INDIA_RAILWAYS_TIMETABLE_API_URL,
    }[provider_key].strip()
    if not value:
        raise TimetableIngestionError(
            f"{provider_key} source URL is not configured", code="NOT_CONFIGURED"
        )
    if not value.startswith("https://"):
        raise TimetableIngestionError("timetable provider URLs must use HTTPS", code="INSECURE_URL")
    parsed = urlsplit(value)
    if parsed.username or parsed.password:
        raise TimetableIngestionError(
            "timetable provider URLs must not contain embedded credentials", code="INSECURE_URL"
        )
    sensitive_query_keys = {
        "api_key",
        "api-key",
        "apikey",
        "key",
        "token",
        "auth",
        "password",
        "secret",
    }
    if any(key.casefold() in sensitive_query_keys for key, _ in parse_qsl(parsed.query)):
        raise TimetableIngestionError(
            "timetable provider URLs must not contain credential query parameters; "
            "use the server-side provider key setting",
            code="INSECURE_URL",
        )
    return value


def public_source_reference(value: str) -> str:
    """Redact credential-like query values before exposing a source URL."""

    parsed = urlsplit(value.strip())
    sensitive = {"api_key", "api-key", "apikey", "key", "token", "auth", "password", "secret"}
    query = [
        (key, "[REDACTED]" if key.casefold() in sensitive else item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit(parsed._replace(query=urlencode(query)))


async def _download_configured(provider_key: str) -> tuple[bytes, str, dict[str, str]]:
    if not settings.LIVE_DATA_ENABLED:
        raise TimetableIngestionError("external timetable providers are disabled", code="DISABLED")
    url = _configured_url(provider_key)
    params: dict[str, str] = {}
    if provider_key == "india_open_data" and settings.INDIA_RAILWAYS_TIMETABLE_API_KEY:
        params["api-key"] = settings.INDIA_RAILWAYS_TIMETABLE_API_KEY
    try:
        async with httpx.AsyncClient(timeout=settings.PROVIDER_TIMEOUT_SECONDS) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.content
            headers = {key.casefold(): value for key, value in response.headers.items()}
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {401, 403}:
            raise TimetableIngestionError("timetable provider requires valid authorization", code="AUTH_REQUIRED") from exc
        raise TimetableIngestionError(
            f"timetable provider returned HTTP {exc.response.status_code}", code="UNAVAILABLE"
        ) from exc
    except httpx.HTTPError as exc:
        raise TimetableIngestionError("timetable provider could not be reached", code="UNAVAILABLE") from exc
    _ensure_feed_size(payload)
    return payload, url, headers


async def fetch_gtfs_static() -> GtfsStaticFeed:
    payload, url, headers = await _download_configured("gtfs_static")
    source = source_metadata(
        provider_key="gtfs_static",
        provider_name=settings.GTFS_STATIC_SOURCE_NAME,
        source_url=public_source_reference(url),
        source_type=TimetableSourceType.LIVE_PROVIDER,
        payload=payload,
        source_license=settings.GTFS_SOURCE_LICENSE or None,
        source_version=headers.get("etag") or headers.get("last-modified"),
    )
    return parse_gtfs_static(payload, source)


async def fetch_gtfs_realtime() -> GtfsRealtimeFeed:
    payload, url, headers = await _download_configured("gtfs_realtime")
    source = source_metadata(
        provider_key="gtfs_realtime",
        provider_name=settings.GTFS_REALTIME_SOURCE_NAME,
        source_url=public_source_reference(url),
        source_type=TimetableSourceType.LIVE_PROVIDER,
        payload=payload,
        source_license=settings.GTFS_SOURCE_LICENSE or None,
        source_version=headers.get("etag") or headers.get("last-modified"),
    )
    return parse_gtfs_realtime(payload, source)


async def fetch_india_open_data() -> IndiaRailwaysTimetableFeed:
    payload, url, headers = await _download_configured("india_open_data")
    source = source_metadata(
        provider_key="india_open_data",
        provider_name=settings.INDIA_RAILWAYS_SOURCE_NAME,
        source_url=public_source_reference(url),
        source_type=TimetableSourceType.PUBLIC_OPEN_DATA,
        payload=payload,
        source_license=settings.INDIA_RAILWAYS_SOURCE_LICENSE or None,
        source_version=headers.get("etag") or headers.get("last-modified"),
    )
    return parse_india_open_data(payload, source, content_type=headers.get("content-type"))


def feed_summary(feed: GtfsStaticFeed | GtfsRealtimeFeed | IndiaRailwaysTimetableFeed) -> dict[str, Any]:
    """Return a bounded API-safe summary without dropping provenance."""

    summary = {
        "feed_type": feed.feed_type,
        "provider_key": feed.source.provider_key,
        "provider_name": feed.source.provider_name,
        "source_type": feed.source.source_type,
        "source_url": feed.source.source_url,
        "source_license": feed.source.source_license,
        "source_version": feed.source.source_version,
        "checksum_sha256": feed.source.checksum_sha256,
        "fetched_at": feed.source.fetched_at,
        "observed_at": feed.source.observed_at,
        "record_count": feed.record_count,
        "validation_state": "VALID",
    }
    if isinstance(feed, GtfsStaticFeed):
        summary["counts"] = {
            "stops": len(feed.stops),
            "routes": len(feed.routes),
            "trips": len(feed.trips),
            "stop_times": len(feed.stop_times),
        }
    elif isinstance(feed, GtfsRealtimeFeed):
        summary["counts"] = {
            "trip_updates": len(feed.trip_updates),
            "vehicle_positions": len(feed.vehicle_positions),
            "alerts": len(feed.alerts),
        }
    else:
        summary["counts"] = {"train_rows": len(feed.rows)}
    return summary
