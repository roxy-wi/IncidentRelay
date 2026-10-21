"""Persistent, retryable delivery of incident participant notifications.

A participant is a user (or email address) pulled into an incident as a
responder or as a stakeholder. Notifying them can fan out across email, Slack
and browser push and, for team or rotation responders, across many recipients.
Doing that inline in the request that creates the participant is slow and, when
the request is retried, can send duplicates.

Instead the request only *enqueues* work: one ``ParticipantNotificationDelivery``
row per recipient per channel, guarded by a unique idempotency key so a retried
request cannot enqueue the same message twice. The scheduler then drains due
rows asynchronously (:func:`process_due_participant_notifications`), claiming
each row with a conditional update so it is sent once, retrying transient
failures with backoff, and recording the final outcome per participant. Because
delivery happens out of band, a delivery failure can never roll back responder
or stakeholder creation.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

import peewee

from app.modules.common import utc_now
from app.modules.db import alerts_repo, incidents_repo
from app.modules.db.models import (
    AlertGroup,
    ParticipantNotificationDelivery,
    User,
)
from app.modules.smtp import send_plain_email
from app.notifiers.browser_push import service as browser_push
from app.notifiers.registry import get_notifier
from app.notifiers.types import SLACK_CHANNEL
from app.services.notifications.delivery import channel_matches_alert_severity
from app.services.notifications.policies.resolver import (
    resolve_notification_channels,
)

logger = logging.getLogger("oncall.incidents.participants")

CHANNEL_EMAIL = "email"
CHANNEL_SLACK = "slack"
CHANNEL_BROWSER_PUSH = "browser_push"

KIND_RESPONDER = "responder"
KIND_STAKEHOLDER_ADDED = "stakeholder_added"

DEFAULT_MAX_ATTEMPTS = 5
RETRY_BACKOFF_BASE_SECONDS = 60
RETRY_BACKOFF_CAP_SECONDS = 3600

# Terminal (no further processing) vs. still-in-flight row statuses.
PENDING = "pending"
PROCESSING = "processing"
SENT = "sent"
FAILED = "failed"
SKIPPED = "skipped"

# Per-kind alert event vocabulary for the aggregate outcome.
_KIND_EVENTS = {
    KIND_RESPONDER: {
        "queued": "responder_notification_queued",
        "sent": "responder_notification_sent",
        "failed": "responder_notification_failed",
        "label": "Responder",
    },
    KIND_STAKEHOLDER_ADDED: {
        "queued": "stakeholder_added_notification_queued",
        "sent": "stakeholder_added_notification_sent",
        "failed": "stakeholder_added_notification_failed",
        "label": "Stakeholder added",
    },
}


@dataclass
class ParticipantRecipient:
    """One resolved participant notification target.

    ``user`` is absent for stakeholders added by email address only. Those
    recipients are email-only: Slack and browser push are never enqueued for
    them because there is no IncidentRelay profile to reach.
    """

    display_name: str
    user: object | None = None
    email: str | None = None

    @property
    def has_user(self):
        return self.user is not None


def is_notifiable_user(user):
    """Return whether a user can be notified at all.

    Inactive and soft-deleted users are excluded from delivery entirely and are
    never counted as delivery failures.
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
    honour route and service notification policy configuration, including each
    channel's notify_on_severities restriction: a Slack channel that excludes
    the incident's severity is not used to deliver participant notifications.
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

        if not channel_matches_alert_severity(channel, group):
            continue

        return channel

    return None


def _recipient_ref(recipient):
    """Return a stable identity for a recipient, for the idempotency key."""
    if recipient.has_user:
        return f"user:{getattr(recipient.user, 'id', None)}"

    return f"email:{(recipient.email or '').strip().lower()}"


def _idempotency_key(kind, source_id, event_type, recipient_ref, channel):
    """Build the unique key that prevents duplicate enqueues."""
    return ":".join(
        [kind, str(source_id), event_type, recipient_ref, channel]
    )


def _recipient_channels(recipient, use_slack, use_push):
    """Return the channels to enqueue for one recipient.

    Email is enqueued only when an address is known. Slack and browser push are
    enqueued only for recipients with an IncidentRelay user, since both need a
    profile to resolve.
    """
    channels = []

    if recipient.email:
        channels.append(CHANNEL_EMAIL)

    if recipient.has_user:
        if use_slack:
            channels.append(CHANNEL_SLACK)

        if use_push:
            channels.append(CHANNEL_BROWSER_PUSH)

    return channels


