"""Randomised simulation harness: fuzz both twins with operation sequences and check safety invariants.

    python -m india_rail.railguard.simulate --demo 4500000 --national 500000 --workers 4 \
        --out seva2026/evidence/simulation/simulation_results.json
    python -m india_rail.railguard.simulate --replay demo:1234 --seed 2026   # re-run one episode verbosely

One *episode* = a fresh twin, randomised starting conditions, then a random
sequence of operations (clock ticks, recommendations, approvals including stale
or wrong ones, section and sensor events, malformed or implausible feed data,
controller holds, threat acknowledgements), with every invariant below checked
after every operation. Episodes are seeded by (seed, twin, index), so any
failure is reproducible from its id alone.

Invariants (a violation is recorded with the episode id and operation trace):
  SAFE_SEPARATION   approved plans never conflict; simulated trains never share a single-line section
                    or close up on one track (checked every 5 s of simulated time)
  APPROVAL_GATE     an approval only succeeds on the latest recommendation for the current state, with
                    fresh evidence, no open critical threat, and a plan avoiding closed/obstructed sections
  EVIDENCE_GATE     stale or missing mandatory evidence never yields an approvable recommendation
  INPUT_REJECTION   malformed, replayed, future or physically impossible observations never move the twin
  CAB_ADVISORY      no speed band without fresh evidence and an approved plan; never a proceed status
                    with a blocked section in the lookahead; band never above the line speed
  RANKING           ranked plans are conflict-free, feasible, monotonic in time, never early, scored 0-1,
                    winner first
  REPLAY            sampled snapshots verify and replay to the same ranking; audit chain verifies
  NO_CRASH          no unexpected exception
  LIVENESS          every episode finishes within EPISODE_LIMIT_S (no hang in planning)
This is a software-in-the-loop test of the twins' own rules on synthetic and open
timetable data, not a field validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import platform
import random
import signal
import sys
import time
import traceback
from collections import Counter
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from india_rail.railguard.cab import CAUTION, DATA_UNAVAILABLE, NORMAL, build_advisory
from india_rail.railguard.engine import RailGuardEngine, plan_from_dict
from india_rail.railguard.evidence import AGING, FRESH, STALE
from india_rail.railguard.planner import TrainPlan
from india_rail.railguard.scoring import PRESETS
from india_rail.railguard.stress import running_speed

TOL = 0.02  # minutes: plans are stored rounded to 0.01 min
MAX_FAILURES_KEPT = 50
EPISODE_LIMIT_S = 60  # an episode (a whole operating sequence) slower than this is a liveness failure


class Violation(Exception):
    def __init__(self, invariant: str, detail: str):
        super().__init__(f"{invariant}: {detail}")
        self.invariant, self.detail = invariant, detail


def check(condition: bool, invariant: str, detail: str) -> None:
    if not condition:
        raise Violation(invariant, detail)


def _rng(seed: int, twin: str, index: int) -> random.Random:
    return random.Random(f"{seed}:{twin}:{index}")  # nosec B311 - seeded on purpose: every episode is reproducible


def _weighted(rng: random.Random, table: list[tuple[str, int]]) -> str:
    return rng.choices([k for k, _ in table], weights=[w for _, w in table])[0]


# ==== shared ranking checks ==================================================================================
def _check_scores(candidates: list[dict[str, Any]], weights: dict[str, float]) -> None:
    check(bool(candidates), "RANKING", "RANKED without candidates")
    check("RECOMMENDED" in candidates[0]["labels"], "RANKING", "first candidate is not the recommended one")
    best = min(c["score"] for c in candidates)
    check(candidates[0]["score"] <= best + 1e-6, "RANKING", "recommended candidate does not have the lowest score")
    ids = [c["candidate_id"] for c in candidates]
    check(len(ids) == len(set(ids)), "RANKING", "duplicate candidate ids")
    for c in candidates:
        for k, v in c["factors"].items():
            check(-1e-6 <= v <= 1 + 1e-6, "RANKING", f"factor {k}={v} outside 0-1 in {c['candidate_id']}")
            check(abs(c["contributions"][k] - weights[k] * v) < 2e-3, "RANKING", f"contribution {k} != w*f")


# ==== tabletop twin ==========================================================================================
def demo_fingerprint(e: RailGuardEngine) -> tuple:
    """Everything a recommendation depends on (the harness's own view, independent of the engine's bookkeeping)."""

    sections = tuple(
        (s.id, s.condition, s.temp_restriction_kmph, s.weather_alert, s.obstacle, s.available)
        for s in e.net.sections.values()
    )
    trains = tuple(
        (t.id, t.section_id, t.from_node, t.offset_km, t.finished, t.feed_frozen, t.sensor_offline, t.last_position_t)
        for t in e.trains.values()
    )
    flags = tuple(sorted((tid, f["type"], f["until_t"]) for tid, fs in e.flags.items() for f in fs))
    holds = tuple(sorted(e.controller_hold))
    approved = tuple(sorted((k, v["snapshot_id"]) for k, v in e.approved.items()))
    return e.t, sections, trains, flags, holds, approved


DEMO_OPS = [
    ("tick", 30),
    ("recommend", 14),
    ("approve", 14),
    ("approve_stale", 3),
    ("section", 8),
    ("fault", 6),
    ("gnss", 4),
    ("sensor_valid", 3),
    ("sensor_invalid", 7),
    ("hold", 2),
    ("ack", 3),
    ("reject", 1),
    ("preset", 2),
    ("silence_hw", 1),
]
INVALID_KINDS = (
    "unknown_train", "bad_source", "bad_section", "offset", "speed", "future", "old", "replay", "jump", "nan",
)  # fmt: skip


class DemoEpisode:
    def __init__(self, index: int, seed: int, verbose: bool = False):
        self.id = f"demo:{index}"
        self.rng = _rng(seed, "demo", index)
        self.verbose = verbose
        self.trace: list[str] = []
        self.stats: Counter = Counter()
        self.e = RailGuardEngine()
        self.silenced: set[str] = set()
        self.fingerprint: tuple | None = None

    def log(self, text: str) -> None:
        self.trace.append(f"t={self.e.t}s {text}")
        if self.verbose:
            print(self.trace[-1])

    # ---- setup -------------------------------------------------------------------------------------------
    def setup(self) -> None:
        e, rng = self.e, self.rng
        a, b = e.trains["A"], e.trains["B"]
        a.departure_delay_min = round(rng.uniform(0, 25), 1) if rng.random() < 0.7 else 0.0
        b.departure_delay_min = round(rng.uniform(0, 15), 1) if rng.random() < 0.5 else 0.0
        sections = sorted(e.net.sections)
        for _ in range(rng.randint(0, 3)):
            self._section_event(rng.choice(sections))
        if rng.random() < 0.3:
            e.set_weights(rng.choice(sorted(PRESETS)))
        e.refresh()
        self.log(f"setup delays A={a.departure_delay_min} B={b.departure_delay_min}")

    def _section_event(self, sid: str) -> None:
        kind = self.rng.choice(("condition", "restriction", "weather", "obstacle", "close", "clear", "open"))
        changes: dict[str, Any] = {
            "condition": {"condition": round(self.rng.uniform(0.2, 1.0), 2)},
            "restriction": {"temp_restriction_kmph": self.rng.choice((None, 30.0, 45.0, 60.0))},
            "weather": {"weather_alert": self.rng.choice((None, "HEAT", "FOG", "FLOOD_WATCH"))},
            "obstacle": {"obstacle": True},
            "close": {"available": False},
            "clear": {"obstacle": False},
            "open": {"available": True},
        }[kind]
        source = "INSPECTION_REPORT" if kind == "clear" else "TRACKSENSE_SIM"
        self.e.update_section(sid, source, **changes)
        self.log(f"section {sid} {changes}")

    # ---- ground truth --------------------------------------------------------------------------------------
    def truth(self, tid: str, minute: float) -> tuple[str | None, str, float, float]:
        """Where the real train is: it follows its approved plan (and holds); without one it waits."""

        train = self.e.trains[tid]
        if tid not in self.e.approved:
            return train.section_id, train.from_node, train.offset_km, 0.0
        sid, node, offset, speed, _done = self.e._simulated_position(tid, minute)
        return sid, node, offset, speed

    def check_separation(self, minute: float) -> None:
        e = self.e
        live = [t for t in sorted(e.trains) if not e.trains[t].finished]
        spots = {t: self.truth(t, minute) for t in live}
        for i, a in enumerate(live):
            for b in live[i + 1 :]:
                (sa, fa, oa, _), (sb, fb, ob, _) = spots[a], spots[b]
                if sa is None or sa != sb:
                    continue
                section = e.net.sections[sa]
                check(section.tracks != 1, "SAFE_SEPARATION", f"{a} and {b} both on single-line {sa}")
                if fa == fb:
                    check(abs(oa - ob) >= 0.5, "SAFE_SEPARATION", f"{a} and {b} {abs(oa - ob):.2f} km apart on {sa}")

    def check_plans(self) -> None:
        e = self.e
        now = e.t / 60
        live = [t for t in sorted(e.trains) if not e.trains[t].finished and t in e.approved]
        plans = {t: _future(plan_from_dict(e.approved[t]["plan"]), now) for t in live}
        _check_pairwise(e, plans, "SAFE_SEPARATION", "approved plans")

    # ---- operations ----------------------------------------------------------------------------------------
    def op_tick(self, seconds: int | None = None) -> None:
        seconds = seconds or self.rng.choice((5, 10, 15, 30, 60, 60, 120, 300))
        self.log(f"tick {seconds}s")
        for _ in range(seconds // 5):
            self.stats["sim_steps_5s"] += 1
            self.e.tick(5)
            for tid in sorted(self.e.hardware_fed):
                if tid not in self.silenced and not self.e.trains[tid].finished:
                    self._feed_truth(tid, self.e.t)
            self.check_separation(self.e.t / 60)

    def _feed_truth(self, tid: str, t: int) -> dict[str, Any]:
        sid, node, offset, speed = self.truth(tid, t / 60)
        obs = {"train_id": tid, "section_id": sid, "from_node": node, "offset_km": offset, "speed_kmph": speed}
        obs.update(source="TWINTRACK_SENSOR", t=self.e.t, sequence=self.e.last_sequence[tid] + 1)
        result = self.e.ingest_position(obs)
        check(result.get("accepted", False), "INPUT_REJECTION", f"true position of {tid} rejected: {result}")
        if result.get("applied") and sid is None and node == self.e.trains[tid].destination:
            self.e.trains[tid].finished = True
        return result

    def op_recommend(self) -> None:
        e = self.e
        stale = [
            t
            for t, tr in e.trains.items()
            if not tr.finished and e.evidence.state_of(f"position:{t}", e.t) not in (FRESH, AGING)
        ]
        critical = [t for t in e.threats.active() if t.severity == "CRITICAL" and t.lifecycle == "OPEN"]
        rec = e.recommend()
        self.fingerprint = demo_fingerprint(e)
        self.stats[f"recommend_{rec['state']}"] += 1
        self.log(f"recommend -> {rec['state']} ({len(rec['ranking'].get('candidates', []))} candidates)")
        check(rec["approvable"] == (rec["state"] == "REVIEWABLE"), "EVIDENCE_GATE", "approvable flag mismatch")
        if stale:
            check(not rec["approvable"], "EVIDENCE_GATE", f"approvable with stale/missing position {stale}")
        if critical:
            check(not rec["approvable"], "APPROVAL_GATE", "approvable with an open critical threat")
        ranking = rec["ranking"]
        if ranking["state"] == "RANKED":
            _check_scores(ranking["candidates"], e.weights)
            for cand in ranking["candidates"]:
                plans = {t: plan_from_dict(p) for t, p in cand["train_plans"].items()}
                self._check_candidate(plans, cand["candidate_id"])
        else:
            check(not ranking["candidates"], "RANKING", "candidates listed without a ranking")
        if self.rng.random() < 0.05:
            replay = e.replay(rec["snapshot_id"])
            self.stats["replays"] += 1
            check(replay["integrity_ok"] and replay["replay_matches"], "REPLAY", f"replay mismatch {replay}")

    def _check_candidate(self, plans: dict[str, TrainPlan], cid: str) -> None:
        e = self.e
        now = e.t / 60
        for tid, plan in plans.items():
            train = e.trains[tid]
            prev_exit = None
            for i, trav in enumerate(plan.traversals):
                check(trav.exit >= trav.enter - TOL, "RANKING", f"{cid} {tid} exits {trav.section_id} before entry")
                if prev_exit is not None:
                    check(trav.enter >= prev_exit - TOL, "RANKING", f"{cid} {tid} overlaps itself")
                prev_exit = trav.exit
                if trav.exit < now or (i == 0 and train.section_id is not None):
                    continue  # past, or the section the train is already on (it must clear it)
                section = e.net.sections[trav.section_id]
                check(section.available, "RANKING", f"{cid} routes {tid} over closed {trav.section_id}")
                check(not section.obstacle, "RANKING", f"{cid} routes {tid} over obstructed {trav.section_id}")
                check(train.axle_load_t <= section.axle_limit_t, "RANKING", f"{cid} axle limit {trav.section_id}")
            departs = train.scheduled_departure_min + train.departure_delay_min
            if train.section_id is None and train.from_node == train.origin and tid not in e.approved:
                first = plan.traversals[0].enter if plan.traversals else departs
                check(first >= departs - TOL, "RANKING", f"{cid} departs {tid} early ({first} < {departs})")
        _check_pairwise(e, {t: _future(p, now) for t, p in plans.items()}, "RANKING", cid)

    def op_approve(self, stale: bool = False) -> None:
        e, rng = self.e, self.rng
        latest = e.latest
        if latest is None:
            return
        candidates = latest["ranking"].get("candidates") or [{"candidate_id": "C1"}]
        cid = candidates[0]["candidate_id"] if rng.random() < 0.7 else rng.choice(candidates)["candidate_id"]
        snapshot = latest["snapshot_id"]
        if stale:
            snapshot = rng.choice((f"SNAP-{rng.randint(1, 9999):04d}", snapshot))
            cid = rng.choice((cid, "C99"))
        # What must hold for an approval to be legitimate, judged on the state right now.
        same_state = self.fingerprint == demo_fingerprint(e)
        stale_now = [
            t
            for t, tr in e.trains.items()
            if not tr.finished and e.evidence.state_of(f"position:{t}", e.t) not in (FRESH, AGING)
        ]
        critical = [t.type for t in e.threats.active() if t.severity == "CRITICAL" and t.lifecycle == "OPEN"]
        chosen = next((c for c in latest["ranking"].get("candidates", []) if c["candidate_id"] == cid), None)
        blocked = []
        for tid, plan in (chosen or {}).get("train_plans", {}).items():
            for trav in plan["traversals"]:
                section = e.net.sections[trav["section_id"]]
                on_it = trav["section_id"] == e.trains[tid].section_id
                if trav["exit"] >= e.t / 60 and not on_it and (section.obstacle or not section.available):
                    blocked.append(section.id)
        try:
            e.approve(snapshot, cid, rng.choice(("controller-1", "controller-2")))
        except (ValueError, KeyError) as exc:
            self.stats["approve_refused"] += 1
            self.log(f"approve {snapshot}/{cid} refused: {exc}")
            return
        self.stats["approve_ok"] += 1
        self.log(f"approve {snapshot}/{cid} OK")
        check(snapshot == latest["snapshot_id"] and latest["approvable"], "APPROVAL_GATE", "approved a non-latest plan")
        check(same_state, "APPROVAL_GATE", "approved a recommendation made for a different twin state")
        check(not stale_now, "APPROVAL_GATE", f"approved with stale/missing position of {stale_now}")
        check(not critical, "APPROVAL_GATE", f"approved with open critical threat {critical}")
        check(not blocked, "APPROVAL_GATE", f"approved a plan over blocked {blocked}")
        self.check_plans()

    def op_section(self) -> None:
        self._section_event(self.rng.choice(sorted(self.e.net.sections)))

    def op_fault(self) -> None:
        tid = self.rng.choice(("A", "B"))
        kind = self.rng.choice(("freeze_feed", "unfreeze_feed", "sensor_offline", "sensor_online"))
        self.e.inject_fault(kind, tid)
        self.log(f"fault {kind} {tid}")

    def op_gnss(self) -> None:
        e, tid = self.e, self.rng.choice(("A", "B"))
        sid = self.rng.choice(sorted(e.net.sections))
        section = e.net.sections[sid]
        obs = {"train_id": tid, "section_id": sid, "from_node": section.a, "source": "GNSS_SIM"}
        obs.update(offset_km=round(self.rng.uniform(0, section.length_km), 2), speed_kmph=50.0, t=e.t)
        before = e.position_of(tid)
        result = e.ingest_position(obs)
        self.log(f"gnss {tid} {sid} -> {result}")
        check(e.position_of(tid) == before, "INPUT_REJECTION", "GNSS-sim observation moved the twin")

    def op_sensor_valid(self) -> None:
        tid = self.rng.choice(("A", "B"))
        if self.e.trains[tid].finished:
            return
        self.silenced.discard(tid)
        self.log(f"sensor_valid {tid} -> {self._feed_truth(tid, self.e.t)}")

    def op_silence_hw(self) -> None:
        if self.e.hardware_fed:
            tid = self.rng.choice(sorted(self.e.hardware_fed))
            self.silenced.add(tid)
            self.log(f"silence hardware feed {tid}")

    def op_sensor_invalid(self) -> None:
        e, rng = self.e, self.rng
        tid = rng.choice(("A", "B"))
        train = e.trains[tid]
        section = e.net.sections["S06"]
        kind = rng.choice(INVALID_KINDS)
        obs: dict[str, Any] = {"train_id": tid, "source": "TWINTRACK_SENSOR", "t": e.t, "speed_kmph": 40.0}
        obs.update(section_id=train.section_id, from_node=train.from_node, offset_km=train.offset_km)
        obs["sequence"] = e.last_sequence[tid] + 1
        if kind == "unknown_train":
            obs["train_id"] = "Z9"
        elif kind == "bad_source":
            obs["source"] = "SPOOF"
        elif kind == "bad_section":
            obs.update(section_id="S99", from_node="X")
        elif kind == "offset":
            obs.update(section_id="S06", from_node=section.a, offset_km=section.length_km + rng.uniform(0.1, 50))
        elif kind == "speed":
            obs["speed_kmph"] = rng.choice((-5.0, 251.0, 1e6))
        elif kind == "future":
            obs["t"] = e.t + rng.randint(6, 10_000)
        elif kind == "old":
            if train.last_position_t is None or train.last_position_t == 0:
                return
            obs["t"] = train.last_position_t - rng.randint(1, max(train.last_position_t, 1))
        elif kind == "replay":
            if e.last_sequence[tid] == 0:
                return
            obs["sequence"] = rng.randint(0, e.last_sequence[tid])
        elif kind == "jump":
            far = max(e.net.sections.values(), key=lambda s: e.track_distance(e.position_of(tid), (s.id, s.a, 0.0)))
            if e.track_distance(e.position_of(tid), (far.id, far.a, 0.0)) < 5:
                return
            last = train.last_position_t if train.last_position_t is not None else e.t
            obs.update(section_id=far.id, from_node=far.a, offset_km=0.0, t=last)  # same second: a true jump
        elif kind == "nan":
            obs["offset_km"] = rng.choice(("abc", None, [1]))
        before, seq = e.position_of(tid), e.last_sequence[tid]
        try:
            result = e.ingest_position(obs)
        except (TypeError, ValueError) as exc:
            result = {"accepted": False, "reason": f"raised {type(exc).__name__}"}
        self.stats[f"invalid_{kind}"] += 1
        self.log(f"sensor_invalid {kind} {tid} -> {result}")
        check(not result.get("accepted"), "INPUT_REJECTION", f"{kind} observation accepted: {obs}")
        check(e.position_of(tid) == before and e.last_sequence[tid] == seq, "INPUT_REJECTION", f"{kind} moved twin")

    def op_hold(self) -> None:
        tid = self.rng.choice(("A", "B", None))
        self.e.hold("controller-1", "simulation hold", tid)
        self.log(f"hold {tid or 'all'}")

    def op_ack(self) -> None:
        active = [t for t in self.e.threats.active() if t.lifecycle == "OPEN"]
        if active:
            threat = self.rng.choice(active)
            self.e.acknowledge(threat.id, "controller-1")
            self.log(f"ack {threat.id} {threat.type}")

    def op_reject(self) -> None:
        if self.e.latest:
            self.e.reject(self.e.latest["snapshot_id"], "controller-1", "simulation")

    def op_preset(self) -> None:
        self.e.set_weights(self.rng.choice(sorted(PRESETS)))

    # ---- invariants after every operation -------------------------------------------------------------------
    def check_cab(self) -> None:
        e = self.e
        for tid, train in e.trains.items():
            adv = build_advisory(e, tid)
            band, status = adv["advisory_speed_band_kmph"], adv["status"]
            if train.finished:
                continue
            state = e.evidence.state_of(f"position:{tid}", e.t)
            if state not in (FRESH, AGING) or train.sensor_offline:
                check(status == DATA_UNAVAILABLE, "CAB_ADVISORY", f"{tid} status {status} with {state} position")
            if status not in (NORMAL, CAUTION):
                check(band is None, "CAB_ADVISORY", f"{tid} speed band shown in {status}")
            if band is not None:
                check(tid in e.approved, "CAB_ADVISORY", f"{tid} band without an approved plan")
                sid = train.section_id or (adv["route_strip"]["approved_route"] or [None])[0]
                if sid:
                    limit = running_speed(train, e.net.sections[sid])
                    check(band[1] <= limit + 0.5, "CAB_ADVISORY", f"{tid} band {band} above line speed {limit}")
            if status in (NORMAL, CAUTION) and tid in e.approved:
                for sid in e.route_ahead(tid)[:3]:
                    section = e.net.sections[sid]
                    blocked = section.obstacle or not section.available
                    check(not blocked, "CAB_ADVISORY", f"{tid} shown {status} with blocked {sid} ahead")

    def run(self) -> None:
        self.setup()
        self.check_cab()
        steps = self.rng.randint(8, 30)
        for _ in range(steps):
            op = _weighted(self.rng, DEMO_OPS)
            self.stats[f"op_{op}"] += 1
            self.stats["ops"] += 1
            if op == "approve_stale":
                self.op_approve(stale=True)
            else:
                getattr(self, f"op_{op}")()
            self.check_plans()
            self.check_cab()
        # Then operate it properly to the end: re-rank, approve when allowed, run the clock.
        for tid in list(self.silenced):
            self.silenced.discard(tid)
        for tid in ("A", "B"):
            self.e.inject_fault("unfreeze_feed", tid)
            self.e.inject_fault("sensor_online", tid)
        if self.rng.random() < 0.7:  # inspection completed: blockages lifted
            for sid, section in self.e.net.sections.items():
                if section.obstacle or not section.available:
                    self.e.update_section(sid, "INSPECTION_REPORT", obstacle=False, available=True)
        for _ in range(80):
            if all(t.finished for t in self.e.trains.values()):
                break
            needs_plan = any(
                not t.finished and (tid not in self.e.approved or tid in self.e.controller_hold)
                for tid, t in self.e.trains.items()
            )
            if needs_plan or any(t.severity in ("WARNING", "CRITICAL") for t in self.e.threats.active()):
                self.op_recommend()
                self.stats["ops"] += 1
                if self.e.latest["approvable"]:
                    self.op_approve()
                    self.stats["ops"] += 1
            self.op_tick(120)
            self.stats["ops"] += 1
            self.check_plans()
            self.check_cab()
        self.stats["completed" if all(t.finished for t in self.e.trains.values()) else "not_completed"] += 1
        check(self.e.audit.verify_chain(), "REPLAY", "audit chain broken")


def _first_change(a: list[float], b: list[float]) -> int | None:
    return next((i for i, (x, y) in enumerate(zip(a, b, strict=False)) if x != y), None)


def _future(plan: TrainPlan, now: float) -> TrainPlan:
    plan.traversals = [t for t in plan.traversals if t.exit >= now]
    return plan


def _check_pairwise(engine: RailGuardEngine, plans: dict[str, TrainPlan], invariant: str, what: str) -> None:
    ids = sorted(plans)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            for x in plans[a].traversals:
                for y in plans[b].traversals:
                    if x.section_id != y.section_id:
                        continue
                    section = engine.net.sections[x.section_id]
                    same = x.from_node == y.from_node
                    if section.tracks == 1:
                        gap = max(y.enter - x.exit, x.enter - y.exit)
                    elif same:
                        overtake = (x.enter - y.enter) * (x.exit - y.exit) < -TOL
                        gap = -1.0 if overtake else min(abs(x.enter - y.enter), abs(x.exit - y.exit))
                    else:
                        continue
                    check(
                        gap >= engine.headway - TOL,
                        invariant,
                        f"{what}: {a}/{b} {gap:.2f} min apart on {x.section_id} (headway {engine.headway})",
                    )


# ==== national twin ==========================================================================================
_NATIONAL: Any = None


def _national_twin() -> Any:
    global _NATIONAL
    if _NATIONAL is None:
        from india_rail.railguard.eta import load_default
        from india_rail.railguard.national import NationalTwin

        _NATIONAL = NationalTwin()
        _NATIONAL.eta = load_default()  # as deployed: live-reported delays follow the learned forecast
    return _NATIONAL


def national_fingerprint(tw: Any) -> tuple:
    plans = tuple(sorted((k, tuple(p.exit), tuple(p.sections)) for k, p in tw.plans.items()))
    sections = tuple(
        sorted(
            (sid, s.condition, s.temp_restriction_kmph, s.weather_alert, s.obstacle, s.available)
            for sid, s in tw.section_overrides.items()
        )
    )
    evidence = tuple(sorted((k, r.observed_t) for k, r in tw.evidence.records.items()))
    flags = tuple(sorted((k, f["type"], f["until"]) for k, fs in tw.flags.items() for f in fs))
    return tw.now, plans, sections, tuple(sorted(tw.pending)), evidence, flags


class NationalEpisode:
    def __init__(self, index: int, seed: int, verbose: bool = False):
        self.id = f"national:{index}"
        self.rng = _rng(seed, "national", index)
        self.verbose = verbose
        self.trace: list[str] = []
        self.stats: Counter = Counter()
        self.tw = _national_twin()
        self.fingerprint: tuple | None = None

    def log(self, text: str) -> None:
        self.stats["ops"] += 1  # every national operation logs exactly once
        self.trace.append(f"now={self.tw.now:.1f} {text}")
        if self.verbose:
            print(self.trace[-1])

    def pick_run(self) -> str | None:
        tw, rng = self.tw, self.rng
        keys = self._keys()
        for _ in range(50):
            key = rng.choice(keys)
            run = tw.runs[key]
            plan = tw.plan_of(key)
            if plan.exit[-1] > tw.now + 30 and run.s_enter[0] < tw.now + 90 and len(run.sections) >= 3:
                return key
        return None

    def _keys(self) -> list[str]:
        cache = getattr(self.tw, "_sim_keys", None)
        if cache is None:
            cache = self.tw._sim_keys = sorted(self.tw.runs)
        return cache

    def station_ahead(self, key: str) -> str | None:
        plan = self.tw.plan_of(key)
        idx = self.tw.position(key)["index"]
        options = [plan.frm[i] for i in range(idx, len(plan.sections)) if plan.enter[i] >= self.tw.now]
        return self.rng.choice(options[:12]) if options else None

    def section_event(self, key: str | None) -> None:
        tw, rng = self.tw, self.rng
        if key:
            plan = tw.plan_of(key)
            idx = tw.position(key)["index"]
            pool = plan.sections[idx : idx + 15] or plan.sections
        else:
            pool = sorted(tw.net.sections)
        sid = rng.choice(pool)
        changes = rng.choice(
            (
                {"condition": round(rng.uniform(0.2, 0.9), 2)},
                {"temp_restriction_kmph": rng.choice((30.0, 45.0, 60.0))},
                {"weather_alert": rng.choice(("HEAT", "FOG", "FLOOD_WATCH"))},
                {"obstacle": True},
                {"available": False},
                {"obstacle": False, "available": True},
            )
        )
        tw.update_section(sid, "TRACKSENSE_FEED", **changes)
        self.log(f"section {sid} {changes}")

    def disrupt(self, key: str) -> bool:
        station = self.station_ahead(key)
        if station is None:
            return False
        delay = round(min(self.rng.expovariate(1 / 25) + 1, 240), 1)
        # Half come from a controller, half from the live feed (projected by the real-running forecast, if loaded).
        observed = round(delay + self.rng.uniform(0, 5), 1) if self.rng.random() < 0.5 else None
        try:
            self.tw.disrupt(key, station, delay, actor="feed:SIM" if observed else "controller",
                            observed_arrival_delay=observed)  # fmt: skip
        except ValueError as exc:
            self.log(f"disrupt {key} refused: {exc}")
            return False
        self.log(f"disrupt {key} at {station} +{delay} min" + (f" (feed, arrived {observed} late)" if observed else ""))
        return True

    def feed(self, key: str, valid: bool = True) -> None:
        tw = self.tw
        pos = tw.position(key)
        plan = tw.plan_of(key)
        if valid:
            sid = pos["section_id"] or plan.sections[min(pos["index"], len(plan.sections) - 1)]
            offset = pos.get("offset_km", 0.0)
        else:
            sid, offset = self.rng.choice(sorted(tw.net.sections)), 0.0
        before = dict(tw.evidence.records)
        result = tw.ingest_position(key, sid, offset)
        self.log(f"feed {key} {sid} valid={valid} -> {result}")
        if not result["accepted"]:
            check(tw.evidence.records == before, "INPUT_REJECTION", "rejected observation changed evidence")
        elif not valid:
            check(sid in plan.sections, "INPUT_REJECTION", "off-plan observation accepted")

    def recommend(self, key: str) -> dict[str, Any] | None:
        tw = self.tw
        tw.set_weights(self.rng.choice(sorted(PRESETS)))
        try:
            rec = tw.recommend(key)
        except ValueError as exc:
            self.log(f"recommend refused: {exc}")
            return None
        self.fingerprint = national_fingerprint(tw)
        self.stats[f"recommend_{rec['state']}"] += 1
        ranking = rec["ranking"]
        self.log(f"recommend {key} -> {rec['state']} ({len(ranking['candidates'])} candidates)")
        involved_stale = tw.position_state(key) == STALE
        if involved_stale:
            check(not rec["approvable"], "EVIDENCE_GATE", f"approvable with stale position of {key}")
        if ranking["state"] == "RANKED":
            _check_scores(ranking["candidates"], tw.weights)
            for cand in ranking["candidates"]:
                full = tw._cache[(key, cand["candidate_id"])]
                yields = {k: v[0] for k, v in full["yields"].items()}
                self._check_plan(key, full["plan"], cand["candidate_id"], overrides=yields)
                pending = frozenset(tw.pending) - {key}
                for okey, oplan in yields.items():
                    joint = {key: full["plan"], **{k: v for k, v in yields.items() if k != okey}}
                    current = tw.plan_of(okey)
                    check(oplan.sections == current.sections, "RANKING", f"yield re-routes {okey}")
                    changed = _first_change(oplan.enter, current.enter)
                    check(changed is not None, "RANKING", f"yield of {okey} changes nothing")
                    self._check_plan(okey, oplan, cand["candidate_id"], joint, pending, route=False, start=changed)
        if self.rng.random() < 0.02:
            replay = tw.replay(rec["snapshot_id"])
            self.stats["replays"] += 1
            check(replay["integrity_ok"] and replay["replay_matches"], "REPLAY", f"replay mismatch {replay}")
        return rec

    def _check_plan(
        self,
        key: str,
        plan: Any,
        label: str,
        overrides: dict[str, Any] | None = None,
        ignore: frozenset[str] = frozenset(),
        route: bool = True,
        start: int | None = None,
    ) -> None:
        tw = self.tw
        run = tw.runs[key]
        idx = tw.position(key)["index"] if start is None else start
        for i in range(len(plan.sections)):
            check(plan.exit[i] >= plan.enter[i] - 1e-6, "RANKING", f"{label} {key} exit before entry at {i}")
            if i:
                check(plan.enter[i] >= plan.exit[i - 1] - 1e-6, "RANKING", f"{label} {key} overlaps itself at {i}")
            if plan.s_enter[i] is not None:
                check(plan.enter[i] >= plan.s_enter[i] - 1e-6, "RANKING", f"{label} {key} runs early at {i}")
        for i in range(idx, len(plan.sections) if route else idx):
            if plan.enter[i] < tw.now:
                continue  # already on it: the run must clear the section it occupies
            sid = plan.sections[i]
            sec = tw.section(sid)
            check(sec.available and not sec.obstacle, "RANKING", f"{label} routes {key} over blocked {sid}")
            check(run.axle_load_t <= sec.axle_limit_t, "RANKING", f"{label} {key} axle limit on {sid}")
        bad = [c for c in tw.conflicts(key, plan, idx, ignore, overrides) if c["is_conflict"]]
        check(not bad, "RANKING", f"{label} {key} conflicts: {bad[:2]}")

    def approve(self, rec: dict[str, Any], mutate: bool) -> None:
        tw, rng = self.tw, self.rng
        key = rec["run"]
        candidates = rec["ranking"]["candidates"] or [{"candidate_id": "N1"}]
        cid = candidates[0]["candidate_id"] if rng.random() < 0.7 else rng.choice(candidates)["candidate_id"]
        if mutate:
            what = rng.choice(("section", "tick", "disrupt", "feed"))
            if what == "section":
                self.section_event(key)
            elif what == "tick":
                minutes = rng.choice((1, 5))
                tw.tick(minutes)
                self.log(f"tick {minutes} min (between ranking and approval)")
            elif what == "disrupt":
                other = self.pick_run()
                if other:
                    self.disrupt(other)
            else:
                self.feed(key)
        same_state = self.fingerprint == national_fingerprint(tw)
        full = tw._cache.get((key, cid))
        blocked = []
        if full is not None:
            plan = full["plan"]
            for i in range(tw.position(key)["index"], len(plan.sections)):
                sec = tw.section(plan.sections[i])
                if plan.enter[i] >= tw.now and (sec.obstacle or not sec.available):
                    blocked.append(sec.id)
        stale = tw.position_state(key) == STALE
        before = {k: tw.plan_of(k) for k in (full["yields"] if full else ())}
        try:
            tw.approve(rec["snapshot_id"], cid, "controller-1")
        except (ValueError, KeyError) as exc:
            self.stats["approve_refused"] += 1
            self.log(f"approve {cid} refused: {exc}")
            return
        self.stats["approve_ok"] += 1
        self.log(f"approve {cid} OK")
        check(rec["approvable"], "APPROVAL_GATE", "approved a non-approvable recommendation")
        check(same_state, "APPROVAL_GATE", "approved a recommendation made for a different twin state")
        check(not blocked, "APPROVAL_GATE", f"approved a plan over blocked {blocked}")
        check(not stale, "APPROVAL_GATE", "approved with a stale live position")
        pending = frozenset(tw.pending)
        # The runs this approval planned are conflict-free over the planning horizon from where it changed them
        # (earlier conflicts of a re-timed run pre-date this decision and must be on the threat list instead).
        starts = {key: tw.position(key)["index"]}
        for k, old in before.items():
            new = tw.plan_of(k)
            starts[k] = _first_change(new.enter, old.enter)
            starts[k] = len(new.enter) if starts[k] is None else starts[k]
        for k, first in starts.items():
            bad = [c for c in tw.conflicts(k, tw.plan_of(k), first, ignore=pending) if c["is_conflict"]]
            check(not bad, "SAFE_SEPARATION", f"approved {k} conflicts after approval: {bad[:2]}")
        self.check_visible()

    def check_visible(self) -> None:
        """Rolling horizon: a conflict that comes into view later must be on the controller's threat list."""

        tw = self.tw
        shown = {
            (frozenset(t.train_ids), t.section_id)
            for t in tw.threats.active()
            if t.type == "CONVERGING_PATH" and t.severity == "WARNING"
        }
        for k, plan in tw.plans.items():
            for c in tw.conflicts(k, plan, tw.position(k)["index"]):
                if c["is_conflict"]:
                    pair = (frozenset((k, c["other"])), c["section_id"])
                    check(pair in shown, "SAFE_SEPARATION", f"conflict {k}/{c['other']} on {c['section_id']} not shown")

    def check_index(self) -> None:
        tw = self.tw
        expected = sorted((sid, k, i) for k, p in tw.plans.items() for i, sid in enumerate(p.sections))
        actual = sorted((sid, k, i) for sid, entries in tw.changed_index.items() for k, i in entries)
        check(expected == actual, "NO_CRASH", "changed-run index out of sync with plans")

    def check_cab(self, key: str) -> None:
        cab = self.tw.cab(key)
        if cab["status"] not in ("NORMAL", "CAUTION"):
            check(cab["advisory_speed_band_kmph"] is None, "CAB_ADVISORY", f"band shown in {cab['status']}")
        if cab["position_evidence"] == STALE:
            check(cab["status"] == "DATA UNAVAILABLE", "CAB_ADVISORY", "stale position not shown as unavailable")

    def run(self) -> None:
        tw, rng = self.tw, self.rng
        with tw.lock:
            tw.reset()
            tw.now = round(rng.uniform(300, 2400), 1)
            for _ in range(rng.randint(0, 2)):  # earlier decisions already in force
                other = self.pick_run()
                if other and self.disrupt(other):
                    rec = self.recommend(other)
                    if rec and rec["approvable"]:
                        self.approve(rec, mutate=False)
            key = self.pick_run()
            if key is None:
                self.stats["no_run"] += 1
                return
            for _ in range(rng.choice((0, 0, 1, 2))):
                self.section_event(key if rng.random() < 0.8 else None)
            if rng.random() < 0.35:
                self.feed(key)
                if rng.random() < 0.3:
                    tw.tick(rng.choice((2, 4, 10)))  # 4+ min without a fix makes the feed stale
                    self.log("tick (feed ageing)")
            if rng.random() < 0.1:
                self.feed(key, valid=False)
            for _round in range(rng.choice((1, 1, 2, 3))):
                if not self.disrupt(key):
                    break
                rec = self.recommend(key)
                self.check_index()
                self.check_cab(key)
                if rec is not None:
                    self.approve(rec, mutate=rng.random() < 0.25)
                self.check_index()
                self.check_cab(key)
                minutes = rng.choice((1, 5, 15, 30))
                tw.tick(minutes)
                self.log(f"tick {minutes} min")
                self.check_visible()
            check(tw.audit.verify_chain(), "REPLAY", "audit chain broken")


