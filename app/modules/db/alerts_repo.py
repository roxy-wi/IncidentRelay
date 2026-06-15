from functools import reduce
from operator import or_
from math import ceil
from datetime import datetime
import hashlib

from peewee import Case, JOIN, fn

from app.modules.db.models import (
    Alert,
    AlertEvent,
    AlertGroup,
    AlertGroupMerge,
    AlertRoute,
    AlertComment,
    Rotation,
    Service,
    Team,
    User,
    IncidentResponder,
    IncidentStakeholder,
    MaintenanceWindow,
    MaintenanceWindowService,
    ServiceOwner,
)
from app.modules.db.query_filters import (
    apply_field_values_filter,
    normalize_filter_values,
)


MAX_ALERTS_PAGE_SIZE = 100

ALERT_GROUP_STATUS_SORT = Case(
    AlertGroup.status,
    (
        ("firing", 1),
        ("acknowledged", 2),
        ("silenced", 3),
        ("resolved", 4),
        ("merged", 5),
    ),
    9,
)

ALERT_GROUP_SEVERITY_SORT = Case(
    AlertGroup.severity,
    (
        ("critical", 4),
        ("high", 3),
        ("medium", 2),
        ("low", 1),
    ),
    0,
)

ALERT_GROUP_PRIORITY_SORT = fn.COALESCE(AlertGroup.priority_order, 3)

ALERT_GROUP_SORT_FIELDS = {
    "id": AlertGroup.id,
    "status": ALERT_GROUP_STATUS_SORT,
    "title": AlertGroup.title,
    "severity": ALERT_GROUP_SEVERITY_SORT,
    "priority": ALERT_GROUP_PRIORITY_SORT,
    "team": Team.slug,
    "assignee": User.username,
    "created": AlertGroup.first_seen_at,
    "last_seen": AlertGroup.last_seen_at,
    "activity": AlertGroup.last_seen_at,
    "reminders": AlertGroup.reminder_count,
}


def normalize_alert_group_sort(sort):
    """Return a whitelisted alert group sort field."""

    if sort in ALERT_GROUP_SORT_FIELDS:
        return sort

    return "activity"


def apply_alert_group_priority_filter(query, values):
    """Apply incident priority filter by priority slug.

    Old groups can have NULL priority_slug if they were created before
    incident priorities were introduced. Treat NULL as the default P3
    priority when filtering by p3.
    """
    priorities = []
    seen = set()

    for value in normalize_filter_values(values):
        value = str(value).strip().lower()

        if not value or value in seen:
            continue

        seen.add(value)
        priorities.append(value)

    if not priorities:
        return query

    conditions = [AlertGroup.priority_slug.in_(priorities)]

    if "p3" in priorities:
        conditions.append(AlertGroup.priority_slug.is_null(True))

    return query.where(reduce(or_, conditions))