def enqueue_participant_notifications(
    group,
    recipients,
    *,
    kind,
    source_id,
    subject,
    body,
    slack_text,
    push_event_type,
    push_context=None,
    use_slack=True,
    use_push=True,
    max_attempts=DEFAULT_MAX_ATTEMPTS,
):
    """Persist one delivery row per recipient per applicable channel.

    Returns the number of rows actually created. Re-enqueuing the same
    participant event is a no-op: the unique idempotency key makes duplicate
    inserts silently ignored, so a retried request does not double-send.
    """
    if not recipients:
        return 0

    group_id = getattr(group, "id", None)
    now = utc_now()
    payload = {
        "subject": subject,
        "body": body,
        "slack_text": slack_text,
        "push_event_type": push_event_type,
        "push_context": push_context,
    }

    created = 0

    for recipient in recipients:
        recipient_ref = _recipient_ref(recipient)
        user_id = (
            getattr(recipient.user, "id", None)
            if recipient.has_user
            else None
        )

        for channel in _recipient_channels(recipient, use_slack, use_push):
            key = _idempotency_key(
                kind,
                source_id,
                push_event_type,
                recipient_ref,
                channel,
            )

            try:
                ParticipantNotificationDelivery.create(
                    group=group_id,
                    kind=kind,
                    source_id=source_id,
                    recipient_display=recipient.display_name,
                    recipient_user=user_id,
                    recipient_email=recipient.email,
                    channel=channel,
                    event_type=push_event_type,
                    payload=payload,
                    status=PENDING,
                    scheduled_at=now,
                    attempts=0,
                    max_attempts=max_attempts,
                    idempotency_key=key,
                    created_at=now,
                    updated_at=now,
                )
            except peewee.IntegrityError:
                # Duplicate idempotency key: this recipient/channel message was
                # already enqueued for this participant event, so skip it.
                continue

            created += 1

    return created


def _active_row_user(delivery):
    """Return the notifiable user for a delivery row, or None."""
    if not delivery.recipient_user_id:
        return None

    user = User.get_or_none(User.id == delivery.recipient_user_id)

    if not is_notifiable_user(user):
        return None

    return user


def _save_row(delivery, **fields):
    """Persist status/outcome fields on a delivery row."""
    fields.setdefault("updated_at", utc_now())

    (
        ParticipantNotificationDelivery
        .update(**fields)
        .where(ParticipantNotificationDelivery.id == delivery.id)
        .execute()
    )


def _mark_sent(delivery, *, provider, result=None):
    result = result or {}

    _save_row(
        delivery,
        status=SENT,
        sent_at=utc_now(),
        provider=provider,
        provider_status=result.get("provider_status") or "sent",
        provider_payload=result or None,
        external_message_id=result.get("external_message_id"),
        last_error=None,
    )

    return SENT


def _mark_skipped(delivery, reason):
    _save_row(delivery, status=SKIPPED, last_error=reason)

    return SKIPPED


def _mark_failed(delivery, error):
    _save_row(delivery, status=FAILED, last_error=error)

    return FAILED


def _retry_or_fail(delivery, error):
    """Reschedule a transiently failed row, or fail it once attempts run out."""
    attempts = (delivery.attempts or 0) + 1

    if attempts >= (delivery.max_attempts or DEFAULT_MAX_ATTEMPTS):
        _save_row(
            delivery,
            status=FAILED,
            attempts=attempts,
            last_error=error,
        )
        return FAILED

    backoff = min(
        RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempts - 1)),
        RETRY_BACKOFF_CAP_SECONDS,
    )

    _save_row(
        delivery,
        status=PENDING,
        attempts=attempts,
        scheduled_at=utc_now() + timedelta(seconds=backoff),
        last_error=error,
    )

    return PENDING


