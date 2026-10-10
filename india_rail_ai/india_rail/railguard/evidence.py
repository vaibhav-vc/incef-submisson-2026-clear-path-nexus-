"""EvidenceGate for the digital twin: freshness, completeness and integrity.

Every input the planner relies on is an EvidenceRecord with a source, an
observation time and a freshness policy. Mandatory evidence that is STALE puts
the recommendation in HOLD; MISSING puts it in UNAVAILABLE. A plan can only be
approved when the assessment is REVIEWABLE (the gate fails closed).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

FRESH, AGING, STALE, MISSING = "FRESH", "AGING", "STALE", "MISSING"
REVIEWABLE, HOLD, UNAVAILABLE = "REVIEWABLE", "HOLD", "UNAVAILABLE"


def checksum(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass
class EvidenceRecord:
    key: str  # e.g. "position:A", "condition:S02", "schedule:B"
    kind: str  # POSITION / CONDITION / SCHEDULE / RESTRICTION / WEATHER
    source: str  # e.g. TWINTRACK_SENSOR, TRACKSENSE_SIM, TIMETABLE
    observed_t: int
    fresh_s: int
    stale_s: int
    mandatory: bool
    payload_checksum: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EvidenceStore:
    def __init__(self) -> None:
        self.records: dict[str, EvidenceRecord] = {}

    def put(
        self, key: str, kind: str, source: str, t: int, payload: Any, *, fresh_s: int, stale_s: int, mandatory: bool
    ) -> EvidenceRecord:
        record = EvidenceRecord(key, kind, source, t, fresh_s, stale_s, mandatory, checksum(payload))
        self.records[key] = record
        return record

    def remove(self, key: str) -> None:
        self.records.pop(key, None)

    def state_of(self, key: str, now: int) -> str:
        record = self.records.get(key)
        if record is None:
            return MISSING
        age = now - record.observed_t
        if age < 0 or age > record.stale_s:
            # A timestamp from the future is as untrustworthy as a stale one.
            return STALE
        return FRESH if age <= record.fresh_s else AGING

    def assess(self, now: int, required: list[str]) -> dict[str, Any]:
        """Assess the evidence a recommendation depends on."""

        items = []
        for key in sorted(set(required) | set(self.records)):
            record = self.records.get(key)
            mandatory = key in required or (record is not None and record.mandatory)
            state = self.state_of(key, now)
            items.append(
                {
                    "key": key,
                    "state": state,
                    "mandatory": mandatory,
                    "source": record.source if record else None,
                    "age_s": (now - record.observed_t) if record else None,
                    "checksum": record.payload_checksum if record else None,
                }
            )
        mandatory_items = [i for i in items if i["mandatory"]]
        missing = [i["key"] for i in mandatory_items if i["state"] == MISSING]
        stale = [i["key"] for i in mandatory_items if i["state"] == STALE]
        if missing:
            state = UNAVAILABLE
        elif stale:
            state = HOLD
        else:
            state = REVIEWABLE
        total = len(mandatory_items)
        present = total - len(missing)
        fresh_count = sum(i["state"] == FRESH for i in mandatory_items)
        return {
            "state": state,
            "missing": missing,
            "stale": stale,
            "aging": [i["key"] for i in mandatory_items if i["state"] == AGING],
            "completeness": round(present / total, 3) if total else 0.0,
            "fresh_rate": round(fresh_count / total, 3) if total else 0.0,
            "items": items,
        }
