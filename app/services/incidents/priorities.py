from app.db import database_proxy as db
from app.modules.db import alerts_repo, audit_repo, incidents_repo
from app.services.notifications.delivery import update_alert_messages
from app.services.incidents.priority_policies import service as policy_service
from app.services.incidents.priority_policies.constants import (
    FALLBACK_FIXED_PRIORITY,
    UPDATE_MODE_INITIAL_ONLY,
    UPDATE_MODE_RAISE_ONLY,
    UPDATE_MODE_RECALCULATE,
)


def _record_priority_audit(group, action, *, user_id, source, old_priority, api_token_id=None):
    """Record a manual priority transition in the same DB transaction."""
    audit_repo.create_audit_log(
        action=action,
        object_type="alert_group",
        object_id=group.id,
        group_id=group.team.group_id if group.team_id and group.team else None,
        team_id=group.team_id,
        user_id=user_id,
        api_token_id=api_token_id,
        data={
            "source": source,
            "from": old_priority,
            "to": group.priority_slug,
            "manual": bool(group.priority_set_manually),
        },
    )


def set_incident_priority(*, group_id, priority, user_id=None, source="system", api_token_id=None):
    if not priority:
        raise ValueError("priority is required")

    group = alerts_repo.get_alert_group(group_id)

    if not group:
        raise LookupError("incident not found")

    # Validate before the no-op fast path: disabled/deleted priority slugs
    # must not become accepted just because the current row still holds them.
    if not incidents_repo.get_priority_by_slug(priority):
        raise ValueError("priority must be one of enabled incident priorities")

    old_priority = group.priority_slug
    if old_priority == priority and group.priority_set_manually:
        return group

    with db.atomic():
        group = incidents_repo.set_incident_priority(
            group.id,
            priority,
            user_id=user_id,
            manual=True,
        )
        _record_priority_audit(
            group, "alert_group.priority.set", user_id=user_id,
            source=source, old_priority=old_priority,
            api_token_id=api_token_id,
        )

    if old_priority != group.priority_slug:
        update_alert_messages(group, event_type="priority_changed")
        pass  # Incident collaboration is independent of AlertGroup.

    return group


def _enabled_alert_priority(alert):
    priority = alert.priority if getattr(alert, "priority_id", None) else None

    if priority and priority.enabled:
        return priority

    return None


def _policy_fallback_priority(group, policy):
    if policy and policy.fallback_mode == FALLBACK_FIXED_PRIORITY and policy.fallback_priority_id:
        priority = policy.fallback_priority

        if priority and priority.enabled:
            return priority

    return incidents_repo.priority_from_severity(group.severity) or incidents_repo.get_default_priority()


def resolve_automatic_incident_priority(group):
    """Rebuild automatic incident priority from stored child alert decisions."""
    policy = policy_service.get_effective_policy(team_id=group.team_id, service=group.service)
    update_mode = getattr(policy, "update_mode", None) or UPDATE_MODE_RAISE_ONLY
    alerts = alerts_repo.list_alerts_for_group(group.id)
    alerts_with_priority = [alert for alert in alerts if _enabled_alert_priority(alert)]

    if update_mode == UPDATE_MODE_INITIAL_ONLY and alerts_with_priority:
        return _enabled_alert_priority(alerts_with_priority[0]), update_mode

    if update_mode == UPDATE_MODE_RECALCULATE:
        active_alerts = [alert for alert in alerts_with_priority if alert.status != "resolved"]

        if active_alerts:
            alert = min(active_alerts, key=lambda item: item.priority_order or 999)
            return _enabled_alert_priority(alert), update_mode

        return _policy_fallback_priority(group, policy), update_mode

    if alerts_with_priority:
        alert = min(alerts_with_priority, key=lambda item: item.priority_order or 999)
        return _enabled_alert_priority(alert), update_mode

    return _policy_fallback_priority(group, policy), update_mode


def reset_incident_priority(*, group_id, user_id=None, source="system", api_token_id=None):
    group = alerts_repo.get_alert_group(group_id)

    if not group:
        raise LookupError("incident not found")

    if not group.priority_set_manually:
        return group

    old_priority = group.priority_slug
    priority, update_mode = resolve_automatic_incident_priority(group)

    if not priority:
        raise ValueError("automatic priority could not be resolved")

    with db.atomic():
        group = incidents_repo.reset_incident_priority(
            group.id, priority, update_mode=update_mode,
        )
        _record_priority_audit(
            group, "alert_group.priority.reset", user_id=user_id,
            source=source, old_priority=old_priority,
            api_token_id=api_token_id,
        )

    if old_priority != group.priority_slug:
        update_alert_messages(group, event_type="priority_changed")
        pass  # Incident collaboration is independent of AlertGroup.

    return group
