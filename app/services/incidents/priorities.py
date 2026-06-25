from app.modules.db import alerts_repo, incidents_repo
from app.services.incidents.stakeholders import notify_stakeholders
from app.services.notifications.delivery import update_alert_messages
from app.services.incidents.priority_policies import service as policy_service
from app.services.incidents.priority_policies.constants import (
    FALLBACK_FIXED_PRIORITY,
    UPDATE_MODE_INITIAL_ONLY,
    UPDATE_MODE_RAISE_ONLY,
    UPDATE_MODE_RECALCULATE,
)


def set_incident_priority(*, group_id, priority, user_id=None):
    if not priority:
        raise ValueError("priority is required")

    group = alerts_repo.get_alert_group(group_id)

    if not group:
        raise LookupError("incident not found")

    old_priority = group.priority_slug

    group = incidents_repo.set_incident_priority(
        group.id,
        priority,
        user_id=user_id,
        manual=True,
    )

    if old_priority != group.priority_slug:
        update_alert_messages(group, event_type="priority_changed")
        notify_stakeholders(
            group,
            "priority_changed",
            old_value=old_priority,
        )

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


def reset_incident_priority(*, group_id):
    group = alerts_repo.get_alert_group(group_id)

    if not group:
        raise LookupError("incident not found")

    if not group.priority_set_manually:
        return group

    old_priority = group.priority_slug
    priority, update_mode = resolve_automatic_incident_priority(group)

    if not priority:
        raise ValueError("automatic priority could not be resolved")

    group = incidents_repo.reset_incident_priority(group.id, priority, update_mode=update_mode)

    if old_priority != group.priority_slug:
        update_alert_messages(group, event_type="priority_changed")
        notify_stakeholders(group, "priority_changed", old_value=old_priority)

    return group
