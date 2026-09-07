"""Verify a shareable ZIP without extracting it (Python standard library only).

Checksums detect corruption, not who produced the package. Obtain the outer
SHA256 file through a trusted channel when verifying a downloaded release.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

MAX_ENTRIES = 10000
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
RESERVED_NAMES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                  *(f"lpt{i}" for i in range(1, 10))}


def validate_name(name: str) -> None:
    """Require portable relative file paths, including on Windows."""
    parts = PurePosixPath(name).parts
    if (not name or any(c in name for c in '\\:<>"|?*') or name.startswith("/")
            or any(ord(c) < 32 for c in name)
            or not parts or any(p in {"", ".", ".."} for p in name.split("/"))
            or any(p.endswith((" ", ".")) or p.split(".")[0].lower() in RESERVED_NAMES
                   for p in parts)):
        raise ValueError(f"Unsafe archive path: {name!r}")


def validate_paths(names) -> None:
    seen: set[str] = set()
    for name in names:
        validate_name(name)
        folded = name.casefold()
        if folded in seen:
            raise ValueError(f"Duplicate archive entry: {name}")
        seen.add(folded)
    for name in seen:
        if any(parent.as_posix() in seen for parent in PurePosixPath(name).parents):
            raise ValueError(f"File/directory path collision: {name}")


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def parse_manifest(data: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    seen: set[str] = set()
    for line in data.splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64})  (.+)", line)
        if not match:
            raise ValueError("Malformed SHA256 manifest")
        checksum, name = match.groups()
        validate_name(name)
        if name.casefold() in seen:
            raise ValueError(f"Duplicate manifest entry: {name}")
        entries[name] = checksum.lower()
        seen.add(name.casefold())
    if not entries:
        raise ValueError("Empty SHA256 manifest")
    return entries


def verify_bundle(path: Path, checksum_file: Path | None = None) -> int:
    if checksum_file is not None:
        expected = parse_manifest(checksum_file.read_text(encoding="utf-8"))
        if set(expected) != {path.name} or expected[path.name] != file_digest(path):
            raise ValueError("Outer bundle checksum mismatch")
    with zipfile.ZipFile(path) as bundle:
        infos = bundle.infolist()
        if len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_EXPANDED_BYTES:
            raise ValueError("Archive exceeds verification limits")
        validate_paths(i.filename for i in infos)
        for info in infos:
            if info.flag_bits & 1 or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("Encrypted entries and symbolic links are not supported")
        if "SHA256SUMS.txt" not in bundle.namelist():
            raise ValueError("Missing SHA256SUMS.txt")
        if bundle.getinfo("SHA256SUMS.txt").file_size > 1024 * 1024:
            raise ValueError("Manifest exceeds verification limits")
        entries = parse_manifest(bundle.read("SHA256SUMS.txt").decode("utf-8"))
        if set(entries) != set(bundle.namelist()) - {"SHA256SUMS.txt"}:
            raise ValueError("Manifest must cover every payload exactly once")
        for name, expected in entries.items():
            with bundle.open(name) as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != expected:
                raise ValueError(f"Checksum mismatch: {name}")
    return len(entries)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--checksum", type=Path, help="Trusted outer .sha256 file")
    args = parser.parse_args()
    try:
        count = verify_bundle(args.bundle, args.checksum)
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS: {count} payloads verified; no files extracted. This is not a deployment test.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
