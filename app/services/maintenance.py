import logging
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.rrule import rrulestr

from app.db import database_proxy as db

from app.modules.db import maintenance_repo
from app.modules.db.models import AlertRoute, Group, MaintenanceWindow, Service, Team, User
from app.services import rbac
from app.services.audit import record_audit
from app.services.serializers.common import serialize_utc_datetime
from app.modules.common import as_naive_datetime

logger = logging.getLogger("oncall.maintenance")


def _maintenance_audit_payload(payload):
    data = dict(payload or {})
    for key in ("starts_at", "ends_at"):
        value = data.get(key)
        if value is not None and hasattr(value, "isoformat"):
            data[key] = value.isoformat()
    return data


def _record_maintenance_command(action, window, *, user_id, api_token_id, payload=None):
    """Persist the command audit in the same transaction as window/scopes."""
    data = {
        "name": window.name,
        "status": window.status,
        "behavior": window.behavior,
        "timezone": window.timezone,
        "starts_at": serialize_utc_datetime(window.starts_at),
        "ends_at": serialize_utc_datetime(window.ends_at),
        "enabled": window.enabled,
        "apply_to_existing": bool(window.apply_to_existing),
        "reactivate_on_end": bool(window.reactivate_on_end),
        "deleted": window.deleted,
    }
    if getattr(window, "rrule", None):
        data["rrule"] = window.rrule
    if payload:
        data["payload"] = _maintenance_audit_payload(payload)
    return record_audit(
        action=action,
        object_type="maintenance_window",
        object_id=window.id,
        group_id=window.group_id,
        team_id=window.team_id,
        user_id=user_id,
        api_token_id=api_token_id,
        data=data,
    )


def _reconcile_after_command(window, *, user_id, api_token_id, force_release=False):
    """Reconcile after the short configuration/audit transaction commits.

    The periodic scheduler rechecks every window and can repair a transient
    reconciliation failure. Holding a DB transaction across all matching
    AlertGroups would otherwise create unbounded locks and timeout risks.
    """
    from app.services.alerts.maintenance_state import reconcile_maintenance_window

    try:
        reconcile_maintenance_window(
            window,
            trigger_source="api",
            actor_user_id=user_id,
            api_token_id=api_token_id,
            force_release=force_release,
        )
    except Exception:
        logger.exception(
            "maintenance window reconciliation deferred to scheduler",
            extra={"extra": {"window_id": window.id, "user_id": user_id}},
        )


VALID_BEHAVIORS = {
    "suppress_notifications",
    "suppress_incident",
    "create_maintenance_incident",
    "pause_escalation_only",
}

VALID_SCOPE_TYPES = {
    "group",
    "team",
    "service",
    "route",
}

VALID_STATUSES = {
    "scheduled",
    "active",
    "finished",
    "cancelled",
}


def _lock_maintenance_window(window_id):
    """Lock an existing window before replacing scopes or changing lifecycle.

    Only PostgreSQL uses ``SELECT FOR UPDATE``; SQLite serializes writes through
    its transaction. Never lock before entering a database transaction.
    """
    query = MaintenanceWindow.select().where(
        (MaintenanceWindow.id == window_id)
        & (MaintenanceWindow.deleted == False)  # noqa: E712
    )
    database = getattr(db, "obj", None)
    if database is not None and database.__class__.__name__ != "SqliteDatabase":
        query = query.for_update()
    return query.first()


@dataclass
class MaintenanceDecision:
    window: object | None = None
    behavior: str | None = None
    suppress_notifications: bool = False
    suppress_incident: bool = False
    pause_escalation_only: bool = False
    incident_status: str | None = None

    @property
    def matched(self):
        return self.window is not None


def _scope_target_id(scope, key):
    value = scope.get(key)

    if hasattr(value, "id"):
        return value.id

    return value


