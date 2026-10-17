"""Tests for incident participant (responder / stakeholder) notifications."""

import pytest

from app.modules.db import incidents_repo
from app.modules.db.models import AlertGroup, AlertEvent
from app.services.incidents import participant_notifications as participants
from app.services.incidents import responder_notifications, stakeholders
from tests.factories import (
    attach_channel,
    create_channel,
    create_group,
    create_route,
    create_team,
    create_user,
    unique,
)


@pytest.fixture
def incident(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team)

    alert_group = AlertGroup.create(
        team=team,
        route=route,
        source=route.source,
        group_key_hash=unique("group-hash"),
        group_key=unique("group-key"),
        title="DiskFull",
        message="/var is 95% full",
        severity="critical",
        status="firing",
        alert_count=1,
        firing_count=1,
        common_labels={},
        label_values={},
        payload_summary={},
    )

    return {
        "group": group,
        "team": team,
        "route": route,
        "alert_group": alert_group,
    }


@pytest.fixture
def captured_emails(monkeypatch):
    sent = []

    monkeypatch.setattr(
        participants,
        "send_plain_email",
        lambda recipient, subject, body: sent.append(
            {"to": recipient, "subject": subject, "body": body}
        ),
    )

    return sent


@pytest.fixture
def no_push(monkeypatch):
    """Default: no active browser push subscriptions."""
    monkeypatch.setattr(
        participants.browser_push,
        "send_stakeholder_push_to_user",
        lambda *args, **kwargs: 0,
    )


@pytest.fixture
def no_slack(monkeypatch):
    """Default: no Slack channel configured for the incident."""
    monkeypatch.setattr(
        participants,
        "resolve_slack_channel",
        lambda group: None,
    )


def alert_events(group_id, event_type):
    """Return group-scoped alert events of one type."""
    return list(
        AlertEvent
        .select()
        .where(
            (AlertEvent.group == group_id)
            & (AlertEvent.event_type == event_type)
        )
        .order_by(AlertEvent.id.asc())
    )


def make_responder(alert_group, target_user, requested_by=None, message="please help"):
    return incidents_repo.create_incident_responder(
        alert_group.id,
        {
            "target_type": "user",
            "target_user_id": target_user.id,
            "requested_by_id": getattr(requested_by, "id", None),
            "message": message,
        },
    )


# --- 8.6 responder notifications -------------------------------------------


def test_responder_email_only_recipient_succeeds(
    incident, captured_emails, no_push, no_slack
):
    user = create_user(group=incident["group"], email="ann@example.com")
    requester = create_user(group=incident["group"])
    responder = make_responder(incident["alert_group"], user, requester)

    result = responder_notifications.notify_incident_responder_requested(responder)

    assert result["status"] == "sent"
    assert result["channels"] == ["email"]
    assert len(captured_emails) == 1
    assert captured_emails[0]["to"] == "ann@example.com"
    assert "added you as a responder" in captured_emails[0]["body"]
    assert "please help" in captured_emails[0]["body"]


def test_responder_slack_only_recipient_succeeds(
    incident, monkeypatch, no_push
):
    user = create_user(group=incident["group"], email=None)
    user.slack_user_id = "U012ABCDEF"
    user.save()

    slack_channel = create_channel(
        incident["group"],
        incident["team"],
        channel_type="slack",
        config={
            "mode": "bot_api",
            "bot_token": "xoxb-test",
            "channel_id": "C1",
            "signing_secret": "s",
        },
    )
    attach_channel(incident["route"], slack_channel)

    dms = []
    monkeypatch.setattr(
        participants,
        "get_notifier",
        lambda channel_type: type(
            "FakeSlack",
            (),
            {
                "send_direct_message": staticmethod(
                    lambda channel, target, text: dms.append(
                        {"user_id": target.id, "text": text}
                    )
                )
            },
        )(),
    )

    responder = make_responder(incident["alert_group"], user)
    result = responder_notifications.notify_incident_responder_requested(responder)

    assert result["status"] == "sent"
    assert result["channels"] == ["slack"]
    assert len(dms) == 1
    assert dms[0]["user_id"] == user.id
    assert "responder" in dms[0]["text"]


