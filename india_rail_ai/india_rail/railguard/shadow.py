"""Shadow-mode trial support: compare RailGuard's recommendations with what controllers actually decided.

In a shadow trial the system runs beside a real control office and changes nothing: controllers decide as they
always do, their actual decisions are logged here (one at a time, or as a CSV export of the Control Office
Application's decisions), and the report measures how often the ranked alternatives contained the decision that
was actually taken. That is the evidence Indian Railways needs before letting the advice be used.

Each actual decision is matched to the latest recommendation for the same run made at or before the decision
(by wall-clock time, so a trial running for months across restarts and service days is matched correctly),
read from the audit snapshots, so the comparison uses exactly what the controller could have seen.

A trial outlives the in-memory audit window: `report_from_audit_dir` rebuilds the report from the persisted,
hash-chained audit files (RAILGUARD_AUDIT_DIR), and so does

    python -m india_rail shadow-report --audit-dir <dir> [--out report.json]
"""

from __future__ import annotations

import csv
import io
import json
import re
import statistics
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ACTIONS = ("CONTINUE", "HOLD", "PATH", "PRIORITY", "REROUTE")
MATCH_WINDOW = timedelta(hours=6)  # a recommendation older than this is not what the controller acted on
MAX_IMPORT_ROWS = 2000
CSV_COLUMNS = ("train_number", "start_date", "action", "decided_at", "station", "hold_min", "desk", "note")
TRAIN = re.compile(r"^[0-9A-Z][0-9A-Z-]{0,15}$")
CODE = re.compile(r"^[A-Z0-9]{1,8}$")
DESK = re.compile(r"^[A-Za-z0-9 ._-]{1,40}$")


@dataclass
class ActualDecision:
    run: str
    action: str  # one of ACTIONS
    at_min: float
    by: str
    hold_min: float | None = None
    station: str | None = None
    note: str = ""
    at: str | None = None  # wall clock (UTC ISO 8601) when it was decided; set when recorded if not given


def _category(action: str) -> str:
    """Candidate action labels ("HOLD+YIELD", "REROUTE+PATH", ...) reduced to the controller's vocabulary."""

    return re.split(r"[\s;+]", action.strip(), maxsplit=1)[0].upper()