def _window_owner_from_scopes(scopes):
    for scope in scopes or []:
        scope_type = scope.get("scope_type")

        if scope_type == "group":
            group_id = _scope_target_id(scope, "group_id") or _scope_target_id(scope, "group")
            group = Group.get_or_none(Group.id == group_id)

            if group:
                return {
                    "group": group,
                    "team": None,
                }

        if scope_type == "team":
            team_id = _scope_target_id(scope, "team_id") or _scope_target_id(scope, "team")
            team = Team.get_or_none(Team.id == team_id)

            if team:
                return {
                    "group": team.group,
                    "team": team,
                }

        if scope_type == "service":
            service_id = _scope_target_id(scope, "service_id") or _scope_target_id(scope, "service")
            service = Service.get_or_none(Service.id == service_id)

            if service and service.team:
                return {
                    "group": service.team.group,
                    "team": service.team,
                }

        if scope_type == "route":
            route_id = _scope_target_id(scope, "route_id") or _scope_target_id(scope, "route")
            route = AlertRoute.get_or_none(AlertRoute.id == route_id)

            if route and route.team:
                return {
                    "group": route.team.group,
                    "team": route.team,
                }

    return {
        "group": None,
        "team": None,
    }


def _can_manage_scope(current_user, scope):
    if getattr(current_user, "is_admin", False):
        return True

    scope_type = scope.get("scope_type")

    if scope_type == "group":
        group_id = _scope_target_id(scope, "group_id") or _scope_target_id(scope, "group")
        return bool(group_id and rbac.can_write_group(current_user, group_id))

    if scope_type == "team":
        team_id = _scope_target_id(scope, "team_id") or _scope_target_id(scope, "team")
        return bool(team_id and rbac.can_write_team(current_user, team_id))

    if scope_type == "service":
        service_id = _scope_target_id(scope, "service_id") or _scope_target_id(scope, "service")
        service = Service.get_or_none(Service.id == service_id)

        return bool(
            service
            and service.team_id
            and rbac.can_write_team(current_user, service.team_id)
        )

    if scope_type == "route":
        route_id = _scope_target_id(scope, "route_id") or _scope_target_id(scope, "route")
        route = AlertRoute.get_or_none(AlertRoute.id == route_id)

        return bool(
            route
            and route.team_id
            and rbac.can_write_team(current_user, route.team_id)
        )

    return False


def _ensure_can_manage_scopes(current_user, scopes):
    for scope in scopes or []:
        if not _can_manage_scope(current_user, scope):
            raise PermissionError("access denied")


def _ensure_can_manage_existing_window(current_user, window):
    if getattr(current_user, "is_admin", False):
        return

    if window.team_id and rbac.can_write_team(current_user, window.team_id):
        return

    if window.group_id and rbac.can_write_group(current_user, window.group_id):
        return

    scopes = maintenance_repo.list_maintenance_window_scopes(window)

    for scope in scopes:
        scope_payload = {
            "scope_type": scope.scope_type,
            "group_id": scope.group_id,
            "team_id": scope.team_id,
            "service_id": scope.service_id,
            "route_id": scope.route_id,
        }

        if _can_manage_scope(current_user, scope_payload):
            return

    raise PermissionError("access denied")


def _get_user_or_raise(user_id):
    if not user_id:
        raise PermissionError("authentication required")

    user = User.get_or_none(User.id == user_id)

    if not user:
        raise PermissionError("authentication required")

    return user


def _local_now(timezone_name):
    try:
        zone = ZoneInfo(timezone_name or "UTC")
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")

    return datetime.now(zone).replace(tzinfo=None)


def normalize_rrule(value, starts_at):
    text = str(value or "").strip()

    if not text:
        return None

    if "\n" in text or "\r" in text:
        raise ValueError("rrule must be a single RRULE value")

    if text.upper().startswith("RRULE:"):
        text = text.split(":", 1)[1].strip()

    if not text:
        return None

    try:
        rrulestr(text, dtstart=starts_at)
    except (TypeError, ValueError) as exc:
        raise ValueError("rrule must be a valid RFC5545 RRULE") from exc

    return text


