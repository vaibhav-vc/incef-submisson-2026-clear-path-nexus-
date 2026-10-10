"""Nexus Cab: the driver advisory view.

The cab renders the *controller-approved* plan only. It has no route choice and
never reads the latest unapproved recommendation, so the driver cannot be shown
a plan a controller has not approved. Status degrades to DATA UNAVAILABLE or
HOLD-FOR-CONTROLLER instead of showing confident guidance on weak evidence.
"""

from __future__ import annotations

from typing import Any

from india_rail.railguard.evidence import AGING, FRESH
from india_rail.railguard.model import AUTHORITY, CAB_FOOTER
from india_rail.railguard.stress import running_speed
from india_rail.railguard.threats import SEVERITY_ORDER

NORMAL, CAUTION, HOLD_FOR_CONTROLLER, DATA_UNAVAILABLE = "NORMAL", "CAUTION", "HOLD-FOR-CONTROLLER", "DATA UNAVAILABLE"
LOOKAHEAD_KM = 12.0


def _relation(engine: Any, tid: str, other: str) -> str:
    mine, theirs = set(engine.route_ahead(tid)), set(engine.route_ahead(other))
    if mine & theirs:
        return "SAME CORRIDOR AHEAD"
    my_nodes = {n for sid in mine for n in (engine.net.sections[sid].a, engine.net.sections[sid].b)}
    their_nodes = {n for sid in theirs for n in (engine.net.sections[sid].a, engine.net.sections[sid].b)}
    return "CROSSING PATH" if my_nodes & their_nodes else "DIVERGING"


