from datetime import timedelta
from types import SimpleNamespace

from app.modules.common import utc_now
from app.modules.db import alerts_repo, incidents_repo
from app.modules.db.models import AlertEvent, AlertGroup, UserNotificationDelivery
from app.services.alerts.actions import acknowledge_alert
from app.services.alerts.lifecycle import upsert_alert
import app.services.alerts.lifecycle as alert_lifecycle
from app.services.alerts import notification_queue, reminders as alert_reminders
from app.services.incidents.priority_policies.resolver import PriorityResolution
from app.services.notifications import delivery as notification_delivery
from tests.factories import (
    create_group,
    create_rotation,
    create_route,
    create_team,
    create_user,
)


def _alert_payload(
    route,
    *,
    dedup_key,
    alertname="DiskUsage",
    severity="warning",
    incident_key="host/node/host1",
):
    return {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "external_id": f"external-{dedup_key}",
        "dedup_key": dedup_key,
        "title": alertname,
        "message": f"{alertname} on host1",
        "severity": severity,
        "labels": {
            "alertname": alertname,
            "instance": "host1",
            "severity": severity,
            "incident_key": incident_key,
        },
        "payload": {},
        "status": "firing",
    }


def _incident_key_route(*, rotation=None):
    group = create_group()
    team = create_team(group)
    route = create_route(
        team,
        source="alertmanager",
        rotation=rotation,
        group_by=["labels.incident_key"],
    )
    return group, team, route


def _event_count(group_id, event_type):
    return (
        AlertEvent.select()
        .where(
            (AlertEvent.group == group_id)
            & (AlertEvent.event_type == event_type)
        )
        .count()
    )


def test_same_priority_incident_key_child_preserves_acknowledgement(db):
    _group, _team, route = _incident_key_route()

    first = upsert_alert(
        _alert_payload(route, dedup_key="ack-same-1", severity="warning")
    )
    acknowledged = acknowledge_alert(first.group.id)
    acknowledged_at = acknowledged.acknowledged_at

    second = upsert_alert(
        _alert_payload(
            route,
            dedup_key="ack-same-2",
            alertname="DiskUsageStillHigh",
            severity="warning",
        )
    )

    stored = AlertGroup.get_by_id(first.group.id)

    assert second.group.id == first.group.id
    assert stored.status == "acknowledged"
    assert stored.acknowledged_at == acknowledged_at
    assert stored.priority_slug == "p3"
    assert _event_count(stored.id, "reopened") == 0


def test_lower_priority_incident_key_child_preserves_acknowledgement(db):
    _group, _team, route = _incident_key_route()

    first = upsert_alert(
        _alert_payload(route, dedup_key="ack-lower-1", severity="critical")
    )
    acknowledge_alert(first.group.id)

    second = upsert_alert(
        _alert_payload(
            route,
            dedup_key="ack-lower-2",
            alertname="DiskUsageWarning",
            severity="warning",
        )
    )

    stored = AlertGroup.get_by_id(first.group.id)

    assert second.group.id == first.group.id
    assert stored.status == "acknowledged"
    assert stored.priority_slug == "p1"
    assert _event_count(stored.id, "reopened") == 0


def test_higher_priority_incident_key_child_reopens_and_resets_escalation(db):
    _group, _team, route = _incident_key_route()

    first = upsert_alert(
        _alert_payload(route, dedup_key="ack-raise-1", severity="warning")
    )
    acknowledge_alert(first.group.id)

    stale = AlertGroup.get_by_id(first.group.id)
    stale.escalation_level = 4
    stale.escalation_repeat_count = 2
    stale.reminder_count = 7
    stale.last_escalated_at = utc_now() - timedelta(minutes=10)
    stale.next_escalation_at = utc_now() - timedelta(minutes=5)
    stale.save()

    second = upsert_alert(
        _alert_payload(
            route,
            dedup_key="ack-raise-2",
            alertname="DiskUsageCritical",
            severity="critical",
        )
    )

    stored = AlertGroup.get_by_id(first.group.id)

    assert second.group.id == first.group.id
    assert stored.status == "firing"
    assert stored.acknowledged_at is None
    assert stored.acknowledged_by_id is None
    assert stored.priority_slug == "p1"
    assert stored.escalation_level == 0
    assert stored.escalation_repeat_count == 0
    assert stored.reminder_count == 0
    assert stored.last_escalated_at is None
    assert stored.next_escalation_at is None
    assert _event_count(stored.id, "reopened") == 1


