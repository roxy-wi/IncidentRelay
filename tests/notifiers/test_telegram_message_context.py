from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.notifiers.mattermost.notifier import MattermostNotifier
from app.notifiers.telegram.templates import format_telegram_alert_message


def _alert(**overrides):
    started = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    data = dict(
        id=123,
        title="DiskFull",
        message="/var is 95% full",
        severity="critical",
        status="firing",
        source="alertmanager",
        priority=None,
        priority_slug="p1",
        priority_order=1,
        first_seen_at=started,
        reminder_count=2,
        labels={"cluster": "prod", "namespace": "payments"},
        common_labels=None,
        payload_summary={
            "latest_payload": {
                "annotations": {"dashboard": "https://grafana.example/d/abc"},
            }
        },
        team=SimpleNamespace(slug="infra", name="Infrastructure"),
        service=None,
        service_id=None,
        assignee=None,
    )
    data.update(overrides)
    return SimpleNamespace(**data)


def test_telegram_message_adds_context_without_dropping_priority():
    message = format_telegram_alert_message(_alert())

    assert "Priority: P1 Critical" in message
    assert "Alert ID: #123" in message
    assert "Cluster: prod" in message
    assert "Namespace: payments" in message
    assert "🕒 <b>Started:</b> 22.10.2026 09:00:00 UTC" in message
    assert '📊 <a href="https://grafana.example/d/abc">Dashboard</a>' in message


def test_reminder_shows_how_long_the_alert_has_been_firing(monkeypatch):
    started = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc).replace(tzinfo=None)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return started.replace(tzinfo=timezone.utc) + timedelta(minutes=45)

    monkeypatch.setattr(
        "app.notifiers.telegram.templates.datetime",
        FrozenDatetime,
    )

    message = format_telegram_alert_message(_alert(), "reminder")

    assert "Reminder count:" in message
    assert "2" in message
    assert "Firing for:</b> 45m" in message


def test_acknowledged_marker_is_not_the_resolved_marker():
    message = format_telegram_alert_message(
        _alert(status="acknowledged"),
        "acknowledged",
    )

    assert "👀" in message
    assert "✅" not in message


def test_mattermost_fields_include_the_same_labels_and_dashboard():
    fields = MattermostNotifier()._fields(_alert())
    titles = {field["title"]: field["value"] for field in fields}

    assert titles["Cluster"] == "prod"
    assert titles["Namespace"] == "payments"
    assert titles["Dashboard"] == "https://grafana.example/d/abc"
    assert titles["Priority"] == "P1 Critical"
