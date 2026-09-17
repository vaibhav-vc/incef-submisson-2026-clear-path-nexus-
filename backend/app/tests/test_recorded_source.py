"""The offline source view must detect changed bytes without trusting the capture."""

import json
from pathlib import Path

import pytest

from app.services.recorded_source import inspect_recorded_source


CAPTURE = (
    Path(__file__).resolve().parents[3]
    / "submission/experiments/runs/20260916T064806641708Z_sncf_snapshot_2dc07b37"
)
PIN = "b2d83222fe4bab87f393b8e93c8a29f87ac2f8279ebd9de6ca63f25604bbf49f"


def test_committed_publisher_bytes_match_manifest():
    result = inspect_recorded_source(CAPTURE, PIN)
    assert result["content_checksums_valid"] is True
    assert len(result["feeds"]) == 3
    assert result["evidence_classification"]["operational_authority"] == "NONE"


def test_modified_bytes_are_detected(tmp_path):
    manifest = json.loads((CAPTURE / "source_manifest.json").read_text(encoding="utf-8"))
    (tmp_path / "source_manifest.json").write_bytes((CAPTURE / "source_manifest.json").read_bytes())
    for feed in manifest["feeds"]:
        (tmp_path / feed["local_filename"]).write_bytes(b"modified")
    result = inspect_recorded_source(tmp_path, PIN)
    assert result["manifest_checksum_valid"] is True
    assert result["content_checksums_valid"] is False
    assert not any(feed["checksum_valid"] for feed in result["feeds"])


def test_unsafe_filename_is_rejected(tmp_path):
    manifest = json.loads((CAPTURE / "source_manifest.json").read_text(encoding="utf-8"))
    manifest["feeds"][0]["local_filename"] = "../escape"
    (tmp_path / "source_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe"):
        inspect_recorded_source(tmp_path, PIN)


def test_duplicate_manifest_keys_are_rejected(tmp_path):
    (tmp_path / "source_manifest.json").write_text(
        '{"schema_version": "a", "schema_version": "b"}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="Duplicate"):
        inspect_recorded_source(tmp_path, PIN)


def test_recomputed_self_checksum_cannot_override_pinned_manifest(tmp_path):
    from app.services.recorded_source import _canonical_digest

    manifest = json.loads((CAPTURE / "source_manifest.json").read_text(encoding="utf-8"))
    manifest["source_catalog"]["publisher"] = "Altered publisher"
    payload = {key: value for key, value in manifest.items() if key != "manifest_payload_sha256"}
    manifest["manifest_payload_sha256"] = _canonical_digest(payload)
    (tmp_path / "source_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = inspect_recorded_source(tmp_path, PIN)
    assert result["manifest_pin_valid"] is False
    assert result["content_checksums_valid"] is False


def test_offline_compose_uses_isolated_real_only_dataset():
    import yaml

    compose = yaml.safe_load(
        (CAPTURE.parents[3] / "docker-compose.judge-demo.yml").read_text(encoding="utf-8")
    )
    assert compose["name"] == "evidencegate-judge-real"
    backend = compose["services"]["backend"]
    assert backend["environment"]["DEMO_DATA_ENABLED"] == "false"
    assert backend["environment"]["REAL_DATA_ONLY"] == "true"
    assert backend["environment"]["RECORDED_SOURCE_SNAPSHOT_DIR"] == "/opt/recorded-source"
    assert backend["environment"]["RECORDED_SOURCE_MANIFEST_SHA256"] == PIN
    assert any(volume.endswith(":/opt/recorded-source:ro") for volume in backend["volumes"])
