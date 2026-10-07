"""Disruption re-planning: propagate a delay and propose conflict-free holds.

What a section controller does by hand after a late running train, written as
an algorithm:

1. Propagate the delay along the train's remaining path. Each section can
   recover a share (default half) of (scheduled run time - model P10 run time),
   and each halt can recover dwell above a minimum, so recovery comes from the
   ML model rather than a flat assumed allowance.
2. At every section entry, look for other trains entering the same directed
   section too close behind or ahead. The required separation for a pair is
   min(headway, the separation the published timetable already plans for that
   pair): the timetable is assumed feasible, so only separations the
   disruption makes *worse* count as conflicts.
3. Resolve each conflict by priority: the lower-priority train is held at the
   station before the section until the headway is restored. A train that is
   held is itself propagated, so knock-on conflicts are found too, up to a
   bounded cascade.

The output is a *proposed plan* (holds, resulting delays, unresolved items and
assumptions) for a human controller to accept or reject. Nothing here talks to
signalling, interlocking, Kavach or any train; it only reads the timetable.
"""

from __future__ import annotations

import sqlite3
from bisect import bisect_right, insort
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from india_rail.network import DEFAULT_PRIORITY, UNKNOWN_PRIORITY, clock
from india_rail.runtime_model import TrainedRuntimeModel, load_sections

MIN_DWELL_MIN = 2  # a booked halt cannot be cut below this many minutes
MAX_SECTION_PASSES = 8
MAX_PROPAGATIONS = 500
DEFAULT_RECOVERY_FACTOR = 0.5


def circular_gap(a: int, b: int) -> int:
    """Signed minutes from b to a on a 24-hour clock, in [-720, 720)."""

    return (a - b + 720) % 1440 - 720


@dataclass
class TrainTimeline:
    number: str
    train_type: str
    stations: list[str]
    arr: list[int]
    dep: list[int]
    recovery: list[float]  # recoverable minutes on section i -> i+1
    delay_at: dict[int, float] = field(default_factory=dict)  # stop index -> departure delay
    delay_keys: list[int] = field(default_factory=list)  # sorted keys of delay_at


@dataclass
class PlanAction:
    action: str
    train_number: str
    station_code: str
    minutes: int
    reason: str


