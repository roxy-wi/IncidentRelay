from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.api.schemas.rotations import RotationCreateSchema
from app.modules.db.models import AlertEvent
from app.services.alerts.reminders import should_send_reminder, send_unacked_reminders
from tests.factories import attach_channel, create_alert, create_channel, create_group, create_route, create_rotation, create_team
from app.modules.common import utc_now


def _rotation_payload(reminder_interval_seconds):
    return {
        "team_id": 1,
        "name": "primary",
        "description": None,
        "start_at": "2026-05-20T09:00:00",
        "rotation_type": "daily",
        "interval_value": 1,
        "interval_unit": "days",
        "handoff_time": "09:00",
        "handoff_weekday": None,
        "timezone": "UTC",
        "duration_seconds": None,
        "reminder_interval_seconds": reminder_interval_seconds,
        "add_team_members": True,
        "enabled": True,
    }


def test_rotation_schema_accepts_zero_reminder_interval():
    payload = RotationCreateSchema.model_validate(_rotation_payload(0))

    assert payload.reminder_interval_seconds == 0


def test_rotation_schema_rejects_reminder_interval_below_60_except_zero():
    with pytest.raises(ValidationError):
        RotationCreateSchema.model_validate(_rotation_payload(59))


def test_rotation_schema_accepts_reminder_interval_60():
    payload = RotationCreateSchema.model_validate(_rotation_payload(60))

    assert payload.reminder_interval_seconds == 60


def test_should_send_reminder_returns_false_when_rotation_interval_is_zero(db):
    group = create_group()
    team = create_team(group)
    rotation = create_rotation(team)
    rotation.reminder_interval_seconds = 0
    rotation.save()

    route = create_route(team, rotation=rotation)
    alert = create_alert(route)
    alert.rotation = rotation
    alert.last_notification_at = utc_now() - timedelta(days=1)

    assert should_send_reminder(alert, utc_now()) is False


def test_send_unacked_reminders_skips_rotation_with_zero_interval(monkeypatch, db):
    group = create_group()
    team = create_team(group)
    rotation = create_rotation(team)
    rotation.reminder_interval_seconds = 0
    rotation.save()

    route = create_route(team, rotation=rotation)
    channel = create_channel(group, team, channel_type="fake", config={"notify_on_severities": ["critical"]})
    attach_channel(route, channel)

    alert = create_alert(route)
    alert.rotation = rotation
    alert.last_notification_at = utc_now() - timedelta(days=1)
    alert.save()

    def fail_notify(*args, **kwargs):
        raise AssertionError("notify_alert must not be called when reminder interval is 0")

    monkeypatch.setattr("app.services.alerts.notification_queue.notify_alert", fail_notify)

    assert send_unacked_reminders() == 0

    alert = type(alert).get_by_id(alert.id)
    assert alert.reminder_count == 0
    assert not AlertEvent.select().where(
        (AlertEvent.alert == alert.id) &
        (AlertEvent.event_type == "reminder_sent")
    ).exists()
