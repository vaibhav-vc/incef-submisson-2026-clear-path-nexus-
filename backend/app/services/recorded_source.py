"""Inspect a captured publisher snapshot without granting operational trust."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


MAX_MANIFEST_BYTES = 64 * 1024
MAX_FEED_BYTES = 100 * 1024 * 1024


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate snapshot manifest key: {key}")
        value[key] = item
    return value


def _canonical_digest(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def inspect_recorded_source(directory: Path) -> dict[str, Any]:
    """Check recorded bytes and return a bounded, explicit research-only view."""
    root = directory.resolve(strict=True)
    manifest_file = root / "source_manifest.json"
    if not manifest_file.is_file() or manifest_file.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("Recorded source manifest is missing or exceeds its size limit")
    manifest = json.loads(
        manifest_file.read_text(encoding="utf-8"),
        object_pairs_hook=_unique_pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "clearpath.external-source-snapshot.v1"
    ):
        raise ValueError("Unsupported recorded source manifest")
    stored_digest = manifest.get("manifest_payload_sha256")
    payload = {key: value for key, value in manifest.items() if key != "manifest_payload_sha256"}
    manifest_checksum_valid = stored_digest == _canonical_digest(payload)
    feeds = manifest.get("feeds")
    if not isinstance(feeds, list) or not 1 <= len(feeds) <= 16:
        raise ValueError("Recorded source feed list is invalid")
    checked_feeds = []
    used_names: set[str] = set()
    for feed in feeds:
        if not isinstance(feed, dict):
            raise ValueError("Recorded source feed entry is invalid")
        filename = feed.get("local_filename")
        if (
            not isinstance(filename, str)
            or filename in used_names
            or Path(filename).name != filename
            or filename in {".", ".."}
        ):
            raise ValueError("Recorded source filename is unsafe or repeated")
        used_names.add(filename)
        expected_length = feed.get("byte_length")
        expected_digest = feed.get("sha256")
        if (
            not isinstance(expected_length, int)
            or isinstance(expected_length, bool)
            or not 0 <= expected_length <= MAX_FEED_BYTES
        ):
            raise ValueError("Recorded source byte length is invalid")
        if (
            not isinstance(expected_digest, str)
            or len(expected_digest) != 64
            or any(character not in "0123456789abcdef" for character in expected_digest)
        ):
            raise ValueError("Recorded source digest is invalid")
        path = root / filename
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FEED_BYTES:
            actual_length = None
            actual_digest = None
        else:
            actual_length = path.stat().st_size
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(128 * 1024), b""):
                    digest.update(chunk)
            actual_digest = digest.hexdigest()
        checked_feeds.append(
            {
                "source_key": feed.get("source_key"),
                "data_kind": feed.get("data_kind"),
                "publisher": feed.get("publisher"),
                "filename": filename,
                "byte_length": expected_length,
                "sha256": expected_digest,
                "response_completed_at_utc": feed.get("transport", {}).get(
                    "response_completed_at_utc"
                )
                if isinstance(feed.get("transport"), dict)
                else None,
                "requested_url": feed.get("transport", {}).get("requested_url")
                if isinstance(feed.get("transport"), dict)
                else None,
                "checksum_valid": expected_length == actual_length
                and expected_digest == actual_digest,
            }
        )
    classification = manifest.get("evidence_classification")
    if (
        not isinstance(classification, dict)
        or classification.get("operational_authority") != "NONE"
    ):
        raise ValueError("Recorded source classification is unsupported")
    return {
        "schema_version": manifest["schema_version"],
        "capture_completed_at_utc": manifest.get("capture_completed_at_utc"),
        "source_catalog": manifest.get("source_catalog"),
        "evidence_classification": classification,
        "limitations": manifest.get("limitations"),
        "manifest_checksum_valid": manifest_checksum_valid,
        "content_checksums_valid": manifest_checksum_valid
        and all(feed["checksum_valid"] for feed in checked_feeds),
        "feeds": checked_feeds,
    }