class DisruptionPlanner:
    def __init__(
        self, con: sqlite3.Connection, model: TrainedRuntimeModel | None = None, priority: dict[str, int] | None = None
    ):
        self.con = con
        self.model = model
        self.priority = priority or DEFAULT_PRIORITY
        self.sections = load_sections(con)
        self.sections_by_train = {k: v.sort_values("seq") for k, v in self.sections.groupby("train_number", sort=False)}
        self.entries: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
        for train, seq, a, b in zip(
            self.sections["train_number"],
            self.sections["seq"],
            self.sections["from_code"],
            self.sections["to_code"],
            strict=True,
        ):
            self.entries[(a, b)].append((train, int(seq)))
        self._timelines: dict[str, TrainTimeline] = {}
        self._recovery_factor = DEFAULT_RECOVERY_FACTOR
        self._types = dict(con.execute("SELECT number, coalesce(type, '') FROM trains").fetchall())
        stops = pd.read_sql_query(
            "SELECT train_number, station_code, arr_min, dep_min FROM stops ORDER BY train_number, seq", con
        )
        self._stops = {
            number: (g["station_code"].tolist(), g["arr_min"].tolist(), g["dep_min"].tolist())
            for number, g in stops.groupby("train_number", sort=False)
        }

    # ---- timeline construction ---------------------------------------------
    def timeline(self, number: str) -> TrainTimeline:
        if number in self._timelines:
            return self._timelines[number]
        if number not in self._stops:
            raise KeyError(f"Unknown train {number}")
        stations, arr, dep = self._stops[number]
        timeline = TrainTimeline(
            number=number,
            train_type=self._types.get(number, ""),
            stations=stations,
            arr=arr,
            dep=dep,
            recovery=[],
        )
        self._timelines[number] = timeline
        return timeline

    def recovery(self, tl: TrainTimeline) -> list[float]:
        """Recoverable minutes per section, computed only for trains that run late.

        recovery_factor x (scheduled - model P10). Only a share of the gap to
        the fastest similarly timetabled running is assumed recoverable, since
        part of it reflects this train's own acceleration and braking needs.
        """

        if tl.recovery:
            return tl.recovery
        recovery = [0.0] * (len(tl.stations) - 1)
        rows = self.sections_by_train.get(tl.number)
        if rows is not None and self.model is not None and self._recovery_factor > 0:
            p10 = self.model.predict_frame(rows)["p10"].to_numpy()
            slack = np.maximum(rows["runtime_min"].to_numpy() - p10, 0.0) * self._recovery_factor
            for seq, value in zip(rows["seq"].to_numpy(), slack, strict=True):
                if seq < len(recovery):
                    recovery[int(seq)] = float(value)
        tl.recovery = recovery
        return recovery

    def rank(self, timeline: TrainTimeline) -> int:
        return self.priority.get(timeline.train_type, UNKNOWN_PRIORITY)

    def _current_delay(self, timeline: TrainTimeline, index: int) -> float:
        position = bisect_right(timeline.delay_keys, index)
        return timeline.delay_at[timeline.delay_keys[position - 1]] if position else 0.0

    def _set_delay(self, timeline: TrainTimeline, index: int, value: float) -> None:
        if index not in timeline.delay_at:
            insort(timeline.delay_keys, index)
        timeline.delay_at[index] = value

    # ---- core algorithm ----------------------------------------------------
    def plan(
        self,
        train_number: str,
        station_code: str,
        delay_min: int,
        *,
        headway_min: int = 6,
        max_cascade_trains: int = 30,
        resolve: bool = True,
        recovery_factor: float = DEFAULT_RECOVERY_FACTOR,
    ) -> dict[str, Any]:
        if delay_min <= 0:
            raise ValueError("delay_min must be positive")
        if not 0 <= recovery_factor <= 1:
            raise ValueError("recovery_factor must be between 0 and 1")
        self._timelines = {}
        self._recovery_factor = recovery_factor
        origin = self.timeline(train_number)
        try:
            start = origin.stations.index(station_code.upper())
        except ValueError as exc:
            raise ValueError(f"Train {train_number} does not call at {station_code}") from exc

        unresolved: list[dict[str, Any]] = []
        conflicts_found = 0
        affected: set[str] = {train_number}
        # Delay sources per train: the initial disruption and holds imposed by
        # other trains. Each walk recomputes a train's path from scratch using
        # these, so a train re-planned several times never double counts.
        injected: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
        injected[train_number][start] += float(delay_min)
        self_holds: dict[str, list[PlanAction]] = defaultdict(list)
        forced_holds: list[PlanAction] = []
        queue: deque[str] = deque([train_number])
        queued = {train_number}

        walks = 0
        while queue and walks < MAX_PROPAGATIONS:
            walks += 1
            number = queue.popleft()
            queued.discard(number)
            tl = self.timeline(number)
            sources = injected[number]
            first, last_source = min(sources), max(sources)
            tl.delay_keys = [k for k in tl.delay_keys if k < first]
            tl.delay_at = {k: tl.delay_at[k] for k in tl.delay_keys}
            self_holds[number] = []
            delay = 0.0
            i = first
            while i < len(tl.stations) - 1:
                if i > first and delay > 0:
                    halt_slack = max(tl.dep[i] - tl.arr[i] - MIN_DWELL_MIN, 0)
                    delay = max(delay - halt_slack, 0.0)
                delay += sources.get(i, 0.0)
                self._set_delay(tl, i, delay)
                if delay <= 0.5:
                    if i >= last_source:
                        break
                    i += 1
                    continue
                entry = tl.dep[i] + delay
                key = (tl.stations[i], tl.stations[i + 1])
                section = f"{key[0]}->{key[1]}"
                # Holding this train can create a new conflict with a train
                # already checked on the same section, so rescan until stable.
                settled: set[str] = set()
                for _ in range(MAX_SECTION_PASSES):
                    held_self = False
                    for other_number, other_seq in self.entries.get(key, []):
                        if other_number == number or other_number in settled:
                            continue
                        other = self.timeline(other_number)
                        other_entry = other.dep[other_seq] + self._current_delay(other, other_seq)
                        gap = circular_gap(round(entry), round(other_entry))
                        # The published timetable is taken as feasible: never
                        # demand more separation than it already plans for
                        # this pair (busy suburban lines run tighter than the
                        # default headway; trains with disjoint running days
                        # appear simultaneous because days are unknown).
                        planned = abs(circular_gap(tl.dep[i], other.dep[other_seq]))
                        required = min(headway_min, planned)
                        if abs(gap) >= required:
                            continue
                        conflicts_found += 1
                        settled.add(other_number)
                        if not resolve:
                            unresolved.append(
                                {
                                    "section": section,
                                    "trains": [number, other_number],
                                    "separation_min": abs(gap),
                                    "required_min": required,
                                }
                            )
                            continue
                        if self.rank(tl) > self.rank(other) or (self.rank(tl) == self.rank(other) and gap >= 0):
                            hold = max(int(np.ceil(required - gap)), 1)
                            delay += hold
                            entry += hold
                            self._set_delay(tl, i, delay)
                            self_holds[number].append(
                                PlanAction(
                                    "HOLD",
                                    number,
                                    key[0],
                                    hold,
                                    f"Give way to {other_number} ({other.train_type or 'unknown type'}) entering "
                                    f"{section}; restores {required} min separation.",
                                )
                            )
                            held_self = True
                        elif len(affected) < max_cascade_trains or other_number in affected:
                            hold = max(int(np.ceil(required + gap)), 1)
                            affected.add(other_number)
                            injected[other_number][other_seq] += hold
                            self._set_delay(other, other_seq, self._current_delay(other, other_seq) + hold)
                            forced_holds.append(
                                PlanAction(
                                    "HOLD",
                                    other_number,
                                    key[0],
                                    hold,
                                    f"Give way to higher-priority {number} ({tl.train_type or 'unknown type'}) "
                                    f"entering {section}; restores {required} min separation.",
                                )
                            )
                            if other_number not in queued:
                                queue.append(other_number)
                                queued.add(other_number)
                        else:
                            unresolved.append(
                                {
                                    "section": section,
                                    "trains": [number, other_number],
                                    "reason": "cascade limit reached",
                                }
                            )
                    if not held_self:
                        break
                delay = max(delay - self.recovery(tl)[i], 0.0)
                i += 1
            self._set_delay(tl, i, delay)

        if queue:
            unresolved.append({"reason": f"re-planning limit {MAX_PROPAGATIONS} reached", "pending": len(queue)})
        actions = forced_holds + [act for holds in self_holds.values() for act in holds]

        impacts = []
        for number in sorted(affected):
            tl = self._timelines[number]
            final = self._current_delay(tl, len(tl.stations) - 1)
            impacts.append(
                {
                    "train_number": number,
                    "train_type": tl.train_type,
                    "destination": tl.stations[-1],
                    "scheduled_arrival": clock(tl.arr[-1]),
                    "projected_delay_at_destination_min": round(final, 1),
                }
            )
        merged: dict[tuple[str, str], PlanAction] = {}
        for act in actions:
            k = (act.train_number, act.station_code)
            if k in merged:
                merged[k].minutes += act.minutes
            else:
                merged[k] = PlanAction(**act.__dict__)
        totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for act in merged.values():
            totals[act.train_number][0] += 1
            totals[act.train_number][1] += act.minutes
        hold_summary = [
            {"train_number": n, "holds": c, "total_hold_min": m}
            for n, (c, m) in sorted(totals.items(), key=lambda kv: -kv[1][1])
        ]
        return {
            "status": "PROPOSED_FOR_CONTROLLER_REVIEW",
            "disruption": {"train_number": train_number, "station_code": station_code.upper(), "delay_min": delay_min},
            "parameters": {
                "headway_min": headway_min,
                "max_cascade_trains": max_cascade_trains,
                "resolve": resolve,
                "recovery_factor": recovery_factor,
            },
            "conflicts_detected": conflicts_found,
            "hold_summary": hold_summary,
            "actions": [a.__dict__ for a in merged.values()],
            "train_impacts": impacts,
            "total_delay_at_destinations_min": round(sum(x["projected_delay_at_destination_min"] for x in impacts), 1),
            "unresolved": unresolved,
            "assumptions": [
                "Every train is assumed to run daily (the open timetable has no running days).",
                "Required separation per train pair = min(headway, separation planned in the published timetable).",
                (
                    "Conflicts are checked per directed section; single-line opposing moves and "
                    "platform/loop capacity are not modelled without track-count data."
                ),
                f"Recovery per section = {recovery_factor:g} x (scheduled run time - model P10 run time).",
                f"Halts may be shortened to {MIN_DWELL_MIN} minutes to recover time.",
                "Priority ranking is a configurable default, not a divisional operating order.",
            ],
        }
