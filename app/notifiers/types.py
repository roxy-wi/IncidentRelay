"""Notification channel type constants.

Keep channel type names in one place so API schemas, OpenAPI docs,
views and notifier registry cannot drift apart.
"""

TELEGRAM_CHANNEL = "telegram"
SLACK_CHANNEL = "slack"
LARK_CHANNEL = "lark"
MATTERMOST_CHANNEL = "mattermost"
WEBHOOK_CHANNEL = "webhook"
DISCORD_CHANNEL = "discord"
TEAMS_CHANNEL = "teams"
EMAIL_CHANNEL = "email"

CHANNEL_TYPE_VALUES = (
    TELEGRAM_CHANNEL,
    SLACK_CHANNEL,
    LARK_CHANNEL,
    MATTERMOST_CHANNEL,
    WEBHOOK_CHANNEL,
    DISCORD_CHANNEL,
    TEAMS_CHANNEL,
    EMAIL_CHANNEL,
)

CHANNEL_TYPE_PATTERN = (
    r"^(telegram|slack|lark|mattermost|webhook|discord|teams|email)$"
)

WEBHOOK_STYLE_CHANNELS = frozenset(
    (WEBHOOK_CHANNEL, DISCORD_CHANNEL, TEAMS_CHANNEL)
)

# Optional Slack channel config flags controlling user mentions. Both default
# to off so an existing Slack channel keeps rendering plain display names.
SLACK_MENTION_ASSIGNEE_KEY = "mention_assignee"
SLACK_MENTION_ONCALL_KEY = "mention_oncall"

SLACK_MENTION_CONFIG_KEYS = (
    SLACK_MENTION_ASSIGNEE_KEY,
    SLACK_MENTION_ONCALL_KEY,
)
