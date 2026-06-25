from types import SimpleNamespace

from app.notifiers.telegram.templates import format_telegram_alert_message


def test_telegram_message_contains_incident_priority():
    alert = SimpleNamespace(
        id=123,
        title="DiskFull",
        message="/var is 95% full",
        severity="critical",
        status="firing",
        source="alertmanager",
        priority=None,
        priority_slug="p1",
        priority_order=1,
        labels={
            "event_link": "https://monitoring.example.com/events/123",
        },
        team=SimpleNamespace(slug="infra", name="Infrastructure"),
        service=None,
        service_id=None,
        assignee=None,
    )

    message = format_telegram_alert_message(alert)

    assert "[P1] DiskFull" in message
    assert "Priority: P1 Critical" in message
    assert (
        '<a href="https://monitoring.example.com/events/123">'
        "Open source event</a>"
    ) in message
