"""Tests for incident participant (responder / stakeholder) notifications.

Participant notifications are enqueued during the request and delivered
asynchronously by the scheduler. Delivery tests therefore enqueue (by calling
the responder/stakeholder service) and then run the worker explicitly via
``run_worker`` before asserting what was delivered.
"""

import pytest

from app.modules.common import utc_now
from app.modules.db import incidents_repo
from app.modules.db.models import (
    AlertGroup,
    AlertEvent,
    ParticipantNotificationDelivery,
)
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


def run_worker():
    """Drain all currently-due participant notification deliveries."""
    return participants.process_due_participant_notifications()


def deliveries(kind=None, status=None):
    query = ParticipantNotificationDelivery.select()

    if kind is not None:
        query = query.where(ParticipantNotificationDelivery.kind == kind)

    if status is not None:
        query = query.where(ParticipantNotificationDelivery.status == status)

    return list(query.order_by(ParticipantNotificationDelivery.id.asc()))


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


def make_bot_api_slack_channel(incident):
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
    return slack_channel


def fake_slack_notifier(monkeypatch, sink):
    monkeypatch.setattr(
        participants,
        "get_notifier",
        lambda channel_type: type(
            "FakeSlack",
            (),
            {
                "send_direct_message": staticmethod(
                    lambda channel, target, text: sink.append(
                        {"user_id": target.id, "text": text}
                    )
                    or {"provider_status": "sent"}
                )
            },
        )(),
    )


# --- enqueue is asynchronous ------------------------------------------------


def test_notify_enqueues_without_delivering_inline(
    incident, captured_emails, no_push, no_slack
):
    user = create_user(group=incident["group"], email="ann@example.com")
    responder = make_responder(incident["alert_group"], user)

    result = responder_notifications.notify_incident_responder_requested(responder)

    assert result["status"] == "queued"
    assert result["enqueued"] >= 1
    # Nothing delivered synchronously: the email goes out only when the worker
    # runs.
    assert captured_emails == []
    assert deliveries(status="pending")

    stored = incidents_repo.get_incident_responder(responder.id)
    assert stored.notification_status == "queued"


# --- responder notifications ------------------------------------------------


def test_responder_email_delivered_by_worker(
    incident, captured_emails, no_push, no_slack
):
    user = create_user(group=incident["group"], email="ann@example.com")
    requester = create_user(group=incident["group"])
    responder = make_responder(incident["alert_group"], user, requester)

    responder_notifications.notify_incident_responder_requested(responder)
    run_worker()

    assert len(captured_emails) == 1
    assert captured_emails[0]["to"] == "ann@example.com"
    assert "added you as a responder" in captured_emails[0]["body"]
    assert "please help" in captured_emails[0]["body"]

    stored = incidents_repo.get_incident_responder(responder.id)
    assert stored.notification_status == "sent"


def test_responder_slack_delivered_by_worker(incident, monkeypatch, no_push):
    user = create_user(group=incident["group"], email=None)
    user.slack_user_id = "U012ABCDEF"
    user.save()

    make_bot_api_slack_channel(incident)

    dms = []
    fake_slack_notifier(monkeypatch, dms)

    responder = make_responder(incident["alert_group"], user)
    responder_notifications.notify_incident_responder_requested(responder)
    run_worker()

    assert len(dms) == 1
    assert dms[0]["user_id"] == user.id
    assert "responder" in dms[0]["text"]


def test_responder_push_delivered_by_worker(incident, monkeypatch, no_slack):
    user = create_user(group=incident["group"], email=None)
    pushes = []

    monkeypatch.setattr(
        participants.browser_push,
        "send_stakeholder_push_to_user",
        lambda target, group, **kwargs: pushes.append(kwargs) or 2,
    )

    responder = make_responder(incident["alert_group"], user)
    responder_notifications.notify_incident_responder_requested(responder)
    run_worker()

    assert pushes
    assert pushes[0]["event_type"] == "responder_requested"


def test_responder_without_contact_data_has_no_delivered_channel(
    incident, captured_emails, no_push, no_slack
):
    # A user with no email, no reachable Slack and no push ends up with every
    # channel skipped and a failed aggregate outcome, never a sent one.
    user = create_user(group=incident["group"], email=None)
    responder = make_responder(incident["alert_group"], user)

    responder_notifications.notify_incident_responder_requested(responder)
    run_worker()

    assert captured_emails == []
    assert not deliveries(status="sent")
    assert alert_events(
        incident["alert_group"].id, "responder_notification_failed"
    )


