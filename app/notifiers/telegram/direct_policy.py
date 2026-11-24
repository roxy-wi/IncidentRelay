"""Who receives a Telegram direct message, and for which alerts.

The channel post, including its buttons, is unchanged. When
``[telegram] dm_priorities`` lists priorities, the bot also writes to the
assignee in a private chat. An empty value turns direct messages off,
including escalation handoffs.

An escalation is the exception while the list is not empty: the new
assignee is messaged at any priority.
"""

from app.settings import Config


# First delivery, a repeated reminder, and a handoff to the next person.
DM_EVENT_TYPES = frozenset({"notification", "reminder", "escalation"})


def dm_priorities():
    """Return the priority slugs that page the assignee directly."""

    raw = getattr(Config, "TELEGRAM_DM_PRIORITIES", "") or ""

    return frozenset(
        item.strip().lower()
        for item in str(raw).split(",")
        if item.strip()
    )


def should_send_dm(alert, event_type):
    """Return True when this delivery must also go to the assignee."""

    if event_type not in DM_EVENT_TYPES:
        return False

    priorities = dm_priorities()

    if not priorities:
        return False

    if event_type == "escalation":
        return True

    slug = str(getattr(alert, "priority_slug", "") or "").strip().lower()
    return slug in priorities


def telegram_chat_id(user):
    """Return the private chat id (the numeric Telegram user id), or None."""

    if not user:
        return None

    telegram_id = str(getattr(user, "telegram_user_id", "") or "").strip()

    if not telegram_id.isdigit():
        return None

    return telegram_id
