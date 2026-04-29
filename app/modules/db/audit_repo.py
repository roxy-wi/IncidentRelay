from app.models import AuditLog


def create_audit_log(action, object_type=None, object_id=None, group_id=None, team_id=None, user_id=None, api_token_id=None, message=None, data=None):
    """
    Create an audit log entry.
    """

    return AuditLog.create(
        group=group_id,
        team=team_id,
        user=user_id,
        api_token=api_token_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        message=message,
        data=data or {},
    )


def list_audit_logs(team_id=None, limit=300):
    """
    Return audit log entries.
    """

    query = AuditLog.select().order_by(AuditLog.id.desc())
    if team_id:
        query = query.where(AuditLog.team == team_id)
    return list(query.limit(limit))
