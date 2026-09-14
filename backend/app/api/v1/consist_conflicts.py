"""Carriage manifests and network conflict API.

All writes are owner-scoped.  Conflict assessment intentionally reads the
network-wide schedule/window set because a train owned by another operator can
still occupy the same section.  The response only exposes the minimum fields
needed to explain a conflict; operational authority remains external.
"""

from __future__ import annotations

from datetime import timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.security import CurrentUser, get_current_user
from app.models.consist import CarriageLoad, RouteOccupationWindow, TrackSectionPolicy, TrainConsist
from app.models.route import TrainSchedule
from app.schemas.consist import (
    NetworkConflictResponse,
    OccupationWindowBatch,
    OccupationWindowResponse,
    TrackSectionPolicyCreate,
    TrackSectionPolicyResponse,
    TrainConsistCreate,
    TrainConsistResponse,
)
from app.services.conflict_engine import assess_network_conflicts, canonical_manifest_checksum


router = APIRouter(dependencies=[Depends(get_current_user)])


async def _owned_schedule(
    db: AsyncSession,
    schedule_id: UUID,
    user_id: str,
    *,
    with_relations: bool = False,
) -> TrainSchedule:
    statement = select(TrainSchedule).where(
        TrainSchedule.id == schedule_id,
        TrainSchedule.user_id == user_id,
    )
    if with_relations:
        statement = statement.options(
            selectinload(TrainSchedule.consist).selectinload(TrainConsist.carriages),
            selectinload(TrainSchedule.occupation_windows),
        )
    schedule = await db.scalar(statement)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


def _consist_response(consist: TrainConsist) -> TrainConsistResponse:
    # model_validate reads the derived aggregate properties and the ORM
    # ``metadata_json`` attribute through the schema alias.
    return TrainConsistResponse.model_validate(consist)


@router.get(
    "/schedules/{schedule_id}/consist",
    response_model=TrainConsistResponse,
)
async def get_train_consist(
    schedule_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> TrainConsistResponse:
    schedule = await _owned_schedule(db, schedule_id, user.id, with_relations=True)
    if schedule.consist is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No carriage-level consist manifest exists for this schedule",
        )
    return _consist_response(schedule.consist)


