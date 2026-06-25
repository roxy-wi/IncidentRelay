from __future__ import annotations
from html import escape
from string import Formatter

from app.modules.common import SafeFormatDict
from app.services.routing.service_context import (
    format_service_links_html,
    format_service_runbooks_html,
    service_display_name,
)
from app.services.alerts.priority import alert_priority_label

EMAIL_HTML_TEMPLATE_MAX_LENGTH = 20000

EMAIL_TEMPLATE_PLACEHOLDERS = (
    "alert_id",
    "event_type",
    "title",
    "message",
    "severity",
    "priority",
    "status",
    "team",
    "service",
    "assignee",
    "source",
    "alert_url",
    "service_links",
    "service_runbooks",
    "source_event_url",
    "source_event_link",
)

DEFAULT_EMAIL_HTML_TEMPLATE = """<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f6f8fb;font-family:Arial,sans-serif;color:#172033;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f6f8fb;padding:24px 0;">
      <tr>
        <td align="center">
          <table role="presentation" width="640" cellspacing="0" cellpadding="0" style="max-width:640px;width:100%;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e4e8f0;">
            <tr>
              <td style="padding:22px 26px;background:#111827;color:#ffffff;">
                <div style="font-size:13px;letter-spacing:.08em;text-transform:uppercase;opacity:.8;">IncidentRelay</div>
                <h1 style="margin:8px 0 0;font-size:22px;line-height:1.3;">{event_type}: {title}</h1>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 26px;">
                <p style="margin:0 0 18px;font-size:15px;line-height:1.6;white-space:pre-line;">{message}</p>
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;font-size:14px;">
                  <tr><td style="padding:8px 0;color:#64748b;width:140px;">Alert ID</td><td style="padding:8px 0;font-weight:600;">{alert_id}</td></tr>
                  <tr><td style="padding:8px 0;color:#64748b;">Team</td><td style="padding:8px 0;font-weight:600;">{team}</td></tr>
                  <tr><td style="padding:8px 0;color:#64748b;">Status</td><td style="padding:8px 0;font-weight:600;">{status}</td></tr>
                  <tr><td style="padding:8px 0;color:#64748b;">Severity</td><td style="padding:8px 0;font-weight:600;">{severity}</td></tr>
                  <tr><td style="padding:8px 0;color:#64748b;">Priority</td><td style="padding:8px 0;font-weight:600;">{priority}</td></tr>
                  <tr><td style="padding:8px 0;color:#64748b;">Assignee</td><td style="padding:8px 0;font-weight:600;">{assignee}</td></tr>
                  <tr><td style="padding:8px 0;color:#64748b;">Source</td><td style="padding:8px 0;font-weight:600;">{source}</td></tr>
                </table>
                <p style="margin:22px 0 0;">
                  <a href="{alert_url}" style="display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;padding:11px 16px;border-radius:9px;font-weight:600;">Open alert</a>
                  {source_event_link}
                </p>
              </td>
            </tr>
            <tr>
                <td>Service</td>
                <td>{service}</td>
            </tr>
            <tr>
                <td>Links</td>
                <td>{service_links}</td>
            </tr>
            <tr>
                <td>Runbooks</td>
                <td>{service_runbooks}</td>
            </tr>
            <tr>
              <td style="padding:16px 26px;background:#f8fafc;color:#64748b;font-size:12px;">
                Sent by IncidentRelay. You can customize this email template in the channel settings.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def render_email_html(alert, text, event_type="notification", template=None):
    """Render alert email as HTML."""
    html_template = (template or "").strip() or DEFAULT_EMAIL_HTML_TEMPLATE
    values = build_email_template_context(alert, text, event_type)

    return html_template.format_map(SafeFormatDict(values))


def _stringify(value, default="-"):
    if value is None:
        return default
    value = str(value)
    if not value:
        return default
    return value


def _escape_value(value, default="-"):
    return escape(_stringify(value, default), quote=True)


def build_email_template_context(alert, text, event_type="notification"):
    """Build escaped placeholder values for email HTML templates."""
    assignee = getattr(alert, "assignee", None)
    assignee_name = None
    if assignee:
        assignee_name = getattr(assignee, "display_name", None) or getattr(
            assignee,
            "username",
            None,
        )

    team = getattr(alert, "team", None)
    team_slug = getattr(team, "slug", None) if team else None

    # Imported lazily to avoid import cycles when tests import only this module.
    from app.services.links import build_alert_web_url, build_source_event_url
    source_event_url = build_source_event_url(alert)

    alert_url = build_alert_web_url(alert) or "#"

    return SafeFormatDict(
        alert_id=_escape_value(getattr(alert, "id", None), "test"),
        event_type=_escape_value(str(event_type or "notification").upper()),
        title=_escape_value(getattr(alert, "title", None), "Alert"),
        message=_escape_value(getattr(alert, "message", None) or text or ""),
        severity=_escape_value(getattr(alert, "severity", None)),
        priority=_escape_value(alert_priority_label(alert)),
        status=_escape_value(getattr(alert, "status", None)),
        team=_escape_value(team_slug),
        assignee=_escape_value(assignee_name),
        source=_escape_value(getattr(alert, "source", None)),
        alert_url=_escape_value(alert_url, "#"),
        source_event_url=_escape_value(source_event_url, ""),
        source_event_link=_build_source_event_link(source_event_url),
        service=_escape_value(service_display_name(alert)),
        service_links=format_service_links_html(alert),
        service_runbooks=format_service_runbooks_html(alert),
    )


def _build_source_event_link(source_event_url):
    """Build an optional source event button."""
    if not source_event_url:
        return ""

    escaped_url = escape(source_event_url, quote=True)

    return (
        '&nbsp;'
        f'<a href="{escaped_url}" '
        'style="display:inline-block;background:#ffffff;color:#2563eb;'
        'text-decoration:none;padding:10px 15px;border-radius:9px;'
        'font-weight:600;border:1px solid #2563eb;">'
        'Open source event</a>'
    )


def normalize_email_html_template(template):
    """Return a safe template value or None when default template should be used."""
    if template is None:
        return None

    template = str(template).strip()
    if not template:
        return None

    if len(template) > EMAIL_HTML_TEMPLATE_MAX_LENGTH:
        raise ValueError(
            f"email html_template must be at most {EMAIL_HTML_TEMPLATE_MAX_LENGTH} characters"
        )

    validate_email_html_template(template)
    return template


def validate_email_html_template(template):
    """Validate Python format braces used by the email HTML template."""
    try:
        # Formatter.parse validates brace balance without requiring known field names.
        list(Formatter().parse(str(template)))
    except ValueError as exc:
        raise ValueError(f"email html_template has invalid format placeholders: {exc}") from exc

    return True
