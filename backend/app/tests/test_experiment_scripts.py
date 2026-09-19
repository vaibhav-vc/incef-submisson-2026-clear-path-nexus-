from __future__ import annotations

import hashlib
import json
import random
import runpy
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import settings


REPO_ROOT = Path(__file__).resolve().parents[3]
RECORDER = runpy.run_path(
    str(REPO_ROOT / "submission/experiments/record_official_sncf_snapshot.py"),
    run_name="sncf_recorder_test",
)
BENCHMARK = runpy.run_path(
    str(REPO_ROOT / "submission/experiments/run_evidence_assurance_benchmark.py"),
    run_name="evidence_benchmark_test",
)
FAULT_PLAN_SEALER = runpy.run_path(
    str(REPO_ROOT / "submission/experiments/seal_fault_plan.py"),
    run_name="fault_plan_sealer_test",
)


def test_recorder_validates_required_gtfs_tables_and_crc() -> None:
    with tempfile.TemporaryDirectory(prefix="experiment-test-", dir=REPO_ROOT / "backend") as temp:
        archive_path = Path(temp) / "fixture.zip"
        with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for filename in RECORDER["REQUIRED_GTFS_MEMBERS"]:
                archive.writestr(filename, "id,name\n1,controlled fixture\n")

        result = RECORDER["validate_gtfs_zip"](archive_path)

    assert result["validation"] == "ZIP_CRC_AND_REQUIRED_GTFS_MEMBERS_OK"
    assert result["member_count"] == len(RECORDER["REQUIRED_GTFS_MEMBERS"])
    assert set(result["row_counts_excluding_header"]) == set(RECORDER["ROW_COUNT_MEMBERS"])
    assert all(count == 1 for count in result["row_counts_excluding_header"].values())


def test_source_manifest_verifier_rejects_changed_publisher_bytes() -> None:
    with tempfile.TemporaryDirectory(prefix="experiment-test-", dir=REPO_ROOT / "backend") as temp:
        temp_path = Path(temp)
        source_path = temp_path / "source.bin"
        source_path.write_bytes(b"real recorded publisher bytes")
        source_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        manifest = {
            "schema_version": BENCHMARK["SOURCE_SCHEMA_VERSION"],
            "evidence_classification": {
                "records": "REAL_PUBLISHER_BYTES",
                "incident_labels": "NONE",
                "operational_authority": "NONE",
                "intended_use": "RESEARCH_REPRODUCIBILITY_ONLY",
            },
            "source_catalog": {
                "publisher": "SNCF Voyageurs",
                "license": "Open Database License (ODbL) 1.0",
                "dataset_page": "https://example.test/dataset",
                "license_url": "https://example.test/license",
                "special_terms_url": "https://example.test/terms",
            },
            "feeds": [],
        }
        for index, source_key in enumerate(sorted(BENCHMARK["EXPECTED_SOURCE_KEYS"])):
            filename = f"source-{index}.bin"
            feed_path = temp_path / filename
            feed_path.write_bytes(source_path.read_bytes())
            manifest["feeds"].append(
                {
                    "source_key": source_key,
                    "local_filename": filename,
                    "sha256": source_digest,
                    "byte_length": source_path.stat().st_size,
                    "transport": {
                        "http_status": 200,
                        "requested_url": "https://example.test/requested",
                        "final_url": "https://example.test/final",
                    },
                }
            )
        manifest["manifest_payload_sha256"] = BENCHMARK["canonical_sha256"](manifest)
        manifest_path = temp_path / "source_manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        verified = BENCHMARK["verify_source_manifest"](manifest_path)
        assert all(feed["sha256"] == source_digest for feed in verified.feeds)

        (temp_path / "source-0.bin").write_bytes(b"changed")
        with pytest.raises(ValueError, match="verification failed"):
            BENCHMARK["verify_source_manifest"](manifest_path)


def test_every_controlled_mutation_fails_closed_in_backend_gate(monkeypatch) -> None:
    monkeypatch.setattr(settings, "EVIDENCE_SIGNING_KEY_ID", "benchmark-test-key")
    monkeypatch.setattr(settings, "EVIDENCE_SIGNING_KEY", "b" * 64)
    monkeypatch.setattr(settings, "EVIDENCE_VERIFICATION_KEYS", {})

    clean = BENCHMARK["build_clean_bundle"](random.Random(1), 0)
    BENCHMARK["seal_and_optionally_tamper"](clean, "none")
    assert BENCHMARK["full_evidence_gate"](clean)[0] is True

    for index, fault in enumerate(BENCHMARK["MUTATIONS"], start=1):
        bundle = BENCHMARK["build_clean_bundle"](random.Random(index), index)
        BENCHMARK["apply_mutation"](bundle, fault, random.Random(index + 1000))
        BENCHMARK["seal_and_optionally_tamper"](bundle, fault)
        admitted, reasons = BENCHMARK["full_evidence_gate"](bundle)
        assert admitted is False, (fault, reasons)