def build_advisory(engine: Any, tid: str) -> dict[str, Any]:
    train = engine.trains[tid]
    net, now = engine.net, engine.t
    position_state = engine.evidence.state_of(f"position:{tid}", now)
    approved = engine.approved.get(tid)
    hold = engine.controller_hold.get(tid)
    threats = engine.threats.for_train(tid)
    top_severity = max((SEVERITY_ORDER[t.severity] for t in threats), default=-1)

    if train.finished:
        status = NORMAL
    elif position_state not in (FRESH, AGING) or train.sensor_offline:
        status = DATA_UNAVAILABLE
    elif approved is None or hold is not None or top_severity >= SEVERITY_ORDER["CRITICAL"]:
        status = HOLD_FOR_CONTROLLER
    elif top_severity >= SEVERITY_ORDER["CAUTION"]:
        status = CAUTION
    else:
        status = NORMAL

    ahead = engine.route_ahead(tid) if approved else []
    current = train.section_id
    nodes_ahead: list[str] = []
    if approved:
        traversals = approved["plan"]["traversals"]
        for trav in traversals:
            if trav["section_id"] in ahead:
                nodes_ahead.append(trav["to_node"])
    next_waypoint = nodes_ahead[0] if nodes_ahead else None

    # Distance to events along the approved route ahead.
    events = []
    cursor = 0.0  # km from the train to the start of the next section ahead
    for i, sid in enumerate(ahead):
        section = net.sections[sid]
        if i == 0 and current == sid:
            start, cursor = 0.0, section.length_km - train.offset_km
        else:
            start, cursor = cursor, cursor + section.length_km
        if start > LOOKAHEAD_KM:
            break
        if section.temp_restriction_kmph:
            events.append(
                {
                    "kind": "RESTRICTION",
                    "section": sid,
                    "in_km": round(start, 1),
                    "text": f"{section.temp_restriction_kmph:g} km/h on {sid}",
                }
            )
        if section.condition < 0.5:
            events.append(
                {
                    "kind": "TRACK_CAUTION",
                    "section": sid,
                    "in_km": round(start, 1),
                    "text": f"Track condition caution on {sid}",
                }
            )
        if section.weather_alert:
            events.append(
                {
                    "kind": "WEATHER",
                    "section": sid,
                    "in_km": round(start, 1),
                    "text": f"{section.weather_alert.replace('_', ' ').title()} on {sid}",
                }
            )
        if section.obstacle:
            events.append(
                {"kind": "OBSTACLE", "section": sid, "in_km": round(start, 1), "text": f"Obstacle report on {sid}"}
            )

    # Advisory target-speed band (simulation only), shown only once the train is running.
    departure_min = approved["plan"]["traversals"][0]["enter"] if approved and approved["plan"]["traversals"] else None
    waiting = (
        approved is not None
        and current is None
        and train.from_node == train.origin
        and departure_min is not None
        and now / 60 < departure_min
    )
    band = None
    if status in (NORMAL, CAUTION) and approved and not train.finished and not waiting:
        sid = current or (ahead[0] if ahead else None)
        if sid:
            target = running_speed(train, net.sections[sid])
            near = [e for e in events if e["kind"] == "RESTRICTION" and e["in_km"] <= 2.0]
            if near:
                target = min(target, net.sections[near[0]["section"]].temp_restriction_kmph)
            band = [round(target * 0.9), round(target)]
    plan_hold = None
    if approved and approved["plan"].get("hold_node") and approved["plan"]["hold_node"] in nodes_ahead:
        plan_hold = {"node": approved["plan"]["hold_node"], "minutes": approved["plan"]["hold_min"]}

    nearby = []
    for other, other_train in engine.trains.items():
        if other == tid or other_train.finished:
            continue
        other_state = engine.evidence.state_of(f"position:{other}", now)
        separation = engine.track_distance(engine.position_of(tid), engine.position_of(other))
        nearby.append(
            {
                "train_id": other,
                "relation": _relation(engine, tid, other),
                "separation_km": round(separation, 1) if separation != float("inf") else None,
                "confidence": "HIGH" if other_state == FRESH else ("REDUCED" if other_state == AGING else "LOW"),
                "source_freshness": other_state,
                "note": "Twin estimate for awareness only - not collision protection.",
            }
        )

    schedule = None
    if approved:
        delay = approved["plan"]["arrival_min"] - train.scheduled_arrival_min
        schedule = {"projected_arrival_min": approved["plan"]["arrival_min"], "deviation_min": round(delay, 1)}

    if status == DATA_UNAVAILABLE:
        headline = "DATA UNAVAILABLE - follow signals; controller informed"
    elif train.finished:
        headline = "ARRIVED"
    elif hold is not None:
        headline = f"HOLD FOR CONTROLLER - {hold['reason']}"
    elif approved is None:
        headline = "AWAITING CONTROLLER-APPROVED PLAN"
    elif status == HOLD_FOR_CONTROLLER:
        headline = "CONTROLLER REVIEW PENDING - " + threats[0].driver_message
    elif waiting:
        seconds = round(departure_min * 60)
        headline = f"Depart {train.origin} at sim {seconds // 60:02d}:{seconds % 60:02d}"
    elif plan_hold:
        headline = f"Planned hold {plan_hold['minutes']:g} min at {plan_hold['node']}"
    elif threats:
        headline = threats[0].driver_message
    else:
        headline = "Proceed per signals on approved plan"

    return {
        "train_id": tid,
        "train_name": train.name,
        "status": status,
        "headline": headline,
        "evidence": {
            "position": position_state,
            "source": train.position_source,
            "age_s": now - train.last_position_t if train.last_position_t is not None else None,
        },
        "position": {"section": current, "from_node": train.from_node, "offset_km": round(train.offset_km, 2)},
        "speed_kmph": round(train.speed_kmph, 1) if status != DATA_UNAVAILABLE else None,
        "advisory_speed_band_kmph": band,
        "route_strip": {
            "approved_route": ahead,
            "current_section": current,
            "next_waypoint": next_waypoint,
            "approved_summary": approved["summary"] if approved else None,
            "planned_hold": plan_hold,
        },
        "next_events": events[:3],
        "schedule": schedule,
        "nearby_trains": nearby,
        "threats": [{"id": t.id, "type": t.type, "severity": t.severity, "message": t.driver_message} for t in threats],
        "approved_snapshot": approved["snapshot_id"] if approved else None,
        "authority": AUTHORITY,
        "footer": CAB_FOOTER,
    }


def compact(advisory: dict[str, Any]) -> str:
    """Short text for a 128x64 tabletop cab display (TwinTrack microcontroller)."""

    band = advisory["advisory_speed_band_kmph"]
    speed = "--" if advisory["speed_kmph"] is None else f"{advisory['speed_kmph']:.0f}"
    lines = [
        f"TRAIN {advisory['train_id']} {advisory['status'][:12]}",
        f"SPD {speed} ADV {band[0]}-{band[1]}" if band else f"SPD {speed} ADV --",
        f"NEXT {advisory['route_strip']['next_waypoint'] or '-'}",
        (advisory["next_events"][0]["text"] if advisory["next_events"] else "No restriction ahead")[:21],
        advisory["headline"][:21],
        "ADVISORY ONLY",
    ]
    return "\n".join(lines)
