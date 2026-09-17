"""Exercise assurance persistence against the disposable CI judge stack only."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from submission.verify_assurance_bundle import verify_bundle  # noqa: E402


def request(path, payload=None, *, expected=200):
    raw = json.dumps(payload).encode() if payload is not None else None
    req = Request("http://127.0.0.1:8080" + path, data=raw, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=20) as response:
            assert response.status == expected, (path, response.status)
            return json.load(response)
    except HTTPError as error:
        if error.code != expected:
            raise RuntimeError(f"{path}: unexpected HTTP {error.code}") from error
        return json.load(error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disposable-ci-stack", action="store_true", required=True)
    parser.parse_args()
    recorded = request("/api/v1/research/recorded-source")
    assert recorded["content_checksums_valid"] is True
    assert recorded["evidence_classification"]["operational_authority"] == "NONE"
    assert len(recorded["feeds"]) == 3
    assert request("/api/v1/planner/stations") == []
    sources = request("/api/v1/provenance/sources")["items"]
    source = next(item for item in sources if item["key"] == "operator_input")
    case = request("/api/v1/assurance/cases", {
        "title": "CI controlled assurance persistence fixture",
        "purpose": "Verify persistence and fail-closed declarations in disposable CI only.",
        "subject_type": "CONTROLLED_TEST_FIXTURE", "subject_key": str(uuid4()),
        "required_roles": ["OBSERVATION"], "context": {"classification": "SYNTHETIC_CI_FIXTURE"},
    }, expected=201)
    prefix = f'/api/v1/assurance/cases/{case["id"]}'
    empty = request(prefix + "/assessments", {}, expected=201)
    assert empty["decision_state"] == "UNAVAILABLE"
    now = datetime.now(timezone.utc).isoformat()
    record = request(prefix + "/evidence", {
        "source_id": source["id"], "evidence_role": "OBSERVATION",
        "entity_type": case["subject_type"], "entity_key": case["subject_key"],
        "canonical_source_type": "OPERATOR_INPUT", "observed_at": now, "fetched_at": now,
        "freshness_state": "FRESH", "availability_state": "AVAILABLE", "completeness": 1,
        "value_summary": {"classification": "SYNTHETIC_CI_FIXTURE", "assertion": "unverified"},
    }, expected=201)
    assert record["metadata"]["ingest_trust"] == "USER_DECLARED"
    assert "license_url" in record and "authority_level" in record
    assessment = request(prefix + "/assessments", {}, expected=201)
    assert assessment["decision_state"] == "HOLD"
    assert assessment["sequence_no"] == 2
    assert any(item["code"] == "SOURCE_USER_DECLARED" for item in assessment["findings"])
    verified = request(prefix + "/verify", {"snapshot_id": assessment["id"]})
    assert verified["verified"] is True, verified
    bundle = request(prefix + "/bundle")
    result = verify_bundle(bundle)
    assert result["canonical_checksums_valid"] is True, result
    assert result["signature_verified"] is False
    request(prefix + "/review-receipts", {
        "snapshot_id": assessment["id"], "outcome": "ATTESTED",
        "statement": "Synthetic self-review must be rejected.",
    }, expected=403)
    assert len(request(prefix + "/timeline")["events"]) >= 4
    print("Assurance HTTP/PostgreSQL smoke passed: empty, capture, HOLD, seal, export, offline checksums and self-review denial.")


if __name__ == "__main__":
    main()