# ==== runner =================================================================================================
class _Overrun(BaseException):
    """Raised by the watchdog; a BaseException so the code under test cannot swallow it."""


def _overrun(_signum: int, _frame: Any) -> None:
    raise _Overrun()


def run_episode(twin: str, index: int, seed: int, verbose: bool = False) -> tuple[Counter, dict[str, Any] | None]:
    episode = (DemoEpisode if twin == "demo" else NationalEpisode)(index, seed, verbose)
    watchdog = hasattr(signal, "SIGALRM")
    if watchdog:
        signal.signal(signal.SIGALRM, _overrun)
        signal.alarm(EPISODE_LIMIT_S)
    try:
        episode.run()
        return episode.stats, None
    except _Overrun:
        return episode.stats, {
            "episode": episode.id,
            "invariant": "LIVENESS",
            "detail": f"episode exceeded {EPISODE_LIMIT_S} s",
            "trace": episode.trace[-25:],
        }
    except Violation as v:
        return episode.stats, {
            "episode": episode.id,
            "invariant": v.invariant,
            "detail": v.detail,
            "trace": episode.trace[-25:],
        }
    except Exception as exc:  # every crash is a finding
        return episode.stats, {
            "episode": episode.id,
            "invariant": "NO_CRASH",
            "detail": f"{type(exc).__name__}: {exc}",
            "trace": episode.trace[-25:] + traceback.format_exc().splitlines()[-6:],
        }
    finally:
        if watchdog:
            signal.alarm(0)


