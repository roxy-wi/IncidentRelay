from datetime import datetime, timedelta

from app.modules.db.models import OnCallShiftEmailNotification
from app.services.notifications import shift_notifications as shift_email_service
from app.services.notifications.shift_notifications import (
    send_due_oncall_shift_email_notifications,
)
from tests.factories import (
    add_user_to_team,
    create_group,
    create_rotation,
    create_rotation_override,
    create_team,
    create_user,
)


def test_shift_start_email_is_sent_once(db, monkeypatch):
    sent = []

    def fake_send(to_email, subject, body):
        sent.append((to_email, subject, body))

    monkeypatch.setattr(
        shift_email_service,
        "_send_plain_email",
        fake_send,
    )

    start = datetime(2026, 5, 30, 9, 0, 0)

    group = create_group(slug="infra")
    team = create_team(group, slug="sre", name="SRE")
    alice = create_user("alice", group, email="alice@example.com")
    add_user_to_team(team, alice)

    create_rotation(
        team,
        name="Primary",
        users=[alice],
        start_at=start,
        duration_seconds=3600,
    )

    count = send_due_oncall_shift_email_notifications(
        now=start + timedelta(seconds=10),
        lookback_seconds=60,
    )

    assert count == 1
    assert len(sent) == 1
    assert sent[0][0] == "alice@example.com"
    assert "shift has started" in sent[0][1]
    assert "Team: SRE" in sent[0][2]
    assert "Rotation: Primary" in sent[0][2]

    count = send_due_oncall_shift_email_notifications(
        now=start + timedelta(seconds=20),
        lookback_seconds=60,
    )

    assert count == 0
    assert len(sent) == 1
    assert OnCallShiftEmailNotification.select().count() == 1


def test_shift_end_email_is_sent(db, monkeypatch):
    sent = []

    monkeypatch.setattr(
        shift_email_service,
        "_send_plain_email",
        lambda to_email, subject, body: sent.append((to_email, subject, body)),
    )

    start = datetime(2026, 5, 30, 9, 0, 0)

    group = create_group(slug="infra")
    team = create_team(group, slug="sre", name="SRE")

    alice = create_user("alice", group, email="alice@example.com")
    bob = create_user("bob", group, email="bob@example.com")

    bob.notify_oncall_shift_start_email = False
    bob.save()

    add_user_to_team(team, alice)
    add_user_to_team(team, bob)

    create_rotation(
        team,
        name="Primary",
        users=[alice, bob],
        start_at=start,
        duration_seconds=3600,
    )

    count = send_due_oncall_shift_email_notifications(
        now=start + timedelta(hours=1, seconds=10),
        lookback_seconds=60,
    )

    assert count == 1
    assert len(sent) == 1
    assert sent[0][0] == "alice@example.com"
    assert "shift has ended" in sent[0][1]


def test_shift_handoff_sends_end_and_start_emails(db, monkeypatch):
    sent = []

    monkeypatch.setattr(
        shift_email_service,
        "_send_plain_email",
        lambda to_email, subject, body: sent.append((to_email, subject, body)),
    )

    start = datetime(2026, 5, 30, 9, 0, 0)

    group = create_group(slug="infra")
    team = create_team(group, slug="sre", name="SRE")

    alice = create_user("alice", group, email="alice@example.com")
    bob = create_user("bob", group, email="bob@example.com")

    add_user_to_team(team, alice)
    add_user_to_team(team, bob)

    create_rotation(
        team,
        name="Primary",
        users=[alice, bob],
        start_at=start,
        duration_seconds=3600,
    )

    count = send_due_oncall_shift_email_notifications(
        now=start + timedelta(hours=1, seconds=10),
        lookback_seconds=60,
    )

    assert count == 2
    assert len(sent) == 2

    sent_by_email = {
        to_email: (subject, body)
        for to_email, subject, body in sent
    }

    assert "alice@example.com" in sent_by_email
    assert "bob@example.com" in sent_by_email

    alice_subject, alice_body = sent_by_email["alice@example.com"]
    bob_subject, bob_body = sent_by_email["bob@example.com"]

    assert "shift has ended" in alice_subject
    assert "Rotation: Primary" in alice_body
    assert "Team: SRE" in alice_body

    assert "shift has started" in bob_subject
    assert "Rotation: Primary" in bob_body
    assert "Team: SRE" in bob_body

    # Same scheduler window must not resend the same transition emails.
    count = send_due_oncall_shift_email_notifications(
        now=start + timedelta(hours=1, seconds=20),
        lookback_seconds=60,
    )

    assert count == 0
    assert len(sent) == 2


def test_shift_email_respects_user_preferences(db, monkeypatch):
    sent = []

    monkeypatch.setattr(
        shift_email_service,
        "_send_plain_email",
        lambda to_email, subject, body: sent.append((to_email, subject, body)),
    )

    start = datetime(2026, 5, 30, 9, 0, 0)

    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    alice = create_user("alice", group, email="alice@example.com")
    alice.notify_oncall_shift_start_email = False
    alice.notify_oncall_shift_end_email = False
    alice.save()

    add_user_to_team(team, alice)

    create_rotation(
        team,
        name="Primary",
        users=[alice],
        start_at=start,
        duration_seconds=3600,
    )

    count = send_due_oncall_shift_email_notifications(
        now=start + timedelta(seconds=10),
        lookback_seconds=60,
    )

    assert count == 0
    assert sent == []


