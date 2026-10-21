import logging

from datetime import timedelta

from app import Config
from app.modules.db import rotations_repo
from app.modules.db.models import (
    OnCallShiftEmailNotification,
    OnCallShiftMattermostNotification,
    Rotation,
    User,
)
from app.modules.smtp import send_plain_email
from app.notifiers.registry import get_notifier
from app.notifiers.types import MATTERMOST_CHANNEL
from app.services.calendar_service import build_rotation_calendar
from app.services.rotation_schedule import layer_duration_seconds
from app.modules.common import as_utc_naive, utc_now

logger = logging.getLogger("oncall.shift_notifications")


SHIFT_START = "shift_start"
SHIFT_END = "shift_end"


def _display_name(user):
    return user.display_name or user.username or f"user #{user.id}"


def _team_display_name(event):
    return event.get("team_name") or event.get("team_slug") or "-"


def _format_dt(value):
    return value.strftime("%Y-%m-%d %H:%M:%S UTC")


def _notification_fingerprint(event, event_type):
    """Deduplicate shift notifications by transition point."""
    if event_type == SHIFT_START:
        transition_at = event.get("start")
    elif event_type == SHIFT_END:
        transition_at = event.get("end")
    else:
        transition_at = event.get("start")

    return ":".join(
        [
            event_type,
            str(event.get("rotation_id")),
            str(event.get("user_id")),
            str(transition_at),
        ]
    )


def _mattermost_notification_fingerprint(event, event_type, mattermost_user_id):
    """Deduplicate personal Mattermost shift notifications."""
    return ":".join(
        [
            "mattermost",
            str(mattermost_user_id),
            _notification_fingerprint(event, event_type),
        ]
    )


def _send_plain_email(to_email, subject, body):
    # Reuse the shared SMTP transport (app.modules.smtp) so on-call shift emails
    # validate configuration and handle STARTTLS/AUTH/timeouts exactly like the
    # alert email channel and the incident participant notifications, instead of
    # maintaining a second, slightly divergent smtplib sequence here.
    send_plain_email(to_email, subject, body)


def _build_shift_email(user, event, event_type):
    name = _display_name(user)
    rotation_name = event.get("rotation_name") or f"Rotation #{event.get('rotation_id')}"
    team_name = _team_display_name(event)
    layer_name = event.get("layer_name") or "Override" if event.get("type") == "override" else "-"
    start_at = as_utc_naive(event["start"])
    end_at = as_utc_naive(event["end"])

    if event_type == SHIFT_START:
        subject = f"[On-call] Your shift has started: {rotation_name}"
        title = "Your on-call shift has started."
    else:
        subject = f"[On-call] Your shift has ended: {rotation_name}"
        title = "Your on-call shift has ended."

    lines = [
        f"Hello {name},",
        "",
        title,
        "",
        f"Team: {team_name}",
        f"Rotation: {rotation_name}",
        f"Layer: {layer_name}",
        f"Starts at: {_format_dt(start_at)}",
        f"Ends at: {_format_dt(end_at)}",
        "",
        "This notification can be disabled in your IncidentRelay profile.",
    ]

    return subject, "\n".join(lines)


def _user_wants_email(user, event_type):
    if event_type == SHIFT_START:
        return getattr(user, "notify_oncall_shift_start_email", True) is not False

    if event_type == SHIFT_END:
        return getattr(user, "notify_oncall_shift_end_email", True) is not False

    return False


def _get_or_create_log(user, rotation, event, event_type):
    fingerprint = _notification_fingerprint(event, event_type)

    log, created = OnCallShiftEmailNotification.get_or_create(
        fingerprint=fingerprint,
        defaults={
            "user": user,
            "rotation": rotation,
            "event_type": event_type,
            "slot_start_at": as_utc_naive(event["start"]),
            "slot_end_at": as_utc_naive(event["end"]),
            "layer_id": event.get("layer_id"),
            "override_id": event.get("override_id"),
            "status": "pending",
            "created_at": utc_now(),
            "updated_at": utc_now(),
        },
    )

    return log, created