@router.put(
    "/schedules/{schedule_id}/consist",
    response_model=TrainConsistResponse,
)
async def replace_train_consist(
    schedule_id: UUID,
    payload: TrainConsistCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> TrainConsistResponse:
    schedule = await _owned_schedule(db, schedule_id, user.id, with_relations=True)
    if schedule.schedule_status == "DISPATCHED":
        raise HTTPException(status_code=409, detail="Dispatched schedules cannot change consist")

    expected_checksum = canonical_manifest_checksum(payload)
    if payload.manifest_checksum.lower() != expected_checksum:
        raise HTTPException(
            status_code=422,
            detail=(
                "manifest_checksum does not match the normalized carriage manifest; "
                f"expected {expected_checksum}"
            ),
        )

    if schedule.consist is not None:
        await db.delete(schedule.consist)
        await db.flush()

    consist = TrainConsist(
        id=uuid4(),
        schedule_id=schedule.id,
        user_id=user.id,
        source_type=payload.source_type,
        source_reference=payload.source_reference.strip(),
        manifest_checksum=payload.manifest_checksum.lower(),
        observed_at=payload.observed_at.astimezone(timezone.utc),
        fetched_at=payload.fetched_at.astimezone(timezone.utc),
        verification_state=payload.verification_state,
        metadata_json=payload.metadata,
    )
    consist.carriages = [
        CarriageLoad(
            id=uuid4(),
            position_in_train=item.position_in_train,
            carriage_identifier=item.carriage_identifier.strip(),
            carriage_type=item.carriage_type.strip(),
            tare_weight_tons=item.tare_weight_tons,
            cargo_weight_tons=item.cargo_weight_tons,
            gross_weight_tons=item.gross_weight_tons,
            length_m=item.length_m,
            width_m=item.width_m,
            height_m=item.height_m,
            axle_count=item.axle_count,
            brake_percentage=item.brake_percentage,
            load_distribution=item.load_distribution,
            hazardous_material_class=item.hazardous_material_class,
            source_type=item.source_type,
            source_reference=item.source_reference.strip(),
            source_checksum=item.source_checksum.lower(),
            observed_at=item.observed_at.astimezone(timezone.utc),
        )
        for item in payload.carriages
    ]
    db.add(consist)
    await db.commit()
    # Reload through the async ORM rather than touching a lazy relationship
    # after commit (which would otherwise risk a MissingGreenlet in asyncpg).
    persisted = await db.scalar(
        select(TrainConsist)
        .where(TrainConsist.id == consist.id)
        .options(selectinload(TrainConsist.carriages))
    )
    if persisted is None:
        raise HTTPException(status_code=500, detail="Persisted consist could not be reloaded")
    return _consist_response(persisted)


@router.put(
    "/schedules/{schedule_id}/occupation-windows",
    response_model=list[OccupationWindowResponse],
)
async def replace_occupation_windows(
    schedule_id: UUID,
    payload: OccupationWindowBatch,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[OccupationWindowResponse]:
    schedule = await _owned_schedule(db, schedule_id, user.id, with_relations=True)
    if schedule.schedule_status == "DISPATCHED":
        raise HTTPException(status_code=409, detail="Dispatched schedules cannot change occupation windows")
    if schedule.consist is None:
        raise HTTPException(
            status_code=409,
            detail="Create and verify a carriage-level consist before section occupation windows",
        )

    total_length = schedule.consist.total_length_m
    for item in payload.windows:
        if abs(item.train_length_m - total_length) > 0.001:
            raise HTTPException(
                status_code=422,
                detail=(
                    "train_length_m must match the sum of carriage lengths "
                    f"({total_length:.3f} m)"
                ),
            )

    await db.execute(delete(RouteOccupationWindow).where(RouteOccupationWindow.schedule_id == schedule.id))
    rows = [
        RouteOccupationWindow(
            id=uuid4(),
            schedule_id=schedule.id,
            segment_id=item.segment_id,
            sequence_in_route=item.sequence_in_route,
            entry_time=item.entry_time.astimezone(timezone.utc),
            exit_time=item.exit_time.astimezone(timezone.utc),
            direction=item.direction,
            train_length_m=item.train_length_m,
            expected_speed_kmh=item.expected_speed_kmh,
            source_type=item.source_type,
            source_reference=item.source_reference.strip(),
            source_checksum=item.source_checksum.lower(),
            observed_at=item.observed_at.astimezone(timezone.utc),
            fetched_at=item.fetched_at.astimezone(timezone.utc),
        )
        for item in payload.windows
    ]
    db.add_all(rows)
    await db.commit()
    return [OccupationWindowResponse.model_validate(row) for row in rows]


@router.put(
    "/track-section-policies/{segment_id}",
    response_model=TrackSectionPolicyResponse,
)
async def upsert_track_section_policy(
    segment_id: UUID,
    payload: TrackSectionPolicyCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> TrackSectionPolicyResponse:
    # A section policy changes the evidence used by every train on that
    # segment. Only an admin-controlled operational role may publish it; a
    # generic authenticated account must not be able to manufacture a
    # headway rule that makes a conflict appear clear.
    allowed_roles = {item.casefold().strip() for item in settings.APPROVAL_ALLOWED_ROLES}
    if user.role.casefold().strip() not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An authorized operational role is required to publish track policies",
        )
    if payload.segment_id != segment_id:
        raise HTTPException(status_code=422, detail="Path segment_id does not match payload")
    existing = await db.scalar(
        select(TrackSectionPolicy).where(TrackSectionPolicy.segment_id == segment_id).with_for_update()
    )
    values = {
        "single_track": payload.single_track,
        "minimum_headway_seconds": payload.minimum_headway_seconds,
        "policy_version": payload.policy_version,
        "source_type": payload.source_type,
        "source_reference": payload.source_reference.strip(),
        "source_checksum": payload.source_checksum.lower(),
        "observed_at": payload.observed_at.astimezone(timezone.utc),
        "fetched_at": payload.fetched_at.astimezone(timezone.utc),
    }
    if existing is None:
        existing = TrackSectionPolicy(id=uuid4(), segment_id=segment_id, **values)
        db.add(existing)
    else:
        for key, value in values.items():
            setattr(existing, key, value)
    await db.commit()
    await db.refresh(existing)
    return TrackSectionPolicyResponse.model_validate(existing)


@router.get(
    "/schedules/{schedule_id}/conflicts",
    response_model=NetworkConflictResponse,
)
async def assess_schedule_conflicts(
    schedule_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> NetworkConflictResponse:
    candidate = await _owned_schedule(db, schedule_id, user.id, with_relations=True)
    candidate_ids = {item.segment_id for item in candidate.occupation_windows}
    policies = []
    if candidate_ids:
        policy_result = await db.execute(
            select(TrackSectionPolicy).where(TrackSectionPolicy.segment_id.in_(candidate_ids))
        )
        policies = list(policy_result.scalars().all())

    # Network-wide scope is intentional: a different owner's train can still
    # occupy the same segment and must not be invisible to conflict detection.
    schedule_result = await db.execute(
        select(TrainSchedule)
        .where(TrainSchedule.schedule_status != "CANCELLED")
        .options(selectinload(TrainSchedule.occupation_windows))
    )
    all_schedules = list(schedule_result.scalars().all())
    network_ids = [item.id for item in all_schedules]
    others = [item for item in all_schedules if item.id != candidate.id]
    assessment = assess_network_conflicts(
        candidate,
        candidate.occupation_windows,
        others,
        policies,
        network_schedule_ids=network_ids,
    )
    candidate.conflict_status = assessment.status
    candidate.conflict_reason = assessment.explanation
    if candidate.schedule_status not in {"DISPATCHED", "CANCELLED"}:
        candidate.schedule_status = "READY" if assessment.status == "CLEAR" else "PLANNED"
    await db.commit()
    return NetworkConflictResponse.model_validate(assessment.as_dict())
