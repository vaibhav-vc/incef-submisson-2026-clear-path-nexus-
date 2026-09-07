"""Dependency-free output allocation that preserves original measured evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def prepare_output_directory(
    base: Path,
    run_kind: str,
    filenames: tuple[str, ...],
    output_dir: Path | None = None,
) -> Path:
    """Allocate a fresh run folder or reject conflicting explicit output files.

    Writers must also use exclusive creation (``open('x')``) to prevent a race
    between this preflight and writing. Existing unrelated files are preserved.
    """
    if not run_kind or any(c not in "abcdefghijklmnopqrstuvwxyz_-" for c in run_kind):
        raise ValueError("Run kind must be a lowercase filename label")
    for name in filenames:
        if not name or name in {".", ".."} or any(c in name for c in "/\\:"):
            raise ValueError("Output names must be plain filenames")
    if output_dir is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        selected = base / "runs" / f"{stamp}_{run_kind}_{uuid4().hex[:8]}"
        selected.mkdir(parents=True, exist_ok=False)
    else:
        selected = Path(output_dir).expanduser().absolute()
        selected.mkdir(parents=True, exist_ok=True)
    for name in filenames:
        target = selected / name
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"Refusing to overwrite experimental output: {target}")
    return selected


def parse_output_directory(
    base: Path,
    run_kind: str,
    filenames: tuple[str, ...],
    argv: list[str] | None = None,
) -> Path:
    parser = argparse.ArgumentParser(description="Run measurements without overwriting prior evidence.")
    parser.add_argument(
        "--output-dir", type=Path,
        help="Output folder (relative to current directory); existing result files are never overwritten.",
    )
    args = parser.parse_args(argv)
    try:
        return prepare_output_directory(base, run_kind, filenames, args.output_dir)
    except (OSError, ValueError) as error:
        parser.error(str(error))