def test_multi_field_incident_key_route_keeps_normal_reopen_behavior(db):
    group = create_group()
    team = create_team(group)
    route = create_route(
        team,
        source="alertmanager",
        group_by=["labels.incident_key", "labels.instance"],
    )

    first = upsert_alert(
        _alert_payload(route, dedup_key="ack-multi-1", severity="warning")
    )
    acknowledge_alert(first.group.id)

    second = upsert_alert(
        _alert_payload(
            route,
            dedup_key="ack-multi-2",
            alertname="DiskUsageStillHigh",
            severity="warning",
        )
    )

    stored = AlertGroup.get_by_id(first.group.id)

    assert second.group.id == first.group.id
    assert stored.status == "firing"
    assert stored.acknowledged_at is None
    assert _event_count(stored.id, "reopened") == 1


def test_orchestration_group_key_override_disables_sticky_ack():
    group = SimpleNamespace(
        priority_order=1,
        priority_set_manually=False,
        common_labels={"incident_key": "host/node/host1"},
    )
    route = SimpleNamespace(group_by=["labels.incident_key"])
    resolution = PriorityResolution(
        priority=SimpleNamespace(level=1),
        source="test",
    )

    assert alert_lifecycle._should_preserve_acknowledgement(
        group,
        {"labels": {"incident_key": "host/node/host1"}},
        route,
        resolution,
        group_key_overridden=True,
    ) is False


def test_manual_priority_prevents_correlated_child_from_reopening_ack(db):
    _group, _team, route = _incident_key_route()

    first = upsert_alert(
        _alert_payload(route, dedup_key="ack-manual-1", severity="warning")
    )
    incidents_repo.set_incident_priority(first.group.id, "p4", manual=True)
    acknowledge_alert(first.group.id)

    second = upsert_alert(
        _alert_payload(
            route,
            dedup_key="ack-manual-2",
            alertname="DiskUsageCritical",
            severity="critical",
        )
    )

    stored = AlertGroup.get_by_id(first.group.id)

    assert second.group.id == first.group.id
    assert stored.status == "acknowledged"
    assert stored.priority_slug == "p4"
    assert stored.priority_set_manually is True
    assert _event_count(stored.id, "reopened") == 0


def test_initial_only_priority_does_not_reopen_correlated_ack(db, monkeypatch):
    _group, _team, route = _incident_key_route()

    first = upsert_alert(
        _alert_payload(route, dedup_key="ack-initial-1", severity="warning")
    )
    acknowledge_alert(first.group.id)

    p1 = incidents_repo.get_priority_by_slug("p1")
    monkeypatch.setattr(
        "app.services.alerts.lifecycle.resolve_incident_priority",
        lambda *args, **kwargs: PriorityResolution(
            priority=p1,
            source="policy_rule",
            update_mode="initial_only",
        ),
    )

    second = upsert_alert(
        _alert_payload(
            route,
            dedup_key="ack-initial-2",
            alertname="DiskUsageCritical",
            severity="critical",
        )
    )

    stored = AlertGroup.get_by_id(first.group.id)

    assert second.group.id == first.group.id
    assert stored.status == "acknowledged"
    assert stored.priority_slug == "p3"
    assert _event_count(stored.id, "reopened") == 0


def test_non_incident_key_grouping_still_reopens_acknowledged_group(db):
    group = create_group()
    team = create_team(group)
    route = create_route(
        team,
        source="alertmanager",
        group_by=["alertname"],
    )

    first = upsert_alert(
        _alert_payload(
            route,
            dedup_key="ack-normal-1",
            alertname="DiskUsage",
            severity="warning",
        )
    )
    acknowledge_alert(first.group.id)

    second = upsert_alert(
        _alert_payload(
            route,
            dedup_key="ack-normal-2",
            alertname="DiskUsage",
            severity="warning",
        )
    )

    stored = AlertGroup.get_by_id(first.group.id)

    assert second.group.id == first.group.id
    assert stored.status == "firing"
    assert stored.acknowledged_at is None
    assert _event_count(stored.id, "reopened") == 1