def _mark_log(log, status, error=None):
    log.status = status
    log.last_error = error
    log.updated_at = utc_now()

    if status == "sent":
        log.sent_at = utc_now()

    log.save()


def _get_or_create_mattermost_log(user, rotation, event, event_type):
    mattermost_user_id = str(user.mattermost_user_id or "").strip()
    fingerprint = _mattermost_notification_fingerprint(
        event,
        event_type,
        mattermost_user_id,
    )

    log, created = OnCallShiftMattermostNotification.get_or_create(
        fingerprint=fingerprint,
        defaults={
            "user": user,
            "rotation": rotation,
            "event_type": event_type,
            "slot_start_at": as_utc_naive(event["start"]),
            "slot_end_at": as_utc_naive(event["end"]),
            "layer_id": event.get("layer_id"),
            "override_id": event.get("override_id"),
            "mattermost_user_id": mattermost_user_id,
            "status": "pending",
            "created_at": utc_now(),
            "updated_at": utc_now(),
        },
    )

    return log, created


def _send_shift_event_to_mattermost(event, event_type):
    if event_type != SHIFT_START:
        return False

    if not getattr(Config, "ONCALL_SHIFT_MATTERMOST_ENABLED", True):
        return False

    if not getattr(Config, "MATTERMOST_API_URL", "") or not getattr(Config, "MATTERMOST_BOT_TOKEN", ""):
        return False

    user_id = event.get("user_id")
    rotation_id = event.get("rotation_id")

    if not user_id or not rotation_id:
        return False

    try:
        user = User.get_by_id(user_id)
        rotation = Rotation.get_by_id(rotation_id)
    except Exception:
        return False

    if not user.active or user.deleted:
        return False

    if not str(user.mattermost_user_id or "").strip():
        return False

    if getattr(user, "notify_oncall_shift_start_mattermost", True) is False:
        return False

    log, _created = _get_or_create_mattermost_log(
        user,
        rotation,
        event,
        event_type,
    )

    if log.status == "sent":
        return False

    try:
        notifier = get_notifier(MATTERMOST_CHANNEL)
        notifier.send_direct_shift_notification(
            user=user,
            event=event,
            event_type=event_type,
            rotation=rotation,
        )
        _mark_log(log, "sent")
        return True
    except Exception as exc:
        logger.exception(
            "on-call shift Mattermost direct notification failed",
            extra={
                "extra": {
                    "event_type": "shift_mattermost",
                    "shift_event_type": event_type,
                    "user_id": user.id,
                    "rotation_id": rotation.id,
                }
            },
        )
        _mark_log(log, "failed", str(exc))
        return False


def _send_shift_event(event, event_type):
    user_id = event.get("user_id")
    rotation_id = event.get("rotation_id")

    if not user_id or not rotation_id:
        return False

    try:
        user = User.get_by_id(user_id)
        rotation = Rotation.get_by_id(rotation_id)
    except Exception:
        return False

    if not user.active or user.deleted:
        return False

    if not user.email:
        return False

    if not _user_wants_email(user, event_type):
        return False

    log, _created = _get_or_create_log(user, rotation, event, event_type)

    if log.status == "sent":
        return False

    try:
        subject, body = _build_shift_email(user, event, event_type)
        _send_plain_email(user.email, subject, body)
        _mark_log(log, "sent")
        return True
    except Exception as exc:
        logger.exception(
            "on-call shift email failed",
            extra={
                "extra": {
                    "event_type": "shift_email",
                    "shift_event_type": event_type,
                    "user_id": user.id,
                    "rotation_id": rotation.id,
                }
            },
        )
        _mark_log(log, "failed", str(exc))
        return False


def _event_due(event, event_type, window_start, now):
    start_at = as_utc_naive(event["start"])
    end_at = as_utc_naive(event["end"])

    if event_type == SHIFT_START:
        return window_start < start_at <= now

    if event_type == SHIFT_END:
        return window_start < end_at <= now

    return False


