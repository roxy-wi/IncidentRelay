from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from peewee import JOIN
from dateutil.rrule import rrulestr

from app.modules.db.models import (
    AlertGroup,
    MaintenanceWindow,
    MaintenanceWindowAlertApplication,
    MaintenanceWindowScope,
    Team,
)
from app.modules.common import as_naive_datetime
from app.modules.common import utc_now


ACTIVE_STATUSES = ("scheduled", "active")


def _get_zoneinfo(timezone_name):
    try:
        return ZoneInfo(timezone_name or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _window_local_now(window, now=None):
    """Return current time as naive wall-clock time in window timezone."""
    zone = _get_zoneinfo(getattr(window, "timezone", None))

    if now is None:
        return datetime.now(zone).replace(tzinfo=None)

    if isinstance(now, str):
        text = now.strip()

        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"

        now = datetime.fromisoformat(text)

    if now.tzinfo is None:
        now = now.replace(tzinfo=dt_timezone.utc)

    return now.astimezone(zone).replace(tzinfo=None)


def _normalize_rrule_text(value):
    text = str(value or "").strip()

    if not text:
        return None

    if text.upper().startswith("RRULE:"):
        text = text.split(":", 1)[1].strip()

    return text or None


def _build_window_rrule(window):
    starts_at = as_naive_datetime(window.starts_at)
    rrule_text = _normalize_rrule_text(getattr(window, "rrule", None))

    if not starts_at or not rrule_text:
        return None

    try:
        return rrulestr(rrule_text, dtstart=starts_at)
    except (TypeError, ValueError):
        return None


def _get_window_duration(window):
    starts_at = as_naive_datetime(window.starts_at)
    ends_at = as_naive_datetime(window.ends_at)

    if not starts_at or not ends_at:
        return None

    duration = ends_at - starts_at

    if duration.total_seconds() <= 0:
        return None

    return duration


def _get_recurring_window_status(window, now=None):
    rule = _build_window_rrule(window)
    duration = _get_window_duration(window)

    if not rule or not duration:
        return None

    local_now = _window_local_now(window, now=now)

    previous_start = rule.before(local_now, inc=True)

    if previous_start:
        previous_end = previous_start + duration

        if previous_start <= local_now <= previous_end:
            return "active"

    next_start = rule.after(local_now, inc=False)

    if next_start:
        return "scheduled"

    return "finished"


def get_effective_window_occurrence(window, now=None):
    status = get_effective_window_status(window, now=now)

    if status == "cancelled":
        return None

    starts_at = as_naive_datetime(window.starts_at)
    ends_at = as_naive_datetime(window.ends_at)

    if not starts_at or not ends_at:
        return None

    if not getattr(window, "rrule", None):
        return {
            "status": status,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "timezone": window.timezone,
            "recurring": False,
        }

    rule = _build_window_rrule(window)
    duration = _get_window_duration(window)

    if not rule or not duration:
        return {
            "status": status,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "timezone": window.timezone,
            "recurring": False,
        }

    local_now = _window_local_now(window, now=now)

    previous_start = rule.before(local_now, inc=True)

    if previous_start:
        previous_end = previous_start + duration

        if previous_start <= local_now <= previous_end:
            return {
                "status": "active",
                "starts_at": previous_start,
                "ends_at": previous_end,
                "timezone": window.timezone,
                "recurring": True,
            }

    next_start = rule.after(local_now, inc=False)

    if next_start:
        return {
            "status": "scheduled",
            "starts_at": next_start,
            "ends_at": next_start + duration,
            "timezone": window.timezone,
            "recurring": True,
        }

    if previous_start:
        return {
            "status": "finished",
            "starts_at": previous_start,
            "ends_at": previous_start + duration,
            "timezone": window.timezone,
            "recurring": True,
        }

    return {
        "status": status,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "timezone": window.timezone,
        "recurring": True,
    }


def get_effective_window_status(window, now=None):
    status = window.status or "scheduled"

    if status == "cancelled":
        return "cancelled"

    if status not in ("scheduled", "active"):
        return status

    if getattr(window, "rrule", None):
        recurring_status = _get_recurring_window_status(window, now=now)

        if recurring_status:
            return recurring_status

    starts_at = as_naive_datetime(window.starts_at)
    ends_at = as_naive_datetime(window.ends_at)
    local_now = _window_local_now(window, now=now)

    if starts_at and local_now < starts_at:
        return "scheduled"

    if ends_at and local_now > ends_at:
        return "finished"

    return "active"


def is_window_active_now(window, now=None):
    if not window:
        return False

    if getattr(window, "deleted", False):
        return False

    if getattr(window, "enabled", True) is False:
        return False

    return get_effective_window_status(window, now=now) == "active"


def get_maintenance_window(window_id):
    return MaintenanceWindow.get_or_none(
        MaintenanceWindow.id == window_id,
        MaintenanceWindow.deleted == False,  # noqa: E712
    )


def list_maintenance_windows(
    *,
    group_id=None,
    team_id=None,
    service_id=None,
    route_id=None,
    include_deleted=False,
    include_finished=True,
):
    query = (
        MaintenanceWindow
        .select(MaintenanceWindow)
        .distinct()
        .join(
            MaintenanceWindowScope,
            JOIN.LEFT_OUTER,
            on=MaintenanceWindowScope.maintenance_window == MaintenanceWindow.id,
        )
        .switch(MaintenanceWindow)
        .order_by(
            MaintenanceWindow.starts_at.desc(),
            MaintenanceWindow.id.desc(),
        )
    )

    if not include_deleted:
        query = query.where(MaintenanceWindow.deleted == False)  # noqa: E712

    scope_filters = []

    if group_id:
        scope_filters.append(MaintenanceWindowScope.group == group_id)

    if team_id:
        scope_filters.append(MaintenanceWindowScope.team == team_id)

    if service_id:
        scope_filters.append(MaintenanceWindowScope.service == service_id)

    if route_id:
        scope_filters.append(MaintenanceWindowScope.route == route_id)

    if scope_filters:
        combined = scope_filters[0]

        for condition in scope_filters[1:]:
            combined = combined | condition

        query = query.where(combined)

    items = list(query)

    if not include_finished:
        items = [
            window
            for window in items
            if get_effective_window_status(window) != "finished"
        ]

    return items


def create_maintenance_window(
    *,
    name,
    starts_at,
    ends_at,
    behavior,
    timezone,
    description=None,
    rrule=None,
    enabled=True,
    apply_to_existing=False,
    reactivate_on_end=True,
    status="scheduled",
    group=None,
    team=None,
):
    return MaintenanceWindow.create(
        group=group,
        team=team,
        name=name,
        description=description,
        starts_at=as_naive_datetime(starts_at),
        ends_at=as_naive_datetime(ends_at),
        behavior=behavior,
        timezone=timezone,
        rrule=rrule,
        enabled=enabled,
        apply_to_existing=apply_to_existing,
        reactivate_on_end=reactivate_on_end,
        status=status,
    )


def update_maintenance_window(window, **fields):
    allowed_fields = {
        "group",
        "team",
        "name",
        "description",
        "starts_at",
        "ends_at",
        "behavior",
        "timezone",
        "rrule",
        "enabled",
        "apply_to_existing",
        "reactivate_on_end",
        "reconciled_at",
        "status",
    }

    for field_name, value in fields.items():
        if field_name not in allowed_fields:
            continue

        if field_name in ("starts_at", "ends_at"):
            value = as_naive_datetime(value)

        setattr(window, field_name, value)

    window.save()
    return window


def soft_delete_maintenance_window(window):
    window.deleted = True
    window.enabled = False
    window.save()

    return MaintenanceWindow.get_by_id(window.id)


def cancel_maintenance_window(window, *, cancelled_by=None, reason=None):
    window.status = "cancelled"
    window.enabled = False
    window.cancelled_by = cancelled_by
    window.cancelled_at = utc_now()
    window.cancel_reason = str(reason or "").strip() or None
    window.save()

    return window


def replace_maintenance_window_scopes(window_id, scopes):
    (
        MaintenanceWindowScope
        .delete()
        .where(MaintenanceWindowScope.maintenance_window == window_id)
        .execute()
    )

    rows = []

    for scope in scopes:
        rows.append(
            MaintenanceWindowScope.create(
                maintenance_window=window_id,
                scope_type=scope["scope_type"],
                group=scope.get("group_id"),
                team=scope.get("team_id"),
                service=scope.get("service_id"),
                route=scope.get("route_id"),
                created_at=utc_now(),
            )
        )

    return rows


def list_maintenance_window_scopes(window_id):
    return list(
        MaintenanceWindowScope
        .select()
        .where(MaintenanceWindowScope.maintenance_window == window_id)
        .order_by(MaintenanceWindowScope.id.asc())
    )


def list_active_maintenance_windows(
    *,
    group_id: int | None = None,
    team_id: int | None = None,
    service_id: int | None = None,
    route_id: int | None = None,
    now: datetime | None = None,
) -> list[MaintenanceWindow]:
    """Return every active window matching the supplied routing scope."""
    query = (
        MaintenanceWindow
        .select(MaintenanceWindow)
        .distinct()
        .join(MaintenanceWindowScope)
        .where(
            MaintenanceWindow.deleted == False,  # noqa: E712
            MaintenanceWindow.enabled == True,  # noqa: E712
            MaintenanceWindow.status.in_(ACTIVE_STATUSES),
        )
        .order_by(MaintenanceWindow.starts_at.desc(), MaintenanceWindow.id.desc())
    )

    conditions = []
    if group_id:
        conditions.append(
            (MaintenanceWindowScope.scope_type == "group")
            & (MaintenanceWindowScope.group == group_id)
        )
    if team_id:
        conditions.append(
            (MaintenanceWindowScope.scope_type == "team")
            & (MaintenanceWindowScope.team == team_id)
        )
    if service_id:
        conditions.append(
            (MaintenanceWindowScope.scope_type == "service")
            & (MaintenanceWindowScope.service == service_id)
        )
    if route_id:
        conditions.append(
            (MaintenanceWindowScope.scope_type == "route")
            & (MaintenanceWindowScope.route == route_id)
        )

    if not conditions:
        return []

    combined = conditions[0]
    for condition in conditions[1:]:
        combined = combined | condition

    return [
        window
        for window in query.where(combined)
        if is_window_active_now(window, now=now)
    ]


def list_unresolved_alert_groups_for_window(
    window: MaintenanceWindow,
    *,
    limit: int | None = None,
) -> list[AlertGroup]:
    """Return unresolved alert groups in any scope of one maintenance window."""
    conditions = []
    for scope in list_maintenance_window_scopes(window):
        if scope.scope_type == "group" and scope.group_id:
            team_ids = Team.select(Team.id).where(Team.group == scope.group_id)
            conditions.append(AlertGroup.team.in_(team_ids))
        elif scope.scope_type == "team" and scope.team_id:
            conditions.append(AlertGroup.team == scope.team_id)
        elif scope.scope_type == "service" and scope.service_id:
            conditions.append(AlertGroup.service == scope.service_id)
        elif scope.scope_type == "route" and scope.route_id:
            conditions.append(AlertGroup.route == scope.route_id)

    if not conditions:
        return []

    combined = conditions[0]
    for condition in conditions[1:]:
        combined = combined | condition

    query = (
        AlertGroup
        .select()
        .where(
            combined,
            AlertGroup.status != "resolved",
            AlertGroup.merged_into.is_null(True),
        )
        .distinct()
        .order_by(AlertGroup.id.asc())
    )
    if limit:
        query = query.limit(limit)
    return list(query)


def list_window_applications(
    window: MaintenanceWindow,
    *,
    active_only: bool = False,
) -> list[MaintenanceWindowAlertApplication]:
    query = (
        MaintenanceWindowAlertApplication
        .select()
        .where(MaintenanceWindowAlertApplication.maintenance_window == window.id)
        .order_by(MaintenanceWindowAlertApplication.id.asc())
    )
    if active_only:
        query = query.where(MaintenanceWindowAlertApplication.active == True)  # noqa: E712
    return list(query)


def list_group_applications(
    group: AlertGroup,
    *,
    active_only: bool = False,
) -> list[MaintenanceWindowAlertApplication]:
    query = (
        MaintenanceWindowAlertApplication
        .select()
        .where(MaintenanceWindowAlertApplication.alert_group == group.id)
        .order_by(MaintenanceWindowAlertApplication.applied_at.desc())
    )
    if active_only:
        query = query.where(MaintenanceWindowAlertApplication.active == True)  # noqa: E712
    return list(query)


def get_window_group_application(
    window: MaintenanceWindow,
    group: AlertGroup,
) -> MaintenanceWindowAlertApplication | None:
    return MaintenanceWindowAlertApplication.get_or_none(
        MaintenanceWindowAlertApplication.maintenance_window == window.id,
        MaintenanceWindowAlertApplication.alert_group == group.id,
    )


def find_active_maintenance_window(
    *,
    group_id: int | None = None,
    team_id: int | None = None,
    service_id: int | None = None,
    route_id: int | None = None,
    now: datetime | None = None,
) -> MaintenanceWindow | None:
    """Return the highest-priority active window for intake-time behavior."""
    windows = list_active_maintenance_windows(
        group_id=group_id,
        team_id=team_id,
        service_id=service_id,
        route_id=route_id,
        now=now,
    )

    if not windows:
        return None

    behavior_priority = {
        "suppress_incident": 0,
        "create_maintenance_incident": 1,
        "suppress_notifications": 2,
        "pause_escalation_only": 3,
    }
    return sorted(
        windows,
        key=lambda item: (behavior_priority.get(item.behavior, 99), -item.id),
    )[0]