def build_alert_groups_query(
    team_id=None,
    team_ids=None,
    status=None,
    source=None,
    severity=None,
    priority=None,
    service_id=None,
    service_slug=None,
    service_status=None,
    service_criticality=None,
    search=None,
    include_merged=False,
):
    """Build the base alert groups query with filters."""

    query = (
        AlertGroup
        .select(AlertGroup, Team, AlertRoute, Rotation, User)
        .join(Team, JOIN.LEFT_OUTER)
        .switch(AlertGroup)
        .join(AlertRoute, JOIN.LEFT_OUTER)
        .switch(AlertGroup)
        .join(Rotation, JOIN.LEFT_OUTER)
        .switch(AlertGroup)
        .join(User, JOIN.LEFT_OUTER, on=(AlertGroup.assignee == User.id))
    )

    if not include_merged:
        query = query.where(AlertGroup.merged_into.is_null(True))
        query = query.where(AlertGroup.status != "merged")

    if team_id:
        query = query.where(AlertGroup.team == team_id)
    elif team_ids is not None:
        if not team_ids:
            return None

        query = query.where(AlertGroup.team.in_(team_ids))

    query = apply_field_values_filter(
        query,
        AlertGroup.status,
        status,
    )

    query = apply_field_values_filter(
        query,
        AlertGroup.source,
        source,
    )

    query = apply_field_values_filter(
        query,
        AlertGroup.severity,
        severity,
    )
    query = apply_alert_group_priority_filter(
        query,
        priority,
    )
    query = apply_field_values_filter(
        query,
        AlertGroup.service,
        service_id,
        value_type=int,
    )

    if service_slug:
        service_ids = (
            Service
            .select(Service.id)
            .where(
                (Service.slug == service_slug)
                & (Service.deleted == False)
            )
        )
        query = query.where(AlertGroup.service.in_(service_ids))

    if service_status:
        service_ids = (
            Service
            .select(Service.id)
            .where(
                (Service.status == service_status)
                & (Service.deleted == False)
            )
        )
        query = query.where(AlertGroup.service.in_(service_ids))

    if service_criticality:
        service_ids = (
            Service
            .select(Service.id)
            .where(
                (Service.criticality == service_criticality)
                & (Service.deleted == False)
            )
        )
        query = query.where(AlertGroup.service.in_(service_ids))

    if search:
        search = str(search).strip()

        if search:
            group_conditions = [
                AlertGroup.title.contains(search),
                AlertGroup.message.contains(search),
                AlertGroup.source.contains(search),
                AlertGroup.group_key.contains(search),
                AlertGroup.severity.contains(search),
                AlertGroup.status.contains(search),
                AlertGroup.common_labels.contains(search),
                AlertGroup.label_values.contains(search),
                AlertGroup.payload_summary.contains(search),
                Team.slug.contains(search),
                Team.name.contains(search),
                AlertRoute.name.contains(search),
                Rotation.name.contains(search),
                User.username.contains(search),
                User.display_name.contains(search),
            ]

            child_conditions = [
                Alert.title.contains(search),
                Alert.message.contains(search),
                Alert.source.contains(search),
                Alert.external_id.contains(search),
                Alert.dedup_key.contains(search),
                Alert.group_key.contains(search),
                Alert.severity.contains(search),
                Alert.status.contains(search),
                Alert.labels.contains(search),
                Alert.payload.contains(search),
            ]

            if search.isdigit():
                search_id = int(search)
                group_conditions.append(AlertGroup.id == search_id)
                child_conditions.append(Alert.id == search_id)

            child_group_ids = (
                Alert
                .select(Alert.group)
                .where(
                    (Alert.group.is_null(False))
                    & reduce(or_, child_conditions)
                )
            )

            group_conditions.append(AlertGroup.id.in_(child_group_ids))

            query = query.where(reduce(or_, group_conditions))

    return query


def apply_alert_group_sort(query, sort, order):
    """Apply whitelisted sorting to alert groups query."""

    sort = normalize_alert_group_sort(sort)
    order = normalize_alert_order(order)

    expression = ALERT_GROUP_SORT_FIELDS[sort]
    ordered_expression = expression.asc() if order == "asc" else expression.desc()

    if sort == "id":
        return query.order_by(ordered_expression)

    return query.order_by(ordered_expression, AlertGroup.id.desc())


def summarize_alert_groups(query, total_items):
    """Build summary counters for the current filtered group selection."""

    summary = {
        "firing": 0,
        "acknowledged": 0,
        "resolved": 0,
        "silenced": 0,
        "merged": 0,
        "reminders": 0,
        "alerts": 0,
        "total": total_items,
    }

    if query is None:
        return summary

    summary_query = (
        query
        .select(
            AlertGroup.status.alias("status"),
            fn.COUNT(AlertGroup.id).alias("count"),
            fn.COALESCE(fn.SUM(AlertGroup.reminder_count), 0).alias("reminders"),
            fn.COALESCE(fn.SUM(AlertGroup.alert_count), 0).alias("alerts"),
        )
        .group_by(AlertGroup.status)
    )

    for row in summary_query.dicts():
        status = row.get("status") or "unknown"
        count = row.get("count") or 0

        if status in summary:
            summary[status] = count

        summary["reminders"] += row.get("reminders") or 0
        summary["alerts"] += row.get("alerts") or 0

    return summary


