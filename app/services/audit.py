import logging

from flask import request

from app.modules.db import audit_repo


def write_audit(action, object_type=None, object_id=None, group_id=None, team_id=None, user_id=None, message=None, data=None):
    """
    Write an audit log entry and a JSON audit log record.
    """

    api_token = getattr(request, "current_api_token", None)
    current_user = getattr(request, "current_user", None)

    entry = audit_repo.create_audit_log(
        action=action,
        object_type=object_type,
        object_id=object_id,
        group_id=group_id,
        team_id=team_id,
        user_id=user_id or (current_user.id if current_user else None),
        api_token_id=api_token.id if api_token else None,
        message=message,
        data=data or {},
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
                "user_id": user_id or (current_user.id if current_user else None),
                "api_token_id": api_token.id if api_token else None,
                "message": message,
                "data": data or {},
            }
        },
    )

    return entry
