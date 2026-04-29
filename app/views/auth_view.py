from flask import Blueprint, jsonify, make_response, request

from app.api.schemas.auth import ChangePasswordSchema, LoginSchema
from app.login import create_access_token, hash_password, verify_password
from app.middleware import jwt_required
from app.modules.db import users_repo, groups_repo
from app.services.serializers import serialize_user
from app.services.validation import validate_body
from app.settings import Config


auth_bp = Blueprint("auth_api", __name__)


@auth_bp.route("/login", methods=["POST"])
def login():
    """
    Authenticate a user and return a JWT access token.
    """

    payload, error = validate_body(LoginSchema)
    if error:
        return error

    user = users_repo.get_user_by_username(payload.username)

    if not user or not user.active or not verify_password(payload.password, user.password_hash):
        return jsonify({"error": "Invalid username or password"}), 401

    token, expires_at = create_access_token(user)

    response = make_response(jsonify({
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at.isoformat(),
        "user": serialize_user(user),
    }))

    response.set_cookie(
        Config.JWT_COOKIE_NAME,
        token,
        max_age=Config.JWT_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=Config.JWT_COOKIE_SECURE,
        samesite="Lax",
    )

    return response


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """
    Clear the JWT cookie.
    """

    response = make_response(jsonify({"status": "logged_out"}))
    response.delete_cookie(Config.JWT_COOKIE_NAME)
    return response


@auth_bp.route("/me", methods=["GET"])
@jwt_required
def me():
    """
    Return the current JWT user.
    """

    return jsonify(serialize_user(request.current_user, groups=groups_repo.list_user_groups(request.current_user.id)))


@auth_bp.route("/change-password", methods=["POST"])
@jwt_required
def change_password():
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

    return jsonify({"status": "password_changed"})
