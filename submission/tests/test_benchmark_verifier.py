import json
import runpy
import shutil
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER = runpy.run_path(
    str(REPO_ROOT / "submission/verify_evidence_assurance_run.py"),
    run_name="benchmark_verifier_test",
)
RUN_DIR = (
    REPO_ROOT
    / "submission/experiments/runs/20260919T040756096976Z_evidence_assurance_40fe5fe4"
)
SOURCE_DIR = (
    REPO_ROOT / "submission/experiments/runs/20260916T064806641708Z_sncf_snapshot_2dc07b37"
)


class BenchmarkVerifierTests(unittest.TestCase):
    def test_checked_in_v2_run_and_source_bytes_verify(self):
        result = VERIFIER["verify_run"](
            RUN_DIR / "evidence_assurance_run_manifest.json",
            SOURCE_DIR / "source_manifest.json",
        )
        self.assertEqual("VERIFIED", result["status"])
        self.assertEqual(2400, result["cases"])
        self.assertEqual(3, len(result["source"]["feeds"]))

    def test_changed_result_bytes_fail_before_interpretation(self):
        with tempfile.TemporaryDirectory() as temp:
            copied = Path(temp) / "run"
            shutil.copytree(RUN_DIR, copied)
            summary_path = copied / "evidence_assurance_summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["total_cases"] = 999
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "output digest mismatch"):
                VERIFIER["verify_run"](
                    copied / "evidence_assurance_run_manifest.json",
                    SOURCE_DIR / "source_manifest.json",
                )


if __name__ == "__main__":
    unittest.main()
