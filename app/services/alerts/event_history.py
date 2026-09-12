"""Persistence policy for incoming alert lifecycle history events."""

from app.settings import Config


ALERT_EVENT_HISTORY_LEVELS = frozenset({"full", "initial", "disabled"})
INCOMING_ALERT_EVENT_TYPES = frozenset({"created", "updated", "resolved"})


def normalize_alert_event_history_level(value, default="full"):
    """Return a supported history level, falling back safely to full."""

    normalized = str(value or "").strip().lower()
    if normalized in ALERT_EVENT_HISTORY_LEVELS:
        return normalized

    fallback = str(default or "").strip().lower()
    if fallback in ALERT_EVENT_HISTORY_LEVELS:
        return fallback

    return "full"


def resolve_alert_event_history_level(runtime=None):
    """Resolve orchestration override first, then the global configuration."""

    override = getattr(runtime, "alert_event_history", None)
    if override not in (None, ""):
        return normalize_alert_event_history_level(override)

    return normalize_alert_event_history_level(
        getattr(Config, "ALERT_EVENT_HISTORY", "full")
    )


def should_record_incoming_alert_event(event_type, runtime=None):
    """Return whether one incoming child-alert lifecycle event should be stored.

    Unknown/non-incoming event types are deliberately preserved so this helper
    cannot accidentally suppress operational incident timeline events.
    """

    normalized_type = str(event_type or "").strip().lower()
    if normalized_type not in INCOMING_ALERT_EVENT_TYPES:
        return True

    level = resolve_alert_event_history_level(runtime)
    if level == "disabled":
        return False
    if level == "initial":
        return normalized_type == "created"
    return True


__all__ = [
    "ALERT_EVENT_HISTORY_LEVELS",
    "INCOMING_ALERT_EVENT_TYPES",
    "normalize_alert_event_history_level",
    "resolve_alert_event_history_level",
    "should_record_incoming_alert_event",
]
