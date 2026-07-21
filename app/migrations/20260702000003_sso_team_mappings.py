"""Add optional IncidentRelay team target to SSO group mappings."""

import re

from peewee import CharField, IntegerField
from playhouse.migrate import migrate

from app.db import init_database
from app.migrations.introspection import (
    get_columns as migration_get_columns,
    get_indexes as migration_get_indexes,
)
from app.modules.db.migrator import get_migrator
from app.modules.db.models import SsoGroupMapping


db = init_database()
migrator = get_migrator(db)


def _is_mysql():
    return "mysql" in db.__class__.__name__.lower()


def _is_postgres():
    name = db.__class__.__name__.lower()
    return "postgres" in name or "postgre" in name


def _quote_identifier(value):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise RuntimeError(f'Unsafe database identifier: "{value}"')
    quote = "`" if _is_mysql() else '"'
    return f"{quote}{value}{quote}"


def _get_columns(table_name):
    return migration_get_columns(db, table_name)


def _get_indexes(table_name):
    return migration_get_indexes(db, table_name)


def _column_exists(table_name, column_name):
    return any(column.name == column_name for column in _get_columns(table_name))


def _index_exists(table_name, index_name):
    return any(index.name == index_name for index in _get_indexes(table_name))


def _drop_index_if_exists(table_name, index_name):
    if not _index_exists(table_name, index_name):
        return

    quoted_index = _quote_identifier(index_name)
    quoted_table = _quote_identifier(table_name)

    if _is_mysql():
        db.execute_sql(f"DROP INDEX {quoted_index} ON {quoted_table}")
    else:
        db.execute_sql(f"DROP INDEX {quoted_index}")


def _create_index_if_missing(table_name, index_name, columns, unique=False):
    if _index_exists(table_name, index_name):
        return

    unique_sql = "UNIQUE " if unique else ""
    quoted_table = _quote_identifier(table_name)
    quoted_index = _quote_identifier(index_name)
    quoted_columns = ", ".join(_quote_identifier(column) for column in columns)
    db.execute_sql(
        f"CREATE {unique_sql}INDEX {quoted_index} ON {quoted_table} ({quoted_columns})"
    )


def upgrade():
    """Allow an SSO group mapping to grant an optional team role."""
    table_name = SsoGroupMapping._meta.table_name
    operations = []

    if not _column_exists(table_name, "incidentrelay_team_id"):
        operations.append(
            migrator.add_column(
                table_name,
                "incidentrelay_team_id",
                IntegerField(null=True),
            )
        )

    if not _column_exists(table_name, "team_role"):
        operations.append(
            migrator.add_column(
                table_name,
                "team_role",
                CharField(null=True),
            )
        )

    if operations:
        migrate(*operations)

    # Older installations used a unique index that prevented mapping one external
    # SSO group to several teams inside the same IncidentRelay group.
    for index_name in (
        "ssogroupmapping_provider_id_external_group_incidentrelay_group_id",
        "sso_group_mapping_provider_id_external_group_incidentrelay_group_id",
        "sso_group_mapping_provider_external_group_incidentrelay_group",
    ):
        _drop_index_if_exists(table_name, index_name)

    _create_index_if_missing(
        table_name,
        "ux_sso_group_mapping_provider_external_group_group_team",
        [
            "provider_id",
            "external_group",
            "incidentrelay_group_id",
            "incidentrelay_team_id",
        ],
        unique=True,
    )

    _create_index_if_missing(
        table_name,
        "idx_sso_group_mapping_team_id",
        ["incidentrelay_team_id"],
    )


def downgrade():
    """Remove optional SSO team mapping fields."""
    table_name = SsoGroupMapping._meta.table_name

    _drop_index_if_exists(table_name, "idx_sso_group_mapping_team_id")
    _drop_index_if_exists(table_name, "ux_sso_group_mapping_provider_external_group_group_team")

    operations = []

    if _column_exists(table_name, "team_role"):
        operations.append(migrator.drop_column(table_name, "team_role"))

    if _column_exists(table_name, "incidentrelay_team_id"):
        operations.append(migrator.drop_column(table_name, "incidentrelay_team_id"))

    if operations:
        migrate(*operations)

    _create_index_if_missing(
        table_name,
        "ssogroupmapping_provider_id_external_group_incidentrelay_group_id",
        ["provider_id", "external_group", "incidentrelay_group_id"],
        unique=True,
    )
