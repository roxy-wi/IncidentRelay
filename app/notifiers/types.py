"""Notification channel type constants.

Keep channel type names in one place so API schemas, OpenAPI docs,
views and notifier registry cannot drift apart.
"""

TELEGRAM_CHANNEL = "telegram"
SLACK_CHANNEL = "slack"
MATTERMOST_CHANNEL = "mattermost"
WEBHOOK_CHANNEL = "webhook"
DISCORD_CHANNEL = "discord"
TEAMS_CHANNEL = "teams"
EMAIL_CHANNEL = "email"

CHANNEL_TYPE_VALUES = (
    TELEGRAM_CHANNEL,
    SLACK_CHANNEL,
    MATTERMOST_CHANNEL,
    WEBHOOK_CHANNEL,
    DISCORD_CHANNEL,
    TEAMS_CHANNEL,
    EMAIL_CHANNEL,
)

CHANNEL_TYPE_PATTERN = r"^(telegram|slack|mattermost|webhook|discord|teams|email)$"

WEBHOOK_STYLE_CHANNELS = frozenset(
    (WEBHOOK_CHANNEL, DISCORD_CHANNEL, TEAMS_CHANNEL)
)
