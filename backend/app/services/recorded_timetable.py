"""Bounded decoded previews of the pinned local publisher capture."""

from copy import deepcopy
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from threading import Lock

from app.schemas.timetable import GtfsStaticFeed, TimetableSourceMetadata, TimetableSourceType
from app.services.recorded_source import inspect_recorded_source
from app.services.timetable_ingestion import (
    feed_summary,
    parse_gtfs_realtime,
    parse_gtfs_static,
)


PREVIEW_ROWS = 10
_decode_lock = Lock()


def _table(name: str, columns: list[str], rows: list[list]) -> dict:
    return {"name": name, "columns": columns, "rows": rows[:PREVIEW_ROWS]}


@lru_cache(maxsize=3)
def _decode_preview(directory: str, manifest_pin: str, source_key: str) -> dict:
    # Verification runs inside the lock as well as before cache lookup, so a
    # changed file cannot become admissible merely because an older result is cached.
    snapshot = inspect_recorded_source(Path(directory), manifest_pin)
    if not snapshot["content_checksums_valid"]:
        raise ValueError("Recorded source integrity check failed")
    item = next((feed for feed in snapshot["feeds"] if feed["source_key"] == source_key), None)
    if item is None:
        raise LookupError("Unknown recorded feed")
    source = TimetableSourceMetadata(
        provider_key=source_key,
        provider_name=item["publisher"],
        source_url=item["requested_url"],
        source_type=TimetableSourceType.REPLAYED_SNAPSHOT,
        source_license=snapshot["source_catalog"]["license"],
        fetched_at=datetime.fromisoformat(item["response_completed_at_utc"]),
        # Bind the decoder to the pinned capture, not a digest of the new read.
        checksum_sha256=item["sha256"],
    )
    with (Path(directory) / item["filename"]).open("rb") as handle:
        payload = handle.read(item["byte_length"] + 1)
    if item["data_kind"] == "published_schedule":
        feed = parse_gtfs_static(payload, source)
    elif item["data_kind"] in {"realtime_trip_updates", "realtime_service_alerts"}:
        feed = parse_gtfs_realtime(payload, source)
    else:
        raise ValueError("Recorded feed format is not supported")
    if isinstance(feed, GtfsStaticFeed):
        tables = [
            _table(
                "Stops",
                ["Stop ID", "Name"],
                [[row.stop_id, row.stop_name] for row in feed.stops[:PREVIEW_ROWS]],
            ),
            _table(
                "Trips",
                ["Trip ID", "Route ID", "Service ID", "Destination"],
                [
                    [row.trip_id, row.route_id, row.service_id, row.trip_headsign]
                    for row in feed.trips[:PREVIEW_ROWS]
                ],
            ),
            _table(
                "Published stop times",
                ["Trip ID", "Stop ID", "Sequence", "Arrival", "Departure"],
                [
                    [
                        row.trip_id,
                        row.stop_id,
                        row.stop_sequence,
                        row.arrival_time,
                        row.departure_time,
                    ]
                    for row in feed.stop_times[:PREVIEW_ROWS]
                ],
            ),
        ]
    else:
        tables = [
            _table(
                "Trip updates",
                ["Trip ID", "Service date", "Relationship", "Stop updates"],
                [
                    [
                        row.trip_id,
                        row.start_date,
                        row.schedule_relationship,
                        len(row.stop_time_updates),
                    ]
                    for row in feed.trip_updates[:PREVIEW_ROWS]
                ],
            ),
            _table(
                "Service alerts",
                ["Alert ID", "Cause", "Effect", "Header"],
                [
                    [row.alert_id, row.cause, row.effect, row.header_text]
                    for row in feed.alerts[:PREVIEW_ROWS]
                ],
            ),
        ]
    return {
        **feed_summary(feed),
        "manifest_sha256": manifest_pin,
        "preview_row_limit": PREVIEW_ROWS,
        "tables": [table for table in tables if table["rows"]],
        "notice": "Historical publisher capture decoded for research. Times belong to the recorded feed; no current traffic, block occupancy or movement authority is inferred.",
    }


def recorded_timetable_preview(directory: Path, manifest_pin: str, source_key: str) -> dict:
    # Full static parsing is expensive. Serialize the first decode and retain
    # only the bounded summary, not hundreds of thousands of parsed objects.
    with _decode_lock:
        snapshot = inspect_recorded_source(directory, manifest_pin)
        if not snapshot["content_checksums_valid"]:
            raise ValueError("Recorded source integrity check failed")
        if source_key not in {feed["source_key"] for feed in snapshot["feeds"]}:
            raise LookupError("Unknown recorded feed")
        return deepcopy(_decode_preview(str(directory.resolve()), manifest_pin, source_key))