def test_shift_email_requires_user_email(db, monkeypatch):
    sent = []

    monkeypatch.setattr(
        shift_email_service,
        "_send_plain_email",
        lambda to_email, subject, body: sent.append((to_email, subject, body)),
    )

    start = datetime(2026, 5, 30, 9, 0, 0)

    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    alice = create_user("alice", group, email=None)
    add_user_to_team(team, alice)

    create_rotation(
        team,
        name="Primary",
        users=[alice],
        start_at=start,
        duration_seconds=3600,
    )

    count = send_due_oncall_shift_email_notifications(
        now=start + timedelta(seconds=10),
        lookback_seconds=60,
    )

    assert count == 0
    assert sent == []


def test_shift_notifications_keep_full_boundaries_and_log_timestamps(db, monkeypatch):
    sent = []
    monkeypatch.setattr(
        shift_email_service,
        "_send_plain_email",
        lambda recipient, subject, body: sent.append((recipient, subject, body)),
    )
    start = datetime(2026, 5, 30, 9, 0)
    group = create_group()
    team = create_team(group)
    alice = create_user(group=group, email="alice@example.com")
    bob = create_user(group=group, email="bob@example.com")
    add_user_to_team(team, alice)
    add_user_to_team(team, bob)
    create_rotation(team, users=[alice, bob], start_at=start, duration_seconds=3600)

    assert shift_email_service.send_due_oncall_shift_email_notifications(
        now=start + timedelta(seconds=10), lookback_seconds=60
    ) == 1
    assert "Starts at: 2026-05-30 09:00:00 UTC" in sent[0][2]
    assert "Ends at: 2026-05-30 10:00:00 UTC" in sent[0][2]

    assert shift_email_service.send_due_oncall_shift_email_notifications(
        now=start + timedelta(hours=1, seconds=10), lookback_seconds=60
    ) == 2  # Alice ends, Bob starts
    end_message = next(body for to, subject, body in sent if "shift has ended" in subject)
    assert "Starts at: 2026-05-30 09:00:00 UTC" in end_message
    assert "Ends at: 2026-05-30 10:00:00 UTC" in end_message
    alice_logs = list(OnCallShiftEmailNotification.select().where(
        OnCallShiftEmailNotification.user == alice.id
    ))
    assert len(alice_logs) == 2
    assert {row.slot_start_at for row in alice_logs} == {start}
    assert {row.slot_end_at for row in alice_logs} == {start + timedelta(hours=1)}
    assert shift_email_service.send_due_oncall_shift_email_notifications(
        now=start + timedelta(hours=1, seconds=20), lookback_seconds=60
    ) == 0


def test_override_shift_email_uses_override_bounds(db, monkeypatch):
    sent = []
    monkeypatch.setattr(shift_email_service, "_send_plain_email",
                        lambda to, subject, body: sent.append(body))
    start = datetime(2026, 5, 30, 9)
    group = create_group()
    team = create_team(group)
    alice = create_user(group=group, email="alice@example.com")
    bob = create_user(group=group, email="bob@example.com")
    add_user_to_team(team, alice)
    add_user_to_team(team, bob)
    rotation = create_rotation(team, users=[alice], start_at=start, duration_seconds=3600)
    create_rotation_override(rotation, bob,
                             starts_at=start + timedelta(minutes=15),
                             ends_at=start + timedelta(hours=2, minutes=15))
    assert shift_email_service.send_due_oncall_shift_email_notifications(
        now=start + timedelta(minutes=15, seconds=10), lookback_seconds=60
    ) >= 1
    assert any("Starts at: 2026-05-30 09:15:00 UTC" in body
               and "Ends at: 2026-05-30 11:15:00 UTC" in body
               for body in sent)


def test_mattermost_shift_start_receives_full_slot(db, monkeypatch):
    start = datetime(2026, 5, 30, 9)
    group = create_group()
    team = create_team(group)
    alice = create_user(group=group)
    bob = create_user(group=group)
    add_user_to_team(team, alice)
    add_user_to_team(team, bob)
    create_rotation(team, users=[alice, bob], start_at=start, duration_seconds=3600)
    delivered = []
    monkeypatch.setattr(
        shift_email_service,
        "_send_shift_event_to_mattermost",
        lambda event, event_type: delivered.append((event, event_type)) or True,
    )
    assert shift_email_service.send_due_oncall_shift_mattermost_notifications(
        now=start + timedelta(seconds=10), lookback_seconds=60
    ) == 1
    event, event_type = delivered[0]
    assert event_type == "shift_start"
    assert event["start"].startswith("2026-05-30T09:00:00")
    assert event["end"].startswith("2026-05-30T10:00:00")
