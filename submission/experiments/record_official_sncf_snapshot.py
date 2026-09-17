#!/usr/bin/env python3
"""Record an immutable, dependency-free snapshot of official SNCF open data.

The recorder preserves the exact response bytes plus enough transport and
licensing metadata for a later experiment to establish what it actually used.
It deliberately does not decode GTFS-Realtime protobuf messages: byte-level
provenance is useful here, but it is not operational or semantic validation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO
from uuid import uuid4


RECORDER_VERSION = "SNCF_SNAPSHOT_V1"
SCHEMA_VERSION = "clearpath.external-source-snapshot.v1"
USER_AGENT = "ClearPath-Nexus-INSEF/7.0 reproducible-research-recorder"
DEFAULT_RUNS_DIR = Path(__file__).resolve().parent / "runs"
CHUNK_BYTES = 128 * 1024
SELECTED_HEADERS = (
    "content-type",
    "content-length",
    "date",
    "etag",
    "last-modified",
    "cache-control",
    "content-location",
)
REQUIRED_GTFS_MEMBERS = (
    "agency.txt",
    "routes.txt",
    "stop_times.txt",
    "stops.txt",
    "trips.txt",
)
ROW_COUNT_MEMBERS = REQUIRED_GTFS_MEMBERS
MAX_ZIP_MEMBERS = 256
MAX_ZIP_UNCOMPRESSED_BYTES = 2_000_000_000
MAX_MEMBER_UNCOMPRESSED_BYTES = 1_000_000_000


@dataclass(frozen=True)
class FeedSpec:
    source_key: str
    data_kind: str
    requested_url: str
    local_filename: str
    max_bytes: int


FEEDS = (
    FeedSpec(
        source_key="sncf_gtfs_static",
        data_kind="published_schedule",
        requested_url=(
            "https://eu.ftp.opendatasoft.com/sncf/plandata/"
            "Export_OpenData_SNCF_GTFS_NewTripId.zip"
        ),
        local_filename="sncf_gtfs_static.zip",
        max_bytes=100 * 1024 * 1024,
    ),
    FeedSpec(
        source_key="sncf_gtfs_rt_trip_updates",
        data_kind="realtime_trip_updates",
        requested_url=(
            "https://proxy.transport.data.gouv.fr/resource/sncf-gtfs-rt-trip-updates"
        ),
        local_filename="sncf_gtfs_rt_trip_updates.pb",
        max_bytes=25 * 1024 * 1024,
    ),
    FeedSpec(
        source_key="sncf_gtfs_rt_service_alerts",
        data_kind="realtime_service_alerts",
        requested_url=(
            "https://proxy.transport.data.gouv.fr/resource/sncf-gtfs-rt-service-alerts"
        ),
        local_filename="sncf_gtfs_rt_service_alerts.pb",
        max_bytes=25 * 1024 * 1024,
    ),
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_response_headers(headers: Any) -> dict[str, str]:
    selected: dict[str, str] = {}
    for name in SELECTED_HEADERS:
        value = headers.get(name)
        if value is not None:
            selected[name] = str(value)
    return selected


def _validate_https_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError(f"Only absolute HTTPS feed URLs are permitted: {url!r}")
    if parsed.username or parsed.password:
        raise ValueError("Feed URLs must not contain credentials")


def _copy_bounded(
    source: BinaryIO,
    destination: BinaryIO,
    *,
    max_bytes: int,
    deadline: float,
) -> tuple[int, str]:
    digest = hashlib.sha256()
    byte_length = 0
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError("Download exceeded the configured total time limit")
        chunk = source.read(CHUNK_BYTES)
        if not chunk:
            break
        byte_length += len(chunk)
        if byte_length > max_bytes:
            raise ValueError(f"Response exceeded maximum permitted size of {max_bytes} bytes")
        destination.write(chunk)
        digest.update(chunk)
    if byte_length == 0:
        raise ValueError("Provider returned an empty response")
    return byte_length, digest.hexdigest()


def download_feed(
    spec: FeedSpec,
    run_dir: Path,
    *,
    socket_timeout_seconds: float,
    total_timeout_seconds: float,
) -> dict[str, Any]:
    """Download one response to a never-before-created file."""

    _validate_https_url(spec.requested_url)
    request_started = utc_now()
    request = urllib.request.Request(
        spec.requested_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/zip, application/x-protobuf, application/octet-stream",
        },
        method="GET",
    )
    destination = run_dir / spec.local_filename
    context = ssl.create_default_context()
    deadline = time.monotonic() + total_timeout_seconds

    with urllib.request.urlopen(
        request,
        timeout=socket_timeout_seconds,
        context=context,
    ) as response:
        status = int(getattr(response, "status", response.getcode()))
        if status != 200:
            raise RuntimeError(f"{spec.source_key} returned HTTP {status}")
        final_url = response.geturl()
        _validate_https_url(final_url)
        declared_length_header = response.headers.get("Content-Length")
        declared_length: int | None = None
        if declared_length_header:
            try:
                declared_length = int(declared_length_header)
            except ValueError as exc:
                raise ValueError("Provider sent an invalid Content-Length") from exc
            if declared_length <= 0 or declared_length > spec.max_bytes:
                raise ValueError(
                    f"Declared Content-Length {declared_length} is outside 1..{spec.max_bytes}"
                )
        with destination.open("xb") as output:
            byte_length, digest = _copy_bounded(
                response,
                output,
                max_bytes=spec.max_bytes,
                deadline=deadline,
            )
            output.flush()
            os.fsync(output.fileno())
        if declared_length is not None and declared_length != byte_length:
            raise ValueError(
                f"Content-Length declared {declared_length} bytes but received {byte_length}"
            )
        completed = utc_now()
        transport = {
            "http_status": status,
            "requested_url": spec.requested_url,
            "final_url": final_url,
            "request_started_at_utc": iso_utc(request_started),
            "response_completed_at_utc": iso_utc(completed),
            "http_headers": _safe_response_headers(response.headers),
        }

    return {
        "source_key": spec.source_key,
        "publisher": "SNCF Voyageurs (via transport.data.gouv.fr)",
        "data_kind": spec.data_kind,
        "local_filename": spec.local_filename,
        "byte_length": byte_length,
        "sha256": digest,
        "transport": transport,
    }


def _safe_zip_member(name: str) -> bool:
    normalized = name.replace("\\", "/")
    return bool(normalized) and not (
        normalized.startswith("/")
        or normalized.startswith("../")
        or "/../" in normalized
        or ":" in normalized.split("/", 1)[0]
    )


def _csv_data_rows(handle: BinaryIO) -> int:
    # GTFS text is UTF-8 (an optional BOM is tolerated). csv.reader correctly
    # handles quoted newlines, unlike counting raw line separators.
    import io

    wrapper = io.TextIOWrapper(handle, encoding="utf-8-sig", errors="strict", newline="")
    try:
        reader = csv.reader(wrapper)
        if next(reader, None) is None:
            raise ValueError("GTFS member has no header")
        return sum(1 for _ in reader)
    finally:
        # Prevent TextIOWrapper from closing ZipExtFile twice in its caller.
        wrapper.detach()


def validate_gtfs_zip(path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            members = archive.infolist()
            if not members or len(members) > MAX_ZIP_MEMBERS:
                raise ValueError("GTFS ZIP has an invalid member count")
            if any(not _safe_zip_member(item.filename) for item in members):
                raise ValueError("GTFS ZIP contains an unsafe member name")
            total_uncompressed = sum(item.file_size for item in members)
            if total_uncompressed > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise ValueError("GTFS ZIP exceeds the total uncompressed-size limit")
            if any(item.file_size > MAX_MEMBER_UNCOMPRESSED_BYTES for item in members):
                raise ValueError("GTFS ZIP contains an oversized member")

            corrupt_member = archive.testzip()
            if corrupt_member is not None:
                raise ValueError(f"GTFS ZIP CRC failure in {corrupt_member!r}")
            names = {item.filename for item in members}
            missing = sorted(set(REQUIRED_GTFS_MEMBERS) - names)
            if missing:
                raise ValueError(f"GTFS ZIP lacks required members: {', '.join(missing)}")

            row_counts: dict[str, int] = {}
            for name in ROW_COUNT_MEMBERS:
                with archive.open(name, "r") as member:
                    row_counts[name] = _csv_data_rows(member)
            if any(count <= 0 for count in row_counts.values()):
                raise ValueError("One or more required GTFS tables contain no data rows")
    except (OSError, UnicodeError, zipfile.BadZipFile) as exc:
        raise ValueError(f"Invalid GTFS ZIP: {exc}") from exc

    return {
        "validation": "ZIP_CRC_AND_REQUIRED_GTFS_MEMBERS_OK",
        "member_count": len(members),
        "required_members": list(REQUIRED_GTFS_MEMBERS),
        "row_counts_excluding_header": row_counts,
        "uncompressed_byte_length": total_uncompressed,
    }


def structural_validation(feed: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    path = run_dir / str(feed["local_filename"])
    if feed["source_key"] == "sncf_gtfs_static":
        return validate_gtfs_zip(path)
    return {
        "validation": "NONEMPTY_PROTOBUF_BYTES_RECORDED",
        "semantic_decode_performed": False,
    }


def _new_run_directory(base_dir: Path) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        stamp = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
        candidate = base_dir / f"{stamp}_sncf_snapshot_{uuid4().hex[:8]}"
        try:
            candidate.mkdir(mode=0o755)
            return candidate
        except FileExistsError:
            continue
    raise FileExistsError("Could not allocate a unique snapshot run directory")


def _write_json_exclusive(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=False, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def capture_snapshot(args: argparse.Namespace) -> Path:
    started = utc_now()
    run_dir = _new_run_directory(args.runs_dir.resolve())
    try:
        feeds: list[dict[str, Any]] = []
        for spec in FEEDS:
            feed = download_feed(
                spec,
                run_dir,
                socket_timeout_seconds=args.socket_timeout,
                total_timeout_seconds=args.total_timeout,
            )
            feed["structural_validation"] = structural_validation(feed, run_dir)
            if sha256_file(run_dir / spec.local_filename) != feed["sha256"]:
                raise RuntimeError(f"Post-write digest mismatch for {spec.source_key}")
            feeds.append(feed)

        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "recorder_version": RECORDER_VERSION,
            "capture_completed_at_utc": iso_utc(utc_now()),
            "capture_started_at_utc": iso_utc(started),
            "runtime": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "user_agent": USER_AGENT,
            },
            "source_catalog": {
                "dataset_page": (
                    "https://transport.data.gouv.fr/datasets/horaires-sncf?locale=fr"
                ),
                "publisher": "SNCF Voyageurs",
                "license": "Open Database License (ODbL) 1.0",
                "license_url": "https://opendatacommons.org/licenses/odbl/1-0/",
                "special_terms_url": (
                    "https://doc.transport.data.gouv.fr/le-point-d-acces-national/"
                    "cadre-juridique/conditions-dutilisation-des-donnees/licence-odbl.md"
                ),
                "attribution": (
                    "Contains information from SNCF Voyageurs' Réseau SNCF TGV, "
                    "Intercités et TER dataset, available under ODbL 1.0 and the "
                    "publisher/platform's stated particular conditions of use."
                ),
            },
            "evidence_classification": {
                "records": "REAL_PUBLISHER_BYTES",
                "incident_labels": "NONE",
                "operational_authority": "NONE",
                "intended_use": "RESEARCH_REPRODUCIBILITY_ONLY",
            },
            "feeds": feeds,
            "limitations": [
                "This French passenger timetable snapshot is not an Indian Railways feed.",
                "Public availability does not make the data safety-authoritative or suitable for control.",
                "GTFS-RT payloads are preserved byte-for-byte but are not semantically decoded here.",
                "Provider validation warnings or scope limitations may exist; consult the dataset page.",
            ],
        }
        manifest["manifest_payload_sha256"] = canonical_sha256(manifest)
        manifest_path = run_dir / "source_manifest.json"
        _write_json_exclusive(manifest_path, manifest)
        return manifest_path
    except Exception as exc:
        # Retain partial bytes as an honest failed capture instead of silently
        # deleting evidence. A failed directory has no source_manifest.json.
        error_path = run_dir / "capture_error.json"
        if not error_path.exists():
            _write_json_exclusive(
                error_path,
                {
                    "capture_failed_at_utc": iso_utc(utc_now()),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "incomplete_run": True,
                },
            )
        raise RuntimeError(f"Snapshot capture failed; partial run retained at {run_dir}: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=DEFAULT_RUNS_DIR,
        help="Parent directory for a new immutable run (default: %(default)s)",
    )
    parser.add_argument(
        "--socket-timeout",
        type=float,
        default=20.0,
        help="Per-socket operation timeout in seconds",
    )
    parser.add_argument(
        "--total-timeout",
        type=float,
        default=90.0,
        help="Total time limit per feed in seconds",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.socket_timeout <= 0 or args.total_timeout <= 0:
        parser.error("timeouts must be positive")
    try:
        manifest = capture_snapshot(args)
    except (OSError, RuntimeError, ValueError, urllib.error.URLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
