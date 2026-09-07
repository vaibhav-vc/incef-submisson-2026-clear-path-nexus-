from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.provenance import (
    _owned_snapshot,
    component_record_ids,
    get_route_evidence_kit,
)
from app.models.provenance import LineageEdge, ProvenanceRecord, RouteDecisionSnapshot

from app.services.provenance import (
    AvailabilityState,
    CanonicalSourceType,
    FreshnessState,
    _record,
    calculate_freshness,
    calculate_traceability_summary,
    capture_route_decision,
    engineering_evidence_payload,
    normalize_source_state,
    redact_metadata,
    stable_checksum,
)
from app.services.congestion import CongestionSource
from app.services.port_sync import LoadingWindow, PortDataSource, PortSchedule, compute_port_sync


def test_source_state_normalization_preserves_truth() -> None:
    assert normalize_source_state("LIVE_AIS") is CanonicalSourceType.LIVE_PROVIDER
    assert normalize_source_state("STALE_AIS") is CanonicalSourceType.CACHED_PROVIDER
    assert normalize_source_state("OPERATOR_INPUT") is CanonicalSourceType.OPERATOR_INPUT
    assert normalize_source_state("provider-unavailable") is CanonicalSourceType.UNAVAILABLE


def test_freshness_is_source_specific_and_timestamp_based() -> None:
    now = datetime.now(timezone.utc)
    state, age = calculate_freshness("open_meteo", now - timedelta(minutes=20), now, now)
    assert state is FreshnessState.AGING
    assert age == 1200

    state, age = calculate_freshness("demo_engineering", None, now, now)
    assert state is FreshnessState.NOT_APPLICABLE
    assert age is None

    state, age = calculate_freshness("open_meteo", now + timedelta(hours=1), now, now)
    assert state is FreshnessState.UNKNOWN
    assert age is None

    state, age = calculate_freshness(
        "noaa_swpc", now - timedelta(hours=3, minutes=45), now, now
    )
    assert state is FreshnessState.FRESH
    assert age == 13_500


def test_traceability_uses_real_five_input_denominator() -> None:
    snapshot_id = uuid4()
    route_id = uuid4()
    records = []
    for role in ("CLEARANCE_DECISION", "WEATHER", "PORT_ALIGNMENT", "CONGESTION"):
        records.append(
            _record(
                user_id="user-a",
                route_id=route_id,
                snapshot_id=snapshot_id,
                source_key="clearpath_derived",
                entity_type=role,
                entity_key=role.lower(),
                source_type=CanonicalSourceType.DERIVED,
                raw_state="DERIVED",
                value={"state": "recorded"},
                request_id="request-a",
                role=role,
                used=True,
            )
        )
    summary = calculate_traceability_summary(records, snapshot_id)
    assert summary.traceability.traced == 4
    assert summary.traceability.total == 5
    assert summary.traceability.coverage_pct == 80.0


def test_unavailable_input_is_explicitly_traced_and_secret_metadata_is_redacted() -> None:
    snapshot_id = uuid4()
    record = _record(
        user_id="user-a",
        route_id=uuid4(),
        snapshot_id=snapshot_id,
        source_key="open_meteo",
        entity_type="WEATHER_OBSERVATION",
        entity_key="weather",
        source_type=CanonicalSourceType.UNAVAILABLE,
        raw_state="UNAVAILABLE",
        value={"status": "unavailable"},
        request_id="request-a",
        role="WEATHER",
        excluded_reason="provider unavailable",
        availability=AvailabilityState.UNAVAILABLE,
    )
    summary = calculate_traceability_summary([record], snapshot_id)
    assert summary.traceability.traced == 1
    assert summary.source_modes.unavailable == 1
    assert redact_metadata({"Authorization": "Bearer secret", "safe": 1}) == {
        "Authorization": "[REDACTED]",
        "safe": 1,
    }


@pytest.mark.asyncio
async def test_route_evidence_lookup_is_ownership_scoped_and_non_disclosing() -> None:
    class EmptyResult:
        def one_or_none(self):
            return None

    class CapturingSession:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return EmptyResult()

    db = CapturingSession()
    with pytest.raises(HTTPException) as exc:
        await _owned_snapshot(db, uuid4(), "owner-a")
    assert exc.value.status_code == 404
    assert "generated_routes.user_id" in str(db.statement)
    assert "owner-a" in db.statement.compile().params.values()


