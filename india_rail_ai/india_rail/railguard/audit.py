"""Decision snapshots and a hash-chained, optionally signed and persisted audit log.

A snapshot freezes every input a recommendation used together with its outputs;
`checksum` covers both, and replay re-runs the planner to show the same ranking
is reproduced. A checksum proves a record was not altered after capture; it does
not prove the inputs were true.

Persistence: with RAILGUARD_AUDIT_DIR set, every event and snapshot is appended
to JSON-lines files. With RAILGUARD_AUDIT_KEY set, each event also carries an
HMAC-SHA256 of its chain hash, and each snapshot an HMAC of its checksum and
wall-clock time, so a log cannot be rewritten without the key. A line torn by a
power cut is closed off at the next start and the chain continues from the last
complete record. Memory is bounded: older events and snapshots stay on disk only.

    python -m india_rail.railguard.audit verify <events.jsonl>     # checks chain (and MACs if key set)
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import sys
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from india_rail.railguard.evidence import checksum

MAX_EVENTS_IN_MEMORY = 5_000
MAX_SNAPSHOTS_IN_MEMORY = 500


def plain_copy(value: Any) -> Any:
    """Deep copy of JSON-like data (dicts, lists, tuples, scalars); much cheaper than copy.deepcopy."""

    kind = type(value)
    if kind is dict:
        return {k: plain_copy(v) for k, v in value.items()}
    if kind is list:
        return [plain_copy(v) for v in value]
    if kind is tuple:
        return tuple(plain_copy(v) for v in value)
    if kind in (str, int, float, bool) or value is None:
        return value
    return copy.deepcopy(value)


def _mac(key: bytes, value: str) -> str:
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


class AuditLog:
    def __init__(self, name: str = "railguard") -> None:
        self.events: list[dict[str, Any]] = []
        self.snapshots: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.base_hash = "GENESIS"  # prev_hash of the oldest event still in memory
        self.count = 0
        self.snapshot_count = 0
        key = os.environ.get("RAILGUARD_AUDIT_KEY", "")
        self.key = key.encode() if key else None
        folder = os.environ.get("RAILGUARD_AUDIT_DIR")
        self.events_path = self.snapshots_path = None
        if folder:
            Path(folder).mkdir(parents=True, exist_ok=True)
            self.events_path = Path(folder) / f"{name}_events.jsonl"
            self.snapshots_path = Path(folder) / f"{name}_snapshots.jsonl"
            # A restart continues the persisted chain instead of starting a second GENESIS in the same file.
            for path in (self.events_path, self.snapshots_path):
                _close_torn_line(path)
            last = _last_record(self.events_path, ("hash", "seq"))
            if last:
                self.base_hash, self.count = last["hash"], int(last["seq"])
            last = _last_record(self.snapshots_path, ("snapshot_id",))
            if last:
                self.snapshot_count = int(str(last["snapshot_id"]).split("-")[1])

    def _append(self, path: Path | None, record: dict[str, Any]) -> None:
        if path is not None:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")

    def record(self, t: int, type_: str, actor: str, details: dict[str, Any]) -> dict[str, Any]:
        self.count += 1
        previous = self.events[-1]["hash"] if self.events else self.base_hash
        event = {"seq": self.count, "t": t, "at": _now_utc(), "type": type_, "actor": actor, "details": details,
                 "prev_hash": previous}  # fmt: skip
        event["hash"] = checksum(event)
        if self.key:
            event["mac"] = _mac(self.key, event["hash"])
        self.events.append(event)
        self._append(self.events_path, event)
        if len(self.events) > MAX_EVENTS_IN_MEMORY:
            self.base_hash = self.events.pop(0)["hash"]
        return event

    def verify_chain(self) -> bool:
        return verify_events(self.events, self.base_hash, self.key)

    def add_snapshot(self, inputs: dict[str, Any], outputs: dict[str, Any], t: int) -> dict[str, Any]:
        self.snapshot_count += 1
        snapshot_id = f"SNAP-{self.snapshot_count:04d}"
        snapshot = {
            "snapshot_id": snapshot_id,
            "t": t,
            "inputs": plain_copy(inputs),
            "outputs": plain_copy(outputs),
            "inputs_checksum": checksum(inputs),
            "outputs_checksum": checksum(outputs),
        }
        snapshot["checksum"] = checksum({k: snapshot[k] for k in ("snapshot_id", "t", "inputs", "outputs")})
        snapshot["at"] = _now_utc()  # wall clock, for matching across days and restarts (outside the replay checksum)
        if self.key:
            snapshot["mac"] = _mac(self.key, f"{snapshot['checksum']}|{snapshot['at']}")
        self.snapshots[snapshot_id] = snapshot
        self._append(self.snapshots_path, snapshot)
        while len(self.snapshots) > MAX_SNAPSHOTS_IN_MEMORY:
            self.snapshots.popitem(last=False)
        return snapshot

    def verify_snapshot(self, snapshot_id: str) -> bool:
        snap = self.snapshots[snapshot_id]
        return snap["checksum"] == checksum({k: snap[k] for k in ("snapshot_id", "t", "inputs", "outputs")})


def _now_utc() -> str:
    """Wall-clock time of a record (UTC, NTP-synced host clock): the twin's own clock `t` restarts every day."""

    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _close_torn_line(path: Path) -> None:
    """End a line left half-written by a crash or power cut, so the next record starts on a line of its own."""

    if path.exists() and path.stat().st_size:
        with path.open("rb+") as handle:
            handle.seek(-1, os.SEEK_END)
            if handle.read(1) != b"\n":
                handle.write(b"\n")


def _last_record(path: Path, required: tuple[str, ...] = ()) -> dict[str, Any] | None:
    """Last complete JSON record (an object with the `required` keys) of an append-only file, read from the end
    so large logs stay cheap."""

    if not path.exists() or path.stat().st_size == 0:
        return None
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        end = handle.tell()
        block = b""
        while True:
            lines = block.strip().splitlines()
            for line in reversed(lines[1:] if end > 0 else lines):  # the first may be cut by the block edge
                try:
                    record = json.loads(line)
                except ValueError:
                    continue  # a torn line: the record before it is the last complete one
                if isinstance(record, dict) and all(k in record for k in required):
                    return record
            if end == 0:
                return None
            step = min(65536, end)
            end -= step
            handle.seek(end)
            block = handle.read(step) + block


def verify_events(events: list[dict[str, Any]], base_hash: str = "GENESIS", key: bytes | None = None) -> bool:
    previous = base_hash
    for event in events:
        body = {k: v for k, v in event.items() if k not in ("hash", "mac")}
        if event["prev_hash"] != previous or checksum(body) != event["hash"]:
            return False
        if key is not None and not hmac.compare_digest(event.get("mac", ""), _mac(key, event["hash"])):
            return False
        previous = event["hash"]
    return True


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "verify":
        print(__doc__)
        return 2
    events, torn = [], 0
    for line in Path(argv[1]).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            torn += 1  # a line cut by a power failure and closed off at the next start: reported, not a crash
    key = os.environ.get("RAILGUARD_AUDIT_KEY", "")
    try:
        ok = verify_events(events, key=key.encode() if key else None)
    except (KeyError, TypeError, AttributeError):
        ok = False
    note = f"; {torn} unreadable line(s) (torn by a power cut?)" if torn else ""
    print(f"{len(events)} events: {'VALID' if ok else 'TAMPERED OR BROKEN'}" + (" (MACs checked)" if key else "")
          + note)  # fmt: skip
    return 0 if ok and not torn else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
