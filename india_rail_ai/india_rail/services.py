"""Shared, lazily built services used by the CLI, the HTTP API and the assistant."""

from __future__ import annotations

import sqlite3
import threading
from functools import cached_property
from pathlib import Path
from typing import Any

from india_rail.ingest import DB_PATH, connect
from india_rail.network import RailNetwork, clock
from india_rail.planner import DisruptionPlanner
from india_rail.runtime_model import MODEL_PATH, TrainedRuntimeModel, load_model, plausibility_mask


class Services:
    def __init__(self, db_path: Path = DB_PATH, model_path: Path = MODEL_PATH):
        self.con: sqlite3.Connection = connect(db_path)
        self.model_path = model_path
        self._lock = threading.Lock()

    @cached_property
    def network(self) -> RailNetwork:
        return RailNetwork(self.con)

    @cached_property
    def model(self) -> TrainedRuntimeModel | None:
        try:
            return load_model(self.model_path)
        except FileNotFoundError:
            return None

    @cached_property
    def planner(self) -> DisruptionPlanner:
        return DisruptionPlanner(self.con, self.model)

    def plan(self, train_number: str, station_code: str, delay_min: int, headway_min: int = 6) -> dict[str, Any]:
        # The planner keeps per-call timelines; serialise calls from threads.
        with self._lock:
            result = self.planner.plan(train_number, station_code, delay_min, headway_min=headway_min)
        if self.model is None:
            result["assumptions"].append("No trained run-time model: section recovery is 0 minutes.")
        return result

    def timetable_slack(self, train_number: str, top: int = 5) -> dict[str, Any]:
        if self.model is None:
            return {"error": "Run-time model not trained. Run `python -m india_rail train`."}
        rows = self.planner.sections_by_train.get(train_number)
        if rows is None:
            return {"error": f"Unknown train {train_number}"}
        pred = self.model.predict_frame(rows)
        frame = rows[["seq", "from_code", "to_code", "dep_min", "runtime_min"]].join(pred)
        # Zero/one-minute interpolated pass-through rows are timetable artefacts,
        # not run-time information (they were excluded from training too).
        excluded = int((~plausibility_mask(rows)).sum())
        frame = frame[plausibility_mask(rows)]
        frame["padding_min"] = frame["runtime_min"] - frame["p50"]

        def describe(r: Any) -> dict[str, Any]:
            return {
                "section": f"{r.from_code}->{r.to_code}",
                "departs": clock(int(r.dep_min)),
                "scheduled_min": int(r.runtime_min),
                "predicted_p50_min": round(float(r.p50), 1),
                "predicted_p10_p90_min": [round(float(r.p10), 1), round(float(r.p90), 1)],
            }

        return {
            "train_number": train_number,
            "sections": len(frame),
            "sections_excluded_as_timetable_artefacts": excluded,
            "scheduled_running_min": int(frame["runtime_min"].sum()),
            "predicted_running_p50_min": round(float(frame["p50"].sum()), 1),
            "recoverable_min_vs_p10": round(float((frame["runtime_min"] - frame["p10"]).clip(lower=0).sum()), 1),
            "most_padded_sections": [describe(r) for r in frame.nlargest(top, "padding_min").itertuples()],
            "tightest_sections": [describe(r) for r in frame.nsmallest(top, "padding_min").itertuples()],
            "note": "Predictions describe how similar trains are timetabled on these sections, not observed running.",
        }
