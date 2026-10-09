"""Nexus RailGuard threat fusion: deterministic, explainable rules.

Each rule reads the digital twin and EvidenceGate state and emits threats with
a type, severity, affected trains/section, evidence sources, confidence, a
controller recommendation and a driver-facing message. The registry keeps a
lifecycle (OPEN -> ACKNOWLEDGED -> CLEARED) so a threat cannot silently vanish.

GNSS/position data is one observation only: proximity rules run on the
simulated twin, and their confidence drops when position evidence ages.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from india_rail.railguard.evidence import AGING, FRESH, STALE
from india_rail.railguard.model import AUTHORITY

SEVERITY_ORDER = {"INFO": 0, "CAUTION": 1, "WARNING": 2, "CRITICAL": 3}
OPEN, ACKNOWLEDGED, CLEARED = "OPEN", "ACKNOWLEDGED", "CLEARED"
MAX_CLEARED_KEPT = 2_000
# Alert hygiene. A threat a rule stops reporting for a moment (a separation hovering at the headway, a report
# arriving a few seconds late) must not clear and come back as a new alert the controller has to acknowledge
# again: a non-critical threat clears only once it has been gone CLEAR_AFTER_S, and one that comes back within
# REOPEN_S of clearing is the same threat (same id; its acknowledgement stands unless it is now more severe).
# A CRITICAL threat is raised at once, clears at once, and comes back OPEN: it must be looked at again.
CLEAR_AFTER_S = 60
REOPEN_S = 900
CONFIDENCE = {FRESH: 1.0, AGING: 0.6, STALE: 0.2}


@dataclass
class Threat:
    key: str
    type: str
    severity: str
    train_ids: list[str]
    section_id: str | None
    evidence_sources: list[str]
    confidence: float
    controller_recommendation: str
    driver_message: str
    detail: str
    lifecycle: str = OPEN
    first_seen_t: int = 0
    last_seen_t: int = 0
    acknowledged_by: str | None = None
    cleared_t: int | None = None
    authority: str = AUTHORITY
    id: str = field(default="")
    absent_since_t: int | None = None  # no longer reported since then (cleared after CLEAR_AFTER_S)
    acknowledged_severity: str | None = None
    reopened: int = 0  # times it came back after clearing

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _threat(
    type_: str,
    severity: str,
    trains: list[str],
    section: str | None,
    sources: list[str],
    confidence: float,
    controller: str,
    driver: str,
    detail: str,
) -> Threat:
    key = f"{type_}|{','.join(sorted(trains))}|{section or '-'}"
    return Threat(
        key, type_, severity, sorted(trains), section, sources, round(confidence, 2), controller, driver, detail
    )


def evaluate(engine: Any) -> list[Threat]:
    """Run every rule against the engine's current twin state."""

    net, now = engine.net, engine.t
    found: list[Threat] = []

    def pos_state(tid: str) -> str:
        return engine.evidence.state_of(f"position:{tid}", now)

    for tid, train in engine.trains.items():
        if train.finished:
            continue
        state = pos_state(tid)
        if state == STALE or state == "MISSING":
            found.append(
                _threat(
                    "STALE_POSITION",
                    "WARNING",
                    [tid],
                    train.section_id,
                    [f"position:{tid}"],
                    CONFIDENCE[STALE],
                    "Do not rely on this train's position; confirm by voice/authorised source before any decision.",
                    "Position data stale - controller review",
                    f"No valid position fix within the {engine.position_stale_s} s freshness policy.",
                )
            )
        if train.sensor_offline:
            found.append(
                _threat(
                    "SOURCE_OFFLINE",
                    "WARNING",
                    [tid],
                    train.section_id,
                    [f"sensor:{tid}"],
                    0.2,
                    "Treat onboard feed as unavailable; fall back to authorised train describer.",
                    "Onboard data link offline",
                    "TwinTrack node reported offline.",
                )
            )
        for flag in [f for f in engine.flags.get(tid, []) if f["until_t"] >= now]:
            found.append(
                _threat(
                    flag["type"],
                    flag["severity"],
                    [tid],
                    flag.get("section_id"),
                    flag["sources"],
                    0.3,
                    flag["controller"],
                    flag["driver"],
                    flag["detail"],
                )
            )

        plan = engine.approved.get(tid)
        ahead = engine.route_ahead(tid)
        if plan and train.section_id and train.section_id not in plan["route_all"]:
            found.append(
                _threat(
                    "ROUTE_DEVIATION",
                    "WARNING",
                    [tid],
                    train.section_id,
                    [f"position:{tid}"],
                    CONFIDENCE.get(state, 0.2),
                    "Re-plan: train observed outside the approved route.",
                    "Off approved route - controller review",
                    f"Observed on {train.section_id}, not in approved plan.",
                )
            )
        for sid in ahead[:3]:
            section = net.sections[sid]
            if section.obstacle:
                found.append(
                    _threat(
                        "OBSTACLE",
                        "CRITICAL",
                        [tid],
                        sid,
                        [f"sensor:obstacle:{sid}"],
                        1.0,
                        f"Arrange inspection of {sid}; re-plan around it. Signalling/ATP remain authoritative.",
                        f"Obstacle reported on {sid} ahead - expect controller instructions",
                        "Tabletop obstacle sensor event.",
                    )
                )
            if not section.available:
                found.append(
                    _threat(
                        "SECTION_CLOSED",
                        "CRITICAL",
                        [tid],
                        sid,
                        [f"condition:{sid}"],
                        1.0,
                        f"{sid} is closed; re-plan around it. Signalling/ATP remain authoritative.",
                        f"{sid} ahead closed - expect controller instructions",
                        "Section closed by infrastructure input.",
                    )
                )
            if section.temp_restriction_kmph:
                found.append(
                    _threat(
                        "RESTRICTION_AHEAD",
                        "INFO",
                        [tid],
                        sid,
                        [f"restriction:{sid}"],
                        1.0,
                        "Restriction already reflected in planned run times.",
                        f"{section.temp_restriction_kmph:g} km/h restriction on {sid}",
                        "Temporary speed restriction.",
                    )
                )
            if section.condition < 0.5:
                found.append(
                    _threat(
                        "INFRA_CAUTION",
                        "CAUTION",
                        [tid],
                        sid,
                        [f"condition:{sid}"],
                        CONFIDENCE.get(engine.evidence.state_of(f"condition:{sid}", now), 0.2),
                        "Consider the lower-stress alternative or a restriction pending inspection.",
                        f"Track condition caution on {sid}",
                        f"TrackSense condition {section.condition:.2f}.",
                    )
                )
            if section.weather_alert:
                found.append(
                    _threat(
                        "WEATHER",
                        "CAUTION",
                        [tid],
                        sid,
                        [f"weather:{sid}"],
                        1.0,
                        "Check weather-related operating instructions for this section.",
                        f"{section.weather_alert.replace('_', ' ').title()} alert on {sid}",
                        "Weather/context alert.",
                    )
                )

    # Proximity rules run on the twin and planned windows, never on GNSS alone.
    ids = [tid for tid in sorted(engine.trains) if not engine.trains[tid].finished]
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            ta, tb = engine.trains[a], engine.trains[b]
            conf = min(CONFIDENCE.get(pos_state(a), 0.2), CONFIDENCE.get(pos_state(b), 0.2))
            if (
                ta.section_id
                and ta.section_id == tb.section_id
                and net.sections[ta.section_id].tracks == 1
                and ta.from_node != tb.from_node
            ):
                found.append(
                    _threat(
                        "OPPOSING_SAME_SECTION",
                        "CRITICAL",
                        [a, b],
                        ta.section_id,
                        [f"position:{a}", f"position:{b}"],
                        conf,
                        "Immediate controller attention: opposing trains mapped to one single-line section.",
                        "Opposing train mapped ahead - follow signals and controller",
                        "Twin shows opposing occupancy.",
                    )
                )
            for c in engine.planned_conflicts(a, b):
                if c["gap_min"] < engine.headway * 2:
                    severity = "WARNING" if c["is_conflict"] else "CAUTION"
                    found.append(
                        _threat(
                            "CONVERGING_PATH",
                            severity,
                            [a, b],
                            c["section_id"],
                            [f"position:{a}", f"position:{b}", "schedule"],
                            conf,
                            "Resequence, hold or reroute - see ranked alternatives.",
                            "Converging traffic - controller review pending"
                            if c["is_conflict"]
                            else "Other train on converging path",
                            f"Planned windows on {c['section_id']} {c['window_a']} / {c['window_b']} min, "
                            f"separation {c['gap_min']} min (headway {engine.headway:g}).",
                        )
                    )
    return found


