from flask import jsonify, request
from pydantic import ValidationError


def make_json_safe(value):
    """
    Convert values from Pydantic errors to JSON-serializable values.
    """

    if isinstance(value, BaseException):
        return str(value)

    if isinstance(value, dict):
        return {str(key): make_json_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [make_json_safe(item) for item in value]

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    return str(value)


def normalize_validation_error(error):
    """
    Convert one Pydantic error to a clean API error object.
    """

    loc = [str(item) for item in error.get("loc", [])]
    message = error.get("msg", "Invalid value")

    if message.startswith("Value error, "):
        message = message.replace("Value error, ", "", 1)

    result = {
        "field": ".".join(loc) if loc else None,
        "loc": loc,
        "message": message,
        "type": error.get("type"),
    }

    if "input" in error:
        result["input"] = make_json_safe(error["input"])

    if "ctx" in error:
        result["ctx"] = make_json_safe(error["ctx"])

    return result


def validate_body(schema_cls):
    """
    Validate JSON request body with a Pydantic schema.
    """

    payload = request.get_json(silent=True)

    if payload is None:
        return None, (
            jsonify({
                "error": "validation_error",
                "message": "Request body must be valid JSON",
                "details": [],
            }),
            400,
        )

    try:
        return schema_cls.model_validate(payload), None
    except ValidationError as exc:
        return None, (
            jsonify({
                "error": "validation_error",
                "message": "Request validation failed",
                "details": [
                    normalize_validation_error(error)
                    for error in exc.errors()
                ],
            }),
            400,
        )
