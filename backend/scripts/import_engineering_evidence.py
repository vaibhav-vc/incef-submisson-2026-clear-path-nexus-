"""Import checksum-verifiable railway engineering evidence from an authorized CSV.

This is an operator action, not an application fallback. Existing segments are
matched by source/destination station code and updated atomically only after
the whole file validates.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from geoalchemy2.elements import WKTElement
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.models.route import LineSegment
from app.services.provenance import engineering_evidence_payload, stable_checksum

REQUIRED_COLUMNS = {
    "source_code",
    "destination_code",
    "max_height",
    "max_width",
    "max_weight",
    "congestion_factor",
    "historical_delay_hours",
    "geometry_lon_lat",
    "source_reference",
    "certified_by",
    "certified_at",
    "source_type",
}
TRUSTED_SOURCE_TYPES = {"OPERATOR_INPUT", "IMPORTED_DOCUMENT"}


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("certified_at must include a timezone")
    return parsed


def _validate_certification(
    certified_by: str,
    certified_at_value: str,
    *,
    now: datetime | None = None,
) -> datetime:
    allowed_issuers = {
        issuer.strip().casefold()
        for issuer in settings.ENGINEERING_CERTIFICATION_ALLOWED_ISSUERS
        if issuer.strip()
    }
    if not allowed_issuers:
        raise ValueError(
            "ENGINEERING_CERTIFICATION_ALLOWED_ISSUERS must explicitly name trusted issuers"
        )
    if certified_by.strip().casefold() not in allowed_issuers:
        raise ValueError("certified_by is not an allowlisted issuer")
    certified_at = _parse_time(certified_at_value)
    if certified_at > (now or datetime.now(timezone.utc)):
        raise ValueError("certified_at cannot be in the future")
    return certified_at


async def import_file(path: Path) -> int:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV missing columns: {', '.join(sorted(missing))}")
        rows = list(reader)
    if not rows:
        raise ValueError("CSV contains no engineering records")

    async with AsyncSessionLocal() as db:
        segments = list(
            (
                await db.scalars(
                    select(LineSegment).options(
                        selectinload(LineSegment.source_station),
                        selectinload(LineSegment.dest_station),
                    )
                )
            ).all()
        )
        by_codes = {
            (item.source_station.code.upper(), item.dest_station.code.upper()): item
            for item in segments
        }
        seen: set[tuple[str, str]] = set()
        for row_number, row in enumerate(rows, start=2):
            key = (row["source_code"].strip().upper(), row["destination_code"].strip().upper())
            if key in seen:
                raise ValueError(f"duplicate segment {key[0]}->{key[1]} at row {row_number}")
            seen.add(key)
            segment = by_codes.get(key)
            if segment is None:
                raise ValueError(f"unknown segment {key[0]}->{key[1]} at row {row_number}")
            source_type = row["source_type"].strip().upper()
            if source_type not in TRUSTED_SOURCE_TYPES:
                raise ValueError(f"untrusted source_type at row {row_number}")
            geometry = json.loads(row["geometry_lon_lat"])
            if not isinstance(geometry, list) or len(geometry) < 2:
                raise ValueError(f"geometry_lon_lat needs at least two points at row {row_number}")
            normalized_geometry = [
                [round(float(point[0]), 7), round(float(point[1]), 7)] for point in geometry
            ]
            payload = {
                "id": str(segment.id),
                "source_code": key[0],
                "destination_code": key[1],
                "max_height": float(row["max_height"]),
                "max_width": float(row["max_width"]),
                "max_weight": float(row["max_weight"]),
                "congestion_factor": float(row["congestion_factor"]),
                "historical_delay_hours": float(row["historical_delay_hours"]),
                "geometry_lon_lat": normalized_geometry,
            }
            if min(payload["max_height"], payload["max_width"], payload["max_weight"]) <= 0:
                raise ValueError(f"clearance values must be positive at row {row_number}")
            reference = row["source_reference"].strip()
            certified_by = row["certified_by"].strip()
            if not reference or not certified_by:
                raise ValueError(f"source_reference and certified_by are required at row {row_number}")
            try:
                certified_at = _validate_certification(
                    certified_by, row["certified_at"].strip()
                )
            except ValueError as exc:
                raise ValueError(f"{exc} at row {row_number}") from exc
            certified_payload = engineering_evidence_payload(
                payload,
                source_type=source_type,
                source_reference=reference,
                certified_by=certified_by,
                certified_at=certified_at,
            )

            segment.max_height_clearance = payload["max_height"]
            segment.max_width_clearance = payload["max_width"]
            segment.max_weight_capacity = payload["max_weight"]
            segment.congestion_factor = payload["congestion_factor"]
            segment.historical_delay_hours = payload["historical_delay_hours"]
            segment.geom_path = WKTElement(
                "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in normalized_geometry) + ")",
                srid=4326,
            )
            segment.engineering_source_type = source_type
            segment.engineering_source_reference = reference
            segment.engineering_certified_by = certified_by
            segment.engineering_certified_at = certified_at
            segment.engineering_checksum = stable_checksum(certified_payload)
        await db.commit()
    return len(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", type=Path)
    args = parser.parse_args()
    imported = asyncio.run(import_file(args.csv_path.resolve()))
    print(json.dumps({"imported_segments": imported, "source": str(args.csv_path.resolve())}))
