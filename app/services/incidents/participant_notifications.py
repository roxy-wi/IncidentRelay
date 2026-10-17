"""Shared notification fan-out for incident participants.

A participant is a user pulled into an incident as a responder or as a
stakeholder. Both cases need the same delivery behaviour, so the fan-out,
per-channel result aggregation and auditing live here rather than being
implemented separately in the responder and stakeholder services.

Delivery is best-effort across channels: the notification counts as sent when
at least one channel succeeds, and per-channel errors are recorded even on
success so a misconfigured channel stays visible.
"""

import logging
from dataclasses import dataclass, field

from app.modules.db import alerts_repo
from app.modules.smtp import send_plain_email
from app.notifiers.browser_push import service as browser_push
from app.notifiers.registry import get_notifier
from app.notifiers.types import SLACK_CHANNEL
from app.services.notifications.policies.resolver import (
    resolve_notification_channels,
)

logger = logging.getLogger("oncall.incidents.participants")

EMAIL_CHANNEL_LABEL = "email"
SLACK_CHANNEL_LABEL = "slack"
BROWSER_PUSH_CHANNEL_LABEL = "browser_push"


@dataclass
class ParticipantRecipient:
    """One resolved participant notification target.

    ``user`` is absent for stakeholders that were added by email address only.
    Those recipients are email-only: Slack and browser push are never attempted
    for them because there is no IncidentRelay profile to look up.
    """

    display_name: str
    user: object | None = None
    email: str | None = None

    @property
    def has_user(self):
        return self.user is not None


@dataclass
class ChannelAttempt:
    """Outcome of one channel delivery attempt for one recipient."""

    channel: str
    recipient: str
    sent: int = 0
    error: str | None = None

    @property
    def succeeded(self):
        return self.sent > 0 and self.error is None


@dataclass
class ParticipantNotificationResult:
    """Aggregated outcome of a participant notification."""

    attempts: list = field(default_factory=list)

    @property
    def sent(self):
        return sum(attempt.sent for attempt in self.attempts)

    @property
    def succeeded_channels(self):
        result = []

        for attempt in self.attempts:
            if attempt.succeeded and attempt.channel not in result:
                result.append(attempt.channel)

        return result

    @property
    def errors(self):
        return [
            f"{attempt.recipient} ({attempt.channel}): {attempt.error}"
            for attempt in self.attempts
            if attempt.error
        ]

    @property
    def error_text(self):
        return "; ".join(self.errors) or None

    @property
    def status(self):
        return "sent" if self.sent > 0 else "failed"

    def as_dict(self):
        return {
            "status": self.status,
            "sent": self.sent,
            "error": self.error_text,
            "channels": self.succeeded_channels,
        }


def is_notifiable_user(user):
    """Return whether a user can be notified at all.

    Inactive and soft-deleted users are excluded from delivery entirely and
    are never counted as delivery failures.
    """
    if not user:
        return False

    if getattr(user, "deleted", False):
        return False

    return bool(getattr(user, "active", False))


def user_contact_email(user):
    """Return a usable profile email for a user, or None."""
    if not user:
        return None

    return str(getattr(user, "email", None) or "").strip() or None


def resolve_slack_channel(group):
    """Return the first usable Slack channel for an incident, or None.

    Reuses the normal notification channel resolution so participant messages
    honour route and service notification policy configuration.
    """
    try:
        resolution = resolve_notification_channels(group)
    except Exception:
        logger.exception(
            "participant slack channel resolution failed",
            extra={"extra": {"group_id": getattr(group, "id", None)}},
        )
        return None

    for channel in getattr(resolution, "channels", []) or []:
        if channel.channel_type != SLACK_CHANNEL:
            continue

        if not channel.enabled:
            continue

        return channel

    return None


def _attempt_email(recipient, subject, body):
    """Deliver a participant notification by email."""
    if not recipient.email:
        return ChannelAttempt(
            channel=EMAIL_CHANNEL_LABEL,
            recipient=recipient.display_name,
            error="no email address",
        )

    try:
        send_plain_email(recipient.email, subject, body)
    except Exception as exc:
        logger.exception(
            "participant email notification failed",
            extra={
                "extra": {
                    "event_type": "participant_notification_failed",
                    "channel": EMAIL_CHANNEL_LABEL,
                    "error": str(exc),
                }
            },
        )
        return ChannelAttempt(
            channel=EMAIL_CHANNEL_LABEL,
            recipient=recipient.display_name,
            error=str(exc),
        )

    return ChannelAttempt(
        channel=EMAIL_CHANNEL_LABEL,
        recipient=recipient.display_name,
        sent=1,
    )


