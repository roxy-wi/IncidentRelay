from html import escape
from typing import Any

from app.settings import Config
from app.services.routing.service_context import (
    get_alert_service_links,
    get_alert_service_runbooks,
    link_display_label,
    runbook_display_label,
)
from app.services.alerts.priority import (
    alert_priority_label,
    format_alert_title_with_priority,
)
from app.services.links import build_source_event_url
from app.services.alerts.correlation import format_correlation_plain

MAX_TELEGRAM_MESSAGE_LENGTH = 4096
MAX_ALERT_MESSAGE_LENGTH = 1600


def _service_context_lines(alert: Any) -> list[str]:
    """Return Telegram HTML lines with service links and runbooks."""
    lines = []

    links = get_alert_service_links(alert)
    if links:
        lines.append("")
        lines.append("<b>Links:</b>")
        for link in links:
            label = _html(link_display_label(link))
            url = _attr(getattr(link, "url", None), "")
            if url:
                lines.append(f'• <a href="{url}">{label}</a>')
            else:
                lines.append(f"• {label}")

    runbooks = get_alert_service_runbooks(alert)
    if runbooks:
        lines.append("")
        lines.append("<b>Runbooks:</b>")
        for runbook in runbooks:
            label = _html(runbook_display_label(runbook))
            url = _attr(getattr(runbook, "url", None), "")
            if url:
                lines.append(f'• <a href="{url}">{label}</a>')
            else:
                lines.append(f"• {label}")

    return lines


def _correlation_context_lines(alert: Any) -> list[str]:
    """Return Telegram HTML lines with saved correlation context."""
    lines = format_correlation_plain(alert)

    if not lines:
        return []

    result = ["", "<b>Correlation:</b>"]

    for line in lines[1:]:
        if line.endswith(":"):
            result.append(f"<b>{_html(line)}</b>")
        elif line.startswith("- "):
            result.append("• " + _html(line[2:]))
        else:
            result.append(_html(line))

    return result


def _raw(value: Any, default: str = "-") -> str:
    """Return a stripped string value."""

    if value is None:
        return default

    text = str(value).strip()

    return text or default


def _html(value: Any, default: str = "-") -> str:
    """Return a Telegram-safe HTML value."""

    return escape(_raw(value, default), quote=False)


def _attr(value: Any, default: str = "-") -> str:
    """Return a Telegram-safe HTML attribute value."""

    return escape(_raw(value, default), quote=True)


def _trim_html(value: Any, limit: int = MAX_ALERT_MESSAGE_LENGTH) -> str:
    """Return a length-limited escaped value."""

    text = _raw(value)

    if len(text) > limit:
        text = text[: limit - 1] + "…"

    return escape(text, quote=False)


def _person_name(user: Any) -> str:
    """Return a human-readable user name."""

    if not user:
        return "-"

    return _html(
        getattr(user, "display_name", None)
        or getattr(user, "username", None)
        or "-"
    )


def _team_name(alert: Any) -> str:
    """Return a human-readable team name."""

    team = getattr(alert, "team", None)

    if not team:
        return "-"

    return _html(
        getattr(team, "slug", None)
        or getattr(team, "name", None)
        or "-"
    )


def _service_name(alert: Any) -> str:
    """Return a human-readable affected service name."""
    service = getattr(alert, "service", None)

    if service:
        parts = [
            getattr(service, "name", None)
            or getattr(service, "slug", None)
            or f"Service #{getattr(service, 'id', '-')}",
        ]

        criticality = getattr(service, "criticality", None)
        status = getattr(service, "status", None)

        if criticality:
            parts.append(criticality)

        if status:
            parts.append(status)

        return _html(" / ".join(str(part) for part in parts if part))

    service_id = getattr(alert, "service_id", None)
    if service_id:
        return _html(f"Service #{service_id}")

    return "-"


def _action_user(alert: Any, event_type: str, actor: Any = None) -> Any:
    """Return the user who performed ACK or Resolve."""

    if actor:
        return actor

    transient_user = getattr(alert, "_action_user", None)
    if transient_user:
        return transient_user

    if event_type == "acknowledged" or getattr(alert, "status", None) == "acknowledged":
        return getattr(alert, "acknowledged_by", None)

    return None


def _format_dt(value: Any) -> str:
    """Format a datetime-like value for Telegram."""

    if not value:
        return "-"

    try:
        return value.strftime("%d.%m.%Y %H:%M:%S UTC")
    except Exception:
        return _html(value)