def empty_paginated_alert_groups(page=1, page_size=25, sort="activity", order="desc"):
    """Return an empty paginated alert group response."""

    page = normalize_alert_page(page)
    page_size = normalize_alert_page_size(page_size)

    return {
        "items": [],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_items": 0,
            "total_pages": 1,
            "from": 0,
            "to": 0,
            "has_prev": False,
            "has_next": False,
        },
        "summary": summarize_alert_groups(None, 0),
        "sort": {
            "field": normalize_alert_group_sort(sort),
            "order": normalize_alert_order(order),
        },
    }


def paginate_alert_groups(
    team_id=None,
    team_ids=None,
    status=None,
    source=None,
    severity=None,
    priority=None,
    service_id=None,
    service_slug=None,
    service_status=None,
    service_criticality=None,
    search=None,
    page=1,
    page_size=25,
    sort="activity",
    order="desc",
    include_merged=False,
):
    """Return alert groups with backend pagination, filtering and sorting."""

    page = normalize_alert_page(page)
    page_size = normalize_alert_page_size(page_size)
    sort = normalize_alert_group_sort(sort)
    order = normalize_alert_order(order)

    query = build_alert_groups_query(
        team_id=team_id,
        team_ids=team_ids,
        status=status,
        source=source,
        severity=severity,
        priority=priority,
        service_id=service_id,
        service_slug=service_slug,
        service_status=service_status,
        service_criticality=service_criticality,
        search=search,
        include_merged=include_merged,
    )

    if query is None:
        return empty_paginated_alert_groups(
            page=page,
            page_size=page_size,
            sort=sort,
            order=order,
        )

    total_items = query.count()
    total_pages = max(1, int(ceil(total_items / float(page_size))))

    if page > total_pages:
        page = total_pages

    sorted_query = apply_alert_group_sort(query, sort, order)
    items = list(sorted_query.paginate(page, page_size))

    start_index = (page - 1) * page_size
    end_index = start_index + len(items)

    return {
        "items": items,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_items": total_items,
            "total_pages": total_pages,
            "from": start_index + 1 if total_items else 0,
            "to": end_index if total_items else 0,
            "has_prev": page > 1,
            "has_next": page < total_pages,
        },
        "summary": summarize_alert_groups(query, total_items),
        "sort": {
            "field": sort,
            "order": order,
        },
    }


def get_alert(alert_id: int) -> Alert | None:
    return Alert.get_or_none(Alert.id == alert_id)


def get_alert_group(group_id):
    """Return an alert group by id."""

    return AlertGroup.get_by_id(group_id)


def hash_group_key(group_key):
    """Return stable hash for potentially long group keys."""

    value = str(group_key or "")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def find_open_alert_group(source, group_key, team_id=None, route_id=None, service_id=None):
    """Return open alert group by routing/grouping key."""

    group_key_hash = hash_group_key(group_key)

    query = AlertGroup.select().where(
        (AlertGroup.source == source)
        & (AlertGroup.group_key_hash == group_key_hash)
        & (AlertGroup.status.not_in(("resolved", "merged")))
        & (AlertGroup.merged_into.is_null(True))
    )

    if team_id:
        query = query.where(AlertGroup.team == team_id)

    if route_id:
        query = query.where(AlertGroup.route == route_id)

    if service_id:
        query = query.where(AlertGroup.service == service_id)

    return query.order_by(AlertGroup.id.desc()).first()


def create_alert_group(**kwargs):
    """Create alert group."""

    group_key = kwargs.get("group_key") or ""
    kwargs["group_key_hash"] = hash_group_key(group_key)
    return AlertGroup.create(**kwargs)


