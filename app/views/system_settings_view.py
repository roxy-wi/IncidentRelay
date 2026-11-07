"""Global administrator API for installation-wide operational settings."""

from flask import Blueprint, jsonify, request

from app.api.schemas.system_settings import SystemSettingsUpdate
from app.middleware import load_jwt_user
from app.services import system_settings
from app.services.validation import make_error_response, validate_body

system_settings_bp = Blueprint("system_settings_api", __name__)


@system_settings_bp.after_request
def prevent_caching(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@system_settings_bp.route("", methods=["GET", "PATCH"])
def manage_system_settings():
    """Read or update the system singleton using a global administrator JWT."""
    user = load_jwt_user()
    if user is None:
        return make_error_response("jwt_required", "Valid JWT token is required", 401)
    if not user.is_admin:
        return make_error_response("access_denied", "Global administrator required", 403)
    if request.args:
        return make_error_response("invalid_query", "No query parameters are supported", 400)
    if request.method == "PATCH":
        payload, error = validate_body(SystemSettingsUpdate)
        if error:
            return error
        try:
            row = system_settings.update_settings(payload, actor_id=user.id)
        except system_settings.InvalidRetryWindow as error:
            return make_error_response("invalid_retry_window", str(error), 400)
        except system_settings.SystemSettingsAccessDenied:
            return make_error_response("access_denied", "Global administrator required", 403)
    else:
        row = system_settings.get_settings()
    return jsonify({name: getattr(row, name) for name in SystemSettingsUpdate.model_fields})
