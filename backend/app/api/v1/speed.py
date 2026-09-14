"""Evidence-backed speed-risk advisory endpoint."""

from fastapi import APIRouter, Depends

from app.core.security import CurrentUser, get_current_user
from app.schemas.speed import SpeedRiskAdvisoryRequest, SpeedRiskAdvisoryResponse
from app.services.speed_advisory import calculate_speed_risk_advisory

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post("/advisory", response_model=SpeedRiskAdvisoryResponse)
async def speed_risk_advisory(
    payload: SpeedRiskAdvisoryRequest,
    _user: CurrentUser = Depends(get_current_user),
) -> SpeedRiskAdvisoryResponse:
    """Calculate a read-only advisory from caller-supplied real evidence."""

    return calculate_speed_risk_advisory(payload)
