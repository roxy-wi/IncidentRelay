"""Machine-only experimental intake; disabled until end-to-end acceptance."""

import json

from flask import Blueprint, current_app, jsonify, request
from pydantic import ValidationError

from app.api.schemas.change_events import MAX_BODY_BYTES, ChangeEventInput
from app.api.schemas.gitlab_changes import GitLabDeployment
from app.services.change_intelligence.authorization import ChangeAccessDenied
from app.services.change_intelligence.ingestion import (
    ChangeEventConflict,
    ChangeIntakeBusy,
    ChangeRateLimited,
    ingest_event,
    ingest_gitlab_event,
)
from app.services.change_intelligence.references import InvalidChangeInput
from app.services.system_settings import get_settings
from app.services.integrations.auth import get_bearer_token, get_gitlab_change_token
from app.services.validation import make_error_response

change_events_bp = Blueprint("change_events_api", __name__)


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError("Invalid JSON number")


@change_events_bp.after_request
def no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@change_events_bp.post("")
def receive_change_event():
    """Accept one bounded event only after global machine authentication."""
    return receive_event(ChangeEventInput, lambda payload: ingest_event(payload, get_bearer_token()))


@change_events_bp.post("/gitlab/<int:source_id>")
def receive_gitlab_event(source_id):
    """Accept GitLab's unmodified Deployment Hook with a source-bound mapping."""
    if request.headers.get("X-Gitlab-Event") != "Deployment Hook":
        return make_error_response("validation_error", "Expected a GitLab Deployment Hook", 422)
    return receive_event(
        GitLabDeployment,
        lambda payload: ingest_gitlab_event(payload, get_gitlab_change_token(), source_id),
    )


def receive_event(schema, ingest):
    """Share bounded parsing, receipts and failure behavior across intake formats."""
    if not get_settings().change_intake_enabled:
        return make_error_response("not_found", "Change Event intake is disabled", 404)
    if not request.is_json:
        return make_error_response("invalid_json", "A JSON object is required", 400)
    if request.content_length is not None and request.content_length > MAX_BODY_BYTES:
        return make_error_response("payload_too_large", "Body exceeds 256 KiB", 413)
    raw = request.stream.read(MAX_BODY_BYTES + 1)
    if len(raw) > MAX_BODY_BYTES:
        return make_error_response("payload_too_large", "Body exceeds 256 KiB", 413)
    try:
        body = json.loads(
            raw, object_pairs_hook=_json_object, parse_constant=_invalid_constant
        )
    except (ValueError, UnicodeError, RecursionError):
        return make_error_response("invalid_json", "Malformed JSON object", 400)
    try:
        ChangeEventInput.portable_json(body)
        payload = schema.model_validate(body)
    except (ValueError, RecursionError):
        # Never echo sender values (including rejected URLs/details or secrets).
        return make_error_response(
            "validation_error", "Invalid Change Event fields or limits", 422
        )
    try:
        result, created = ingest(payload)
    except ChangeAccessDenied:
        return make_error_response("access_denied", "Change access denied", 403)
    except ValidationError:
        return make_error_response("validation_error", "Invalid Change Event fields or limits", 422)
    except InvalidChangeInput as error:
        return make_error_response("validation_error", str(error), 422)
    except ChangeEventConflict as error:
        return make_error_response("conflict", str(error), 409)
    except (ChangeRateLimited, ChangeIntakeBusy) as error:
        limited = isinstance(error, ChangeRateLimited)
        response, status = make_error_response(
            "rate_limited" if limited else "temporarily_unavailable",
            str(error),
            429 if limited else 503,
        )
        response.headers["Retry-After"] = "60" if limited else "1"
        return response, status
    except Exception as error:
        # Database errors may contain SQL parameter values. Log only the class;
        # callers retry by ID even if a connection loss made commit uncertain.
        current_app.logger.error("Change Event intake failed: %s", type(error).__name__)
        return make_error_response(
            "internal_error",
            "Change Event could not be confirmed; retry the same event",
            500,
        )
    return jsonify(result), 201 if created else 200
