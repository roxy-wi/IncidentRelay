"""Move user notification deliveries and browser push tokens to alert groups."""

from app.db import init_database
from app.migrations.introspection import (
    get_columns as migration_get_columns,
    get_tables as migration_get_tables,
)


db = init_database()


def _is_postgres():
    name = db.__class__.__name__.lower()
    return "postgres" in name or "postgre" in name


def _has_table(table_name):
    return table_name in migration_get_tables(db)


def _has_column(table_name, column_name):
    if not _has_table(table_name):
        return False

    return any(column.name == column_name for column in migration_get_columns(db, table_name))


def upgrade():
    if _is_postgres():
        _upgrade_postgres()
    else:
        _upgrade_sqlite()


def downgrade():
    pass


def _upgrade_postgres():
    _postgres_add_group_columns()
    _postgres_backfill_from_alert_id()
    _postgres_delete_unmapped_rows()
    _postgres_add_foreign_keys()
    _postgres_set_not_null()
    _postgres_create_indexes()


def _postgres_add_group_columns():
    if _has_table("user_notification_delivery"):
        db.execute_sql(
            """
            ALTER TABLE user_notification_delivery
            ADD COLUMN IF NOT EXISTS group_id INTEGER NULL
            """
        )

    if _has_table("browser_push_action_token"):
        db.execute_sql(
            """
            ALTER TABLE browser_push_action_token
            ADD COLUMN IF NOT EXISTS group_id INTEGER NULL
            """
        )


def _postgres_backfill_from_alert_id():
    if (
        _has_table("user_notification_delivery")
        and _has_column("user_notification_delivery", "alert_id")
        and _has_column("user_notification_delivery", "group_id")
        and _has_table("alert")
        and _has_column("alert", "group_id")
    ):
        db.execute_sql(
            """
            UPDATE user_notification_delivery AS delivery
            SET group_id = alert.group_id
            FROM alert
            WHERE delivery.alert_id = alert.id
              AND delivery.group_id IS NULL
              AND alert.group_id IS NOT NULL
            """
        )

    if (
        _has_table("browser_push_action_token")
        and _has_column("browser_push_action_token", "alert_id")
        and _has_column("browser_push_action_token", "group_id")
        and _has_table("alert")
        and _has_column("alert", "group_id")
    ):
        db.execute_sql(
            """
            UPDATE browser_push_action_token AS token
            SET group_id = alert.group_id
            FROM alert
            WHERE token.alert_id = alert.id
              AND token.group_id IS NULL
              AND alert.group_id IS NOT NULL
            """
        )


def _postgres_delete_unmapped_rows():
    if (
        _has_table("user_notification_delivery")
        and _has_column("user_notification_delivery", "group_id")
    ):
        db.execute_sql(
            """
            DELETE FROM user_notification_delivery
            WHERE group_id IS NULL
            """
        )

    if (
        _has_table("browser_push_action_token")
        and _has_column("browser_push_action_token", "group_id")
    ):
        db.execute_sql(
            """
            DELETE FROM browser_push_action_token
            WHERE group_id IS NULL
            """
        )


def _postgres_add_foreign_keys():
    if (
        _has_table("user_notification_delivery")
        and _has_column("user_notification_delivery", "group_id")
        and _has_table("alert_group")
    ):
        db.execute_sql(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'user_notification_delivery_group_id_fkey'
                ) THEN
                    ALTER TABLE user_notification_delivery
                    ADD CONSTRAINT user_notification_delivery_group_id_fkey
                    FOREIGN KEY (group_id)
                    REFERENCES alert_group(id)
                    ON DELETE CASCADE;
                END IF;
            END $$;
            """
        )

    if (
        _has_table("browser_push_action_token")
        and _has_column("browser_push_action_token", "group_id")
        and _has_table("alert_group")
    ):
        db.execute_sql(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'browser_push_action_token_group_id_fkey'
                ) THEN
                    ALTER TABLE browser_push_action_token
                    ADD CONSTRAINT browser_push_action_token_group_id_fkey
                    FOREIGN KEY (group_id)
                    REFERENCES alert_group(id)
                    ON DELETE CASCADE;
                END IF;
            END $$;
            """
        )


