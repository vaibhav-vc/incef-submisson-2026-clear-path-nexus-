"""The offline source view must detect changed bytes without trusting the capture."""

import json
from pathlib import Path

import pytest

from app.services.recorded_source import inspect_recorded_source


CAPTURE = (
    Path(__file__).resolve().parents[3]
    / "submission/experiments/runs/20260916T064806641708Z_sncf_snapshot_2dc07b37"
)


def test_committed_publisher_bytes_match_manifest():
    result = inspect_recorded_source(CAPTURE)
    assert result["content_checksums_valid"] is True
    assert len(result["feeds"]) == 3
    assert result["evidence_classification"]["operational_authority"] == "NONE"


def test_modified_bytes_are_detected(tmp_path):
    manifest = json.loads((CAPTURE / "source_manifest.json").read_text(encoding="utf-8"))
    (tmp_path / "source_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for feed in manifest["feeds"]:
        (tmp_path / feed["local_filename"]).write_bytes(b"modified")
    result = inspect_recorded_source(tmp_path)
    assert result["manifest_checksum_valid"] is True
    assert result["content_checksums_valid"] is False
    assert not any(feed["checksum_valid"] for feed in result["feeds"])


def test_unsafe_filename_is_rejected(tmp_path):
    manifest = json.loads((CAPTURE / "source_manifest.json").read_text(encoding="utf-8"))
    manifest["feeds"][0]["local_filename"] = "../escape"
    (tmp_path / "source_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe"):
        inspect_recorded_source(tmp_path)


def test_duplicate_manifest_keys_are_rejected(tmp_path):
    (tmp_path / "source_manifest.json").write_text(
        '{"schema_version": "a", "schema_version": "b"}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="Duplicate"):
        inspect_recorded_source(tmp_path)


def test_offline_compose_uses_isolated_real_only_dataset():
    import yaml

    compose = yaml.safe_load((CAPTURE.parents[3] / "docker-compose.judge-demo.yml").read_text(encoding="utf-8"))
    assert compose["name"] == "evidencegate-judge-real"
    backend = compose["services"]["backend"]
    assert backend["environment"]["DEMO_DATA_ENABLED"] == "false"
    assert backend["environment"]["REAL_DATA_ONLY"] == "true"
    assert backend["environment"]["RECORDED_SOURCE_SNAPSHOT_DIR"] == "/opt/recorded-source"
    assert any(volume.endswith(":/opt/recorded-source:ro") for volume in backend["volumes"])