def test_all_predeclared_baselines_accept_a_clean_fixture(monkeypatch) -> None:
    monkeypatch.setattr(settings, "EVIDENCE_SIGNING_KEY_ID", "benchmark-test-key")
    monkeypatch.setattr(settings, "EVIDENCE_SIGNING_KEY", "b" * 64)
    monkeypatch.setattr(settings, "EVIDENCE_VERIFICATION_KEYS", {})
    bundle = BENCHMARK["build_clean_bundle"](random.Random(55), 0)
    BENCHMARK["seal_and_optionally_tamper"](bundle, "none")
    for classifier in BENCHMARK["CLASSIFIER_NAMES"]:
        function = BENCHMARK[classifier]
        result = function(bundle)
        admitted = result[0] if isinstance(result, tuple) else result
        assert admitted is True, classifier


def test_declared_fault_plan_is_sealed_bounded_and_not_self_certifying() -> None:
    with tempfile.TemporaryDirectory(prefix="experiment-test-", dir=REPO_ROOT / "backend") as temp:
        path = Path(temp) / "fault-plan.json"
        plan = {
            "schema_version": BENCHMARK["FAULT_PLAN_SCHEMA_VERSION"],
            "protocol_id": "held-out-fixture-v1",
            "author_role": "external-reviewer-fixture",
            "declared_independence": True,
            "faults": ["none", "wrong_context", "lineage_cycle"],
        }
        plan["plan_payload_sha256"] = BENCHMARK["canonical_sha256"](plan)
        path.write_text(json.dumps(plan), encoding="utf-8")

        faults, metadata, file_digest = BENCHMARK["load_declared_fault_plan"](path)
        assert faults == plan["faults"]
        assert metadata["origin"] == "SEALED_DECLARED_PLAN"
        assert metadata["declared_independence"] is True
        assert len(file_digest) == 64

        plan["faults"][1] = "none"
        path.write_text(json.dumps(plan), encoding="utf-8")
        with pytest.raises(ValueError, match="digest mismatch"):
            BENCHMARK["load_declared_fault_plan"](path)


def test_declared_fault_plan_requires_both_outcome_classes() -> None:
    for faults in (["none", "none"], ["wrong_context", "lineage_cycle"]):
        with tempfile.TemporaryDirectory(prefix="experiment-test-", dir=REPO_ROOT / "backend") as temp:
            path = Path(temp) / "fault-plan.json"
            plan = {
                "schema_version": BENCHMARK["FAULT_PLAN_SCHEMA_VERSION"],
                "protocol_id": "invalid-fixture-v1",
                "author_role": "test-fixture",
                "faults": faults,
            }
            plan["plan_payload_sha256"] = BENCHMARK["canonical_sha256"](plan)
            path.write_text(json.dumps(plan), encoding="utf-8")
            with pytest.raises(ValueError, match="clean and mutated"):
                BENCHMARK["load_declared_fault_plan"](path)


def test_fault_plan_sealer_never_overwrites_and_round_trips() -> None:
    with tempfile.TemporaryDirectory(prefix="experiment-test-", dir=REPO_ROOT / "backend") as temp:
        root = Path(temp)
        source = root / "draft.json"
        destination = root / "sealed.json"
        draft = {
            "schema_version": BENCHMARK["FAULT_PLAN_SCHEMA_VERSION"],
            "protocol_id": "reviewer-held-out-v1",
            "author_role": "declared reviewer role",
            "declared_independence": False,
            "faults": ["none", "wrong_context"],
        }
        source.write_text(json.dumps(draft), encoding="utf-8")
        FAULT_PLAN_SEALER["seal_plan"](source, destination)
        faults, metadata, _ = BENCHMARK["load_declared_fault_plan"](destination)
        assert faults == draft["faults"]
        assert metadata["declared_independence"] is False
        with pytest.raises(FileExistsError):
            FAULT_PLAN_SEALER["seal_plan"](source, destination)


def test_declared_plan_is_preserved_inside_run_artifacts() -> None:
    source_manifest = (
        REPO_ROOT
        / "submission/experiments/runs/20260916T064806641708Z_sncf_snapshot_2dc07b37"
        / "source_manifest.json"
    )
    with tempfile.TemporaryDirectory(prefix="experiment-test-", dir=REPO_ROOT / "backend") as temp:
        root = Path(temp)
        draft_path = root / "draft.json"
        sealed_path = root / "sealed.json"
        draft = {
            "schema_version": BENCHMARK["FAULT_PLAN_SCHEMA_VERSION"],
            "protocol_id": "preservation-fixture-v1",
            "author_role": "test fixture",
            "declared_independence": False,
            "faults": ["none", "wrong_context"],
        }
        draft_path.write_text(json.dumps(draft), encoding="utf-8")
        FAULT_PLAN_SEALER["seal_plan"](draft_path, sealed_path)
        manifest_path, status = BENCHMARK["run_benchmark"](
            SimpleNamespace(
                source_manifest=source_manifest,
                seed=123,
                fault_plan=sealed_path,
                cases=None,
                role_quorum_minimum=4,
                legacy_score_threshold=60.0,
                output_dir=root / "run",
            )
        )
        assert status == 0
        run_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert (manifest_path.parent / "fault_plan.json").read_bytes() == sealed_path.read_bytes()
        assert set(run_manifest["output_files"]) == {
            "evidence_assurance_cases.csv", "evidence_assurance_summary.json", "fault_plan.json",
        }
