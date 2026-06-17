import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta

from pywebpush import WebPushException, webpush

from app.modules.db.models import (
    AlertGroup,
    BrowserPushActionToken,
    BrowserPushSubscription,
)
from app.db import database_proxy as db
from app.services.audit import write_audit
from app.modules.common import truncate_text
from app.services.links import build_alert_web_url
from app.settings import Config
from app.services.alerts.priority import (
    alert_priority_label,
    alert_priority_short_label,
    format_alert_title_with_priority,
)


logger = logging.getLogger("oncall.notifications")


def get_public_config():
    return {
        "enabled": bool(Config.BROWSER_PUSH_ENABLED),
        "public_key": Config.BROWSER_PUSH_VAPID_PUBLIC_KEY or None,
    }


def serialize_subscription(subscription):
    return {
        "id": subscription.id,
        "device_name": subscription.device_name,
        "user_agent": subscription.user_agent,
        "enabled": subscription.enabled,
        "created_at": subscription.created_at.isoformat() if subscription.created_at else None,
        "last_seen_at": subscription.last_seen_at.isoformat() if subscription.last_seen_at else None,
    }


def list_user_subscriptions(user):
    rows = (
        BrowserPushSubscription
        .select()
        .where(
            (BrowserPushSubscription.user == user.id)
            & (BrowserPushSubscription.deleted == False)
        )
        .order_by(BrowserPushSubscription.id.desc())
    )

    return [serialize_subscription(row) for row in rows]


def save_user_subscription(user, endpoint, keys, device_name=None, user_agent=None):
    if not endpoint:
        raise ValueError("endpoint is required")

    p256dh = keys.get("p256dh")
    auth = keys.get("auth")

    if not p256dh or not auth:
        raise ValueError("subscription keys p256dh/auth are required")

    subscription = BrowserPushSubscription.get_or_none(
        BrowserPushSubscription.endpoint == endpoint
    )

    now = datetime.utcnow()

    if not subscription:
        return BrowserPushSubscription.create(
            user=user.id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            device_name=device_name,
            user_agent=user_agent,
            enabled=True,
            deleted=False,
            created_at=now,
            updated_at=now,
            last_seen_at=now,
        )

    subscription.user = user.id
    subscription.p256dh = p256dh
    subscription.auth = auth
    subscription.device_name = device_name or subscription.device_name
    subscription.user_agent = user_agent or subscription.user_agent
    subscription.enabled = True
    subscription.deleted = False
    subscription.deleted_at = None
    subscription.updated_at = now
    subscription.last_seen_at = now
    subscription.save()

    return subscription


def disable_user_subscription(user, subscription_id):
    subscription = BrowserPushSubscription.get_or_none(
        (BrowserPushSubscription.id == subscription_id)
        & (BrowserPushSubscription.user == user.id)
    )

    if not subscription:
        return None

    subscription.enabled = False
    subscription.deleted = True
    subscription.deleted_at = datetime.utcnow()
    subscription.updated_at = datetime.utcnow()
    subscription.save()

    return subscription


def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_action_token(user, group, action):
    raw_token = secrets.token_urlsafe(32)
    ttl = int(getattr(Config, "BROWSER_PUSH_ACTION_TOKEN_TTL_SECONDS", 900))

    BrowserPushActionToken.create(
        user=user.id,
        group=group.id,
        action=action,
        token_hash=_hash_token(raw_token),
        expires_at=datetime.utcnow() + timedelta(seconds=ttl),
    )

    return raw_token


def _subscription_info(subscription):
    return {
        "endpoint": subscription.endpoint,
        "keys": {
            "p256dh": subscription.p256dh,
            "auth": subscription.auth,
        },
    }


def _webpush(subscription, payload):
    return webpush(
        subscription_info=_subscription_info(subscription),
        data=json.dumps(payload),
        vapid_private_key=Config.BROWSER_PUSH_VAPID_PRIVATE_KEY,
        vapid_claims={
            "sub": Config.BROWSER_PUSH_VAPID_SUBJECT,
        },
    )


