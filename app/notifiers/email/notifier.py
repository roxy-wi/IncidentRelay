from email.message import EmailMessage

from app import Config
from app.modules.smtp import send_email_message
from app.notifiers.base import BaseNotifier
from app.notifiers.email.email_templates import render_email_html
from app.services.alerts.priority import format_alert_title_with_priority


class EmailNotifier(BaseNotifier):
    """Send notifications through globally configured SMTP."""

    name = "email"

    def send(self, channel, alert, text, event_type="notification"):
        """Send an email notification to the assigned user's profile email."""
        config = channel.config or {}
        recipient = self._recipient_email(alert)

        message = EmailMessage()
        message["Subject"] = f"[On-call] {format_alert_title_with_priority(alert)}"
        message["From"] = Config.SMTP_FROM
        message["To"] = recipient
        message.set_content(text)

        html_body = render_email_html(
            alert,
            text,
            event_type,
            template=config.get("html_template"),
        )
        message.add_alternative(html_body, subtype="html")

        send_email_message(message)

        return {
            "provider": self.name,
            "provider_payload": {"recipient_source": "assignee.email"},
        }

    def _recipient_email(self, alert):
        assignee = getattr(alert, "assignee", None)
        email = getattr(assignee, "email", None) if assignee else None
        email = str(email or "").strip()
        if not email:
            raise RuntimeError("email test recipient is missing: set email in your profile")
        return email
