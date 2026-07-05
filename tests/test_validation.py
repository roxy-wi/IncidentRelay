from pydantic import BaseModel

from app.services.validation import make_json_safe, normalize_validation_error, validate_body


class ExampleBody(BaseModel):
    name: str
    count: int


def test_make_json_safe_converts_non_serializable_values():
    value = make_json_safe({
        "ok": True,
        "items": (1, 2),
        "error": ValueError("bad"),
    })

    assert value == {
        "ok": True,
        "items": [1, 2],
        "error": "Invalid value",
    }


def test_make_json_safe_does_not_expose_exception_messages():
    value = make_json_safe(ValueError("secret database detail"))

    assert value == "Invalid value"
    assert "secret" not in value


def test_normalize_validation_error_returns_compact_details():
    try:
        ExampleBody.model_validate({"name": "test", "count": "not-an-int"})
    except Exception as exc:
        result = normalize_validation_error(exc.errors()[0])

    assert result["field"] == "count"
    assert result["loc"] == ["count"]
    assert result["type"] == "int_parsing"
    assert "message" in result


def test_validate_body_accepts_valid_json(app):
    @app.post("/_test/validate")
    def route():
        payload, error = validate_body(ExampleBody)
        if error:
            return error
        return {"name": payload.name, "count": payload.count}

    response = app.test_client().post("/_test/validate", json={"name": "ok", "count": 3})

    assert response.status_code == 200
    assert response.get_json() == {"name": "ok", "count": 3}


def test_validate_body_rejects_invalid_json(app):
    @app.post("/_test/invalid-json")
    def route_invalid_json():
        payload, error = validate_body(ExampleBody)
        if error:
            return error
        return {"name": payload.name, "count": payload.count}

    response = app.test_client().post(
        "/_test/invalid-json",
        data="{invalid-json",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"
    assert response.get_json()["message"] == "Request body must be valid JSON"


def test_validate_body_rejects_schema_errors(app):
    @app.post("/_test/schema-error")
    def route_schema_error():
        payload, error = validate_body(ExampleBody)
        if error:
            return error
        return {"name": payload.name, "count": payload.count}

    response = app.test_client().post("/_test/schema-error", json={"name": "ok"})

    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"
    assert response.get_json()["message"] == "Request validation failed"
    assert response.get_json()["details"][0]["field"] == "count"
