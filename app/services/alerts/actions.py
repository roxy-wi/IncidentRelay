from app.modules.db import alerts_repo
from app.modules.db.models import AlertGroup
from app.services.alerts.correlation import refresh_alert_group_correlations_safely
from app.services.incidents.stakeholders import notify_stakeholders
from app.services.notifications.delivery import update_alert_messages
from app.services.business_services.impact import refresh_business_impacts_safely_for_group
from app.services.business_services.status import refresh_business_services_safely_for_technical_service


def acknowledge_alert(alert_id, user_id=None):
    """Acknowledge an alert group."""
    group_before = alerts_repo.get_alert_group(alert_id)
    old_status = getattr(group_before, "status", None)

    # Repeated acknowledge is a no-op. This preserves the original
    # acknowledged_at/user and avoids duplicate timeline/notification effects.
    if old_status == "acknowledged":
        return group_before

    group = alerts_repo.acknowledge_alert_group(alert_id, user_id=user_id)

    alerts_repo.create_alert_event(
        group_id=group.id,
        event_type="acknowledged",
        message="Alert group acknowledged",
        user_id=user_id,
    )

    refresh_alert_group_correlations_safely(group, reason="manual_acknowledge")

    if getattr(group, "service_id", None):
        refresh_business_services_safely_for_technical_service(
            group.service_id,
            reason="manual_acknowledge",
        )

    refresh_business_impacts_safely_for_group(group, reason="manual_acknowledge")

    update_alert_messages(group, event_type="acknowledged")

    if old_status != group.status:
        notify_stakeholders(
            group,
            "status_changed",
            old_value=old_status,
        )

    return group


def resolve_alert(
    alert_id: int,
    user_id: int | None = None,
    *,
    update_messages: bool = True,
) -> AlertGroup:
    """Resolve an alert group."""
    group_before = alerts_repo.get_alert_group(alert_id)
    old_status = getattr(group_before, "status", None)

    # Repeated resolve is a no-op. Keep the original resolved_at/user and
    # avoid duplicate timeline, impact and outbound-message side effects.
    if old_status == "resolved":
        return group_before

    group = alerts_repo.resolve_alert_group(alert_id, user_id=user_id)

    alerts_repo.create_alert_event(
        group_id=group.id,
        event_type="resolved",
        message="Alert group resolved",
        user_id=user_id,
    )

    refresh_alert_group_correlations_safely(group, reason="manual_resolve")

    if getattr(group, "service_id", None):
        refresh_business_services_safely_for_technical_service(
            group.service_id,
            reason="manual_resolve",
        )

    refresh_business_impacts_safely_for_group(group, reason="manual_resolve")

    if update_messages:
        update_alert_messages(group, event_type="resolved")

    if old_status != group.status:
        notify_stakeholders(
            group,
            "resolved",
            old_value=old_status,
        )

    return group
