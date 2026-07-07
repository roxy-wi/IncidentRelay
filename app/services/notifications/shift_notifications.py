import logging
import smtplib

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from app import Config
from app.modules.db.models import (
    OnCallShiftEmailNotification,
    OnCallShiftMattermostNotification,
    Rotation,
    User,
)
from app.notifiers.registry import get_notifier
from app.notifiers.types import MATTERMOST_CHANNEL
from app.services.calendar_service import build_rotation_calendar

logger = logging.getLogger("oncall.shift_notifications")


SHIFT_START = "shift_start"
SHIFT_END = "shift_end"


def _display_name(user):
    return user.display_name or user.username or f"user #{user.id}"


def _team_display_name(event):
    return event.get("team_name") or event.get("team_slug") or "-"


def _event_dt(value):
    """Parse calendar event datetime and return naive UTC datetime."""
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)

    return parsed


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


def _event_contains_time(event, at):
    start_at = _event_dt(event["start"])
    end_at = _event_dt(event["end"])

    return start_at <= at < end_at


def _same_user_event_at(rotation, user_id, at):
    events = build_rotation_calendar(
        rotation,
        at - timedelta(seconds=1),
        at + timedelta(seconds=1),
    )

    for event in events:
        if int(event.get("user_id") or 0) != int(user_id):
            continue

        if _event_contains_time(event, at):
            return event

    return None


def _send_plain_email(to_email, subject, body):
    smtp_host = Config.SMTP_HOST
    smtp_port = int(Config.SMTP_PORT)

    if not smtp_host:
        raise RuntimeError("smtp host is missing: set [smtp] host in config")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = Config.SMTP_FROM
    message["To"] = to_email
    message.set_content(body)

    if getattr(Config, "SMTP_USE_TLS", False):
        with smtplib.SMTP(smtp_host, smtp_port) as smtp:
            smtp.starttls()
            if Config.SMTP_USER:
                smtp.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
            smtp.send_message(message)
        return

    with smtplib.SMTP(smtp_host, smtp_port) as smtp:
        if Config.SMTP_USER:
            smtp.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
        smtp.send_message(message)


def _build_shift_email(user, event, event_type):
    name = _display_name(user)
    rotation_name = event.get("rotation_name") or f"Rotation #{event.get('rotation_id')}"
    team_name = _team_display_name(event)
    layer_name = event.get("layer_name") or "Override" if event.get("type") == "override" else "-"
    start_at = _event_dt(event["start"])
    end_at = _event_dt(event["end"])

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
            "slot_start_at": _event_dt(event["start"]),
            "slot_end_at": _event_dt(event["end"]),
            "layer_id": event.get("layer_id"),
            "override_id": event.get("override_id"),
            "status": "pending",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        },
    )

    return log, created


def _mark_log(log, status, error=None):
    log.status = status
    log.last_error = error
    log.updated_at = datetime.utcnow()

    if status == "sent":
        log.sent_at = datetime.utcnow()

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
            "slot_start_at": _event_dt(event["start"]),
            "slot_end_at": _event_dt(event["end"]),
            "layer_id": event.get("layer_id"),
            "override_id": event.get("override_id"),
            "mattermost_user_id": mattermost_user_id,
            "status": "pending",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
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
    start_at = _event_dt(event["start"])
    end_at = _event_dt(event["end"])

    if event_type == SHIFT_START:
        return window_start < start_at <= now

    if event_type == SHIFT_END:
        return window_start < end_at <= now

    return False


def send_due_oncall_shift_email_notifications(now=None, lookback_seconds=None):
    """
    Send email notifications for shifts that started or ended recently.

    The scheduler runs periodically, so this job looks back a small window
    and uses OnCallShiftEmailNotification.fingerprint to avoid duplicates.
    """
    now = now or datetime.utcnow()

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
        events = build_rotation_calendar(rotation, window_start, window_end)

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
    now = now or datetime.utcnow()

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
        events = build_rotation_calendar(rotation, window_start, window_end)

        for event in events:
            if _event_due(event, SHIFT_START, window_start, now):
                if _send_shift_event_to_mattermost(event, SHIFT_START):
                    sent += 1

    return sent