@pytest.mark.asyncio
async def test_owned_route_without_snapshot_returns_verifiable_unavailable_kit() -> None:
    route_id = uuid4()

    class Session:
        calls = 0
        statements = []

        async def scalar(self, statement):
            self.statements.append(statement)
            self.calls += 1
            return SimpleNamespace(id=route_id) if self.calls == 1 else None

    db = Session()
    kit = await get_route_evidence_kit(
        route_id=route_id,
        db=db,
        user=SimpleNamespace(id="owner-a"),
    )

    assert kit.decision_state == "UNAVAILABLE"
    assert kit.kit_status == "UNAVAILABLE"
    assert kit.provider_refetch_required is False
    assert kit.evidence is None
    assert kit.integrity.verified is False
    assert kit.manifest["route_id"] == str(route_id)
    assert len(kit.manifest_checksum) == 64
    assert "generated_routes.user_id" in str(db.statements[0])


@pytest.mark.asyncio
async def test_evidence_kit_missing_or_foreign_route_is_non_disclosing() -> None:
    class Session:
        async def scalar(self, _statement):
            return None

    with pytest.raises(HTTPException) as exc:
        await get_route_evidence_kit(
            route_id=uuid4(),
            db=Session(),
            user=SimpleNamespace(id="owner-a"),
        )
    assert exc.value.status_code == 404
    assert exc.value.detail == "Route evidence kit not found"


def test_component_evidence_includes_all_raw_provider_ancestors() -> None:
    raw_weather = SimpleNamespace(id=uuid4())
    raw_noaa = SimpleNamespace(id=uuid4())
    weather_score = SimpleNamespace(id=uuid4())
    records = [raw_weather, raw_noaa, weather_score]
    edges = [
        SimpleNamespace(parent_record_id=raw_weather.id, child_record_id=weather_score.id),
        SimpleNamespace(parent_record_id=raw_noaa.id, child_record_id=weather_score.id),
    ]
    assert component_record_ids(records, edges, [weather_score]) == [
        raw_weather.id,
        raw_noaa.id,
        weather_score.id,
    ]


