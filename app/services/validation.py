import re
import logging
import json
from json import JSONDecodeError

from flask import current_app, jsonify, request
from pydantic import ValidationError
from werkzeug.datastructures import MultiDict


def make_json_safe(value):
    """Convert values from Pydantic errors to JSON-serializable values."""
    if isinstance(value, BaseException):
        return "Invalid value"
    if isinstance(value, dict):
        return {str(key): make_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [make_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


SENSITIVE_VALIDATION_FIELDS = {
    "password",
    "passwd",
    "secret",
    "client_secret",
    "token",
    "api_token",
    "access_token",
    "refresh_token",
    "authorization",
    "private_key",
    "webhook_secret",
}

SENSITIVE_MESSAGE_PATTERN = re.compile(
    r"\b("
    r"password|passwd|secret|client[_ -]?secret|"
    r"api[_ -]?token|access[_ -]?token|refresh[_ -]?token|"
    r"authorization|private[_ -]?key"
    r")\b",
    re.IGNORECASE,
)


def _contains_sensitive_key(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_VALIDATION_FIELDS:
                return True
            if _contains_sensitive_key(item):
                return True

    if isinstance(value, (list, tuple)):
        return any(_contains_sensitive_key(item) for item in value)

    return False


def _validation_error_is_sensitive(loc, input_value, message):
    if any(str(item).lower() in SENSITIVE_VALIDATION_FIELDS for item in loc):
        return True

    if _contains_sensitive_key(input_value):
        return True

    return bool(SENSITIVE_MESSAGE_PATTERN.search(message or ""))


def _safe_validation_ctx(ctx):
    safe = {}

    for key, value in (ctx or {}).items():
        if isinstance(value, BaseException):
            continue

        safe[key] = make_json_safe(value)

    return safe


def normalize_validation_error(error):
    """Convert one Pydantic error to a clean API error object."""
    loc = [str(item) for item in error.get("loc", [])]
    raw_message = error.get("msg", "Invalid value")
    input_value = error.get("input")
    sensitive = _validation_error_is_sensitive(loc, input_value, raw_message)

    if sensitive:
        message = "Invalid value"
    else:
        message = raw_message
        if message.startswith("Value error, "):
            message = message.replace("Value error, ", "", 1)

    result = {
        "field": ".".join(loc) if loc else None,
        "loc": loc,
        "message": message,
        "type": error.get("type"),
    }

    if "input" in error:
        result["input"] = "***REDACTED***" if sensitive else make_json_safe(input_value)

    ctx = _safe_validation_ctx(error.get("ctx"))
    if ctx:
        result["ctx"] = ctx

    return result


def make_body_validation_detail(message, error_type, input_value=None):
    """Build a validation detail for request body level errors."""
    detail = {
        "field": "body",
        "loc": ["body"],
        "message": message,
        "type": error_type,
    }

    if input_value is not None:
        detail["input"] = make_json_safe(input_value)

    return detail


def make_error_response(error, message, status_code, **extra):
    """Build a normalized API error response."""
    payload = {
        "error": error,
        "message": message,
    }

    payload.update(extra)

    return jsonify(payload), status_code


def safe_exception_response(
    exc,
    *,
    error="invalid_request",
    message="Invalid request.",
    status_code=400,
    log_level=logging.WARNING,
    **extra,
):
    """Log exception details server-side without exposing them to clients."""
    current_app.logger.log(
        log_level,
        "%s while handling API request",
        exc.__class__.__name__,
        exc_info=True,
    )

    return make_error_response(
        error,
        message,
        status_code,
        **extra,
    )


def make_validation_response(message, details):
    """Build a normalized validation error response."""
    return make_error_response(
        "validation_error",
        message,
        400,
        details=details,
    )


def _validate_payload(schema_cls, payload):
    try:
        return schema_cls.model_validate(payload), None
    except ValidationError as exc:
        return None, make_validation_response(
            "Request validation failed",
            [
                normalize_validation_error(error)
                for error in exc.errors()
            ],
        )


def normalize_query_payload(args: MultiDict):
    """Convert Flask query args to a Pydantic-friendly dict.

    Single values stay scalar:
        ?service_id=1 -> {"service_id": "1"}

    Repeated values become lists:
        ?status=firing&status=acknowledged -> {"status": ["firing", "acknowledged"]}
    """
    payload = {}

    for key in args.keys():
        values = args.getlist(key)

        if len(values) == 1:
            payload[key] = values[0]
        else:
            payload[key] = values

    return payload


def validate_query(schema_cls):
    """Validate request query parameters with a Pydantic schema."""
    return _validate_payload(schema_cls, normalize_query_payload(request.args))


def validate_body(schema_cls, *, allow_empty=False):
    """Validate JSON request body with a Pydantic schema."""
    raw_body = request.get_data(cache=True) or b""

    if not raw_body.strip():
        if allow_empty:
            return _validate_payload(schema_cls, {})

        message = "Request body is required"
        return None, make_validation_response(
            message,
            [make_body_validation_detail(message, "missing")],
        )

    raw_text = raw_body.decode("utf-8", errors="replace")

    try:
        payload = json.loads(raw_text)
    except JSONDecodeError:
        message = "Request body must be valid JSON"
        return None, make_validation_response(
            message,
            [make_body_validation_detail(message, "json_invalid", raw_text)],
        )

    return _validate_payload(schema_cls, payload)
