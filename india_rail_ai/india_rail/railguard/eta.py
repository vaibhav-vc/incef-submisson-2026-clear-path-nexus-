"""Arrival-delay forecasts learned from real running, for trains the live feed reports late.

Trained on observed arrivals of 1-20 September 2024 and scored on 21-30 September (see realval.py):
average error 13.9 minutes against 17.4 for carrying the delay forward with dwell recovery (the twin's
rule without it), and 80% of forecasts within 15 minutes. The P10-P90 band covered 82% of real outcomes.

The forecast moves only the *projection* of a reported-late train (where it will be, so conflicts are
looked for in the right place). It never approves, holds or releases anything; controllers decide.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from india_rail.realdata import REAL_DB_PATH


class EtaForecaster:
    def __init__(self, model_path: Path | None = None, db: Path | None = None, history_until: str | None = None):
        """`db`: the timetable the twin runs on (default: the one it is configured for). History comes from the
        observed running (data/real.sqlite), keyed by train and station."""

        import joblib

        from india_rail import realval
        from india_rail.railguard.national import timetable_source

        bundle = joblib.load(model_path or realval.ETA_MODEL_PATH)  # nosec B301 - model file produced by this project
        self.median, self.p10, self.p90 = bundle["median"], bundle["p10"], bundle["p90"]
        self.features = bundle["features"]
        data = realval.load(db or timetable_source()[1], obs_db=REAL_DB_PATH)
        # In operation the history is every real day available; validation passes the training cut-off.
        self.lookups = realval.Lookups(data, history_until=history_until or max(data["obs"].date))
        self.source = bundle.get("trained_on", "")

    def _rows(self, train: str, run_date: str, p: int, d_now: float, targets: list[int]) -> pd.DataFrame:
        return pd.DataFrame(self.lookups.rows(train, run_date, p, d_now, targets))[self.features]

    def delays(
        self, train: str, run_date: str, p: int, d_now: float, targets: list[int], band: bool = True
    ) -> dict[str, np.ndarray]:
        """Forecast arrival delay (minutes) at each target stop: median, and the P10/P90 band if asked."""

        models = (("median", self.median), ("p10", self.p10), ("p90", self.p90)) if band else (("median", self.median),)
        if not targets:
            return {name: np.array([]) for name, _ in models}
        rows = self._rows(train, run_date, p, d_now, targets)
        return {name: np.maximum(d_now + model.predict(rows), 0.0) for name, model in models}

    def plan(self, twin: Any, key: str, p: int, d_now: float, horizon_min: float = 480.0):
        """The run's plan with forecast delays at its later stops (held at the last forecast beyond the horizon)."""

        plan = twin.plan_of(key)
        n = len(plan.sections)
        until = plan.enter[p] + d_now + horizon_min
        targets = [q for q in range(p + 1, n + 1) if plan.s_exit[q - 1] is not None and plan.s_exit[q - 1] <= until]
        number, day = key.split("@")
        run_date = (twin_service_date(twin) + timedelta(days=int(day))).isoformat()
        forecast = self.delays(number, run_date, p, d_now, targets, band=False)["median"].tolist()
        return forecast_plan(plan, p, {p: d_now, **dict(zip(targets, forecast, strict=True))})

    def forecast(self, twin: Any, key: str) -> list[dict[str, Any]]:
        """Downstream stops of a run with its current delay and the forecast band (for the console and cab)."""

        plan = twin.plan_of(key)
        pos = twin.position(key)
        p = pos["index"]
        d_now = max(plan.enter[p] - plan.s_enter[p], 0.0) if plan.s_enter[p] is not None else 0.0
        targets = list(range(p + 1, len(plan.sections) + 1))
        number, day = key.split("@")
        run_date = (twin_service_date(twin) + timedelta(days=int(day))).isoformat()
        band = self.delays(number, run_date, p, d_now, targets)
        return [
            {
                "station": plan.to[q - 1],
                "scheduled_min": plan.s_exit[q - 1],
                "delay_min": round(float(band["median"][k]), 1),
                "delay_p10_min": round(float(band["p10"][k]), 1),
                "delay_p90_min": round(float(band["p90"][k]), 1),
            }
            for k, q in enumerate(targets)
        ]


RUN_FLOOR = 0.85  # a forecast may not have a train run a section faster than 85% of its timetabled time


def forecast_plan(plan: Any, p: int, delay_at: dict[int, float]):
    """Apply forecast arrival delays (stop index -> minutes) to a timetable-following plan from stop `p` on.

    Physically consistent whatever the forecast says: a train never leaves a stop before it has arrived there,
    and never runs a section in less than RUN_FLOOR of its timetabled running time. Beyond the last forecast
    stop the last forecast delay is held.
    """

    from dataclasses import replace

    last = delay_at[max(delay_at)]
    enter, exit_ = list(plan.enter), list(plan.exit)
    arrived = exit_[p - 1] if p > 0 else float("-inf")
    for i in range(p, len(plan.sections)):
        se, sx = plan.s_enter[i], plan.s_exit[i]
        if se is None or sx is None:  # off the timetable (a detour): keep the plan as it is from here
            break
        dep = max(se + delay_at.get(i, last), arrived)
        arrived = max(sx + delay_at.get(i + 1, last), dep + RUN_FLOOR * max(sx - se, 0.0))
        enter[i], exit_[i] = dep, arrived
    return replace(plan, enter=enter, exit=exit_, sources={**plan.sources, p: delay_at[p]},
                   note="FORECAST_FROM_REAL_RUNNING")  # fmt: skip


def twin_service_date(twin: Any) -> date:
    return date.fromisoformat(twin.data.stats["service_date"])


def load_default() -> EtaForecaster | None:
    """The forecaster when the trained model and the real data are present (else the twin's own rule is used)."""

    from india_rail import realval

    if not (realval.ETA_MODEL_PATH.exists() and REAL_DB_PATH.exists()):
        return None
    return EtaForecaster()
