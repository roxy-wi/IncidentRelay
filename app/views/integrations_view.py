import logging
from datetime import datetime

from flask import Blueprint, jsonify, request
from peewee import DoesNotExist

from app.api.schemas.integrations import (
    AlertmanagerWebhookSchema,
    GenericWebhookSchema,
    SentryWebhookSchema,
    ZabbixWebhookSchema,
)
from app.settings import Config
from app.modules.db import channels_repo, users_repo, alerts_repo, routes_repo
from app.services.alerts.actions import acknowledge_alert, resolve_alert
from app.services.alerts.lifecycle import upsert_alert
from app.services.integrations.auth import require_alert_token
from app.services.integrations.normalizers.sentry import normalize_sentry
from app.services.integrations.normalizers.webhook import normalize_webhook
from app.services.integrations.normalizers.zabbix import normalize_zabbix
from app.services.integrations.normalizers.alertmanager import normalize_alertmanager
from app.services.validation import validate_body
from app.notifiers.voice.loader import create_voice_provider
from app.services.routing.routing import find_route_for_alert
from app.modules.db.models import UserNotificationDelivery
from app.services.integrations.sentry import validate_sentry_route_signature

integrations_bp = Blueprint("integrations_api", __name__)


@integrations_bp.route("/alertmanager", methods=["POST"])
@require_alert_token()
def alertmanager_webhook():
    """
    Receive alerts from Prometheus Alertmanager.
    """

    payload, error = validate_body(AlertmanagerWebhookSchema)
    if error:
        return error
    return process_incoming_alerts(normalize_alertmanager(payload.model_dump()))


@integrations_bp.route("/zabbix", methods=["POST"])
@require_alert_token()
def zabbix_webhook():
    """
    Receive alerts from Zabbix.
    """

    payload, error = validate_body(ZabbixWebhookSchema)
    if error:
        return error
    return process_incoming_alerts(normalize_zabbix(payload.model_dump()))


@integrations_bp.route("/webhook", methods=["POST"])
@require_alert_token()
def generic_webhook():
    """
    Receive alerts from a generic webhook.
    """

    payload, error = validate_body(GenericWebhookSchema)
    if error:
        return error
    return process_incoming_alerts(normalize_webhook(payload.model_dump()))


@integrations_bp.route("/sentry/<int:route_id>", methods=["POST"])
def sentry_webhook(route_id):
    """Receive signed webhooks from Sentry Internal Integration."""
    try:
        route = routes_repo.get_route(route_id)
    except DoesNotExist:
        return jsonify({
            "error": "route_not_found",
            "message": "Sentry route was not found",
        }), 404

    if route.source != "sentry":
        return jsonify({
            "error": "route_source_mismatch",
            "message": "Route source must be sentry",
        }), 400

    if not route.enabled or route.deleted:
        return jsonify({
            "error": "route_disabled",
            "message": "Sentry route is disabled",
        }), 403

    if not route.team or route.team.deleted or not route.team.active:
        return jsonify({
            "error": "route_team_inactive",
            "message": "Sentry route team is inactive",
        }), 403

    if route.team.group and (
        route.team.group.deleted or not route.team.group.active
    ):
        return jsonify({
            "error": "route_group_inactive",
            "message": "Sentry route group is inactive",
        }), 403

    raw_body = request.get_data(cache=True)

    signature_error, status_code = validate_sentry_route_signature(
        route,
        raw_body,
        request.headers,
    )

    if signature_error:
        return jsonify(signature_error), status_code

    payload, error = validate_body(SentryWebhookSchema)
    if error:
        return error

    request.current_intake_route = route
    request.current_auth_type = "sentry_signature"

    return process_incoming_alerts(
        normalize_sentry(
            payload.model_dump(),
            headers=dict(request.headers),
        )
    )


def process_incoming_alerts(normalized_alerts):
    """
    Store normalized alerts and return created or updated records.
    """
    result = []
    routing_errors = []
    intake_route = getattr(request, "current_intake_route", None)

    for index, alert_data in enumerate(normalized_alerts):
        if intake_route:
            # The route intake token is the routing boundary.
            # Alerts submitted with this token are forced to this route,
            # which already defines team, rotation and notification channels.
            alert_data["forced_route_id"] = intake_route.id
            alert_data["forced_team_id"] = intake_route.team.id
            alert_data["team_slug"] = intake_route.team.slug

        route = find_route_for_alert(alert_data)

        if not route:
            routing_errors.append(
                {
                    "index": index,
                    "source": alert_data.get("source"),
                    "team_slug": alert_data.get("team_slug"),
                    "title": alert_data.get("title"),
                    "dedup_key": alert_data.get("dedup_key"),
                    "routing_error": alert_data.get("routing_error")
                    or "no enabled route matched alert labels",
                }
            )

    if routing_errors:
        logging.getLogger("oncall.alerts").warning(
            "incoming alerts rejected by routing",
            extra={
                "extra": {
                    "event_type": "alert_intake_routing_error",
                    "source": normalized_alerts[0].get("source") if normalized_alerts else None,
                    "alerts_count": len(normalized_alerts),
                    "errors": routing_errors,
                    "route_id": intake_route.id if intake_route else None,
                    "team_id": intake_route.team.id if intake_route else None,
                }
            },
        )

        return jsonify(
            {
                "error": "routing_error",
                "message": "Alert routing failed",
                "details": routing_errors,
            }
        ), 400

    for alert_data in normalized_alerts:
        alert, created = upsert_alert(alert_data)

        if alert is None:
            return jsonify(
                {
                    "status": "ignored",
                    "reason": "orphan_resolved",
                }
            ), 202

        result.append(
            {
                "id": alert.id,
                "team_id": alert.team.id if alert.team else None,
                "team_slug": alert.team.slug if alert.team else None,
                "route_id": alert.route.id if alert.route else None,
                "rotation_id": alert.rotation.id if alert.rotation else None,
                "routing_error": alert_data.get("routing_error"),
                "created": created,
                "status": alert.status,
                "assignee": alert.assignee.username if alert.assignee else None,
            }
        )

    logging.getLogger("oncall.alerts").info(
        "incoming alerts processed",
        extra={
            "extra": {
                "event_type": "alert_intake",
                "source": normalized_alerts[0].get("source") if normalized_alerts else None,
                "alerts_count": len(normalized_alerts),
                "route_id": intake_route.id if intake_route else None,
                "team_id": intake_route.team.id if intake_route else None,
                "results": result,
            }
        },
    )

    return jsonify(result)


