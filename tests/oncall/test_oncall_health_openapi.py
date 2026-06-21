from app.api.openapi.spec import build_openapi_spec


ROTATION_SUMMARIES_PATH = "/api/oncall-health/rotations/summaries"
ROTATION_DETAILS_PATH = "/api/oncall-health/rotations/{rotation_id}"
TEAM_SUMMARIES_PATH = "/api/oncall-health/teams/summaries"
TEAM_DETAILS_PATH = "/api/oncall-health/teams/{team_id}"


def _response_schema(operation, status_code="200"):
    return operation["responses"][status_code]["content"]["application/json"]["schema"]


def test_openapi_includes_oncall_health_paths():
    spec = build_openapi_spec()
    paths = spec["paths"]

    assert ROTATION_SUMMARIES_PATH in paths
    assert ROTATION_DETAILS_PATH in paths
    assert TEAM_SUMMARIES_PATH in paths
    assert TEAM_DETAILS_PATH in paths


def test_openapi_oncall_health_endpoints_require_bearer_auth():
    spec = build_openapi_spec()

    operations = [
        spec["paths"][ROTATION_SUMMARIES_PATH]["get"],
        spec["paths"][ROTATION_DETAILS_PATH]["get"],
        spec["paths"][TEAM_SUMMARIES_PATH]["get"],
        spec["paths"][TEAM_DETAILS_PATH]["get"],
    ]

    for operation in operations:
        assert operation["security"] == [{"bearerAuth": []}]


def test_openapi_rotation_summary_uses_repeated_rotation_ids():
    spec = build_openapi_spec()
    operation = spec["paths"][ROTATION_SUMMARIES_PATH]["get"]

    assert operation["operationId"] == "listRotationHealthSummaries"

    parameter = operation["parameters"][0]

    assert parameter["name"] == "rotation_id"
    assert parameter["in"] == "query"
    assert parameter["style"] == "form"
    assert parameter["explode"] is True
    assert parameter["schema"]["type"] == "array"
    assert parameter["schema"]["items"]["type"] == "integer"


def test_openapi_team_summary_uses_repeated_team_ids():
    spec = build_openapi_spec()
    operation = spec["paths"][TEAM_SUMMARIES_PATH]["get"]

    assert operation["operationId"] == "listTeamHealthSummaries"

    parameter = operation["parameters"][0]

    assert parameter["name"] == "team_id"
    assert parameter["in"] == "query"
    assert parameter["style"] == "form"
    assert parameter["explode"] is True
    assert parameter["schema"]["type"] == "array"
    assert parameter["schema"]["items"]["type"] == "integer"


def test_openapi_rotation_summary_response_contains_items_and_by_id():
    spec = build_openapi_spec()
    operation = spec["paths"][ROTATION_SUMMARIES_PATH]["get"]
    schema = _response_schema(operation)

    assert schema["required"] == ["items", "by_id"]
    assert schema["properties"]["items"]["type"] == "array"
    assert schema["properties"]["by_id"]["type"] == "object"

    item_schema = schema["properties"]["items"]["items"]

    assert item_schema["required"] == ["rotation_id", "summary"]
    assert "status" in item_schema["properties"]["summary"]["properties"]
    assert "partial" in item_schema["properties"]["summary"]["properties"]


def test_openapi_team_summary_response_contains_items_and_by_id():
    spec = build_openapi_spec()
    operation = spec["paths"][TEAM_SUMMARIES_PATH]["get"]
    schema = _response_schema(operation)

    assert schema["required"] == ["items", "by_id"]

    item_schema = schema["properties"]["items"]["items"]

    assert item_schema["required"] == ["team_id", "summary"]
    assert "status" in item_schema["properties"]["summary"]["properties"]


def test_openapi_rotation_health_details_contains_issues():
    spec = build_openapi_spec()
    operation = spec["paths"][ROTATION_DETAILS_PATH]["get"]

    assert operation["operationId"] == "getRotationHealth"

    schema = _response_schema(operation)

    assert schema["properties"]["scope"]["enum"] == ["rotation"]
    assert "summary" in schema["properties"]
    assert "issues" in schema["properties"]

    issue_schema = schema["properties"]["issues"]["items"]

    assert "severity" in issue_schema["required"]
    assert "code" in issue_schema["required"]
    assert "target_type" in issue_schema["required"]


def test_openapi_team_health_details_contains_issues():
    spec = build_openapi_spec()
    operation = spec["paths"][TEAM_DETAILS_PATH]["get"]

    assert operation["operationId"] == "getTeamHealth"

    schema = _response_schema(operation)

    assert schema["properties"]["scope"]["enum"] == ["team"]
    assert "summary" in schema["properties"]
    assert "issues" in schema["properties"]


def test_openapi_has_oncall_health_tag():
    spec = build_openapi_spec()
    tags = {
        tag["name"]: tag
        for tag in spec["tags"]
    }

    assert "on-call health" in tags
    assert "Diagnostics" in tags["on-call health"]["description"]
