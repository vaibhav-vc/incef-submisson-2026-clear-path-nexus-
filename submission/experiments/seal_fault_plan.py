#!/usr/bin/env python3
"""Seal a reviewer-authored EvidenceGate challenge plan without overwriting files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from submission.experiments.run_evidence_assurance_benchmark import (  # noqa: E402
    FAULT_PLAN_SCHEMA_VERSION,
    MAX_FAULT_PLAN_BYTES,
    MUTATIONS,
    canonical_sha256,
    write_json_exclusive,
)


def seal_plan(source: Path, destination: Path) -> Path:
    raw = source.read_bytes()
    if not raw or len(raw) > MAX_FAULT_PLAN_BYTES:
        raise ValueError(f"Input plan must be within 1..{MAX_FAULT_PLAN_BYTES} bytes")
    try:
        plan = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Input plan is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(plan, dict):
        raise ValueError("Input plan root must be an object")
    if "plan_payload_sha256" in plan:
        raise ValueError("Input is already sealed; remove plan_payload_sha256 to create a new plan")
    if plan.get("schema_version") != FAULT_PLAN_SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {FAULT_PLAN_SCHEMA_VERSION}")
    if not isinstance(plan.get("protocol_id"), str) or not (3 <= len(plan["protocol_id"]) <= 120):
        raise ValueError("protocol_id must contain 3..120 characters")
    if not isinstance(plan.get("author_role"), str) or not (3 <= len(plan["author_role"]) <= 120):
        raise ValueError("author_role must contain 3..120 characters")
    faults = plan.get("faults")
    if not isinstance(faults, list) or not (2 <= len(faults) <= 100_000):
        raise ValueError("faults must contain 2..100000 cases")
    supported = {"none", *MUTATIONS}
    if any(not isinstance(fault, str) or fault not in supported for fault in faults):
        raise ValueError("faults contains an unsupported mutation")
    if "none" not in faults or not any(fault != "none" for fault in faults):
        raise ValueError("faults must include clean and mutated cases")
    sealed = dict(plan)
    sealed["plan_payload_sha256"] = canonical_sha256(plan)
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_json_exclusive(destination, sealed)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Unsealed reviewer-authored JSON plan")
    parser.add_argument("destination", type=Path, help="New sealed JSON path")
    args = parser.parse_args(argv)
    try:
        output = seal_plan(args.source, args.destination)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