def _active_user_subscriptions(user_id):
    return list(
        BrowserPushSubscription
        .select()
        .where(
            (BrowserPushSubscription.user == user_id)
            & (BrowserPushSubscription.enabled == True)
            & (BrowserPushSubscription.deleted == False)
        )
    )


def has_active_user_subscriptions(user_id):
    if not Config.BROWSER_PUSH_ENABLED:
        return False

    if not user_id:
        return False

    return (
        BrowserPushSubscription
        .select(BrowserPushSubscription.id)
        .where(
            (BrowserPushSubscription.user == user_id)
            & (BrowserPushSubscription.enabled == True)
            & (BrowserPushSubscription.deleted == False)
        )
        .exists()
    )


def can_send_alert_push(group):
    return has_active_user_subscriptions(getattr(group, "assignee_id", None))


def build_alert_push_payload(group, user, event_type="notification"):
    action_tokens = {}

    if group.status == "firing":
        action_tokens["ack"] = create_action_token(user, group, "ack")
        action_tokens["resolve"] = create_action_token(user, group, "resolve")
    elif group.status == "acknowledged":
        action_tokens["resolve"] = create_action_token(user, group, "resolve")

    return {
        "title": _build_alert_push_title(group, event_type),
        "body": _build_alert_push_body(group, event_type),
        "alert_id": group.id,
        "alert_group_id": group.id,
        "alert_title": group.title,
        "status": group.status,
        "priority": alert_priority_short_label(group),
        "priority_label": alert_priority_label(group),
        "url": build_alert_web_url(group) or f"/alerts/{group.id}",
        "tag": f"incidentrelay-alert-group-{group.id}",
        "require_interaction": True,
        "renotify": True,
        "silent": False,
        "vibrate": [300, 100, 300],
        "event_type": event_type,
        "action_tokens": action_tokens,
    }


def send_alert_push_to_user(user, group, event_type="notification"):
    if not Config.BROWSER_PUSH_ENABLED:
        return 0

    subscriptions = _active_user_subscriptions(user.id)

    if not subscriptions:
        return 0

    payload = build_alert_push_payload(group, user, event_type=event_type)

    sent = 0

    for subscription in subscriptions:
        try:
            _webpush(subscription, payload)
            subscription.last_seen_at = datetime.utcnow()
            subscription.save()
            sent += 1
        except WebPushException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)

            if status_code in {404, 410}:
                subscription.enabled = False
                subscription.deleted = True
                subscription.deleted_at = datetime.utcnow()
                subscription.updated_at = datetime.utcnow()
                subscription.save()

            logger.warning(
                "browser push failed",
                extra={
                    "extra": {
                        "event_type": "browser_push_failed",
                        "user_id": user.id,
                        "subscription_id": subscription.id,
                        "status_code": status_code,
                        "error": str(exc),
                    }
                },
            )

    return sent


