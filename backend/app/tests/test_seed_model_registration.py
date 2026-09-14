from __future__ import annotations

import subprocess
import sys


def test_seed_entrypoint_registers_all_relationship_models() -> None:
    """The standalone seed process must configure TrainConsist relationships."""

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import scripts.seed; from sqlalchemy.orm import configure_mappers; configure_mappers()",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
