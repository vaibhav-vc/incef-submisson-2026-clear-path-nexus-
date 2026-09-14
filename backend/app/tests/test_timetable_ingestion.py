from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone

import pytest

from app.schemas.timetable import TimetableSourceType
from app.core.security import CurrentUser
from app.api.v1.timetables import timetable_sources
from app.services.timetable_ingestion import (
    TimetableIngestionError,
    parse_gtfs_realtime,
    parse_gtfs_static,
    parse_india_open_data,
    public_source_reference,
    source_metadata,
)


def _source(payload: bytes, *, source_type: TimetableSourceType = TimetableSourceType.REAL_HISTORICAL):
    return source_metadata(
        provider_key="test_feed",
        provider_name="Test feed",
        source_url="file:///test/feed",
        source_type=source_type,
        payload=payload,
        fetched_at=datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_timetable_source_catalog_has_no_implicit_feed_url() -> None:
    catalog = await timetable_sources(
        CurrentUser(id="judge", email=None, role="unassigned", claims={})
    )

    assert len(catalog.items) == 3
    assert {item.feed_type.value for item in catalog.items} == {
        "GTFS_STATIC",
        "GTFS_REALTIME",
        "INDIA_RAILWAYS_OPEN_DATA",
    }
    assert all(item.configured is False for item in catalog.items)
    assert all(item.source_url is None for item in catalog.items)


def test_public_source_reference_redacts_query_credentials() -> None:
    assert (
        public_source_reference("https://feed.example/timetable?api-key=secret&format=json")
        == "https://feed.example/timetable?api-key=%5BREDACTED%5D&format=json"
    )


def _gtfs_zip(*, bad_reference: bool = False, overnight: bool = False) -> bytes:
    files = {
        "stops.txt": "stop_id,stop_name,stop_code\nA,Alpha,A\nB,Bravo,B\n",
        "routes.txt": "route_id,route_short_name,route_long_name,route_type\nR,1,Real route,2\n",
        "trips.txt": "route_id,service_id,trip_id,trip_headsign,direction_id\nR,WEEKDAY,T1,Bravo,0\n",
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            f"T1,08:00:00,08:01:00,{'UNKNOWN' if bad_reference else 'A'},1\n"
            f"T1,{'25:00:00' if overnight else '09:00:00'},{'25:01:00' if overnight else '09:01:00'},B,2\n"
        ),
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
            "WEEKDAY,1,1,1,1,1,0,0,20260101,20261231\n"
        ),
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return stream.getvalue()


def test_gtfs_static_validates_references_and_preserves_checksum() -> None:
    payload = _gtfs_zip()
    feed = parse_gtfs_static(payload, _source(payload))

    assert feed.record_count == 7
    assert len(feed.stops) == 2
    assert feed.stop_times[0].arrival_time == "08:00:00"
    assert feed.source.checksum_sha256 == __import__("hashlib").sha256(payload).hexdigest()
    assert feed.source.source_type is TimetableSourceType.REAL_HISTORICAL


def test_gtfs_static_rejects_unknown_stop_reference() -> None:
    payload = _gtfs_zip(bad_reference=True)

    with pytest.raises(TimetableIngestionError, match="unknown trip or stop"):
        parse_gtfs_static(payload, _source(payload))


def test_feed_rejects_a_checksum_not_matching_downloaded_bytes() -> None:
    payload = _gtfs_zip()
    source = _source(payload).model_copy(update={"checksum_sha256": "0" * 64})

    with pytest.raises(TimetableIngestionError, match="checksum"):
        parse_gtfs_static(payload, source)


def test_gtfs_static_preserves_overnight_gtfs_service_time() -> None:
    payload = _gtfs_zip(overnight=True)
    feed = parse_gtfs_static(payload, _source(payload))

    assert feed.stop_times[1].arrival_time == "25:00:00"


