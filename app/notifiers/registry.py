from app.notifiers.plugins import (
    DiscordNotifier,
    EmailNotifier,
    IncomingWebhookNotifier,
    MattermostNotifier,
    SlackNotifier,
    TeamsNotifier,
    TelegramNotifier,
    VoiceCallNotifier
)


NOTIFIERS = {
    "telegram": TelegramNotifier(),
    "slack": SlackNotifier(),
    "mattermost": MattermostNotifier(),
    "webhook": IncomingWebhookNotifier(),
    "discord": DiscordNotifier(),
    "teams": TeamsNotifier(),
    "email": EmailNotifier(),
    "voice_call": VoiceCallNotifier(),
}


def get_notifier(channel_type):
    """
    Return a notifier plugin by channel type.
    """

    notifier = NOTIFIERS.get(channel_type)

    if not notifier:
        raise RuntimeError(f"Unsupported channel_type: {channel_type}")

    return notifier


def list_notifier_types():
    """
    Return supported notifier types.
    """

    return sorted(NOTIFIERS.keys())
