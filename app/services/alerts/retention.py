"""Retention cleanup for terminal alert history."""

from __future__ import annotations

from datetime import timedelta

from peewee import fn

from app.db import database_proxy
from app.modules.common import utc_now
from app.modules.db import incident_core_repo
from app.modules.db.models import (
    Alert,
    AlertGroup,
    AlertGroupEpisode,
    ChangeAlertGroupCorrelation,
    ChangeJob,
)
from app.services.change_intelligence.authorization import lock_row


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


def _resolved_group_query(cutoff):
    """Retain active children and manually reviewed Change evidence."""
    non_terminal_alert = Alert.select(Alert.id).where(
        Alert.group == AlertGroup.id, Alert.status != "resolved"
    )
    retained_review = (
        ChangeAlertGroupCorrelation.select(ChangeAlertGroupCorrelation.id)
        .join(AlertGroupEpisode)
        .where(
            AlertGroupEpisode.alert_group == AlertGroup.id,
            (ChangeAlertGroupCorrelation.review_status != "suggested")
            | (ChangeAlertGroupCorrelation.relation_type != "potential_cause")
            | ChangeAlertGroupCorrelation.review_evidence.is_null(False)
            | ChangeAlertGroupCorrelation.reviewed_at.is_null(False)
            | ChangeAlertGroupCorrelation.reviewed_by.is_null(False),
        )
    )
    return AlertGroup.select(AlertGroup.id).where(
        AlertGroup.status == "resolved",
        AlertGroup.resolved_at.is_null(False),
        AlertGroup.resolved_at < cutoff,
        ~fn.EXISTS(non_terminal_alert),
        ~fn.EXISTS(retained_review),
    )


def _resolved_group_batch(cutoff, batch_size: int) -> list[int]:
    """Return the next bounded batch, excluding retained investigation history."""
    return [
        row.id
        for row in _resolved_group_query(cutoff)
        .order_by(AlertGroup.resolved_at, AlertGroup.id)
        .limit(batch_size)
    ]


def _standalone_alert_batch(cutoff, batch_size: int) -> list[int]:
    """Return old resolved alerts that are not attached to an alert group."""
    return [
        row.id
        for row in (
            Alert.select(Alert.id)
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
    group-owned history. Manual Change reviews pin their episode and group;
    unreviewed derived suggestions are removed before the parent rows.
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

        with incident_core_repo.write_transaction():
            for group_id in sorted(group_ids):
                incident_core_repo.lock_alert_group(group_id)
            episodes = list(
                AlertGroupEpisode.select()
                .where(AlertGroupEpisode.alert_group.in_(group_ids))
                .order_by(AlertGroupEpisode.id)
            )
            for episode in episodes:
                lock_row(
                    AlertGroupEpisode.select().where(AlertGroupEpisode.id == episode.id)
                )
            # Reopen and future review writers serialize on these same rows.
            group_ids = [
                row.id
                for row in _resolved_group_query(cutoff).where(
                    AlertGroup.id.in_(group_ids)
                )
            ]
            if not group_ids:
                continue
            episode_ids = [
                episode.id
                for episode in episodes
                if episode.alert_group_id in group_ids
            ]
            ChangeAlertGroupCorrelation.delete().where(
                ChangeAlertGroupCorrelation.episode.in_(episode_ids)
            ).execute()
            ChangeJob.delete().where(
                ChangeJob.job_type == "discover_episode",
                ChangeJob.entity_id.in_(episode_ids),
            ).execute()
            alerts_deleted += Alert.delete().where(Alert.group.in_(group_ids)).execute()
            deleted = AlertGroup.delete().where(AlertGroup.id.in_(group_ids)).execute()

        groups_deleted += deleted
        batches += 1

        if deleted == 0:
            break

    while True:
        alert_ids = _standalone_alert_batch(cutoff, batch_size)
        if not alert_ids:
            break

        with database_proxy.atomic():
            deleted = Alert.delete().where(Alert.id.in_(alert_ids)).execute()

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
