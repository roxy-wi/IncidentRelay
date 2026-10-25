"""IncidentRelay 2.4: resolved-group reuse is opt-in and non-destructive."""

from datetime import timedelta

import pytest

from app.modules.common import utc_now
from app.modules.db.models import (
    Alert, AlertEvent, AlertGroup, AuditLog, Incident, IncidentAlertGroupLink, IncidentEvent,
    UserNotificationDelivery,
)
from app.services.alerts.lifecycle import upsert_alert
from app.services.alerts.reopen import find_resolved_reopen_candidate
from app.services.alerts import lifecycle
from app.services.orchestration.runtime import RuntimeResult
from tests.factories import (
    add_user_to_team,
    create_escalation_policy,
    create_escalation_policy_rule,
    create_group,
    create_route,
    create_service,
    create_team,
    create_user,
)


def _setup(monkeypatch, *, window=300):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager", group_by=["alertname"])
    monkeypatch.setattr(
        lifecycle, "run_event_orchestration",
        lambda alert_data, trace=None: RuntimeResult(
            grouping_reopen_window_seconds=window,
        ),
    )
    return team, route


def _data(route, key="reopen-key", *, status="firing"):
    return {
        "source": "alertmanager", "forced_route_id": route.id,
        "external_id": key, "dedup_key": key,
        "title": "Disk full", "message": "Disk alert",
        "status": status, "severity": "critical",
        "labels": {"alertname": "DiskFull"}, "payload": {},
    }


def _resolved_group(route):
    first = upsert_alert(_data(route))
    assert first.created_group is True
    resolved = upsert_alert(_data(route, status="resolved"))
    assert resolved.group.id == first.group.id
    assert resolved.group.status == "resolved"
    return first


def test_reopen_adds_child_and_keeps_old_child_resolved(db, monkeypatch):
    team, route = _setup(monkeypatch)
    first = _resolved_group(route)
    before = first.alert.first_seen_at
    result = upsert_alert(_data(route))
    assert result.created_group is False
    assert result.outcome == "reopened"
    assert result.group.id == first.group.id
    assert result.alert.id != first.alert.id
    assert result.group.status == "firing"
    assert result.group.resolved_at is None
    old = Alert.get_by_id(first.alert.id)
    assert old.status == "resolved"
    assert old.resolved_at is not None
    assert old.first_seen_at == before
    assert Alert.select().where(Alert.group == first.group.id).count() == 2
    assert AlertEvent.select().where(
        AlertEvent.group == first.group.id,
        AlertEvent.event_type == "reopened",
        AlertEvent.alert == result.alert.id,
    ).count() == 1


def test_reopen_is_disabled_when_grace_is_zero(db, monkeypatch):
    _, route = _setup(monkeypatch, window=0)
    first = _resolved_group(route)
    result = upsert_alert(_data(route))
    assert result.created_group is True
    assert result.group.id != first.group.id


def test_expired_grace_creates_new_group(db, monkeypatch):
    _, route = _setup(monkeypatch, window=60)
    first = _resolved_group(route)
    AlertGroup.update(resolved_at=utc_now() - timedelta(seconds=61)).where(
        AlertGroup.id == first.group.id,
    ).execute()
    result = upsert_alert(_data(route))
    assert result.created_group is True
    assert result.group.id != first.group.id


def test_resolved_payload_does_not_reopen(db, monkeypatch):
    _, route = _setup(monkeypatch)
    first = _resolved_group(route)
    result = upsert_alert(_data(route, status="resolved"))
    assert result.outcome == "ignored"
    assert AlertGroup.get_by_id(first.group.id).status == "resolved"
    assert Alert.select().where(Alert.group == first.group.id).count() == 1


def test_active_alert_is_not_hijacked_across_routes(db, monkeypatch):
    _, route = _setup(monkeypatch)
    first = upsert_alert(_data(route))
    other = create_route(route.team, source="alertmanager", group_by=["alertname"])
    second = upsert_alert(_data(other))
    assert second.created_group is True
    assert second.group.id != first.group.id
    assert second.group.route_id == other.id
    assert Alert.get_by_id(first.alert.id).route_id == route.id


def test_different_route_is_not_reused(db, monkeypatch):
    _, route = _setup(monkeypatch)
    first = _resolved_group(route)
    # Same source, team, grouping and dedup_key, but different intake route.
    other = create_route(route.team, source="alertmanager", group_by=["alertname"])
    result = upsert_alert(_data(other))
    assert result.created_group is True
    assert result.group.id != first.group.id


