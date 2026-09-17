"""Controlled corruption tests for the offline reconstruction contract."""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import runpy
from uuid import uuid4

import pytest

from app.models.provenance import LineageEdge
from app.services.assurance_integrity import lineage_payload
from app.services.provenance import redact_metadata, stable_checksum


VERIFY = runpy.run_path(
    str(Path(__file__).resolve().parents[3] / "submission/verify_assurance_bundle.py"),
    run_name="assurance_export_test",
)["verify_bundle"]


def _bundle() -> dict:
    """Synthetic software fixture, never represented as a real railway record."""
    child_id, parent_id, source_id, case_id, snapshot_id = [uuid4() for _ in range(5)]
    source = {"id": source_id, "license_name": "controlled fixture"}
    envelope = {
        "id": child_id,
        "source_id": source_id,
        "observed_at": datetime(2026, 9, 17, tzinfo=timezone.utc),
        "value_summary": {"number": 1.23456789},
        "metadata": {"api_key": "synthetic-value-for-redaction-test"},
    }
    edge = LineageEdge(
        id=uuid4(), parent_record_id=parent_id, child_record_id=child_id,
        relationship="DERIVED_FROM",
    )
    lineage = lineage_payload([edge], child_id)
    manifest = {
        "format_version": "clearpath.assurance-manifest.v1",
        "case": {"id": case_id},
        "snapshot": {
            "id": snapshot_id,
            "evidence_manifest": [{
                "record_id": str(child_id), "source_id": str(source_id),
                "integrity_checksum": stable_checksum(envelope),
                "source_metadata_checksum": stable_checksum(source),
                "lineage_checksum": stable_checksum(lineage),
            }],
        },
    }
    return redact_metadata({
        "format_version": "clearpath.assurance-bundle.v1",
        "assessment": {"id": snapshot_id, "bundle_checksum": stable_checksum(manifest)},
        "sealed_manifest": manifest,
        "evidence_envelopes": [envelope], "source_catalog": [source], "lineage": lineage,
        "review_receipts": [], "review_receipt_manifests": [],
    })


def test_exported_canonical_form_reconstructs_backend_checksums() -> None:
    bundle = _bundle()
    assert bundle["evidence_envelopes"][0]["metadata"]["api_key"] == "[REDACTED]"
    result = VERIFY(bundle)
    assert result["canonical_checksums_valid"] is True
    assert result["signature_verified"] is False


@pytest.mark.parametrize("section", ["evidence", "source", "lineage", "manifest"])
def test_offline_verifier_detects_changes_in_every_proof_section(section: str) -> None:
    bundle = deepcopy(_bundle())
    if section == "evidence":
        bundle["evidence_envelopes"][0]["value_summary"]["number"] = 999
    elif section == "source":
        bundle["source_catalog"][0]["license_name"] = "changed terms"
    elif section == "lineage":
        bundle["lineage"].clear()
    else:
        bundle["sealed_manifest"]["case"]["id"] = str(uuid4())
    assert VERIFY(bundle)["canonical_checksums_valid"] is False


def test_offline_verifier_rejects_duplicate_records() -> None:
    bundle = _bundle()
    bundle["evidence_envelopes"].append(deepcopy(bundle["evidence_envelopes"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        VERIFY(bundle)


def test_lineage_receipt_changes_when_an_edge_is_replaced() -> None:
    child_id = uuid4()
    edge = LineageEdge(id=uuid4(), parent_record_id=uuid4(), child_record_id=child_id, relationship="DERIVED_FROM")
    original = stable_checksum(lineage_payload([edge], child_id))
    edge.parent_record_id = uuid4()
    assert stable_checksum(lineage_payload([edge], child_id)) != original
    assert stable_checksum(lineage_payload([], child_id)) != original
