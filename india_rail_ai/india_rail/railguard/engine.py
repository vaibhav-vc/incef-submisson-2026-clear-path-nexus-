"""RailGuard engine: the digital twin, its evidence, threats, plans and audit.

Flow: observe (TwinTrack feed) -> verify (EvidenceGate) -> twin -> detect
(threat rules) -> optimise (planner) -> human approves -> driver advisory ->
audit. The engine runs on a simulated clock (`t`, seconds) so scenarios are
deterministic and replayable.

Authority: `approve` records approval of an *advisory/simulated* plan. The
engine has no interface to signals, points, interlocking, ATP or brakes.
"""

from __future__ import annotations

import heapq
import threading
from collections import defaultdict
from dataclasses import replace
from typing import Any

from india_rail.railguard import scoring
from india_rail.railguard.audit import AuditLog
from india_rail.railguard.evidence import REVIEWABLE, EvidenceRecord, EvidenceStore, checksum
from india_rail.railguard.model import AUTHORITY, Network, Section, Train, demo_network, demo_trains
from india_rail.railguard.planner import (
    DEFAULT_HEADWAY_MIN,
    TrainPlan,
    Traversal,
    build_train_plan,
    conflicts_between,
    recommend,
)
from india_rail.railguard.scoring import PRESETS
from india_rail.railguard.stress import running_speed
from india_rail.railguard.threats import ThreatRegistry, evaluate

POSITION_FRESH_S = 10
POSITION_STALE_S = 30
CONDITION_FRESH_S = 3600
CONDITION_STALE_S = 4 * 3600
SCHEDULE_STALE_S = 24 * 3600
MAX_PLAUSIBLE_FACTOR = 1.5  # observed speed above 1.5x the train's maximum is physically implausible
FLAG_HOLD_S = 60  # an evidence flag stays raised this long after its last occurrence
SOURCES = {"TWINTRACK_SENSOR", "TWINTRACK_SIM", "GNSS_SIM", "MANUAL_CONTROLLER"}


def network_from_dict(data: dict[str, Any]) -> Network:
    nodes = {k: (v["x"], v["y"]) for k, v in data["nodes"].items()}
    return Network(nodes=nodes, sections={k: Section(**v) for k, v in data["sections"].items()})


def plan_from_dict(data: dict[str, Any]) -> TrainPlan:
    traversals = [
        Traversal(
            t["section_id"], t["from_node"], t["to_node"], t["enter"], t["exit"], t["speed_kmph"], t.get("offset_km", 0)
        )
        for t in data["traversals"]
    ]
    return TrainPlan(
        data["train_id"],
        data["start_node"],
        data["route"],
        data["hold_node"],
        data["hold_min"],
        traversals,
        data["arrival_min"],
        data["delay_min"],
        data["stress"],
        data["energy"],
    )


def rank_from_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Pure function of a snapshot's inputs: used for live ranking and for replay."""

    network = network_from_dict(inputs["network"])
    trains = {tid: Train(**t) for tid, t in inputs["trains"].items()}
    evidence = EvidenceStore()
    for record in inputs["evidence"]:
        evidence.records[record["key"]] = EvidenceRecord(**record)
    starts = {
        tid: {"node": s["node"], "time_min": s["time_min"], "prefix": [Traversal(**p) for p in s["prefix"]]}
        for tid, s in inputs["starts"].items()
    }
    assessment = evidence.assess(inputs["now_t"], inputs["required"])
    ranking = recommend(network, trains, starts, evidence, inputs["now_t"], inputs["weights"], inputs["headway"])
    return {"assessment": assessment, "ranking": ranking}