def test_different_service_is_not_reused(db, monkeypatch):
    team, route = _setup(monkeypatch)
    first_service = create_service(team)
    other_service = create_service(team)
    initial = _data(route)
    initial["_forced_service_id"] = first_service.id
    first = upsert_alert(dict(initial))
    upsert_alert(dict(initial, status="resolved"))
    incoming = _data(route)
    incoming["_forced_service_id"] = other_service.id
    later = upsert_alert(incoming)
    assert later.created_group is True
    assert later.group.id != first.group.id
    assert later.group.service_id == other_service.id


def test_reopen_cancels_pending_previous_cycle_deliveries(db, monkeypatch):
    team, route = _setup(monkeypatch)
    first = _resolved_group(route)
    user = create_user(group=team.group)
    old_resolution = UserNotificationDelivery.create(
        group=first.group, user=user, method="email", event_type="resolved",
        scheduled_at=utc_now() + timedelta(minutes=3),
    )
    result = upsert_alert(_data(route))
    assert result.outcome == "reopened"
    old_resolution = UserNotificationDelivery.get_by_id(old_resolution.id)
    assert old_resolution.status == "skipped"
    assert old_resolution.last_error == "alert_group_reopened"


@pytest.mark.parametrize("status", ["resolved", "monitoring"])
def test_reopen_resumes_linked_resolved_incident_not_closed(db, monkeypatch, status):
    team, route = _setup(monkeypatch)
    first = _resolved_group(route)
    incident = Incident.create(
        team=team, title="Disk outage", workflow_status=status,
        resolved_at=utc_now(),
    )
    IncidentAlertGroupLink.create(
        incident=incident, alert_group=first.group, relation_type="primary",
    )
    result = upsert_alert(_data(route))
    assert result.group.id == first.group.id
    current = Incident.get_by_id(incident.id)
    assert current.workflow_status == "investigating"
    assert current.resolved_at is None
    assert current.row_version == 2
    assert IncidentEvent.select().where(
        IncidentEvent.incident == incident.id,
        IncidentEvent.event_type == "incident_reopened_by_alert_group",
    ).count() == 1
    audit = list(AuditLog.select().where(
        (AuditLog.object_type == "incident")
        & (AuditLog.object_id == incident.id)
        & (AuditLog.action == "incident.reopen_by_alert_group")
    ))
    assert len(audit) == 1
    assert audit[0].data["alert_group_id"] == first.group.id
    assert audit[0].data["new_alert_id"] == result.alert.id
    assert audit[0].data["to"] == "investigating"


@pytest.mark.parametrize("terminal_status", ["closed", "cancelled"])
def test_closed_incident_stays_closed(db, monkeypatch, terminal_status):
    team, route = _setup(monkeypatch)
    first = _resolved_group(route)
    incident = Incident.create(
        team=team, title="Terminal outage", workflow_status=terminal_status,
    )
    IncidentAlertGroupLink.create(incident=incident, alert_group=first.group)
    upsert_alert(_data(route))
    assert Incident.get_by_id(incident.id).workflow_status == terminal_status
    assert IncidentEvent.select().where(
        IncidentEvent.incident == incident.id,
        IncidentEvent.event_type == "incident_reopened_by_alert_group",
    ).count() == 0


def test_new_child_failure_rolls_back_reopen(db, monkeypatch):
    _, route = _setup(monkeypatch)
    first = _resolved_group(route)
    resolved_at = AlertGroup.get_by_id(first.group.id).resolved_at

    def fail_child(**kwargs):
        raise RuntimeError("child insert failed")

    from app.modules.db import alerts_repo
    monkeypatch.setattr(alerts_repo, "create_alert", fail_child)
    with pytest.raises(RuntimeError, match="child insert failed"):
        upsert_alert(_data(route))
    old = AlertGroup.get_by_id(first.group.id)
    assert old.status == "resolved"
    assert old.resolved_at == resolved_at
    assert Alert.select().where(Alert.group == old.id).count() == 1


def test_missing_reopen_policy_preserves_pre_24_creation(db):
    """An installation with no published reopen action does not reuse resolved groups."""
    scope = create_group()
    team = create_team(scope)
    route = create_route(team, source="alertmanager", group_by=["alertname"])
    first = _resolved_group(route)

    subsequent = upsert_alert(_data(route))

    assert subsequent.created_group is True
    assert subsequent.group.id != first.group.id
    assert AlertGroup.get_by_id(first.group.id).status == "resolved"
    assert AlertEvent.select().where(
        AlertEvent.group == first.group.id,
        AlertEvent.event_type == "reopened",
    ).count() == 0


