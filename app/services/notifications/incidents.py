"""Durable delivery for operational Incident events using the shared retry policy."""

import hashlib
import logging
from datetime import timedelta
from uuid import uuid4

from app.db import database_proxy as db
from app.modules.common import utc_now
from app.modules.db import incident_core_repo, incidents_repo
from app.modules.db.models import (
    BrowserPushSubscription,
    IncidentNotificationDelivery,
    IncidentResponder,
    IncidentStakeholder,
    User,
)
from app.notifiers.browser_push import service as browser_push
from app.services.notifications.retries import delivery_attempt
from app.settings import Config


logger = logging.getLogger("oncall.incident_notifications")
MAX_ATTEMPTS = 5
CLAIM_SECONDS = 300
STAKEHOLDER_FLAGS = {
    "created": "notify_on_created",
    "priority_changed": "notify_on_priority_change",
    "status_changed": "notify_on_status_change",
    "resolved": "notify_on_resolved",
    "comment_added": "notify_on_comment",
}


class DeliveryUnavailable(RuntimeError):
    """A retryable delivery failure with a fixed, non-secret reason."""


def _safe_error(exc):
    # Provider exception strings can contain credentials or push endpoints.
    return str(exc) if isinstance(exc, DeliveryUnavailable) else type(exc).__name__


def _active_user(user_id):
    return User.get_or_none(
        User.id == user_id,
        User.active == True,
        User.deleted == False,  # noqa: E712
    )


def _payload(incident, event, event_type, context=None):
    context = context or {}
    priority = incident.priority.slug if incident.priority_id else "-"
    url = f"{(Config.PUBLIC_BASE_URL or '').rstrip('/')}/incidents/{incident.id}"
    body = (
        f"Incident: {incident.title}\nPriority: {priority}\n"
        f"Status: {incident.workflow_status}\nURL: {url}"
    )
    if context.get("message"):
        body += f"\n{context['message']}"
    push = browser_push.build_incident_push_payload(
        incident,
        event_type=event_type,
        context={**context, "message": body, "event_id": event.id},
    )
    return {
        "event_type": event_type,
        "subject": f"Incident #{incident.id}: {incident.title} ({event_type})",
        "body": body,
        "push": push,
    }


def _enqueue(incident, event, method, target_key, payload, **fields):
    return IncidentNotificationDelivery.get_or_create(
        event=event.id,
        method=method,
        target_key=target_key,
        defaults={"incident": incident.id, "payload": payload, **fields},
    )[0]


def enqueue_stakeholders(
    incident, event, event_type, *, skip_user_id=None, context=None
):
    """Snapshot eligible recipients inside the event's transaction, deduplicating roles."""
    flag = STAKEHOLDER_FLAGS[event_type]
    payload = _payload(incident, event, event_type, context)
    targets = {}
    for stakeholder in incidents_repo.list_incident_stakeholders(incident.id):
        if stakeholder.user_id == skip_user_id and skip_user_id is not None:
            continue
        if not getattr(stakeholder, flag):
            continue
        user = _active_user(stakeholder.user_id) if stakeholder.user_id else None
        if stakeholder.user_id and user is None:
            continue
        email = (stakeholder.email or (user.email if user else "") or "").strip()
        channels = []
        if email:
            key = hashlib.sha256(email.casefold().encode()).hexdigest()
            channels.append(("email", key, {"recipient": email, "user": user}))
        if user:
            channels.append(("browser_push", f"user:{user.id}", {"user": user}))
        for method, key, fields in channels:
            target = targets.setdefault((method, key), {"fields": fields, "ids": []})
            target["ids"].append(stakeholder.id)
    for (method, key), target in targets.items():
        _enqueue(
            incident,
            event,
            method,
            key,
            {**payload, "stakeholder_ids": target["ids"]},
            **target["fields"],
        )


def enqueue_responder(responder, event):
    """Persist responder targets with their request; transport runs after commit."""
    from app.services.incidents.responder_notifications import (
        _responder_notification_context,
        resolve_responder_recipients,
    )

    incident = responder.incident
    payload = _payload(
        incident,
        event,
        "responder_requested",
        _responder_notification_context(responder),
    )
    recipients = resolve_responder_recipients(responder)
    if not recipients:
        _enqueue(
            incident,
            event,
            "browser_push",
            "no_recipients",
            payload,
            responder_id=responder.id,
        )
    for user in recipients:
        _enqueue(
            incident,
            event,
            "browser_push",
            f"user:{user.id}",
            payload,
            user=user,
            responder_id=responder.id,
        )


def _owned(delivery):
    return (
        (IncidentNotificationDelivery.id == delivery.id)
        & (IncidentNotificationDelivery.status == "processing")
        & (IncidentNotificationDelivery.claim_token == delivery.claim_token)
    )


