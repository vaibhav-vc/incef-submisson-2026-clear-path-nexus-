from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.planner import dispatch_journey, dispatch_route, dispatch_schedule
from app.schemas.route import JourneyDispatchRequest


@pytest.mark.asyncio
async def test_route_level_dispatch_is_retired_before_database_access() -> None:
    with pytest.raises(HTTPException) as exc:
        await dispatch_route(uuid4(), db=None, user=None)  # type: ignore[arg-type]
    assert exc.value.status_code == 410
    assert "authorized control" in exc.value.detail


@pytest.mark.asyncio
async def test_journey_dispatch_is_retired_before_database_access() -> None:
    with pytest.raises(HTTPException) as exc:
        await dispatch_journey(
            JourneyDispatchRequest(route_ids=[uuid4()]),
            db=None,  # type: ignore[arg-type]
            user=None,  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_schedule_dispatch_is_retired_before_database_access() -> None:
    with pytest.raises(HTTPException) as exc:
        await dispatch_schedule(uuid4(), db=None, user=None)  # type: ignore[arg-type]
    assert exc.value.status_code == 410
