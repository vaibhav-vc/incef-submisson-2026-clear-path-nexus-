from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.v1.speed import speed_risk_advisory


@pytest.mark.asyncio
async def test_public_speed_advisory_is_retired_before_using_caller_claims() -> None:
    with pytest.raises(HTTPException) as exc:
        await speed_risk_advisory(None, AsyncMock())  # type: ignore[arg-type]
    assert exc.value.status_code == 410
    assert "certified movement-authority" in exc.value.detail