def list_alerts_for_group(group_id):
    """Return concrete alerts inside group."""

    return list(
        Alert.select()
        .where(Alert.group == group_id)
        .order_by(Alert.id.asc())
    )


def _collect_group_labels(alerts):
    """Build common labels and varying values for a group."""

    if not alerts:
        return {}, {}

    all_keys = set()
    for alert in alerts:
        all_keys.update((alert.labels or {}).keys())

    common = {}
    values = {}

    for key in sorted(all_keys):
        seen = []
        for alert in alerts:
            value = (alert.labels or {}).get(key)
            if value is not None and value not in seen:
                seen.append(value)

        if len(seen) == 1:
            common[key] = seen[0]
        elif seen:
            values[key] = seen

    return common, values


def recalculate_alert_group(group):
    """Recalculate alert group counters, labels and effective status."""

    now = datetime.utcnow()

    alerts = list(
        Alert
        .select()
        .where(Alert.group == group.id)
        .order_by(Alert.last_seen_at.desc(), Alert.id.desc())
    )

    total = len(alerts)

    firing_count = sum(1 for alert in alerts if alert.status == "firing")
    acknowledged_count = sum(1 for alert in alerts if alert.status == "acknowledged")
    resolved_count = sum(1 for alert in alerts if alert.status == "resolved")
    silenced_count = sum(1 for alert in alerts if alert.status == "silenced")

    previous_status = group.status

    group.alert_count = total
    group.firing_count = firing_count
    group.acknowledged_count = acknowledged_count
    group.resolved_count = resolved_count
    group.silenced_count = silenced_count
    group.silenced = total > 0 and silenced_count == total

    if alerts:
        newest_alert = alerts[0]

        group.title = newest_alert.title
        group.message = newest_alert.message
        group.severity = newest_alert.severity
        group.last_seen_at = newest_alert.last_seen_at or now

        if not group.first_seen_at:
            group.first_seen_at = min(
                alert.first_seen_at
                for alert in alerts
                if alert.first_seen_at
            )

        common_labels, label_values = _collect_group_labels(alerts)

        group.common_labels = common_labels
        group.label_values = label_values
        group.payload_summary = {
            "latest_alert_id": newest_alert.id,
            "latest_dedup_key": newest_alert.dedup_key,
            "latest_external_id": newest_alert.external_id,
            "latest_payload": newest_alert.payload or {},
        }

    if total == 0:
        pass

    elif resolved_count == total:
        group.status = "resolved"

        if not group.resolved_at:
            group.resolved_at = now

        alerts_without_resolved_at = [
            alert
            for alert in alerts
            if not alert.resolved_at
        ]

        for alert in alerts_without_resolved_at:
            alert.resolved_at = now
            alert.updated_at = now
            alert.save()

    elif firing_count > 0:
        if group.status == "acknowledged":
            group.status = "acknowledged"
        else:
            group.status = "firing"
            group.resolved_at = None
            group.resolved_by = None

    elif silenced_count > 0:
        group.status = "silenced"
        group.resolved_at = None
        group.resolved_by = None

    elif acknowledged_count > 0:
        group.status = "acknowledged"
        group.resolved_at = None
        group.resolved_by = None

    else:
        group.status = previous_status

    if previous_status != group.status:
        group.previous_status = previous_status

    group.updated_at = now
    group.save()

    return group


def acknowledge_alert_group(group_id, user_id=None):
    """Acknowledge alert group."""

    group = AlertGroup.get_by_id(group_id)
    group.previous_status = group.status
    group.status = "acknowledged"
    group.acknowledged_by = user_id
    group.acknowledged_at = datetime.utcnow()
    group.save()
    return group


