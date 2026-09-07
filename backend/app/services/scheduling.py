from __future__ import annotations

from datetime import datetime

from typing import Any

def _overlaps(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return start_a < end_b and start_b < end_a


def assess_schedule(
    schedule: Any,
    others: list[Any],
) -> tuple[str, str | None]:
    """Assess only stored operator schedules and declared berth windows.

    Maintenance or signalling restrictions must arrive through an authorized
    operations feed; this function never invents a fixed network block.
    """
    dep = schedule.scheduled_departure
    arr = schedule.scheduled_arrival

    # Operator berth window: arrival outside the supplied window is a warning,
    # not a fabricated hard block.
    if schedule.berth_window_start and schedule.berth_window_end:
        if not (schedule.berth_window_start <= arr <= schedule.berth_window_end):
            return (
                "WARNING",
                "Arrival falls outside the operator berth window. Shift departure to reduce terminal waiting.",
            )

    # Coarse shared-corridor proxy for MVP: same destination and overlapping
    # movement windows. A real signalling/section-occupation engine can replace
    # this later without changing the API contract.
    for other in others:
        if other.id == schedule.id or other.schedule_status == "CANCELLED":
            continue
        same_constrained_end = other.dest_station_code == schedule.dest_station_code
        if same_constrained_end and _overlaps(
            dep, arr, other.scheduled_departure, other.scheduled_arrival
        ):
            return (
                "WARNING",
                f"Train-slot overlap with {other.train_code} on the approach to {schedule.dest_station_code}. Recommended shift: +30 min.",
            )

    return "CLEAR", None
