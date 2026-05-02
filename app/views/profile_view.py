from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from app.api.schemas.auth import ChangePasswordSchema
from app.api.schemas.profile import ActiveGroupSchema, ProfileTokenCreateSchema, ProfileUpdateSchema
from app.login import hash_password, verify_password
from app.modules.db import groups_repo, tokens_repo, users_repo
from app.services.auth import create_raw_token, hash_token
from app.services.audit import write_audit
from app.services.rbac import can_read_group
from app.services.serializers import serialize_user, serialize_api_token
from app.services.validation import validate_body


profile_bp = Blueprint("profile_api", __name__)

ALLOWED_PROFILE_TOKEN_SCOPES = {
    "alerts:read",
    "alerts:write",
    "resources:read",
    "resources:write",
    "profile:read",
    "profile:write",
    "*",
}


def validate_profile_token_scopes(requested_scopes):
    """
    Validate scopes for a newly created personal API token.

    Security rules:
    - unknown scopes are rejected;
    - wildcard "*" is admin-only;
    - API token cannot create another token with broader scopes than itself.
    """
    requested = set(requested_scopes or ["alerts:read"])
    unknown = requested - ALLOWED_PROFILE_TOKEN_SCOPES

    if unknown:
        return None, jsonify({
            "error": "Unknown token scopes",
            "unknown_scopes": sorted(unknown),
        }), 400

    if "*" in requested and not request.current_user.is_admin:
        return None, jsonify({
            "error": "Wildcard scope is allowed for admin users only",
        }), 403

    current_api_token = getattr(request, "current_api_token", None)

    if current_api_token:
        current_scopes = set(current_api_token.scopes or [])

        if "*" not in current_scopes and not requested.issubset(current_scopes):
            return None, jsonify({
                "error": "Cannot create a token with broader scopes than the current token",
                "allowed_scopes": sorted(current_scopes),
                "requested_scopes": sorted(requested),
            }), 403

    return sorted(requested), None, None


@profile_bp.route("", methods=["GET"])
def get_profile():
    """
    Return the current user profile.
    """

    memberships = groups_repo.list_user_groups(request.current_user.id)
    return jsonify(serialize_user(request.current_user, groups=memberships))


@profile_bp.route("", methods=["PUT"])
def update_profile():
    """
    Update the current user profile.
    """

    payload, error = validate_body(ProfileUpdateSchema)
    if error:
        return error

    data = payload.model_dump(exclude_unset=True)
    user = users_repo.update_user(request.current_user.id, data)
    write_audit("profile.update", object_type="user", object_id=user.id, user_id=user.id, data=data)

    return jsonify(serialize_user(user, groups=groups_repo.list_user_groups(user.id)))


@profile_bp.route("/change-password", methods=["POST"])
def change_profile_password():
    """
    Change the current user's password.
    """

    payload, error = validate_body(ChangePasswordSchema)
    if error:
        return error

    user = request.current_user

    if not verify_password(payload.old_password, user.password_hash):
        return jsonify({"error": "Old password is invalid"}), 400

    users_repo.set_user_password(user.id, hash_password(payload.new_password))
    write_audit("profile.password.change", object_type="user", object_id=user.id, user_id=user.id)

    return jsonify({"status": "password_changed"})


@profile_bp.route("/tokens", methods=["GET"])
def list_profile_tokens():
    """
    Return personal API token metadata for the current user.
    """
    tokens = tokens_repo.list_user_tokens(request.current_user.id)

    return jsonify([serialize_api_token(token) for token in tokens])


@profile_bp.route("/tokens", methods=["POST"])
def create_profile_token():
    """
    Create a personal API token for the current user.
    """

    payload, error = validate_body(ProfileTokenCreateSchema)
    if error:
        return error

    scopes, error_response, status_code = validate_profile_token_scopes(payload.scopes)
    if error_response:
        return error_response, status_code

    group = None

    if payload.group_id:
        if not can_read_group(request.current_user, payload.group_id):
            return jsonify({"error": "Access to this group is denied"}), 403
        group = payload.group_id

    raw_token = create_raw_token()
    expires_at = datetime.utcnow() + timedelta(days=payload.days) if payload.days else None

    token = tokens_repo.create_token(
        name=payload.name,
        token_prefix=raw_token[:12],
        token_hash=hash_token(raw_token),
        scopes=scopes,
        user=request.current_user.id,
        group=group,
        expires_at=expires_at,
    )

    write_audit(
        "profile.token.create",
        object_type="api_token",
        object_id=token.id,
        user_id=request.current_user.id,
    )

    data = serialize_api_token(token)
    data["token"] = raw_token

    return jsonify(data), 201


@profile_bp.route("/tokens/<int:token_id>", methods=["DELETE"])
def revoke_profile_token(token_id):
    """
    Revoke a personal API token owned by the current user.
    """
    token = tokens_repo.revoke_user_token(token_id, request.current_user.id)

    if not token:
        return jsonify({"error": "Token not found"}), 404

    write_audit(
        "profile.token.revoke",
        object_type="api_token",
        object_id=token.id,
        user_id=request.current_user.id,
    )

    return jsonify({
        "revoked": True,
        "id": token.id,
    })


@profile_bp.route("/active-group", methods=["POST"])
def set_active_group():
    """
    Set the current user's active group.
    """

    payload, error = validate_body(ActiveGroupSchema)
    if error:
        return error

    if payload.group_id:
        if not can_read_group(request.current_user, payload.group_id):
            return jsonify({"error": "Access to this group is denied"}), 403
        user = users_repo.set_active_group(request.current_user.id, payload.group_id)
    else:
        user = users_repo.set_active_group(request.current_user.id, None)

    write_audit(
        "profile.active_group.set",
        object_type="user",
        object_id=user.id,
        group_id=payload.group_id,
        user_id=user.id,
    )

    return jsonify(serialize_user(user, groups=groups_repo.list_user_groups(user.id)))
