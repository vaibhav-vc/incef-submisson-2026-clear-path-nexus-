"""Expected times for passengers, freight customers and station staff: what to publish, and when to change it.

The twin's projection is the single source: for a train the live feed reports late it is the forecast learned
from real running, for a train a controller has re-planned it is the approved plan, for a train with no report it
is the timetable. Publishing it raw would irritate the people who read it: a time that wobbles by a minute at
every refresh, a train shown leaving before its timetabled time, an "improvement" that is withdrawn a minute
later, a confident time for a train nobody has heard from in half an hour. So what is published follows rules:

* bad news promptly: a later time is published as soon as it is forecast (by at least PUBLISH_STEP_MIN);
* good news once sure: an earlier time only when it has been forecast for EARLIER_HOLD_MIN, so a passenger who
  stepped away is not caught out by a promise that is withdrawn a minute later;
* no wobble: a change smaller than PUBLISH_STEP_MIN does not move a published time;
* never early: a departure is never shown before its timetabled time (Indian Railways trains do not leave early)
  nor before the arrival published for the same stop;
* honest when unsure: a train whose last report is older than STALE_REPORT_MIN carries when and where it was
  last reported, with its times marked as not confirmed; one with no live report (and no re-plan) is shown as
  SCHEDULED, the timetable, never as "on time";
  a stop whose expected time has passed with no arrival reported shows as due, not as a time in the past;
* a range when known: where the forecaster gives one, the likely range (P10-P90) is shown with the time, and it
  always contains the published time;
* a diverted train that no longer calls at a station is shown there as not calling, not dropped silently.

Published times are advice for information, not an official announcement (that is NTES's); nothing here changes a
plan or reaches a train.
"""

from __future__ import annotations

import threading
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from india_rail.network import clock
from india_rail.railguard.evidence import FRESH, STALE

PUBLISH_STEP_MIN = 2.0
EARLIER_HOLD_MIN = 3.0
STALE_REPORT_MIN = 15.0
BOARD_PAST_MIN = 10.0  # a call whose expected time is this far past drops off the board
BOARD_LOOKBACK_MIN = 720.0  # a train scheduled this long ago may still be to come
LATE_MIN = 2.0  # shown as late from this many minutes; less is "on time"
NOTE = "Expected times for information, published under rules that avoid needless changes; official " \
       "announcements are NTES's."  # fmt: skip


@dataclass
class _Shown:
    minute: float
    earlier: float | None = None  # an earlier time forecast but not yet held long enough
    since: float = 0.0  # twin minute the earlier time was first forecast