class RailGuardEngine:
    position_stale_s = POSITION_STALE_S

    def __init__(self, headway: float = DEFAULT_HEADWAY_MIN):
        self.headway = headway
        self.lock = threading.RLock()
        self.reset()

    # ---- setup ---------------------------------------------------------------
    def reset(self, network: Network | None = None, trains: dict[str, Train] | None = None) -> None:
        self.net = network or demo_network()
        self.trains = trains or demo_trains()
        # Pure-function caches (keyed by every input they depend on, so they can never serve a stale answer).
        self._plan_cache: dict[tuple, TrainPlan] = {}
        self._distance_cache: dict[str, dict[str, float]] = {}
        self.t = 0
        self.version = 0  # bumped by every state change; an approval must match the version it was ranked on
        self.evidence = EvidenceStore()
        self.threats = ThreatRegistry()
        self.audit = AuditLog("tabletop")  # its own chain and files: never mixed with the national twin's
        self.flags: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.approved: dict[str, dict[str, Any]] = {}
        self.controller_hold: dict[str, dict[str, Any]] = {}
        self.latest: dict[str, Any] | None = None
        self.preset = "BALANCED"
        self.weights = dict(PRESETS["BALANCED"])
        self.observations: dict[str, list[dict[str, Any]]] = defaultdict(list)
        # Trains whose position comes from TwinTrack hardware; the simulator stops moving them.
        self.hardware_fed: set[str] = set()
        self.last_sequence: dict[str, int] = defaultdict(int)
        for tid, train in self.trains.items():
            train.from_node = train.from_node or train.origin
            self.evidence.put(
                f"schedule:{tid}",
                "SCHEDULE",
                "TIMETABLE",
                0,
                {"dep": train.scheduled_departure_min, "arr": train.scheduled_arrival_min},
                fresh_s=SCHEDULE_STALE_S,
                stale_s=SCHEDULE_STALE_S,
                mandatory=True,
            )
            self._accept_position(tid, None, train.origin, 0.0, 0.0, "TWINTRACK_SIM", 0)
        for sid, section in self.net.sections.items():
            self._condition_evidence(sid, section, "TRACKSENSE_SIM")
        self.audit.record(
            0, "TWIN_INITIALISED", "system", {"trains": sorted(self.trains), "sections": len(self.net.sections)}
        )
        self.refresh()

    def _condition_evidence(self, sid: str, section: Section, source: str) -> None:
        self.evidence.put(
            f"condition:{sid}",
            "CONDITION",
            source,
            self.t,
            {
                "condition": section.condition,
                "restriction": section.temp_restriction_kmph,
                "weather": section.weather_alert,
                "obstacle": section.obstacle,
                "available": section.available,
            },
            fresh_s=CONDITION_FRESH_S,
            stale_s=CONDITION_STALE_S,
            mandatory=True,
        )

    # ---- geometry helpers ----------------------------------------------------
    def _node_distances(self, start: str) -> dict[str, float]:
        cached = self._distance_cache.get(start)
        if cached is not None:
            return cached  # section lengths and topology never change within a twin
        dist = {start: 0.0}
        heap = [(0.0, start)]
        while heap:
            d, node = heapq.heappop(heap)
            if d > dist.get(node, float("inf")):
                continue
            for sid in self.net.adjacency[node]:
                section = self.net.sections[sid]
                nxt, nd = section.other(node), d + section.length_km
                if nd < dist.get(nxt, float("inf")):
                    dist[nxt] = nd
                    heapq.heappush(heap, (nd, nxt))
        self._distance_cache[start] = dist
        return dist

    def _ends(self, section_id: str | None, from_node: str, offset: float) -> list[tuple[str, float]]:
        if section_id is None:
            return [(from_node, 0.0)]
        section = self.net.sections[section_id]
        return [(from_node, offset), (section.other(from_node), section.length_km - offset)]

    def track_distance(self, p: tuple[str | None, str, float], q: tuple[str | None, str, float]) -> float:
        """Shortest along-track distance between two twin positions (km)."""

        if p[0] is not None and p[0] == q[0]:
            a = p[2] if p[1] == q[1] else self.net.sections[p[0]].length_km - p[2]
            return abs(a - q[2])
        best = float("inf")
        for node_p, dp in self._ends(*p):
            dist = self._node_distances(node_p)
            for node_q, dq in self._ends(*q):
                best = min(best, dp + dist.get(node_q, float("inf")) + dq)
        return best

    def position_of(self, tid: str) -> tuple[str | None, str, float]:
        train = self.trains[tid]
        return (train.section_id, train.from_node or train.origin, train.offset_km)

    # ---- observation ingestion (TwinTrack / GNSS-sim) ------------------------
    def _accept_position(
        self, tid: str, section_id: str | None, from_node: str, offset: float, speed: float, source: str, t: int
    ) -> None:
        train = self.trains[tid]
        train.section_id, train.from_node, train.offset_km = section_id, from_node, offset
        train.speed_kmph, train.last_position_t, train.position_source = speed, t, source
        payload = {"section": section_id, "from": from_node, "offset": round(offset, 4), "speed": speed}
        self.evidence.put(
            f"position:{tid}",
            "POSITION",
            source,
            t,
            payload,
            fresh_s=POSITION_FRESH_S,
            stale_s=POSITION_STALE_S,
            mandatory=True,
        )

    def ingest_position(self, obs: dict[str, Any]) -> dict[str, Any]:
        """Validate and apply one position observation. Invalid input never moves the twin."""

        with self.lock:
            tid = obs.get("train_id")
            if tid not in self.trains:
                return {"accepted": False, "reason": "unknown train"}
            source = obs.get("source", "TWINTRACK_SENSOR")
            if source not in SOURCES:
                return {"accepted": False, "reason": f"unknown source {source}"}
            try:
                t = int(obs.get("t", self.t))
                offset = float(obs.get("offset_km", 0.0))
                speed = float(obs.get("speed_kmph", 0.0))
            except (TypeError, ValueError):
                return {"accepted": False, "reason": "non-numeric field"}
            section_id, from_node = obs.get("section_id"), obs.get("from_node")
            if section_id is not None:
                section = self.net.sections.get(section_id)
                if section is None or from_node not in (section.a, section.b):
                    return {"accepted": False, "reason": "unknown section or endpoint"}
                if not 0 <= offset <= section.length_km:
                    return {"accepted": False, "reason": "offset outside section"}
            elif from_node not in self.net.nodes:
                return {"accepted": False, "reason": "unknown node"}
            if not 0 <= speed <= 250:
                return {"accepted": False, "reason": "speed outside 0-250 km/h"}
            if t > self.t + 5:
                return {"accepted": False, "reason": "timestamp in the future"}
            train = self.trains[tid]
            if train.last_position_t is not None and t < train.last_position_t:
                return {"accepted": False, "reason": "out-of-order timestamp"}
            sequence = int(obs.get("sequence", self.last_sequence[tid] + 1))
            if sequence <= self.last_sequence[tid] and source != "GNSS_SIM":
                return {"accepted": False, "reason": "replayed sequence number"}

            new_pos = (section_id, from_node, offset)
            self.observations[tid].append({**obs, "t": t})
            self.observations[tid] = self.observations[tid][-50:]
            if source == "GNSS_SIM":
                # GNSS is a secondary observation: compared, never trusted on its own.
                gap = self.track_distance(self.position_of(tid), new_pos)
                if t - (train.last_position_t or 0) <= POSITION_FRESH_S and gap > 1.0:
                    self._flag(
                        tid,
                        "EVIDENCE_CONFLICT",
                        "WARNING",
                        section_id,
                        [f"position:{tid}", f"gnss:{tid}"],
                        "Sources disagree on position; verify before using either.",
                        "Position sources disagree - controller review",
                        f"GNSS-sim differs from TwinTrack by {gap:.1f} km.",
                    )
                return {"accepted": True, "applied": False, "reason": "secondary source compared only"}
            if train.last_position_t is not None:
                # A same-second fix still counts as one second, so a jump cannot hide in a zero interval.
                dt_h = max(t - train.last_position_t, 1) / 3600
                gap = self.track_distance(self.position_of(tid), new_pos)
                if gap / dt_h > train.vmax_kmph * MAX_PLAUSIBLE_FACTOR + 1:
                    self._flag(
                        tid,
                        "IMPOSSIBLE_MOVEMENT",
                        "CRITICAL",
                        section_id,
                        [f"position:{tid}"],
                        "Reject the jump; confirm the train's location through authorised means.",
                        "Position jump rejected - controller review",
                        f"Implied {gap / dt_h:.0f} km/h over {gap:.1f} km.",
                    )
                    return {"accepted": False, "reason": "implausible movement"}
            self.last_sequence[tid] = max(sequence, self.last_sequence[tid])
            if source == "TWINTRACK_SENSOR" and tid not in self.hardware_fed:
                self.hardware_fed.add(tid)
                self.audit.record(self.t, "HARDWARE_FEED_ACTIVE", "twintrack", {"train": tid})
            self._accept_position(tid, section_id, from_node, offset, speed, source, t)
            if section_id is None and from_node == train.destination:
                train.finished = True
            self.refresh()
            return {"accepted": True, "applied": True}

    def _flag(
        self,
        tid: str,
        type_: str,
        severity: str,
        section_id: str | None,
        sources: list[str],
        controller: str,
        driver: str,
        detail: str,
    ) -> None:
        self.flags[tid] = [f for f in self.flags.get(tid, []) if f["type"] != type_]
        self.flags[tid].append(
            {
                "type": type_,
                "severity": severity,
                "section_id": section_id,
                "sources": sources,
                "controller": controller,
                "driver": driver,
                "detail": detail,
                "until_t": self.t + FLAG_HOLD_S,
            }
        )
        self.audit.record(self.t, "EVIDENCE_FLAG", "evidencegate", {"train": tid, "type": type_, "detail": detail})
        self.refresh()

    # ---- infrastructure / sensor events --------------------------------------
    def update_section(self, sid: str, source: str = "TRACKSENSE_SIM", **changes: Any) -> Section:
        with self.lock:
            section = self.net.sections[sid]
            allowed = {"condition", "temp_restriction_kmph", "weather_alert", "obstacle", "available"}
            for key, value in changes.items():
                if key not in allowed:
                    raise ValueError(f"field {key} cannot be changed")
                setattr(section, key, value)
            self._condition_evidence(sid, section, source)
            self.audit.record(self.t, "SECTION_UPDATED", source, {"section": sid, **changes})
            self.refresh()
            return section

    def inject_fault(self, kind: str, train_id: str | None = None, section_id: str | None = None) -> dict[str, Any]:
        """Demo fault injection: freeze/unfreeze a feed, take a sensor offline, report an obstacle."""

        with self.lock:
            if kind in {"freeze_feed", "unfreeze_feed", "sensor_offline", "sensor_online"}:
                train = self.trains[train_id]
                if kind == "freeze_feed":
                    train.feed_frozen = True
                elif kind == "unfreeze_feed":
                    train.feed_frozen = False
                elif kind == "sensor_offline":
                    train.sensor_offline = True
                else:
                    train.sensor_offline = False
            elif kind == "obstacle":
                self.update_section(section_id, source="TWINTRACK_OBSTACLE_SENSOR", obstacle=True)
            elif kind == "clear_obstacle":
                self.update_section(section_id, source="INSPECTION_REPORT", obstacle=False)
            else:
                raise ValueError(f"unknown fault {kind}")
            self.audit.record(
                self.t, "FAULT_INJECTED", "demo", {"kind": kind, "train": train_id, "section": section_id}
            )
            self.refresh()
            return {"ok": True, "kind": kind}

    # ---- plans and simulation ------------------------------------------------
    def default_plan(self, tid: str) -> TrainPlan:
        """The timetabled plan (treat as read-only: it is cached on the exact train and section state)."""

        train = self.trains[tid]
        start = train.scheduled_departure_min + train.departure_delay_min
        key = (
            tid,
            start,
            train.vmax_kmph,
            train.axle_load_t,
            train.mass_t,
            train.origin,
            tuple(train.default_route),
            tuple(tuple(vars(self.net.sections[sid]).values()) for sid in train.default_route),
        )
        cached = self._plan_cache.get(key)
        if cached is not None:
            return cached
        if len(self._plan_cache) > 256:
            self._plan_cache.clear()
        plan = self._plan_cache[key] = build_train_plan(
            self.net,
            train,
            train.origin,
            train.scheduled_departure_min + train.departure_delay_min,
            train.default_route,
            None,
            0,
            [],
        )
        return plan

    def current_plan(self, tid: str) -> TrainPlan:
        """Approved plan, else the timetabled one (read-only: both are cached)."""

        approved = self.approved.get(tid)
        if not approved:
            return self.default_plan(tid)
        key = ("approved", tid, approved["snapshot_id"], approved["candidate_id"], approved["approved_t"])
        cached = self._plan_cache.get(key)
        if cached is None:
            cached = self._plan_cache[key] = plan_from_dict(approved["plan"])
        return cached

    def route_ahead(self, tid: str) -> list[str]:
        """Sections of the train's current plan still ahead of it (routes never revisit a node)."""

        train = self.trains[tid]
        traversals = self.current_plan(tid).traversals
        route = [t.section_id for t in traversals]
        if train.section_id in route:
            return route[route.index(train.section_id) :]
        for i, trav in enumerate(traversals):
            if train.section_id is None and trav.from_node == train.from_node:
                return route[i:]
        return []

    def planned_conflicts(self, a: str, b: str) -> list[dict[str, Any]]:
        now_min = self.t / 60
        plans = []
        for tid in (a, b):
            plan = self.current_plan(tid)
            plans.append(replace(plan, traversals=[t for t in plan.traversals if t.exit >= now_min]))
        return conflicts_between(self.net, plans[0], plans[1], self.headway)

    def _simulated_position(self, tid: str, minute: float) -> tuple[str | None, str, float, float, bool]:
        traversals = self.current_plan(tid).traversals
        hold = self.controller_hold.get(tid)
        train = self.trains[tid]
        if hold is not None and minute >= hold["stop_by_min"]:
            # Under a controller hold the train clears its current section, then waits at the next node.
            done = [t for t in traversals if t.exit <= hold["stop_by_min"] + 1e-6]
            if not done:
                return train.section_id, train.from_node, train.offset_km, 0.0, False
            return None, done[-1].to_node, 0.0, 0.0, done[-1] is traversals[-1]
        if not traversals or minute < traversals[0].enter:
            if traversals and traversals[0].offset_km > 0:  # re-planned mid-section (times are stored rounded)
                return traversals[0].section_id, traversals[0].from_node, traversals[0].offset_km, 0.0, False
            first = traversals[0].from_node if traversals else train.from_node
            return None, first, 0.0, 0.0, False
        for i, trav in enumerate(traversals):
            if trav.enter <= minute < trav.exit:
                length = self.net.sections[trav.section_id].length_km
                frac = (minute - trav.enter) / (trav.exit - trav.enter)
                offset = trav.offset_km + (length - trav.offset_km) * frac
                return trav.section_id, trav.from_node, round(offset, 4), trav.speed_kmph, False
            nxt = traversals[i + 1] if i + 1 < len(traversals) else None
            if minute >= trav.exit and (nxt is None or minute < nxt.enter):
                return None, trav.to_node, 0.0, 0.0, nxt is None
        return None, traversals[-1].to_node, 0.0, 0.0, True

    def tick(self, seconds: int = 10) -> None:
        """Advance the simulated clock; TwinTrack-sim reports positions for trains whose feed is live."""

        with self.lock:
            step = 5
            remaining = max(int(seconds), 0)
            while remaining > 0:
                dt = min(step, remaining)
                self.t += dt
                remaining -= dt
                for tid, train in self.trains.items():
                    if train.finished or train.feed_frozen or train.sensor_offline or tid in self.hardware_fed:
                        continue
                    if tid not in self.approved:
                        # No approved plan: the train waits where it is (twin keeps reporting).
                        self._accept_position(
                            tid, train.section_id, train.from_node, train.offset_km, 0.0, "TWINTRACK_SIM", self.t
                        )
                        continue
                    section_id, node, offset, speed, finished = self._simulated_position(tid, self.t / 60)
                    self.last_sequence[tid] += 1
                    self._accept_position(tid, section_id, node, offset, speed, "TWINTRACK_SIM", self.t)
                    if finished:
                        train.finished = True
                        self.audit.record(self.t, "TRAIN_ARRIVED", "twin", {"train": tid, "node": node})
            self.refresh()

    def refresh(self) -> None:
        """Re-evaluate threats after any state change (and mark earlier recommendations superseded)."""

        self.version += 1
        self.threats.update(evaluate(self), self.t)

    # ---- recommendation, approval and audit -----------------------------------
    def set_weights(self, preset: str | None = None, weights: dict[str, float] | None = None) -> dict[str, float]:
        name, self.weights = scoring.choose_weights(self.weights, preset, weights)
        self.preset = name or self.preset
        return self.weights

    def _starts(self) -> dict[str, dict[str, Any]]:
        now_min = self.t / 60
        starts = {}
        for tid, train in self.trains.items():
            if train.finished:
                continue
            if train.section_id is None:
                time_min = now_min
                if train.from_node == train.origin and tid not in self.approved:
                    time_min = max(now_min, train.scheduled_departure_min + train.departure_delay_min)
                starts[tid] = {"node": train.from_node, "time_min": round(time_min, 4), "prefix": []}
            else:
                section = self.net.sections[train.section_id]
                speed = running_speed(train, section)
                eta = now_min + (section.length_km - train.offset_km) / speed * 60
                nxt = section.other(train.from_node)
                prefix = Traversal(
                    section.id, train.from_node, nxt, round(now_min, 4), round(eta, 4), speed, round(train.offset_km, 4)
                )
                starts[tid] = {"node": nxt, "time_min": round(eta, 4), "prefix": [prefix.__dict__]}
        return starts

    def recommend(self, actor: str = "controller") -> dict[str, Any]:
        with self.lock:
            starts = self._starts()
            required = [f"position:{tid}" for tid in starts] + [f"schedule:{tid}" for tid in starts]
            required += [f"condition:{sid}" for sid in sorted(self.net.sections)]
            inputs = {
                "network": self.net.to_dict(),
                "trains": {tid: train.to_dict() for tid, train in self.trains.items() if tid in starts},
                "starts": starts,
                "evidence": [r.to_dict() for _k, r in sorted(self.evidence.records.items())],
                "required": required,
                "now_t": self.t,
                "weights": dict(self.weights),
                "headway": self.headway,
            }
            outputs = rank_from_inputs(inputs)
            threats = [t.to_dict() for t in self.threats.active()]
            critical = [t for t in self.threats.active() if t.severity == "CRITICAL" and t.lifecycle == "OPEN"]
            assessment, ranking = outputs["assessment"], outputs["ranking"]
            if not starts:
                state, reason = "COMPLETE", "All trains have arrived."
            elif assessment["state"] != REVIEWABLE:
                state = assessment["state"]
                reason = (
                    ("Mandatory evidence missing: " + ", ".join(assessment["missing"]))
                    if assessment["missing"]
                    else "Mandatory evidence stale: " + ", ".join(assessment["stale"])
                )
            elif ranking["state"] != "RANKED":
                state, reason = "NO_FEASIBLE_PLAN", "No conflict-free alternative within the planning options."
            elif critical:
                state, reason = "REVIEW", "Critical threat open: " + ", ".join(sorted({t.type for t in critical}))
            else:
                state, reason = REVIEWABLE, "Evidence fresh and complete; alternatives ranked for controller review."
            approvable = state == REVIEWABLE
            snapshot = self.audit.add_snapshot(
                inputs, {**outputs, "threats": threats, "state": state, "approvable": approvable}, self.t
            )
            self.latest = {
                "snapshot_id": snapshot["snapshot_id"],
                "checksum": snapshot["checksum"],
                "t": self.t,
                "version": self.version,
                "state": state,
                "reason": reason,
                "approvable": approvable,
                "preset": self.preset,
                "assessment": assessment,
                "ranking": ranking,
                "authority": AUTHORITY,
            }
            self.audit.record(
                self.t,
                "RECOMMENDATION_ISSUED",
                actor,
                {
                    "snapshot_id": snapshot["snapshot_id"],
                    "state": state,
                    "top": ranking["candidates"][0]["summary"] if ranking.get("candidates") else None,
                },
            )
            return self.latest

    def approve(self, snapshot_id: str, candidate_id: str, controller: str) -> dict[str, Any]:
        with self.lock:
            if not controller:
                raise PermissionError("A named controller must approve")
            latest = self.latest
            if latest is None or latest["snapshot_id"] != snapshot_id or latest["version"] != self.version:
                # Ranked on an earlier state (clock, positions, sections, holds or threats have changed since).
                raise ValueError("Recommendation superseded: re-rank, then approve the latest snapshot")
            if not self.latest["approvable"]:
                raise ValueError(f"Not approvable: {self.latest['state']} - {self.latest['reason']}")
            candidate = next(
                (c for c in self.latest["ranking"]["candidates"] if c["candidate_id"] == candidate_id), None
            )
            if candidate is None:
                raise KeyError(candidate_id)
            for tid, plan in candidate["train_plans"].items():
                self.approved[tid] = {
                    "snapshot_id": snapshot_id,
                    "candidate_id": candidate_id,
                    "summary": candidate["summary"],
                    "route_all": [t["section_id"] for t in plan["traversals"]],
                    "plan": plan,
                    "approved_by": controller,
                    "approved_t": self.t,
                }
                self.controller_hold.pop(tid, None)
            event = self.audit.record(
                self.t,
                "PLAN_APPROVED_FOR_DEMO",
                controller,
                {
                    "snapshot_id": snapshot_id,
                    "candidate_id": candidate_id,
                    "summary": candidate["summary"],
                    "authority": AUTHORITY,
                },
            )
            self.refresh()
            return {
                "status": "APPROVED_FOR_DEMO",
                "authority": AUTHORITY,
                "event_hash": event["hash"],
                "note": "Approval of a simulated advisory plan. Not movement authority.",
            }

    def reject(self, snapshot_id: str, controller: str, reason: str) -> dict[str, Any]:
        with self.lock:
            event = self.audit.record(
                self.t, "RECOMMENDATION_REJECTED", controller, {"snapshot_id": snapshot_id, "reason": reason}
            )
            return {"status": "REJECTED", "event_hash": event["hash"]}

    def hold(self, controller: str, reason: str, train_id: str | None = None) -> dict[str, Any]:
        with self.lock:
            targets = [train_id] if train_id else [tid for tid, t in self.trains.items() if not t.finished]
            for tid in targets:
                plan = self.current_plan(tid)
                now_min = self.t / 60
                stop_by = now_min
                for trav in plan.traversals:
                    if trav.enter <= now_min < trav.exit:
                        stop_by = trav.exit
                previous = self.controller_hold.get(tid)
                if previous is not None:  # already held: it stays where it stopped (never released by a re-hold)
                    stop_by = min(stop_by, previous["stop_by_min"])
                self.controller_hold[tid] = {"reason": reason, "by": controller, "t": self.t, "stop_by_min": stop_by}
            event = self.audit.record(self.t, "CONTROLLER_HOLD", controller, {"trains": targets, "reason": reason})
            self.refresh()
            return {"status": "HOLD_RECORDED", "trains": targets, "event_hash": event["hash"]}

    def acknowledge(self, threat_id: str, by: str) -> dict[str, Any]:
        with self.lock:
            threat = self.threats.acknowledge(threat_id, by)
            self.audit.record(self.t, "THREAT_ACKNOWLEDGED", by, {"threat": threat_id, "type": threat.type})
            return threat.to_dict()

    def replay(self, snapshot_id: str) -> dict[str, Any]:
        """Re-run the planner on a snapshot's stored inputs and compare with what was recorded."""

        snapshot = self.audit.snapshots[snapshot_id]
        rerun = rank_from_inputs(snapshot["inputs"])
        recorded = {k: snapshot["outputs"][k] for k in ("assessment", "ranking")}
        return {
            "snapshot_id": snapshot_id,
            "integrity_ok": self.audit.verify_snapshot(snapshot_id),
            "replay_matches": checksum(rerun) == checksum(recorded),
            "recorded_top": recorded["ranking"]["candidates"][0]["summary"]
            if recorded["ranking"]["candidates"]
            else None,
            "replayed_top": rerun["ranking"]["candidates"][0]["summary"] if rerun["ranking"]["candidates"] else None,
            "inputs_checksum": snapshot["inputs_checksum"],
            "note": "Integrity and reproducibility of the record; not proof that the inputs were true.",
        }

    def state(self) -> dict[str, Any]:
        with self.lock:
            return {
                "t": self.t,
                "network": self.net.to_dict(),
                "trains": {
                    tid: {
                        **t.to_dict(),
                        "position_evidence": self.evidence.state_of(f"position:{tid}", self.t),
                        "hardware_fed": tid in self.hardware_fed,
                        "approved": self.approved.get(tid, {}).get("summary"),
                        "approved_route": self.approved.get(tid, {}).get("route_all", []),
                        "controller_hold": self.controller_hold.get(tid),
                    }
                    for tid, t in self.trains.items()
                },
                "threats": [t.to_dict() for t in self.threats.active()],
                "latest_recommendation": self.latest,
                "preset": self.preset,
                "weights": self.weights,
                "headway_min": self.headway,
                "audit_events": len(self.audit.events),
                "audit_chain_ok": self.audit.verify_chain(),
                "authority": AUTHORITY,
            }
