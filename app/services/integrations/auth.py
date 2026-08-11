import hashlib
import secrets
from datetime import datetime
from functools import wraps

from flask import jsonify, request

from app.middleware import load_jwt_user
from app.modules.db import routes_repo, tokens_repo
from app.settings import Config
from app.modules.common import utc_now
from app.services.api_token_scopes import token_has_scopes


def create_raw_token():
    """
    Create a random token.
    """

    return secrets.token_urlsafe(48)


def hash_token(raw_token):
    """
    Hash a token before storing it.
    """

    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def get_bearer_token():
    """
    Extract a bearer token from the Authorization header.
    """

    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        return None

    return auth_header.split(" ", 1)[1].strip()


def get_json_routing_key():
    """Return PagerDuty-compatible routing_key from a JSON request body."""

    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return None

    routing_key = payload.get("routing_key")

    if routing_key is None:
        return None

    routing_key = str(routing_key).strip()
    return routing_key or None


def authenticate_api_token(raw_token=None):
    """
    Authenticate a stored API token.
    """

    raw_token = raw_token or get_bearer_token()

    if not raw_token:
        request.current_api_token = None
        return None

    api_token = tokens_repo.get_active_token_by_hash(hash_token(raw_token))

    if not api_token:
        request.current_api_token = None
        return None

    if api_token.expires_at and api_token.expires_at <= utc_now():
        request.current_api_token = None
        return None

    tokens_repo.mark_token_used(api_token)

    request.current_api_token = api_token
    request.current_auth_type = "api_token"

    if api_token.user and api_token.user.active:
        request.current_user = api_token.user

    return api_token


def authenticate_route_token(raw_token=None):
    """
    Authenticate a route alert intake token.
    """

    raw_token = raw_token or get_bearer_token()

    if not raw_token:
        request.current_intake_route = None
        return None

    route = routes_repo.get_route_by_intake_hash(hash_token(raw_token))

    if not route:
        request.current_intake_route = None
        return None

    request.current_intake_route = route
    request.current_auth_type = "route_token"

    return route


def authenticate_request():
    """
    Authenticate the request using JWT first, then personal/API tokens.
    """

    user = load_jwt_user()

    if user:
        request.current_api_token = None
        request.current_auth_type = "jwt"
        return user

    api_token = authenticate_api_token()

    if api_token:
        return api_token

    request.current_auth_type = None
    return None


def token_has_scope(api_token, required_scopes):
    """Return True when an API token has all required effective scopes."""
    return token_has_scopes(api_token.scopes or [], required_scopes)


def require_api_token(scopes=None, required=None):
    """
    Require JWT or API token authentication for a view.
    """

    scopes = scopes or []
    required = Config.API_AUTH_REQUIRED if required is None else required

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            principal = authenticate_request()

            if not required and not principal:
                return func(*args, **kwargs)

            if not principal:
                return jsonify({"error": "Authentication is required"}), 401

            api_token = getattr(request, "current_api_token", None)

            if api_token and not token_has_scope(api_token, scopes):
                return jsonify({"error": "Missing API token scope", "missing_scopes": scopes}), 403

            return func(*args, **kwargs)

        return wrapper

    return decorator


def require_alert_token(allow_json_routing_key=False):
    """
    Require a token that can submit incoming alerts.

    Accepted tokens:
    - personal/API token with alerts:write scope;
    - route intake token created on the Routes page;
    - PagerDuty-compatible JSON routing_key when explicitly enabled.

    routing_key is checked before Authorization so it remains the routing
    boundary for PagerDuty Events API v2-compatible requests.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if allow_json_routing_key:
                routing_key = get_json_routing_key()

                if routing_key:
                    route = authenticate_route_token(routing_key)

                    if route:
                        request.current_auth_type = "pagerduty_routing_key"
                        return func(*args, **kwargs)

                    # Do not silently fall back to another credential when a
                    # sender explicitly supplied a PagerDuty routing key.
                    return jsonify({"error": "Route intake token is required"}), 401

            raw_token = get_bearer_token()

            api_token = authenticate_api_token(raw_token)

            if api_token:
                if token_has_scope(api_token, ["alerts:write"]):
                    request.current_auth_type = "api_token"
                    return func(*args, **kwargs)

                return jsonify({"error": "Missing API token scope", "missing_scopes": ["alerts:write"]}), 403

            route = authenticate_route_token(raw_token)

            if route:
                return func(*args, **kwargs)

            return jsonify({"error": "Route intake token is required"}), 401

        return wrapper

    return decorator
