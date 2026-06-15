import logging

import requests

from app.notifiers.base import BaseNotifier
from app.services.links import build_alert_web_url
from app.services.routing.service_context import (
    get_alert_service_links,
    get_alert_service_runbooks,
    link_display_label,
    runbook_display_label,
)
from app.services.alerts.priority import (
    alert_priority_label,
    alert_priority_short_label,
)

logger = logging.getLogger("oncall.alerts")


def alert_service_label(alert):
    """Return a human-readable affected service label."""
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

        return " / ".join(str(part) for part in parts if part)

    service_id = getattr(alert, "service_id", None)
    if service_id:
        return f"Service #{service_id}"

    return "-"


class IncomingWebhookNotifier(BaseNotifier):
    """Send notifications through a generic incoming webhook."""

    name = "webhook"

    def send(self, channel, alert, text, event_type="notification"):
        """Send a JSON webhook notification."""
        config = channel.config or {}
        webhook_url = config.get("webhook_url")
        if not webhook_url:
            raise RuntimeError("webhook_url is missing")

        response = requests.post(
            webhook_url,
            json={
                "text": text,
                "alert_id": alert.id,
                "alert_url": build_alert_web_url(alert),
                "team": alert.team.slug if alert.team else None,
                "status": alert.status,
                "source": alert.source,
                "title": alert.title,
                "message": alert.message,
                "severity": alert.severity,
                "priority": alert_priority_short_label(alert),
                "priority_label": alert_priority_label(alert),
                "assignee": alert.assignee.username if alert.assignee else None,
                "service": alert_service_label(alert),
                "service_id": alert.service.id if getattr(alert, "service", None) else None,
                "service_name": (
                    alert.service.name
                    if getattr(alert, "service", None)
                    else None
                ),
                "service_slug": (
                    alert.service.slug
                    if getattr(alert, "service", None)
                    else None
                ),
                "service_links": [
                    {
                        "id": link.id,
                        "type": link.link_type,
                        "label": link_display_label(link),
                        "url": link.url,
                    }
                    for link in get_alert_service_links(alert)
                ],
                "service_runbooks": [
                    {
                        "id": runbook.id,
                        "title": runbook_display_label(runbook),
                        "url": runbook.url,
                        "severity": runbook.severity,
                    }
                    for runbook in get_alert_service_runbooks(alert)
                ],
            },
            timeout=10,
        )
        response.raise_for_status()
        return {"provider": self.name}


class SlackNotifier(IncomingWebhookNotifier):
    """Send notifications through Slack Incoming Webhook."""

    name = "slack"


class TeamsNotifier(IncomingWebhookNotifier):
    """Send notifications through Microsoft Teams Incoming Webhook."""

    name = "teams"


class DiscordNotifier(IncomingWebhookNotifier):
    """Send notifications through Discord Webhook."""

    name = "discord"

    def send(self, channel, alert, text, event_type="notification"):
        """Send a Discord webhook notification."""
        config = channel.config or {}
        webhook_url = config.get("webhook_url")
        if not webhook_url:
            raise RuntimeError("webhook_url is missing")

        response = requests.post(webhook_url, json={"content": text}, timeout=10)
        response.raise_for_status()
        return {"provider": self.name}


