from app.api.openapi.spec import build_openapi_spec


def test_openapi_includes_matcher_suggestions_path():
    spec = build_openapi_spec()

    assert "/api/matchers/suggestions" in spec["paths"]
    assert "get" in spec["paths"]["/api/matchers/suggestions"]


def test_openapi_matcher_suggestions_require_team_id_and_bearer_auth():
    operation = build_openapi_spec()["paths"]["/api/matchers/suggestions"]["get"]
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}

    assert operation["security"] == [{"bearerAuth": []}]
    assert parameters["team_id"]["required"] is True
    assert parameters["limit"]["schema"]["maximum"] == 500
    assert parameters["values_limit"]["schema"]["maximum"] == 50


def test_openapi_matcher_suggestions_response_contains_labels_and_fields():
    operation = build_openapi_spec()["paths"]["/api/matchers/suggestions"]["get"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]

    labels_schema = schema["properties"]["labels"]["additionalProperties"]
    fields_schema = schema["properties"]["fields"]["additionalProperties"]

    assert labels_schema["items"]["type"] == "string"
    assert fields_schema["items"]["type"] == "string"


def test_openapi_has_matchers_tag():
    tags = {tag["name"] for tag in build_openapi_spec()["tags"]}

    assert "matchers" in tags