def resolve_alert_group(group_id, user_id=None):
    """Resolve alert group and all child alerts."""

    now = datetime.utcnow()
    group = AlertGroup.get_by_id(group_id)

    (
        Alert.update(status="resolved", resolved_at=now)
        .where(
            (Alert.group == group.id)
            & (Alert.status != "resolved")
        )
        .execute()
    )

    group.previous_status = group.status
    group.status = "resolved"
    group.resolved_by = user_id
    group.resolved_at = now
    group.firing_count = 0
    group.acknowledged_count = 0
    group.resolved_count = Alert.select().where(Alert.group == group.id).count()
    group.updated_at = now
    group.save()

    return group


def list_firing_alert_groups():
    """Return groups for reminder/escalation processing."""

    return list(
        AlertGroup.select()
        .where(
            (AlertGroup.status == "firing")
            & (AlertGroup.merged_into.is_null(True))
        )
    )


def record_group_notification_time(group, now):
    group.last_notification_at = now
    group.save()
    return group


def increment_group_reminder(group, now):
    group.reminder_count += 1
    group.last_notification_at = now
    group.save()
    return group


def list_group_events(group_id):
    """Return group-level and child alert events."""

    alert_ids = Alert.select(Alert.id).where(Alert.group == group_id)

    return list(
        AlertEvent.select()
        .where(
            (AlertEvent.group == group_id)
            | (AlertEvent.alert.in_(alert_ids))
        )
        .order_by(AlertEvent.id.asc())
    )


def merge_alert_groups(target_group_id, source_group_ids, user_id=None, reason=None):
    """Merge source groups into target group."""

    target = AlertGroup.get_by_id(target_group_id)
    now = datetime.utcnow()

    for source_id in source_group_ids:
        if int(source_id) == int(target_group_id):
            continue

        source = AlertGroup.get_by_id(source_id)

        (
            Alert.update(group=target.id, group_key=target.group_key)
            .where(Alert.group == source.id)
            .execute()
        )

        source.previous_status = source.status
        source.status = "merged"
        source.merged_into = target.id
        source.merged_by = user_id
        source.merged_at = now
        source.merge_reason = reason
        source.updated_at = now
        source.save()

        AlertGroupMerge.create(
            source_group=source.id,
            target_group=target.id,
            merged_by=user_id,
            reason=reason,
        )

        create_alert_event(
            group_id=source.id,
            event_type="merged",
            message=f"Merged into group #{target.id}",
            user_id=user_id,
        )

    recalculate_alert_group(target)

    create_alert_event(
        group_id=target.id,
        event_type="merge_target_updated",
        message="Alert groups merged into this group",
        user_id=user_id,
    )

    return target


def normalize_alert_page(page):
    """
    Return a safe page number.
    """
    try:
        page = int(page)
    except (TypeError, ValueError):
        return 1

    return max(page, 1)


def normalize_alert_page_size(page_size):
    """
    Return a safe page size.

    The upper limit protects the API from loading too many rows at once.
    """
    try:
        page_size = int(page_size)
    except (TypeError, ValueError):
        return 25

    page_size = max(page_size, 1)

    return min(page_size, MAX_ALERTS_PAGE_SIZE)


def normalize_alert_order(order):
    """
    Return a safe sort order.
    """
    if order == "asc":
        return "asc"

    return "desc"


def find_existing_alert(source, dedup_key, window_seconds=None):
    """
    Return an existing non-resolved alert by source and dedup key.

    Resolved alerts are final occurrences. If the same fingerprint fires again
    after resolve, a new alert must be created with a new id and first_seen_at.
    """
    return (
        Alert.select()
        .where(
            (Alert.source == source)
            & (Alert.dedup_key == dedup_key)
            & (Alert.status != "resolved")
        )
        .order_by(Alert.id.desc())
        .first()
    )


def create_alert(**kwargs):
    """
    Create an alert.
    """

    return Alert.create(**kwargs)


