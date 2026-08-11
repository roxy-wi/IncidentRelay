from functools import wraps

import jwt
from flask import jsonify, request

from app.login import decode_access_token
from app.modules.db import users_repo
from app.settings import Config
from app.services.api_token_scopes import (
    is_public_api_request,
    is_public_calendar_feed_path as is_public_calendar_feed_request,
    required_scopes_for_path,
    token_has_scopes,
)


def get_authorization_token():
    """
    Read a JWT token from the Authorization header or the auth cookie.
    """

    header = request.headers.get("Authorization", "")

    if header.startswith("Bearer "):
        return header.split(" ", 1)[1].strip()

    return request.cookies.get(Config.JWT_COOKIE_NAME)


def load_jwt_user():
    """
    Load the current user from a JWT token.
    """

    token = get_authorization_token()

    if not token:
        request.current_user = None
        return None

    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        request.current_user = None
        return None

    user = users_repo.get_user(int(payload["sub"]))

    if not user or not user.active:
        request.current_user = None
        return None

    request.current_user = user
    request.current_auth_type = "jwt"
    return user


def jwt_required(func):
    """
    Require a valid JWT token.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        user = load_jwt_user()

        if not user:
            return jsonify({"error": "Valid JWT token is required"}), 401

        return func(*args, **kwargs)

    return wrapper


def api_auth_required_for_path(path, method=None):
    """Return True when global API authentication must protect the path."""
    if not path.startswith("/api/"):
        return False

    method = method or request.method
    return not is_public_api_request(path, method)


def is_public_calendar_feed_path(path, method=None):
    """Compatibility wrapper for the tokenized public ICS feed check."""
    return is_public_calendar_feed_request(path, method or request.method)


def required_scopes_for_request():
    """Return configured API-token scopes for the current request.

    None means the endpoint has no scope mapping and must fail closed for an
    API-token principal. JWT users are unaffected by this mapping.
    """
    return required_scopes_for_path(request.path, request.method)


def api_token_has_scopes(api_token, required_scopes):
    """Return True when an API token has the required effective scopes."""
    return token_has_scopes(api_token.scopes or [], required_scopes)

def load_api_token_principal():
    """
    Load a personal/API token principal.

    This function imports auth helpers lazily to avoid circular imports.
    """

    from app.services.integrations.auth import authenticate_api_token, get_bearer_token

    raw_token = get_bearer_token()

    if not raw_token:
        return None

    api_token = authenticate_api_token(raw_token)

    if not api_token:
        return None

    required_scopes = required_scopes_for_request()

    if required_scopes is None:
        return jsonify({
            "error": "API token access is not configured for this endpoint",
        }), 403

    if not api_token_has_scopes(api_token, required_scopes):
        return jsonify({
            "error": "Missing API token scope",
            "missing_scopes": required_scopes,
        }), 403

    return api_token


def enforce_api_authentication():
    """
    Enforce authentication for regular API endpoints.

    Accepted authentication methods:
    - JWT cookie or JWT Bearer token;
    - personal/API Bearer token.
    """

    if request.method == "OPTIONS":
        return None

    if not api_auth_required_for_path(request.path):
        return None

    user = load_jwt_user()

    if user:
        return None

    api_token_or_response = load_api_token_principal()

    if api_token_or_response:
        if isinstance(api_token_or_response, tuple):
            return api_token_or_response
        return None

    if Config.API_AUTH_REQUIRED:
        return jsonify({"error": "JWT or API token authentication is required"}), 401

    return None