def _above(severity: str, than: str | None) -> bool:
    return than is not None and SEVERITY_ORDER[severity] > SEVERITY_ORDER[than]


class ThreatRegistry:
    def __init__(self) -> None:
        self.threats: dict[str, Threat] = {}
        self._counter = 0
        self.raised = 0  # new alerts (new ids)
        self.came_back = 0  # threats that cleared and came back as themselves (no new alert)
        self.held = 0  # evaluations in which a non-critical threat missing for a moment was kept

    def update(self, current: list[Threat], now: int, settled: bool = False) -> None:
        """`current`: what the rules report now. `settled`: this evaluation follows a deliberate change (a plan
        approved, a section reported reopened or cleared): what it no longer reports was resolved, not missed,
        and clears at once."""

        seen = set()
        for threat in current:
            seen.add(threat.key)
            existing = self.threats.get(threat.key)
            if (existing and existing.lifecycle == CLEARED and existing.cleared_t is not None
                    and now - existing.cleared_t <= REOPEN_S):  # fmt: skip
                keeps_ack = (existing.acknowledged_by is not None and threat.severity != "CRITICAL"
                             and not _above(threat.severity, existing.acknowledged_severity))  # fmt: skip
                existing.lifecycle = ACKNOWLEDGED if keeps_ack else OPEN
                if not keeps_ack:
                    existing.acknowledged_by = existing.acknowledged_severity = None
                existing.cleared_t = None
                existing.reopened += 1
                self.came_back += 1
            if existing and existing.lifecycle != CLEARED:
                if existing.lifecycle == ACKNOWLEDGED and _above(threat.severity, existing.acknowledged_severity):
                    # more severe than what the controller acknowledged: it needs acknowledging again
                    existing.lifecycle, existing.acknowledged_by, existing.acknowledged_severity = OPEN, None, None
                existing.severity = threat.severity
                existing.confidence = threat.confidence
                existing.detail = threat.detail
                existing.driver_message = threat.driver_message
                existing.controller_recommendation = threat.controller_recommendation
                existing.last_seen_t = now
                existing.absent_since_t = None
                continue
            self._counter += 1
            self.raised += 1
            threat.id = f"THR-{self._counter:04d}"
            threat.first_seen_t = threat.last_seen_t = now
            self.threats[threat.key] = threat
        for key, threat in self.threats.items():
            if key in seen or threat.lifecycle == CLEARED:
                continue
            if threat.absent_since_t is None:
                threat.absent_since_t = now
            if settled or threat.severity == "CRITICAL" or now - threat.absent_since_t >= CLEAR_AFTER_S:
                threat.lifecycle = CLEARED
                threat.cleared_t = now
            else:
                self.held += 1
        cleared = [k for k, t in self.threats.items() if t.lifecycle == CLEARED]
        for key in cleared[: max(len(cleared) - MAX_CLEARED_KEPT, 0)]:  # bounded memory: oldest cleared first
            del self.threats[key]

    def acknowledge(self, threat_id: str, by: str) -> Threat:
        for threat in self.threats.values():
            if threat.id == threat_id:
                if threat.lifecycle == CLEARED:
                    raise ValueError(f"{threat_id} is already cleared")
                threat.lifecycle = ACKNOWLEDGED
                threat.acknowledged_by = by
                threat.acknowledged_severity = threat.severity
                return threat
        raise KeyError(threat_id)

    def active(self) -> list[Threat]:
        return sorted(
            (t for t in self.threats.values() if t.lifecycle != CLEARED),
            key=lambda t: (-SEVERITY_ORDER[t.severity], t.id),
        )

    def for_train(self, tid: str) -> list[Threat]:
        return [t for t in self.active() if tid in t.train_ids]
