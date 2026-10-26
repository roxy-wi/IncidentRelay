from app.db import database_proxy as db
from app.modules.db import alerts_repo, audit_repo
from app.modules.redaction import redact_secrets
from app.modules.db.models import AlertGroup
from app.services.alerts.correlation import refresh_alert_group_correlations_safely
from app.services.alerts.shelving import clear_shelve_on_resolve
from app.services.incidents.stakeholders import notify_stakeholders
from app.services.notifications.delivery import update_alert_messages
from app.services.notifications.rules import cancel_pending_group_deliveries
from app.services.business_services.impact import refresh_business_impacts_safely_for_group
from app.services.business_services.status import refresh_business_services_safely_for_technical_service


ACK_CANCELLED_DELIVERY_EVENT_TYPES = frozenset({
    "notification",
    "reminder",
    "escalation",
})


def _cancel_acknowledged_notification_work(group):
    """Cancel queued notification work that predates an acknowledgement."""

    if getattr(group, "notification_pending", False):
        alerts_repo.clear_alert_group_notification(group)

    return cancel_pending_group_deliveries(
        group,
        event_types=ACK_CANCELLED_DELIVERY_EVENT_TYPES,
        reason="alert_acknowledged",
    )


def _audit_lifecycle_change(
    group, action, *, user_id=None, source="system", api_token_id=None,
):
    """Persist a canonical audit record for a successful AlertGroup transition."""
    audit_repo.create_audit_log(
        action=f"alert_group.{action}",
        object_type="alert_group",
        object_id=group.id,
        group_id=group.team.group_id if group.team_id and group.team else None,
        team_id=group.team_id,
        user_id=user_id,
        api_token_id=api_token_id,
        data=redact_secrets({"source": source}),
    )


def _lock_group_for_lifecycle(group_id):
    """Serialize lifecycle changes on the same AlertGroup under PostgreSQL."""
    query = AlertGroup.select().where(AlertGroup.id == group_id)
    database = getattr(db, "obj", None)
    if database is not None and database.__class__.__name__ != "SqliteDatabase":
        query = query.for_update()
    return query.get()


def acknowledge_alert(alert_id, user_id=None, *, source="system", api_token_id=None):
    """Acknowledge an alert group."""
    with db.atomic():
        group_before = _lock_group_for_lifecycle(alert_id)
        old_status = group_before.status

        # Repeated acknowledge is a no-op, even across concurrent workers.
        if old_status == "acknowledged":
            _cancel_acknowledged_notification_work(group_before)
            return group_before
        # Late callbacks must not resurrect terminal or merged groups.
        if old_status in {"resolved", "merged"} or group_before.merged_into_id:
            return group_before

        group = alerts_repo.acknowledge_alert_group(alert_id, user_id=user_id)
        _cancel_acknowledged_notification_work(group)
        alerts_repo.create_alert_event(
            group_id=group.id,
            event_type="acknowledged",
            message="Alert group acknowledged",
            user_id=user_id,
        )
        _audit_lifecycle_change(
            group, "ack", user_id=user_id, source=source,
            api_token_id=api_token_id,
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
        pass  # Incident collaboration is independent of AlertGroup.

    return group


def resolve_alert(
    alert_id: int,
    user_id: int | None = None,
    *,
    update_messages: bool = True,
    defer_stakeholder_notification: bool = False,
    source: str = "system",
    api_token_id: int | None = None,
) -> AlertGroup:
    """Resolve an alert group."""
    with db.atomic():
        group_before = _lock_group_for_lifecycle(alert_id)
        old_status = group_before.status

        # Repeated resolve is a no-op, even across concurrent workers.
        if old_status in {"resolved", "merged"} or group_before.merged_into_id:
            return group_before

        group = alerts_repo.resolve_alert_group(alert_id, user_id=user_id)
        # A manual resolve must not leave a stale firing group_wait job behind.
        alerts_repo.clear_alert_group_notification(group)
        clear_shelve_on_resolve(group.id, user_id=user_id, api_token_id=api_token_id)
        alerts_repo.create_alert_event(
            group_id=group.id,
            event_type="resolved",
            message="Alert group resolved",
            user_id=user_id,
        )
        _audit_lifecycle_change(
            group, "resolve", user_id=user_id, source=source,
            api_token_id=api_token_id,
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

    if old_status != group.status and not defer_stakeholder_notification:
        pass  # Incident collaboration is independent of AlertGroup.

    return group
