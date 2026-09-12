"""Operator-controlled temporary shelving for AlertGroups."""

from __future__ import annotations

from datetime import timedelta

from app.db import database_proxy as db
from app.modules.common import utc_now
from app.modules.db import alerts_repo, audit_repo, shelving_repo
from app.modules.db.models import AlertGroup, AlertGroupShelve
from app.modules.redaction import redact_secrets
from app.services import escalation_policies as escalation_policy_service


DEFAULT_SHELVE_DURATION_SECONDS = 3600
MIN_SHELVE_DURATION_SECONDS = 60
MAX_SHELVE_DURATION_SECONDS = 7 * 24 * 60 * 60
SHELVE_CANCELLED_DELIVERY_EVENT_TYPES = frozenset({
    "notification",
    "update",
    "reminder",
    "escalation",
})


def _normalize_duration(duration_seconds) -> int:
    if duration_seconds in (None, ""):
        return DEFAULT_SHELVE_DURATION_SECONDS
    try:
        value = int(duration_seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("duration_seconds must be an integer") from exc
    if value < MIN_SHELVE_DURATION_SECONDS:
        raise ValueError(
            f"duration_seconds must be at least {MIN_SHELVE_DURATION_SECONDS}"
        )
    if value > MAX_SHELVE_DURATION_SECONDS:
        raise ValueError(
            f"duration_seconds must not exceed {MAX_SHELVE_DURATION_SECONDS}"
        )
    return value


def _normalize_reason(reason) -> str | None:
    value = str(reason or "").strip()
    if not value:
        return None
    if len(value) > 1000:
        raise ValueError("reason must not exceed 1000 characters")
    return value


def _normalize_source(source) -> str:
    value = str(source or "ui").strip().lower()
    return value[:64] or "ui"


def _lock_alert_group(group_id: int) -> AlertGroup:
    """Lock one AlertGroup row where supported to serialize shelf mutations."""
    query = AlertGroup.select().where(AlertGroup.id == int(group_id))
    database = getattr(db, "obj", None)
    if database is not None and database.__class__.__name__ != "SqliteDatabase":
        query = query.for_update()
    group = query.first()
    if group is None:
        return alerts_repo.get_alert_group(group_id)
    return group


def get_active_shelve(group_or_id, *, now=None) -> AlertGroupShelve | None:
    group_id = getattr(group_or_id, "id", group_or_id)
    if not group_id:
        return None
    return shelving_repo.get_current_shelve(group_id, now=now)


def is_alert_group_shelved(group_or_id, *, now=None) -> bool:
    return get_active_shelve(group_or_id, now=now) is not None


def serialize_shelve_state(group_or_id, *, now=None):
    shelf = get_active_shelve(group_or_id, now=now)
    if not shelf:
        return None

    user = shelf.shelved_by if shelf.shelved_by_id else None
    return {
        "active": True,
        "id": shelf.id,
        "shelved_at": shelf.shelved_at.isoformat() if shelf.shelved_at else None,
        "until": shelf.ends_at.isoformat() if shelf.ends_at else None,
        "reason": shelf.reason,
        "source": shelf.source,
        "shelved_by": (
            {
                "id": user.id,
                "username": getattr(user, "username", None),
                "display_name": getattr(user, "display_name", None),
            }
            if user
            else None
        ),
    }


def _write_shelve_audit(
    action: str,
    group: AlertGroup,
    *,
    user_id: int | None,
    data: dict,
):
    group_id = None
    if group.team_id and group.team:
        group_id = getattr(group.team, "group_id", None)
    return audit_repo.create_audit_log(
        action=action,
        object_type="alert_group",
        object_id=group.id,
        group_id=group_id,
        team_id=group.team_id,
        user_id=user_id,
        data=redact_secrets(data),
    )


def _cancel_shelved_notification_work(group: AlertGroup):
    from app.services.notifications.rules import cancel_pending_group_deliveries

    if getattr(group, "notification_pending", False):
        alerts_repo.clear_alert_group_notification(group)

    cancel_pending_group_deliveries(
        group,
        event_types=SHELVE_CANCELLED_DELIVERY_EVENT_TYPES,
        reason="alert_group_shelved",
    )

    changed = False
    if group.next_escalation_at is not None:
        group.next_escalation_at = None
        changed = True
    if group.notification_pending or group.notification_due_at or group.notification_reason:
        group.notification_pending = False
        group.notification_due_at = None
        group.notification_reason = None
        changed = True
    if changed:
        group.updated_at = utc_now()
        group.save()


def _restart_after_unshelve(group: AlertGroup, *, now):
    """Restart current-state delivery/escalation from the unshelve time."""
    if group.status != "firing" or group.merged_into_id:
        return

    group.reminder_count = 0
    from app.services.alerts.maintenance_state import is_escalation_lifecycle_paused

    if (
        group.escalation_policy_id
        and group.escalation_rule_id
        and not is_escalation_lifecycle_paused(group, now=now)
    ):
        group.next_escalation_at = escalation_policy_service.get_next_escalation_at(
            group.escalation_rule,
            now,
        )
    else:
        group.next_escalation_at = None
    group.updated_at = now
    group.save()

    from app.services.alerts.notification_queue import schedule_group_notification

    schedule_group_notification(
        group,
        reason="shelve_ended",
        now=now,
    )


def shelve_alert_group(
    group_id: int,
    *,
    user_id: int | None = None,
    duration_seconds: int | None = None,
    reason: str | None = None,
    source: str = "ui",
):
    """Shelve one open AlertGroup and pause active delivery/escalation work."""
    duration = _normalize_duration(duration_seconds)
    reason = _normalize_reason(reason)
    source = _normalize_source(source)
    now = utc_now()
    ends_at = now + timedelta(seconds=duration)

    with db.atomic():
        group = _lock_alert_group(group_id)
        if group.status == "resolved" or group.merged_into_id:
            raise ValueError("only open, non-merged alert groups can be shelved")

        previous = shelving_repo.get_active_record(group.id)
        if previous:
            (
                AlertGroupShelve.update(
                    active=False,
                    unshelved_at=now,
                    unshelved_by=user_id,
                    unshelve_reason="replaced",
                    updated_at=now,
                )
                .where(
                    AlertGroupShelve.id == previous.id,
                    AlertGroupShelve.active == True,  # noqa: E712
                )
                .execute()
            )

        shelf = AlertGroupShelve.create(
            alert_group=group.id,
            shelved_by=user_id,
            reason=reason,
            source=source,
            shelved_at=now,
            ends_at=ends_at,
            active=True,
            created_at=now,
            updated_at=now,
        )

        _cancel_shelved_notification_work(group)
        alerts_repo.create_alert_event(
            group_id=group.id,
            event_type="alert_group_shelved",
            message=(
                f"Alert group shelved until {ends_at.isoformat()}"
                + (f": {reason}" if reason else "")
            ),
            user_id=user_id,
        )
        _write_shelve_audit(
            "alert_group.shelve",
            group,
            user_id=user_id,
            data={
                "source": source,
                "duration_seconds": duration,
                "until": ends_at.isoformat(),
                "reason": reason,
            },
        )

    from app.services.notifications.delivery import update_alert_messages

    update_alert_messages(group, event_type="shelved")
    return group, shelf


def unshelve_alert_group(
    group_id: int,
    *,
    user_id: int | None = None,
    source: str = "ui",
    reason: str | None = None,
    expired: bool = False,
    resume: bool = True,
    update_messages: bool = True,
    expected_shelf_id: int | None = None,
):
    """End the current shelf, optionally restarting delivery/escalation."""
    source = _normalize_source(source)
    reason = _normalize_reason(reason)
    now = utc_now()

    with db.atomic():
        group = _lock_alert_group(group_id)
        shelf = shelving_repo.get_active_record(group.id)
        if not shelf:
            return group, None
        if expected_shelf_id is not None and shelf.id != int(expected_shelf_id):
            return group, None

        updated = (
            AlertGroupShelve.update(
                active=False,
                unshelved_at=now,
                unshelved_by=user_id,
                unshelve_reason=(reason or ("expired" if expired else "manual")),
                updated_at=now,
            )
            .where(
                AlertGroupShelve.id == shelf.id,
                AlertGroupShelve.active == True,  # noqa: E712
            )
            .execute()
        )
        if not updated:
            return alerts_repo.get_alert_group(group.id), None

        event_type = (
            "alert_group_shelve_expired" if expired else "alert_group_unshelved"
        )
        alerts_repo.create_alert_event(
            group_id=group.id,
            event_type=event_type,
            message=(
                "Alert group shelf expired"
                if expired
                else "Alert group unshelved"
            ),
            user_id=user_id,
        )
        _write_shelve_audit(
            "alert_group.shelve_expired" if expired else "alert_group.unshelve",
            group,
            user_id=user_id,
            data={"source": source, "reason": reason},
        )

        if resume:
            _restart_after_unshelve(group, now=now)

    if update_messages:
        from app.services.notifications.delivery import update_alert_messages

        update_alert_messages(
            group,
            event_type="unshelved" if not expired else "shelve_expired",
        )
    return group, shelf


def clear_shelve_on_resolve(group_id: int, *, user_id: int | None = None):
    """Close an active shelf when its AlertGroup resolves, without resuming."""
    return unshelve_alert_group(
        group_id,
        user_id=user_id,
        source="resolve",
        reason="alert_resolved",
        resume=False,
        update_messages=False,
    )


def process_due_shelves(*, limit=100):
    """Expire due shelves; safe to run repeatedly from the scheduler."""
    now = utc_now()
    processed = 0
    expired_count = 0

    for shelf in shelving_repo.list_due_shelves(now=now, limit=limit):
        processed += 1
        group, ended = unshelve_alert_group(
            shelf.alert_group_id,
            source="scheduler",
            expired=True,
            resume=True,
            expected_shelf_id=shelf.id,
        )
        if ended:
            expired_count += 1

    return {
        "processed": processed,
        "expired": expired_count,
    }
