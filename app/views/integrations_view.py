import logging

from flask import Blueprint, jsonify, request

from app.api.schemas.integrations import AlertmanagerWebhookSchema, GenericWebhookSchema, ZabbixWebhookSchema
from app.settings import Config
from app.modules.db import channels_repo, users_repo
from app.services.alerts import acknowledge_alert, resolve_alert, upsert_alert
from app.services.auth import require_alert_token
from app.services.normalizers import normalize_alertmanager, normalize_webhook, normalize_zabbix
from app.services.validation import validate_body


integrations_bp = Blueprint("integrations_api", __name__)


@integrations_bp.route("/alertmanager", methods=["POST"])
@require_alert_token(required=Config.WEBHOOK_AUTH_REQUIRED)
def alertmanager_webhook():
    """
    Receive alerts from Prometheus Alertmanager.
    """

    payload, error = validate_body(AlertmanagerWebhookSchema)
    if error:
        return error
    return process_incoming_alerts(normalize_alertmanager(payload.model_dump()))


@integrations_bp.route("/zabbix", methods=["POST"])
@require_alert_token(required=Config.WEBHOOK_AUTH_REQUIRED)
def zabbix_webhook():
    """
    Receive alerts from Zabbix.
    """

    payload, error = validate_body(ZabbixWebhookSchema)
    if error:
        return error
    return process_incoming_alerts(normalize_zabbix(payload.model_dump()))


@integrations_bp.route("/webhook", methods=["POST"])
@require_alert_token(required=Config.WEBHOOK_AUTH_REQUIRED)
def generic_webhook():
    """
    Receive alerts from a generic webhook.
    """

    payload, error = validate_body(GenericWebhookSchema)
    if error:
        return error
    return process_incoming_alerts(normalize_webhook(payload.model_dump()))


def process_incoming_alerts(normalized_alerts):
    """
    Store normalized alerts and return created or updated records.
    """

    result = []

    intake_route = getattr(request, "current_intake_route", None)

    for alert_data in normalized_alerts:
        if intake_route:
            # The route intake token is the routing boundary. Alerts submitted
            # with this token are forced to this route, which already defines
            # team, rotation and notification channels.
            alert_data["forced_route_id"] = intake_route.id
            alert_data["forced_team_id"] = intake_route.team.id
            alert_data["team_slug"] = intake_route.team.slug

        alert, created = upsert_alert(alert_data)
        result.append({
            "id": alert.id,
            "team_id": alert.team.id if alert.team else None,
            "team_slug": alert.team.slug if alert.team else None,
            "route_id": alert.route.id if alert.route else None,
            "rotation_id": alert.rotation.id if alert.rotation else None,
            "routing_error": alert_data.get("routing_error"),
            "created": created,
            "status": alert.status,
            "assignee": alert.assignee.username if alert.assignee else None,
        })

    logging.getLogger("oncall.alerts").info(
        "incoming alerts processed",
        extra={
            "extra": {
                "event_type": "alert_intake",
                "source": normalized_alerts[0]["source"] if normalized_alerts else None,
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