def test_reopen_candidate_requires_exact_identity_including_null_service(db, monkeypatch):
    """A resolved group cannot be reused across any ownership/grouping boundary."""
    team, route = _setup(monkeypatch)
    first = _resolved_group(route)
    saved = AlertGroup.get_by_id(first.group.id)
    assert saved.service_id is None
    other_team = create_team(team.group)
    other_route = create_route(team, source="alertmanager", group_by=["alertname"])
    service = create_service(team)

    identity = {
        "source": saved.source,
        "group_key": saved.group_key,
        "team_id": saved.team_id,
        "route_id": saved.route_id,
        "service_id": saved.service_id,
        "now": utc_now(),
        "reopen_window_seconds": 300,
    }
    assert find_resolved_reopen_candidate(**identity).id == first.group.id

    for field, wrong_value in (
        ("source", "grafana"),
        ("group_key", saved.group_key + "-other"),
        ("team_id", other_team.id),
        ("route_id", other_route.id),
        ("service_id", service.id),
    ):
        mismatched = dict(identity, **{field: wrong_value})
        assert find_resolved_reopen_candidate(**mismatched) is None, field

    # NULL is not a wildcard: a signal without a service cannot reuse one
    # owned by a specific service even if every other dimension agrees.
    AlertGroup.update(service=service.id).where(
        AlertGroup.id == saved.id,
    ).execute()
    assert find_resolved_reopen_candidate(**identity) is None


def test_reopen_selects_newest_eligible_resolved_group_once(db, monkeypatch):
    """Multiple matching historical groups never turn into multiple active groups."""
    _, route = _setup(monkeypatch, window=0)
    oldest = _resolved_group(route)
    newest = _resolved_group(route)
    assert newest.group.id != oldest.group.id
    now = utc_now()
    AlertGroup.update(resolved_at=now - timedelta(seconds=20)).where(
        AlertGroup.id == oldest.group.id,
    ).execute()
    AlertGroup.update(resolved_at=now - timedelta(seconds=5)).where(
        AlertGroup.id == newest.group.id,
    ).execute()
    monkeypatch.setattr(
        lifecycle, "run_event_orchestration",
        lambda alert_data, trace=None: RuntimeResult(grouping_reopen_window_seconds=60),
    )

    result = upsert_alert(_data(route, key="a-new-occurrence"))

    assert result.outcome == "reopened"
    assert result.group.id == newest.group.id
    assert AlertGroup.get_by_id(oldest.group.id).status == "resolved"
    assert AlertGroup.get_by_id(newest.group.id).status == "firing"
    assert Alert.select().where(Alert.group == oldest.group.id).count() == 1
    assert Alert.select().where(Alert.group == newest.group.id).count() == 2
    assert AlertEvent.select().where(
        AlertEvent.group == newest.group.id,
        AlertEvent.event_type == "reopened",
    ).count() == 1


def test_stale_pre_reopen_reminder_selection_does_not_page(db, monkeypatch):
    """Re-read fresh post-reopen counters before delivering an old reminder."""
    from app.modules.db import alerts_repo
    from app.services.alerts import reminders

    _, route = _setup(monkeypatch)
    original = upsert_alert(_data(route))
    group = AlertGroup.get_by_id(original.group.id)
    group.last_notification_at = utc_now() - timedelta(hours=1)
    group.save(only=[AlertGroup.last_notification_at])
    old_selection = AlertGroup.get_by_id(group.id)

    upsert_alert(_data(route, status="resolved"))
    reopened = upsert_alert(_data(route))
    assert reopened.outcome == "reopened"
    assert AlertGroup.get_by_id(group.id).last_notification_at is None

    sent = []
    monkeypatch.setattr(alerts_repo, "list_firing_alert_groups", lambda: [old_selection])
    monkeypatch.setattr(
        reminders, "notify_alert", lambda *args, **kwargs: sent.append(kwargs),
    )
    assert reminders.send_unacked_reminders() == 0
    assert sent == []
    assert AlertGroup.get_by_id(group.id).status == "firing"


