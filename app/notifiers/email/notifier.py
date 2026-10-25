from email.message import EmailMessage

from app import Config
from app.modules.smtp import send_email_message
from app.notifiers.base import BaseNotifier
from app.notifiers.email.email_templates import render_email_html
from app.notifiers.email.recipients import resolve_email_channel_recipient
from app.services.alerts.priority import format_alert_title_with_priority


class EmailNotifier(BaseNotifier):
    """Send notifications through globally configured SMTP."""

    name = "email"

    def send(self, channel, alert, text, event_type="notification"):
        """Send an email to the recipient selected by this channel's mode."""
        config = channel.config or {}
        assignee = getattr(alert, "assignee", None)
        recipient, recipient_source = resolve_email_channel_recipient(
            config,
            getattr(assignee, "email", None) if assignee else None,
            is_test=event_type == "test",
        )

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
            "provider_payload": {"recipient_source": recipient_source},
        }
