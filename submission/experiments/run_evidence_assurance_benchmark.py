#!/usr/bin/env python3
"""Run a deterministic, paired benchmark of evidence-admission policies.

The cases in this program are controlled software-test fixtures. The optional
SNCF snapshot contributes real publisher bytes and a reproducible source
receipt, but it does not turn these mutations into real incidents or confer
railway operational authority.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import random
import statistics
import sys
import time
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterable
from uuid import UUID, uuid4


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.models.provenance import (  # noqa: E402
    LineageEdge,
    ProvenanceRecord,
    RouteDecisionSnapshot,
)
from app.services.evidence_gate import (  # noqa: E402
    DecisionState,
    REQUIRED_DECISION_ROLES,
    assess_decision_evidence,
)
from app.services.provenance import (  # noqa: E402
    SOURCE_IDS,
    record_integrity_payload,
    seal_decision_evidence,
    snapshot_integrity_payload,
    stable_checksum,
)


EXPERIMENT_VERSION = "EVIDENCE_ASSURANCE_BENCHMARK_V1"
RUN_SCHEMA_VERSION = "clearpath.experiment-run.v1"
SOURCE_SCHEMA_VERSION = "clearpath.external-source-snapshot.v1"
DEFAULT_SEED = 20260915
DEFAULT_CASES = 2400
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_REFERENCED_SOURCE_BYTES = 200 * 1024 * 1024
CHUNK_BYTES = 128 * 1024
EXPECTED_SOURCE_KEYS = {
    "sncf_gtfs_static",
    "sncf_gtfs_rt_trip_updates",
    "sncf_gtfs_rt_service_alerts",
}
MUTATIONS = (
    "missing_direct_role",
    "wrong_context",
    "unknown_source",
    "source_type_impersonation",
    "empty_payload",
    "malformed_payload",
    "missing_lineage",
    "lineage_cycle",
    "broken_lineage",
    "future_timestamp",
    "stale_live_observation",
    "expired_import",
    "excluded_ancestor",
    "snapshot_score_conflict",
    "role_conflict",
    "incomplete_payload",
    "unavailable_record",
    "payload_tamper_after_seal",
    "root_signature_tamper_after_seal",
)
CLASSIFIER_NAMES = (
    "b0_latest_value",
    "b1_checksum_timestamp",
    "full_evidence_gate",
)
CSV_FIELDS = (
    "case_id",
    "case_fingerprint_sha256",
    "data_class",
    "fault_type",
    "expected_admissible",
    "b0_latest_value",
    "b0_latest_value_latency_ms",
    "b1_checksum_timestamp",
    "b1_checksum_timestamp_latency_ms",
    "full_evidence_gate",
    "full_evidence_gate_latency_ms",
    "full_reason_codes",
    "source_snapshot_manifest_sha256",
)


@dataclass
class EvidenceBundle:
    snapshot: RouteDecisionSnapshot
    records: list[ProvenanceRecord]
    edges: list[LineageEdge]
    now: datetime
    sources_by_id: dict[UUID, Any]


@dataclass(frozen=True)
class SourceSnapshot:
    manifest_path: Path
    file_sha256: str
    payload_sha256: str
    classification: dict[str, Any]
    feeds: list[dict[str, Any]]


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sha256_file(path: Path, *, maximum_bytes: int | None = None) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            total += len(chunk)
            if maximum_bytes is not None and total > maximum_bytes:
                raise ValueError(f"{path} exceeds the permitted size of {maximum_bytes} bytes")
            digest.update(chunk)
    return digest.hexdigest(), total


def _load_json_object(path: Path, *, maximum_bytes: int) -> dict[str, Any]:
    raw = path.read_bytes()
    if not raw or len(raw) > maximum_bytes:
        raise ValueError(f"Manifest size must be within 1..{maximum_bytes} bytes")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid UTF-8 JSON manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("Manifest root must be a JSON object")
    return value


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _valid_https_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urllib.parse.urlsplit(value)
    return (
        parsed.scheme.lower() == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )


def verify_source_manifest(path: Path) -> SourceSnapshot:
    """Verify manifest self-digest and every referenced response byte."""

    path = path.resolve(strict=True)
    manifest = _load_json_object(path, maximum_bytes=MAX_MANIFEST_BYTES)
    if manifest.get("schema_version") != SOURCE_SCHEMA_VERSION:
        raise ValueError("Unsupported source-manifest schema_version")
    declared_payload_digest = manifest.get("manifest_payload_sha256")
    if not _valid_digest(declared_payload_digest):
        raise ValueError("Source manifest has no valid payload digest")
    payload = dict(manifest)
    payload.pop("manifest_payload_sha256", None)
    actual_payload_digest = canonical_sha256(payload)
    if actual_payload_digest != declared_payload_digest:
        raise ValueError("Source manifest payload digest mismatch")

    classification = manifest.get("evidence_classification")
    if not isinstance(classification, dict):
        raise ValueError("Source manifest lacks evidence_classification")
    if classification.get("records") != "REAL_PUBLISHER_BYTES":
        raise ValueError("Source manifest is not classified as REAL_PUBLISHER_BYTES")
    expected_classification = {
        "incident_labels": "NONE",
        "operational_authority": "NONE",
        "intended_use": "RESEARCH_REPRODUCIBILITY_ONLY",
    }
    if any(classification.get(key) != value for key, value in expected_classification.items()):
        raise ValueError("Unexpected incident, authority, or intended-use classification")

    source_catalog = manifest.get("source_catalog")
    if not isinstance(source_catalog, dict):
        raise ValueError("Source manifest lacks source_catalog")
    if source_catalog.get("publisher") != "SNCF Voyageurs":
        raise ValueError("Unexpected source publisher")
    if source_catalog.get("license") != "Open Database License (ODbL) 1.0":
        raise ValueError("Unexpected or missing source licence")
    if not all(
        _valid_https_url(source_catalog.get(key))
        for key in ("dataset_page", "license_url", "special_terms_url")
    ):
        raise ValueError("Source catalogue URLs must be absolute HTTPS URLs")

    feeds = manifest.get("feeds")
    if not isinstance(feeds, list) or not feeds:
        raise ValueError("Source manifest must contain at least one feed")
    seen_keys: set[str] = set()
    seen_files: set[str] = set()
    verified_feeds: list[dict[str, Any]] = []
    for feed in feeds:
        if not isinstance(feed, dict):
            raise ValueError("Each source feed must be a JSON object")
        source_key = feed.get("source_key")
        filename = feed.get("local_filename")
        declared_digest = feed.get("sha256")
        declared_length = feed.get("byte_length")
        if not isinstance(source_key, str) or not source_key:
            raise ValueError("A source feed has no source_key")
        if source_key in seen_keys:
            raise ValueError(f"Duplicate source_key {source_key!r}")
        seen_keys.add(source_key)
        if (
            not isinstance(filename, str)
            or not filename
            or filename != Path(filename).name
            or "/" in filename
            or "\\" in filename
            or filename in {".", ".."}
            or filename in seen_files
        ):
            raise ValueError(f"Unsafe or duplicate source filename {filename!r}")
        seen_files.add(filename)
        if not _valid_digest(declared_digest):
            raise ValueError(f"Invalid digest for {source_key}")
        if not isinstance(declared_length, int) or declared_length <= 0:
            raise ValueError(f"Invalid byte_length for {source_key}")
        transport = feed.get("transport")
        if not isinstance(transport, dict) or transport.get("http_status") != 200:
            raise ValueError(f"Missing successful HTTP receipt for {source_key}")
        if not all(
            _valid_https_url(transport.get(key)) for key in ("requested_url", "final_url")
        ):
            raise ValueError(f"Invalid transport URL for {source_key}")
        source_path = (path.parent / filename).resolve(strict=True)
        if source_path.parent != path.parent:
            raise ValueError(f"Source file escapes snapshot directory: {filename}")
        actual_digest, actual_length = sha256_file(
            source_path,
            maximum_bytes=MAX_REFERENCED_SOURCE_BYTES,
        )
        if actual_length != declared_length or actual_digest != declared_digest:
            raise ValueError(f"Source byte verification failed for {source_key}")
        verified_feeds.append(
            {
                "source_key": source_key,
                "sha256": actual_digest,
                "byte_length": actual_length,
            }
        )

    if seen_keys != EXPECTED_SOURCE_KEYS:
        missing = sorted(EXPECTED_SOURCE_KEYS - seen_keys)
        unexpected = sorted(seen_keys - EXPECTED_SOURCE_KEYS)
        raise ValueError(
            f"SNCF snapshot feed set mismatch; missing={missing}, unexpected={unexpected}"
        )

    file_digest, _ = sha256_file(path, maximum_bytes=MAX_MANIFEST_BYTES)
    return SourceSnapshot(
        manifest_path=path,
        file_sha256=file_digest,
        payload_sha256=actual_payload_digest,
        classification=classification,
        feeds=verified_feeds,
    )


def deterministic_uuid(rng: random.Random) -> UUID:
    return UUID(int=rng.getrandbits(128), version=4)


def make_record(
    *,
    rng: random.Random,
    snapshot: RouteDecisionSnapshot,
    now: datetime,
    role: str | None,
    source_key: str,
    source_type: str,
    entity_type: str,
    value: dict[str, Any],
    freshness: str = "NOT_APPLICABLE",
    availability: str = "AVAILABLE",
    observed_at: datetime | None = None,
    valid_until: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> ProvenanceRecord:
    if observed_at is None and source_type in {
        "LIVE_PROVIDER",
        "CACHED_PROVIDER",
        "OPERATOR_INPUT",
        "IMPORTED_DOCUMENT",
    }:
        observed_at = now
    return ProvenanceRecord(
        id=deterministic_uuid(rng),
        user_id=snapshot.user_id,
        route_id=snapshot.route_id,
        decision_snapshot_id=snapshot.id,
        source_id=SOURCE_IDS[source_key],
        entity_type=entity_type,
        entity_key=f"{entity_type.casefold()}:{rng.getrandbits(48):012x}",
        decision_input_role=role,
        canonical_source_type=source_type,
        raw_source_state=source_type,
        observed_at=observed_at,
        fetched_at=now,
        valid_until=valid_until,
        freshness_state=freshness,
        freshness_seconds=0 if freshness == "FRESH" else None,
        cache_hit=False,
        used_in_decision=True,
        excluded_reason=None,
        availability_state=availability,
        confidence=1.0,
        completeness=1.0,
        transform_name="benchmark_fixture",
        transform_version=EXPERIMENT_VERSION,
        formula_reference="CONTROLLED_TEST_ONLY",
        request_id=snapshot.request_id,
        checksum=stable_checksum(value),
        integrity_checksum=None,
        value_summary=value,
        metadata_json=metadata or {},
        created_at=now,
    )


def build_clean_bundle(rng: random.Random, case_index: int) -> EvidenceBundle:
    base = datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc)
    now = base + timedelta(seconds=rng.randint(0, 86_399), microseconds=case_index)
    route_id = deterministic_uuid(rng)
    snapshot_id = deterministic_uuid(rng)
    source_code = rng.choice(("AAA", "BBB", "CCC", "DDD"))
    destination_code = rng.choice(("EEE", "FFF", "GGG", "HHH"))
    if destination_code == source_code:
        destination_code = "ZZZ"
    segment_id = f"segment-{rng.getrandbits(48):012x}"
    height = round(rng.uniform(2.0, 4.2), 3)
    width = round(rng.uniform(1.8, 3.2), 3)
    weight = round(rng.uniform(20.0, 70.0), 3)
    scores = {
        "weather": rng.randint(55, 94),
        "port": rng.randint(55, 94),
        "congestion": rng.randint(55, 94),
        "historical": rng.randint(55, 94),
    }
    snapshot = RouteDecisionSnapshot(
        id=snapshot_id,
        route_id=route_id,
        user_id=f"benchmark-owner-{case_index:05d}",
        request_id=f"benchmark-request-{case_index:05d}-{rng.getrandbits(32):08x}",
        decision_engine_version="7.0.0-research",
        routing_algorithm_version="CONTROLLED_FIXTURE_V1",
        scoring_version="CONTROLLED_FIXTURE_V1",
        clearance_engine_version="EVIDENCE_ONLY_V2",
        source_code=source_code,
        destination_code=destination_code,
        cargo_request={"height": height, "width": width, "weight": weight},
        route_segment_ids=[segment_id],
        clearance_state="APPROVED",
        blocking_segment_id=None,
        reliability_score=round(statistics.fmean(scores.values())),
        estimated_hours=round(rng.uniform(3.0, 36.0), 2),
        score_breakdown=scores,
        applied_weights={
            "weather": 0.4,
            "port": 0.3,
            "congestion": 0.15,
            "historical": 0.15,
        },
        excluded_factors=[],
        environmental_alerts=[],
        traceability_summary={"classification": "CONTROLLED_TEST_FIXTURE"},
        final_response_summary={"operational_authority": "NONE"},
        evidence_root_checksum=None,
        evidence_root_signature=None,
        evidence_root_key_id=None,
        evidence_root_algorithm=None,
        created_at=now,
    )

    clearance = make_record(
        rng=rng,
        snapshot=snapshot,
        now=now,
        role="CLEARANCE_DECISION",
        source_key="clearpath_derived",
        source_type="DERIVED",
        entity_type="CLEARANCE_RESULT",
        value={"status": "APPROVED", "blocking_segment_id": None},
    )
    weather = make_record(
        rng=rng,
        snapshot=snapshot,
        now=now,
        role="WEATHER",
        source_key="clearpath_derived",
        source_type="DERIVED",
        entity_type="WEATHER_SCORE",
        value={"score": scores["weather"], "provider_unavailable": False, "weight": 0.4},
    )
    port = make_record(
        rng=rng,
        snapshot=snapshot,
        now=now,
        role="PORT_ALIGNMENT",
        source_key="maritime_feed",
        source_type="LIVE_PROVIDER",
        entity_type="PORT_ALIGNMENT_SCORE",
        freshness="FRESH",
        observed_at=now - timedelta(seconds=rng.randint(0, 120)),
        valid_until=now + timedelta(hours=2),
        value={
            "score": scores["port"],
            "available": True,
            "aligned": True,
            "port_id": f"PORT-{rng.getrandbits(24):06x}",
            "vessel_id": f"VESSEL-{rng.getrandbits(28):07x}",
            "evaluated_at": now.isoformat(),
            "train_arrival_hours": round(rng.uniform(3, 30), 2),
            "loading_window": {
                "start": (now + timedelta(hours=1)).isoformat(),
                "end": (now + timedelta(hours=2)).isoformat(),
            },
        },
    )
    congestion = make_record(
        rng=rng,
        snapshot=snapshot,
        now=now,
        role="CONGESTION",
        source_key="clearpath_derived",
        source_type="DERIVED",
        entity_type="CONGESTION_SCORE",
        value={
            "score": scores["congestion"],
            "static_score": scores["congestion"],
            "live_weight": 0.0,
        },
    )
    historical = make_record(
        rng=rng,
        snapshot=snapshot,
        now=now,
        role="HISTORICAL_DELAY",
        source_key="clearpath_derived",
        source_type="DERIVED",
        entity_type="HISTORICAL_DELAY_SCORE",
        value={
            "score": scores["historical"],
            "segment_delay_hours": [round(rng.uniform(0.1, 4.0), 3)],
            "weight": 0.15,
        },
    )
    cargo = make_record(
        rng=rng,
        snapshot=snapshot,
        now=now,
        role=None,
        source_key="operator_input",
        source_type="OPERATOR_INPUT",
        entity_type="CARGO_DECLARATION",
        value={"height": height, "width": width, "weight": weight},
    )
    engineering = make_record(
        rng=rng,
        snapshot=snapshot,
        now=now,
        role=None,
        source_key="imported_engineering",
        source_type="IMPORTED_DOCUMENT",
        entity_type="ENGINEERING_LIMITS",
        metadata={
            "verified": True,
            "signature_verified": True,
            "issuer_authentication": "DETACHED_SIGNATURE",
            "classification": "CONTROLLED_TEST_FIXTURE",
        },
        value={
            "certification": "VERIFIED",
            "segments": [
                {
                    "id": segment_id,
                    "source_code": source_code,
                    "destination_code": destination_code,
                    "max_height": height + 1.0,
                    "max_width": width + 1.0,
                    "max_weight": weight + 50.0,
                    "source_reference": "benchmark.invalid/controlled-authority-fixture",
                    "certified_by": "Controlled benchmark fixture — not an authority",
                    "certified_at": now.isoformat(),
                    "verified": True,
                    "declared_checksum": "a" * 64,
                    "computed_checksum": "a" * 64,
                }
            ],
        },
    )
    weather_observation = make_record(
        rng=rng,
        snapshot=snapshot,
        now=now,
        role=None,
        source_key="open_meteo",
        source_type="LIVE_PROVIDER",
        entity_type="WEATHER_OBSERVATION",
        freshness="FRESH",
        observed_at=now - timedelta(seconds=rng.randint(0, 120)),
        value={
            "weather": [{"id": rng.choice((500, 600, 800))}],
            "wind": {"speed": round(rng.uniform(0.0, 15.0), 2)},
            "main": {"visibility": rng.randint(2_000, 20_000)},
        },
    )
    congestion_baseline = make_record(
        rng=rng,
        snapshot=snapshot,
        now=now,
        role=None,
        source_key="imported_engineering",
        source_type="IMPORTED_DOCUMENT",
        entity_type="CONGESTION_BASELINE",
        value={"score": scores["congestion"], "segment_factors": [1.0]},
    )
    records = [
        clearance,
        weather,
        port,
        congestion,
        historical,
        cargo,
        engineering,
        weather_observation,
        congestion_baseline,
    ]
    edges = [
        LineageEdge(
            id=deterministic_uuid(rng),
            parent_record_id=cargo.id,
            child_record_id=clearance.id,
            relationship="INPUT_TO",
            created_at=now,
        ),
        LineageEdge(
            id=deterministic_uuid(rng),
            parent_record_id=engineering.id,
            child_record_id=clearance.id,
            relationship="VALIDATES",
            created_at=now,
        ),
        LineageEdge(
            id=deterministic_uuid(rng),
            parent_record_id=weather_observation.id,
            child_record_id=weather.id,
            relationship="DERIVED_FROM",
            created_at=now,
        ),
        LineageEdge(
            id=deterministic_uuid(rng),
            parent_record_id=congestion_baseline.id,
            child_record_id=congestion.id,
            relationship="DERIVED_FROM",
            created_at=now,
        ),
        LineageEdge(
            id=deterministic_uuid(rng),
            parent_record_id=engineering.id,
            child_record_id=historical.id,
            relationship="DERIVED_FROM",
            created_at=now,
        ),
    ]
    sources_by_id = {
        source_id: SimpleNamespace(key=source_key, enabled=True)
        for source_key, source_id in SOURCE_IDS.items()
    }
    return EvidenceBundle(snapshot, records, edges, now, sources_by_id)


def direct_for(bundle: EvidenceBundle, role: str) -> ProvenanceRecord:
    return next(record for record in bundle.records if record.decision_input_role == role)


def entity_for(bundle: EvidenceBundle, entity_type: str) -> ProvenanceRecord:
    return next(record for record in bundle.records if record.entity_type == entity_type)


def refresh_value_checksum(record: ProvenanceRecord) -> None:
    record.checksum = stable_checksum(record.value_summary)


def apply_mutation(bundle: EvidenceBundle, fault: str, rng: random.Random) -> None:
    if fault == "none":
        return
    if fault == "missing_direct_role":
        target = direct_for(bundle, "HISTORICAL_DELAY")
        bundle.records.remove(target)
        bundle.edges = [edge for edge in bundle.edges if edge.child_record_id != target.id]
    elif fault == "wrong_context":
        direct_for(bundle, "CLEARANCE_DECISION").route_id = deterministic_uuid(rng)
    elif fault == "unknown_source":
        direct_for(bundle, "PORT_ALIGNMENT").source_id = deterministic_uuid(rng)
    elif fault == "source_type_impersonation":
        target = direct_for(bundle, "PORT_ALIGNMENT")
        target.source_id = SOURCE_IDS["operator_input"]
        target.canonical_source_type = "OPERATOR_INPUT"
        target.raw_source_state = "OPERATOR_INPUT"
    elif fault == "empty_payload":
        target = direct_for(bundle, "HISTORICAL_DELAY")
        target.value_summary = {}
        refresh_value_checksum(target)
    elif fault == "malformed_payload":
        target = direct_for(bundle, "WEATHER")
        target.value_summary = {"garbage": f"controlled-{rng.getrandbits(32):08x}"}
        refresh_value_checksum(target)
    elif fault == "missing_lineage":
        target = direct_for(bundle, "WEATHER")
        bundle.edges = [edge for edge in bundle.edges if edge.child_record_id != target.id]
    elif fault == "lineage_cycle":
        parent = entity_for(bundle, "WEATHER_OBSERVATION")
        child = direct_for(bundle, "WEATHER")
        bundle.edges.append(
            LineageEdge(
                id=deterministic_uuid(rng),
                parent_record_id=child.id,
                child_record_id=parent.id,
                relationship="DERIVED_FROM",
                created_at=bundle.now,
            )
        )
    elif fault == "broken_lineage":
        bundle.edges.append(
            LineageEdge(
                id=deterministic_uuid(rng),
                parent_record_id=deterministic_uuid(rng),
                child_record_id=direct_for(bundle, "WEATHER").id,
                relationship="DERIVED_FROM",
                created_at=bundle.now,
            )
        )
    elif fault == "future_timestamp":
        target = entity_for(bundle, "WEATHER_OBSERVATION")
        target.observed_at = bundle.now + timedelta(hours=1)
        target.fetched_at = bundle.now + timedelta(hours=1)
        target.freshness_state = "UNKNOWN"
    elif fault == "stale_live_observation":
        target = entity_for(bundle, "WEATHER_OBSERVATION")
        target.observed_at = bundle.now - timedelta(hours=3)
        target.freshness_state = "STALE"
        target.freshness_seconds = 10_800
    elif fault == "expired_import":
        target = entity_for(bundle, "ENGINEERING_LIMITS")
        target.observed_at = bundle.now - timedelta(days=400)
        target.valid_until = None
    elif fault == "excluded_ancestor":
        target = entity_for(bundle, "ENGINEERING_LIMITS")
        target.used_in_decision = False
        target.excluded_reason = "CONTROLLED_TEST_MUTATION"
    elif fault == "snapshot_score_conflict":
        target = direct_for(bundle, "WEATHER")
        target.value_summary = dict(target.value_summary)
        target.value_summary["score"] = (int(target.value_summary["score"]) + 1) % 101
        refresh_value_checksum(target)
    elif fault == "role_conflict":
        original = direct_for(bundle, "WEATHER")
        duplicate = make_record(
            rng=rng,
            snapshot=bundle.snapshot,
            now=bundle.now,
            role="WEATHER",
            source_key="clearpath_derived",
            source_type="DERIVED",
            entity_type="WEATHER_SCORE",
            value=dict(original.value_summary),
        )
        bundle.records.append(duplicate)
        bundle.edges.append(
            LineageEdge(
                id=deterministic_uuid(rng),
                parent_record_id=entity_for(bundle, "WEATHER_OBSERVATION").id,
                child_record_id=duplicate.id,
                relationship="DERIVED_FROM",
                created_at=bundle.now,
            )
        )
    elif fault == "incomplete_payload":
        direct_for(bundle, "CONGESTION").completeness = 0.5
    elif fault == "unavailable_record":
        target = entity_for(bundle, "WEATHER_OBSERVATION")
        target.canonical_source_type = "UNAVAILABLE"
        target.raw_source_state = "UNAVAILABLE"
        target.availability_state = "UNAVAILABLE"
        target.freshness_state = "UNKNOWN"
    elif fault in {"payload_tamper_after_seal", "root_signature_tamper_after_seal"}:
        return
    else:
        raise ValueError(f"Unknown controlled mutation: {fault}")


def seal_and_optionally_tamper(bundle: EvidenceBundle, fault: str) -> None:
    seal_decision_evidence(bundle.snapshot, bundle.records, bundle.edges)
    if fault == "payload_tamper_after_seal":
        target = direct_for(bundle, "WEATHER")
        target.value_summary = dict(target.value_summary)
        target.value_summary["score"] = (int(target.value_summary["score"]) + 7) % 101
    elif fault == "root_signature_tamper_after_seal":
        signature = bundle.snapshot.evidence_root_signature or ""
        bundle.snapshot.evidence_root_signature = ("0" if signature[:1] != "0" else "1") + signature[1:]


def b0_latest_value(bundle: EvidenceBundle) -> bool:
    """Naive comparator: one explicit approval and any value for each role."""

    by_role = {
        role: [record for record in bundle.records if record.decision_input_role == role]
        for role in REQUIRED_DECISION_ROLES
    }
    if any(not records for records in by_role.values()):
        return False
    latest = {
        role: max(records, key=lambda record: (record.fetched_at, str(record.id)))
        for role, records in by_role.items()
    }
    clearance = latest["CLEARANCE_DECISION"]
    return clearance.value_summary.get("status") == "APPROVED" and all(
        bool(record.value_summary) for record in latest.values()
    )


def _aware(value: datetime | None) -> bool:
    return bool(value is not None and value.tzinfo is not None and value.utcoffset() is not None)


def b1_checksum_timestamp(bundle: EvidenceBundle) -> bool:
    """Checksum/time comparator that intentionally omits semantics and lineage."""

    if not b0_latest_value(bundle):
        return False
    for record in bundle.records:
        if not record.checksum or stable_checksum(record.value_summary) != record.checksum:
            return False
        if float(record.completeness or 0) < 1.0:
            return False
        if record.availability_state != "AVAILABLE":
            return False
        if record.freshness_state in {"STALE", "UNKNOWN"}:
            return False
        if not _aware(record.fetched_at) or record.fetched_at > bundle.now + timedelta(minutes=5):
            return False
        if record.observed_at is not None:
            if not _aware(record.observed_at):
                return False
            if record.observed_at > bundle.now + timedelta(minutes=5):
                return False
        if record.valid_until is not None:
            if not _aware(record.valid_until) or record.valid_until < bundle.now:
                return False
        if record.canonical_source_type == "IMPORTED_DOCUMENT" and record.observed_at:
            if bundle.now - record.observed_at > timedelta(days=366):
                return False
    return True


def full_evidence_gate(bundle: EvidenceBundle) -> tuple[bool, tuple[str, ...]]:
    assessment = assess_decision_evidence(
        bundle.snapshot,
        bundle.records,
        bundle.edges,
        now=bundle.now,
        sources_by_id=bundle.sources_by_id,
    )
    return assessment.decision_state is DecisionState.READY, assessment.reason_codes


def timed(call: Callable[[], Any]) -> tuple[Any, float]:
    started = time.perf_counter_ns()
    result = call()
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    return result, elapsed_ms


def bundle_fingerprint(case_id: str, fault: str, bundle: EvidenceBundle) -> str:
    return canonical_sha256(
        {
            "case_id": case_id,
            "fault_type": fault,
            "snapshot": snapshot_integrity_payload(bundle.snapshot),
            "records": [
                record_integrity_payload(record)
                for record in sorted(bundle.records, key=lambda item: str(item.id))
            ],
            "edges": [
                {
                    "parent": edge.parent_record_id,
                    "child": edge.child_record_id,
                    "relationship": edge.relationship,
                }
                for edge in sorted(
                    bundle.edges,
                    key=lambda item: (
                        str(item.parent_record_id),
                        str(item.child_record_id),
                        item.relationship,
                    ),
                )
            ],
            "stored_root": bundle.snapshot.evidence_root_checksum,
            "stored_signature": bundle.snapshot.evidence_root_signature,
        }
    )


def make_fault_plan(case_count: int, rng: random.Random) -> list[str]:
    plan: list[str] = []
    if case_count >= len(MUTATIONS) + 1:
        plan.extend(("none", *MUTATIONS))
    while len(plan) < case_count:
        plan.append("none" if rng.random() < 0.2 else rng.choice(MUTATIONS))
    rng.shuffle(plan)
    return plan[:case_count]


def confusion(rows: Iterable[dict[str, Any]], classifier: str) -> dict[str, int]:
    result = {"tp": 0, "tn": 0, "fp": 0, "fn": 0}
    for row in rows:
        expected = bool(row["expected_admissible"])
        predicted = bool(row[classifier])
        if expected and predicted:
            result["tp"] += 1
        elif not expected and not predicted:
            result["tn"] += 1
        elif not expected and predicted:
            result["fp"] += 1
        else:
            result["fn"] += 1
    return result


def wilson_interval(successes: int, trials: int, z: float = 1.959963984540054) -> list[float]:
    if trials <= 0:
        return [0.0, 0.0]
    proportion = successes / trials
    denominator = 1 + z * z / trials
    centre = (proportion + z * z / (2 * trials)) / denominator
    half = z * math.sqrt(
        proportion * (1 - proportion) / trials + z * z / (4 * trials * trials)
    ) / denominator
    return [round(max(0.0, centre - half), 6), round(min(1.0, centre + half), 6)]


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def classifier_metrics(rows: list[dict[str, Any]], classifier: str) -> dict[str, Any]:
    matrix = confusion(rows, classifier)
    positives = matrix["tp"] + matrix["fn"]
    negatives = matrix["tn"] + matrix["fp"]
    sensitivity = matrix["tp"] / positives if positives else 0.0
    specificity = matrix["tn"] / negatives if negatives else 0.0
    false_admission = matrix["fp"] / negatives if negatives else 0.0
    false_hold = matrix["fn"] / positives if positives else 0.0
    denominator = math.sqrt(
        (matrix["tp"] + matrix["fp"])
        * (matrix["tp"] + matrix["fn"])
        * (matrix["tn"] + matrix["fp"])
        * (matrix["tn"] + matrix["fn"])
    )
    mcc = (
        (matrix["tp"] * matrix["tn"] - matrix["fp"] * matrix["fn"]) / denominator
        if denominator
        else 0.0
    )
    latencies = [float(row[f"{classifier}_latency_ms"]) for row in rows]
    return {
        "confusion_matrix": matrix,
        "false_admission_rate": round(false_admission, 6),
        "false_admission_rate_wilson_95": wilson_interval(matrix["fp"], negatives),
        "false_hold_rate": round(false_hold, 6),
        "false_hold_rate_wilson_95": wilson_interval(matrix["fn"], positives),
        "balanced_accuracy": round((sensitivity + specificity) / 2, 6),
        "matthews_correlation_coefficient": round(mcc, 6),
        "latency_ms": {
            "median": round(percentile(latencies, 0.50), 4),
            "p95": round(percentile(latencies, 0.95), 4),
            "p99": round(percentile(latencies, 0.99), 4),
        },
    }


def exact_mcnemar(
    rows: list[dict[str, Any]], left: str, right: str
) -> dict[str, Any]:
    left_only = 0
    right_only = 0
    for row in rows:
        expected = bool(row["expected_admissible"])
        left_correct = bool(row[left]) == expected
        right_correct = bool(row[right]) == expected
        left_only += int(left_correct and not right_correct)
        right_only += int(right_correct and not left_correct)
    discordant = left_only + right_only
    if discordant == 0:
        p_value = 1.0
        log10_p = 0.0
    else:
        tail = min(left_only, right_only)
        numerator = 2 * sum(math.comb(discordant, index) for index in range(tail + 1))
        denominator = 1 << discordant
        if numerator >= denominator:
            p_value = 1.0
            log10_p = 0.0
        else:
            log10_p = math.log10(numerator) - discordant * math.log10(2)
            p_value = 10**log10_p if log10_p > -324 else 0.0
    return {
        "left_only_correct": left_only,
        "right_only_correct": right_only,
        "discordant_pairs": discordant,
        "two_sided_exact_p": round(p_value, 12),
        "log10_p": round(log10_p, 6),
    }


def holm_adjust(comparisons: dict[str, dict[str, Any]]) -> dict[str, float]:
    ordered = sorted(
        comparisons.items(),
        key=lambda item: float(item[1]["two_sided_exact_p"]),
    )
    adjusted: dict[str, float] = {}
    running = 0.0
    count = len(ordered)
    for rank, (name, result) in enumerate(ordered):
        candidate = min(1.0, (count - rank) * float(result["two_sided_exact_p"]))
        running = max(running, candidate)
        adjusted[name] = round(running, 12)
    return adjusted


def per_fault_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["fault_type"])].append(row)
    result: dict[str, Any] = {}
    for fault, fault_rows in grouped.items():
        reason_counts: Counter[str] = Counter()
        for row in fault_rows:
            reason_counts.update(filter(None, str(row["full_reason_codes"]).split("|")))
        result[fault] = {
            "cases": len(fault_rows),
            "admitted": {
                classifier: sum(bool(row[classifier]) for row in fault_rows)
                for classifier in CLASSIFIER_NAMES
            },
            "full_gate_reason_codes": dict(sorted(reason_counts.items())),
        }
    return result


def _new_output_dir(requested: Path | None) -> Path:
    if requested is not None:
        candidate = requested.resolve()
        candidate.mkdir(parents=True, exist_ok=False)
        return candidate
    runs = Path(__file__).resolve().parent / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        candidate = runs / f"{stamp}_evidence_assurance_{uuid4().hex[:8]}"
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise FileExistsError("Could not allocate a unique benchmark run directory")


def write_json_exclusive(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=False, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def write_csv_exclusive(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())


def run_benchmark(args: argparse.Namespace) -> tuple[Path, int]:
    source_snapshot = verify_source_manifest(args.source_manifest)

    # A deterministic, experiment-only key lets the real backend sealing and
    # verification code run without using or recording a deployment secret.
    settings.EVIDENCE_SIGNING_KEY_ID = "benchmark-ephemeral-v1"
    settings.EVIDENCE_SIGNING_KEY = hashlib.sha256(
        f"{EXPERIMENT_VERSION}:{args.seed}:controlled-test-only".encode("utf-8")
    ).hexdigest()
    settings.EVIDENCE_VERIFICATION_KEYS = {}

    rng = random.Random(args.seed)
    plan = make_fault_plan(args.cases, rng)
    rows: list[dict[str, Any]] = []
    fingerprints: set[str] = set()
    policy_errors: list[dict[str, Any]] = []
    for case_index, fault in enumerate(plan):
        case_id = f"case-{case_index:05d}"
        bundle = build_clean_bundle(rng, case_index)
        apply_mutation(bundle, fault, rng)
        seal_and_optionally_tamper(bundle, fault)
        fingerprint = bundle_fingerprint(case_id, fault, bundle)
        if fingerprint in fingerprints:
            raise RuntimeError(f"Duplicate case fingerprint generated for {case_id}")
        fingerprints.add(fingerprint)
        expected = fault == "none"

        b0_result, b0_latency = timed(lambda: b0_latest_value(bundle))
        b1_result, b1_latency = timed(lambda: b1_checksum_timestamp(bundle))
        try:
            full_result, full_latency = timed(lambda: full_evidence_gate(bundle))
            full_admitted, reason_codes = full_result
        except Exception as exc:  # continue to preserve a diagnostic artifact
            full_admitted = False
            reason_codes = (f"POLICY_EXCEPTION:{type(exc).__name__}",)
            full_latency = 0.0
            policy_errors.append(
                {"case_id": case_id, "fault_type": fault, "error": repr(exc)}
            )
        if full_admitted != expected:
            policy_errors.append(
                {
                    "case_id": case_id,
                    "fault_type": fault,
                    "expected_admissible": expected,
                    "actual_admissible": full_admitted,
                    "reason_codes": list(reason_codes),
                }
            )
        rows.append(
            {
                "case_id": case_id,
                "case_fingerprint_sha256": fingerprint,
                "data_class": (
                    "CLEAN_TEST_FIXTURE" if expected else "CONTROLLED_TEST_MUTATION"
                ),
                "fault_type": fault,
                "expected_admissible": expected,
                "b0_latest_value": bool(b0_result),
                "b0_latest_value_latency_ms": round(b0_latency, 4),
                "b1_checksum_timestamp": bool(b1_result),
                "b1_checksum_timestamp_latency_ms": round(b1_latency, 4),
                "full_evidence_gate": bool(full_admitted),
                "full_evidence_gate_latency_ms": round(full_latency, 4),
                "full_reason_codes": "|".join(reason_codes),
                "source_snapshot_manifest_sha256": source_snapshot.file_sha256,
            }
        )

    output_dir = _new_output_dir(args.output_dir)
    csv_path = output_dir / "evidence_assurance_cases.csv"
    write_csv_exclusive(csv_path, rows)
    csv_digest, _ = sha256_file(csv_path)
    comparisons = {
        "b0_vs_full": exact_mcnemar(rows, "b0_latest_value", "full_evidence_gate"),
        "b1_vs_full": exact_mcnemar(rows, "b1_checksum_timestamp", "full_evidence_gate"),
        "b0_vs_b1": exact_mcnemar(rows, "b0_latest_value", "b1_checksum_timestamp"),
    }
    adjusted = holm_adjust(comparisons)
    for name, value in adjusted.items():
        comparisons[name]["holm_adjusted_p"] = value

    summary: dict[str, Any] = {
        "experiment": "Randomized paired evidence-admissibility benchmark",
        "experiment_version": EXPERIMENT_VERSION,
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "deterministic_seed": args.seed,
        "total_cases": len(rows),
        "unique_case_fingerprints": len(fingerprints),
        "case_classes": dict(sorted(Counter(row["data_class"] for row in rows).items())),
        "fault_distribution": dict(sorted(Counter(row["fault_type"] for row in rows).items())),
        "classifiers": {
            classifier: classifier_metrics(rows, classifier)
            for classifier in CLASSIFIER_NAMES
        },
        "paired_exact_mcnemar": comparisons,
        "per_fault": per_fault_summary(rows),
        "evidence_gate_policy_errors": policy_errors,
        "external_source_snapshot": {
            "manifest_file_sha256": source_snapshot.file_sha256,
            "manifest_payload_sha256": source_snapshot.payload_sha256,
            "classification": source_snapshot.classification,
            "feeds": source_snapshot.feeds,
        },
        "csv_sha256": csv_digest,
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "limitations": [
            "The benchmark tests software admissibility logic, not railway physics or field safety.",
            "Controlled mutations are not real incidents, trains, failures, or accident records.",
            "The clean route bundles are randomized test fixtures, not certified railway inputs.",
            "An attached SNCF snapshot supplies real publisher bytes and provenance only; it does not make the route fixtures real.",
            "SNCF passenger data is not Indian Railways operational data and cannot validate replacement of an existing railway system.",
            "Latency is local-process timing and is not a production capacity or availability claim.",
        ],
    }
    summary_path = output_dir / "evidence_assurance_summary.json"
    write_json_exclusive(summary_path, summary)
    summary_digest, _ = sha256_file(summary_path)

    run_manifest: dict[str, Any] = {
        "schema_version": RUN_SCHEMA_VERSION,
        "experiment_version": EXPERIMENT_VERSION,
        "seed": args.seed,
        "case_count": args.cases,
        "output_files": {
            csv_path.name: csv_digest,
            summary_path.name: summary_digest,
        },
        "source_snapshot_manifest_sha256": source_snapshot.file_sha256,
        "controlled_mutations": list(MUTATIONS),
        "classification_rule": (
            "Only fault_type=none is admissible; every named fault is generated "
            "by the benchmark and labelled CONTROLLED_TEST_MUTATION."
        ),
        "evidence_gate_policy_error_count": len(policy_errors),
    }
    run_manifest["manifest_payload_sha256"] = canonical_sha256(run_manifest)
    manifest_path = output_dir / "evidence_assurance_run_manifest.json"
    write_json_exclusive(manifest_path, run_manifest)
    return manifest_path, (2 if policy_errors else 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=int, default=DEFAULT_CASES)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="New output directory; existing paths are rejected",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cases < 2:
        parser.error("--cases must be at least 2 so both outcome classes can be measured")
    if args.cases > 100_000:
        parser.error("--cases may not exceed 100000")
    try:
        manifest, status = run_benchmark(args)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(manifest)
    if status:
        print("ERROR: EvidenceGate policy errors were recorded; see summary", file=sys.stderr)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
