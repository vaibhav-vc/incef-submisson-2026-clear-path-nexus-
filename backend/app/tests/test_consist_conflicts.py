from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock, Mock

import pytest

from app.schemas.consist import CarriageLoadCreate, TrainConsistCreate
from app.services.conflict_engine import assess_network_conflicts, canonical_manifest_checksum


NOW = datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("field", ["tare_weight_tons", "cargo_weight_tons", "gross_weight_tons", "length_m", "width_m", "height_m", "brake_percentage"])
@pytest.mark.parametrize("value", [float("inf"), float("nan"), float("-inf")])
def test_carriage_rejects_nonfinite_measurements(field, value):
    with pytest.raises(ValueError):
        CarriageLoadCreate(**{**_carriage().model_dump(), field: value})


@pytest.mark.parametrize("field", ["carriage_identifier", "carriage_type", "source_reference"])
def test_carriage_rejects_blank_identity_and_source(field):
    with pytest.raises(ValueError):
        CarriageLoadCreate(**{**_carriage().model_dump(), field: "   "})


def _manifest(carriages):
    return TrainConsistCreate(
        manifest_checksum="a" * 64, expected_carriage_count=len(carriages),
        source_type="AUTHORIZED_FEED", source_reference="https://railway.example.test/manifest/1",
        observed_at=NOW, fetched_at=NOW, carriages=carriages,
    )


def test_manifest_rejects_duplicate_physical_carriage():
    duplicate = {**_carriage(position=2).model_dump(), "carriage_identifier": " W1 "}
    with pytest.raises(ValueError, match="identifiers must be unique"):
        _manifest([_carriage(), CarriageLoadCreate(**duplicate)])


@pytest.mark.asyncio
async def test_consist_endpoint_constructs_and_saves_carriages(monkeypatch):
    from app.api.v1 import consist_conflicts as api

    schedule = SimpleNamespace(id=uuid4(), schedule_status="PLANNED", consist=None)
    monkeypatch.setattr(api, "_owned_schedule", AsyncMock(return_value=schedule))
    # Keep real ORM construction; only database I/O and response reload are mocked.
    db = SimpleNamespace(add=Mock(), commit=AsyncMock(), scalar=AsyncMock(return_value=object()))
    monkeypatch.setattr(api, "_consist_response", lambda value: value)
    payload = _manifest([_carriage()])
    payload.manifest_checksum = canonical_manifest_checksum(payload)
    await api.replace_train_consist(schedule.id, payload, db, SimpleNamespace(id="owner"))
    persisted = db.add.call_args.args[0]
    assert persisted.verification_state == "UNVERIFIED"
    assert len(persisted.carriages) == 1
    assert persisted.carriages[0].carriage_identifier == "W1"
    db.commit.assert_awaited_once()


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
        verification_state="VERIFIED",
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
        verification_state="VERIFIED",
        observed_at=NOW,
        fetched_at=NOW,
    )


def test_consist_requires_contiguous_carriage_positions_and_real_source():
    with pytest.raises(ValueError, match="contiguous"):
        TrainConsistCreate(
            manifest_checksum="a" * 64,
            expected_carriage_count=2,
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
        expected_carriage_count=1,
        source_type="AUTHORIZED_FEED",
        source_reference="https://railway.example.test/manifest/1",
        observed_at=NOW,
        fetched_at=NOW,
        carriages=[_carriage()],
    )
    assert canonical_manifest_checksum(payload) == canonical_manifest_checksum(payload)
    assert len(canonical_manifest_checksum(payload)) == 64


def test_consist_rejects_a_contiguous_but_truncated_manifest():
    with pytest.raises(ValueError, match="manifest is incomplete"):
        TrainConsistCreate(
            manifest_checksum="a" * 64,
            expected_carriage_count=3,
            source_type="AUTHORIZED_FEED",
            source_reference="https://railway.example.test/manifest/1",
            observed_at=NOW,
            fetched_at=NOW,
            carriages=[_carriage(position=1), _carriage(position=2)],
        )


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


def test_network_engine_never_returns_clear_for_user_declared_sources():
    segment_id = uuid4()
    candidate = SimpleNamespace(id=uuid4(), train_code="FREIGHT-1", schedule_status="PLANNED")
    window = _window(segment_id, start_minute=0, end_minute=5)
    window.verification_state = "UNVERIFIED"
    result = assess_network_conflicts(candidate, [window], [], [_policy(segment_id)])
    assert result.status == "UNAVAILABLE"
    assert any("SOURCE_AUTHENTICATION_UNVERIFIED" in item for item in result.missing_evidence)
