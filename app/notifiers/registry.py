from app.notifiers.plugins import (
    DiscordNotifier,
    IncomingWebhookNotifier,
    TeamsNotifier,
)
from app.notifiers.mattermost.notifier import MattermostNotifier
from app.notifiers.email.notifier import EmailNotifier
from app.notifiers.telegram.notifier import TelegramNotifier
from app.notifiers.slack.notifier import SlackNotifier
from app.notifiers.types import (
    CHANNEL_TYPE_VALUES,
    DISCORD_CHANNEL,
    EMAIL_CHANNEL,
    MATTERMOST_CHANNEL,
    SLACK_CHANNEL,
    TEAMS_CHANNEL,
    TELEGRAM_CHANNEL,
    WEBHOOK_CHANNEL,
)

NOTIFIERS = {
    TELEGRAM_CHANNEL: TelegramNotifier(),
    SLACK_CHANNEL: SlackNotifier(),
    MATTERMOST_CHANNEL: MattermostNotifier(),
    WEBHOOK_CHANNEL: IncomingWebhookNotifier(),
    DISCORD_CHANNEL: DiscordNotifier(),
    TEAMS_CHANNEL: TeamsNotifier(),
    EMAIL_CHANNEL: EmailNotifier(),
}


def get_notifier(channel_type):
    """Return a notifier plugin by channel type."""
    notifier = NOTIFIERS.get(channel_type)
    if not notifier:
        raise RuntimeError(f"Unsupported channel_type: {channel_type}")
    return notifier


def list_notifier_types():
    """Return supported notifier types in UI/API order."""
    return list(CHANNEL_TYPE_VALUES)