def _attempt_slack(recipient, slack_channel, text):
    """Deliver a participant notification through Slack."""
    if not recipient.has_user:
        return None

    if not slack_channel:
        return ChannelAttempt(
            channel=SLACK_CHANNEL_LABEL,
            recipient=recipient.display_name,
            error="no Slack channel configured for this incident",
        )

    try:
        notifier = get_notifier(SLACK_CHANNEL)
        notifier.send_direct_message(slack_channel, recipient.user, text)
    except Exception as exc:
        logger.exception(
            "participant slack notification failed",
            extra={
                "extra": {
                    "event_type": "participant_notification_failed",
                    "channel": SLACK_CHANNEL_LABEL,
                    "error": str(exc),
                }
            },
        )
        return ChannelAttempt(
            channel=SLACK_CHANNEL_LABEL,
            recipient=recipient.display_name,
            error=str(exc),
        )

    return ChannelAttempt(
        channel=SLACK_CHANNEL_LABEL,
        recipient=recipient.display_name,
        sent=1,
    )


def _attempt_browser_push(recipient, group, push_event_type, push_context):
    """Deliver a participant notification through browser push."""
    if not recipient.has_user:
        return None

    try:
        if push_context is None:
            sent = browser_push.send_stakeholder_push_to_user(
                recipient.user,
                group,
                event_type=push_event_type,
            )
        else:
            sent = browser_push.send_stakeholder_push_to_user(
                recipient.user,
                group,
                event_type=push_event_type,
                context=push_context,
            )
    except Exception as exc:
        logger.exception(
            "participant browser push failed",
            extra={
                "extra": {
                    "event_type": "participant_notification_failed",
                    "channel": BROWSER_PUSH_CHANNEL_LABEL,
                    "error": str(exc),
                }
            },
        )
        return ChannelAttempt(
            channel=BROWSER_PUSH_CHANNEL_LABEL,
            recipient=recipient.display_name,
            error=str(exc),
        )

    if not sent:
        return ChannelAttempt(
            channel=BROWSER_PUSH_CHANNEL_LABEL,
            recipient=recipient.display_name,
            error="no active push subscriptions",
        )

    return ChannelAttempt(
        channel=BROWSER_PUSH_CHANNEL_LABEL,
        recipient=recipient.display_name,
        sent=sent,
    )


def notify_participants(
    group,
    recipients,
    *,
    subject,
    body,
    slack_text,
    push_event_type,
    push_context=None,
    slack_channel=None,
    use_slack=True,
    use_push=True,
):
    """Notify incident participants across email, Slack and browser push.

    Each recipient is attempted on every applicable channel. One failing
    channel or recipient never prevents the remaining deliveries.
    """
    result = ParticipantNotificationResult()

    if not recipients:
        return result

    if use_slack and slack_channel is None:
        slack_channel = resolve_slack_channel(group)

    for recipient in recipients:
        result.attempts.append(_attempt_email(recipient, subject, body))

        if use_slack:
            attempt = _attempt_slack(recipient, slack_channel, slack_text)

            if attempt:
                result.attempts.append(attempt)

        if use_push:
            attempt = _attempt_browser_push(
                recipient,
                group,
                push_event_type,
                push_context,
            )

            if attempt:
                result.attempts.append(attempt)

    return result


def record_participant_notification_events(
    group_id,
    result,
    *,
    sent_event_type,
    failed_event_type,
    label,
):
    """Write alert events describing a participant notification outcome."""
    if result.status == "sent":
        channels = ", ".join(result.succeeded_channels) or "no channels"
        message = f"{label} notification sent via {channels}"

        if result.error_text:
            message = f"{message} (partial failures: {result.error_text})"

        alerts_repo.create_alert_event(
            group_id=group_id,
            event_type=sent_event_type,
            message=message,
            user_id=None,
        )
        return

    error = result.error_text or "no notifications were sent"

    alerts_repo.create_alert_event(
        group_id=group_id,
        event_type=failed_event_type,
        message=f"{label} notification failed: {error}",
        user_id=None,
    )