def run_chunk(args: tuple[str, int, int, int]) -> dict[str, Any]:
    twin, start, stop, seed = args
    stats: Counter = Counter()
    failures: list[dict[str, Any]] = []
    by_invariant: Counter = Counter()
    began = time.perf_counter()
    for index in range(start, stop):
        episode_stats, failure = run_episode(twin, index, seed)
        stats.update(episode_stats)
        if failure:
            by_invariant[failure["invariant"]] += 1
            if len(failures) < MAX_FAILURES_KEPT:
                failures.append(failure)
    return {
        "twin": twin,
        "episodes": stop - start,
        "seconds": time.perf_counter() - began,
        "stats": stats,
        "violations": by_invariant,
        "failures": failures,
    }


def simulate(demo: int, national: int, workers: int, seed: int, chunk: int, out: Path | None) -> dict[str, Any]:
    small = max(chunk // 20, 50)  # national episodes are heavier: smaller chunks keep the workers balanced
    jobs = [("national", s, min(s + small, national), seed) for s in range(0, national, small)]
    jobs += [("demo", s, min(s + chunk, demo), seed) for s in range(0, demo, chunk)]
    totals = {
        t: {"episodes": 0, "cpu_seconds": 0.0, "stats": Counter(), "violations": Counter(), "failures": []}
        for t in ("demo", "national")
    }
    began = time.perf_counter()
    done = 0
    _code_checksum()
    with mp.get_context("fork").Pool(workers, initializer=_init_worker, initargs=(national > 0,)) as pool:
        for result in pool.imap_unordered(run_chunk, jobs):
            total = totals[result["twin"]]
            total["episodes"] += result["episodes"]
            total["cpu_seconds"] += result["seconds"]
            total["stats"].update(result["stats"])
            total["violations"].update(result["violations"])
            total["failures"] += result["failures"][: MAX_FAILURES_KEPT - len(total["failures"])]
            done += result["episodes"]
            if out is not None:
                _write(out, totals, began, seed, workers, demo + national, done)
    return _write(out, totals, began, seed, workers, demo + national, done)


@lru_cache(maxsize=1)  # computed once at launch: later edits to the files do not relabel a running test
def _code_checksum() -> str:
    """SHA-256 over the twin's source files, so a result always names the exact code it tested."""

    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode() + path.read_bytes())
    return digest.hexdigest()


