from datetime import timedelta

import pytest

from app.modules.common import utc_now
from app.modules.db.models import AlertGroup, AlertGroupShelve
from app.services.alerts import shelving
from app.services.alerts.lifecycle import upsert_alert
from app.services.serializers.alerts import serialize_alert_group
from tests.factories import add_user_to_team, create_group, create_route, create_team, create_user


def _open_group():
    group = create_group(slug="shelving")
    team = create_team(group, slug="sre")
    user = create_user("shelve-user", group)
    add_user_to_team(team, user)
    route = create_route(team, group_by=["alertname"])
    result = upsert_alert({
        "source": "alertmanager",
        "forced_route_id": route.id,
        "external_id": "shelve-external-1",
        "dedup_key": "shelve-dedup-1",
        "title": "HighLatency",
        "message": "Latency is high",
        "severity": "warning",
        "labels": {"alertname": "HighLatency"},
        "payload": {},
        "status": "firing",
    })
    return result.group, user


@pytest.fixture(autouse=True)
def disable_message_updates(monkeypatch):
    monkeypatch.setattr(
        "app.services.notifications.delivery.update_alert_messages",
        lambda *args, **kwargs: 0,
    )


def test_shelve_preserves_technical_status_and_serializes_state(db):
    group, user = _open_group()

    stored, shelf = shelving.shelve_alert_group(
        group.id,
        user_id=user.id,
        duration_seconds=3600,
        reason="Waiting for deployment",
        source="ui",
    )

    stored = AlertGroup.get_by_id(stored.id)
    assert stored.status == "firing"
    assert shelf.active is True
    assert shelving.is_alert_group_shelved(stored) is True

    payload = serialize_alert_group(stored)
    assert payload["shelved"] is True
    assert payload["shelve"]["active"] is True
    assert payload["shelve"]["reason"] == "Waiting for deployment"
    assert payload["shelve"]["shelved_by"]["id"] == user.id


def test_reshelve_replaces_previous_active_record(db):
    group, user = _open_group()

    _, first = shelving.shelve_alert_group(
        group.id, user_id=user.id, duration_seconds=1800
    )
    _, second = shelving.shelve_alert_group(
        group.id, user_id=user.id, duration_seconds=3600
    )

    first = AlertGroupShelve.get_by_id(first.id)
    second = AlertGroupShelve.get_by_id(second.id)
    assert first.active is False
    assert first.unshelve_reason == "replaced"
    assert second.active is True
    assert shelving.get_active_shelve(group.id).id == second.id


def test_manual_unshelve_ends_shelf_and_restarts_firing_group(db, monkeypatch):
    group, user = _open_group()
    shelving.shelve_alert_group(group.id, user_id=user.id, duration_seconds=3600)
    restarted = []
    monkeypatch.setattr(
        shelving,
        "_restart_after_unshelve",
        lambda target, *, now: restarted.append(target.id),
    )

    _, ended = shelving.unshelve_alert_group(group.id, user_id=user.id)

    assert ended is not None
    assert AlertGroupShelve.get_by_id(ended.id).active is False
    assert shelving.is_alert_group_shelved(group.id) is False
    assert restarted == [group.id]


def test_due_shelf_expires_once(db, monkeypatch):
    group, user = _open_group()
    _, shelf = shelving.shelve_alert_group(
        group.id, user_id=user.id, duration_seconds=3600
    )
    shelf.ends_at = utc_now() - timedelta(seconds=1)
    shelf.save()
    monkeypatch.setattr(shelving, "_restart_after_unshelve", lambda *args, **kwargs: None)

    first = shelving.process_due_shelves()
    second = shelving.process_due_shelves()

    assert first["expired"] == 1
    assert second["expired"] == 0
    stored = AlertGroupShelve.get_by_id(shelf.id)
    assert stored.active is False
    assert stored.unshelve_reason == "expired"