def test_ack_cancels_queued_group_and_user_notification_work(db):
    group, _team, route = _incident_key_route()
    user = create_user(group=group)
    result = upsert_alert(_alert_payload(route, dedup_key="ack-cancel-1"))

    alert_group = AlertGroup.get_by_id(result.group.id)
    alert_group.notification_pending = True
    alert_group.notification_due_at = utc_now() + timedelta(minutes=1)
    alert_group.notification_reason = "notification"
    alert_group.save()

    deliveries = {}
    for event_type in ("notification", "reminder", "escalation", "resolved"):
        deliveries[event_type] = UserNotificationDelivery.create(
            group=alert_group.id,
            user=user.id,
            method="email",
            event_type=event_type,
            status="pending",
            scheduled_at=utc_now() + timedelta(minutes=5),
        )

    acknowledge_alert(alert_group.id, user_id=user.id)

    stored_group = AlertGroup.get_by_id(alert_group.id)
    assert stored_group.notification_pending is False
    assert stored_group.notification_due_at is None
    assert stored_group.notification_reason is None

    for event_type in ("notification", "reminder", "escalation"):
        stored = UserNotificationDelivery.get_by_id(deliveries[event_type].id)
        assert stored.status == "skipped"
        assert stored.provider_status == "skipped"
        assert stored.last_error == "alert_acknowledged"

    assert UserNotificationDelivery.get_by_id(deliveries["resolved"].id).status == "pending"

    # Repeated ACK remains idempotent but still cleans work queued by a racing
    # worker after the first acknowledgement.
    late = UserNotificationDelivery.create(
        group=alert_group.id,
        user=user.id,
        method="email",
        event_type="reminder",
        status="pending",
        scheduled_at=utc_now() + timedelta(minutes=5),
    )
    acknowledge_alert(alert_group.id, user_id=user.id)
    assert UserNotificationDelivery.get_by_id(late.id).status == "skipped"
    assert _event_count(alert_group.id, "acknowledged") == 1


def test_reminder_scheduler_reloads_group_after_batch_selection(db, monkeypatch):
    group = create_group()
    team = create_team(group)
    rotation = create_rotation(team)
    route = create_route(
        team,
        source="alertmanager",
        rotation=rotation,
        group_by=["alertname"],
    )
    result = upsert_alert(
        _alert_payload(
            route,
            dedup_key="ack-race-reminder",
            alertname="DiskUsage",
        )
    )

    alert_group = AlertGroup.get_by_id(result.group.id)
    alert_group.last_notification_at = utc_now() - timedelta(minutes=10)
    alert_group.notification_pending = False
    alert_group.save()

    stale_firing_group = AlertGroup.get_by_id(alert_group.id)
    alerts_repo.acknowledge_alert_group(alert_group.id)

    monkeypatch.setattr(
        alert_reminders.alerts_repo,
        "list_firing_alert_groups",
        lambda: [stale_firing_group],
    )
    monkeypatch.setattr(
        alert_reminders,
        "notify_alert",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("acknowledged incident must not receive a reminder")
        ),
    )

    assert alert_reminders.send_unacked_reminders() == 0
    assert AlertGroup.get_by_id(alert_group.id).status == "acknowledged"


def test_due_notification_queue_does_not_resurrect_acknowledged_group(
    db,
    monkeypatch,
):
    group, _team, route = _incident_key_route()
    result = upsert_alert(_alert_payload(route, dedup_key="ack-race-queue"))

    alert_group = AlertGroup.get_by_id(result.group.id)
    alert_group.notification_pending = True
    alert_group.notification_due_at = utc_now() - timedelta(seconds=1)
    alert_group.notification_reason = "notification"
    alert_group.save()

    stale_due_group = AlertGroup.get_by_id(alert_group.id)
    acknowledge_alert(alert_group.id)

    monkeypatch.setattr(
        notification_queue.alerts_repo,
        "list_due_alert_group_notifications",
        lambda **kwargs: [stale_due_group],
    )
    monkeypatch.setattr(
        notification_queue,
        "notify_alert",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("ACKed group must not be delivered or reopened")
        ),
    )

    result = notification_queue.process_due_alert_group_notifications()
    stored = AlertGroup.get_by_id(alert_group.id)

    assert result == {"processed": 1, "sent": 0, "skipped": 1, "failed": 0}
    assert stored.status == "acknowledged"
    assert stored.notification_pending is False


def test_notify_alert_rechecks_firing_status_before_delivery(db, monkeypatch):
    _group, _team, route = _incident_key_route()
    result = upsert_alert(_alert_payload(route, dedup_key="ack-race-delivery"))

    stale_firing_group = AlertGroup.get_by_id(result.group.id)
    alerts_repo.acknowledge_alert_group(result.group.id)

    monkeypatch.setattr(
        notification_delivery,
        "_notification_targets",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("delivery targets must not be resolved after ACK")
        ),
    )

    assert notification_delivery.notify_alert(
        stale_firing_group,
        event_type="reminder",
    ) == 0