@integrations_bp.route("/mattermost/actions", methods=["POST"])
def mattermost_action():
    """
    Handle Mattermost interactive message button callbacks.
    """

    payload = request.json or {}
    context = payload.get("context") or {}
    alert_id = context.get("alert_id")
    channel_id = context.get("channel_id")
    action = context.get("action")
    secret = context.get("secret")

    if not alert_id or not channel_id or action not in {"acknowledge", "resolve"}:
        return jsonify({"ephemeral_text": "Invalid action payload"}), 400

    channel = channels_repo.get_channel(int(channel_id))
    config = channel.config or {}
    expected_secret = config.get("callback_secret") or Config.MATTERMOST_ACTION_SECRET

    if secret != expected_secret:
        return jsonify({"ephemeral_text": "Action rejected"}), 403

    mattermost_user_id = payload.get("user_id")
    user = users_repo.get_user_by_mattermost_id(mattermost_user_id)
    user_id = user.id if user else None

    if action == "acknowledge":
        alert = acknowledge_alert(int(alert_id), user_id=user_id)
        return jsonify({
            "ephemeral_text": f"Alert #{alert.id} acknowledged",
            "skip_slack_parsing": True,
        })

    alert = resolve_alert(int(alert_id), user_id=user_id)
    return jsonify({
        "ephemeral_text": f"Alert #{alert.id} resolved",
        "skip_slack_parsing": True,
    })


@integrations_bp.route("/voice/rule-callback/<int:delivery_id>/<secret>", methods=["POST"])
def voice_rule_callback(delivery_id, secret):
    """Handle voice callbacks for user notification rules."""
    expected_secret = Config.VOICE_CALLBACK_SECRET

    if not expected_secret or secret != expected_secret:
        return jsonify({"error": "voice callback rejected"}), 403

    delivery = UserNotificationDelivery.get_or_none(
        UserNotificationDelivery.id == delivery_id
    )

    if not delivery:
        return jsonify({"error": "notification delivery was not found"}), 404

    payload = request.get_json(silent=True)

    if payload is None:
        payload = request.form.to_dict(flat=True)

    provider = create_voice_provider(
        Config.VOICE_PROVIDER,
        Config.VOICE_PROVIDER_CONFIG,
    )

    events = provider.parse_callback(
        payload=payload or {},
        headers=dict(request.headers),
        raw_body=request.get_data(),
        query_args=request.args.to_dict(flat=True),
    )

    if not events:
        return jsonify({"status": "ignored", "events": 0})

    processed = []

    for event in events:
        processed.append(
            _process_voice_rule_callback_event(delivery, event)
        )

    return jsonify(
        {
            "status": "processed",
            "events": processed,
        }
    )


def _process_voice_rule_callback_event(delivery, event):
    delivery.provider_status = event.status
    delivery.provider_payload = event.raw
    delivery.updated_at = datetime.utcnow()
    delivery.save()

    alert = delivery.alert

    action = None

    if event.action in {"acknowledge", "resolve"}:
        action = event.action
    elif event.digit:
        action = {
            "1": "acknowledge",
            "2": "resolve",
        }.get(str(event.digit))

    alerts_repo.create_alert_event(
        alert.id,
        f"voice_{event.event_type}",
        _voice_rule_event_message(delivery, event, action),
    )

    if action == "acknowledge":
        user_id = alert.assignee.id if alert.assignee else None
        acknowledge_alert(alert.id, user_id=user_id)
    elif action == "resolve":
        user_id = alert.assignee.id if alert.assignee else None
        resolve_alert(alert.id, user_id=user_id)

    return {
        "call_id": event.call_id,
        "event_type": event.event_type,
        "status": event.status,
        "digit": event.digit,
        "action": action,
        "alert_id": alert.id,
        "delivery_id": delivery.id,
    }


def _voice_rule_event_message(delivery, event, action):
    parts = [
        f"Voice notification rule delivery #{delivery.id}",
        f"event={event.event_type}",
    ]

    if event.status:
        parts.append(f"status={event.status}")

    if event.digit:
        parts.append(f"digit={event.digit}")

    if action:
        parts.append(f"action={action}")

    return ", ".join(parts)
