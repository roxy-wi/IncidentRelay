import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs

from peewee import DoesNotExist

from app.modules.db import alerts_repo, channels_repo, users_repo
from app.notifiers.types import SLACK_CHANNEL
from app.services.alerts.actions import acknowledge_alert, resolve_alert


SLACK_SIGNATURE_VERSION = "v0"
SLACK_MAX_REQUEST_AGE_SECONDS = 300


class SlackActionError(Exception):
    """Expected error while processing a Slack interaction."""

    def __init__(
        self,
        error,
        message,
        status_code=400,
    ):
        super().__init__(message)

        self.error = error
        self.message = message
        self.status_code = status_code


def handle_slack_action(
    *,
    raw_body,
    timestamp,
    signature,
):
    """Validate and process one Slack Block Kit action."""
    payload, context, action_item = parse_slack_action_payload(
        raw_body
    )

    channel = _get_action_channel(
        context["channel_id"]
    )
    config = channel.config or {}

    validate_slack_signature(
        raw_body=raw_body,
        timestamp=timestamp,
        signature=signature,
        signing_secret=config.get("signing_secret"),
    )

    _validate_channel_config(
        channel,
        config,
        payload,
    )

    action = context["action"]
    expected_action_id = f"incidentrelay_{action}"

    if action_item.get("action_id") != expected_action_id:
        raise SlackActionError(
            "invalid_action",
            "Slack action ID does not match its context.",
        )

    alert = _get_action_alert(
        context["alert_id"]
    )

    if alert.team_id != channel.team_id:
        raise SlackActionError(
            "action_rejected",
            "Slack channel and alert belong to different teams.",
            status_code=403,
        )

    slack_user_id = (
        (payload.get("user") or {}).get("id")
    )
    user = users_repo.get_user_by_slack_id(
        slack_user_id
    )
    user_id = user.id if user else None

    if action == "acknowledge":
        alert = acknowledge_alert(
            alert.id,
            user_id=user_id,
        )
    else:
        alert = resolve_alert(
            alert.id,
            user_id=user_id,
        )

    return {
        "ok": True,
        "action": action,
        "alert_id": alert.id,
        "user_id": user_id,
    }


def parse_slack_action_payload(raw_body):
    """Parse Slack's form-encoded interaction payload."""
    if not raw_body:
        raise SlackActionError(
            "invalid_payload",
            "Slack action request body is empty.",
        )

    try:
        form_data = parse_qs(
            raw_body.decode("utf-8"),
            keep_blank_values=True,
        )
    except UnicodeDecodeError as exc:
        raise SlackActionError(
            "invalid_payload",
            "Slack action request body is not valid UTF-8.",
        ) from exc

    raw_payload_values = form_data.get("payload") or []

    if not raw_payload_values:
        raise SlackActionError(
            "invalid_payload",
            "Slack action payload is missing.",
        )

    try:
        payload = json.loads(raw_payload_values[0])
    except (TypeError, ValueError) as exc:
        raise SlackActionError(
            "invalid_payload",
            "Slack action payload is not valid JSON.",
        ) from exc

    if payload.get("type") != "block_actions":
        raise SlackActionError(
            "invalid_payload",
            "Unsupported Slack interaction type.",
        )

    actions = payload.get("actions") or []

    if len(actions) != 1:
        raise SlackActionError(
            "invalid_payload",
            "Slack action payload must contain one action.",
        )

    action_item = actions[0]
    raw_context = action_item.get("value")

    if not isinstance(raw_context, str):
        raise SlackActionError(
            "invalid_payload",
            "Slack action context is missing.",
        )

    try:
        context = json.loads(raw_context)
    except (TypeError, ValueError) as exc:
        raise SlackActionError(
            "invalid_payload",
            "Slack action context is not valid JSON.",
        ) from exc

    action = context.get("action")

    if action not in {"acknowledge", "resolve"}:
        raise SlackActionError(
            "invalid_action",
            "Unsupported Slack alert action.",
        )

    try:
        context["alert_id"] = int(
            context["alert_id"]
        )
        context["channel_id"] = int(
            context["channel_id"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SlackActionError(
            "invalid_payload",
            "Slack action alert or channel ID is invalid.",
        ) from exc

    context["action"] = action

    return payload, context, action_item


def validate_slack_signature(
    *,
    raw_body,
    timestamp,
    signature,
    signing_secret,
    now=None,
):
    """Verify Slack HMAC signature and request age."""
    if not signing_secret:
        raise SlackActionError(
            "action_rejected",
            "Slack signing secret is not configured.",
            status_code=403,
        )

    if not timestamp or not signature:
        raise SlackActionError(
            "invalid_signature",
            "Slack signature headers are missing.",
            status_code=403,
        )

    try:
        request_timestamp = int(timestamp)
    except (TypeError, ValueError) as exc:
        raise SlackActionError(
            "invalid_signature",
            "Slack request timestamp is invalid.",
            status_code=403,
        ) from exc

    current_time = int(
        time.time() if now is None else now
    )

    if (
        abs(current_time - request_timestamp)
        > SLACK_MAX_REQUEST_AGE_SECONDS
    ):
        raise SlackActionError(
            "stale_request",
            "Slack action request has expired.",
            status_code=403,
        )

    base_string = (
        f"{SLACK_SIGNATURE_VERSION}:"
        f"{timestamp}:"
    ).encode("utf-8") + raw_body

    digest = hmac.new(
        str(signing_secret).encode("utf-8"),
        base_string,
        hashlib.sha256,
    ).hexdigest()

    expected_signature = (
        f"{SLACK_SIGNATURE_VERSION}={digest}"
    )

    if not hmac.compare_digest(
        expected_signature,
        str(signature),
    ):
        raise SlackActionError(
            "invalid_signature",
            "Slack request signature is invalid.",
            status_code=403,
        )


def _get_action_channel(channel_id):
    """Load the local notification channel."""
    try:
        channel = channels_repo.get_channel(
            channel_id
        )
    except (DoesNotExist, TypeError, ValueError) as exc:
        raise SlackActionError(
            "action_rejected",
            "Slack action channel was not found.",
            status_code=403,
        ) from exc

    if channel.channel_type != SLACK_CHANNEL:
        raise SlackActionError(
            "action_rejected",
            "Action channel is not a Slack channel.",
            status_code=403,
        )

    if not channel.enabled:
        raise SlackActionError(
            "action_rejected",
            "Slack action channel is disabled.",
            status_code=403,
        )

    return channel


def _get_action_alert(alert_id):
    """Load an alert group referenced by a button."""
    try:
        return alerts_repo.get_alert_group(
            alert_id
        )
    except (DoesNotExist, TypeError, ValueError) as exc:
        raise SlackActionError(
            "alert_not_found",
            "Slack action alert was not found.",
            status_code=404,
        ) from exc


def _validate_channel_config(
    channel,
    config,
    payload,
):
    """Validate Slack channel mode and external channel ID."""
    if config.get("mode") != "bot_api":
        raise SlackActionError(
            "action_rejected",
            "Slack channel is not configured for Bot API.",
            status_code=403,
        )

    configured_channel_id = str(
        config.get("channel_id") or ""
    ).strip()

    payload_channel_id = str(
        (payload.get("channel") or {}).get("id")
        or ""
    ).strip()

    if (
        not configured_channel_id
        or payload_channel_id
        != configured_channel_id
    ):
        raise SlackActionError(
            "action_rejected",
            "Slack workspace channel does not match configuration.",
            status_code=403,
        )