def _deliver_row(delivery):
    """Deliver one claimed row and record its outcome.

    Returns the resulting status. A missing address / channel / subscription is
    a terminal ``skipped`` (nothing to deliver, not an error). An exception from
    the transport is treated as transient and retried with backoff until
    ``max_attempts`` is reached.
    """
    payload = delivery.payload or {}
    group = AlertGroup.get_or_none(AlertGroup.id == delivery.group_id)

    if group is None:
        return _mark_skipped(delivery, "incident not found")

    try:
        if delivery.channel == CHANNEL_EMAIL:
            if not delivery.recipient_email:
                return _mark_skipped(delivery, "no email address")

            send_plain_email(
                delivery.recipient_email,
                payload.get("subject"),
                payload.get("body"),
            )
            return _mark_sent(delivery, provider=CHANNEL_EMAIL)

        if delivery.channel == CHANNEL_SLACK:
            user = _active_row_user(delivery)
            if user is None:
                return _mark_skipped(delivery, "recipient has no active user")

            slack_channel = resolve_slack_channel(group)
            if not slack_channel:
                return _mark_skipped(
                    delivery,
                    "no Slack channel configured for this incident",
                )

            notifier = get_notifier(SLACK_CHANNEL)
            result = notifier.send_direct_message(
                slack_channel,
                user,
                payload.get("slack_text"),
            ) or {}
            return _mark_sent(delivery, provider=CHANNEL_SLACK, result=result)

        if delivery.channel == CHANNEL_BROWSER_PUSH:
            user = _active_row_user(delivery)
            if user is None:
                return _mark_skipped(delivery, "recipient has no active user")

            count = browser_push.send_stakeholder_push_to_user(
                user,
                group,
                event_type=payload.get("push_event_type"),
                context=payload.get("push_context"),
            )
            if not count:
                return _mark_skipped(delivery, "no active push subscriptions")

            return _mark_sent(
                delivery,
                provider=CHANNEL_BROWSER_PUSH,
                result={"sent": count},
            )

        return _mark_failed(
            delivery,
            f"unsupported channel: {delivery.channel}",
        )
    except Exception as exc:
        logger.exception(
            "participant notification delivery failed",
            extra={
                "extra": {
                    "event_type": "participant_notification_failed",
                    "delivery_id": delivery.id,
                    "channel": delivery.channel,
                    "attempts": delivery.attempts,
                    "error": str(exc),
                }
            },
        )
        return _retry_or_fail(delivery, str(exc))


def process_due_participant_notifications(limit=100):
    """Deliver due participant notification rows; return the number sent.

    Each row is claimed with a conditional update so it is processed once.
    When every row for a participant event reaches a terminal state, the
    aggregate outcome is recorded (once) via an alert event and, for
    responders, the responder notification status.
    """
    now = utc_now()
    sent_total = 0
    finalize_sources = set()

    due_rows = (
        ParticipantNotificationDelivery
        .select()
        .where(
            (ParticipantNotificationDelivery.status == PENDING)
            & (ParticipantNotificationDelivery.scheduled_at <= now)
        )
        .order_by(ParticipantNotificationDelivery.scheduled_at.asc())
        .limit(limit)
    )

    for due_row in due_rows:
        claimed = (
            ParticipantNotificationDelivery
            .update(status=PROCESSING, updated_at=utc_now())
            .where(
                (ParticipantNotificationDelivery.id == due_row.id)
                & (ParticipantNotificationDelivery.status == PENDING)
            )
            .execute()
        )

        if not claimed:
            continue

        delivery = ParticipantNotificationDelivery.get_by_id(due_row.id)
        outcome = _deliver_row(delivery)

        if outcome == SENT:
            sent_total += 1

        if outcome in {SENT, FAILED, SKIPPED}:
            finalize_sources.add((delivery.kind, delivery.source_id))

    for kind, source_id in finalize_sources:
        _finalize_source_if_complete(kind, source_id)

    return sent_total


def _finalize_source_if_complete(kind, source_id):
    """Record the aggregate outcome once all rows for a source are terminal."""
    rows = list(
        ParticipantNotificationDelivery
        .select()
        .where(
            (ParticipantNotificationDelivery.kind == kind)
            & (ParticipantNotificationDelivery.source_id == source_id)
        )
    )

    if not rows:
        return

    if any(row.status in {PENDING, PROCESSING} for row in rows):
        # Still in flight (e.g. a row is waiting for a retry); finalize later.
        return

    events = _KIND_EVENTS.get(kind)
    if not events:
        return

    sent_rows = [row for row in rows if row.status == SENT]
    failed_rows = [row for row in rows if row.status == FAILED]

    def describe(row):
        return f"{row.recipient_display} ({row.channel}): {row.last_error}"

    failed_text = "; ".join(describe(row) for row in failed_rows)
    channels_sent = sorted({row.channel for row in sent_rows})
    group_id = rows[0].group_id

    if sent_rows:
        status = "sent"
        error_text = failed_text or None
        channels = ", ".join(channels_sent) or "no channels"
        message = f"{events['label']} notification sent via {channels}"

        if error_text:
            message = f"{message} (partial failures: {error_text})"

        alerts_repo.create_alert_event(
            group_id=group_id,
            event_type=events["sent"],
            message=message,
            user_id=None,
        )
    else:
        status = "failed"
        skip_text = "; ".join(
            describe(row)
            for row in rows
            if row.status == SKIPPED and row.last_error
        )
        error_text = failed_text or skip_text or "no notifications were sent"

        alerts_repo.create_alert_event(
            group_id=group_id,
            event_type=events["failed"],
            message=f"{events['label']} notification failed: {error_text}",
            user_id=None,
        )

    if kind == KIND_RESPONDER and source_id:
        incidents_repo.update_incident_responder_notification(
            source_id,
            status=status,
            error=error_text,
        )