def _save_progress(delivery, **values):
    updated = (
        IncidentNotificationDelivery.update(
            **values,
            claim_expires_at=utc_now() + timedelta(seconds=CLAIM_SECONDS),
        )
        .where(_owned(delivery))
        .execute()
    )
    if updated != 1:
        raise DeliveryUnavailable("delivery_claim_lost")


def _is_relevant(delivery):
    if delivery.user_id and _active_user(delivery.user_id) is None:
        return False
    if delivery.target_key.startswith("user:") and not delivery.user_id:
        return False
    if delivery.responder_id:
        return (
            IncidentResponder.select()
            .where(
                IncidentResponder.id == delivery.responder_id,
                IncidentResponder.incident == delivery.incident_id,
                IncidentResponder.status == "requested",
                IncidentResponder.expires_at.is_null(True)
                | (IncidentResponder.expires_at > utc_now()),
            )
            .exists()
        )
    ids = delivery.payload.get("stakeholder_ids", [])
    flag = getattr(
        IncidentStakeholder, STAKEHOLDER_FLAGS[delivery.payload["event_type"]]
    )
    return (
        IncidentStakeholder.select()
        .where(
            IncidentStakeholder.id.in_(ids),
            IncidentStakeholder.incident == delivery.incident_id,
            IncidentStakeholder.active == True,
            flag == True,  # noqa: E712
        )
        .exists()
    )


def _send_push(delivery):
    if not Config.BROWSER_PUSH_ENABLED:
        raise DeliveryUnavailable("browser_push_disabled")
    if not delivery.user_id:
        raise DeliveryUnavailable("no_active_responder_recipients")
    ids = delivery.subscription_ids
    if ids is None:
        ids = [
            row.id for row in browser_push._active_user_subscriptions(delivery.user_id)
        ]
        if not ids:
            raise DeliveryUnavailable("no_active_push_subscriptions")
        _save_progress(delivery, subscription_ids=ids)
    sent_ids = list(delivery.sent_subscription_ids or [])
    failures = []
    for subscription_id in ids:
        if subscription_id in sent_ids:
            continue
        if not _is_relevant(delivery):
            return "skipped", len(sent_ids)
        subscription = BrowserPushSubscription.get_or_none(
            BrowserPushSubscription.id == subscription_id,
            BrowserPushSubscription.user == delivery.user_id,
            BrowserPushSubscription.enabled == True,  # noqa: E712
            BrowserPushSubscription.deleted == False,  # noqa: E712
        )
        if subscription is None:
            continue
        _save_progress(delivery)
        try:
            sent = browser_push.send_incident_push_to_subscription(
                subscription,
                delivery.payload["push"],
            )
        except Exception as exc:
            failures.append(_safe_error(exc))
            continue
        if sent:
            sent_ids.append(subscription.id)
            # Commit every successful device before trying the next one.
            _save_progress(delivery, sent_subscription_ids=sent_ids)
    if failures:
        raise DeliveryUnavailable(
            "push_delivery_failed: " + ", ".join(sorted(set(failures)))
        )
    return ("sent" if sent_ids else "skipped"), len(sent_ids)


def _send(delivery):
    if not _is_relevant(delivery):
        return "skipped", 0
    if delivery.method == "browser_push":
        return _send_push(delivery)
    if delivery.method != "email":
        raise DeliveryUnavailable("unsupported_delivery_method")
    from app.services.incidents.stakeholders import send_stakeholder_email

    _save_progress(delivery)
    if not send_stakeholder_email(
        delivery.recipient,
        delivery.payload["subject"],
        delivery.payload["body"],
    ):
        raise DeliveryUnavailable("email_not_sent")
    return "sent", 1


def _update_responder_summary(responder_id):
    if not responder_id:
        return
    rows = list(
        IncidentNotificationDelivery.select().where(
            IncidentNotificationDelivery.responder_id == responder_id,
        )
    )
    pending = any(row.status in {"pending", "processing"} for row in rows)
    failed = any(row.status in {"failed", "skipped"} for row in rows)
    status = "pending" if pending else ("failed" if failed else "sent")
    incidents_repo.update_incident_responder_notification(
        responder_id,
        status=status,
        error=next((row.last_error for row in rows if row.last_error), None),
    )


