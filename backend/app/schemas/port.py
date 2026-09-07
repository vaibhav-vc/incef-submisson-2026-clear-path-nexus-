from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PortBerthResponse(BaseModel):
    id: UUID
    port_name: str
    berth_identifier: str
    vessel_name: str | None
    window_start: datetime
    window_end: datetime

    model_config = {"from_attributes": True}


class PortSyncStatus(BaseModel):
    aligned: bool
    berth_id: str
    vessel_status: str
    loading_window_start: datetime
    loading_window_end: datetime
    sync_score: float
    warning: str | None = None
