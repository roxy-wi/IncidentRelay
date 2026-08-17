import hmac
import logging
from datetime import datetime

from flask import Blueprint, jsonify, request
from peewee import DoesNotExist

from app.api.schemas.integrations import (
    AlertmanagerWebhookSchema,
    AwsSnsEnvelopeSchema,
    DatadogWebhookSchema,
    GenericWebhookSchema,
    GrafanaWebhookSchema,
    LibreNMSWebhookSchema,
    RmonWebhookSchema,
    SentryWebhookSchema,
    UptimeKumaWebhookSchema,
    ZabbixWebhookSchema,
)
from app.services.serializers.alerts import serialize_alert_processing_result
from app.settings import Config
from app.modules.db import channels_repo, users_repo, alerts_repo, routes_repo
from app.services.alerts.actions import acknowledge_alert, resolve_alert
from app.services.alerts.lifecycle import upsert_alert
from app.services.integrations.auth import require_alert_token
from app.services.integrations.normalizers.registry import normalize_for_source
from app.services.integrations.normalizers.webhook import is_pagerduty_events_v2
from app.services.validation import make_error_response, validate_body
from app.notifiers.voice.loader import create_voice_provider
from app.modules.db.models import UserNotificationDelivery
from app.services.integrations.sentry import validate_sentry_route_signature
from app.services.integrations.aws_sns import (
    AwsSnsError,
    confirm_aws_sns_subscription,
    validate_aws_sns_message,
)
from app.notifiers.mattermost.actions import verify_mattermost_action_signature
from app.notifiers.slack.actions import (
    SlackActionError,
    handle_slack_action,
)
from app.modules.common import utc_now
from app.services.rbac import can_respond_team

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
    return process_incoming_alerts(
        normalize_for_source("alertmanager", payload.model_dump())
    )


@integrations_bp.route("/grafana", methods=["POST"])
@require_alert_token()
def grafana_webhook():
    """Receive alerts from Grafana Alerting."""
    payload, error = validate_body(GrafanaWebhookSchema)
    if error:
        return error

    return process_incoming_alerts(
        normalize_for_source("grafana", payload.model_dump())
    )


@integrations_bp.route("/datadog", methods=["POST"])
@require_alert_token()
def datadog_webhook():
    """Receive alerts from the Datadog Webhooks integration."""

    intake_route = getattr(request, "current_intake_route", None)

    if intake_route and intake_route.source != "datadog":
        return make_error_response(
            error="route_source_mismatch",
            message="Route source must be datadog.",
            status_code=400,
        )

    payload, error = validate_body(DatadogWebhookSchema)
    if error:
        return error

    return process_incoming_alerts(
        normalize_for_source("datadog", payload.model_dump(exclude_none=True))
    )


@integrations_bp.route("/rmon", methods=["POST"])
@require_alert_token()
def rmon_webhook():
    """Receive alerts from RMON."""

    payload, error = validate_body(RmonWebhookSchema)

    if error:
        return error

    return process_incoming_alerts(
        normalize_for_source("rmon", payload.model_dump())
    )


