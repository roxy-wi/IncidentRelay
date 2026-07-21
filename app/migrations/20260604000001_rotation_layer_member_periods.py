"""Convert rotation layer members to versioned membership periods."""

from app.db import init_database
from app.migrations.introspection import (
    get_columns as migration_get_columns,
)


db = init_database()


def _is_postgres():
    name = db.__class__.__name__.lower()
    return "postgres" in name or "postgre" in name


def _has_column(table_name: str, column_name: str) -> bool:
    return any(column.name == column_name for column in migration_get_columns(db, table_name))


def upgrade():
    if _is_postgres():
        _upgrade_postgres()
    else:
        _upgrade_sqlite()


def downgrade():
    # Do not restore old unique constraints.
    # After this migration the table may contain several periods
    # for the same layer/user or layer/position.
    pass


def _upgrade_common():
    if _is_postgres():
        db.execute_sql(
            """
            ALTER TABLE rotation_layer_member
            ADD COLUMN IF NOT EXISTS starts_at TIMESTAMP NULL
            """
        )

        db.execute_sql(
            """
            ALTER TABLE rotation_layer_member
            ADD COLUMN IF NOT EXISTS ends_at TIMESTAMP NULL
            """
        )
    else:
        if not _has_column("rotation_layer_member", "starts_at"):
            db.execute_sql(
                """
                ALTER TABLE rotation_layer_member
                ADD COLUMN starts_at TIMESTAMP NULL
                """
            )

        if not _has_column("rotation_layer_member", "ends_at"):
            db.execute_sql(
                """
                ALTER TABLE rotation_layer_member
                ADD COLUMN ends_at TIMESTAMP NULL
                """
            )

    db.execute_sql(
        """
        UPDATE rotation_layer_member
        SET starts_at = COALESCE(
            (
                SELECT rotation_layer.start_at
                FROM rotation_layer
                WHERE rotation_layer.id = rotation_layer_member.layer_id
            ),
            CURRENT_TIMESTAMP
        )
        WHERE starts_at IS NULL
        """
    )

    if _is_postgres():
        db.execute_sql(
            """
            UPDATE rotation_layer_member
            SET ends_at = CURRENT_TIMESTAMP
            WHERE active IS FALSE
              AND ends_at IS NULL
            """
        )
    else:
        db.execute_sql(
            """
            UPDATE rotation_layer_member
            SET ends_at = CURRENT_TIMESTAMP
            WHERE active = 0
              AND ends_at IS NULL
            """
        )


def _upgrade_postgres():
    _upgrade_common()

    db.execute_sql(
        """
        DO $$
        DECLARE
            item record;
        BEGIN
            FOR item IN
                SELECT
                    n.nspname AS schema_name,
                    rel.relname AS table_name,
                    con.conname AS constraint_name
                FROM pg_constraint con
                JOIN pg_class rel
                  ON rel.oid = con.conrelid
                JOIN pg_namespace n
                  ON n.oid = rel.relnamespace
                WHERE rel.relname = 'rotation_layer_member'
                  AND con.contype = 'u'
                  AND (
                      (
                          SELECT array_agg(att.attname::text ORDER BY att.attname::text)
                          FROM unnest(con.conkey) AS cols(attnum)
                          JOIN pg_attribute att
                            ON att.attrelid = rel.oid
                           AND att.attnum = cols.attnum
                      ) = ARRAY['layer_id', 'position']
                      OR
                      (
                          SELECT array_agg(att.attname::text ORDER BY att.attname::text)
                          FROM unnest(con.conkey) AS cols(attnum)
                          JOIN pg_attribute att
                            ON att.attrelid = rel.oid
                           AND att.attnum = cols.attnum
                      ) = ARRAY['layer_id', 'user_id']
                  )
            LOOP
                EXECUTE format(
                    'ALTER TABLE %%I.%%I DROP CONSTRAINT IF EXISTS %%I',
                    item.schema_name,
                    item.table_name,
                    item.constraint_name
                );
            END LOOP;
        END $$;
        """
    )

    db.execute_sql(
        """
        DO $$
        DECLARE
            item record;
        BEGIN
            FOR item IN
                SELECT
                    n.nspname AS schema_name,
                    idx.relname AS index_name
                FROM pg_index ix
                JOIN pg_class tbl
                  ON tbl.oid = ix.indrelid
                JOIN pg_class idx
                  ON idx.oid = ix.indexrelid
                JOIN pg_namespace n
                  ON n.oid = tbl.relnamespace
                WHERE tbl.relname = 'rotation_layer_member'
                  AND ix.indisunique = TRUE
                  AND (
                      (
                          SELECT array_agg(att.attname::text ORDER BY att.attname::text)
                          FROM unnest(ix.indkey) AS cols(attnum)
                          JOIN pg_attribute att
                            ON att.attrelid = tbl.oid
                           AND att.attnum = cols.attnum
                      ) = ARRAY['layer_id', 'position']
                      OR
                      (
                          SELECT array_agg(att.attname::text ORDER BY att.attname::text)
                          FROM unnest(ix.indkey) AS cols(attnum)
                          JOIN pg_attribute att
                            ON att.attrelid = tbl.oid
                           AND att.attnum = cols.attnum
                      ) = ARRAY['layer_id', 'user_id']
                  )
            LOOP
                EXECUTE format(
                    'DROP INDEX IF EXISTS %%I.%%I',
                    item.schema_name,
                    item.index_name
                );
            END LOOP;
        END $$;
        """
    )

    db.execute_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_rlm_layer_position_starts_at
        ON rotation_layer_member(layer_id, position, starts_at)
        """
    )

    db.execute_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_rlm_layer_user_starts_at
        ON rotation_layer_member(layer_id, user_id, starts_at)
        """
    )

    db.execute_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_rlm_layer_period
        ON rotation_layer_member(layer_id, starts_at, ends_at)
        """
    )


def _upgrade_sqlite():
    _upgrade_common()

    db.execute_sql(
        """
        DROP INDEX IF EXISTS rotation_layer_member_layer_id_position
        """
    )

    db.execute_sql(
        """
        DROP INDEX IF EXISTS rotation_layer_member_layer_id_user_id
        """
    )

    db.execute_sql(
        """
        DROP INDEX IF EXISTS rotationlayermember_layer_id_position
        """
    )

    db.execute_sql(
        """
        DROP INDEX IF EXISTS rotationlayermember_layer_id_user_id
        """
    )

    db.execute_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_rlm_layer_position_starts_at
        ON rotation_layer_member(layer_id, position, starts_at)
        """
    )

    db.execute_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_rlm_layer_user_starts_at
        ON rotation_layer_member(layer_id, user_id, starts_at)
        """
    )

    db.execute_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_rlm_layer_period
        ON rotation_layer_member(layer_id, starts_at, ends_at)
        """
    )
