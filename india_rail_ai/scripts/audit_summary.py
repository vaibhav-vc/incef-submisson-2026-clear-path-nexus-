"""Measure the figures the report quotes about the code itself, so they cannot drift from what was run.

    python scripts/audit_summary.py [--bandit PATH] [--pip-audit PATH]

Writes seva2026/evidence/audit/audit_summary.json: tests passed, attack tests, Bandit findings and lines
scanned, pip-audit result, and the national twin's statistics on the timetable it is configured for.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404 - runs this project's own test and scan tools with fixed arguments
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # run as a script from anywhere
OUT = ROOT / "seva2026" / "evidence" / "audit" / "audit_summary.json"


def run(command: list[str]) -> str:
    done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)  # nosec B603
    return done.stdout + done.stderr


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bandit", default="bandit")
    parser.add_argument("--pip-audit", dest="pip_audit", default="pip-audit")
    args = parser.parse_args()
    summary: dict = {}

    tests = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"])
    passed = re.search(r"(\d+) passed", tests)
    failed = re.search(r"(\d+) failed", tests)
    summary["tests_passed"] = int(passed.group(1)) if passed else 0
    summary["tests_failed"] = int(failed.group(1)) if failed else 0
    collected = run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
                     "tests/test_attacks.py", "tests/test_attacks_live.py"])  # fmt: skip
    summary["attack_tests"] = sum(1 for line in collected.splitlines() if "::" in line)

    try:
        raw = run([args.bandit, "-q", "-r", "india_rail", "-f", "json"])
        report, _ = json.JSONDecoder().raw_decode(raw[raw.index("{") :])  # warnings may surround the JSON
        summary["bandit_findings"] = len(report["results"])
        summary["bandit_lines_scanned"] = report["metrics"]["_totals"]["loc"]
        summary["bandit_reviewed_suppressions"] = sum(
            text.count("# nosec") for text in (p.read_text() for p in (ROOT / "india_rail").rglob("*.py"))
        )
    except (OSError, ValueError, KeyError):
        summary["bandit_findings"] = None
    raw = run([args.pip_audit, "-r", "requirements.txt", "--progress-spinner", "off", "-f", "json"])
    try:
        deps = json.JSONDecoder().raw_decode(raw[raw.index("{") :])[0]["dependencies"]
        summary["pip_audit"] = {
            "packages": len(deps),
            "known_vulnerabilities": sum(len(d.get("vulns", [])) for d in deps),
        }
    except (ValueError, KeyError):
        summary["pip_audit"] = {"error": raw[-300:]}

    from india_rail.railguard.national import build_national, timetable_source

    name, path = timetable_source()
    stats = dict(build_national(path).stats)
    stats["timetable"] = name
    summary["national_stats"] = stats
    from india_rail.current import CURRENT_DB_PATH

    if CURRENT_DB_PATH.exists():
        import sqlite3

        con = sqlite3.connect(f"file:{CURRENT_DB_PATH}?mode=ro", uri=True)
        one = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
        summary["registry"] = {
            "trains_current": one("SELECT COUNT(*) FROM train_registry WHERE in_current_2026 = 1"),
            "trains_all_sources": one("SELECT COUNT(*) FROM train_registry"),
            "by_operator": dict(
                con.execute(
                    "SELECT operator, COUNT(*) FROM train_registry WHERE in_current_2026 = 1 "
                    "GROUP BY operator ORDER BY 2 DESC"
                )
            ),  # fmt: skip
            "trains_with_observed_running": one(
                "SELECT COUNT(*) FROM train_registry WHERE in_current_2026 = 1 " "AND real_running_observed = 1"
            ),  # fmt: skip
            "stations": one("SELECT COUNT(*) FROM stations"),
            "stations_with_pin": one("SELECT COUNT(*) FROM station_pin"),
            "sections_with_mapped_track": one(
                "SELECT COUNT(*) FROM osm_sections WHERE quality = 'ACCEPTED' " "AND geometry IS NOT NULL"
            ),  # fmt: skip
        }
        con.close()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "national_stats"}, indent=2))
    return 0 if not summary["tests_failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
