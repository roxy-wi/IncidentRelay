"""Helpers for safely exposing and updating channel configuration secrets."""

from copy import deepcopy


CHANNEL_SECRET_PLACEHOLDER = "__INCIDENTRELAY_SECRET__"

_CHANNEL_SECRET_KEYS = {
    "telegram": {"bot_token"},
    "slack": {"bot_token", "app_token", "signing_secret", "webhook_url"},
    "mattermost": {"bot_token", "callback_secret", "webhook_url"},
    "webhook": {"webhook_url"},
    "discord": {"webhook_url"},
    "teams": {"webhook_url"},
}


def mask_channel_config(channel_type, config):
    """Return a copy of channel config with supported secrets replaced."""
    result = deepcopy(config or {})

    for key in _CHANNEL_SECRET_KEYS.get(channel_type, set()):
        if result.get(key):
            result[key] = CHANNEL_SECRET_PLACEHOLDER

    return result


def merge_channel_config_secrets(
    channel_type,
    incoming_config,
    existing_channel_type,
    existing_config,
):
    """Replace update placeholders with values from the stored config."""
    result = deepcopy(incoming_config or {})
    existing = existing_config or {}

    for key in _CHANNEL_SECRET_KEYS.get(channel_type, set()):
        if result.get(key) != CHANNEL_SECRET_PLACEHOLDER:
            continue

        if channel_type != existing_channel_type or not existing.get(key):
            raise ValueError(
                f"channel secret placeholder for {key} has no stored value"
            )

        result[key] = existing[key]

    return result


def contains_channel_secret_placeholder(channel_type, config):
    """Return whether config contains a masked secret placeholder."""
    return any(
        (config or {}).get(key) == CHANNEL_SECRET_PLACEHOLDER
        for key in _CHANNEL_SECRET_KEYS.get(channel_type, set())
    )
