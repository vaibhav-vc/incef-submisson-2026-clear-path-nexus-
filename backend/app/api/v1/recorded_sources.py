"""Read-only provenance view of a dated, non-operational publisher capture."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import settings
from app.core.security import CurrentUser, get_current_user
from app.services.recorded_source import inspect_recorded_source


router = APIRouter()


@router.get("/recorded-source")
def recorded_source(_user: CurrentUser = Depends(get_current_user)) -> dict:
    if not settings.RECORDED_SOURCE_SNAPSHOT_DIR:
        raise HTTPException(status_code=404, detail="No recorded source is configured")
    try:
        return inspect_recorded_source(
            Path(settings.RECORDED_SOURCE_SNAPSHOT_DIR),
            settings.RECORDED_SOURCE_MANIFEST_SHA256,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=503, detail="Recorded source could not be verified"
        ) from exc
