"""Global administrator API for installation-wide operational settings."""

from flask import Blueprint, jsonify, request

from app.api.schemas.system_settings import SystemSettingsUpdate
from app.services import system_settings
from app.services.rbac import current_api_token
from app.services.validation import make_error_response, validate_body

system_settings_bp = Blueprint("system_settings_api", __name__)


@system_settings_bp.after_request
def prevent_caching(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@system_settings_bp.route("", methods=["GET", "PATCH"])
def manage_system_settings():
    """Read or update the singleton as an authenticated global administrator."""
    user = getattr(request, "current_user", None)
    if not user or not user.active or user.deleted:
        return make_error_response(
            "authentication_required", "Authentication is required", 401
        )
    if not user.is_admin:
        return make_error_response("access_denied", "Global administrator required", 403)
    token = current_api_token()
    if token and (token.group_id is not None or token.team_id is not None):
        return make_error_response(
            "access_denied", "An unrestricted administrator token is required", 403
        )
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
