from app.modules.db import alerts_repo, users_repo
from app.services.alerts.correlation import refresh_alert_group_correlations_safely
from app.services.incidents.stakeholders import notify_stakeholders
from app.services.notifications.delivery import update_alert_messages


def acknowledge_alert(alert_id, user_id=None):
    """Acknowledge an alert group."""
    group_before = alerts_repo.get_alert_group(alert_id)
    old_status = getattr(group_before, "status", None)

    group = alerts_repo.acknowledge_alert_group(alert_id, user_id=user_id)

    alerts_repo.create_alert_event(
        group_id=group.id,
        event_type="acknowledged",
        message="Alert group acknowledged",
        user_id=user_id,
    )

    refresh_alert_group_correlations_safely(group, reason="manual_acknowledge")
    update_alert_messages(group, event_type="acknowledged")

    if old_status != group.status:
        notify_stakeholders(group, "status_changed", old_value=old_status)

    return group


def resolve_alert(alert_id, user_id=None):
    """Resolve an alert group."""
    group_before = alerts_repo.get_alert_group(alert_id)
    old_status = getattr(group_before, "status", None)

    group = alerts_repo.resolve_alert_group(alert_id, user_id=user_id)

    alerts_repo.create_alert_event(
        group_id=group.id,
        event_type="resolved",
        message="Alert group resolved",
        user_id=user_id,
    )

    refresh_alert_group_correlations_safely(group, reason="manual_resolve")
    update_alert_messages(group, event_type="resolved")

    if old_status != group.status:
        notify_stakeholders(group, "resolved", old_value=old_status)

    return group


def attach_action_user(alert, user_id):
    """Attach the action user to the alert object for notification formatting."""
    if not user_id:
        alert._action_user = None
        return alert

    alert._action_user = users_repo.get_user_or_none(user_id)
    return alert
