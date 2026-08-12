from app.api.openapi.spec import build_openapi_spec
from app.services.orchestration.actions import SUPPORTED_ACTION_TYPES
from app.services.orchestration.conditions import SUPPORTED_OPERATORS


EXPECTED_PATHS = {
    "/api/event-orchestrations",
    "/api/event-orchestrations/catalog",
    "/api/event-orchestrations/{orchestration_id}",
    "/api/event-orchestrations/{orchestration_id}/draft",
    "/api/event-orchestrations/{orchestration_id}/validate",
    "/api/event-orchestrations/{orchestration_id}/publish",
    "/api/event-orchestrations/{orchestration_id}/rollback",
    "/api/event-orchestrations/{orchestration_id}/runtime",
    "/api/event-orchestrations/{orchestration_id}/versions",
    "/api/event-orchestrations/{orchestration_id}/versions/{version_id}",
    "/api/event-orchestrations/{orchestration_id}/simulate",
    "/api/event-orchestrations/{orchestration_id}/replay",
    "/api/event-orchestrations/{orchestration_id}/executions",
    "/api/event-orchestrations/{orchestration_id}/shadow-metrics",
    "/api/orchestration-webhook-actions",
    "/api/orchestration-webhook-actions/{action_id}",
    "/api/orchestration-webhook-actions/{action_id}/executions",
}


def test_openapi_documents_all_event_orchestration_control_plane_paths():
    spec = build_openapi_spec()

    assert EXPECTED_PATHS <= set(spec["paths"])
    tags = {item["name"] for item in spec["tags"]}
    assert "event-orchestrations" in tags
    assert "orchestration-webhook-actions" in tags

    operation_ids = []
    for path in EXPECTED_PATHS:
        for operation in spec["paths"][path].values():
            operation_ids.append(operation["operationId"])
            assert operation["security"] == [{"bearerAuth": []}]
    assert len(operation_ids) == len(set(operation_ids))


def test_openapi_condition_tree_is_recursive_and_lists_runtime_operators():
    schemas = build_openapi_spec()["components"]["schemas"]
    condition = schemas["OrchestrationCondition"]
    group = schemas["OrchestrationConditionGroup"]
    tree = schemas["OrchestrationConditionTree"]

    assert set(condition["properties"]["operator"]["enum"]) == set(
        SUPPORTED_OPERATORS
    )
    assert tree["oneOf"] == [
        {"$ref": "#/components/schemas/OrchestrationCondition"},
        {"$ref": "#/components/schemas/OrchestrationConditionGroup"},
    ]
    for logical_key in ("all", "any", "none"):
        assert group["properties"][logical_key]["items"] == {
            "$ref": "#/components/schemas/OrchestrationConditionTree"
        }


def test_openapi_action_schema_tracks_safe_supported_actions():
    action = build_openapi_spec()["components"]["schemas"][
        "OrchestrationAction"
    ]

    assert set(action["properties"]["type"]["enum"]) == set(
        SUPPORTED_ACTION_TYPES
    )
    assert "enqueue_webhook" in action["properties"]["type"]["enum"]
    assert "shell" not in action["properties"]["type"]["enum"]
    assert "python" not in action["properties"]["type"]["enum"]


def test_openapi_versions_include_editor_and_publisher_metadata():
    version = build_openapi_spec()["components"]["schemas"][
        "OrchestrationVersion"
    ]

    for field in (
        "created_by_id",
        "created_by",
        "updated_by_id",
        "updated_by",
        "published_by_id",
        "published_by",
    ):
        assert field in version["properties"]

    publish = build_openapi_spec()["paths"][
        "/api/event-orchestrations/{orchestration_id}/publish"
    ]["post"]
    assert "Group editors" in publish["description"]


def test_openapi_webhook_headers_are_write_only_and_never_in_response():
    spec = build_openapi_spec()
    create_schema = spec["paths"]["/api/orchestration-webhook-actions"][
        "post"
    ]["requestBody"]["content"]["application/json"]["schema"]
    response_schema = spec["components"]["schemas"][
        "OrchestrationWebhookAction"
    ]

    assert create_schema["properties"]["headers"]["writeOnly"] is True
    assert "headers" not in response_schema["properties"]