@integrations_bp.route("/aws-sns/<int:route_id>", methods=["POST"])
def aws_sns_webhook(route_id):
    """Receive signed Amazon SNS and CloudWatch notifications."""
    try:
        route = routes_repo.get_route(route_id)
    except DoesNotExist:
        return make_error_response(
            error="not_found",
            message="AWS SNS route was not found.",
            status_code=404,
        )

    if route.source != "aws_sns":
        return make_error_response(
            error="route_source_mismatch",
            message="Route source must be aws_sns.",
            status_code=400,
        )

    if not route.enabled or route.deleted:
        return make_error_response(
            error="route_disabled",
            message="AWS SNS route is disabled.",
            status_code=403,
        )

    if not route.team or route.team.deleted or not route.team.active:
        return make_error_response(
            error="route_team_inactive",
            message="AWS SNS route team is inactive.",
            status_code=403,
        )

    if route.team.group and (route.team.group.deleted or not route.team.group.active):
        return make_error_response(
            error="route_group_inactive",
            message="AWS SNS route group is inactive.",
            status_code=403,
        )

    payload, error = validate_body(
        AwsSnsEnvelopeSchema
    )

    if error:
        return error

    envelope = payload.model_dump(
        by_alias=True,
        exclude_none=True,
    )

    header_type = request.headers.get(
        "x-amz-sns-message-type"
    )
    header_topic_arn = request.headers.get(
        "x-amz-sns-topic-arn"
    )

    if header_type and header_type != envelope["Type"]:
        return make_error_response(
            error="aws_sns_header_mismatch",
            message=(
                "Amazon SNS message type header "
                "does not match the payload."
            ),
            status_code=400,
        )

    if (
            header_topic_arn
            and header_topic_arn != envelope["TopicArn"]
    ):
        return make_error_response(
            error="aws_sns_header_mismatch",
            message=(
                "Amazon SNS Topic ARN header "
                "does not match the payload."
            ),
            status_code=400,
        )

    integration_config = (
            route.integration_config or {}
    )
    aws_sns_config = dict(
        integration_config.get("aws_sns") or {}
    )
    expected_topic_arn = str(
        aws_sns_config.get("topic_arn") or ""
    ).strip()

    try:
        validate_aws_sns_message(
            envelope,
            expected_topic_arn,
        )

        if envelope["Type"] == (
                "SubscriptionConfirmation"
        ):
            confirm_aws_sns_subscription(
                envelope["SubscribeURL"],
                expected_topic_arn,
            )

            return jsonify({
                "status": "confirmed",
                "message_id": envelope["MessageId"],
                "topic_arn": envelope["TopicArn"],
            })

        if envelope["Type"] == (
                "UnsubscribeConfirmation"
        ):
            return jsonify({
                "status": "unsubscribed",
                "message_id": envelope["MessageId"],
                "topic_arn": envelope["TopicArn"],
            })
    except AwsSnsError as exc:
        return make_error_response(
            error=exc.code,
            message=exc.message,
            status_code=exc.status_code,
        )

    request.current_intake_route = route
    request.current_auth_type = "aws_sns_signature"

    return process_incoming_alerts(
        normalize_for_source("aws_sns", envelope)
    )


@integrations_bp.route("/zabbix", methods=["POST"])
@require_alert_token()
def zabbix_webhook():
    """
    Receive alerts from Zabbix.
    """

    payload, error = validate_body(ZabbixWebhookSchema)
    if error:
        return error
    return process_incoming_alerts(
        normalize_for_source("zabbix", payload.model_dump())
    )


def _pagerduty_events_success(dedup_key):
    """Return the standard successful Events API v2 response shape."""

    return jsonify({
        "status": "success",
        "message": "Event processed",
        "dedup_key": dedup_key,
    }), 202


def _process_pagerduty_events_v2(alert_data):
    """Process one PagerDuty Events API v2-compatible webhook event."""

    action = alert_data.get("lifecycle_action")
    dedup_key = alert_data.get("dedup_key")
    intake_route = getattr(request, "current_intake_route", None)

    if not intake_route or intake_route.source != "webhook":
        return make_error_response(
            error="route_source_mismatch",
            message="PagerDuty routing_key must belong to a webhook route.",
            status_code=400,
        )

    if action == "trigger":
        response, status_code = process_incoming_alerts([alert_data])

        if status_code >= 400:
            return response, status_code

        return _pagerduty_events_success(dedup_key)

    existing_alert = alerts_repo.find_existing_alert(
        source="webhook",
        dedup_key=dedup_key,
        route_id=intake_route.id,
    )

    if existing_alert and existing_alert.group:
        group_id = existing_alert.group.id

        if action == "acknowledge":
            acknowledge_alert(group_id)
        elif action == "resolve":
            resolve_alert(group_id)

    logging.getLogger("oncall.alerts").info(
        "PagerDuty Events API v2 lifecycle event processed",
        extra={
            "extra": {
                "event_type": "pagerduty_events_api_v2",
                "event_action": action,
                "dedup_key": dedup_key,
                "route_id": intake_route.id,
                "matched_alert_id": existing_alert.id if existing_alert else None,
                "matched_group_id": (
                    existing_alert.group.id
                    if existing_alert and existing_alert.group
                    else None
                ),
            }
        },
    )

    # PagerDuty accepts follow-up events asynchronously. Keep unknown or
    # already-resolved dedup keys as successful no-ops for compatibility.
    return _pagerduty_events_success(dedup_key)