def update_alert_from_payload(alert, alert_data, status, group_key):
    """
    Update an alert from normalized payload data.
    """
    now = datetime.utcnow()

    alert.last_seen_at = now
    previous_status = alert.status
    alert.previous_status = previous_status
    alert.last_seen_at = datetime.utcnow()
    alert.payload = alert_data.get("payload")
    alert.labels = alert_data.get("labels")
    alert.message = alert_data.get("message")
    alert.severity = alert_data.get("severity")
    alert.group_key = group_key
    if previous_status in ("acknowledged", "silenced") and status == "firing":
        alert.status = previous_status
    else:
        alert.status = status
    if status == "resolved" and not alert.resolved_at:
        alert.resolved_at = now
    alert.save()
    return alert, previous_status


def create_alert_event(alert_id=None, event_type=None, message=None, user_id=None, group_id=None):
    """Create alert/group event."""

    return AlertEvent.create(
        alert=alert_id,
        group=group_id,
        event_type=event_type,
        message=message,
        user=user_id,
    )


def list_alert_events(alert_id):
    """
    Return alert events.
    """

    return list(
        AlertEvent.select()
        .where(AlertEvent.alert == alert_id)
        .order_by(AlertEvent.id.asc())
    )


def schedule_alert_group_notification(group, due_at, reason="notification"):
    """Schedule a pending notification for an alert group."""

    if (
        group.notification_pending
        and group.notification_due_at
        and group.notification_due_at <= due_at
    ):
        return group

    group.notification_pending = True
    group.notification_due_at = due_at
    group.notification_reason = reason
    group.updated_at = datetime.utcnow()
    group.save()

    return group


def clear_alert_group_notification(group):
    """Clear pending group notification."""

    group.notification_pending = False
    group.notification_due_at = None
    group.notification_reason = None
    group.updated_at = datetime.utcnow()
    group.save()

    return group


def mark_alert_group_notification_sent(group, now=None):
    """Mark group notification as sent."""

    now = now or datetime.utcnow()

    group.notification_pending = False
    group.notification_due_at = None
    group.notification_reason = None
    group.last_notification_at = now
    group.updated_at = now
    group.save()

    return group


def list_due_alert_group_notifications(now=None, limit=100):
    """Return groups with due pending notifications."""

    now = now or datetime.utcnow()

    return list(
        AlertGroup
        .select()
        .where(
            (AlertGroup.notification_pending == True)
            & (AlertGroup.notification_due_at.is_null(False))
            & (AlertGroup.notification_due_at <= now)
            & (AlertGroup.merged_into.is_null(True))
            & (AlertGroup.status != "merged")
        )
        .order_by(AlertGroup.notification_due_at.asc(), AlertGroup.id.asc())
        .limit(limit)
    )


