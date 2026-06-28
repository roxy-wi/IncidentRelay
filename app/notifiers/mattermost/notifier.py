from urllib.parse import urljoin

import requests

from app import Config
from app.notifiers.plugins import IncomingWebhookNotifier, alert_service_label
from app.services.links import build_alert_web_url, build_source_event_url
from app.services.routing.service_context import (
    format_service_links_markdown,
    format_service_runbooks_markdown,
)
from app.services.alerts.priority import (
    alert_priority_label,
    format_alert_title_with_priority,
)


class MattermostNotifier(IncomingWebhookNotifier):
    """Send notifications through Mattermost."""

    name = "mattermost"
    supports_update = True

    def send(self, channel, alert, text, event_type="notification"):
        """Send a Mattermost notification."""
        config = channel.config or {}
        if self._should_use_bot_api(config):
            return self._send_bot_post(channel, alert, text, event_type)
        return super().send(channel, alert, text, event_type=event_type)

    def update(self, channel, alert, text, delivery, event_type="resolved"):
        """Update a previously sent Mattermost post."""
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
            "provider_payload": {
                "requested_channel_id": channel_id,
                "response_channel_id": result.get("channel_id"),
                "channel_mismatch": bool(
                    channel_id and result.get("channel_id") and channel_id != result.get("channel_id")),
            },
        }

    def _should_include_actions_after_update(self, alert, event_type):
        """Return True when an updated Mattermost post should still have buttons."""
        if event_type == "resolved" or alert.status == "resolved":
            return False
        if event_type == "acknowledged" or alert.status == "acknowledged":
            return True
        return self._can_show_actions(alert)

    def _send_bot_post(self, channel, alert, text, event_type):
        """Send a post through the Mattermost Bot API."""
        config = channel.config or {}

        if not self._bot_api_ready(config):
            raise RuntimeError("Mattermost Bot API requires api_url, bot_token and channel_id")

        requested_channel_id = config.get("channel_id")
        payload = self._build_post_payload(channel, alert, text, event_type, include_actions=True)
        result = self._request(config, "POST", "/api/v4/posts", payload)
        external_channel_id = result.get("channel_id") or requested_channel_id

        return {
            "provider": self.name,
            "external_message_id": result.get("id"),
            "external_channel_id": external_channel_id,
            "provider_payload": {
                "requested_channel_id": requested_channel_id,
                "response_channel_id": result.get("channel_id"),
                "channel_mismatch": bool(
                    requested_channel_id and external_channel_id and requested_channel_id != external_channel_id),
            },
        }

    def _should_use_bot_api(self, config):
        """Decide whether this channel should use Bot API mode."""
        return config.get("mode") == "bot_api" or self._bot_api_ready(config)

    def _bot_api_ready(self, config):
        """Check that Mattermost Bot API config is complete."""
        return bool(config.get("api_url") and config.get("bot_token") and config.get("channel_id"))

    def _request(self, config, method, path, payload):
        """Send a Mattermost REST API request."""
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
        """Build a Mattermost post payload."""
        alert_url = build_alert_web_url(alert)
        attachment = {
            "fallback": alert.title,
            "color": self._color_for_alert(alert, event_type),
            "title": self._title_for_alert(alert, event_type),
            "text": self._text_for_alert(alert, text, event_type),
            "fields": self._fields(alert),
        }

        if alert_url:
            attachment["title_link"] = alert_url

        if include_actions and self._can_show_actions(alert):
            attachment["actions"] = self._actions(channel, alert)

        return {
            "channel_id": (channel.config or {}).get("channel_id"),
            "message": "",
            "props": {"attachments": [attachment]},
        }

    def _can_show_actions(self, alert):
        """Return True when action buttons should be visible."""
        return bool(alert.id and alert.status in {"firing", "acknowledged"})

    def _title_for_alert(self, alert, event_type):
        """Return the attachment title."""
        title = format_alert_title_with_priority(alert)
        if alert.status == "resolved" or event_type == "resolved":
            return f"RESOLVED: {title}"
        if alert.status == "acknowledged" or event_type == "acknowledged":
            return f"ACKNOWLEDGED: {title}"
        if event_type == "reminder":
            return f"REMINDER: {title}"
        if event_type == "escalation":
            return f"ESCALATION: {title}"

        return title

    def _text_for_alert(self, alert, text, event_type):
        """Return the main attachment text."""
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
        """Return Mattermost attachment fields."""
        assignee = (
            alert.assignee.display_name or alert.assignee.username
            if alert.assignee
            else "-"
        )
        team = (
            alert.team.name
            or alert.team.slug
            if alert.team
            else "-"
        )
        alert_url = build_alert_web_url(alert)
        source_event_url = build_source_event_url(alert)
        fields = [
            {"short": True, "title": "Team", "value": team},
            {"short": True, "title": "Service", "value": alert_service_label(alert)},
            {"short": True, "title": "Status", "value": alert.status},
            {"short": True, "title": "Severity", "value": alert.severity or "-"},
            {"short": True, "title": "Priority", "value": alert_priority_label(alert)},
            {"short": True, "title": "Assignee", "value": assignee},
            {"short": True, "title": "Source", "value": alert.source},
            {"short": True, "title": "Alert ID", "value": str(alert.id)},
        ]
        service_links = format_service_links_markdown(alert)
        if service_links:
            fields.append(
                {
                    "short": False,
                    "title": "Links",
                    "value": service_links,
                }
            )

        service_runbooks = format_service_runbooks_markdown(alert)
        if service_runbooks:
            fields.append(
                {
                    "short": False,
                    "title": "Runbooks",
                    "value": service_runbooks,
                }
            )
        if alert_url:
            fields.append({
                "short": False,
                "title": "Open",
                "value": f"[Open alert]({alert_url})",
            })
        if source_event_url:
            fields.append({
                "short": False,
                "title": "Source event",
                "value": f"[Open source event]({source_event_url})",
            })
        return fields

    def _actions(self, channel, alert):
        """Return Mattermost action buttons."""
        action_url = f"{Config.PUBLIC_BASE_URL.rstrip('/')}/api/integrations/mattermost/actions"
        secret = self._callback_secret(channel)

        if alert.status == "acknowledged":
            return [
                self._button("resolve", "Resolve", "success", action_url, alert.id, channel.id, secret),
            ]

        return [
            self._button("acknowledge", "Acknowledge", "primary", action_url, alert.id, channel.id, secret),
            self._button("resolve", "Resolve", "success", action_url, alert.id, channel.id, secret),
        ]

    def _button(self, action, name, style, action_url, alert_id, channel_id, secret):
        """Build one Mattermost button definition."""
        action_prefix = "ack" if action == "acknowledge" else "resolve"
        return {
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
        """Return the callback secret for Mattermost buttons."""
        config = channel.config or {}
        return config.get("callback_secret") or Config.MATTERMOST_ACTION_SECRET

    def _color_for_alert(self, alert, event_type):
        """Return the attachment border color."""
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
