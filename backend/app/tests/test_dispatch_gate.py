from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1.planner import (
    _require_current_approval,
    _require_schedule_matches_evidence,
)
from app.schemas.route import JourneyDispatchRequest


def test_dispatch_approval_must_match_current_evidence_root() -> None:
    route = SimpleNamespace(
        approved_at=datetime.now(timezone.utc),
        approved_by_user_id="operator-a",
        approved_by_role="operator",
        approval_evidence_checksum="a" * 64,
    )
    snapshot = SimpleNamespace(evidence_root_checksum="b" * 64)

    with pytest.raises(HTTPException) as exc:
        _require_current_approval(route, snapshot)

    assert exc.value.status_code == 409


def test_dispatch_approval_accepts_receipt_bound_to_current_root() -> None:
    checksum = "a" * 64
    route = SimpleNamespace(
        approved_at=datetime.now(timezone.utc),
        approved_by_user_id="operator-a",
        approved_by_role="operator",
        approval_evidence_checksum=checksum,
    )
    snapshot = SimpleNamespace(evidence_root_checksum=checksum)

    _require_current_approval(route, snapshot)


def test_atomic_journey_dispatch_rejects_duplicate_legs() -> None:
    route_id = uuid4()
    with pytest.raises(ValidationError):
        JourneyDispatchRequest(route_ids=[route_id, route_id])


class _ScalarDb:
    def __init__(self, value: object) -> None:
        self.value = value

    async def scalar(self, _query: object) -> object:
        return self.value


@pytest.mark.asyncio
async def test_schedule_dispatch_must_match_sealed_port_timing() -> None:
    evaluated_at = datetime(2026, 8, 31, 10, tzinfo=timezone.utc)
    start = datetime(2026, 9, 1, 9, tzinfo=timezone.utc)
    end = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    record = SimpleNamespace(
        value_summary={
            "evaluated_at": evaluated_at.isoformat(),
            "train_arrival_hours": 24,
            "loading_window": {"start": start.isoformat(), "end": end.isoformat()},
        }
    )
    schedule = SimpleNamespace(
        scheduled_arrival=evaluated_at.replace(day=1, month=9),
        berth_window_start=start,
        berth_window_end=end,
    )

    await _require_schedule_matches_evidence(
        _ScalarDb(record), schedule, SimpleNamespace(id=uuid4())
    )


@pytest.mark.asyncio
async def test_schedule_dispatch_rejects_timing_changed_after_evaluation() -> None:
    evaluated_at = datetime(2026, 8, 31, 10, tzinfo=timezone.utc)
    record = SimpleNamespace(
        value_summary={
            "evaluated_at": evaluated_at.isoformat(),
            "train_arrival_hours": 24,
            "loading_window": None,
        }
    )
    schedule = SimpleNamespace(
        scheduled_arrival=evaluated_at.replace(day=2, month=9),
        berth_window_start=None,
        berth_window_end=None,
    )

    with pytest.raises(HTTPException, match="arrival does not match"):
        await _require_schedule_matches_evidence(
            _ScalarDb(record), schedule, SimpleNamespace(id=uuid4())
        )
