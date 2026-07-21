"""Repair alert group schema and backfill old alerts into groups."""

import hashlib
from datetime import datetime

from peewee import IntegerField
from playhouse.migrate import migrate

from app.db import init_database
from app.migrations.introspection import (
    get_columns as migration_get_columns,
    get_tables as migration_get_tables,
)
from app.modules.db.migrator import get_migrator
from app.modules.db.models import (
    Alert,
    AlertEvent,
    AlertGroup,
    AlertGroupMerge,
    AlertNotification,
)


db = init_database()
migrator = get_migrator(db)


def _is_postgres():
    name = db.__class__.__name__.lower()
    return "postgres" in name or "postgre" in name


def _table(model):
    return model._meta.table_name


def _tables():
    return set(migration_get_tables(db))


def _has_table(table_name):
    return table_name in _tables()


def _has_column(table_name, column_name):
    if not _has_table(table_name):
        return False

    return any(column.name == column_name for column in migration_get_columns(db, table_name))


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _first_existing_table(*names):
    existing = _tables()

    for name in names:
        if name and name in existing:
            return name

    return None


def _hash_group_key(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def upgrade():
    db.create_tables([AlertGroup, AlertGroupMerge], safe=True)

    alert_table = _first_existing_table(_table(Alert), "alert")
    event_table = _first_existing_table(
        _table(AlertEvent),
        "alert_event",
        "alertevent",
    )
    notification_table = _first_existing_table(
        _table(AlertNotification),
        "alert_notification",
        "alertnotification",
    )

    _ensure_alert_group_id(alert_table)
    _ensure_event_group_id(event_table)
    _ensure_notification_group_id(notification_table)

    if _is_postgres():
        _drop_postgres_not_null(event_table, "alert_id")
        _drop_postgres_not_null(notification_table, "alert_id")

    _backfill_alert_groups()
    _backfill_event_group_id(event_table, alert_table)
    _backfill_notification_group_id(notification_table, alert_table)


def downgrade():
    # Do not undo this migration.
    # AlertGroup is now the primary incident object.
    pass


def _ensure_alert_group_id(alert_table):
    if not alert_table:
        return

    if _has_column(alert_table, "group_id"):
        return

    migrate(
        migrator.add_column(
            alert_table,
            "group_id",
            IntegerField(null=True),
        )
    )

    db.execute_sql(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{alert_table}_group_id
        ON {_quote(alert_table)}(group_id)
        """
    )


def _ensure_event_group_id(event_table):
    if not event_table:
        return

    if not _has_column(event_table, "group_id"):
        migrate(
            migrator.add_column(
                event_table,
                "group_id",
                IntegerField(null=True),
            )
        )

    db.execute_sql(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{event_table}_group_id
        ON {_quote(event_table)}(group_id)
        """
    )


def _ensure_notification_group_id(notification_table):
    if not notification_table:
        return

    if not _has_column(notification_table, "group_id"):
        migrate(
            migrator.add_column(
                notification_table,
                "group_id",
                IntegerField(null=True),
            )
        )

    db.execute_sql(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{notification_table}_group_id
        ON {_quote(notification_table)}(group_id)
        """
    )


def _drop_postgres_not_null(table_name, column_name):
    if not table_name:
        return

    if not _has_column(table_name, column_name):
        return

    db.execute_sql(
        f"""
        ALTER TABLE {_quote(table_name)}
        ALTER COLUMN {_quote(column_name)} DROP NOT NULL
        """
    )


def _backfill_alert_groups():
    if not _has_column(_table(Alert), "group_id"):
        return

    alerts = (
        Alert
        .select()
        .where(Alert.group.is_null(True))
        .order_by(Alert.id.asc())
    )

    for alert in alerts:
        group_key = alert.group_key or alert.dedup_key or f"alert:{alert.id}"
        now = datetime.utcnow()
        first_seen_at = alert.first_seen_at or now
        last_seen_at = alert.last_seen_at or first_seen_at
        status = alert.status or "firing"

        group = AlertGroup.create(
            team=alert.team_id,
            route=alert.route_id,
            service=alert.service_id,
            rotation=alert.rotation_id,
            escalation_policy=alert.escalation_policy_id,
            escalation_rule=alert.escalation_rule_id,
            next_escalation_at=alert.next_escalation_at,
            last_escalated_at=alert.last_escalated_at,
            escalation_repeat_count=alert.escalation_repeat_count or 0,
            escalation_level=alert.escalation_level or 0,
            assignee=alert.assignee_id,
            source=alert.source or "unknown",
            group_key=group_key,
            group_key_hash=_hash_group_key(group_key),
            title=alert.title or f"Alert #{alert.id}",
            message=alert.message,
            severity=alert.severity,
            common_labels=alert.labels or {},
            label_values={},
            payload_summary=None,
            status=status,
            previous_status=alert.previous_status,
            acknowledged_by=alert.acknowledged_by_id,
            acknowledged_at=alert.acknowledged_at,
            resolved_by=None,
            resolved_at=alert.resolved_at,
            first_seen_at=first_seen_at,
            last_seen_at=last_seen_at,
            last_notification_at=alert.last_notification_at,
            alert_count=1,
            firing_count=1 if status == "firing" else 0,
            acknowledged_count=1 if status == "acknowledged" else 0,
            resolved_count=1 if status == "resolved" else 0,
            silenced_count=1 if status == "silenced" else 0,
            reminder_count=alert.reminder_count or 0,
            silenced=bool(alert.silenced),
            created_at=first_seen_at,
            updated_at=last_seen_at,
        )

        alert.group = group.id
        alert.save()


def _backfill_event_group_id(event_table, alert_table):
    if not event_table or not alert_table:
        return

    if not _has_column(event_table, "group_id"):
        return

    if not _has_column(event_table, "alert_id"):
        return

    if not _has_column(alert_table, "group_id"):
        return

    db.execute_sql(
        f"""
        UPDATE {_quote(event_table)} AS event
        SET group_id = alert.group_id
        FROM {_quote(alert_table)} AS alert
        WHERE event.alert_id = alert.id
          AND event.group_id IS NULL
          AND alert.group_id IS NOT NULL
        """
    )


def _backfill_notification_group_id(notification_table, alert_table):
    if not notification_table or not alert_table:
        return

    if not _has_column(notification_table, "group_id"):
        return

    if not _has_column(notification_table, "alert_id"):
        return

    if not _has_column(alert_table, "group_id"):
        return

    db.execute_sql(
        f"""
        UPDATE {_quote(notification_table)} AS notification
        SET group_id = alert.group_id
        FROM {_quote(alert_table)} AS alert
        WHERE notification.alert_id = alert.id
          AND notification.group_id IS NULL
          AND alert.group_id IS NOT NULL
        """
    )
