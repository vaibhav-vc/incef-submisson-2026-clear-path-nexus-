"""Exercise decoder and integrity boundaries using the captured publisher bytes."""

from datetime import datetime
from pathlib import Path
import shutil
from unittest.mock import patch

import pytest

from app.services.recorded_timetable import recorded_timetable_preview


CAPTURE = (
    Path(__file__).resolve().parents[3]
    / "submission/experiments/runs/20260916T064806641708Z_sncf_snapshot_2dc07b37"
)
PIN = "b2d83222fe4bab87f393b8e93c8a29f87ac2f8279ebd9de6ca63f25604bbf49f"


@pytest.mark.parametrize(
    ("source_key", "count_key", "count"),
    [
        ("sncf_gtfs_static", "stop_times", 330490),
        ("sncf_gtfs_rt_trip_updates", "trip_updates", 1675),
        ("sncf_gtfs_rt_service_alerts", "alerts", 527),
    ],
)
def test_actual_snapshot_decodes_with_captured_provenance_and_bounded_rows(
    source_key, count_key, count
):
    with patch("httpx.AsyncClient") as network:
        result = recorded_timetable_preview(CAPTURE, PIN, source_key)
    network.assert_not_called()
    assert result["source_type"] == "REPLAYED_SNAPSHOT"
    assert result["fetched_at"].date() == datetime(2026, 9, 16).date()
    assert result["counts"][count_key] == count
    assert result["manifest_sha256"] == PIN
    assert result["tables"]
    assert all(0 < len(table["rows"]) <= 10 for table in result["tables"])
    assert all(
        len(row) == len(table["columns"]) for table in result["tables"] for row in table["rows"]
    )


def test_cached_preview_rechecks_current_capture_and_is_not_mutable(tmp_path):
    capture = tmp_path / "capture"
    shutil.copytree(CAPTURE, capture)
    result = recorded_timetable_preview(capture, PIN, "sncf_gtfs_rt_trip_updates")
    result["tables"].clear()
    assert recorded_timetable_preview(capture, PIN, "sncf_gtfs_rt_trip_updates")["tables"]
    (capture / "sncf_gtfs_rt_trip_updates.pb").write_bytes(b"changed after first decode")
    with pytest.raises(ValueError, match="integrity"):
        recorded_timetable_preview(capture, PIN, "sncf_gtfs_rt_trip_updates")


def test_unknown_feed_cannot_select_arbitrary_files():
    with pytest.raises(LookupError, match="Unknown"):
        recorded_timetable_preview(CAPTURE, PIN, "../source_manifest.json")


def test_change_between_inspection_and_decode_is_rejected(tmp_path, monkeypatch):
    from app.services import recorded_timetable

    capture = tmp_path / "capture"
    shutil.copytree(CAPTURE, capture)
    inspect = recorded_timetable.inspect_recorded_source
    calls = 0

    def inspect_then_change(*args):
        nonlocal calls
        result = inspect(*args)
        calls += 1
        if calls == 2:
            (capture / "sncf_gtfs_rt_trip_updates.pb").write_bytes(b"changed before decode")
        return result

    monkeypatch.setattr(recorded_timetable, "inspect_recorded_source", inspect_then_change)
    with pytest.raises(ValueError, match="checksum"):
        recorded_timetable_preview(capture, PIN, "sncf_gtfs_rt_trip_updates")
