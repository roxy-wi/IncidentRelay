import json
import re

import requests

from app.notifiers.plugins import IncomingWebhookNotifier, alert_service_label
from app.notifiers.types import (
    SLACK_MENTION_ASSIGNEE_KEY,
    SLACK_MENTION_ONCALL_KEY,
)
from app.services.alerts.priority import (
    alert_priority_label,
    format_alert_title_with_priority,
)
from app.services.links import build_alert_web_url, build_source_event_url
from app.services.oncall import get_current_oncall_user
from app.services.outbound_http import safe_request
from app.services.routing.service_context import (
    get_alert_service_links,
    get_alert_service_runbooks,
    link_display_label,
    runbook_display_label,
)
from app.services.alerts.correlation import format_correlation_markdown
from app.services.alerts.shelving import get_active_shelve, is_alert_group_shelved

# Slack user IDs start with U (regular user) or W (Enterprise Grid user)
# followed by uppercase alphanumerics. slack_user_id is free text supplied
# through a profile form, the API or an SSO claim, so it must be validated
# before it is embedded in Slack mention markup.
SLACK_USER_ID_PATTERN = re.compile(r"^[UW][A-Z0-9]{1,32}$")


class SlackNotifier(IncomingWebhookNotifier):
    """Send notifications through Slack."""

    name = "slack"
    supports_update = True

    api_base_url = "https://slack.com/api"

    def send(self, channel, alert, text, event_type="notification"):
        """Send a Slack notification."""
        config = channel.config or {}

        if self._should_use_bot_api(config):
            return self._send_bot_message(
                channel,
                alert,
                text,
                event_type,
            )

        return self._send_webhook_message(
            channel,
            alert,
            text,
            event_type,
        )

    def update(
        self,
        channel,
        alert,
        text,
        delivery,
        event_type="resolved",
    ):
        """Update a previously sent Slack Bot API message."""
        config = channel.config or {}

        if not self._bot_api_ready(config):
            raise RuntimeError(
                "Slack Bot API config is required to update messages"
            )

        message_ts = delivery.external_message_id
        channel_id = (
            delivery.external_channel_id
            or config.get("channel_id")
        )

        if not message_ts:
            raise RuntimeError("Slack message timestamp is missing")

        if not channel_id:
            raise RuntimeError("Slack channel_id is missing")

        payload = self._build_message_payload(
            channel,
            alert,
            text,
            event_type,
            include_actions=(
                self._actions_ready(config)
                and self._should_include_actions_after_update(
                    alert,
                    event_type,
                )
            ),
        )
        payload.update(
            {
                "channel": channel_id,
                "ts": message_ts,
            }
        )

        result = self._request(
            config,
            "chat.update",
            payload,
        )

        return {
            "provider": self.name,
            "provider_status": "updated",
            "external_message_id": (
                    result.get("ts")
                    or message_ts
            ),
            "external_channel_id": (
                    result.get("channel")
                    or channel_id
            ),
        }

    def can_update(self, channel, delivery=None):
        """Return whether this Slack delivery can be updated."""
        config = channel.config or {}

        if config.get("mode") != "bot_api":
            return False

        if not self._bot_api_ready(config):
            return False

        if delivery is None:
            return True

        return bool(
            getattr(delivery, "external_message_id", None)
            and (
                    getattr(delivery, "external_channel_id", None)
                    or config.get("channel_id")
            )
        )

    def _send_webhook_message(
        self,
        channel,
        alert,
        text,
        event_type,
    ):
        """Send a message through a Slack incoming webhook."""
        config = channel.config or {}
        webhook_url = config.get("webhook_url")

        if not webhook_url:
            raise RuntimeError("webhook_url is missing")

        response = safe_request(
            "POST",
            webhook_url,
            json=self._build_message_payload(
                channel,
                alert,
                text,
                event_type,
                include_actions=False,
            ),
            timeout=10,
        )
        response.raise_for_status()

        return {
            "provider": self.name,
        }

    def _send_bot_message(
        self,
        channel,
        alert,
        text,
        event_type,
    ):
        """Send a message through Slack Bot API."""
        config = channel.config or {}

        if not self._bot_api_ready(config):
            raise RuntimeError(
                "Slack Bot API requires bot_token and channel_id"
            )

        payload = self._build_message_payload(
            channel,
            alert,
            text,
            event_type,
            include_actions=self._actions_ready(config),
        )
        payload["channel"] = config["channel_id"]

        result = self._request(
            config,
            "chat.postMessage",
            payload,
        )

        return {
            "provider": self.name,
            "provider_status": "sent",
            "external_message_id": result.get("ts"),
            "external_channel_id": (
                    result.get("channel")
                    or config.get("channel_id")
            ),
        }

    def send_direct_message(self, channel, user, text, *, blocks=None):
        """Send a Slack message to one user.

        Prefers a direct message via ``conversations.open`` + ``chat.postMessage``,
        which needs Bot API mode and the ``im:write`` scope. When only an
        incoming webhook is configured a DM is impossible, so the message is
        posted to the configured channel with the user mentioned instead.
        """
        config = channel.config or {}
        slack_user_id = self._slack_user_id(user)

        if not slack_user_id:
            raise RuntimeError(
                "Slack user id is missing or invalid in user profile"
            )

        if not self._bot_api_ready(config):
            return self._send_channel_fallback_message(
                channel,
                slack_user_id,
                text,
                blocks=blocks,
            )

        conversation = self._request(
            config,
            "conversations.open",
            {"users": slack_user_id},
        )

        dm_channel_id = str(
            (conversation.get("channel") or {}).get("id") or ""
        ).strip()

        if not dm_channel_id:
            raise RuntimeError(
                "Slack direct channel id was not returned"
            )

        payload = {
            "channel": dm_channel_id,
            "text": self._truncate(text, 4000),
        }

        if blocks:
            payload["blocks"] = blocks

        result = self._request(config, "chat.postMessage", payload)

        return {
            "provider": self.name,
            "provider_status": "sent",
            "delivery_mode": "direct_message",
            "external_message_id": result.get("ts"),
            "external_channel_id": (
                result.get("channel") or dm_channel_id
            ),
        }

    def _send_channel_fallback_message(
        self,
        channel,
        slack_user_id,
        text,
        *,
        blocks=None,
    ):
        """Post to the configured webhook channel, mentioning the user."""
        config = channel.config or {}
        webhook_url = config.get("webhook_url")

        if not webhook_url:
            raise RuntimeError(
                "Slack direct messages require Bot API mode "
                "(bot_token and channel_id), or a webhook_url fallback"
            )

        mention_text = f"<@{slack_user_id}> {text}"

        payload = {"text": self._truncate(mention_text, 4000)}

        if blocks:
            payload["blocks"] = blocks

        response = safe_request(
            "POST",
            webhook_url,
            json=payload,
            timeout=10,
        )
        response.raise_for_status()

        return {
            "provider": self.name,
            "provider_status": "sent",
            "delivery_mode": "channel_mention",
        }

    def _request(self, config, method, payload):
        """Call a Slack Web API method."""
        try:
            response = requests.post(
                f"{self.api_base_url}/{method}",
                json=payload,
                headers={
                    "Authorization": (
                        f"Bearer {config['bot_token']}"
                    ),
                    "Content-Type": (
                        "application/json; charset=utf-8"
                    ),
                },
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Slack API request failed: {exc}"
            ) from exc

        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeError(
                "Slack API request failed: "
                "invalid JSON response"
            ) from exc

        if not result.get("ok"):
            error = result.get("error") or "unknown_error"

            raise RuntimeError(
                f"Slack API error: {error}"
            )

        return result

    def _should_use_bot_api(self, config):
        """Return True when Slack Bot API mode is selected."""
        mode = config.get("mode")

        if mode:
            return mode == "bot_api"

        return self._bot_api_ready(config)

    @staticmethod
    def _bot_api_ready(config):
        """Check that Slack Bot API message delivery is configured."""
        return bool(
            config.get("bot_token")
            and config.get("channel_id")
        )

    @staticmethod
    def _actions_ready(config):
        """Check that one inbound interactive action transport is ready."""
        if config.get("mode") != "bot_api":
            return False

        connection_mode = str(
            config.get("connection_mode") or "http"
        ).strip()

        if connection_mode == "socket_mode":
            return bool(config.get("app_token"))

        return bool(config.get("signing_secret"))

    @staticmethod
    def _mentions_enabled(config, key):
        """Return whether a mention flag is explicitly enabled.

        Only a real boolean True enables mentions, so a channel with no
        mention config renders exactly as it did before mentions existed.
        """
        return (config or {}).get(key) is True

    @staticmethod
    def _slack_user_id(user):
        """Return a validated Slack user ID for a user, or None."""
        if not user:
            return None

        slack_user_id = str(
            getattr(user, "slack_user_id", "") or ""
        ).strip()

        if not slack_user_id:
            return None

        if not SLACK_USER_ID_PATTERN.match(slack_user_id):
            return None

        return slack_user_id

    @staticmethod
    def _user_display_name(user):
        """Return a plain display name for a user."""
        if not user:
            return "-"

        return (
            getattr(user, "display_name", None)
            or getattr(user, "username", None)
            or "-"
        )

    def _user_reference(self, user, *, mention, mentioned_user_ids):
        """Render a user as a Slack mention or as escaped plain text.

        A user is mentioned at most once per message: the first field that
        emits a real mention claims it, and later fields fall back to the
        display name so nobody is pinged twice for the same alert.
        """
        display_name = self._escape_text(self._user_display_name(user))

        if not mention:
            return display_name

        slack_user_id = self._slack_user_id(user)

        if not slack_user_id:
            return display_name

        user_id = getattr(user, "id", None)

        if user_id is not None and user_id in mentioned_user_ids:
            return display_name

        if user_id is not None:
            mentioned_user_ids.add(user_id)

        return f"<@{slack_user_id}>"

    @staticmethod
    def _current_oncall_user(alert):
        """Resolve the effective on-call user for an alert at send time.

        Uses the rotation stored on the alert group, so rotation overrides
        and layer restrictions are honoured by the on-call service.
        """
        rotation = getattr(alert, "rotation", None)

        if not rotation:
            return None

        try:
            return get_current_oncall_user(rotation)
        except Exception:
            return None

    def _build_message_payload(
            self,
            channel,
            alert,
            text,
            event_type,
            *,
            include_actions=True,
    ):
        """Build a Slack Block Kit message."""
        title = self._title_for_alert(alert, event_type)
        description = self._description_for_alert(
            alert,
            text,
            event_type,
        )

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": self._truncate(title, 150),
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": self._truncate(
                        self._escape_text(description),
                        3000,
                    ),
                },
            },
            {
                "type": "section",
                "fields": self._field_blocks(alert, channel=channel),
            },
        ]

        service_links = self._service_links(alert)
        if service_links:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": self._truncate(
                            f"*Links*\n{service_links}",
                            3000,
                        ),
                    },
                }
            )

        runbooks = self._service_runbooks(alert)
        if runbooks:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": self._truncate(
                            f"*Runbooks*\n{runbooks}",
                            3000,
                        ),
                    },
                }
            )

        correlation = self._correlation_context(alert)
        if correlation:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": self._truncate(
                            f"*Correlation*\n{correlation}",
                            3000,
                        ),
                    },
                }
            )

        alert_url = build_alert_web_url(alert)
        source_event_url = build_source_event_url(alert)
        link_elements = []

        if alert_url:
            link_elements.append({
                "type": "mrkdwn",
                "text": f"<{alert_url}|Open alert in IncidentRelay>",
            })

        if source_event_url:
            link_elements.append({
                "type": "mrkdwn",
                "text": f"<{source_event_url}|Open source event>",
            })

        if link_elements:
            blocks.append({
                "type": "context",
                "elements": link_elements,
            })

        if include_actions and self._can_show_actions(alert):
            blocks.append(
                self._actions(channel, alert)
            )

        return {
            "text": self._truncate(
                f"{title}: {description}",
                4000,
            ),
            "blocks": blocks,
        }

    def _field_blocks(self, alert, channel=None):
        """Build the common Slack message fields."""
        config = getattr(channel, "config", None) or {}
        team = getattr(alert, "team", None)
        assignee = getattr(alert, "assignee", None)

        team_name = (
            getattr(team, "name", None)
            or getattr(team, "slug", None)
            or "-"
        )

        mention_assignee = self._mentions_enabled(
            config,
            SLACK_MENTION_ASSIGNEE_KEY,
        )
        mention_oncall = self._mentions_enabled(
            config,
            SLACK_MENTION_ONCALL_KEY,
        )
        mentioned_user_ids = set()

        if assignee:
            assignee_name = self._user_reference(
                assignee,
                mention=mention_assignee,
                mentioned_user_ids=mentioned_user_ids,
            )
        else:
            assignee_name = "-"

        # User references are already escaped or are deliberate Slack mention
        # markup, so they are inserted verbatim. Every other value is raw and
        # must be escaped here.
        values = [
            ("Team", self._escape_text(team_name)),
            ("Service", self._escape_text(alert_service_label(alert))),
            ("Status", self._escape_text(getattr(alert, "status", None) or "-")),
            ("Severity", self._escape_text(getattr(alert, "severity", None) or "-")),
            ("Priority", self._escape_text(alert_priority_label(alert))),
            ("Assignee", assignee_name),
        ]

        if mention_oncall:
            oncall_user = self._current_oncall_user(alert)

            if oncall_user:
                values.append((
                    "On-call",
                    self._user_reference(
                        oncall_user,
                        mention=True,
                        mentioned_user_ids=mentioned_user_ids,
                    ),
                ))

        values.extend([
            ("Source", self._escape_text(getattr(alert, "source", None) or "-")),
            ("Alert ID", self._escape_text(getattr(alert, "id", None) or "-")),
        ])

        return [
            {
                "type": "mrkdwn",
                "text": self._truncate(
                    f"*{title}*\n{value}",
                    2000,
                ),
            }
            for title, value in values
        ]

    def _title_for_alert(self, alert, event_type):
        """Return a Slack message title."""
        title = format_alert_title_with_priority(alert)
        status = getattr(alert, "status", None)

        if event_type == "resolved" or status == "resolved":
            return f"✅ RESOLVED: {title}"

        if event_type == "shelved" or is_alert_group_shelved(alert):
            return f"🔕 SHELVED: {title}"

        if event_type == "acknowledged" or status == "acknowledged":
            return f"🟡 ACKNOWLEDGED: {title}"

        if event_type == "reminder":
            return f"⏰ REMINDER: {title}"

        if event_type == "escalation":
            return f"⬆️ ESCALATION: {title}"

        if event_type == "test":
            return f"🧪 {title}"

        severity = str(
            getattr(alert, "severity", None) or ""
        ).lower()

        if severity in {"critical", "crit", "high", "error"}:
            return f"🚨 {title}"

        if severity in {"warning", "warn"}:
            return f"⚠️ {title}"

        return f"🔵 {title}"

    def _description_for_alert(
        self,
        alert,
        text,
        event_type,
    ):
        """Return message text for the current alert state."""
        message = getattr(alert, "message", None) or text or ""
        status = getattr(alert, "status", None)

        if event_type == "resolved" or status == "resolved":
            return f"The alert has been resolved.\n\n{message}"

        shelf = get_active_shelve(alert)
        if event_type == "shelved" or shelf:
            until = getattr(shelf, "ends_at", None) if shelf else None
            reason = getattr(shelf, "reason", None) if shelf else None
            details = "This alert is temporarily shelved."
            if until:
                details += f" Until {until.isoformat()} UTC."
            if reason:
                details += f" Reason: {reason}"
            return f"{details}\n\n{message}"

        if event_type == "acknowledged" or status == "acknowledged":
            acknowledged_by = getattr(
                alert,
                "acknowledged_by",
                None,
            )
            username = (
                getattr(acknowledged_by, "display_name", None)
                or getattr(acknowledged_by, "username", None)
                or "unknown"
            )

            return (
                f"The alert was acknowledged by {username}."
                f"\n\n{message}"
            )

        if event_type == "reminder":
            return (
                "This alert is still not acknowledged."
                f"\n\n{message}"
            )

        if event_type == "escalation":
            return f"The alert was escalated.\n\n{message}"

        return message

    def _service_links(self, alert):
        """Format service links using Slack mrkdwn syntax."""
        result = []

        for link in get_alert_service_links(alert):
            label = self._escape_link_label(
                link_display_label(link)
            )
            result.append(f"• <{link.url}|{label}>")

        return "\n".join(result)

    def _service_runbooks(self, alert):
        """Format service runbooks using Slack mrkdwn syntax."""
        result = []

        for runbook in get_alert_service_runbooks(alert):
            label = self._escape_link_label(
                runbook_display_label(runbook)
            )
            result.append(f"• <{runbook.url}|{label}>")

        return "\n".join(result)

    def _correlation_context(self, alert):
        """Format saved alert correlations using Slack mrkdwn."""
        correlation = format_correlation_markdown(alert)

        if not correlation:
            return ""

        return self._truncate(correlation, 3000)

    @staticmethod
    def _escape_text(value):
        """Escape dynamic text for Slack mrkdwn."""
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    @staticmethod
    def _escape_link_label(value):
        """Escape text used inside Slack link labels."""
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("|", "¦")
        )

    @staticmethod
    def _truncate(value, limit):
        """Limit a string to a Slack field size."""
        value = str(value or "")

        if len(value) <= limit:
            return value

        return f"{value[:limit - 1]}…"

    @staticmethod
    def _can_show_actions(alert):
        """Return True when Slack buttons should be displayed."""
        return bool(
            getattr(alert, "id", None)
            and getattr(alert, "status", None)
            in {"firing", "acknowledged"}
        )

    @staticmethod
    def _should_include_actions_after_update(
            alert,
            event_type,
    ):
        """Return whether buttons should remain after an update."""
        status = getattr(alert, "status", None)

        if event_type == "resolved" or status == "resolved":
            return False

        return status in {"firing", "acknowledged"}

    def _actions(self, channel, alert):
        """Build a Slack Block Kit actions block."""
        elements = []
        shelved = is_alert_group_shelved(alert)

        if shelved:
            elements.append(
                self._action_button(
                    action="unshelve",
                    label="Unshelve",
                    style=None,
                    channel=channel,
                    alert=alert,
                )
            )
        else:
            if alert.status == "firing":
                elements.append(
                    self._action_button(
                        action="acknowledge",
                        label="Acknowledge",
                        style="primary",
                        channel=channel,
                        alert=alert,
                    )
                )
            elements.append(
                self._action_button(
                    action="shelve",
                    label="Shelve 1h",
                    style=None,
                    channel=channel,
                    alert=alert,
                )
            )

        elements.append(
            self._action_button(
                action="resolve",
                label="Resolve",
                style="danger",
                channel=channel,
                alert=alert,
            )
        )

        return {
            "type": "actions",
            "block_id": f"incidentrelay_alert_{alert.id}",
            "elements": elements,
        }

    def _action_button(
            self,
            *,
            action,
            label,
            style,
            channel,
            alert,
    ):
        """Build one Slack action button."""
        context = {
            "action": action,
            "alert_id": alert.id,
            "channel_id": channel.id,
        }

        button = {
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": label,
                "emoji": True,
            },
            "action_id": f"incidentrelay_{action}",
            "value": json.dumps(
                context,
                separators=(",", ":"),
            ),
        }
        if style:
            button["style"] = style
        return button
