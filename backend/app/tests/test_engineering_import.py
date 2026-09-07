from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.services.provenance import engineering_evidence_payload, stable_checksum
from scripts.import_engineering_evidence import _validate_certification


def test_certification_requires_an_explicit_allowlisted_issuer(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENGINEERING_CERTIFICATION_ALLOWED_ISSUERS", [])
    with pytest.raises(ValueError, match="must explicitly name trusted issuers"):
        _validate_certification("claimed issuer", "2026-08-01T00:00:00+00:00")

    monkeypatch.setattr(
        settings, "ENGINEERING_CERTIFICATION_ALLOWED_ISSUERS", ["authorized issuer"]
    )
    with pytest.raises(ValueError, match="not an allowlisted issuer"):
        _validate_certification("claimed issuer", "2026-08-01T00:00:00+00:00")


def test_certification_rejects_a_future_timestamp(monkeypatch) -> None:
    monkeypatch.setattr(
        settings, "ENGINEERING_CERTIFICATION_ALLOWED_ISSUERS", ["authorized issuer"]
    )
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="cannot be in the future"):
        _validate_certification(
            "authorized issuer", (now + timedelta(seconds=1)).isoformat(), now=now
        )


def test_engineering_digest_binds_certification_metadata() -> None:
    limits = {
        "id": "segment-1",
        "source_code": "NGP",
        "destination_code": "JNPT",
        "max_height": 6.0,
        "max_width": 4.0,
        "max_weight": 100.0,
        "congestion_factor": 1.1,
        "historical_delay_hours": 0.5,
        "geometry_lon_lat": [[79.0, 21.0], [72.9, 18.9]],
    }
    certified_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
    first = engineering_evidence_payload(
        limits,
        source_type="IMPORTED_DOCUMENT",
        source_reference="register-1",
        certified_by="authorized issuer",
        certified_at=certified_at,
    )
    changed = engineering_evidence_payload(
        limits,
        source_type="IMPORTED_DOCUMENT",
        source_reference="register-1",
        certified_by="different issuer",
        certified_at=certified_at,
    )
    assert stable_checksum(first) != stable_checksum(changed)