def create_alert_comment(
    *,
    group_id: int | None = None,
    alert_id: int | None = None,
    user_id: int | None = None,
    body: str,
) -> AlertComment:
    if not group_id and not alert_id:
        raise ValueError("group_id or alert_id is required")

    return AlertComment.create(
        group=group_id,
        alert=alert_id,
        user=user_id,
        body=body,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def list_group_comments(
    group_id: int,
    *,
    include_deleted: bool = False,
) -> list[AlertComment]:
    query = (
        AlertComment
        .select(AlertComment, User)
        .join(User, JOIN.LEFT_OUTER)
        .switch(AlertComment)
        .where(AlertComment.group == group_id)
        .order_by(AlertComment.created_at.asc(), AlertComment.id.asc())
    )

    if not include_deleted:
        query = query.where(AlertComment.deleted == False)  # noqa: E712

    return list(query)


def list_alert_comments(
    alert_id: int,
    *,
    include_deleted: bool = False,
) -> list[AlertComment]:
    query = (
        AlertComment
        .select(AlertComment, User)
        .join(User, JOIN.LEFT_OUTER)
        .switch(AlertComment)
        .where(AlertComment.alert == alert_id)
        .order_by(AlertComment.created_at.asc(), AlertComment.id.asc())
    )

    if not include_deleted:
        query = query.where(AlertComment.deleted == False)  # noqa: E712

    return list(query)


def get_alert_comment(comment_id: int) -> AlertComment | None:
    return AlertComment.get_or_none(AlertComment.id == comment_id)


def soft_delete_alert_comment(comment_id: int) -> bool:
    updated = (
        AlertComment
        .update(
            deleted=True,
            deleted_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        .where(
            AlertComment.id == comment_id,
            AlertComment.deleted == False,  # noqa: E712
        )
        .execute()
    )

    return bool(updated)


def update_alert_comment(
    comment_id: int,
    *,
    body: str,
) -> AlertComment | None:
    comment = AlertComment.get_or_none(
        AlertComment.id == comment_id,
        AlertComment.deleted == False,  # noqa: E712
    )

    if not comment:
        return None

    comment.body = body
    comment.updated_at = datetime.utcnow()
    comment.save(only=[
        AlertComment.body,
        AlertComment.updated_at,
    ])

    return comment


def priority_from_severity(severity):
    value = (severity or "").lower()

    if value in ("critical", "fatal", "disaster"):
        return "p1", 1

    if value in ("high", "error"):
        return "p2", 2

    if value in ("warning", "warn"):
        return "p3", 3

    if value in ("info", "notice"):
        return "p4", 4

    return "p5", 5


def set_alert_group_priority(group_id, priority, user_id=None):
    priority = (priority or "p3").lower()

    order_map = {
        "p1": 1,
        "p2": 2,
        "p3": 3,
        "p4": 4,
        "p5": 5,
    }

    if priority not in order_map:
        raise ValueError("priority must be one of: p1, p2, p3, p4, p5")

    group = AlertGroup.get_by_id(group_id)
    old_priority = group.priority

    group.priority = priority
    group.priority_order = order_map[priority]
    group.updated_at = datetime.utcnow()
    group.save(only=[
        AlertGroup.priority,
        AlertGroup.priority_order,
        AlertGroup.updated_at,
    ])

    create_alert_event(
        group_id=group.id,
        event_type="priority_changed",
        message=f"Priority changed from {old_priority} to {priority}",
        user_id=user_id,
    )

    return group


def find_active_maintenance_window(*, group_id=None, team_id=None, service_id=None, now=None):
    now = now or datetime.utcnow()

    query = (
        MaintenanceWindow
        .select()
        .where(
            MaintenanceWindow.deleted == False,  # noqa: E712
            MaintenanceWindow.enabled == True,  # noqa: E712
            MaintenanceWindow.starts_at <= now,
            MaintenanceWindow.ends_at >= now,
            MaintenanceWindow.status.in_(("scheduled", "active")),
        )
        .order_by(MaintenanceWindow.starts_at.desc(), MaintenanceWindow.id.desc())
    )

    service_window_ids = []

    if service_id:
        service_window_ids = [
            row.maintenance_window_id
            for row in (
                MaintenanceWindowService
                .select(MaintenanceWindowService.maintenance_window)
                .where(MaintenanceWindowService.service == service_id)
            )
        ]

    conditions = []

    if group_id:
        conditions.append(MaintenanceWindow.group == group_id)

    if team_id:
        conditions.append(MaintenanceWindow.team == team_id)

    if service_window_ids:
        conditions.append(MaintenanceWindow.id.in_(service_window_ids))

    if not conditions:
        return None

    combined = conditions[0]
    for condition in conditions[1:]:
        combined = combined | condition

    return query.where(combined).first()


def create_incident_stakeholder(group_id, data):
    """Create stakeholder subscription for an incident."""
    return IncidentStakeholder.create(
        group=group_id,
        user=data.get("user_id"),
        email=data.get("email"),
        display_name=data.get("display_name"),
        role=data.get("role") or "stakeholder",
        source=data.get("source") or "manual",
        notify_on_created=data.get("notify_on_created", True),
        notify_on_priority_change=data.get("notify_on_priority_change", True),
        notify_on_status_change=data.get("notify_on_status_change", True),
        notify_on_resolved=data.get("notify_on_resolved", True),
        active=data.get("active", True),
        created_by=data.get("created_by_id"),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def list_incident_stakeholders(group_id, *, include_inactive=False):
    """Return incident stakeholders."""
    query = (
        IncidentStakeholder
        .select()
        .where(IncidentStakeholder.group == group_id)
        .order_by(
            IncidentStakeholder.created_at.asc(),
            IncidentStakeholder.id.asc(),
        )
    )

    if not include_inactive:
        query = query.where(IncidentStakeholder.active == True)  # noqa: E712

    return list(query)


def get_incident_stakeholder(stakeholder_id):
    """Return one incident stakeholder."""
    return IncidentStakeholder.get_or_none(
        IncidentStakeholder.id == stakeholder_id
    )


def deactivate_incident_stakeholder(stakeholder_id):
    """Soft-disable incident stakeholder subscription."""
    updated = (
        IncidentStakeholder
        .update(
            active=False,
            updated_at=datetime.utcnow(),
        )
        .where(
            IncidentStakeholder.id == stakeholder_id,
            IncidentStakeholder.active == True,  # noqa: E712
        )
        .execute()
    )

    return bool(updated)


def add_service_stakeholders_to_incident(group):
    """Auto-add service stakeholders/business owners to a new incident."""
    if not group.service_id:
        return []

    rows = []

    owners = (
        ServiceOwner
        .select()
        .where(
            ServiceOwner.service == group.service_id,
            ServiceOwner.active == True,  # noqa: E712
            ServiceOwner.role.in_(
                (
                    "stakeholder",
                    "business_owner",
                    "owner",
                )
            ),
        )
    )

    for owner in owners:
        exists = (
            IncidentStakeholder
            .select()
            .where(
                IncidentStakeholder.group == group.id,
                IncidentStakeholder.user == owner.user_id,
                IncidentStakeholder.active == True,  # noqa: E712
            )
            .exists()
        )

        if exists:
            continue

        rows.append(
            create_incident_stakeholder(
                group.id,
                {
                    "user_id": owner.user_id,
                    "role": owner.role,
                    "source": "service_owner",
                    "notify_on_created": True,
                    "notify_on_priority_change": True,
                    "notify_on_status_change": True,
                    "notify_on_resolved": True,
                    "active": True,
                },
            )
        )

    return rows

def create_incident_responder(group_id, data):
    """Create responder request for an incident."""
    return IncidentResponder.create(
        group=group_id,
        target_type=data["target_type"],
        target_user=data.get("target_user_id"),
        target_team=data.get("target_team_id"),
        target_rotation=data.get("target_rotation_id"),
        target_escalation_policy=data.get("target_escalation_policy_id"),
        requested_by=data.get("requested_by_id"),
        status=data.get("status") or "requested",
        message=data.get("message"),
        notification_status=data.get("notification_status") or "pending",
        expires_at=data.get("expires_at"),
        requested_at=datetime.utcnow(),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def list_incident_responders(group_id):
    """Return incident responder requests."""
    return list(
        IncidentResponder
        .select()
        .where(IncidentResponder.group == group_id)
        .order_by(
            IncidentResponder.created_at.asc(),
            IncidentResponder.id.asc(),
        )
    )


def get_incident_responder(responder_id):
    """Return one incident responder request."""
    return IncidentResponder.get_or_none(
        IncidentResponder.id == responder_id
    )


def update_incident_responder_status(
    responder_id,
    status,
    *,
    user_id=None,
    response_message=None,
):
    """Update incident responder request status."""
    responder = IncidentResponder.get_by_id(responder_id)

    responder.status = status
    responder.response_message = response_message
    responder.responded_at = datetime.utcnow()
    responder.updated_at = datetime.utcnow()

    if status == "accepted":
        responder.accepted_by = user_id

    if status == "declined":
        responder.declined_by = user_id

    responder.save()

    return responder
