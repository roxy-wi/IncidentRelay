from datetime import timedelta

from app.modules.common import utc_now
from app.modules.db.models import AlertEvent, UserNotificationDelivery
from app.services.alerts.actions import acknowledge_alert, resolve_alert
from app.services.alerts.lifecycle import upsert_alert
from tests.factories import create_group, create_route, create_team, create_user


def _normalized_alert(route, *, status="firing", message="/var is 95% full"):
    return {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "external_id": "release-lifecycle-external-1",
        "dedup_key": "release-lifecycle-dedup-1",
        "title": "DiskFull",
        "message": message,
        "severity": "critical",
        "labels": {
            "alertname": "DiskFull",
            "severity": "critical",
            "instance": "host1",
        },
        "payload": {"source": "release-test"},
        "status": status,
    }


def _create_firing_group():
    group = create_group(slug="release-lifecycle")
    team = create_team(group, slug="release-lifecycle-team")
    route = create_route(
        team,
        source="alertmanager",
        group_by=["alertname", "severity", "instance"],
    )
    result = upsert_alert(_normalized_alert(route))
    assert result.group is not None
    assert result.alert is not None
    assert result.created_group is True
    return group, team, route, result.group, result.alert


def _event_count(alert_group_id, event_type):
    return (
        AlertEvent.select()
        .where(
            (AlertEvent.group == alert_group_id)
            & (AlertEvent.event_type == event_type)
        )
        .count()
    )


def test_acknowledge_alert_is_idempotent(monkeypatch, db):
    """
    Repeating the same manual acknowledge must not create another timeline
    event, update outbound messages again, or emit another stakeholder event.
    """
    group, _team, _route, alert_group, _alert = _create_firing_group()
    user = create_user("release-ack-user", group)

    alert_group.notification_pending = True
    alert_group.notification_due_at = utc_now() + timedelta(seconds=30)
    alert_group.notification_reason = "notification"
    alert_group.save()

    pending_delivery = UserNotificationDelivery.create(
        group=alert_group.id,
        user=user.id,
        method="voice_call",
        event_type="reminder",
        status="pending",
        scheduled_at=utc_now() + timedelta(minutes=5),
    )

    message_updates = []
    stakeholder_updates = []

    monkeypatch.setattr(
        "app.services.alerts.actions.update_alert_messages",
        lambda current_group, event_type: message_updates.append(
            (current_group.id, event_type)
        ) or 1,
    )
    monkeypatch.setattr(
        "app.services.alerts.actions.notify_stakeholders",
        lambda current_group, event_type, **kwargs: stakeholder_updates.append(
            (current_group.id, event_type, kwargs)
        ),
    )

    first = acknowledge_alert(alert_group.id, user_id=user.id)
    second = acknowledge_alert(alert_group.id, user_id=user.id)

    assert first.status == "acknowledged"
    assert second.status == "acknowledged"
    assert second.acknowledged_by_id == user.id

    stored_group = type(alert_group).get_by_id(alert_group.id)
    stored_delivery = UserNotificationDelivery.get_by_id(pending_delivery.id)

    assert stored_group.notification_pending is False
    assert stored_group.notification_due_at is None
    assert stored_delivery.status == "skipped"
    assert stored_delivery.last_error == "alert_acknowledged"

    assert _event_count(alert_group.id, "acknowledged") == 1
    assert message_updates == [(alert_group.id, "acknowledged")]
    assert len(stakeholder_updates) == 1
    assert stakeholder_updates[0][1] == "status_changed"


def test_resolve_alert_is_idempotent(monkeypatch, db):
    """
    Repeating manual resolve must preserve the first transition and must not
    duplicate timeline, outbound-message, or stakeholder side effects.
    """
    group, _team, _route, alert_group, _alert = _create_firing_group()
    user = create_user("release-resolve-user", group)

    message_updates = []
    stakeholder_updates = []

    monkeypatch.setattr(
        "app.services.alerts.actions.update_alert_messages",
        lambda current_group, event_type: message_updates.append(
            (current_group.id, event_type)
        ) or 1,
    )
    monkeypatch.setattr(
        "app.services.alerts.actions.notify_stakeholders",
        lambda current_group, event_type, **kwargs: stakeholder_updates.append(
            (current_group.id, event_type, kwargs)
        ),
    )

    first = resolve_alert(alert_group.id, user_id=user.id)
    first_resolved_at = first.resolved_at

    second = resolve_alert(alert_group.id, user_id=user.id)

    assert first.status == "resolved"
    assert second.status == "resolved"
    assert second.resolved_at == first_resolved_at

    assert _event_count(alert_group.id, "resolved") == 1
    assert message_updates == [(alert_group.id, "resolved")]
    assert len(stakeholder_updates) == 1
    assert stakeholder_updates[0][1] == "resolved"


def test_same_alert_firing_after_payload_resolve_creates_new_group(db):
    """
    A new firing after a completed lifecycle must create a new alert group,
    while preserving the resolved group and its history.
    """
    _group, _team, route, old_group, old_alert = _create_firing_group()

    resolved = upsert_alert(
        _normalized_alert(
            route,
            status="resolved",
            message="Recovered",
        )
    )

    assert resolved.created_group is False
    assert resolved.group.id == old_group.id
    assert resolved.alert.id == old_alert.id
    assert resolved.group.status == "resolved"
    assert resolved.alert.status == "resolved"

    firing_again = upsert_alert(
        _normalized_alert(
            route,
            status="firing",
            message="/var is full again",
        )
    )

    assert firing_again.created_group is True
    assert firing_again.group.id != old_group.id
    assert firing_again.group.status == "firing"
    assert firing_again.alert.status == "firing"
    assert firing_again.group.resolved_at is None
    assert firing_again.alert.resolved_at is None
    assert firing_again.group.message == "/var is full again"
    assert firing_again.alert.message == "/var is full again"

    old_group = type(old_group).get_by_id(old_group.id)
    old_alert = type(old_alert).get_by_id(old_alert.id)

    assert old_group.status == "resolved"
    assert old_alert.status == "resolved"
    assert old_group.resolved_at is not None
    assert old_alert.resolved_at is not None


def test_resolve_alert_can_skip_message_updates(monkeypatch, db):
    group, _team, _route, alert_group, _alert = _create_firing_group()
    user = create_user("release-resolve-no-update-user", group)

    message_updates = []
    stakeholder_updates = []

    monkeypatch.setattr(
        "app.services.alerts.actions.update_alert_messages",
        lambda current_group, event_type: message_updates.append(
            (current_group.id, event_type)
        )
        or 1,
    )
    monkeypatch.setattr(
        "app.services.alerts.actions.notify_stakeholders",
        lambda current_group, event_type, **kwargs: stakeholder_updates.append(
            (current_group.id, event_type, kwargs)
        ),
    )

    resolved = resolve_alert(
        alert_group.id,
        user_id=user.id,
        update_messages=False,
    )

    assert resolved.status == "resolved"
    assert message_updates == []
    assert len(stakeholder_updates) == 1
    assert _event_count(alert_group.id, "resolved") == 1
