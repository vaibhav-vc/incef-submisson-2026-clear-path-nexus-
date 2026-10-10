"""Multi-objective controller planner for the digital twin.

Generates route / hold / resequence alternatives for both trains, rejects any
that break a hard constraint, and ranks the rest by an explainable weighted
score (lower is better):

    score = Wd*delay + Wc*conflict + Wi*infra_stress + We*energy
          + Wt*threat + Wv*evidence_uncertainty + Wx*complexity

Every factor is normalised to 0-1 and shown to the controller with its
contribution, so it is visible why the winner won and why alternatives lost.
The output is shadow dispatch: a proposal for human approval, never movement
authority.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

from india_rail.railguard import scoring
from india_rail.railguard.evidence import AGING, FRESH, EvidenceStore
from india_rail.railguard.model import Network, Train
from india_rail.railguard.stress import restart_energy, running_speed, section_energy, section_stress

DEFAULT_HEADWAY_MIN = 3.0
HOLD_OPTIONS_MIN = (0, 3, 6, 9, 12, 15, 20)
MAX_ROUTE_STRETCH = 1.7  # ignore routes more than 70% longer than the shortest


@dataclass
class Traversal:
    section_id: str
    from_node: str
    to_node: str
    enter: float
    exit: float
    speed_kmph: float
    offset_km: float = 0.0  # distance already covered at `enter` (a train already on the section)

    def to_dict(self) -> dict[str, Any]:
        return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


@dataclass
class TrainPlan:
    train_id: str
    start_node: str
    route: list[str]
    hold_node: str | None
    hold_min: float
    traversals: list[Traversal]
    arrival_min: float
    delay_min: float
    stress: float
    energy: float
    stress_detail: list[dict[str, Any]] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "train_id": self.train_id,
            "start_node": self.start_node,
            "route": self.route,
            "hold_node": self.hold_node,
            "hold_min": self.hold_min,
            "arrival_min": round(self.arrival_min, 2),
            "delay_min": round(self.delay_min, 2),
            "stress": round(self.stress, 2),
            "energy": round(self.energy, 2),
            "traversals": [t.to_dict() for t in self.traversals],
            "violations": self.violations,
        }


def simple_routes(network: Network, origin: str, destination: str, max_sections: int = 7) -> list[list[str]]:
    """All loop-free section paths, shortest first, within MAX_ROUTE_STRETCH of the shortest."""

    found: list[tuple[float, list[str]]] = []

    def walk(node: str, visited: set[str], path: list[str], length: float) -> None:
        if node == destination:
            found.append((length, list(path)))
            return
        if len(path) >= max_sections:
            return
        for sid in network.adjacency[node]:
            nxt = network.sections[sid].other(node)
            if nxt in visited:
                continue
            visited.add(nxt)
            path.append(sid)
            walk(nxt, visited, path, length + network.sections[sid].length_km)
            path.pop()
            visited.discard(nxt)

    walk(origin, {origin}, [], 0.0)
    if not found:
        return []
    found.sort(key=lambda item: (item[0], item[1]))
    shortest = found[0][0]
    return [path for length, path in found if length <= shortest * MAX_ROUTE_STRETCH]


def build_train_plan(
    network: Network,
    train: Train,
    start_node: str,
    start_min: float,
    route: list[str],
    hold_index: int | None,
    hold_min: float,
    prefix: list[Traversal],
) -> TrainPlan:
    nodes = network.path_nodes(start_node, route)
    t = start_min
    traversals = list(prefix)
    stress = energy = 0.0
    detail = []
    violations = []
    for i, sid in enumerate(route):
        section = network.sections[sid]
        if hold_index is not None and i == hold_index and hold_min > 0:
            t += hold_min
            energy += restart_energy(train)
        if not section.available:
            violations.append(f"{sid} is closed")
        if section.obstacle:
            violations.append(f"{sid} blocked: obstacle report pending inspection")
        if train.axle_load_t > section.axle_limit_t:
            violations.append(f"{sid} axle limit {section.axle_limit_t}t < {train.axle_load_t}t")
        speed = running_speed(train, section)
        run = section.length_km / speed * 60
        traversals.append(Traversal(sid, nodes[i], nodes[i + 1], t, t + run, speed))
        t += run
        item = section_stress(train, section, speed)
        detail.append(item)
        stress += item["stress"]
        energy += section_energy(train, section, speed)
    delay = max(0.0, t - train.scheduled_arrival_min)
    hold_node = nodes[hold_index] if hold_index is not None and hold_min > 0 else None
    return TrainPlan(
        train.id,
        start_node,
        route,
        hold_node,
        hold_min if hold_node else 0.0,
        traversals,
        t,
        delay,
        stress,
        energy,
        detail,
        violations,
    )


def conflicts_between(network: Network, p: TrainPlan, q: TrainPlan, headway: float) -> list[dict[str, Any]]:
    """Occupancy conflicts and margins between two trains' traversals.

    Single line: any overlap of occupation windows (either direction) closer
    than the headway. Double line: same-direction moves closer than the headway
    or an overtake (order reversal) on the section.
    """

    found = []
    for a in p.traversals:
        for b in q.traversals:
            if a.section_id != b.section_id:
                continue
            section = network.sections[a.section_id]
            same_direction = a.from_node == b.from_node
            if section.tracks == 1:
                gap = max(b.enter - a.exit, a.enter - b.exit)  # negative = overlap
            elif same_direction:
                if (a.enter - b.enter) * (a.exit - b.exit) < 0:
                    gap = -1.0  # overtake on plain line
                else:
                    gap = min(abs(a.enter - b.enter), abs(a.exit - b.exit))
            else:
                continue
            found.append(
                {
                    "section_id": a.section_id,
                    "trains": [p.train_id, q.train_id],
                    "single_line": section.tracks == 1,
                    "opposing": not same_direction,
                    "gap_min": round(gap, 2),
                    "is_conflict": gap < headway,
                    "window_a": [round(a.enter, 2), round(a.exit, 2)],
                    "window_b": [round(b.enter, 2), round(b.exit, 2)],
                }
            )
    return found


def section_threat_weight(network: Network, sid: str) -> float:
    section = network.sections[sid]
    weight = 0.0
    if section.weather_alert:
        weight += 0.5
    if section.temp_restriction_kmph:
        weight += 0.25
    if section.condition < 0.5:
        weight += 0.25
    return weight


def _evidence_penalty(state: str) -> float:
    return {FRESH: 0.0, AGING: 0.5}.get(state, 1.0)


def describe(network: Network, trains: dict[str, Train], plans: dict[str, TrainPlan]) -> dict[str, Any]:
    parts, kinds = [], set()
    for tid, plan in plans.items():
        train = trains[tid]
        default_tail = train.default_route[len(train.default_route) - len(plan.route) :]
        rerouted = plan.route != default_tail
        via = "->".join(network.path_nodes(plan.start_node, plan.route))
        text = f"Train {tid}: {via}"
        if rerouted:
            kinds.add("REROUTE")
            text += " (alternative route)"
        if plan.hold_node:
            kinds.add("HOLD")
            text += f", hold {plan.hold_min:g} min at {plan.hold_node}"
        parts.append(text)
    kind = "CONTINUE" if not kinds else "+".join(sorted(kinds))
    return {"action": kind, "summary": "; ".join(parts)}


def recommend(
    network: Network,
    trains: dict[str, Train],
    starts: dict[str, dict[str, Any]],
    evidence: EvidenceStore,
    now_t: int,
    weights: dict[str, float],
    headway: float = DEFAULT_HEADWAY_MIN,
    top: int = 8,
) -> dict[str, Any]:
    """Rank controller alternatives for every active train.

    `starts[tid]` = {"node", "time_min", "prefix": [Traversal]} describing where
    each train can next be routed from (a running train first finishes its
    current section, which is included as an occupation in `prefix`).
    """

    active = [tid for tid in sorted(trains) if tid in starts]
    routes = {tid: simple_routes(network, starts[tid]["node"], trains[tid].destination) for tid in active}
    options: dict[str, list[TrainPlan]] = {}
    rejected: list[dict[str, Any]] = []
    for tid in active:
        train, start = trains[tid], starts[tid]
        others = {sid for other in active if other != tid for r in routes[other] for sid in r}
        plans = []
        for route in routes[tid]:
            # Hold at departure, or at the node before the first section another train may use.
            shared = [i for i, sid in enumerate(route) if sid in others]
            hold_points = sorted({0, *(shared[:1])})
            for hold_index in hold_points:
                for hold in HOLD_OPTIONS_MIN:
                    if hold == 0 and hold_index != 0:
                        continue
                    plan = build_train_plan(
                        network,
                        train,
                        start["node"],
                        start["time_min"],
                        route,
                        hold_index,
                        hold,
                        start.get("prefix", []),
                    )
                    if plan.violations:
                        if hold == 0:
                            rejected.append({"train_id": tid, "route": route, "reasons": plan.violations})
                        continue
                    plans.append(plan)
        options[tid] = plans

    candidates = []
    infeasible_conflicts = 0
    for combo in itertools.product(*(options[tid] for tid in active)):
        plans = dict(zip(active, combo, strict=True))
        pairs = []
        for p, q in itertools.combinations(combo, 2):
            pairs += conflicts_between(network, p, q, headway)
        if any(c["is_conflict"] for c in pairs):
            infeasible_conflicts += 1
            continue
        candidates.append((plans, pairs))

    if not candidates:
        return {
            "state": "NO_FEASIBLE_PLAN",
            "candidates": [],
            "rejected_routes": rejected,
            "conflicting_combinations": infeasible_conflicts,
            "weights": weights,
        }

    raw = []
    for plans, pairs in candidates:
        conflict = sum(max(0.0, (2 * headway - c["gap_min"]) / headway) for c in pairs if c["gap_min"] < 2 * headway)
        threat = sum(section_threat_weight(network, t.section_id) for p in plans.values() for t in p.traversals)
        ev = [
            _evidence_penalty(evidence.state_of(f"condition:{t.section_id}", now_t))
            for p in plans.values()
            for t in p.traversals
        ]
        ev += [_evidence_penalty(evidence.state_of(f"position:{tid}", now_t)) for tid in plans]
        holds = sum(1 for p in plans.values() if p.hold_node)
        reroutes = sum(
            1
            for tid, p in plans.items()
            if p.route != trains[tid].default_route[len(trains[tid].default_route) - len(p.route) :]
        )
        raw.append(
            {
                "delay": sum(trains[tid].delay_weight * p.delay_min for tid, p in plans.items()),
                "conflict": conflict,
                "infra": sum(p.stress for p in plans.values()),
                "energy": sum(p.energy for p in plans.values()),
                "threat": threat,
                "evidence": sum(ev) / len(ev) if ev else 1.0,
                "complexity": holds + reroutes,
            }
        )
    shown = scoring.rank(scoring.score(raw, weights), top)
    out = []
    for n, cand in enumerate(shown, start=1):
        plans, pairs = candidates[cand["index"]]
        desc = describe(network, trains, plans)
        out.append(
            {
                "candidate_id": f"C{n}",
                "action": desc["action"],
                "summary": desc["summary"],
                **scoring.public(cand),
                "closest_separations": sorted(pairs, key=lambda c: c["gap_min"])[:3],
                "train_plans": {tid: p.to_dict() for tid, p in plans.items()},
            }
        )
    return {
        "state": "RANKED",
        "candidates": out,
        "feasible_count": len(candidates),
        "conflicting_combinations": infeasible_conflicts,
        "rejected_routes": rejected,
        "weights": weights,
        "headway_min": headway,
    }