def parse_iso_datetime(value, field_name):
    if not value:
        raise ValueError(f"{field_name} is required")

    try:
        return as_naive_datetime(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be ISO datetime") from exc


def get_payload_datetime(payload, field_name, *, existing_window=None, partial=False):
    if field_name in payload:
        return parse_iso_datetime(payload.get(field_name), field_name)

    if partial and existing_window is not None:
        return getattr(existing_window, field_name)

    raise ValueError(f"{field_name} is required")


def normalize_scopes(scopes):
    if not scopes:
        raise ValueError("at least one scope is required")

    normalized = []

    for scope in scopes:
        scope_type = scope.get("scope_type")

        if scope_type not in VALID_SCOPE_TYPES:
            raise ValueError("scope_type must be one of: group, team, service, route")

        required_field = f"{scope_type}_id"

        if not scope.get(required_field):
            raise ValueError(f"{required_field} is required for {scope_type} scope")

        normalized.append({
            "scope_type": scope_type,
            "group_id": scope.get("group_id"),
            "team_id": scope.get("team_id"),
            "service_id": scope.get("service_id"),
            "route_id": scope.get("route_id"),
        })

    return normalized


def normalize_window_payload(payload, *, existing_window=None, partial=False):
    payload = payload or {}

    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")

    name = payload.get("name")
    if name is None and partial and existing_window is not None:
        name = existing_window.name

    name = str(name or "").strip()
    if not name:
        raise ValueError("name is required")

    description = payload.get("description")
    if description is None and partial and existing_window is not None:
        description = existing_window.description

    if description is not None:
        description = str(description).strip() or None

    behavior = payload.get("behavior")
    if behavior is None and partial and existing_window is not None:
        behavior = existing_window.behavior

    behavior = str(behavior or "suppress_notifications").strip()
    if behavior not in VALID_BEHAVIORS:
        raise ValueError("behavior is invalid")

    timezone_name = payload.get("timezone")
    if timezone_name is None and partial and existing_window is not None:
        timezone_name = existing_window.timezone

    timezone_name = str(timezone_name or "UTC").strip() or "UTC"

    starts_at_changed = "starts_at" in payload
    ends_at_changed = "ends_at" in payload
    timezone_changed = "timezone" in payload

    starts_at = get_payload_datetime(
        payload,
        "starts_at",
        existing_window=existing_window,
        partial=partial,
    )
    ends_at = get_payload_datetime(
        payload,
        "ends_at",
        existing_window=existing_window,
        partial=partial,
    )

    starts_at = as_naive_datetime(starts_at)
    ends_at = as_naive_datetime(ends_at)

    if ends_at <= starts_at:
        raise ValueError("ends_at must be greater than starts_at")

    should_validate_future = (
        not partial
        or starts_at_changed
        or ends_at_changed
        or timezone_changed
    )

    if should_validate_future and ends_at <= _local_now(timezone_name):
        raise ValueError("ends_at must be in the future")

    if "rrule" in payload:
        rrule = normalize_rrule(payload.get("rrule"), starts_at)
    elif partial and existing_window is not None:
        rrule = existing_window.rrule
    else:
        rrule = None

    if rrule:
        rrule = normalize_rrule(rrule, starts_at)

    apply_to_existing = payload.get("apply_to_existing")
    if apply_to_existing is None and partial and existing_window is not None:
        apply_to_existing = existing_window.apply_to_existing
    apply_to_existing = bool(apply_to_existing) if apply_to_existing is not None else False

    reactivate_on_end = payload.get("reactivate_on_end")
    if reactivate_on_end is None and partial and existing_window is not None:
        reactivate_on_end = existing_window.reactivate_on_end
    reactivate_on_end = True if reactivate_on_end is None else bool(reactivate_on_end)

    if behavior == "suppress_incident" and apply_to_existing:
        raise ValueError(
            "apply_to_existing is not supported for suppress_incident behavior"
        )

    enabled = payload.get("enabled")
    if enabled is None and partial and existing_window is not None:
        enabled = existing_window.enabled

    enabled = bool(enabled) if enabled is not None else True

    if "scopes" in payload:
        scopes = normalize_scopes(payload.get("scopes"))
    elif partial:
        scopes = None
    else:
        scopes = normalize_scopes(payload.get("scopes"))

    return {
        "name": name,
        "description": description,
        "behavior": behavior,
        "timezone": timezone_name,
        "rrule": rrule,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "enabled": enabled,
        "apply_to_existing": apply_to_existing,
        "reactivate_on_end": reactivate_on_end,
        "scopes": scopes,
    }


def create_maintenance_window(payload, *, user_id, api_token_id=None):
    user = _get_user_or_raise(user_id)
    data = normalize_window_payload(payload)
    scopes = data.pop("scopes")
    _ensure_can_manage_scopes(user, scopes)
    data.update(_window_owner_from_scopes(scopes))

    with db.atomic():
        window = maintenance_repo.create_maintenance_window(**data)
        maintenance_repo.replace_maintenance_window_scopes(window, scopes)
        _record_maintenance_command(
            "maintenance_window.create", window,
            user_id=user.id, api_token_id=api_token_id, payload=payload,
        )

    _reconcile_after_command(window, user_id=user.id, api_token_id=api_token_id)
    return window


def update_maintenance_window(window_id, payload, *, user_id, api_token_id=None):
    user = _get_user_or_raise(user_id)

    with db.atomic():
        window = _lock_maintenance_window(window_id)
        if not window:
            raise LookupError("maintenance window was not found")

        data = normalize_window_payload(payload, existing_window=window, partial=True)
        scopes = data.pop("scopes", None)
        if scopes is not None:
            _ensure_can_manage_scopes(user, scopes)
            data.update(_window_owner_from_scopes(scopes))
        else:
            _ensure_can_manage_existing_window(user, window)

        # Invalidate the previous reconciliation marker before the config commit.
        data["reconciled_at"] = None
        window = maintenance_repo.update_maintenance_window(window, **data)
        if scopes is not None:
            maintenance_repo.replace_maintenance_window_scopes(window, scopes)
        _record_maintenance_command(
            "maintenance_window.update", window,
            user_id=user.id, api_token_id=api_token_id, payload=payload,
        )

    _reconcile_after_command(window, user_id=user.id, api_token_id=api_token_id)
    return window


def cancel_maintenance_window(window_id, payload=None, *, user_id, api_token_id=None):
    user = _get_user_or_raise(user_id)

    with db.atomic():
        window = _lock_maintenance_window(window_id)
        if not window:
            raise LookupError("maintenance window was not found")
        _ensure_can_manage_existing_window(user, window)

        reason = payload.get("reason") if isinstance(payload, dict) else None
        window = maintenance_repo.cancel_maintenance_window(
            window, cancelled_by=user, reason=reason,
        )
        _record_maintenance_command(
            "maintenance_window.cancel", window,
            user_id=user.id, api_token_id=api_token_id, payload=payload,
        )

    _reconcile_after_command(window, user_id=user.id, api_token_id=api_token_id)
    return window


def delete_maintenance_window(window_id, *, user_id, api_token_id=None):
    user = _get_user_or_raise(user_id)

    with db.atomic():
        window = _lock_maintenance_window(window_id)
        if not window:
            raise LookupError("maintenance window was not found")
        _ensure_can_manage_existing_window(user, window)

        window = maintenance_repo.soft_delete_maintenance_window(window)
        _record_maintenance_command(
            "maintenance_window.delete", window,
            user_id=user.id, api_token_id=api_token_id,
            payload={"deleted": True},
        )

    _reconcile_after_command(
        window, user_id=user.id, api_token_id=api_token_id, force_release=True,
    )
    return window


def get_maintenance_decision(*, team=None, route=None, service=None, status=None, now=None):
    window = maintenance_repo.find_active_maintenance_window(
        group_id=team.group_id if team else None,
        team_id=team.id if team else None,
        service_id=service.id if service else None,
        route_id=route.id if route else None,
        now=now,
    )

    if not window:
        return MaintenanceDecision()

    behavior = window.behavior or "suppress_notifications"

    return MaintenanceDecision(
        window=window,
        behavior=behavior,
        suppress_notifications=behavior == "suppress_notifications",
        suppress_incident=behavior == "suppress_incident",
        pause_escalation_only=behavior == "pause_escalation_only",
        incident_status="maintenance" if behavior == "create_maintenance_incident" else None,
    )
