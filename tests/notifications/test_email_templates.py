from types import SimpleNamespace

import pytest

from app.notifiers.email.email_templates import (
    DEFAULT_EMAIL_HTML_TEMPLATE,
    normalize_email_html_template,
    render_email_html,
)
from app.services.alerts.priority import format_alert_title_with_priority


def make_alert():
    return SimpleNamespace(
        id=123,
        title="Disk <Full>",
        message="/var is > 95% & growing",
        severity="critical",
        status="firing",
        source="alertmanager",
        priority=None,
        priority_slug="p1",
        priority_order=1,
        team=SimpleNamespace(slug="infra"),
        assignee=SimpleNamespace(username="ivan", display_name="Ivan"),
    )


def test_default_email_template_renders_escaped_values(monkeypatch):
    monkeypatch.setattr("app.services.links.build_alert_web_url", lambda alert: "https://example.test/a?x=1&y=2")

    html = render_email_html(make_alert(), "fallback", "notification")

    assert "P1 Critical" in html
    assert "IncidentRelay" in html
    assert "Disk &lt;Full&gt;" in html
    assert "/var is &gt; 95% &amp; growing" in html
    assert "https://example.test/a?x=1&amp;y=2" in html
    assert DEFAULT_EMAIL_HTML_TEMPLATE.startswith("<!doctype html>")


def test_custom_email_template_renders_known_and_keeps_unknown_placeholders(monkeypatch):
    monkeypatch.setattr("app.services.links.build_alert_web_url", lambda alert: "https://example.test/alerts/123")

    html = render_email_html(make_alert(), "fallback", "resolved", "<b>{title}</b> {unknown}")

    assert "<b>Disk &lt;Full&gt;</b>" in html
    assert "{unknown}" in html


def test_invalid_email_template_braces_are_rejected():
    with pytest.raises(ValueError):
        normalize_email_html_template("<b>{title</b>")


def test_email_title_contains_incident_priority():
    assert format_alert_title_with_priority(make_alert()) == "[P1] Disk <Full>"
