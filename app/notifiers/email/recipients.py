"""Recipient selection for route-attached Email notification channels.

The channel only selects a recipient; SMTP credentials remain global. Keep
recipient configuration strict: a single mailbox, not a display name, list or
header fragment, is accepted. The test action always targets its actor.
"""

from email_validator import EmailNotValidError, validate_email

EMAIL_RECIPIENT_MODES = ("assignee", "fallback", "fixed")


def normalize_email_recipient_config(config):
    """Validate and normalize recipient fields on channel create/update.

    Missing mode remains missing, preserving historical empty JSON configs.
    An assignee-only channel never retains an unused old fixed recipient.
    """
    mode = config.get("recipient_mode", "assignee")
    if not isinstance(mode, str) or mode not in EMAIL_RECIPIENT_MODES:
        raise ValueError("email recipient_mode must be assignee, fallback or fixed")

    if mode == "assignee":
        config.pop("recipient_mode", None)
        config.pop("recipient_email", None)
        return config

    value = config.get("recipient_email")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("email recipient_email is required for fallback and fixed modes")
    try:
        # Do not query DNS during request validation. SMTP delivery is handled
        # by the existing notifier; configuration is a syntactic check only.
        normalized = validate_email(value.strip(), check_deliverability=False).normalized
    except EmailNotValidError as exc:
        raise ValueError("email recipient_email must be one valid mailbox address") from exc

    config["recipient_mode"] = mode
    config["recipient_email"] = normalized
    return config


def resolve_email_channel_recipient(config, assignee_email, *, is_test=False):
    """Return ``(recipient_email, source)`` without leaking the email into logs.

    A channel test intentionally bypasses a fixed/fallback recipient so that
    clicking Test never sends an unexpected message to a shared mailbox.
    """
    email = str(assignee_email or "").strip()
    if is_test:
        if not email:
            raise RuntimeError("email test recipient is missing: set email in your profile")
        return email, "test_user.email"

    settings = normalize_email_recipient_config(dict(config or {}))
    mode = settings.get("recipient_mode", "assignee")
    if mode == "fixed":
        return settings["recipient_email"], "channel.fixed_recipient"
    if email:
        return email, "assignee.email"
    if mode == "fallback":
        return settings["recipient_email"], "channel.fallback_recipient"
    raise RuntimeError("email notification recipient is missing: assignee has no email address")