def _utc(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _match(decision: dict[str, Any], snapshots: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    """Latest recommendation for the decision's run made at or before it (wall clock where both carry it)."""

    at = _utc(decision.get("at"))
    best, best_key = None, None
    for snap in snapshots:
        inputs = snap["inputs"]
        if inputs.get("run") != decision["run"]:
            continue
        snap_at = _utc(snap.get("at"))
        if at is not None and snap_at is not None:
            if not at - MATCH_WINDOW <= snap_at <= at:
                continue
            key = snap_at.timestamp()
        elif inputs.get("now", -1) <= decision["at_min"]:
            key = float(inputs["now"])
        else:
            continue
        if best_key is None or key >= best_key:
            best, best_key = snap, key
    return best


def build_report(decisions: list[dict[str, Any]], snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for d in decisions:
        snap = _match(d, snapshots)
        if snap is None:
            rows.append({"run": d["run"], "actual": d["action"], "matched": False})
            continue
        candidates = snap["outputs"]["ranking"].get("candidates", [])
        shown = [_category(c["action"]) for c in candidates]
        lead = None
        if _utc(d.get("at")) and _utc(snap.get("at")):
            lead = (_utc(d["at"]) - _utc(snap["at"])).total_seconds() / 60
        rows.append({
            "run": d["run"],
            "matched": True,
            "snapshot_id": snap["snapshot_id"],
            "actual": d["action"],
            "recommended": shown[0] if shown else None,
            "top1": bool(shown) and shown[0] == d["action"],
            "in_shown": d["action"] in shown,
            "state": snap["outputs"]["state"],
            "minutes_after_recommendation": None if lead is None else round(lead, 1),
        })  # fmt: skip
    matched = [r for r in rows if r["matched"]]
    n = len(matched)

    def pct(part: list[dict[str, Any]], field: str) -> float | None:
        return round(100 * sum(r[field] for r in part) / len(part), 1) if part else None

    by_action = {
        a: {"decisions": len(part), "top1_agreement_pct": pct(part, "top1"), "in_shown_pct": pct(part, "in_shown")}
        for a in ACTIONS
        if (part := [r for r in matched if r["actual"] == a])
    }
    by_state = {s: {"decisions": c, "top1_agreement_pct": pct([r for r in matched if r["state"] == s], "top1")}
                for s, c in Counter(r["state"] for r in matched).items()}  # fmt: skip
    leads = [r["minutes_after_recommendation"] for r in matched if r["minutes_after_recommendation"] is not None]
    unseen = Counter(r["run"] for r in rows if not r["matched"])
    return {
        "decisions_logged": len(rows),
        "decisions_with_a_prior_recommendation": n,
        "top1_agreement_pct": pct(matched, "top1"),
        "shown_alternatives_contained_decision_pct": pct(matched, "in_shown"),
        "by_actual_action": by_action,
        "by_recommendation_state": by_state,
        "median_minutes_from_recommendation_to_decision": round(statistics.median(leads), 1) if leads else None,
        "decisions_without_a_recommendation": {"count": sum(unseen.values()), "runs": sorted(unseen)[:50]},
        "rows": rows[-200:],
        "note": "Agreement is evidence about usefulness, not safety: the controller's decision is the reference. "
        "Decisions without a recommendation are situations the system did not see or was not asked about.",
    }


class ShadowTrial:
    def __init__(self, twin: Any):
        self.twin = twin
        self.decisions: list[ActualDecision] = []

    def record(self, decision: ActualDecision) -> dict[str, Any]:
        if decision.action not in ACTIONS:
            raise ValueError(f"action must be one of {ACTIONS}")
        if decision.run not in self.twin.runs:
            raise KeyError(decision.run)
        decision.at = decision.at or datetime.now(UTC).isoformat(timespec="milliseconds")
        _utc(decision.at)  # refuses a malformed time before anything is written
        with self.twin.lock:
            self.decisions.append(decision)
            self.twin.audit.record(
                int(self.twin.now * 60), "SHADOW_ACTUAL_DECISION", decision.by, asdict(decision)
            )  # changes nothing in the twin: shadow mode only observes
        return {"recorded": True, "decisions": len(self.decisions)}

    def import_csv(self, text: str, by: str, service_date: date) -> dict[str, Any]:
        """Decisions exported from the control office, one per row (CSV_COLUMNS, header required).

        `decided_at` is ISO 8601 with a time zone; `start_date` is the train's journey start. Each row is
        checked on its own: a bad row is reported and skipped, never guessed at."""

        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None or set(reader.fieldnames) != set(CSV_COLUMNS):
            raise ValueError(f"header must be exactly: {','.join(CSV_COLUMNS)}")
        results, recorded = [], 0
        for n, row in enumerate(reader, start=2):
            if n - 1 > MAX_IMPORT_ROWS:
                raise ValueError(f"at most {MAX_IMPORT_ROWS} rows per import")
            try:
                decision = self._row(row, by, service_date)
                self.record(decision)
                recorded += 1
                results.append({"line": n, "recorded": True, "run": decision.run})
            except (ValueError, KeyError, TypeError) as exc:
                results.append({"line": n, "recorded": False, "reason": str(exc)[:160]})
        return {"recorded": recorded, "refused": len(results) - recorded, "rows": results[:MAX_IMPORT_ROWS]}

    def _row(self, row: dict[str, str], by: str, service_date: date) -> ActualDecision:
        number, start = (row["train_number"] or "").strip().upper(), (row["start_date"] or "").strip()
        if not TRAIN.match(number):
            raise ValueError("invalid train_number")
        run = f"{number}@{(date.fromisoformat(start) - service_date).days}"
        if run not in self.twin.runs:
            raise KeyError(f"no run {run} in the twin")
        action = (row["action"] or "").strip().upper()
        decided = datetime.fromisoformat((row["decided_at"] or "").strip().replace("Z", "+00:00"))
        if decided.tzinfo is None:
            raise ValueError("decided_at must be ISO 8601 with a time zone")
        station = (row["station"] or "").strip().upper() or None
        if station is not None and not CODE.match(station):
            raise ValueError("invalid station")
        hold = float(row["hold_min"]) if (row["hold_min"] or "").strip() else None
        if hold is not None and not 0 <= hold <= 720:
            raise ValueError("hold_min must be 0-720")
        desk = (row["desk"] or "").strip()
        if desk and not DESK.match(desk):
            raise ValueError("invalid desk")
        ist = decided.astimezone(timezone(timedelta(hours=5, minutes=30)))
        at_min = (ist.date() - service_date).days * 1440 + ist.hour * 60 + ist.minute + ist.second / 60
        note = (row["note"] or "").strip()[:200]
        return ActualDecision(run, action, at_min, f"{by} ({desk})" if desk else by, hold, station, note,
                              decided.astimezone(UTC).isoformat(timespec="seconds"))  # fmt: skip

    def report(self) -> dict[str, Any]:
        return build_report([asdict(d) for d in self.decisions], list(self.twin.audit.snapshots.values()))


def report_from_audit_dir(folder: Path, name: str = "railguard") -> dict[str, Any]:
    """The report over the whole persisted trial (every restart and service day), read from the audit files."""

    events, snaps = folder / f"{name}_events.jsonl", folder / f"{name}_snapshots.jsonl"
    decisions = []
    if events.exists():
        with events.open(encoding="utf-8") as handle:
            for line in handle:
                if '"SHADOW_ACTUAL_DECISION"' in line:
                    event = json.loads(line)
                    if event["type"] == "SHADOW_ACTUAL_DECISION":
                        decisions.append(event["details"])
    runs = {d["run"] for d in decisions}
    snapshots = []
    if snaps.exists():
        with snaps.open(encoding="utf-8") as handle:
            for line in handle:
                snap = json.loads(line)
                if snap["inputs"].get("run") in runs:  # keep only what matching and agreement need
                    ranking = snap["outputs"]["ranking"]
                    snapshots.append({
                        "snapshot_id": snap["snapshot_id"],
                        "at": snap.get("at"),
                        "inputs": {"run": snap["inputs"]["run"], "now": snap["inputs"].get("now")},
                        "outputs": {"state": snap["outputs"]["state"],
                                    "ranking": {"candidates": [{"action": c["action"]}
                                                               for c in ranking.get("candidates", [])]}},
                    })  # fmt: skip
    report = build_report(decisions, snapshots)
    report["source"] = {"events": str(events), "snapshots": str(snaps), "recommendations_read": len(snapshots)}
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m india_rail shadow-report")
    parser.add_argument("--audit-dir", type=Path, required=True, help="RAILGUARD_AUDIT_DIR of the trial")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    report = report_from_audit_dir(args.audit_dir)
    text = json.dumps(report, indent=2, default=str)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2, default=str))
    return 0
