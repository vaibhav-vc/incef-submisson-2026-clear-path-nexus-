"""Shadow-mode trial support: compare RailGuard's recommendations with what controllers actually decided.

In a shadow trial the system runs beside a real control office and changes nothing: controllers decide as they
always do, their actual decisions are logged here (by hand or from the Control Office Application), and the
report measures how often the ranked alternatives contained the decision that was actually taken. That is the
evidence Indian Railways needs before letting the advice be used.

Each actual decision is matched to the latest recommendation for the same run made at or before the decision,
read from the audit snapshots, so the comparison uses exactly what the controller could have seen.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

ACTIONS = ("CONTINUE", "HOLD", "PATH", "PRIORITY", "REROUTE")


@dataclass
class ActualDecision:
    run: str
    action: str  # one of ACTIONS
    at_min: float
    by: str
    hold_min: float | None = None
    station: str | None = None
    note: str = ""


def _category(action: str) -> str:
    """Candidate action labels ("HOLD+YIELD", "PATH", ...) reduced to the controller's vocabulary."""

    return re.split(r"[\s;+]", action.strip(), maxsplit=1)[0].upper()


class ShadowTrial:
    def __init__(self, twin: Any):
        self.twin = twin
        self.decisions: list[ActualDecision] = []

    def record(self, decision: ActualDecision) -> dict[str, Any]:
        if decision.action not in ACTIONS:
            raise ValueError(f"action must be one of {ACTIONS}")
        if decision.run not in self.twin.runs:
            raise KeyError(decision.run)
        with self.twin.lock:
            self.decisions.append(decision)
            self.twin.audit.record(
                int(self.twin.now * 60), "SHADOW_ACTUAL_DECISION", decision.by, asdict(decision)
            )  # changes nothing in the twin: shadow mode only observes
        return {"recorded": True, "decisions": len(self.decisions)}

    def _recommendation(self, decision: ActualDecision) -> dict[str, Any] | None:
        best = None
        for snap in self.twin.audit.snapshots.values():
            inputs = snap["inputs"]
            if inputs.get("run") == decision.run and inputs.get("now", -1) <= decision.at_min:
                if best is None or inputs["now"] >= best["inputs"]["now"]:
                    best = snap
        return best

    def report(self) -> dict[str, Any]:
        rows = []
        for decision in self.decisions:
            snap = self._recommendation(decision)
            if snap is None:
                rows.append({"run": decision.run, "matched": False})
                continue
            candidates = snap["outputs"]["ranking"].get("candidates", [])
            shown = [_category(c["action"]) for c in candidates]
            rows.append(
                {
                    "run": decision.run,
                    "matched": True,
                    "snapshot_id": snap["snapshot_id"],
                    "actual": decision.action,
                    "recommended": shown[0] if shown else None,
                    "top1": bool(shown) and shown[0] == decision.action,
                    "in_shown": decision.action in shown,
                    "state": snap["outputs"]["state"],
                }
            )
        matched = [r for r in rows if r["matched"]]
        n = len(matched)
        return {
            "decisions_logged": len(self.decisions),
            "decisions_with_a_prior_recommendation": n,
            "top1_agreement_pct": round(100 * sum(r["top1"] for r in matched) / n, 1) if n else None,
            "shown_alternatives_contained_decision_pct": round(100 * sum(r["in_shown"] for r in matched) / n, 1)
            if n
            else None,
            "rows": rows[-200:],
            "note": "Agreement is evidence about usefulness, not safety: the controller's decision is the reference.",
        }
