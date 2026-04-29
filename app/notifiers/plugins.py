import smtplib
from email.message import EmailMessage
from urllib.parse import urljoin

import requests

from app.settings import Config
from app.notifiers.base import BaseNotifier


class TelegramNotifier(BaseNotifier):
    """
    Send notifications through Telegram Bot API.
    """

    name = "telegram"

    def send(self, channel, alert, text, event_type="notification"):
        """
        Send a Telegram message.
        """

        config = channel.config or {}
        bot_token = config.get("bot_token")
        chat_id = None

        if alert.assignee and alert.assignee.telegram_chat_id:
            chat_id = alert.assignee.telegram_chat_id

        chat_id = chat_id or config.get("chat_id")

        if not bot_token or not chat_id:
            raise RuntimeError("telegram bot_token or chat_id is missing")

        response = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        response.raise_for_status()
        return {"provider": self.name}


class IncomingWebhookNotifier(BaseNotifier):
    """
    Send notifications through a generic incoming webhook.
    """

    name = "webhook"

    def send(self, channel, alert, text, event_type="notification"):
        """
        Send a JSON webhook notification.
        """

        config = channel.config or {}
        webhook_url = config.get("webhook_url")

        if not webhook_url:
            raise RuntimeError("webhook_url is missing")

        response = requests.post(
            webhook_url,
            json={
                "text": text,
                "alert_id": alert.id,
                "team": alert.team.slug if alert.team else None,
                "status": alert.status,
                "source": alert.source,
                "title": alert.title,
                "message": alert.message,
                "severity": alert.severity,
                "assignee": alert.assignee.username if alert.assignee else None,
            },
            timeout=10,
        )
        response.raise_for_status()
        return {"provider": self.name}


class SlackNotifier(IncomingWebhookNotifier):
    """
    Send notifications through Slack Incoming Webhook.
    """

    name = "slack"