def _process_one(delivery_id, now):
    token = uuid4().hex
    eligible = (
        (IncidentNotificationDelivery.status == "pending")
        & (IncidentNotificationDelivery.next_attempt_at <= now)
    ) | (
        (IncidentNotificationDelivery.status == "processing")
        & (IncidentNotificationDelivery.claim_expires_at <= now)
    )
    claimed = (
        IncidentNotificationDelivery.update(
            status="processing",
            claim_token=token,
            claim_expires_at=now + timedelta(seconds=CLAIM_SECONDS),
            attempts=IncidentNotificationDelivery.attempts + 1,
            updated_at=now,
        )
        .where(IncidentNotificationDelivery.id == delivery_id, eligible)
        .execute()
    )
    if not claimed:
        return 0
    delivery = IncidentNotificationDelivery.get_or_none(
        IncidentNotificationDelivery.id == delivery_id,
        IncidentNotificationDelivery.status == "processing",
        IncidentNotificationDelivery.claim_token == token,
    )
    if delivery is None:
        return 0
    if delivery.attempts > MAX_ATTEMPTS:
        values = {
            "status": "failed",
            "attempts": MAX_ATTEMPTS,
            "last_error": "delivery_attempts_exhausted",
        }
    else:
        values = delivery_attempt(
            lambda: _send(delivery),
            attempt=delivery.attempts,
            now=now,
            max_attempts=MAX_ATTEMPTS,
            error_text=_safe_error,
        )
    with incident_core_repo.incident_transaction(delivery.incident_id):
        updated = (
            IncidentNotificationDelivery.update(
                **values,
                claim_token=None,
                claim_expires_at=None,
            )
            .where(_owned(delivery))
            .execute()
        )
        if not updated:
            return 0
        status = values["status"]
        incident_core_repo.create_event(
            delivery.incident_id,
            f"incident_notification_{status}",
            data={
                "delivery_id": delivery.id,
                "source_event_id": delivery.event_id,
                "method": delivery.method,
                "attempt": delivery.attempts,
            },
        )
        _update_responder_summary(delivery.responder_id)
    if values.get("last_error"):
        logger.warning(
            "Incident delivery failed: delivery_id=%s attempt=%s reason=%s",
            delivery.id,
            delivery.attempts,
            values["last_error"],
        )
    return values.get("delivered_count", 0) if status == "sent" else 0


def _enqueue_outstanding_responder_requests(now, limit):
    """Resume pre-upgrade unsent requests without replaying sent or expired ones."""
    queued = IncidentNotificationDelivery.select(
        IncidentNotificationDelivery.responder_id,
    ).where(IncidentNotificationDelivery.responder_id.is_null(False))
    candidates = list(
        IncidentResponder.select()
        .where(
            IncidentResponder.status == "requested",
            IncidentResponder.notification_status.in_(("pending", "failed")),
            IncidentResponder.expires_at.is_null(True)
            | (IncidentResponder.expires_at > now),
            IncidentResponder.id.not_in(queued),
        )
        .order_by(IncidentResponder.id)
        .limit(limit)
    )
    for selected in candidates:
        try:
            with incident_core_repo.incident_transaction(selected.incident_id):
                responder = IncidentResponder.get_by_id(selected.id)
                if (
                    responder.status != "requested"
                    or responder.notification_status not in {"pending", "failed"}
                    or (responder.expires_at and responder.expires_at <= now)
                    or responder_notification_event(responder.id) is not None
                ):
                    continue
                event = incident_core_repo.create_event(
                    responder.incident_id,
                    "responder_notification_queued",
                    data={"responder_id": responder.id},
                )
                enqueue_responder(responder, event)
        except Exception as exc:
            logger.error(
                "Responder delivery enqueue deferred: responder_id=%s error_type=%s",
                selected.id,
                type(exc).__name__,
            )


def process_due_incident_notifications(*, now=None, limit=100, event_id=None):
    """Claim due targets; successful targets and live claims are never resent."""
    if db.in_transaction():
        # Composed domain operations leave dispatch to the existing scheduler.
        return 0
    now = now or utc_now()
    if event_id is None:
        _enqueue_outstanding_responder_requests(now, limit)
    query = IncidentNotificationDelivery.select(IncidentNotificationDelivery.id).where(
        (
            (IncidentNotificationDelivery.status == "pending")
            & (IncidentNotificationDelivery.next_attempt_at <= now)
        )
        | (
            (IncidentNotificationDelivery.status == "processing")
            & (IncidentNotificationDelivery.claim_expires_at <= now)
        )
    )
    if event_id is not None:
        query = query.where(IncidentNotificationDelivery.event == event_id)
    ids = [
        row.id
        for row in query.order_by(
            IncidentNotificationDelivery.next_attempt_at,
            IncidentNotificationDelivery.id,
        ).limit(limit)
    ]
    sent = 0
    for delivery_id in ids:
        try:
            sent += _process_one(delivery_id, now)
        except Exception as exc:
            # The durable pending row/claim survives DB and worker failures.
            logger.error(
                "Incident delivery worker failed: delivery_id=%s error_type=%s",
                delivery_id,
                type(exc).__name__,
            )
    return sent


def dispatch_event(event_id):
    """Best-effort eager delivery after commit; a failure leaves scheduler work."""
    try:
        return process_due_incident_notifications(event_id=event_id)
    except Exception as exc:
        logger.error(
            "Incident dispatch deferred: event_id=%s error_type=%s",
            event_id,
            type(exc).__name__,
        )
        return 0


def responder_notification_event(responder_id):
    return (
        IncidentNotificationDelivery.select(IncidentNotificationDelivery.event)
        .where(IncidentNotificationDelivery.responder_id == responder_id)
        .first()
    )
