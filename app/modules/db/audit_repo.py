from datetime import timedelta


from app.modules.db.models import AuditLog, Team, User


DEFAULT_AUDIT_PAGE_SIZE = 25
MAX_AUDIT_PAGE_SIZE = 100


def create_audit_log(
    action,
    object_type=None,
    object_id=None,
    group_id=None,
    team_id=None,
    user_id=None,
    api_token_id=None,
    message=None,
    data=None,
):
    """Create an audit log entry."""

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


def audit_scope_condition(group_ids):
    """Return a query condition for audit entries owned by groups.

    An audit record belongs to a group either directly through ``group_id`` or
    indirectly through a team in that group. Records without either relation
    are global and therefore intentionally excluded from group-editor scope.
    """

    normalized_ids = sorted({int(group_id) for group_id in group_ids or []})
    if not normalized_ids:
        return AuditLog.id == -1

    team_ids = Team.select(Team.id).where(Team.group.in_(normalized_ids))
    return (
        AuditLog.group.in_(normalized_ids)
        | AuditLog.team.in_(team_ids)
    )


def scoped_audit_query(group_ids=None):
    """Return the base audit query, optionally restricted to group scope."""

    query = AuditLog.select()
    if group_ids is not None:
        query = query.where(audit_scope_condition(group_ids))
    return query


def filter_audit_query(
    query,
    *,
    search=None,
    group_id=None,
    actor_id=None,
    action=None,
    object_type=None,
    date_from=None,
    date_to=None,
):
    """Apply supported audit-log filters to a Peewee query."""

    if group_id:
        query = query.where(audit_scope_condition([group_id]))

    if actor_id:
        query = query.where(AuditLog.user == actor_id)

    if action:
        query = query.where(AuditLog.action == action)

    if object_type:
        query = query.where(AuditLog.object_type == object_type)

    if date_from:
        query = query.where(AuditLog.created_at >= date_from)

    if date_to:
        query = query.where(AuditLog.created_at < date_to + timedelta(days=1))

    normalized_search = str(search or "").strip()
    if normalized_search:
        actor_ids = User.select(User.id).where(
            User.username.contains(normalized_search)
            | User.display_name.contains(normalized_search)
        )
        query = query.where(
            AuditLog.action.contains(normalized_search)
            | AuditLog.object_type.contains(normalized_search)
            | AuditLog.message.contains(normalized_search)
            | AuditLog.user.in_(actor_ids)
        )

    return query


def paginate_audit_query(query, page=1, page_size=DEFAULT_AUDIT_PAGE_SIZE):
    """Return a normalized paginated response for an audit query."""

    try:
        normalized_page = max(1, int(page or 1))
    except (TypeError, ValueError):
        normalized_page = 1

    try:
        normalized_page_size = int(page_size or DEFAULT_AUDIT_PAGE_SIZE)
    except (TypeError, ValueError):
        normalized_page_size = DEFAULT_AUDIT_PAGE_SIZE

    normalized_page_size = min(
        MAX_AUDIT_PAGE_SIZE,
        max(1, normalized_page_size),
    )

    total_items = query.count()
    total_pages = max(
        1,
        (total_items + normalized_page_size - 1) // normalized_page_size,
    )
    normalized_page = min(normalized_page, total_pages)

    ordered_query = query.order_by(
        AuditLog.created_at.desc(),
        AuditLog.id.desc(),
    )
    items = list(ordered_query.paginate(normalized_page, normalized_page_size))

    page_from = 0
    page_to = 0
    if total_items:
        page_from = ((normalized_page - 1) * normalized_page_size) + 1
        page_to = min(normalized_page * normalized_page_size, total_items)

    return {
        "items": items,
        "pagination": {
            "page": normalized_page,
            "page_size": normalized_page_size,
            "total_items": total_items,
            "total_pages": total_pages,
            "from": page_from,
            "to": page_to,
            "has_previous": normalized_page > 1,
            "has_next": normalized_page < total_pages,
        },
    }


def audit_filter_options(query):
    """Return distinct actions, object types and actor ids in scope."""

    actions = [
        row.action
        for row in (
            query
            .select(AuditLog.action)
            .where(AuditLog.action.is_null(False))
            .distinct()
            .order_by(AuditLog.action.asc())
        )
        if row.action
    ]

    object_types = [
        row.object_type
        for row in (
            query
            .select(AuditLog.object_type)
            .where(AuditLog.object_type.is_null(False))
            .distinct()
            .order_by(AuditLog.object_type.asc())
        )
        if row.object_type
    ]

    actor_ids = [
        row.user_id
        for row in (
            query
            .select(AuditLog.user)
            .where(AuditLog.user.is_null(False))
            .distinct()
        )
        if row.user_id
    ]

    return {
        "actions": actions,
        "object_types": object_types,
        "actor_ids": actor_ids,
    }


def audit_summary(query):
    """Return aggregate values for the currently filtered audit query."""

    total = query.count()
    actor_count = (
        query
        .select(AuditLog.user)
        .where(AuditLog.user.is_null(False))
        .distinct()
        .count()
    )
    action_count = query.select(AuditLog.action).distinct().count()

    return {
        "total": total,
        "actors": actor_count,
        "actions": action_count,
    }


def list_audit_logs(team_id=None, limit=300):
    """Return audit log entries for backwards-compatible internal callers."""

    query = AuditLog.select().order_by(AuditLog.id.desc())
    if team_id:
        query = query.where(AuditLog.team == team_id)
    return list(query.limit(limit))
