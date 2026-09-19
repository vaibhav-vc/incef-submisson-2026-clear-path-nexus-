#!/usr/bin/env python3
"""Dependency-free integrity verifier for an EvidenceGate benchmark run."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


MAX_JSON_BYTES = 10 * 1024 * 1024
MAX_CSV_BYTES = 512 * 1024 * 1024
CHUNK_BYTES = 128 * 1024
BASE_OUTPUTS = {"evidence_assurance_cases.csv", "evidence_assurance_summary.json"}
EXPECTED_CLASSIFIERS = {
    "b0_latest_value", "b1_checksum_timestamp", "b2_role_quorum",
    "b3_conservative_complete", "b4_legacy_score", "full_evidence_gate",
}


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path, maximum_bytes: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            total += len(chunk)
            if total > maximum_bytes:
                raise ValueError(f"{path.name} exceeds {maximum_bytes} bytes")
            digest.update(chunk)
    return digest.hexdigest(), total


def load_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if not raw or len(raw) > MAX_JSON_BYTES:
        raise ValueError(f"{path.name} must be within 1..{MAX_JSON_BYTES} bytes")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path.name} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} root must be an object")
    return value


def safe_child(directory: Path, filename: object) -> Path:
    if (
        not isinstance(filename, str)
        or filename != Path(filename).name
        or filename in {"", ".", ".."}
        or "/" in filename
        or "\\" in filename
    ):
        raise ValueError(f"Unsafe artifact filename {filename!r}")
    path = directory / filename
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Required regular artifact is missing: {filename}")
    return path


def verify_source_snapshot(path: Path, expected_file_digest: str) -> dict[str, Any]:
    file_digest, _ = sha256_file(path, MAX_JSON_BYTES)
    if file_digest != expected_file_digest:
        raise ValueError("Source-manifest file digest mismatch")
    manifest = load_json(path)
    declared = manifest.get("manifest_payload_sha256")
    payload = dict(manifest)
    payload.pop("manifest_payload_sha256", None)
    if canonical_sha256(payload) != declared:
        raise ValueError("Source-manifest payload digest mismatch")
    feeds = manifest.get("feeds")
    if not isinstance(feeds, list) or not feeds:
        raise ValueError("Source manifest contains no feeds")
    verified = []
    for feed in feeds:
        if not isinstance(feed, dict):
            raise ValueError("Source feed must be an object")
        source_file = safe_child(path.parent, feed.get("local_filename"))
        digest, length = sha256_file(source_file, MAX_CSV_BYTES)
        if digest != feed.get("sha256") or length != feed.get("byte_length"):
            raise ValueError(f"Source feed verification failed: {source_file.name}")
        verified.append({"source_key": feed.get("source_key"), "sha256": digest, "bytes": length})
    return {"manifest_sha256": file_digest, "feeds": verified}


def verify_run(run_manifest_path: Path, source_manifest_path: Path) -> dict[str, Any]:
    run_manifest_path = run_manifest_path.resolve(strict=True)
    if run_manifest_path.is_symlink():
        raise ValueError("Run manifest must be a regular file, not a symlink")
    manifest = load_json(run_manifest_path)
    if manifest.get("schema_version") != "clearpath.experiment-run.v2":
        raise ValueError("Unsupported experiment-run schema")
    declared_manifest_digest = manifest.get("manifest_payload_sha256")
    payload = dict(manifest)
    payload.pop("manifest_payload_sha256", None)
    if canonical_sha256(payload) != declared_manifest_digest:
        raise ValueError("Run-manifest payload digest mismatch")
    outputs = manifest.get("output_files")
    expected_outputs = set(BASE_OUTPUTS)
    if manifest.get("fault_plan", {}).get("origin") == "SEALED_DECLARED_PLAN":
        expected_outputs.add("fault_plan.json")
    if not isinstance(outputs, dict) or set(outputs) != expected_outputs:
        raise ValueError("Run manifest output set does not match its plan origin")
    run_dir = run_manifest_path.parent
    csv_path = safe_child(run_dir, "evidence_assurance_cases.csv")
    summary_path = safe_child(run_dir, "evidence_assurance_summary.json")
    csv_digest, _ = sha256_file(csv_path, MAX_CSV_BYTES)
    summary_digest, _ = sha256_file(summary_path, MAX_JSON_BYTES)
    if outputs[csv_path.name] != csv_digest or outputs[summary_path.name] != summary_digest:
        raise ValueError("Run output digest mismatch")
    if "fault_plan.json" in outputs:
        plan_path = safe_child(run_dir, "fault_plan.json")
        plan_digest, _ = sha256_file(plan_path, MAX_JSON_BYTES)
        if (
            outputs[plan_path.name] != plan_digest
            or manifest["fault_plan"].get("file_sha256") != plan_digest
        ):
            raise ValueError("Preserved fault-plan digest mismatch")

    summary = load_json(summary_path)
    if summary.get("csv_sha256") != csv_digest:
        raise ValueError("Summary CSV digest mismatch")
    if summary.get("experiment_version") != manifest.get("experiment_version"):
        raise ValueError("Experiment version mismatch")
    if summary.get("fault_plan") != manifest.get("fault_plan"):
        raise ValueError("Fault-plan metadata mismatch")
    if summary.get("experimental_parameters") != manifest.get("experimental_parameters"):
        raise ValueError("Experimental-parameter metadata mismatch")
    if len(summary.get("evidence_gate_policy_errors", [])) != manifest.get(
        "evidence_gate_policy_error_count"
    ):
        raise ValueError("Policy-error count mismatch")

    fingerprints: set[str] = set()
    row_count = 0
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        classifiers_value = summary.get("classifiers")
        if not isinstance(classifiers_value, dict) or set(classifiers_value) != EXPECTED_CLASSIFIERS:
            raise ValueError("Summary classifier set is incomplete or unexpected")
        classifiers = set(classifiers_value)
        required = {
            "case_id", "case_fingerprint_sha256", "expected_admissible",
            "source_snapshot_manifest_sha256", *classifiers,
        }
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError("CSV is missing required result columns")
        for row in reader:
            row_count += 1
            fingerprint = row["case_fingerprint_sha256"]
            if len(fingerprint) != 64 or fingerprint in fingerprints:
                raise ValueError("CSV contains an invalid or duplicate case fingerprint")
            fingerprints.add(fingerprint)
            if row["source_snapshot_manifest_sha256"] != manifest.get(
                "source_snapshot_manifest_sha256"
            ):
                raise ValueError("CSV source-manifest digest mismatch")
            if row["expected_admissible"] not in {"True", "False"}:
                raise ValueError("CSV contains an invalid expected label")
            if any(row[classifier] not in {"True", "False"} for classifier in classifiers):
                raise ValueError("CSV contains an invalid classifier result")
    if row_count != manifest.get("case_count") or row_count != summary.get("total_cases"):
        raise ValueError("Case count mismatch")
    if len(fingerprints) != summary.get("unique_case_fingerprints"):
        raise ValueError("Unique case count mismatch")

    source = verify_source_snapshot(
        source_manifest_path.resolve(strict=True),
        manifest.get("source_snapshot_manifest_sha256"),
    )
    if summary.get("external_source_snapshot", {}).get("manifest_file_sha256") != source[
        "manifest_sha256"
    ]:
        raise ValueError("Summary source-manifest digest mismatch")
    return {
        "status": "VERIFIED",
        "experiment_version": manifest.get("experiment_version"),
        "cases": row_count,
        "run_manifest_payload_sha256": declared_manifest_digest,
        "csv_sha256": csv_digest,
        "summary_sha256": summary_digest,
        "source": source,
        "limitations": [
            "Integrity verification does not establish correctness, independence, or railway safety.",
            "Declared plan authorship and independence are not cryptographically authenticated.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_manifest", type=Path)
    parser.add_argument("source_manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        report = verify_run(args.run_manifest, args.source_manifest)
    except (OSError, ValueError) as exc:
        print(f"VERIFICATION_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
