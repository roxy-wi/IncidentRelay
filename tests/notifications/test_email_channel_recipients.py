"""Issue #129: email channel assignee, fallback and fixed-recipient contract."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.schemas.channels import ChannelCreateSchema, ChannelUpdateSchema
from app.notifiers.email.notifier import EmailNotifier
from app.notifiers.email.recipients import (
    normalize_email_recipient_config,
    resolve_email_channel_recipient,
)
from app.settings import Config


def channel_payload(config):
    return {
        "team_id": 1,
        "name": "Backup email",
        "channel_type": "email",
        "config": config,
        "enabled": True,
    }


def test_missing_mode_keeps_old_empty_config():
    assert ChannelCreateSchema.model_validate(channel_payload({})).config == {}
    assert resolve_email_channel_recipient({}, "user@example.com") == (
        "user@example.com", "assignee.email",
    )
    with pytest.raises(RuntimeError, match="assignee has no email"):
        resolve_email_channel_recipient({}, None)


@pytest.mark.parametrize("mode", ["fallback", "fixed"])
def test_email_channel_accepts_and_normalizes_recipient_modes(mode):
    config = ChannelCreateSchema.model_validate(channel_payload({
        "recipient_mode": mode,
        "recipient_email": "  Backup@EXAMPLE.COM  ",
        "notify_on_severities": ["critical"],
    })).config
    assert config == {
        "recipient_mode": mode,
        "recipient_email": "Backup@example.com",
        "notify_on_severities": ["critical"],
    }


@pytest.mark.parametrize("mode", ["fallback", "fixed"])
def test_required_recipient_rejects_empty_config(mode):
    for address in (None, "", "   "):
        with pytest.raises(ValidationError, match="recipient_email is required"):
            ChannelCreateSchema.model_validate(channel_payload({
                "recipient_mode": mode, "recipient_email": address,
            }))


@pytest.mark.parametrize("value", [
    "invalid", "first@example.com,second@example.com",
    "Ops Team <ops@example.com>",
    "person@example.com\nBcc:evil@example.com",
    "a@bad..example",
    "a" * 260 + "@example.com",
    42,
])
def test_recipient_config_rejects_invalid_or_header_injection(value):
    with pytest.raises(ValidationError, match="recipient_email"):
        ChannelCreateSchema.model_validate(channel_payload({
            "recipient_mode": "fixed", "recipient_email": value,
        }))


@pytest.mark.parametrize("value", [None, "", "assignee_with_fallback", True, [], 1])
def test_rejects_unsupported_recipient_mode(value):
    with pytest.raises(ValidationError, match="recipient_mode"):
        ChannelCreateSchema.model_validate(channel_payload({"recipient_mode": value}))


def test_switch_to_assignee_removes_unused_recipient():
    schema = ChannelUpdateSchema.model_validate(channel_payload({
        "recipient_mode": "assignee",
        "recipient_email": "old@example.com",
    }))
    assert schema.config == {}
    assert normalize_email_recipient_config({
        "recipient_mode": "assignee", "recipient_email": "old@example.com",
    }) == {}


@pytest.mark.parametrize("assignee,expected,source", [
    ("owner@example.com", "owner@example.com", "assignee.email"),
    (None, "backup@example.com", "channel.fallback_recipient"),
    ("   ", "backup@example.com", "channel.fallback_recipient"),
])
def test_fallback_mode_uses_assignee_when_available(assignee, expected, source):
    assert resolve_email_channel_recipient({
        "recipient_mode": "fallback", "recipient_email": "backup@example.com",
    }, assignee) == (expected, source)


def test_fixed_mode_always_uses_channel_recipient():
    config = {"recipient_mode": "fixed", "recipient_email": "team@example.com"}
    assert resolve_email_channel_recipient(config, "owner@example.com") == (
        "team@example.com", "channel.fixed_recipient",
    )
    assert resolve_email_channel_recipient(config, None) == (
        "team@example.com", "channel.fixed_recipient",
    )


def test_test_mode_bypasses_fixed_destination_and_requires_requester_email():
    config = {"recipient_mode": "fixed", "recipient_email": "team@example.com"}
    assert resolve_email_channel_recipient(config, "tester@example.com", is_test=True) == (
        "tester@example.com", "test_user.email",
    )
    with pytest.raises(RuntimeError, match="email test recipient"):
        resolve_email_channel_recipient(config, None, is_test=True)


def test_recipient_selection_fails_closed_for_corrupted_persisted_config():
    with pytest.raises(ValueError, match="recipient_email"):
        resolve_email_channel_recipient({
            "recipient_mode": "fixed", "recipient_email": "fake,another@example.com",
        }, "owner@example.com")


def test_channel_api_persists_recipient_mode_and_removes_address_on_switch(client, admin_headers, db):
    from tests.factories import create_group, create_team

    group = create_group()
    team = create_team(group)
    payload = channel_payload({
        "recipient_mode": "fixed", "recipient_email": "team@example.com",
    })
    payload["team_id"] = team.id

    created = client.post("/api/channels", headers=admin_headers, json=payload)
    assert created.status_code == 201
    channel_id = created.get_json()["id"]
    retrieved = client.get(f"/api/channels/{channel_id}", headers=admin_headers)
    assert retrieved.status_code == 200
    assert retrieved.get_json()["config"]["recipient_email"] == "team@example.com"

    payload["config"] = {
        "recipient_mode": "assignee", "recipient_email": "team@example.com",
    }
    updated = client.put(f"/api/channels/{channel_id}", headers=admin_headers, json=payload)
    assert updated.status_code == 200
    assert updated.get_json()["config"] == {}


def test_channel_api_rejects_invalid_fixed_recipient(client, admin_headers, db):
    from tests.factories import create_group, create_team

    group = create_group()
    team = create_team(group)
    payload = channel_payload({
        "recipient_mode": "fixed", "recipient_email": "evil\nBcc:a@example.com",
    })
    payload["team_id"] = team.id
    response = client.post("/api/channels", headers=admin_headers, json=payload)
    assert response.status_code == 400


def test_channel_test_action_uses_requester_profile_not_fixed_mailbox(
    client, admin_headers, db, monkeypatch,
):
    from tests.factories import create_group, create_team, create_channel

    _configure_fake_smtp(monkeypatch)
    group = create_group()
    team = create_team(group)
    channel = create_channel(group, team, channel_type="email", config={
        "recipient_mode": "fixed", "recipient_email": "team@example.com",
    })
    response = client.post(f"/api/channels/{channel.id}/test", headers=admin_headers)
    assert response.status_code == 200
    assert FakeSMTP.sent[0]["To"] == "admin@example.com"


class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout):
        assert host == "localhost"
        assert port == 2525
        assert timeout == 10

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def ehlo(self):
        pass

    def send_message(self, message):
        self.sent.append(message)


def _configure_fake_smtp(monkeypatch):
    FakeSMTP.sent = []
    monkeypatch.setattr("app.notifiers.email.notifier.smtplib.SMTP", FakeSMTP)
    monkeypatch.setattr("app.notifiers.email.notifier.render_email_html", lambda *_args, **_kwargs: "<b>Test</b>")
    for key, value in {
        "SMTP_HOST": "localhost", "SMTP_PORT": "2525", "SMTP_FROM": "ir@example.com",
        "SMTP_USE_TLS": False, "SMTP_USER": "", "SMTP_PASSWORD": "",
    }.items():
        monkeypatch.setattr(Config, key, value)


def _test_alert(email=None):
    return SimpleNamespace(
        id=42, title="DiskFull", status="firing", severity="critical",
        assignee=SimpleNamespace(email=email) if email else None,
    )


@pytest.mark.parametrize("mode,assignee,expected,source", [
    ("fallback", None, "fallback@example.com", "channel.fallback_recipient"),
    ("fallback", "user@example.com", "user@example.com", "assignee.email"),
    ("fixed", None, "fallback@example.com", "channel.fixed_recipient"),
    ("fixed", "user@example.com", "fallback@example.com", "channel.fixed_recipient"),
])
def test_notifier_sends_to_correct_mailbox_and_records_only_source(
    monkeypatch, mode, assignee, expected, source,
):
    _configure_fake_smtp(monkeypatch)
    channel = SimpleNamespace(config={
        "recipient_mode": mode, "recipient_email": "fallback@example.com",
    })
    result = EmailNotifier().send(channel, _test_alert(assignee), "alert")
    assert FakeSMTP.sent[0]["To"] == expected
    assert result["provider_payload"] == {"recipient_source": source}
    assert "recipient_email" not in result["provider_payload"]


def test_notifier_legacy_assignee_delivery(monkeypatch):
    _configure_fake_smtp(monkeypatch)
    result = EmailNotifier().send(
        SimpleNamespace(config={}), _test_alert("user@example.com"), "alert",
    )
    assert FakeSMTP.sent[0]["To"] == "user@example.com"
    assert result["provider_payload"]["recipient_source"] == "assignee.email"


def test_notifier_test_event_goes_to_requester_even_with_fixed_channel(monkeypatch):
    _configure_fake_smtp(monkeypatch)
    result = EmailNotifier().send(
        SimpleNamespace(config={
            "recipient_mode": "fixed", "recipient_email": "team@example.com",
        }),
        _test_alert("tester@example.com"), "test message", event_type="test",
    )
    assert FakeSMTP.sent[0]["To"] == "tester@example.com"
    assert result["provider_payload"]["recipient_source"] == "test_user.email"