@integrations_bp.route("/webhook", methods=["POST"])
@require_alert_token(allow_json_routing_key=True)
def generic_webhook():
    """Receive generic or PagerDuty Events API v2-compatible alerts."""

    payload, error = validate_body(GenericWebhookSchema)
    if error:
        return error

    raw_payload = payload.model_dump()
    normalized_alerts = normalize_for_source("webhook", raw_payload)

    if is_pagerduty_events_v2(raw_payload):
        return _process_pagerduty_events_v2(normalized_alerts[0])

    return process_incoming_alerts(normalized_alerts)


@integrations_bp.route("/uptime-kuma", methods=["POST"])
@require_alert_token()
def uptime_kuma_webhook():
    """Receive standard Uptime Kuma Webhook notifications."""

    intake_route = getattr(request, "current_intake_route", None)

    if intake_route and intake_route.source != "uptime_kuma":
        return make_error_response(
            error="route_source_mismatch",
            message="Route source must be uptime_kuma.",
            status_code=400,
        )

    payload, error = validate_body(UptimeKumaWebhookSchema)
    if error:
        return error

    return process_incoming_alerts(
        normalize_for_source(
            "uptime_kuma",
            payload.model_dump(exclude_none=True),
        )
    )


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
        normalize_for_source(
            "sentry",
            payload.model_dump(),
            headers=dict(request.headers),
            route_config=route.integration_config or {},
        )
    )


@integrations_bp.route("/librenms", methods=["POST"])
@require_alert_token()
def librenms_webhook():
    """Receive alerts from LibreNMS API transport."""
    payload, error = validate_body(LibreNMSWebhookSchema)

    if error:
        return error

    return process_incoming_alerts(
        normalize_for_source("librenms", payload.model_dump())
    )


def process_incoming_alerts(normalized_alerts):
    """
    Store normalized alerts and return created, updated, ignored or failed records.

    Routing decisions are intentionally delegated to upsert_alert(), because
    upsert_alert() creates an explain trace for both successful and stopped
    processing paths.
    """
    items = []
    intake_route = getattr(request, "current_intake_route", None)

    for alert_data in normalized_alerts:
        if intake_route:
            # The route intake token is the routing boundary.
            # Alerts submitted with this token are forced to this route,
            # which already defines team, rotation and notification channels.
            alert_data["forced_route_id"] = intake_route.id
            alert_data["forced_team_id"] = intake_route.team.id
            alert_data["team_slug"] = intake_route.team.slug

        result = upsert_alert(alert_data)

        item = serialize_alert_processing_result(
            result,
            status=alert_data.get("status") or "firing",
            routing_error=alert_data.get("routing_error"),
        )

        items.append(item)

    logging.getLogger("oncall.alerts").info(
        "incoming alerts processed",
        extra={
            "extra": {
                "event_type": "alert_intake",
                "source": normalized_alerts[0].get("source") if normalized_alerts else None,
                "alerts_count": len(normalized_alerts),
                "route_id": intake_route.id if intake_route else None,
                "team_id": intake_route.team.id if intake_route else None,
                "results": items,
            }
        },
    )

    return jsonify(items), _incoming_alerts_status_code(items)