def _severity_icon(alert: Any) -> str:
    """Return an icon for alert severity."""

    severity = str(getattr(alert, "severity", "") or "").lower()

    if severity in {"critical", "crit", "high", "error"}:
        return "🚨"

    if severity in {"warning", "warn", "medium"}:
        return "⚠️"

    if severity in {"low", "info", "information", "informational"}:
        return "ℹ️"

    return "🔔"


def _title(alert: Any, event_type: str) -> str:
    """Return a title line for Telegram."""

    title = _html(format_alert_title_with_priority(alert), "Alert")
    status = str(getattr(alert, "status", "") or "").lower()

    if event_type == "resolved" or status == "resolved":
        return f"🟢 <b>RESOLVED · {title}</b>"

    if event_type == "acknowledged" or status == "acknowledged":
        return f"✅ <b>ACKNOWLEDGED · {title}</b>"

    if event_type == "reminder":
        return f"🔔 <b>REMINDER · {title}</b>"

    if event_type == "escalation":
        return f"⏫ <b>ESCALATION · {title}</b>"

    severity = _html(getattr(alert, "severity", None), "-").upper()

    if severity != "-":
        return f"{_severity_icon(alert)} <b>{severity} · {title}</b>"

    return f"{_severity_icon(alert)} <b>{title}</b>"


def _state_note(alert: Any, event_type: str, actor: Any = None) -> list[str]:
    """Return state-specific Telegram lines."""

    status = str(getattr(alert, "status", "") or "").lower()
    user = _action_user(alert, event_type, actor)

    if event_type == "resolved" or status == "resolved":
        return [
            "🟢 <b>Alert has been resolved.</b>",
            f"👤 <b>Resolved by:</b> {_person_name(user)}",
            f"🕒 <b>Resolved at:</b> {_html(_format_dt(getattr(alert, 'resolved_at', None)))}",
        ]

    if event_type == "acknowledged" or status == "acknowledged":
        return [
            "✅ <b>Alert has been acknowledged.</b>",
            f"👤 <b>Acknowledged by:</b> {_person_name(user)}",
            f"🕒 <b>Acknowledged at:</b> {_html(_format_dt(getattr(alert, 'acknowledged_at', None)))}",
        ]

    if event_type == "reminder":
        return [
            "🔔 <b>This alert is still firing.</b>",
            f"🔁 <b>Reminder count:</b> {_html(getattr(alert, 'reminder_count', 0))}",
        ]

    if event_type == "escalation":
        return [
            "⏫ <b>Alert has been escalated.</b>",
            f"📈 <b>Escalation level:</b> {_html(getattr(alert, 'escalation_level', 0))}",
        ]

    return []


def _ack_url(alert: Any) -> str:
    """Return the ACK API URL."""

    base_url = str(Config.PUBLIC_BASE_URL or "").rstrip("/")
    alert_id = getattr(alert, "id", None)

    if not base_url or not alert_id:
        return ""

    return f"{base_url}/api/alerts/{alert_id}/ack"


def format_telegram_alert_message(
    alert: Any,
    event_type: str = "notification",
    actor: Any = None,
) -> str:
    """Build a rich Telegram HTML message for an alert."""

    lines = [
        _title(alert, event_type),
        "",
    ]

    state_lines = _state_note(alert, event_type, actor)
    if state_lines:
        lines.extend(state_lines)
        lines.append("")

    lines.extend(
        [
            f"Team: {_team_name(alert)}",
            f"Service: {_service_name(alert)}",
            f"Status: {_html(getattr(alert, 'status', None))}",
            f"Severity: {_html(getattr(alert, 'severity', None))}",
            f"Priority: {_html(alert_priority_label(alert))}",
            f"Assignee: {_person_name(getattr(alert, 'assignee', None))}",
            f"Source: {_html(getattr(alert, 'source', None))}",
            f"Alert ID: #{_html(getattr(alert, 'id', None))}",
        ]
    )

    source_event_url = build_source_event_url(alert)

    if source_event_url:
        lines.append(
            f'🔗 <a href="{_attr(source_event_url)}">Open source event</a>'
        )

    lines.extend(_service_context_lines(alert))

    lines.extend(
        [
            "",
            "<b>Message:</b>",
            f"<blockquote>{_trim_html(getattr(alert, 'message', None))}</blockquote>",
        ]
    )

    if getattr(alert, "status", None) == "firing":
        ack_url = _ack_url(alert)
        if ack_url:
            lines.extend(
                [
                    "",
                    f"🔗 <a href=\"{_attr(ack_url)}\">ACK URL</a>",
                ]
            )

    lines.extend(_correlation_context_lines(alert))

    text = "\n".join(lines)

    if len(text) <= MAX_TELEGRAM_MESSAGE_LENGTH:
        return text

    return text[: MAX_TELEGRAM_MESSAGE_LENGTH - 1] + "…"
