from __future__ import annotations

import logging

from pydantic import BaseModel, field_validator

from app.services.validation import (
    make_json_safe,
    normalize_validation_error,
    safe_exception_response,
    validate_body,
)


class _ExplodingBody(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def reject_name(cls, value):
        raise ValueError("database password is release-secret")


def test_safe_exception_response_returns_only_generic_client_message(app, caplog):
    @app.get("/_release/safe-exception")
    def safe_exception_route():
        try:
            raise RuntimeError(
                "postgresql://incidentrelay:release-secret@db.internal/app"
            )
        except RuntimeError as exc:
            return safe_exception_response(
                exc,
                error="dependency_unavailable",
                message="Dependency is unavailable.",
                status_code=503,
            )

    with caplog.at_level(logging.WARNING):
        response = app.test_client().get("/_release/safe-exception")

    body = response.get_data(as_text=True)

    assert response.status_code == 503
    assert response.get_json() == {
        "error": "dependency_unavailable",
        "message": "Dependency is unavailable.",
    }
    assert "release-secret" not in body
    assert "postgresql://" not in body
    assert "db.internal" not in body
    assert "RuntimeError" not in body
    assert "Traceback" not in body


def test_validation_error_does_not_expose_validator_exception(app):
    @app.post("/_release/validation-exception")
    def validation_exception_route():
        payload, error = validate_body(_ExplodingBody)
        if error:
            return error
        return {"name": payload.name}

    response = app.test_client().post(
        "/_release/validation-exception",
        json={"name": "unsafe"},
    )
    body = response.get_data(as_text=True)
    payload = response.get_json()

    assert response.status_code == 400
    assert payload["error"] == "validation_error"
    assert payload["message"] == "Request validation failed"
    assert len(payload["details"]) == 1

    detail = payload["details"][0]
    assert detail["field"] == "name"
    assert "release-secret" not in str(detail)
    assert "password" not in str(detail).lower()
    assert "ValueError" not in str(detail)

    assert "release-secret" not in body
    assert "Traceback" not in body


def test_make_json_safe_recursively_hides_exception_messages():
    value = make_json_safe(
        {
            "top": RuntimeError("top-secret"),
            "nested": [
                ValueError("nested-secret"),
                {"error": KeyError("key-secret")},
            ],
        }
    )

    assert value == {
        "top": "Invalid value",
        "nested": [
            "Invalid value",
            {"error": "Invalid value"},
        ],
    }
    assert "secret" not in str(value).lower()


def test_normalize_validation_error_drops_exception_objects_from_context():
    result = normalize_validation_error(
        {
            "loc": ("body", "name"),
            "msg": "Value error, invalid name",
            "type": "value_error",
            "input": RuntimeError("input-secret"),
            "ctx": {
                "error": ValueError("context-secret"),
                "safe": "visible",
            },
        }
    )

    assert result == {
        "field": "body.name",
        "loc": ["body", "name"],
        "message": "Invalid value",
        "type": "value_error",
        "input": "Invalid value",
        "ctx": {"safe": "visible"},
    }