def _incoming_alerts_status_code(items):
    if not items:
        return 200

    has_group = any(item.get("group_id") for item in items)

    has_failure = any(
        item.get("processing_status") == "failed"
        or item.get("outcome") == "routing_failed"
        for item in items
    )

    has_stopped = any(
        item.get("processing_status") == "stopped"
        for item in items
    )

    if has_failure and has_group:
        return 207

    if has_failure:
        return 400

    if has_stopped and not has_group:
        return 202

    return 200


@integrations_bp.route("/mattermost/actions", methods=["POST"])
def mattermost_action():
    """Handle authenticated and authorized Mattermost alert actions."""

    payload = request.json or {}
    context = payload.get("context") or {}
    alert_id = context.get("alert_id")
    channel_id = context.get("channel_id")
    action = context.get("action")
    signature = context.get("signature")

    if not alert_id or not channel_id or action not in {"acknowledge", "resolve"}:
        return jsonify({"ephemeral_text": "Invalid action payload"}), 400

    try:
        channel = channels_repo.get_channel(int(channel_id))
        alert_group = alerts_repo.get_alert_group(int(alert_id))
    except (DoesNotExist, TypeError, ValueError):
        return jsonify({"ephemeral_text": "Action rejected"}), 403

    config = channel.config or {}
    signing_secret = config.get("callback_secret") or Config.MATTERMOST_ACTION_SECRET

    if not verify_mattermost_action_signature(
        signing_secret,
        signature,
        action,
        alert_id,
        channel_id,
    ):
        return jsonify({"ephemeral_text": "Action rejected"}), 403

    if (
        not alert_group.team_id
        or not channel.team_id
        or int(channel.team_id) != int(alert_group.team_id)
    ):
        return jsonify({"ephemeral_text": "Action rejected"}), 403

    mattermost_user_id = str(payload.get("user_id") or "").strip()
    user = users_repo.get_user_by_mattermost_id(mattermost_user_id)

    if not user or not can_respond_team(user, alert_group.team_id):
        return jsonify({"ephemeral_text": "Action rejected"}), 403

    if action == "acknowledge":
        alert = acknowledge_alert(int(alert_id), user_id=user.id)
        return jsonify({
            "ephemeral_text": f"Alert #{alert.id} acknowledged",
            "skip_slack_parsing": True,
        })

    alert = resolve_alert(int(alert_id), user_id=user.id)
    return jsonify({
        "ephemeral_text": f"Alert #{alert.id} resolved",
        "skip_slack_parsing": True,
    })


@integrations_bp.route("/slack/actions", methods=["POST"])
def slack_action():
    """Handle Slack Block Kit alert actions."""
    raw_body = request.get_data(cache=True)

    try:
        result = handle_slack_action(
            raw_body=raw_body,
            timestamp=request.headers.get(
                "X-Slack-Request-Timestamp"
            ),
            signature=request.headers.get(
                "X-Slack-Signature"
            ),
        )
    except SlackActionError as exc:
        return jsonify(
            {
                "error": exc.error,
                "message": exc.message,
            }
        ), exc.status_code

    return jsonify(result)


@integrations_bp.route("/voice/rule-callback/<int:delivery_id>", methods=["POST"])
def voice_rule_callback(delivery_id):
    """Handle voice callbacks without placing credentials in the URL."""
    expected_secret = str(Config.VOICE_CALLBACK_SECRET or "")
    authorization = str(request.headers.get("Authorization") or "")
    provided_secret = (
        authorization[7:]
        if authorization.startswith("Bearer ")
        else str(request.headers.get("X-IncidentRelay-Callback-Secret") or "")
    )

    if (
        not expected_secret
        or not provided_secret
        or not hmac.compare_digest(provided_secret, expected_secret)
    ):
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
    delivery.updated_at = utc_now()
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
