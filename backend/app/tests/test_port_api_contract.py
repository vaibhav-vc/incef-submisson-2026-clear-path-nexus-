from app.main import app


def test_port_sync_query_requires_real_operation_context() -> None:
    operation = app.openapi()["paths"]["/api/v1/port/sync-status"]["get"]
    parameters = {item["name"]: item for item in operation["parameters"]}

    for name in ("port_id", "vessel_id", "train_arrival_hours"):
        assert parameters[name]["required"] is True


def test_route_requests_require_port_and_arrival_context() -> None:
    schemas = app.openapi()["components"]["schemas"]
    for schema_name in ("RouteEvaluateRequest", "RouteSuggestRequest"):
        required = set(schemas[schema_name]["required"])
        assert {"port_id", "vessel_id", "train_arrival_hours"} <= required


def test_operator_window_requires_manifest_integrity_reference() -> None:
    schema = app.openapi()["components"]["schemas"]["OperatorLoadingWindow"]
    required = set(schema["required"])
    assert {"start_time", "end_time", "manifest_reference", "manifest_sha256"} <= required
