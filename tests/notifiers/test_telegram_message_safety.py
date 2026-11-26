"""Regression tests for safe message formatting with optional fields.

Dashboard can contain a name or relative path, which creates an invalid link.
Long label values can push the final cutoff inside an HTML tag, causing
Telegram to reject the entire alert. The dashboard link must be validated and
optional fields must be budgeted before assembling the HTML.
"""

from app.modules.db.models import AlertGroup
from app.notifiers.telegram.templates import format_telegram_alert_message, MAX_TELEGRAM_MESSAGE_LENGTH
from tests.factories import (
    create_group,
    create_route,
    create_team,
    create_user,
)


def test_valid_https_dashboard_url_is_included():
    """An absolute HTTPS dashboard URL becomes a link."""

    group = create_group()
    team = create_team(group)
    assignee = create_user(group=group, is_admin=True)
    route = create_route(team)

    alert = AlertGroup.create(
        team=team,
        route=route,
        assignee=assignee,
        source="pytest",
        group_key_hash="hash-valid-https",
        group_key="key-valid-https",
        title="ValidHTTPSDashboard",
        message="test",
        severity="info",
        status="firing",
        common_labels={"dashboard": "https://grafana.example.com/d/abc123"},
    )

    text = format_telegram_alert_message(alert, "notification")

    assert "📊" in text
    assert 'href="https://grafana.example.com/d/abc123"' in text
    assert "Dashboard</a>" in text


def test_valid_http_dashboard_url_is_included():
    """An absolute HTTP dashboard URL becomes a link."""

    group = create_group()
    team = create_team(group)
    assignee = create_user(group=group, is_admin=True)
    route = create_route(team)

    alert = AlertGroup.create(
        team=team,
        route=route,
        assignee=assignee,
        source="pytest",
        group_key_hash="hash-valid-http",
        group_key="key-valid-http",
        title="ValidHTTPDashboard",
        message="test",
        severity="info",
        status="firing",
        common_labels={"dashboard_url": "http://localhost:3000/d/xyz"},
    )

    text = format_telegram_alert_message(alert, "notification")

    assert "📊" in text
    assert 'href="http://localhost:3000/d/xyz"' in text
    assert "Dashboard</a>" in text


def test_dashboard_name_is_omitted_and_alert_renders():
    """A dashboard name is not an absolute URL. The link is omitted."""

    group = create_group()
    team = create_team(group)
    assignee = create_user(group=group, is_admin=True)
    route = create_route(team)

    alert = AlertGroup.create(
        team=team,
        route=route,
        assignee=assignee,
        source="pytest",
        group_key_hash="hash-name",
        group_key="key-name",
        title="DashboardName",
        message="test",
        severity="info",
        status="firing",
        common_labels={"dashboard": "My Dashboard"},
    )

    text = format_telegram_alert_message(alert, "notification")

    assert "📊" not in text
    assert "My Dashboard" not in text
    assert "DashboardName" in text
    assert "Message:" in text


def test_relative_dashboard_path_is_omitted_and_alert_renders():
    """A relative dashboard path is not an absolute URL. The link is omitted."""

    group = create_group()
    team = create_team(group)
    assignee = create_user(group=group, is_admin=True)
    route = create_route(team)

    alert = AlertGroup.create(
        team=team,
        route=route,
        assignee=assignee,
        source="pytest",
        group_key_hash="hash-relative",
        group_key="key-relative",
        title="RelativeDashboard",
        message="test",
        severity="info",
        status="firing",
        common_labels={"dashboard_url": "/d/abc123"},
    )

    text = format_telegram_alert_message(alert, "notification")

    assert "📊" not in text
    assert "/d/abc123" not in text
    assert "RelativeDashboard" in text
    assert "Message:" in text


def test_long_labels_do_not_break_html():
    """Very long label values are budgeted so the message stays under the limit."""

    group = create_group()
    team = create_team(group)
    assignee = create_user(group=group, is_admin=True)
    route = create_route(team)

    long_value = "A" * 2000

    alert = AlertGroup.create(
        team=team,
        route=route,
        assignee=assignee,
        source="pytest",
        group_key_hash="hash-long",
        group_key="key-long",
        title="LongLabels",
        message="test",
        severity="info",
        status="firing",
        common_labels={"very_long_label": long_value},
    )

    text = format_telegram_alert_message(alert, "notification")

    assert len(text) <= MAX_TELEGRAM_MESSAGE_LENGTH
    assert "LongLabels" in text
    assert "Message:" in text
    assert text.count("<") == text.count(">")


def test_long_labels_with_html_escapes_do_not_break_delivery():
    """Long labels with HTML special characters are escaped and budgeted."""

    group = create_group()
    team = create_team(group)
    assignee = create_user(group=group, is_admin=True)
    route = create_route(team)

    long_value_with_escapes = "<tag>" * 500

    alert = AlertGroup.create(
        team=team,
        route=route,
        assignee=assignee,
        source="pytest",
        group_key_hash="hash-escapes",
        group_key="key-escapes",
        title="LongEscapes",
        message="test",
        severity="info",
        status="firing",
        common_labels={"escaped_label": long_value_with_escapes},
    )

    text = format_telegram_alert_message(alert, "notification")

    assert len(text) <= MAX_TELEGRAM_MESSAGE_LENGTH
    assert "LongEscapes" in text
    assert "Message:" in text
    assert "&lt;tag&gt;" in text or "…" in text


def test_core_fields_always_present_when_optional_fields_are_too_long():
    """Title, status, and actions stay even when optional fields overflow."""

    group = create_group()
    team = create_team(group)
    assignee = create_user(group=group, is_admin=True)
    route = create_route(team)

    alert = AlertGroup.create(
        team=team,
        route=route,
        assignee=assignee,
        source="pytest",
        group_key_hash="hash-core",
        group_key="key-core",
        title="CoreFields",
        message="x" * MAX_TELEGRAM_MESSAGE_LENGTH,
        severity="critical",
        status="firing",
        common_labels={"huge": "Y" * MAX_TELEGRAM_MESSAGE_LENGTH},
    )

    text = format_telegram_alert_message(alert, "notification")

    assert len(text) <= MAX_TELEGRAM_MESSAGE_LENGTH
    assert "CoreFields" in text
    assert "Status:" in text
    assert "Priority:" in text