def test_responder_multi_recipient_partial_failure(
    incident, monkeypatch, no_push, no_slack
):
    """One recipient failing must not block the others."""
    good = create_user(group=incident["group"], email="good@example.com")
    bad = create_user(group=incident["group"], email="bad@example.com")

    def flaky_email(recipient, subject, body):
        if recipient == "bad@example.com":
            raise RuntimeError("smtp rejected recipient")

    monkeypatch.setattr(participants, "send_plain_email", flaky_email)
    monkeypatch.setattr(
        responder_notifications,
        "resolve_responder_recipients",
        lambda responder: [good, bad],
    )

    responder = make_responder(incident["alert_group"], good)
    result = responder_notifications.notify_incident_responder_requested(responder)

    assert result["status"] == "sent"
    assert result["sent"] == 1
    assert "smtp rejected recipient" in result["error"]


def test_responder_without_any_contact_data_fails_descriptively(
    incident, captured_emails, no_push, no_slack
):
    user = create_user(group=incident["group"], email=None)
    responder = make_responder(incident["alert_group"], user)

    result = responder_notifications.notify_incident_responder_requested(responder)

    assert result["status"] == "failed"
    assert result["sent"] == 0
    assert "no email address" in result["error"]
    assert captured_emails == []


def test_responder_inactive_user_is_not_a_failure(
    incident, captured_emails, no_push, no_slack
):
    user = create_user(group=incident["group"], active=False)
    responder = make_responder(incident["alert_group"], user)

    result = responder_notifications.notify_incident_responder_requested(responder)

    assert result["status"] == "failed"
    assert result["error"] == "no active responder recipients"
    assert captured_emails == []


def test_responder_push_still_delivered(incident, monkeypatch, no_slack):
    user = create_user(group=incident["group"], email=None)
    pushes = []

    monkeypatch.setattr(
        participants.browser_push,
        "send_stakeholder_push_to_user",
        lambda target, group, **kwargs: pushes.append(kwargs) or 2,
    )

    responder = make_responder(incident["alert_group"], user)
    result = responder_notifications.notify_incident_responder_requested(responder)

    assert result["status"] == "sent"
    assert result["channels"] == ["browser_push"]
    assert pushes[0]["event_type"] == "responder_requested"


# --- 8.7 stakeholder-added notifications -----------------------------------


def test_stakeholder_added_notification_sent(
    incident, captured_emails, no_push, no_slack
):
    user = create_user(group=incident["group"], email="stake@example.com")
    adder = create_user(group=incident["group"])

    stakeholders.create_incident_stakeholder(
        group_id=incident["alert_group"].id,
        payload={"user_id": user.id},
        user_id=adder.id,
    )

    assert len(captured_emails) == 1
    body = captured_emails[0]["body"]
    assert "added you as a stakeholder" in body
    assert "DiskFull" in body
    assert "firing" in body
    assert "critical" in body


def test_stakeholder_added_email_only_recipient(
    incident, captured_emails, monkeypatch, no_push
):
    slack_calls = []
    monkeypatch.setattr(
        participants,
        "resolve_slack_channel",
        lambda group: slack_calls.append(group) or None,
    )

    stakeholders.create_incident_stakeholder(
        group_id=incident["alert_group"].id,
        payload={"email": "external@example.com"},
    )

    assert len(captured_emails) == 1
    assert captured_emails[0]["to"] == "external@example.com"


def test_stakeholder_email_only_skips_slack_and_push(incident, captured_emails):
    """A stakeholder with no linked user must not attempt Slack or push."""
    recipient = participants.ParticipantRecipient(
        display_name="external@example.com",
        email="external@example.com",
    )

    assert participants._attempt_slack(recipient, object(), "text") is None
    assert participants._attempt_browser_push(recipient, None, "e", None) is None


def test_self_added_stakeholder_is_not_notified(
    incident, captured_emails, no_push, no_slack
):
    user = create_user(group=incident["group"], email="self@example.com")

    stakeholders.create_incident_stakeholder(
        group_id=incident["alert_group"].id,
        payload={"user_id": user.id},
        user_id=user.id,
    )

    assert captured_emails == []


def test_stakeholder_lifecycle_events_are_unchanged():
    assert set(stakeholders.STAKEHOLDER_NOTIFICATION_EVENTS) == {
        "created",
        "priority_changed",
        "status_changed",
        "resolved",
        "comment_added",
    }
    assert "stakeholder_added" not in stakeholders.STAKEHOLDER_NOTIFICATION_EVENTS


def test_stakeholder_added_notification_failure_does_not_break_creation(
    incident, monkeypatch, no_push, no_slack
):
    """Creating a stakeholder must succeed even if notification blows up."""
    monkeypatch.setattr(
        participants,
        "send_plain_email",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("smtp down")),
    )

    user = create_user(group=incident["group"], email="stake@example.com")

    stakeholder = stakeholders.create_incident_stakeholder(
        group_id=incident["alert_group"].id,
        payload={"user_id": user.id},
    )

    assert stakeholder.id is not None


