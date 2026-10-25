import logging

from flask import request

from app.modules.db import audit_repo
from app.modules.redaction import redact_secrets


def current_api_token_id():
    """Return the authenticated personal API-token id for this request."""
    return getattr(getattr(request, "current_api_token", None), "id", None)


def record_audit(
    action,
    object_type=None,
    object_id=None,
    group_id=None,
    team_id=None,
    user_id=None,
    api_token_id=None,
    message=None,
    data=None,
    transport="api",
):
    """Persist a redacted, structured audit from any service or worker.

    All actor and token identifiers are explicit; this function must never
    assume Flask request context (scheduler and integration callers use it too).
    """
    if transport not in {"api", "sso", "system", "integration"}:
        raise ValueError("unsupported audit transport")

    safe_message = redact_secrets(message)
    safe_data = redact_secrets({**(data or {}), "transport": transport})
    entry = audit_repo.create_audit_log(
        action=action,
        object_type=object_type,
        object_id=object_id,
        group_id=group_id,
        team_id=team_id,
        user_id=user_id,
        api_token_id=api_token_id,
        message=safe_message,
        data=safe_data,
    )
    logging.getLogger("oncall.audit").info(
        "user action",
        extra={
            "extra": {
                "event_type": "user_action",
                "audit_id": entry.id,
                "action": action,
                "object_type": object_type,
                "object_id": object_id,
                "group_id": group_id,
                "team_id": team_id,
                "user_id": user_id,
                "api_token_id": api_token_id,
                "has_message": bool(safe_message),
                "data_keys": sorted(safe_data.keys()),
            }
        },
    )
    return entry


def write_audit(
    action,
    object_type=None,
    object_id=None,
    group_id=None,
    team_id=None,
    user_id=None,
    message=None,
    data=None,
    transport="api",
):
    """Resolve Flask authentication context, then call the shared writer."""
    current_user = getattr(request, "current_user", None)
    resolved_user_id = user_id or (
        current_user.id if current_user else None
    )
    return record_audit(
        action,
        object_type=object_type,
        object_id=object_id,
        group_id=group_id,
        team_id=team_id,
        user_id=resolved_user_id,
        api_token_id=current_api_token_id(),
        message=message,
        data=data,
        transport=transport,
    )
