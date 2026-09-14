from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.schemas.consist import CarriageLoadCreate, TrainConsistCreate
from app.services.conflict_engine import assess_network_conflicts, canonical_manifest_checksum


NOW = datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc)


def _carriage(*, position: int = 1, source_type: str = "AUTHORIZED_FEED") -> CarriageLoadCreate:
    return CarriageLoadCreate(
        position_in_train=position,
        carriage_identifier=f"W{position}",
        carriage_type="covered-wagon",
        tare_weight_tons=20,
        cargo_weight_tons=30,
        gross_weight_tons=50,
        length_m=20,
        width_m=3,
        height_m=4,
        axle_count=4,
        brake_percentage=80,
        source_type=source_type,
        source_reference="https://railway.example.test/manifest/1",
        source_checksum="a" * 64,
        observed_at=NOW,
    )


def _window(segment_id, *, start_minute: int, end_minute: int, direction="FORWARD"):
    return SimpleNamespace(
        id=uuid4(),
        segment_id=segment_id,
        entry_time=NOW + timedelta(minutes=start_minute),
        exit_time=NOW + timedelta(minutes=end_minute),
        direction=direction,
        train_length_m=20,
        source_type="AUTHORIZED_FEED",
        source_reference="https://railway.example.test/occupancy/1",
        source_checksum="b" * 64,
        observed_at=NOW,
        fetched_at=NOW,
    )


def _policy(segment_id, *, single_track=False, headway=600):
    return SimpleNamespace(
        segment_id=segment_id,
        single_track=single_track,
        minimum_headway_seconds=headway,
        source_type="AUTHORIZED_FEED",
        source_reference="https://railway.example.test/policies/1",
        source_checksum="c" * 64,
        observed_at=NOW,
        fetched_at=NOW,
    )


def test_consist_requires_contiguous_carriage_positions_and_real_source():
    with pytest.raises(ValueError, match="contiguous"):
        TrainConsistCreate(
            manifest_checksum="a" * 64,
            source_type="AUTHORIZED_FEED",
            source_reference="https://railway.example.test/manifest/1",
            observed_at=NOW,
            fetched_at=NOW,
            carriages=[_carriage(position=1), _carriage(position=3)],
        )

    with pytest.raises(ValueError, match="gross_weight"):
        CarriageLoadCreate(
            **{
                **_carriage().model_dump(),
                "gross_weight_tons": 51,
            }
        )


def test_manifest_checksum_is_deterministic_and_carriage_level():
    payload = TrainConsistCreate(
        manifest_checksum="a" * 64,
        source_type="AUTHORIZED_FEED",
        source_reference="https://railway.example.test/manifest/1",
        observed_at=NOW,
        fetched_at=NOW,
        carriages=[_carriage()],
    )
    assert canonical_manifest_checksum(payload) == canonical_manifest_checksum(payload)
    assert len(canonical_manifest_checksum(payload)) == 64


def test_network_engine_blocks_same_section_overlap_and_headway():
    segment_id = uuid4()
    candidate = SimpleNamespace(id=uuid4(), train_code="FREIGHT-1", schedule_status="PLANNED")
    other = SimpleNamespace(
        id=uuid4(),
        train_code="PASSENGER-1",
        schedule_status="PLANNED",
        occupation_windows=[_window(segment_id, start_minute=2, end_minute=7)],
    )
    result = assess_network_conflicts(
        candidate,
        [_window(segment_id, start_minute=0, end_minute=5)],
        [other],
        [_policy(segment_id)],
    )
    assert result.status == "BLOCKED"
    assert {item.conflict_type for item in result.conflicts} == {
        "SAME_SECTION_OVERLAP",
        "MINIMUM_HEADWAY",
    }


def test_network_engine_blocks_opposing_single_track_movement():
    segment_id = uuid4()
    candidate = SimpleNamespace(id=uuid4(), train_code="FREIGHT-1", schedule_status="PLANNED")
    other = SimpleNamespace(
        id=uuid4(),
        train_code="PASSENGER-1",
        schedule_status="PLANNED",
        occupation_windows=[
            _window(segment_id, start_minute=2, end_minute=7, direction="REVERSE")
        ],
    )
    result = assess_network_conflicts(
        candidate,
        [_window(segment_id, start_minute=0, end_minute=5)],
        [other],
        [_policy(segment_id, single_track=True)],
    )
    assert result.status == "BLOCKED"
    assert result.conflicts[0].conflict_type == "OPPOSING_SINGLE_TRACK"


def test_network_engine_fails_closed_when_policy_or_network_coverage_is_missing():
    segment_id = uuid4()
    candidate = SimpleNamespace(id=uuid4(), train_code="FREIGHT-1", schedule_status="PLANNED")
    result = assess_network_conflicts(
        candidate,
        [_window(segment_id, start_minute=0, end_minute=5)],
        [],
        [],
    )
    assert result.status == "UNAVAILABLE"
    assert f"TRACK_POLICY_MISSING:{segment_id}" in result.missing_evidence


def test_network_engine_never_returns_clear_for_historical_replay():
    segment_id = uuid4()
    candidate = SimpleNamespace(id=uuid4(), train_code="FREIGHT-1", schedule_status="PLANNED")
    window = _window(segment_id, start_minute=0, end_minute=5)
    window.source_type = "REAL_HISTORICAL"
    policy = _policy(segment_id)
    result = assess_network_conflicts(candidate, [window], [], [policy])
    assert result.status == "UNAVAILABLE"
    assert result.evidence_state == "HISTORICAL_REPLAY"
