"""An independent check of a plan's separation, written apart from the planner's own conflict search.

The planner (national.NationalTwin.conflicts) looks for conflicts through time-windowed binary searches of
sorted occupation indexes, keeps one entry per pair, and stops at its planning horizon. This module checks the
same rule by brute force: it collects every occupation of every piece of track the checked runs use - each
timetabled run straight from the occupancy arrays, each changed run straight from its plan - and compares every
pair. It shares no search code with the planner, so a fault in the windows, the indexes or the bookkeeping of
changed runs cannot hide a conflict from both.

The rule (the operating rule the twin is built on, stated here on its own):
* single line: one occupation must end at least the required separation before the other begins;
* two or more tracks: trains in opposite directions use different tracks; in the same direction the later
  train may not overtake on plain line, and both its entry and its exit must be at least the required
  separation after the earlier train's;
* the required separation is the piece's signalled headway (the Indian Railways register where loaded, else the
  twin's default), or the separation the two trains have in the published timetable if that is smaller - except
  that a pair the timetable has crossing or overtaking inside the piece keeps that allowance only while neither
  train has moved against the other; once one has, they must be a full headway apart on the piece.

A conflict starts when the second of the two trains enters the piece. Conflicts starting more than HORIZON_MIN
ahead are counted separately: the planner resolves them when they come into view, so they are information, not a
fault of the plan. (An occupation can be very long - a tourist train timetabled 33 hours between two stations
because it stands overnight - so a conflict can start far beyond the horizon although the first train entered
inside it.)
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from india_rail.railguard.national import HORIZON_MIN, Plan

EPS = 1e-6


def separation(tracks: int, same_direction: bool, a: tuple[float, float], b: tuple[float, float]) -> float | None:
    """Minutes by which two occupations (entry, exit) of one piece are apart; None if they cannot meet."""

    if tracks == 1:
        return max(b[0] - a[1], a[0] - b[1])
    if not same_direction:
        return None
    first, second = sorted((a, b))
    if second[1] < first[1]:
        return -1.0  # the later train would leave first: an overtake on plain line
    return min(second[0] - first[0], second[1] - first[1])


def _occupations(twin: Any, key: str, plan: Plan, from_index: int = 0):
    """(piece, entry station, (enter, exit), (timetabled enter, exit) or None, section index) of a plan."""

    for i in range(from_index, len(plan.sections)):
        e, x, se, sx = plan.enter[i], plan.exit[i], plan.s_enter[i], plan.s_exit[i]
        for piece, f0, f1, frm in twin.parts(plan.sections[i], plan.frm[i]):
            occ = (e + f0 * (x - e), e + f1 * (x - e))
            timetabled = None if se is None or sx is None else (se + f0 * (sx - se), se + f1 * (sx - se))
            yield piece, frm, occ, timetabled, i


def check(twin: Any, changed: dict[str, tuple[Plan, int]]) -> dict[str, Any]:
    """Every pair of occupations involving the runs in `changed` ({run: (plan, first index to check)}), against
    every other run (timetabled runs as timetabled, changed runs as currently planned, `changed` as given)."""

    now, limit = twin.now, twin.now + HORIZON_MIN
    mine: dict[str, list[tuple]] = defaultdict(list)
    for key, (plan, start) in changed.items():
        for piece, frm, occ, timetabled, i in _occupations(twin, key, plan, start):
            if occ[1] >= now:
                mine[piece].append((key, i, frm, occ, timetabled))
    others: dict[str, list[tuple]] = defaultdict(list)
    for key, plan in twin.plans.items():  # changed runs, as currently planned
        if key not in changed:
            for piece, frm, occ, timetabled, i in _occupations(twin, key, plan):
                if piece in mine:
                    others[piece].append((key, i, frm, occ, timetabled))
    for piece in mine:  # timetabled runs, every occupation of the piece (no time window)
        occ = twin.data.occupancy.get(piece)
        if occ is None:
            continue
        for n, key in enumerate(occ.keys):
            if key in changed or key in twin.plans:
                continue
            others[piece].append((key, occ.idx[n], occ.frm[n], (occ.enter[n], occ.exit[n]),
                                  (occ.enter[n], occ.exit[n])))  # fmt: skip
    conflicts, beyond, pairs = [], 0, 0
    for piece, entries in mine.items():
        tracks = twin.section(piece).tracks
        headway = twin.data.headway.get(piece, twin.headway)
        candidates = entries + others.get(piece, [])
        for a_n, a in enumerate(entries):
            for b_n, b in enumerate(candidates):
                if b[0] == a[0] or (b_n < len(entries) and b_n <= a_n):
                    continue  # the same run, or a pair of checked runs already compared
                pairs += 1
                same = a[2] == b[2]
                apart = separation(tracks, same, a[3], b[3])
                if apart is None:
                    continue
                planned = separation(tracks, same, a[4], b[4]) if a[4] and b[4] else None
                if planned is None or planned >= headway:
                    required = headway
                elif planned < 0 and abs((a[3][0] - a[4][0]) - (b[3][0] - b[4][0])) > EPS:
                    required = headway  # the timetabled crossing or overtake inside the piece has moved
                else:
                    required = planned
                if apart >= required - EPS:
                    continue
                if max(a[3][0], b[3][0]) > limit:  # starts beyond the planning horizon
                    beyond += 1
                    continue
                conflicts.append({"piece": piece, "run": a[0], "index": a[1], "other": b[0], "other_index": b[1],
                                  "apart_min": round(apart, 2), "required_min": round(required, 2)})  # fmt: skip
    return {"conflicts": conflicts, "beyond_horizon": beyond, "pairs_compared": pairs}


def blocked_ahead(twin: Any, key: str, plan: Plan) -> list[str]:
    """Closed or obstructed pieces of track still ahead of the train on its plan (including the rest of the
    section it is on)."""

    out, now = [], twin.now
    for i in range(len(plan.sections)):
        e, x = plan.enter[i], plan.exit[i]
        if x <= now:
            continue
        done = 0.0 if e >= now else (now - e) / max(x - e, EPS)
        for piece, _f0, f1, _frm in twin.parts(plan.sections[i], plan.frm[i]):
            sec = twin.section(piece)
            if f1 > done and (not sec.available or sec.obstacle):
                out.append(piece)
    return out