def _postgres_set_not_null():
    if (
        _has_table("user_notification_delivery")
        and _has_column("user_notification_delivery", "group_id")
    ):
        db.execute_sql(
            """
            ALTER TABLE user_notification_delivery
            ALTER COLUMN group_id SET NOT NULL
            """
        )

    if (
        _has_table("browser_push_action_token")
        and _has_column("browser_push_action_token", "group_id")
    ):
        db.execute_sql(
            """
            ALTER TABLE browser_push_action_token
            ALTER COLUMN group_id SET NOT NULL
            """
        )


def _postgres_create_indexes():
    if _has_table("user_notification_delivery"):
        db.execute_sql(
            """
            CREATE INDEX IF NOT EXISTS idx_user_notification_delivery_group_user_method_event
            ON user_notification_delivery(group_id, user_id, method, event_type)
            """
        )

        db.execute_sql(
            """
            CREATE INDEX IF NOT EXISTS idx_user_notification_delivery_rule_group_event
            ON user_notification_delivery(rule_id, group_id, event_type)
            """
        )

    if _has_table("browser_push_action_token"):
        db.execute_sql(
            """
            CREATE INDEX IF NOT EXISTS idx_browser_push_action_token_group_user_action
            ON browser_push_action_token(group_id, user_id, action)
            """
        )


def _upgrade_sqlite():
    _sqlite_add_group_columns()
    _sqlite_backfill_from_alert_id()
    _sqlite_delete_unmapped_rows()
    _sqlite_create_indexes()


def _sqlite_add_group_columns():
    if (
        _has_table("user_notification_delivery")
        and not _has_column("user_notification_delivery", "group_id")
    ):
        db.execute_sql(
            """
            ALTER TABLE user_notification_delivery
            ADD COLUMN group_id INTEGER NULL
            """
        )

    if (
        _has_table("browser_push_action_token")
        and not _has_column("browser_push_action_token", "group_id")
    ):
        db.execute_sql(
            """
            ALTER TABLE browser_push_action_token
            ADD COLUMN group_id INTEGER NULL
            """
        )


def _sqlite_backfill_from_alert_id():
    if (
        _has_table("user_notification_delivery")
        and _has_column("user_notification_delivery", "alert_id")
        and _has_column("user_notification_delivery", "group_id")
        and _has_table("alert")
        and _has_column("alert", "group_id")
    ):
        db.execute_sql(
            """
            UPDATE user_notification_delivery
            SET group_id = (
                SELECT alert.group_id
                FROM alert
                WHERE alert.id = user_notification_delivery.alert_id
            )
            WHERE group_id IS NULL
            """
        )

    if (
        _has_table("browser_push_action_token")
        and _has_column("browser_push_action_token", "alert_id")
        and _has_column("browser_push_action_token", "group_id")
        and _has_table("alert")
        and _has_column("alert", "group_id")
    ):
        db.execute_sql(
            """
            UPDATE browser_push_action_token
            SET group_id = (
                SELECT alert.group_id
                FROM alert
                WHERE alert.id = browser_push_action_token.alert_id
            )
            WHERE group_id IS NULL
            """
        )


def _sqlite_delete_unmapped_rows():
    if (
        _has_table("user_notification_delivery")
        and _has_column("user_notification_delivery", "group_id")
    ):
        db.execute_sql(
            """
            DELETE FROM user_notification_delivery
            WHERE group_id IS NULL
            """
        )

    if (
        _has_table("browser_push_action_token")
        and _has_column("browser_push_action_token", "group_id")
    ):
        db.execute_sql(
            """
            DELETE FROM browser_push_action_token
            WHERE group_id IS NULL
            """
        )


def _sqlite_create_indexes():
    if _has_table("user_notification_delivery"):
        db.execute_sql(
            """
            CREATE INDEX IF NOT EXISTS idx_user_notification_delivery_group_user_method_event
            ON user_notification_delivery(group_id, user_id, method, event_type)
            """
        )

        db.execute_sql(
            """
            CREATE INDEX IF NOT EXISTS idx_user_notification_delivery_rule_group_event
            ON user_notification_delivery(rule_id, group_id, event_type)
            """
        )

    if _has_table("browser_push_action_token"):
        db.execute_sql(
            """
            CREATE INDEX IF NOT EXISTS idx_browser_push_action_token_group_user_action
            ON browser_push_action_token(group_id, user_id, action)
            """
        )
