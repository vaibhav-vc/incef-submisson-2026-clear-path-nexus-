"""Evidence-backed speed-risk advisory endpoint."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import CurrentUser, get_current_user
from app.schemas.speed import SpeedRiskAdvisoryRequest, SpeedRiskAdvisoryResponse

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post("/advisory", response_model=SpeedRiskAdvisoryResponse)
async def speed_risk_advisory(
    payload: SpeedRiskAdvisoryRequest,
    _user: CurrentUser = Depends(get_current_user),
) -> SpeedRiskAdvisoryResponse:
    """Retired boundary for an unsafe caller-asserted authority contract.

    The pure calculation remains available to controlled simulations and unit
    tests. A network API must not emit a driver-facing number until its inputs
    are loaded from authenticated, certified, territory-bound records rather
    than accepted as authority claims in the request body.
    """

    del payload
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "The public speed-advisory endpoint is retired. Numerical speed guidance "
            "requires certified movement-authority, restriction, braking, consist and "
            "ATP/Kavach interfaces; use the pure calculator only for labelled simulation."
        ),
    )