class MattermostNotifier(IncomingWebhookNotifier):
    """
    Send notifications through Mattermost.

    Bot API mode supports buttons and post updates. Incoming webhook mode is
    kept as a simple fallback for plain messages.
    """

    name = "mattermost"
    supports_update = True

    def send(self, channel, alert, text, event_type="notification"):
        """
        Send a Mattermost notification.
        """

        config = channel.config or {}

        if self._should_use_bot_api(config):
            return self._send_bot_post(channel, alert, text, event_type)

        return super().send(channel, alert, text, event_type=event_type)

    def update(self, channel, alert, text, delivery, event_type="resolved"):
        """
        Update a previously sent Mattermost post.
        """

        config = channel.config or {}

        if not self._bot_api_ready(config):
            raise RuntimeError("Mattermost Bot API config is required to update posts")

        post_id = delivery.external_message_id
        channel_id = delivery.external_channel_id or config.get("channel_id")

        if not post_id:
            raise RuntimeError("Mattermost post_id is missing for update")

        payload = self._build_post_payload(
            channel,
            alert,
            text,
            event_type,
            include_actions=self._should_include_actions_after_update(alert, event_type),
        )
        payload["id"] = post_id
        payload["channel_id"] = channel_id

        result = self._request(config, "PUT", f"/api/v4/posts/{post_id}", payload)

        return {
            "provider": self.name,
            "external_message_id": result.get("id") or post_id,
            "external_channel_id": result.get("channel_id") or channel_id,
        }

    def _should_include_actions_after_update(self, alert, event_type):
        """
        Return True when an updated Mattermost post should still have buttons.

        After acknowledge the alert is still not finished, so Resolve must stay
        available. After resolve all action buttons must be removed.
        """

        if event_type == "resolved" or alert.status == "resolved":
            return False

        if event_type == "acknowledged" or alert.status == "acknowledged":
            return True

        return self._can_show_actions(alert)

    def _send_bot_post(self, channel, alert, text, event_type):
        """
        Send a post through the Mattermost Bot API.
        """

        config = channel.config or {}

        if not self._bot_api_ready(config):
            raise RuntimeError("Mattermost Bot API requires api_url, bot_token and channel_id")

        payload = self._build_post_payload(channel, alert, text, event_type, include_actions=True)
        result = self._request(config, "POST", "/api/v4/posts", payload)

        return {
            "provider": self.name,
            "external_message_id": result.get("id"),
            "external_channel_id": result.get("channel_id") or config.get("channel_id"),
        }

    def _should_use_bot_api(self, config):
        """
        Decide whether this channel should use Bot API mode.
        """

        return config.get("mode") == "bot_api" or self._bot_api_ready(config)

    def _bot_api_ready(self, config):
        """
        Check that Mattermost Bot API config is complete.
        """

        return bool(config.get("api_url") and config.get("bot_token") and config.get("channel_id"))

    def _request(self, config, method, path, payload):
        """
        Send a Mattermost REST API request.
        """

        api_url = config.get("api_url", "").rstrip("/")
        url = urljoin(api_url + "/", path.lstrip("/"))

        response = requests.request(
            method,
            url,
            json=payload,
            headers={"Authorization": f"Bearer {config['bot_token']}"},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

    def _build_post_payload(self, channel, alert, text, event_type, include_actions=True):
        """
        Build a Mattermost post payload.
        """

        attachment = {
            "fallback": alert.title,
            "color": self._color_for_alert(alert, event_type),
            "title": self._title_for_alert(alert, event_type),
            "text": self._text_for_alert(alert, text, event_type),
            "fields": self._fields(alert),
        }

        if include_actions and self._can_show_actions(alert):
            attachment["actions"] = self._actions(channel, alert)

        return {
            "channel_id": (channel.config or {}).get("channel_id"),
            "message": "",
            "props": {"attachments": [attachment]},
        }

    def _can_show_actions(self, alert):
        """
        Return True when action buttons should be visible.
        """

        return bool(alert.id and alert.status in {"firing", "acknowledged"})

    def _title_for_alert(self, alert, event_type):
        """
        Return the attachment title.
        """

        if alert.status == "resolved" or event_type == "resolved":
            return f"RESOLVED: {alert.title}"

        if alert.status == "acknowledged" or event_type == "acknowledged":
            return f"ACKNOWLEDGED: {alert.title}"

        if event_type == "reminder":
            return f"REMINDER: {alert.title}"

        if event_type == "escalation":
            return f"ESCALATION: {alert.title}"

        return alert.title

    def _text_for_alert(self, alert, text, event_type):
        """
        Return the main attachment text.
        """

        if alert.status == "resolved" or event_type == "resolved":
            return f"The alert has been resolved.\n\n{alert.message or ''}"

        if alert.status == "acknowledged" or event_type == "acknowledged":
            user = alert.acknowledged_by.username if alert.acknowledged_by else "unknown"
            return f"The alert was acknowledged by {user}.\n\n{alert.message or ''}"

        if event_type == "reminder":
            return f"This alert is still not acknowledged.\n\n{alert.message or ''}"

        if event_type == "escalation":
            return f"The alert was escalated.\n\n{alert.message or ''}"

        return alert.message or text

    def _fields(self, alert):
        """
        Return Mattermost attachment fields.
        """

        assignee = alert.assignee.display_name or alert.assignee.username if alert.assignee else "-"
        team = alert.team.slug if alert.team else "-"

        return [
            {"short": True, "title": "Team", "value": team},
            {"short": True, "title": "Status", "value": alert.status},
            {"short": True, "title": "Severity", "value": alert.severity or "-"},
            {"short": True, "title": "Assignee", "value": assignee},
            {"short": True, "title": "Source", "value": alert.source},
            {"short": True, "title": "Alert ID", "value": str(alert.id)},
        ]

    def _actions(self, channel, alert):
        """
        Return Mattermost action buttons.
        """

        action_url = f"{Config.PUBLIC_BASE_URL.rstrip('/')}/api/integrations/mattermost/actions"
        secret = self._callback_secret(channel)

        if alert.status == "acknowledged":
            return [
                self._button("resolve", "Resolve", "danger", action_url, alert.id, channel.id, secret),
            ]

        return [
            self._button("acknowledge", "Acknowledge", "primary", action_url, alert.id, channel.id, secret),
            self._button("resolve", "Resolve", "danger", action_url, alert.id, channel.id, secret),
        ]

    def _button(self, action, name, style, action_url, alert_id, channel_id, secret):
        """
        Build one Mattermost button definition.
        """

        action_prefix = "ack" if action == "acknowledge" else "resolve"

        return {
            # Mattermost uses this id in /api/v4/posts/{post_id}/actions/{action_id}.
            # Keep it strictly alphanumeric. Hyphens and underscores can make
            # Mattermost return 404 before it calls integration.url.
            "id": f"{action_prefix}{alert_id}",
            "name": name,
            "type": "button",
            "style": style,
            "integration": {
                "url": action_url,
                "context": {
                    "alert_id": alert_id,
                    "channel_id": channel_id,
                    "action": action,
                    "secret": secret,
                },
            },
        }

    def _callback_secret(self, channel):
        """
        Return the callback secret for Mattermost buttons.
        """

        config = channel.config or {}
        return config.get("callback_secret") or Config.MATTERMOST_ACTION_SECRET

    def _color_for_alert(self, alert, event_type):
        """
        Return the attachment border color.
        """

        if event_type == "resolved" or alert.status == "resolved":
            return "#2e7d32"

        if event_type == "acknowledged" or alert.status == "acknowledged":
            return "#f0ad4e"

        severity = (alert.severity or "").lower()

        if severity in {"critical", "crit", "high", "error"}:
            return "#d9534f"

        if severity in {"warning", "warn"}:
            return "#f0ad4e"

        if severity in {"info", "information", "informational"}:
            return "#4a90e2"

        return "#4a90e2"


class TeamsNotifier(IncomingWebhookNotifier):
    """
    Send notifications through Microsoft Teams Incoming Webhook.
    """

    name = "teams"


class DiscordNotifier(IncomingWebhookNotifier):
    """
    Send notifications through Discord Webhook.
    """

    name = "discord"

    def send(self, channel, alert, text, event_type="notification"):
        """
        Send a Discord webhook notification.
        """

        config = channel.config or {}
        webhook_url = config.get("webhook_url")

        if not webhook_url:
            raise RuntimeError("webhook_url is missing")

        response = requests.post(webhook_url, json={"content": text}, timeout=10)
        response.raise_for_status()
        return {"provider": self.name}


class EmailNotifier(BaseNotifier):
    """
    Send notifications through SMTP.
    """

    name = "email"

    def send(self, channel, alert, text, event_type="notification"):
        """
        Send an email notification.
        """

        config = channel.config or {}
        recipients = config.get("recipients") or []

        if alert.assignee and alert.assignee.email:
            recipients = [alert.assignee.email]

        if not recipients:
            raise RuntimeError("email recipients are missing")

        smtp_host = config.get("smtp_host") or Config.SMTP_HOST
        smtp_port = int(config.get("smtp_port") or Config.SMTP_PORT)

        if not smtp_host:
            raise RuntimeError("smtp_host is missing")

        message = EmailMessage()
        message["Subject"] = f"[On-call] {alert.title}"
        message["From"] = config.get("from") or Config.SMTP_FROM
        message["To"] = ", ".join(recipients)
        message.set_content(text)

        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as smtp:
            if config.get("smtp_use_tls", Config.SMTP_USE_TLS):
                smtp.starttls()

            username = config.get("smtp_user") or Config.SMTP_USER
            password = config.get("smtp_password") or Config.SMTP_PASSWORD

            if username:
                smtp.login(username, password)

            smtp.send_message(message)

        return {"provider": self.name}
