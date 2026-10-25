import smtplib
from email.message import EmailMessage

from app import Config
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

        smtp_host = Config.SMTP_HOST
        smtp_port = int(Config.SMTP_PORT)

        if not smtp_host:
            raise RuntimeError("smtp host is missing: set [smtp] host in config")

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

        username = (Config.SMTP_USER or "").strip()
        password = Config.SMTP_PASSWORD or ""

        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as smtp:
            smtp.ehlo()

            if Config.SMTP_USE_TLS:
                smtp.starttls()
                smtp.ehlo()

            if username or password:
                if not username or not password:
                    raise RuntimeError(
                        "SMTP auth is partially configured: both [smtp] user and password "
                        "must be set, or both must be empty"
                    )

                if not smtp.has_extn("auth"):
                    raise RuntimeError(
                        "SMTP auth is configured, but the SMTP server does not support AUTH. "
                        "Clear [smtp] user/password for an unauthenticated relay, or use an "
                        "SMTP server that supports AUTH."
                    )

                smtp.login(username, password)

            smtp.send_message(message)

        return {
            "provider": self.name,
            "provider_payload": {"recipient_source": recipient_source},
        }