def build_stakeholder_alert_push_payload(
    group,
    event_type="incident_created",
    context=None,
):
    """Build browser push payload for incident stakeholders.

    Stakeholder push notifications are informational and do not include
    ack/resolve action tokens.
    """
    normalized_event_type = (event_type or "").lower()

    if normalized_event_type in {"created", "incident_created", "notification"}:
        title = f"INCIDENT CREATED: {format_alert_title_with_priority(group)}"
        body = (
            group.message
            or f"Priority: {alert_priority_label(group)}"
        )
    elif normalized_event_type in {
            "responder_requested",
            "incident_responder_requested",
        }:
        context = context or {}

        requester = context.get("requested_by_name") or "Someone"
        target_type = context.get("target_type") or "responder"
        message = truncate_text(context.get("message"), limit=120)

        team = group.team.slug if group.team else "-"
        service = getattr(group.service, "name", None) if group.service else None

        title = f"RESPONDER REQUESTED: {format_alert_title_with_priority(group)}"

        body_parts = [
            f"{requester} requested you as {target_type.replace('_', ' ')}.",
            f"Team: {team}",
        ]

        if service:
            body_parts.append(f"Service: {service}")

        if message:
            body_parts.append(f"Message: {message}")

        body = "\n".join(body_parts)
    elif normalized_event_type in {
            "priority_changed",
            "incident_priority_changed",
        }:
        title = f"PRIORITY CHANGED: {format_alert_title_with_priority(group)}"
        body = f"Priority: {alert_priority_label(group)}"
    elif normalized_event_type in {
        "status_changed",
        "incident_status_changed",
        "acknowledged",
    }:
        title = f"STATUS CHANGED: {format_alert_title_with_priority(group)}"
        body = f"Status: {group.status or '-'}"
    elif normalized_event_type in {"resolved", "incident_resolved"}:
        title = f"RESOLVED: {format_alert_title_with_priority(group)}"
        body = group.message or "Incident has been resolved."
    elif normalized_event_type in {
        "comment_added",
        "incident_comment_added",
    }:
        context = context or {}
        author_name = context.get("author_name") or "Unknown user"
        comment_body = truncate_text(context.get("comment_body"), limit=180)

        title = f"COMMENT: {format_alert_title_with_priority(group)}"

        if comment_body:
            body = f"{author_name}: {comment_body}"
        else:
            body = f"{author_name} added a comment."
    else:
        title = format_alert_title_with_priority(group)
        body = group.message or f"Priority: {alert_priority_label(group)}"

    tag = f"incidentrelay-stakeholder-alert-group-{group.id}"

    if normalized_event_type in {
        "responder_requested",
        "incident_responder_requested",
    }:
        responder_id = (context or {}).get("responder_id")
        tag = f"incidentrelay-responder-{group.id}-{responder_id or 'request'}"

    return {
        "title": title,
        "body": body,
        "alert_id": group.id,
        "alert_group_id": group.id,
        "alert_title": group.title,
        "status": group.status,
        "severity": group.severity,
        "priority": getattr(group, "priority_slug", None) or "p3",
        "priority_label": alert_priority_label(group),
        "url": build_alert_web_url(group) or f"/alerts/{group.id}",
        "tag": tag,
        "require_interaction": True,
        "renotify": True,
        "silent": False,
        "vibrate": [300, 100, 300],
        "event_type": event_type,
        "action_tokens": {},
    }


def send_stakeholder_push_to_user(
    user,
    group,
    event_type="incident_created",
    context=None,
):
    """Send informational browser push notification to a stakeholder user."""
    if not Config.BROWSER_PUSH_ENABLED:
        return 0

    if not user:
        return 0

    subscriptions = _active_user_subscriptions(user.id)

    if not subscriptions:
        return 0

    payload = build_stakeholder_alert_push_payload(
        group,
        event_type=event_type,
        context=context,
    )

    sent = 0

    for subscription in subscriptions:
        try:
            _webpush(subscription, payload)
            subscription.last_seen_at = datetime.utcnow()
            subscription.save()
            sent += 1
        except WebPushException as exc:
            status_code = getattr(
                getattr(exc, "response", None),
                "status_code",
                None,
            )

            if status_code in {404, 410}:
                subscription.enabled = False
                subscription.deleted = True
                subscription.deleted_at = datetime.utcnow()
                subscription.updated_at = datetime.utcnow()
                subscription.save()

            logger.warning(
                "stakeholder browser push failed",
                extra={
                    "extra": {
                        "event_type": "stakeholder_browser_push_failed",
                        "user_id": user.id,
                        "subscription_id": subscription.id,
                        "status_code": status_code,
                        "error": str(exc),
                    }
                },
            )

    return sent


