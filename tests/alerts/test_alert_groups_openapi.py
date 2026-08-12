from app.api.openapi.spec import build_openapi_spec


def _json_schema(operation):
    return operation["responses"]["200"]["content"]["application/json"]["schema"]


def test_openapi_alerts_are_documented_as_groups():
    spec = build_openapi_spec()

    operation = spec["paths"]["/api/alerts"]["get"]

    assert operation["operationId"] == "listAlertGroups"
    assert operation["security"] == [{"bearerAuth": []}]

    schema = _json_schema(operation)
    item_schema = schema["properties"]["items"]["items"]

    assert item_schema["properties"]["type"]["enum"] == ["alert_group"]
    assert "alert_count" in item_schema["properties"]
    assert "firing_count" in item_schema["properties"]
    assert "resolved_count" in item_schema["properties"]


def test_openapi_alert_group_detail_contains_child_alerts():
    spec = build_openapi_spec()

    operation = spec["paths"]["/api/alerts/{alert_id}"]["get"]

    assert operation["operationId"] == "getAlertGroup"
    assert operation["security"] == [{"bearerAuth": []}]

    schema = _json_schema(operation)
    properties = schema["properties"]

    assert properties["type"]["enum"] == ["alert_group"]
    assert "alerts" in properties
    assert properties["alerts"]["items"]["properties"]["type"]["enum"] == ["alert"]


def test_openapi_alert_group_merge_endpoint():
    spec = build_openapi_spec()

    operation = spec["paths"]["/api/alerts/merge"]["post"]

    assert operation["operationId"] == "mergeAlertGroups"
    assert operation["security"] == [{"bearerAuth": []}]

    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]

    assert request_schema["required"] == ["target_group_id", "source_group_ids"]
    assert request_schema["properties"]["source_group_ids"]["type"] == "array"


def test_openapi_alert_list_supports_multi_value_filters():
    spec = build_openapi_spec()

    parameters = {
        parameter["name"]: parameter
        for parameter in spec["paths"]["/api/alerts"]["get"]["parameters"]
    }

    assert parameters["status"]["schema"]["type"] == "array"
    assert parameters["status"]["explode"] is True
    assert parameters["severity"]["schema"]["type"] == "array"
    assert parameters["service_id"]["schema"]["type"] == "array"


def test_openapi_has_alerts_tag_for_group_lifecycle():
    spec = build_openapi_spec()

    tags = {tag["name"]: tag for tag in spec["tags"]}

    assert "alerts" in tags
    assert "alert groups" in tags["alerts"]["description"].lower()


def test_openapi_alert_comment_schema_keeps_validation_constraints():
    from app.api.openapi.endpoints.alerts import alert_comment_schema

    schema = alert_comment_schema()
    properties = schema["properties"]

    assert properties["body"]["minLength"] == 1
    assert properties["body"]["maxLength"] == 5000
    assert properties["user"]["nullable"] is True
    assert properties["user"]["properties"]["email"]["format"] == "email"
    assert properties["alert_id"]["nullable"] is True
    assert "edited" in properties
