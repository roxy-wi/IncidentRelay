from app.api.openapi.spec import build_openapi_spec


def test_openapi_includes_browser_push_paths():
    spec = build_openapi_spec()

    paths = spec["paths"]

    assert "/api/profile/push/vapid-public-key" in paths
    assert "/api/profile/push/subscriptions" in paths
    assert "/api/profile/push/subscriptions/{subscription_id}" in paths
    assert "/api/profile/push/test" in paths
    assert "/api/push/actions" in paths


def test_openapi_browser_push_profile_endpoints_require_bearer_auth():
    spec = build_openapi_spec()

    assert spec["paths"]["/api/profile/push/vapid-public-key"]["get"]["security"] == [
        {"bearerAuth": []}
    ]
    assert spec["paths"]["/api/profile/push/subscriptions"]["get"]["security"] == [
        {"bearerAuth": []}
    ]
    assert spec["paths"]["/api/profile/push/subscriptions"]["post"]["security"] == [
        {"bearerAuth": []}
    ]
    assert spec["paths"]["/api/profile/push/subscriptions/{subscription_id}"]["delete"][
        "security"
    ] == [{"bearerAuth": []}]
    assert spec["paths"]["/api/profile/push/test"]["post"]["security"] == [
        {"bearerAuth": []}
    ]


def test_openapi_browser_push_action_endpoint_is_public():
    spec = build_openapi_spec()

    action_operation = spec["paths"]["/api/push/actions"]["post"]

    assert "security" not in action_operation
    assert action_operation["operationId"] == "executeBrowserPushAction"


def test_openapi_browser_push_subscription_schema_has_required_fields():
    spec = build_openapi_spec()

    schema = spec["paths"]["/api/profile/push/subscriptions"]["post"]["requestBody"][
        "content"
    ]["application/json"]["schema"]

    assert schema["required"] == ["endpoint", "keys"]
    assert "endpoint" in schema["properties"]
    assert "keys" in schema["properties"]
    assert schema["properties"]["keys"]["required"] == ["p256dh", "auth"]


def test_openapi_browser_push_action_schema_has_ack_resolve_enum():
    spec = build_openapi_spec()

    schema = spec["paths"]["/api/push/actions"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]

    assert schema["required"] == ["token", "action"]
    assert schema["properties"]["action"]["enum"] == ["ack", "resolve"]


def test_openapi_has_browser_push_tag():
    spec = build_openapi_spec()

    tags = {tag["name"]: tag for tag in spec["tags"]}

    assert "browser-push" in tags
    assert "Profile-level browser push subscriptions" in tags["browser-push"]["description"]