@lru_cache(maxsize=1)
def _data_identity() -> dict[str, Any]:
    """Which timetable the national twin ran on and which forecast model was attached (by SHA-256)."""

    from india_rail.railguard.national import timetable_source

    try:
        name, path = timetable_source()
    except RuntimeError as exc:
        return {"timetable": f"unavailable: {exc}"}
    out: dict[str, Any] = {"timetable": name, "timetable_db": path.name}
    model = Path(__file__).resolve().parents[2] / "models" / "eta_model.joblib"
    if model.exists():
        out["eta_model_sha256"] = hashlib.sha256(model.read_bytes()).hexdigest()
    return out


def _init_worker(load_national: bool) -> None:
    # One thread per worker: OpenMP inference threads in every worker would spin against each other.
    os.environ["OMP_NUM_THREADS"] = "1"
    if load_national:
        _national_twin()
    from threadpoolctl import threadpool_limits

    threadpool_limits(1)  # also for libraries already loaded above


def _write(out, totals, began, seed, workers, target, done) -> dict[str, Any]:
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "what": "Randomised software-in-the-loop simulation of the RailGuard twins with invariant checks",
        "seed": seed,
        "workers": workers,
        "platform": f"{platform.python_implementation()} {platform.python_version()} on {platform.machine()}",
        "code_checksum": _code_checksum(),
        "data": _data_identity(),
        "target_episodes": target,
        "completed_episodes": done,
        "operations_checked": sum(t["stats"].get("ops", 0) for t in totals.values()),
        "simulated_5s_steps": sum(t["stats"].get("sim_steps_5s", 0) for t in totals.values()),
        "wall_seconds": round(time.perf_counter() - began, 1),
        "twins": {
            twin: {
                "episodes": t["episodes"],
                "violations_total": sum(t["violations"].values()),
                "violations_by_invariant": dict(t["violations"]),
                "cpu_ms_per_episode": round(1000 * t["cpu_seconds"] / max(t["episodes"], 1), 3),
                "stats": dict(sorted(t["stats"].items())),
                "first_failures": t["failures"],
            }
            for twin, t in totals.items()
        },
    }
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(report, indent=2, default=str))
        os.replace(tmp, out)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo", type=int, default=2000)
    parser.add_argument("--national", type=int, default=200)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--chunk", type=int, default=2000)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--replay", help="re-run one episode verbosely, e.g. demo:1234")
    args = parser.parse_args(argv)
    if args.replay:
        twin, index = args.replay.split(":")
        _stats, failure = run_episode(twin, int(index), args.seed, verbose=True)
        print(json.dumps(failure, indent=2) if failure else "no violation")
        return 1 if failure else 0
    report = simulate(args.demo, args.national, args.workers, args.seed, args.chunk, args.out)
    for twin, t in report["twins"].items():
        ops = t["stats"].get("ops", 0)
        print(f"{twin}: {t['episodes']} episodes, {ops} operations, {t['violations_total']} violations")
        for name, count in t["violations_by_invariant"].items():
            print(f"  {name}: {count}")
    return 0 if all(t["violations_total"] == 0 for t in report["twins"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