def test_missing_webhook_traffic_does_not_infer_recovery(db, monkeypatch):
    """The ordinary notification scheduler does not close inactive sources."""
    from app.services.alerts import notification_queue, reminders

    _, route = _setup(monkeypatch)
    first = upsert_alert(_data(route))
    AlertGroup.update(last_seen_at=utc_now() - timedelta(days=2)).where(
        AlertGroup.id == first.group.id,
    ).execute()

    reminders.send_unacked_reminders()
    notification_queue.process_due_alert_group_notifications()

    assert AlertGroup.get_by_id(first.group.id).status == "firing"
    assert Alert.get_by_id(first.alert.id).status == "firing"
    assert AlertGroup.get_by_id(first.group.id).resolved_at is None


def test_reopen_does_not_cross_group_key_or_team(db, monkeypatch):
    """Same dedup fingerprint is not sufficient to reopen a different identity."""
    team, route = _setup(monkeypatch)
    initial = _resolved_group(route)

    changed_group_key = _data(route)
    changed_group_key["labels"] = {"alertname": "AnotherDisk"}
    other_signal = upsert_alert(changed_group_key)
    assert other_signal.created_group is True
    assert other_signal.group.id != initial.group.id

    second_team = create_team(team.group)
    other_route = create_route(
        second_team, source="alertmanager", group_by=["alertname"],
    )
    different_owner = upsert_alert(_data(other_route))
    assert different_owner.created_group is True
    assert different_owner.group.team_id == second_team.id
    assert different_owner.group.id != initial.group.id

    assert AlertGroup.get_by_id(initial.group.id).status == "resolved"


def test_reopen_resets_ack_reminders_and_escalation_cycle(db, monkeypatch):
    """A new technical occurrence starts a fresh notification/escalation cycle."""
    _, route = _setup(monkeypatch)
    initial = _resolved_group(route)
    group = AlertGroup.get_by_id(initial.group.id)
    group.reminder_count = 4
    group.escalation_level = 3
    group.escalation_repeat_count = 2
    group.last_notification_at = utc_now() - timedelta(minutes=10)
    group.save(only=[
        AlertGroup.reminder_count,
        AlertGroup.escalation_level,
        AlertGroup.escalation_repeat_count,
        AlertGroup.last_notification_at,
    ])

    reopened = upsert_alert(_data(route))

    assert reopened.outcome == "reopened"
    fresh = AlertGroup.get_by_id(initial.group.id)
    assert fresh.status == "firing"
    assert fresh.reminder_count == 0
    assert fresh.escalation_level == 0
    assert fresh.escalation_repeat_count == 0
    assert fresh.last_notification_at is None
    assert fresh.resolved_at is None
    assert Alert.get_by_id(initial.alert.id).status == "resolved"


def test_stale_escalation_selection_does_not_advance_reopened_cycle(db, monkeypatch):
    """An old scheduler selection must reload the new escalation deadline."""
    from app.modules.db import alerts_repo
    from app.services.alerts import escalation, reminders

    scope = create_group()
    team = create_team(scope)
    user = create_user(group=scope)
    add_user_to_team(team, user)
    policy = create_escalation_policy(team)
    first_rule = create_escalation_policy_rule(
        policy, position=1, delay_seconds=600,
        target_type="user", user=user,
    )
    create_escalation_policy_rule(
        policy, position=2, delay_seconds=600,
        target_type="user", user=user,
    )
    route = create_route(
        team, source="alertmanager", group_by=["alertname"],
        escalation_policy=policy,
    )
    monkeypatch.setattr(
        lifecycle, "run_event_orchestration",
        lambda data, trace=None: RuntimeResult(grouping_reopen_window_seconds=300),
    )
    initial = upsert_alert(_data(route))
    AlertGroup.update(next_escalation_at=utc_now() - timedelta(minutes=1)).where(
        AlertGroup.id == initial.group.id,
    ).execute()
    stale = AlertGroup.get_by_id(initial.group.id)

    upsert_alert(_data(route, status="resolved"))
    reopened = upsert_alert(_data(route))
    assert reopened.outcome == "reopened"
    current = AlertGroup.get_by_id(initial.group.id)
    assert current.escalation_rule_id == first_rule.id
    assert current.next_escalation_at > utc_now()

    sent = []
    monkeypatch.setattr(alerts_repo, "list_firing_alert_groups", lambda: [stale])
    monkeypatch.setattr(
        escalation, "notify_alert",
        lambda *args, **kwargs: sent.append(kwargs),
    )
    assert reminders.send_unacked_reminders() == 0
    updated = AlertGroup.get_by_id(initial.group.id)
    assert updated.escalation_rule_id == first_rule.id
    assert updated.escalation_level == 0
    assert sent == []
