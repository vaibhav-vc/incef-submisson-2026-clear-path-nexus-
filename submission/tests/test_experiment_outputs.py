"""Dependency-free experiment output and schema checks; never contacts providers."""
import tempfile
import unittest
import contextlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from submission.experiments.output_paths import prepare_output_directory
from submission.experiments.run_live_provider_observations import (
    validate_noaa,
    validate_open_meteo,
)
from submission.experiments import run_live_provider_observations as live_runner


class ExperimentOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.names = ("results.csv", "summary.json")

    def test_default_runs_are_unique_and_preserve_originals(self):
        original = self.root / "results.csv"
        original.write_text("original measurements", encoding="utf-8")
        first = prepare_output_directory(self.root, "evidencegate", self.names)
        second = prepare_output_directory(self.root, "evidencegate", self.names)
        self.assertNotEqual(first, second)
        self.assertEqual(self.root / "runs", first.parent)
        self.assertRegex(first.name, r"^\d{8}T\d{12}Z_evidencegate_[0-9a-f]{8}$")
        self.assertEqual("original measurements", original.read_text(encoding="utf-8"))

    def test_explicit_directory_can_be_created(self):
        selected = self.root / "custom" / "new-run"
        self.assertEqual(selected, prepare_output_directory(self.root, "test", self.names, selected))
        self.assertTrue(selected.is_dir())

    def test_existing_unrelated_file_is_preserved(self):
        note = self.root / "notes.txt"
        note.write_text("operator note", encoding="utf-8")
        prepare_output_directory(self.root, "test", self.names, self.root)
        self.assertEqual("operator note", note.read_text(encoding="utf-8"))

    def test_any_existing_result_refuses_entire_run(self):
        for name in self.names:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                original = output / name
                original.write_bytes(b"measured evidence")
                with self.assertRaises(FileExistsError):
                    prepare_output_directory(self.root, "test", self.names, output)
                self.assertEqual(b"measured evidence", original.read_bytes())
                self.assertEqual([original], list(output.iterdir()))

    def test_output_names_cannot_escape_directory(self):
        for name in ("../old.csv", "x/y.csv", "x\\y.csv", "C:old.csv", "..", ""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                prepare_output_directory(self.root, "test", (name,))

    def test_existing_directory_cannot_be_overwritten_as_result(self):
        (self.root / self.names[0]).mkdir()
        with self.assertRaises(FileExistsError):
            prepare_output_directory(self.root, "test", self.names, self.root)


class ProviderSchemaTests(unittest.TestCase):
    def weather(self):
        return {"current": {"time": "2026-09-07T10:15", "temperature_2m": 28.1,
                            "relative_humidity_2m": 75, "precipitation": 0,
                            "weather_code": 3, "wind_speed_10m": 8.2, "visibility": 24000}}

    def test_valid_weather_is_accepted(self):
        self.assertTrue(validate_open_meteo(self.weather())[0])

    def test_weather_rejects_invalid_numeric_values(self):
        for value in (None, True, "28.1", float("nan"), float("inf"), [], {}):
            payload = self.weather()
            payload["current"]["temperature_2m"] = value
            with self.subTest(value=value):
                self.assertFalse(validate_open_meteo(payload)[0])

    def test_weather_rejects_invalid_timestamps(self):
        for timestamp in (None, 0, "", "2026-09-07", "not-a-time", "2026-99-99T99:00"):
            payload = self.weather()
            payload["current"]["time"] = timestamp
            with self.subTest(timestamp=timestamp):
                self.assertFalse(validate_open_meteo(payload)[0])

    def test_valid_noaa_numeric_string_is_accepted(self):
        self.assertTrue(validate_noaa([{"time_tag": "2026-09-07T09:00:00Z", "Kp": "3.67"}])[0])

    def test_noaa_rejects_invalid_kp(self):
        for value in (None, True, float("nan"), float("inf"), -1, 10, "garbage"):
            with self.subTest(value=value):
                self.assertFalse(validate_noaa([{"time_tag": "2026-09-07T09:00:00Z", "Kp": value}])[0])

    def test_noaa_rejects_invalid_timestamp(self):
        self.assertFalse(validate_noaa([{"time_tag": "not-a-time", "Kp": "3"}])[0])

    def test_live_runner_exit_code_preserves_pass_and_failure_measurements(self):
        for valid in (True, False):
            with self.subTest(valid=valid), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                weather = self.weather() if valid else {"current": {}}

                class FakeClient:
                    def __init__(self, **_kwargs):
                        pass

                    def __enter__(self):
                        return self

                    def __exit__(self, *_args):
                        pass

                    def get(self, url):
                        payload = weather if url == live_runner.OPEN_METEO_URL else [
                            {"time_tag": "2026-09-07T09:00:00Z", "Kp": "3"}
                        ]
                        return SimpleNamespace(
                            raise_for_status=lambda: None, json=lambda: payload, status_code=200,
                        )

                with (
                    patch.dict("sys.modules", {"httpx": SimpleNamespace(Client=FakeClient)}),
                    patch("sys.argv", ["runner", "--output-dir", str(output)]),
                    patch.object(live_runner, "REPETITIONS", 1),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    self.assertEqual(0 if valid else 1, live_runner.main())
                self.assertTrue((output / "live_provider_observations.csv").is_file())
                summary = json.loads((output / "live_provider_summary.json").read_text(encoding="utf-8"))
                self.assertEqual(2, summary["total_requests"])
                self.assertEqual(1 if valid else 0, summary["providers"][0]["schema_valid"])


if __name__ == "__main__":
    unittest.main()
