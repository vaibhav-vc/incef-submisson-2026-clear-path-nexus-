"""Reconstruct exported assurance checksums offline, with no dependencies.

Only the canonical proof sections are verified. Human-readable presentation
fields are supplementary. HMAC authentication requires the trusted API; this
tool never treats self-consistent checksums as proof of authorship or safety.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


MAX_BUNDLE_BYTES = 64 * 1024 * 1024


def checksum(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _unique_rows(rows: list[dict], key: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for row in rows:
        identifier = row[key]
        if not isinstance(identifier, str) or identifier in result:
            raise ValueError(f"Invalid or duplicate {key}")
        result[identifier] = row
    return result


def verify_bundle(bundle: dict) -> dict:
    if bundle["format_version"] != "clearpath.assurance-bundle.v1":
        raise ValueError("Unsupported assurance bundle format")
    manifest = bundle["sealed_manifest"]
    if manifest["format_version"] != "clearpath.assurance-manifest.v1":
        raise ValueError("Unsupported assurance manifest format")
    errors: list[str] = []
    assessment = bundle["assessment"]
    if checksum(manifest) != assessment["bundle_checksum"]:
        errors.append("SEALED_MANIFEST_CHECKSUM_MISMATCH")
    if manifest["snapshot"]["id"] != assessment["id"]:
        errors.append("SNAPSHOT_ID_MISMATCH")
    expected = _unique_rows(manifest["snapshot"]["evidence_manifest"], "record_id")
    envelopes = _unique_rows(bundle["evidence_envelopes"], "id")
    sources = _unique_rows(bundle["source_catalog"], "id")
    if set(expected) != set(envelopes):
        errors.append("EVIDENCE_SET_MISMATCH")
    if {row["source_id"] for row in expected.values()} != set(sources):
        errors.append("SOURCE_SET_MISMATCH")
    lineage = bundle["lineage"]
    _unique_rows(lineage, "id")
    if any(edge["child_record_id"] not in expected for edge in lineage):
        errors.append("UNBOUND_LINEAGE")
    for record_id, receipt in expected.items():
        envelope = envelopes.get(record_id)
        if envelope is None or checksum(envelope) != receipt["integrity_checksum"]:
            errors.append(f"EVIDENCE_CHECKSUM_MISMATCH:{record_id}")
        source = sources.get(receipt["source_id"])
        if source is None or checksum(source) != receipt["source_metadata_checksum"]:
            errors.append(f"SOURCE_CHECKSUM_MISMATCH:{record_id}")
        edges = sorted(
            [edge for edge in lineage if edge["child_record_id"] == record_id],
            key=lambda edge: (edge["parent_record_id"], edge["relationship"], edge["id"]),
        )
        if checksum(edges) != receipt["lineage_checksum"]:
            errors.append(f"LINEAGE_CHECKSUM_MISMATCH:{record_id}")
    reviews = _unique_rows(bundle["review_receipts"], "id")
    review_manifests = _unique_rows(bundle["review_receipt_manifests"], "id")
    if set(reviews) != set(review_manifests):
        errors.append("REVIEW_SET_MISMATCH")
    for receipt_id, receipt in reviews.items():
        canonical = review_manifests.get(receipt_id)
        if canonical is None or checksum(canonical) != receipt["receipt_checksum"]:
            errors.append(f"REVIEW_CHECKSUM_MISMATCH:{receipt_id}")
        elif (
            canonical["snapshot_checksum"] != assessment["bundle_checksum"]
            or canonical["snapshot_id"] != assessment["id"]
            or canonical["case_id"] != manifest["case"]["id"]
        ):
            errors.append(f"REVIEW_BINDING_MISMATCH:{receipt_id}")
    return {
        "canonical_checksums_valid": not errors,
        "signature_verified": False,
        "signature_status": "NOT_CHECKED_REQUIRES_TRUSTED_SERVER",
        "scope": "Canonical manifest, evidence envelopes, source catalog, lineage and review receipts only",
        "limitations": [
            "Checksums alone do not authenticate the sender; compare with a root obtained through a trusted channel.",
            "Display summaries, policy correctness, current freshness and operational safety are not certified.",
            "Sensitive metadata is redacted and floating-point values use the server's six-decimal canonical form.",
        ],
        "errors": errors,
    }


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("Non-finite JSON number")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    try:
        with args.bundle.open("rb") as handle:
            raw = handle.read(MAX_BUNDLE_BYTES + 1)
        if len(raw) > MAX_BUNDLE_BYTES:
            raise ValueError("Assurance bundle exceeds 64 MiB")
        bundle = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        result = verify_bundle(bundle)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
        print(json.dumps({"canonical_checksums_valid": False, "error": "Invalid or unreadable assurance bundle"}))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["canonical_checksums_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