def _shift_calendar_context(rotation, transition_start, transition_end):
    """Build an unclipped context around due shift transitions.

    Calendar events are clipped to their query boundaries. Querying only the
    scheduler lookback corrupts the *opposite* end of a shift (including
    persisted notification log fields). Extend by at least a whole slot on
    either side. Keep the narrow transition window for deciding what is due.

    Long overrides may be wider than the rotation's normal slot, so their
    actual endpoints must also fit in the context.
    """
    layers = rotations_repo.list_rotation_layers(rotation.id, enabled_only=True)
    slot_seconds = max(
        [86400, int(rotation.duration_seconds or 86400)]
        + [layer_duration_seconds(layer) for layer in layers]
    )
    margin = timedelta(seconds=slot_seconds * 2 + 86400)
    start_at = transition_start - margin
    end_at = transition_end + margin

    # An override may span multiple regular shifts. Include its true edges
    # rather than reporting the artificial context boundary as its end.
    for override in rotations_repo.list_rotation_overrides(
        rotation.id, transition_start, transition_end
    ):
        start_at = min(start_at, as_utc_naive(override.starts_at) - timedelta(seconds=1))
        end_at = max(end_at, as_utc_naive(override.ends_at) + timedelta(seconds=1))

    return start_at, end_at


def _shift_transition_events(rotation, window_start, window_end):
    """Return calendar slices with genuine boundaries around the due window."""
    start_at, end_at = _shift_calendar_context(rotation, window_start, window_end)
    return build_rotation_calendar(rotation, start_at, end_at)


def send_due_oncall_shift_email_notifications(now=None, lookback_seconds=None):
    """
    Send email notifications for shifts that started or ended recently.

    The scheduler runs periodically, so this job looks back a small window
    and uses OnCallShiftEmailNotification.fingerprint to avoid duplicates.
    """
    now = now or utc_now()

    if lookback_seconds is None:
        lookback_seconds = int(
            getattr(
                Config,
                "ONCALL_SHIFT_EMAIL_LOOKBACK_SECONDS",
                max(int(getattr(Config, "REMINDER_INTERVAL_SECONDS", 300)) * 2, 300),
            )
        )

    window_start = now - timedelta(seconds=lookback_seconds)
    window_end = now + timedelta(seconds=1)

    sent = 0

    rotations = (
        Rotation
        .select()
        .where(
            Rotation.enabled == True,
            Rotation.deleted == False,
        )
    )

    for rotation in rotations:
        events = _shift_transition_events(rotation, window_start, window_end)

        for event in events:
            if _event_due(event, SHIFT_START, window_start, now):
                if _send_shift_event(event, SHIFT_START):
                    sent += 1

            if _event_due(event, SHIFT_END, window_start, now):
                if _send_shift_event(event, SHIFT_END):
                    sent += 1

    return sent


def send_due_oncall_shift_mattermost_notifications(now=None, lookback_seconds=None):
    """
    Send personal Mattermost notifications for shifts that started recently.

    The notification is sent to the user's Mattermost DM when
    User.mattermost_user_id is set. End-of-shift messages are intentionally
    not sent to avoid noisy direct messages.
    """
    now = now or utc_now()

    if lookback_seconds is None:
        lookback_seconds = int(
            getattr(
                Config,
                "ONCALL_SHIFT_MATTERMOST_LOOKBACK_SECONDS",
                max(int(getattr(Config, "REMINDER_INTERVAL_SECONDS", 300)) * 2, 300),
            )
        )

    window_start = now - timedelta(seconds=lookback_seconds)
    window_end = now + timedelta(seconds=1)

    sent = 0

    rotations = (
        Rotation
        .select()
        .where(
            Rotation.enabled == True,
            Rotation.deleted == False,
        )
    )

    for rotation in rotations:
        events = _shift_transition_events(rotation, window_start, window_end)

        for event in events:
            if _event_due(event, SHIFT_START, window_start, now):
                if _send_shift_event_to_mattermost(event, SHIFT_START):
                    sent += 1

    return sent