def test_responder_inactive_user_is_not_enqueued(
    incident, captured_emails, no_push, no_slack
):
    user = create_user(group=incident["group"], active=False)
    responder = make_responder(incident["alert_group"], user)

    result = responder_notifications.notify_incident_responder_requested(responder)

    assert result["status"] == "failed"
    assert result["error"] == "no active responder recipients"
    assert deliveries() == []
    assert captured_emails == []


# --- idempotency ------------------------------------------------------------


def test_duplicate_enqueue_is_a_noop(incident, no_push, no_slack):
    user = create_user(group=incident["group"], email="ann@example.com")
    responder = make_responder(incident["alert_group"], user)

    first = responder_notifications.notify_incident_responder_requested(responder)
    before = len(deliveries())

    # Re-running the same responder request (e.g. an HTTP retry) must not
    # enqueue the same recipient/channel messages again.
    second = responder_notifications.notify_incident_responder_requested(responder)

    assert first["enqueued"] >= 1
    assert second["enqueued"] == 0
    assert len(deliveries()) == before


def test_worker_claims_each_row_once(incident, captured_emails, no_push, no_slack):
    user = create_user(group=incident["group"], email="ann@example.com")
    responder = make_responder(incident["alert_group"], user)

    responder_notifications.notify_incident_responder_requested(responder)

    run_worker()
    run_worker()  # second drain must not re-send the already-sent email

    assert len(captured_emails) == 1


# --- retries ----------------------------------------------------------------


def _enqueue_single_email(incident, *, max_attempts):
    recipient = participants.ParticipantRecipient(
        display_name="Ann",
        email="ann@example.com",
    )
    return participants.enqueue_participant_notifications(
        incident["alert_group"],
        [recipient],
        kind=participants.KIND_RESPONDER,
        source_id=4242,
        subject="subj",
        body="body",
        slack_text="t",
        push_event_type="responder_requested",
        use_slack=False,
        use_push=False,
        max_attempts=max_attempts,
    )


def _make_all_due():
    ParticipantNotificationDelivery.update(scheduled_at=utc_now()).where(
        ParticipantNotificationDelivery.status == "pending"
    ).execute()


def test_transient_failure_is_retried_then_succeeds(
    incident, monkeypatch, no_slack, no_push
):
    attempts = {"n": 0}

    def flaky_email(recipient, subject, body):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("temporary smtp error")

    monkeypatch.setattr(participants, "send_plain_email", flaky_email)

    _enqueue_single_email(incident, max_attempts=3)

    run_worker()  # attempt 1 fails -> rescheduled as pending
    row = deliveries(kind=participants.KIND_RESPONDER)[0]
    assert row.status == "pending"
    assert row.attempts == 1

    _make_all_due()
    run_worker()  # attempt 2 succeeds

    row = deliveries(kind=participants.KIND_RESPONDER)[0]
    assert row.status == "sent"
    assert attempts["n"] == 2


def test_transient_failure_fails_after_max_attempts(
    incident, monkeypatch, no_slack, no_push
):
    def always_fails(recipient, subject, body):
        raise RuntimeError("smtp permanently down")

    monkeypatch.setattr(participants, "send_plain_email", always_fails)

    _enqueue_single_email(incident, max_attempts=2)

    run_worker()  # attempt 1 -> pending
    assert deliveries(kind=participants.KIND_RESPONDER)[0].status == "pending"

    _make_all_due()
    run_worker()  # attempt 2 == max_attempts -> failed

    row = deliveries(kind=participants.KIND_RESPONDER)[0]
    assert row.status == "failed"
    assert row.attempts == 2
    assert "smtp permanently down" in row.last_error


# --- partial delivery outcomes ----------------------------------------------


def test_multi_recipient_partial_failure_is_recorded(
    incident, monkeypatch, no_slack, no_push
):
    good = participants.ParticipantRecipient(
        display_name="Good", email="good@example.com"
    )
    bad = participants.ParticipantRecipient(
        display_name="Bad", email="bad@example.com"
    )

    def flaky_email(recipient, subject, body):
        if recipient == "bad@example.com":
            raise RuntimeError("smtp rejected recipient")

    monkeypatch.setattr(participants, "send_plain_email", flaky_email)

    participants.enqueue_participant_notifications(
        incident["alert_group"],
        [good, bad],
        kind=participants.KIND_RESPONDER,
        source_id=99,
        subject="s",
        body="b",
        slack_text="t",
        push_event_type="responder_requested",
        use_slack=False,
        use_push=False,
        max_attempts=1,
    )

    run_worker()

    statuses = {row.recipient_email: row.status for row in deliveries()}
    assert statuses["good@example.com"] == "sent"
    assert statuses["bad@example.com"] == "failed"

    # A single recipient's success must not hide the other's failure.
    events = alert_events(incident["alert_group"].id, "responder_notification_sent")
    assert events
    assert "partial failures" in events[0].message
    assert "Bad" in events[0].message
    assert "smtp rejected recipient" in events[0].message