def test_stale_due_shelf_does_not_expire_newer_active_shelf(db, monkeypatch):
    group, user = _open_group()
    _, old_shelf = shelving.shelve_alert_group(
        group.id, user_id=user.id, duration_seconds=3600
    )
    old_shelf.ends_at = utc_now() - timedelta(seconds=1)
    old_shelf.save()

    _, new_shelf = shelving.shelve_alert_group(
        group.id, user_id=user.id, duration_seconds=7200
    )

    # Simulate a stale scheduler row that was selected before the replacement.
    group_result, ended = shelving.unshelve_alert_group(
        group.id,
        source="scheduler",
        expired=True,
        expected_shelf_id=old_shelf.id,
    )

    assert group_result.id == group.id
    assert ended is None
    assert shelving.get_active_shelve(group.id).id == new_shelf.id
    assert AlertGroupShelve.get_by_id(new_shelf.id).active is True


def test_source_resolution_closes_active_shelf(db):
    group, user = _open_group()
    shelving.shelve_alert_group(
        group.id, user_id=user.id, duration_seconds=3600
    )

    result = upsert_alert({
        "source": "alertmanager",
        "forced_route_id": group.route_id,
        "external_id": "shelve-external-1",
        "dedup_key": "shelve-dedup-1",
        "title": "HighLatency",
        "message": "Latency recovered",
        "severity": "warning",
        "labels": {"alertname": "HighLatency"},
        "payload": {},
        "status": "resolved",
    })

    stored = AlertGroup.get_by_id(group.id)
    assert result.group.id == group.id
    assert stored.status == "resolved"
    assert shelving.is_alert_group_shelved(group.id) is False
    shelf = AlertGroupShelve.get(AlertGroupShelve.alert_group == group.id)
    assert shelf.active is False
    assert shelf.unshelve_reason == "alert_resolved"


def test_shelved_group_cannot_be_rescheduled_for_notification(db):
    from app.services.alerts.notification_queue import schedule_group_notification

    group, user = _open_group()
    shelving.shelve_alert_group(
        group.id, user_id=user.id, duration_seconds=3600
    )

    group = AlertGroup.get_by_id(group.id)
    group.notification_pending = True
    group.notification_due_at = utc_now()
    group.notification_reason = "test"
    group.next_escalation_at = utc_now()
    group.save()

    schedule_group_notification(group, reason="update")

    stored = AlertGroup.get_by_id(group.id)
    assert stored.notification_pending is False
    assert stored.notification_due_at is None
    assert stored.notification_reason is None
    assert stored.next_escalation_at is None

def test_resolved_group_cannot_be_shelved(db):
    group, user = _open_group()
    group.status = "resolved"
    group.resolved_at = utc_now()
    group.save()

    with pytest.raises(ValueError, match="only open"):
        shelving.shelve_alert_group(group.id, user_id=user.id)


def test_merge_closes_source_group_shelf_without_resume(db):
    from app.modules.db import alerts_repo

    source, user = _open_group()
    shelving.shelve_alert_group(
        source.id, user_id=user.id, duration_seconds=3600
    )

    target_result = upsert_alert({
        "source": "alertmanager",
        "forced_route_id": source.route_id,
        "external_id": "shelve-target-external",
        "dedup_key": "shelve-target-dedup",
        "title": "DatabaseUnavailable",
        "message": "Database is unavailable",
        "severity": "critical",
        "labels": {"alertname": "DatabaseUnavailable"},
        "payload": {},
        "status": "firing",
    })

    alerts_repo.merge_alert_groups(
        target_result.group.id,
        [source.id],
        user_id=user.id,
        reason="same technical signal",
    )

    source = AlertGroup.get_by_id(source.id)
    shelf = AlertGroupShelve.get(AlertGroupShelve.alert_group == source.id)

    assert source.status == "merged"
    assert shelf.active is False
    assert shelf.unshelve_reason == "alert_group_merged"
