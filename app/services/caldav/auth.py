import base64
from datetime import datetime
from functools import wraps

from flask import Response, g, request

from app.modules.db import tokens_repo
from app.modules.db.models import User
from app.services.integrations.auth import hash_token, token_has_scope
from app.modules.common import utc_now

CALDAV_REQUIRED_SCOPES = ["calendar:read"]


def unauthorized():
    response = Response("Authentication required\n", status=401)
    response.headers["WWW-Authenticate"] = 'Basic realm="IncidentRelay CalDAV"'
    return response


def parse_basic_auth_header():
    header = request.headers.get("Authorization") or ""

    if not header.lower().startswith("basic "):
        return None, None

    try:
        encoded = header.split(" ", 1)[1].strip()
        decoded = base64.b64decode(encoded).decode("utf-8")
    except Exception:
        return None, None

    if ":" not in decoded:
        return None, None

    username, password = decoded.split(":", 1)

    return username.strip(), password.strip()


def find_user_by_login(login):
    if not login:
        return None

    return User.get_or_none(
        (
            (User.username == login) |
            (User.email == login)
        ) &
        (User.active == True) &  # noqa: E712
        (User.deleted == False)  # noqa: E712
    )


def authenticate_caldav_user(username, token):
    """Authenticate CalDAV request with username/email + personal API token."""
    user = find_user_by_login(username)

    if not user or not token:
        return None

    api_token = tokens_repo.get_active_token_by_hash(hash_token(token))

    if not api_token:
        return None

    if api_token.expires_at and api_token.expires_at <= utc_now():
        return None

    if not api_token.user or api_token.user.id != user.id:
        return None

    if not token_has_scope(api_token, CALDAV_REQUIRED_SCOPES):
        return None

    tokens_repo.mark_token_used(api_token)

    g.caldav_api_token = api_token

    return user


def require_caldav_auth(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        username, token = parse_basic_auth_header()
        user = authenticate_caldav_user(username, token)

        if not user:
            return unauthorized()

        g.caldav_user = user

        return func(*args, **kwargs)

    return wrapper