def send_test_push(user):
    payload = {
        "title": "IncidentRelay test push",
        "body": "Browser push notifications are enabled for this device.",
        "url": "/profile",
        "tag": "incidentrelay-test-push",
        "require_interaction": True,
        "renotify": True,
        "silent": False,
        "action_tokens": {},
    }

    sent = 0

    for subscription in _active_user_subscriptions(user.id):
        try:
            _webpush(subscription, payload)
            subscription.last_seen_at = datetime.utcnow()
            subscription.save()
            sent += 1
        except WebPushException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)

            if status_code in {404, 410}:
                subscription.enabled = False
                subscription.deleted = True
                subscription.deleted_at = datetime.utcnow()
                subscription.updated_at = datetime.utcnow()
                subscription.save()

            logger.warning(
                "browser push test failed",
                extra={
                    "extra": {
                        "event_type": "browser_push_test_failed",
                        "user_id": user.id,
                        "subscription_id": subscription.id,
                        "status_code": status_code,
                        "error": str(exc),
                    }
                },
            )

    return sent


def execute_push_action(token, action):
    if action not in {"ack", "resolve"}:
        return {"ok": False, "error": "invalid_action"}

    if not token:
        return {"ok": False, "error": "missing_token"}

    token_hash = _hash_token(token)
    now = datetime.utcnow()

    record = BrowserPushActionToken.get_or_none(
        BrowserPushActionToken.token_hash == token_hash
    )

    if not record:
        return {"ok": False, "error": "invalid_token"}

    if record.used_at:
        return {"ok": False, "error": "token_already_used"}

    if record.expires_at < now:
        return {"ok": False, "error": "token_expired"}

    if record.action != action:
        return {"ok": False, "error": "action_mismatch"}

    with db.atomic():
        updated = (
            BrowserPushActionToken
            .update(used_at=now)
            .where(
                BrowserPushActionToken.id == record.id,
                BrowserPushActionToken.used_at.is_null(True),
                BrowserPushActionToken.expires_at >= now,
                BrowserPushActionToken.action == action,
            )
            .execute()
        )

        if updated != 1:
            return {"ok": False, "error": "token_already_used"}

        group = AlertGroup.get_or_none(AlertGroup.id == record.group_id)

        if not group:
            return {"ok": False, "error": "alert_group_not_found"}

        result_group = _run_alert_push_action(
            group.id,
            user_id=record.user_id,
            action=action,
        )

    if action == "ack":
        audit_event = "alert_group.ack.browser_push"
    else:
        audit_event = "alert_group.resolve.browser_push"

    write_audit(
        audit_event,
        object_type="alert_group",
        object_id=result_group.id,
        team_id=result_group.team_id,
        user_id=record.user_id,
        data={
            "source": "browser_push",
            "action": action,
        },
    )

    return {
        "ok": True,
        "action": action,
        "alert_group_id": result_group.id,
        "alert_id": result_group.id,
        "status": result_group.status,
    }


def _run_alert_push_action(group_id, user_id, action):
    """Run alert group action from browser push."""

    from app.services.alerts.actions import acknowledge_alert, resolve_alert

    if action == "ack":
        return acknowledge_alert(group_id, user_id=user_id)

    if action == "resolve":
        return resolve_alert(group_id, user_id=user_id)

    raise ValueError(f"unsupported browser push action: {action}")


def _build_alert_push_title(alert, event_type):
    normalized_event_type = (event_type or "").lower()
    status = (alert.status or "").lower()
    title = format_alert_title_with_priority(alert)

    if normalized_event_type in {"resolved", "resolve"} or status == "resolved":
        return f"RESOLVED: {title}"
    if normalized_event_type in {"acknowledged", "ack"} or status == "acknowledged":
        return f"ACKNOWLEDGED: {title}"
    if normalized_event_type == "reminder":
        return f"REMINDER: {title}"
    if normalized_event_type == "escalation":
        return f"ESCALATION: {title}"

    severity = alert.severity or "unknown"

    return f"{severity.upper()}: {title}"


def _build_alert_push_body(alert, event_type):
    normalized_event_type = (event_type or "").lower()

    if normalized_event_type in {"resolved", "resolve"}:
        return alert.message or alert.source or "Alert has been resolved."

    if normalized_event_type in {"acknowledged", "ack"}:
        return alert.message or alert.source or "Alert has been acknowledged."

    return alert.message or alert.source or "IncidentRelay alert"
