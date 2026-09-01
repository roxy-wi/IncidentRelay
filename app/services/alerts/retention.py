"""Retention cleanup for terminal alert history."""

from __future__ import annotations

from datetime import timedelta

from peewee import fn

from app.db import database_proxy
from app.modules.common import utc_now
from app.modules.db.models import Alert, AlertGroup


DEFAULT_ALERT_RETENTION_DAYS = 0
DEFAULT_ALERT_RETENTION_BATCH_SIZE = 500


def _normalize_retention_days(value) -> int:
    retention_days = int(value)
    if retention_days < 0:
        raise ValueError("retention_days must be greater than or equal to 0")
    return retention_days


def _normalize_batch_size(value) -> int:
    batch_size = int(value)
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than 0")
    return batch_size


def _resolved_group_batch(cutoff, batch_size: int) -> list[int]:
    """Return terminal groups that are safe to remove.

    A resolved group is retained if it still contains any non-resolved alert.
    That defensive check prevents retention cleanup from deleting an inconsistent or
    reactivated incident merely because an old ``resolved_at`` value survived.
    """
    non_terminal_alert = (
        Alert
        .select(Alert.id)
        .where(
            (Alert.group == AlertGroup.id)
            & (Alert.status != "resolved")
        )
    )

    return [
        row.id
        for row in (
            AlertGroup
            .select(AlertGroup.id)
            .where(
                (AlertGroup.status == "resolved")
                & AlertGroup.resolved_at.is_null(False)
                & (AlertGroup.resolved_at < cutoff)
                & ~fn.EXISTS(non_terminal_alert)
            )
            .order_by(AlertGroup.resolved_at.asc(), AlertGroup.id.asc())
            .limit(batch_size)
        )
    ]


def _standalone_alert_batch(cutoff, batch_size: int) -> list[int]:
    """Return old resolved alerts that are not attached to an alert group."""
    return [
        row.id
        for row in (
            Alert
            .select(Alert.id)
            .where(
                Alert.group.is_null(True)
                & (Alert.status == "resolved")
                & Alert.resolved_at.is_null(False)
                & (Alert.resolved_at < cutoff)
            )
            .order_by(Alert.resolved_at.asc(), Alert.id.asc())
            .limit(batch_size)
        )
    ]


def cleanup_alert_history(
    *,
    retention_days=DEFAULT_ALERT_RETENTION_DAYS,
    batch_size=DEFAULT_ALERT_RETENTION_BATCH_SIZE,
    now=None,
):
    """Delete resolved alert history older than the configured retention.

    ``retention_days=0`` disables destructive cleanup. Once enabled, retention
    is measured from ``resolved_at`` rather than creation time. Alert groups are
    removed only when the group is resolved and every attached alert is also
    resolved. Foreign-key cascades remove comments, lifecycle events,
    notifications, responder/stakeholder state, correlations and other
    group-owned history.
    """
    retention_days = _normalize_retention_days(retention_days)
    batch_size = _normalize_batch_size(batch_size)
    now = now or utc_now()

    if retention_days == 0:
        return {
            "enabled": False,
            "retention_days": 0,
            "cutoff": None,
            "groups_deleted": 0,
            "alerts_deleted": 0,
            "standalone_alerts_deleted": 0,
            "batches": 0,
        }

    cutoff = now - timedelta(days=retention_days)
    groups_deleted = 0
    alerts_deleted = 0
    standalone_alerts_deleted = 0
    batches = 0

    while True:
        group_ids = _resolved_group_batch(cutoff, batch_size)
        if not group_ids:
            break

        with database_proxy.atomic():
            alerts_deleted += (
                Alert
                .delete()
                .where(Alert.group.in_(group_ids))
                .execute()
            )
            deleted = (
                AlertGroup
                .delete()
                .where(AlertGroup.id.in_(group_ids))
                .execute()
            )

        groups_deleted += deleted
        batches += 1

        if deleted == 0:
            break

    while True:
        alert_ids = _standalone_alert_batch(cutoff, batch_size)
        if not alert_ids:
            break

        with database_proxy.atomic():
            deleted = (
                Alert
                .delete()
                .where(Alert.id.in_(alert_ids))
                .execute()
            )

        standalone_alerts_deleted += deleted
        alerts_deleted += deleted
        batches += 1

        if deleted == 0:
            break

    return {
        "enabled": True,
        "retention_days": retention_days,
        "cutoff": cutoff,
        "groups_deleted": groups_deleted,
        "alerts_deleted": alerts_deleted,
        "standalone_alerts_deleted": standalone_alerts_deleted,
        "batches": batches,
    }