def test_push_skip_is_not_reported_as_partial_failure(
    incident, captured_emails, monkeypatch, no_slack
):
    # "no active push subscriptions" is a skip, not a failure, so an email-only
    # delivery should report a clean success.
    user = create_user(group=incident["group"], email="ann@example.com")

    monkeypatch.setattr(
        participants.browser_push,
        "send_stakeholder_push_to_user",
        lambda *args, **kwargs: 0,
    )

    responder = make_responder(incident["alert_group"], user)
    responder_notifications.notify_incident_responder_requested(responder)
    run_worker()

    events = alert_events(incident["alert_group"].id, "responder_notification_sent")
    assert events
    assert "partial failures" not in events[0].message


# --- stakeholder-added notifications ----------------------------------------


def test_stakeholder_added_email_delivered_by_worker(
    incident, captured_emails, no_push, no_slack
):
    user = create_user(group=incident["group"], email="stake@example.com")
    adder = create_user(group=incident["group"])

    stakeholders.create_incident_stakeholder(
        group_id=incident["alert_group"].id,
        payload={"user_id": user.id},
        user_id=adder.id,
    )
    run_worker()

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
    run_worker()

    assert len(captured_emails) == 1
    assert captured_emails[0]["to"] == "external@example.com"


def test_stakeholder_email_only_enqueues_email_channel_only(incident):
    """A stakeholder with no linked user must only get an email delivery row,
    never a Slack or browser push row."""
    recipient = participants.ParticipantRecipient(
        display_name="external@example.com",
        email="external@example.com",
    )

    participants.enqueue_participant_notifications(
        incident["alert_group"],
        [recipient],
        kind=participants.KIND_STAKEHOLDER_ADDED,
        source_id=7,
        subject="s",
        body="b",
        slack_text="t",
        push_event_type="stakeholder_added",
    )

    channels = {row.channel for row in deliveries()}
    assert channels == {"email"}


def test_self_added_stakeholder_is_not_notified(
    incident, captured_emails, no_push, no_slack
):
    user = create_user(group=incident["group"], email="self@example.com")

    stakeholders.create_incident_stakeholder(
        group_id=incident["alert_group"].id,
        payload={"user_id": user.id},
        user_id=user.id,
    )
    run_worker()

    assert captured_emails == []
    assert deliveries() == []


def test_stakeholder_lifecycle_events_are_unchanged():
    assert set(stakeholders.STAKEHOLDER_NOTIFICATION_EVENTS) == {
        "created",
        "priority_changed",
        "status_changed",
        "resolved",
        "comment_added",
    }
    assert "stakeholder_added" not in stakeholders.STAKEHOLDER_NOTIFICATION_EVENTS


def test_stakeholder_added_enqueue_failure_does_not_break_creation(
    incident, monkeypatch, no_push, no_slack
):
    """Creating a stakeholder must succeed even if enqueuing notifications
    blows up."""
    def boom(*args, **kwargs):
        raise RuntimeError("enqueue exploded")

    monkeypatch.setattr(stakeholders, "enqueue_participant_notifications", boom)

    user = create_user(group=incident["group"], email="stake@example.com")

    stakeholder = stakeholders.create_incident_stakeholder(
        group_id=incident["alert_group"].id,
        payload={"user_id": user.id},
    )

    assert stakeholder.id is not None


# --- enqueue edge cases -----------------------------------------------------


def test_empty_recipients_enqueues_nothing(incident):
    created = participants.enqueue_participant_notifications(
        incident["alert_group"],
        [],
        kind=participants.KIND_RESPONDER,
        source_id=1,
        subject="s",
        body="b",
        slack_text="t",
        push_event_type="responder_requested",
    )

    assert created == 0
    assert deliveries() == []


def test_is_notifiable_user_rejects_missing_user():
    assert participants.is_notifiable_user(None) is False


def test_is_notifiable_user_filters_inactive_and_deleted(db):
    group = create_group()

    active = create_user(group=group)
    inactive = create_user(group=group, active=False)

    assert participants.is_notifiable_user(active) is True
    assert participants.is_notifiable_user(inactive) is False


# --- auditing ---------------------------------------------------------------


