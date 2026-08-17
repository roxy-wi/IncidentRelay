"""Signing helpers for Mattermost interactive alert actions."""

import hashlib
import hmac


ALLOWED_MATTERMOST_ACTIONS = {"acknowledge", "resolve"}


def _action_payload(action, alert_id, channel_id):
    action = str(action or "").strip()
    if action not in ALLOWED_MATTERMOST_ACTIONS:
        raise ValueError(f"unsupported Mattermost action: {action}")
    return f"ir:mm:{action}:{int(alert_id)}:{int(channel_id)}"


def build_mattermost_action_signature(secret, action, alert_id, channel_id):
    """Return an HMAC signature without exposing the signing secret."""
    secret = str(secret or "")
    if not secret:
        raise ValueError("Mattermost action signing secret is missing")

    payload = _action_payload(action, alert_id, channel_id)
    return hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_mattermost_action_signature(
    secret,
    signature,
    action,
    alert_id,
    channel_id,
):
    """Return True when a Mattermost callback signature is authentic."""
    if not secret or not signature:
        return False

    try:
        expected = build_mattermost_action_signature(
            secret,
            action,
            alert_id,
            channel_id,
        )
    except (TypeError, ValueError):
        return False

    return hmac.compare_digest(str(signature), expected)