# --- 8.8 best-effort aggregation -------------------------------------------


def test_push_unavailable_but_email_succeeds_is_sent():
    result = participants.ParticipantNotificationResult(attempts=[
        participants.ChannelAttempt("email", "Ann", sent=1),
        participants.ChannelAttempt(
            "browser_push", "Ann", error="no active push subscriptions"
        ),
    ])

    assert result.status == "sent"
    assert result.succeeded_channels == ["email"]
    assert "no active push subscriptions" in result.error_text


def test_all_channels_failing_is_failed():
    result = participants.ParticipantNotificationResult(attempts=[
        participants.ChannelAttempt("email", "Ann", error="smtp down"),
        participants.ChannelAttempt("slack", "Ann", error="slack down"),
    ])

    assert result.status == "failed"
    assert result.sent == 0
    assert result.succeeded_channels == []
    assert "smtp down" in result.error_text
    assert "slack down" in result.error_text


def test_slack_exception_does_not_prevent_email_success(
    incident, captured_emails, monkeypatch, no_push
):
    user = create_user(group=incident["group"], email="ann@example.com")
    user.slack_user_id = "U012ABCDEF"
    user.save()

    monkeypatch.setattr(
        participants,
        "resolve_slack_channel",
        lambda group: object(),
    )

    def boom(channel_type):
        raise RuntimeError("slack exploded")

    monkeypatch.setattr(participants, "get_notifier", boom)

    responder = make_responder(incident["alert_group"], user)
    result = responder_notifications.notify_incident_responder_requested(responder)

    assert result["status"] == "sent"
    assert result["channels"] == ["email"]
    assert "slack exploded" in result["error"]
    assert len(captured_emails) == 1


def test_empty_recipients_returns_failed_without_attempts():
    result = participants.notify_participants(
        None,
        [],
        subject="s",
        body="b",
        slack_text="t",
        push_event_type="e",
    )

    assert result.status == "failed"
    assert result.attempts == []


@pytest.mark.parametrize(
    "user,expected",
    [
        (None, False),
    ],
)
def test_is_notifiable_user_rejects_missing_user(user, expected):
    assert participants.is_notifiable_user(user) is expected


def test_is_notifiable_user_filters_inactive_and_deleted(db):
    group = create_group()

    active = create_user(group=group)
    inactive = create_user(group=group, active=False)

    assert participants.is_notifiable_user(active) is True
    assert participants.is_notifiable_user(inactive) is False


# --- 8.9 auditing -----------------------------------------------------------


def test_successful_notification_writes_alert_event(
    incident, captured_emails, no_push, no_slack
):
    user = create_user(group=incident["group"], email="ann@example.com")
    responder = make_responder(incident["alert_group"], user)

    responder_notifications.notify_incident_responder_requested(responder)

    events = alert_events(incident["alert_group"].id, "responder_notification_sent")

    assert len(events) == 1
    assert "email" in events[0].message


def test_failed_notification_writes_alert_event_with_reason(
    incident, captured_emails, no_push, no_slack
):
    user = create_user(group=incident["group"], email=None)
    responder = make_responder(incident["alert_group"], user)

    responder_notifications.notify_incident_responder_requested(responder)

    events = alert_events(incident["alert_group"].id, "responder_notification_failed")

    assert len(events) == 1
    assert "no email address" in events[0].message


def test_partial_failure_is_recorded_on_success_event(
    incident, captured_emails, no_push, no_slack
):
    user = create_user(group=incident["group"], email="ann@example.com")
    responder = make_responder(incident["alert_group"], user)

    responder_notifications.notify_incident_responder_requested(responder)

    events = alert_events(incident["alert_group"].id, "responder_notification_sent")

    assert "partial failures" in events[0].message
    assert "no active push subscriptions" in events[0].message


def test_stakeholder_added_writes_alert_event(
    incident, captured_emails, no_push, no_slack
):
    user = create_user(group=incident["group"], email="stake@example.com")

    stakeholders.create_incident_stakeholder(
        group_id=incident["alert_group"].id,
        payload={"user_id": user.id},
    )

    events = alert_events(
        incident["alert_group"].id,
        "stakeholder_added_notification_sent",
    )

    assert len(events) == 1
    assert "email" in events[0].message