def test_gtfs_realtime_json_normalizes_observations() -> None:
    payload = json.dumps(
        {
            "header": {"gtfs_realtime_version": "2.0", "timestamp": 1789344000},
            "entity": [
                {
                    "id": "update-1",
                    "trip_update": {
                        "trip": {"trip_id": "T1", "route_id": "R1"},
                        "stop_time_update": [
                            {
                                "stop_id": "A",
                                "stop_sequence": 1,
                                "arrival": {"time": 1789344300, "delay": 30},
                            }
                        ],
                    },
                },
                {
                    "id": "vehicle-1",
                    "vehicle": {
                        "trip": {"trip_id": "T1"},
                        "vehicle": {"id": "V1"},
                        "position": {"latitude": 21.1, "longitude": 79.1, "speed": 12.5},
                        "timestamp": 1789344300,
                    },
                },
                {
                    "id": "alert-1",
                    "alert": {
                        "cause": "MAINTENANCE",
                        "effect": "DETOUR",
                        "header_text": {"translation": [{"text": "Track work"}]},
                    },
                },
            ],
        }
    ).encode()
    feed = parse_gtfs_realtime(payload, _source(payload, source_type=TimetableSourceType.LIVE_PROVIDER))

    assert feed.gtfs_realtime_version == "2.0"
    assert feed.header_timestamp is not None
    assert feed.source.observed_at == feed.header_timestamp
    assert feed.trip_updates[0].stop_time_updates[0]["arrival"]["time_iso"].endswith("+00:00")
    assert feed.vehicle_positions[0].latitude == 21.1
    assert feed.alerts[0].header_text == "Track work"


def test_gtfs_realtime_accepts_standard_protobuf_wire_format() -> None:
    gtfs_realtime_pb2 = pytest.importorskip("google.transit.gtfs_realtime_pb2")
    message = gtfs_realtime_pb2.FeedMessage()
    message.header.gtfs_realtime_version = "2.0"
    message.header.timestamp = 1789344000
    entity = message.entity.add()
    entity.id = "protobuf-trip"
    entity.trip_update.trip.trip_id = "T1"
    payload = message.SerializeToString()

    feed = parse_gtfs_realtime(
        payload,
        _source(payload, source_type=TimetableSourceType.LIVE_PROVIDER),
    )

    assert feed.record_count == 1
    assert feed.trip_updates[0].trip_id == "T1"


def test_gtfs_realtime_rejects_duplicate_entity_ids() -> None:
    payload = json.dumps(
        {
            "header": {"gtfs_realtime_version": "2.0"},
            "entity": [{"id": "same"}, {"id": "same"}],
        }
    ).encode()

    with pytest.raises(TimetableIngestionError, match="duplicate"):
        parse_gtfs_realtime(payload, _source(payload, source_type=TimetableSourceType.LIVE_PROVIDER))


def test_india_open_data_accepts_records_and_keeps_raw_provenance() -> None:
    payload = json.dumps(
        {
            "records": [
                {
                    "Train No": "12345",
                    "Train Name": "Real Express",
                    "Source Station Code": "AAA",
                    "Destination Station Code": "BBB",
                    "Departure Time": "23:40",
                    "Arrival Time": "01:20",
                    "Date": "2026-09-14",
                }
            ]
        }
    ).encode()
    feed = parse_india_open_data(
        payload,
        source_metadata(
            provider_key="india_open_data",
            provider_name="Government export",
            source_url="https://example.gov.in/timetable.json",
            source_type=TimetableSourceType.PUBLIC_OPEN_DATA,
            payload=payload,
            fetched_at=datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc),
        ),
    )

    assert feed.rows[0].train_code == "12345"
    assert feed.rows[0].scheduled_departure == "23:40:00"
    assert feed.rows[0].scheduled_arrival == "01:20:00"
    assert feed.rows[0].service_date == "2026-09-14"
    assert feed.rows[0].raw_record["Train Name"] == "Real Express"


def test_india_open_data_rejects_unmapped_operational_columns() -> None:
    payload = json.dumps({"records": [{"train": "12345", "station": "AAA"}]}).encode()
    with pytest.raises(TimetableIngestionError, match="missing"):
        parse_india_open_data(payload, _source(payload, source_type=TimetableSourceType.PUBLIC_OPEN_DATA))