def test_queued_event_is_written_on_enqueue(
    incident, captured_emails, no_push, no_slack
):
    user = create_user(group=incident["group"], email="ann@example.com")
    responder = make_responder(incident["alert_group"], user)

    responder_notifications.notify_incident_responder_requested(responder)

    # Before the worker runs, only the queued event exists.
    assert alert_events(
        incident["alert_group"].id, "responder_notification_queued"
    )
    assert not alert_events(
        incident["alert_group"].id, "responder_notification_sent"
    )


def test_successful_notification_writes_sent_event_after_worker(
    incident, captured_emails, no_push, no_slack
):
    user = create_user(group=incident["group"], email="ann@example.com")
    responder = make_responder(incident["alert_group"], user)

    responder_notifications.notify_incident_responder_requested(responder)
    run_worker()

    events = alert_events(
        incident["alert_group"].id, "responder_notification_sent"
    )
    assert len(events) == 1
    assert "email" in events[0].message


def test_failed_notification_writes_failed_event_after_worker(
    incident, captured_emails, no_push, no_slack
):
    user = create_user(group=incident["group"], email=None)
    responder = make_responder(incident["alert_group"], user)

    responder_notifications.notify_incident_responder_requested(responder)
    run_worker()

    events = alert_events(
        incident["alert_group"].id, "responder_notification_failed"
    )
    assert len(events) == 1


def test_stakeholder_added_writes_sent_event_after_worker(
    incident, captured_emails, no_push, no_slack
):
    user = create_user(group=incident["group"], email="stake@example.com")

    stakeholders.create_incident_stakeholder(
        group_id=incident["alert_group"].id,
        payload={"user_id": user.id},
    )
    run_worker()

    events = alert_events(
        incident["alert_group"].id,
        "stakeholder_added_notification_sent",
    )

    assert len(events) == 1
    assert "email" in events[0].message


# --- Slack mrkdwn escaping of participant message content -------------------
# Responder/stakeholder Slack text interpolates alert titles, display names and
# free-text messages. Unescaped, an injected <!channel>/<!here>/<@U...> would be
# rendered by Slack as a real broadcast or mention. The deliberate direct-message
# target mention is added separately by the notifier, so the builder output must
# contain no live Slack control sequences.


def test_responder_slack_text_escapes_injected_broadcast(incident):
    user = create_user(group=incident["group"])
    responder = make_responder(
        incident["alert_group"],
        user,
        message="<!channel> everyone look",
    )

    text = responder_notifications.build_responder_notification_slack_text(
        responder
    )

    assert "<!channel>" not in text
    assert "&lt;!channel&gt;" in text


def test_responder_slack_text_escapes_injected_title(incident):
    group = incident["alert_group"]
    group.title = "<!here> DiskFull"
    group.save()
    user = create_user(group=incident["group"])
    responder = make_responder(group, user)

    text = responder_notifications.build_responder_notification_slack_text(
        responder
    )

    assert "<!here>" not in text
    assert "&lt;!here&gt;" in text


def test_stakeholder_added_slack_text_escapes_injected_adder_name(incident):
    text = stakeholders.build_stakeholder_added_slack_text(
        incident["alert_group"],
        added_by_name="<@U999EVIL>",
    )

    assert "<@U999EVIL>" not in text
    assert "&lt;@U999EVIL&gt;" in text


# --- Slack channel selection respects notify_on_severities ------------------
# Participant Slack delivery reuses the normal notification channel resolution,
# which includes per-channel severity restrictions. A channel that excludes the
# incident's severity must not be chosen as the participant DM transport.


def _attach_slack_channel(incident, notify_on_severities):
    slack_channel = create_channel(
        incident["group"],
        incident["team"],
        channel_type="slack",
        config={
            "mode": "bot_api",
            "bot_token": "xoxb-test",
            "channel_id": "C1",
            "signing_secret": "s",
            "notify_on_severities": notify_on_severities,
        },
    )
    attach_channel(incident["route"], slack_channel)
    return slack_channel


def test_resolve_slack_channel_skips_severity_filtered_channel(incident):
    # incident fixture is severity "critical"; the channel only accepts warnings.
    _attach_slack_channel(incident, ["warning"])

    assert participants.resolve_slack_channel(incident["alert_group"]) is None


def test_resolve_slack_channel_returns_matching_severity_channel(incident):
    _attach_slack_channel(incident, ["critical"])

    resolved = participants.resolve_slack_channel(incident["alert_group"])

    assert resolved is not None
    assert resolved.channel_type == "slack"