@pytest.mark.asyncio
async def test_captured_snapshot_keeps_reproducible_port_and_honest_provider_lineage(
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)

    class Session:
        added = []

        def add(self, value):
            self.added.append(value)

        def add_all(self, values):
            self.added.extend(values)

        async def flush(self):
            return None

    segment_id = uuid4()
    engineering_limits = {
        "id": str(segment_id),
        "source_code": "NGP",
        "destination_code": "JNPT",
        "max_height": 6.0,
        "max_width": 4.0,
        "max_weight": 100.0,
        "congestion_factor": 1.1,
        "historical_delay_hours": 0.5,
        "geometry_lon_lat": [],
    }
    segment = SimpleNamespace(
        id=segment_id,
        source_station=SimpleNamespace(code="NGP"),
        dest_station=SimpleNamespace(code="JNPT"),
        geom_path=None,
        max_height_clearance=6.0,
        max_width_clearance=4.0,
        max_weight_capacity=100.0,
        congestion_factor=1.1,
        historical_delay_hours=0.5,
        engineering_source_type="IMPORTED_DOCUMENT",
        engineering_source_reference="Authorized engineering register ER-2026-08",
        engineering_checksum=stable_checksum(
            engineering_evidence_payload(
                engineering_limits,
                source_type="IMPORTED_DOCUMENT",
                source_reference="Authorized engineering register ER-2026-08",
                certified_by="Railway engineering authority",
                certified_at=now,
            )
        ),
        engineering_certified_at=now,
        engineering_certified_by="Railway engineering authority",
    )
    from app.core.config import settings

    monkeypatch.setattr(
        settings,
        "ENGINEERING_CERTIFICATION_ALLOWED_ISSUERS",
        ["Railway engineering authority"],
    )
    port_sync = compute_port_sync(
        17,
        PortSchedule(
            source=PortDataSource.OPERATOR_INPUT,
            port_id="INNSA",
            vessel_id="IMO1234567",
            vessel_status="OPERATOR_DECLARED",
            window=LoadingWindow(
                start=now + timedelta(hours=10), end=now + timedelta(hours=20)
            ),
        ),
        now=now,
    )
    congestion = SimpleNamespace(
        source=CongestionSource.STATIC_PLUS_LIVE_RAIL_AND_PORT,
        score=70.0,
        static_score=80.0,
        live_rail_score=65.0,
        live_weight=0.6,
        port_congestion_pct=20.0,
        port_penalty=5.0,
        detail={
            "rail_source": "CACHED",
            "rail_observed_at": (now - timedelta(hours=2)).isoformat(),
            "rail_fetched_at": now.isoformat(),
            "stations_live": 3,
            "stations_total": 5,
            "port_source": "STALE_AIS",
            "port_observed_at": (now - timedelta(minutes=20)).isoformat(),
        },
    )
    db = Session()
    await capture_route_decision(
        db,
        route=SimpleNamespace(
            id=uuid4(), source_station_code="NGP", dest_station_code="JNPT"
        ),
        user_id="owner-a",
        request_id="request-a",
        cargo={"height": 4.0, "width": 3.0, "weight": 50.0},
        segments=[segment],
        clearance={"status": "APPROVED", "blocking_segment_id": None},
        weather_data={
            "status": "unavailable",
            "_provenance": {
                "provider": "open_meteo",
                "raw_state": "UNAVAILABLE",
                "fetched_at": now.isoformat(),
            },
        },
        kp_data={
            "status": "unavailable",
            "kp_index": None,
            "alert_level": "UNKNOWN",
            "_provenance": {"raw_state": "UNAVAILABLE", "fetched_at": now.isoformat()},
        },
        weather_score=None,
        port_sync=port_sync,
        congestion=congestion,
        historical_score=90.0,
        reliability=68,
        estimated_hours=17,
        applied_weights={"weather": 0.4, "port": 0.3, "congestion": 0.15, "historical": 0.15},
        alerts=[],
    )

    records = [value for value in db.added if isinstance(value, ProvenanceRecord)]
    edges = [value for value in db.added if isinstance(value, LineageEdge)]
    snapshot = next(value for value in db.added if isinstance(value, RouteDecisionSnapshot))
    by_type = {record.entity_type: record for record in records}

    assert by_type["PORT_ALIGNMENT_SCORE"].value_summary["train_arrival_hours"] == 17
    assert by_type["PORT_ALIGNMENT_SCORE"].value_summary["port_id"] == "INNSA"
    assert by_type["PORT_ALIGNMENT_SCORE"].value_summary["vessel_id"] == "IMO1234567"
    assert by_type["ENGINEERING_LIMITS"].canonical_source_type == "IMPORTED_DOCUMENT"
    assert by_type["ENGINEERING_LIMITS"].value_summary["certification"] == "VERIFIED"
    assert by_type["PORT_ALIGNMENT_SCORE"].value_summary["loading_window"]["start"]
    assert by_type["PORT_ALIGNMENT_SCORE"].observed_at == now
    assert by_type["PORT_ALIGNMENT_SCORE"].fetched_at == now
    assert by_type["PORT_ALIGNMENT_SCORE"].valid_until == now + timedelta(hours=20)
    assert by_type["RAIL_CONGESTION_SIGNAL"].raw_source_state == "CACHED"
    assert by_type["AIS_PORT_ACTIVITY"].raw_source_state == "STALE_AIS"
    noaa_edge = next(
        edge
        for edge in edges
        if edge.parent_record_id == by_type["SPACE_WEATHER_OBSERVATION"].id
    )
    assert noaa_edge.relationship == "INPUT_TO"
    assert by_type["WEATHER_SCORE"].used_in_decision is False
    assert by_type["WEATHER_SCORE"].availability_state == "UNAVAILABLE"
    assert "weather" in snapshot.excluded_factors
    assert snapshot.score_breakdown["port"] == port_sync.score