class Publisher:
    """What has been published for every (run, stop, arrival|departure) of one twin."""

    def __init__(self, twin: Any):
        self.twin = twin
        self.shown: dict[tuple[str, int, str], _Shown] = {}
        self.lock = threading.RLock()
        self._epoch = twin.epoch
        self._calls: dict[str, list[tuple[float, str, int, str]]] | None = None  # station -> (time, run, q, kind)
        self._cache: dict[tuple[str, bool], tuple[tuple, dict[str, Any]]] = {}

    # ---- the publishing rule ----------------------------------------------------------------------------------
    def _publish(self, key: tuple[str, int, str], forecast: float, floor: float | None) -> float:
        if floor is not None:
            forecast = max(forecast, floor)
        now = self.twin.now
        shown = self.shown.get(key)
        if shown is None:
            self.shown[key] = _Shown(forecast)
            return forecast
        if forecast >= shown.minute + PUBLISH_STEP_MIN:  # later: at once
            shown.minute, shown.earlier = forecast, None
        elif forecast <= shown.minute - PUBLISH_STEP_MIN:  # earlier: once it has held
            if shown.earlier is None or abs(forecast - shown.earlier) >= PUBLISH_STEP_MIN:
                shown.earlier, shown.since = forecast, now
            elif now - shown.since >= EARLIER_HOLD_MIN:
                shown.minute, shown.earlier = forecast, None
        else:
            shown.earlier = None
        if floor is not None and shown.minute < floor:  # a floor that rose (the arrival moved later)
            shown.minute = floor
        return shown.minute

    # ---- one train ----------------------------------------------------------------------------------------------
    def _evidence(self, run: str) -> dict[str, Any]:
        twin = self.twin
        record = twin.evidence.records.get(f"position:{run}")
        if record is None:
            return {"basis": "TIMETABLE", "text": "no live report: timetable time"}
        age_min = (twin.now * 60 - record.observed_t) / 60
        state = twin.evidence.state_of(f"position:{run}", int(twin.now * 60))
        observed = twin.observed.get(run)
        where = observed[1] if observed else None
        if age_min > STALE_REPORT_MIN or state == STALE:
            return {"basis": "LAST_REPORT", "age_min": round(age_min), "section": where,
                    "text": f"last reported {round(age_min)} min ago" + (f" on {where}" if where else "")
                    + ": times not confirmed"}  # fmt: skip
        return {"basis": "LIVE", "age_min": round(age_min, 1), "fresh": state == FRESH, "text": "live"}

    def _band(self, run: str) -> dict[int, tuple[float, float]]:
        """Likely range of the arrival delay at each later stop (stop index -> (P10, P90)), when the forecaster
        is attached and the train is reported live."""

        twin = self.twin
        if twin.eta is None:
            return {}
        try:
            stops = twin.eta.forecast(twin, run)
        except (KeyError, ValueError, IndexError):
            return {}
        first = len(twin.plan_of(run).sections) + 1 - len(stops)
        return {first + k: (s["delay_p10_min"], s["delay_p90_min"]) for k, s in enumerate(stops)}

    def _done(self, run: str) -> tuple[int, int]:
        """(last stop arrived at, last stop departed from), by the twin's position of the run (-1: none)."""

        pos = self.twin.position(run)
        i, state = pos["index"], pos["state"]
        if state == "NOT_STARTED":
            return 0, -1
        if state == "RUNNING":  # on section i: stops 0..i are behind it
            return i, i
        if state == "AT_STATION":  # at stop i, not yet left
            return i, i - 1
        return i + 1, i + 1  # ARRIVED at the end of section i

    def _fresh(self) -> None:
        if self.twin.epoch != self._epoch:  # the twin was reset: nothing published before stands
            self.shown.clear()
            self._cache.clear()
            self._epoch = self.twin.epoch

    def train(self, run: str, band: bool = True) -> dict[str, Any]:
        """Every stop of one run: scheduled and expected arrival and departure, as published."""

        twin = self.twin
        with twin.lock, self.lock:
            if run not in twin.runs:
                raise KeyError(run)
            self._fresh()
            stamp = (twin.version, twin.now)
            hit = self._cache.get((run, band))
            if hit is not None and hit[0] == stamp:  # nothing has changed since the last look
                return hit[1]
            out = self._train(run, band)
            self._cache[(run, band)] = (stamp, out)
            return out

    def expected(self, run: str) -> dict[str, Any]:
        """`train` as published: without the working minutes."""

        info = self.train(run)
        stops = [{k: v for k, v in stop.items() if not k.startswith("_")} for stop in info["stops"]]
        return {**info, "stops": stops}

    def _train(self, run: str, with_band: bool) -> dict[str, Any]:
        twin = self.twin
        r, plan = twin.runs[run], twin.plan_of(run)
        arrived, departed = self._done(run)
        evidence = self._evidence(run)
        band = self._band(run) if with_band and evidence["basis"] == "LIVE" else {}
        known = evidence["basis"] == "LIVE" or run in twin.plans  # reported live, or re-planned by the twin
        stops = []
        for q in range(len(plan.sections) + 1):  # stop q: arrival from section q-1, departure to section q
            row: dict[str, Any] = {"station": plan.frm[q] if q < len(plan.sections) else plan.to[q - 1]}
            arr = None
            if q > 0:
                row.update(self._times(run, q, "arr", plan.exit[q - 1], plan.s_exit[q - 1], None, q <= arrived, known))
                arr = row.get("_arr_min")
                if arr is not None and q in band and plan.s_exit[q - 1] is not None:
                    lo, hi = (plan.s_exit[q - 1] + d for d in band[q])
                    row["likely_arrival"] = [clock(min(lo, arr)), clock(max(hi, arr))]
            if q < len(plan.sections):
                floor = plan.s_enter[q] if arr is None else max(plan.s_enter[q] or arr, arr)
                row.update(self._times(run, q, "dep", plan.enter[q], plan.s_enter[q], floor, q <= departed, known))
            stops.append(row)
        return {"run": run, "train": f"{r.number} {r.name}", "now": clock(twin.now), "evidence": evidence,
                "plan": plan.note or "TIMETABLE", "stops": stops, "note": NOTE}  # fmt: skip

    def _times(self, run: str, q: int, kind: str, planned: float, scheduled: float | None, floor: float | None,
               done: bool, known: bool) -> dict[str, Any]:  # fmt: skip
        out: dict[str, Any] = {f"scheduled_{kind}": clock(scheduled) if scheduled is not None else None}
        if done:
            out[f"{kind}_status"] = "ARRIVED" if kind == "arr" else "DEPARTED"
            self.shown.pop((run, q, kind), None)
            return out
        shown = self._publish((run, q, kind), planned, floor)
        out[f"expected_{kind}"] = clock(shown)
        late = shown - scheduled if scheduled is not None else 0.0
        if shown <= self.twin.now:
            status = "DUE"  # the time has come and no arrival or departure is reported yet
        elif late >= LATE_MIN:
            status = f"LATE {round(late)} MIN"
        elif scheduled is None:
            status = "NOT IN TIMETABLE"
        else:  # "on time" is a claim only a live report or a re-plan can make; otherwise it is the timetable
            status = "ON TIME" if known else "SCHEDULED"
        out[f"{kind}_status"] = status
        out[f"_{kind}_min"] = shown
        return out

    # ---- a station ----------------------------------------------------------------------------------------------
    def _index(self) -> dict[str, list[tuple[float, str, int, str]]]:
        if self._calls is None:
            calls: dict[str, list[tuple[float, str, int, str]]] = defaultdict(list)
            for key, r in self.twin.runs.items():
                for i in range(len(r.sections)):
                    calls[r.frm[i]].append((r.s_enter[i], key, i, "dep"))
                    calls[r.to[i]].append((r.s_exit[i], key, i + 1, "arr"))
            for v in calls.values():
                v.sort()
            self._calls = dict(calls)
        return self._calls

    @staticmethod
    def _stop_now(info: dict[str, Any], code: str, scheduled: str) -> dict[str, Any] | None:
        """The run's current stop at `code` that carries the timetabled time `scheduled` (a re-planned run keeps
        its timetabled times where it still follows the timetable); None if it no longer calls there."""

        for stop in info["stops"]:
            if stop["station"] == code and scheduled in (stop.get("scheduled_arr"), stop.get("scheduled_dep")):
                return stop
        return None

    def board(self, code: str, window_min: float = 180.0, limit: int = 40) -> dict[str, Any]:
        """Trains due at a station from now to `window_min` ahead (and late ones still to come), soonest first."""

        with self.twin.lock, self.lock:
            return self._board(code.upper(), window_min, limit)

    def _board(self, code: str, window_min: float, limit: int) -> dict[str, Any]:
        twin = self.twin
        calls = self._index().get(code)
        if calls is None:
            raise KeyError(code)
        now = twin.now
        wanted: dict[tuple[str, int], float] = {}
        for sched, run, q, _kind in calls[bisect_left(calls, (now - BOARD_LOOKBACK_MIN,)) :]:
            if sched > now + window_min:
                break
            if sched < now - BOARD_PAST_MIN and run not in twin.plans and run not in twin.observed:
                continue  # running to the timetable: it has been and gone
            wanted.setdefault((run, q), sched)
        rows = []
        for (run, q), sched in wanted.items():
            info = self.train(run, band=False)
            r = twin.runs[run]
            base = {"train": info["train"], "run": run, "from": r.frm[0], "to": r.to[-1],
                    "evidence": info["evidence"]["text"]}  # fmt: skip
            stop = self._stop_now(info, code, clock(sched)) if run in twin.plans else info["stops"][q]
            if stop is None:
                if sched >= now - BOARD_PAST_MIN:
                    rows.append({**base, "station": code, "status": "NOT CALLING HERE (diverted)",
                                 "scheduled": clock(sched), "_when": sched})  # fmt: skip
                continue
            when = min((stop[f"_{k}_min"] for k in ("arr", "dep") if f"_{k}_min" in stop), default=None)
            if when is None or when < now - BOARD_PAST_MIN or when > now + window_min:
                continue
            rows.append({**base, **{k: v for k, v in stop.items() if not k.startswith("_")}, "_when": when})
        rows.sort(key=lambda x: (x["_when"], x["run"]))
        for row in rows:
            row.pop("_when")
        return {"station": code, "now": clock(now), "window_min": window_min, "trains": rows[:limit],
                "more": max(len(rows) - limit, 0), "note": NOTE}  # fmt: skip
