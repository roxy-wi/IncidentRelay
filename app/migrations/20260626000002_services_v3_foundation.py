import re
import uuid

from peewee import BooleanField, CharField, IntegerField, TextField, UUIDField
from playhouse.migrate import migrate

from app.db import init_database
from app.migrations.introspection import (
    get_columns as migration_get_columns,
    get_indexes as migration_get_indexes,
)
from app.modules.db.migrator import get_migrator
from app.modules.db.models import Service, ServiceDependency, ServiceEvent

db = init_database()
migrator = get_migrator(db)


def _is_postgres():
    name = db.__class__.__name__.lower()
    return "postgres" in name or "postgre" in name


def _is_mysql():
    return "mysql" in db.__class__.__name__.lower()


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


def _column_is_nullable(table_name, column_name):
    for column in _get_columns(table_name):
        if column.name == column_name:
            return bool(column.null)
    return False


def _index_exists(table_name, index_name):
    return any(index.name == index_name for index in _get_indexes(table_name))


def _create_index(table_name, index_name, columns, unique=False):
    if _index_exists(table_name, index_name):
        return
    unique_sql = "UNIQUE " if unique else ""
    quoted_table = _quote_identifier(table_name)
    quoted_index = _quote_identifier(index_name)
    quoted_columns = ", ".join(_quote_identifier(column) for column in columns)
    db.execute_sql(f"CREATE {unique_sql}INDEX {quoted_index} ON {quoted_table} ({quoted_columns})")


def upgrade():
    """Add the Services v3 identity, timeline and correlation foundation."""

    service_table = Service._meta.table_name
    dependency_table = ServiceDependency._meta.table_name

    service_operations = []

    if not _column_exists(service_table, "uid"):
        service_operations.append(migrator.add_column(service_table, "uid", UUIDField(null=True)))

    if not _column_exists(service_table, "kind"):
        service_operations.append(migrator.add_column(service_table, "kind", CharField(null=True)))

    if not _column_exists(service_table, "lifecycle"):
        service_operations.append(migrator.add_column(service_table, "lifecycle", CharField(null=True)))

    if service_operations:
        migrate(*service_operations)

    for service_id, current_uid, current_kind, current_lifecycle in Service.select(Service.id, Service.uid, Service.kind, Service.lifecycle).tuples():
        values = {}

        if current_uid is None:
            values["uid"] = uuid.uuid4()

        if not current_kind:
            values["kind"] = "technical"

        if not current_lifecycle:
            values["lifecycle"] = "production"

        if values:
            Service.update(**values).where(Service.id == service_id).execute()

    not_null_operations = []

    if _column_is_nullable(service_table, "uid"):
        not_null_operations.append(migrator.add_not_null(service_table, "uid"))

    if _column_is_nullable(service_table, "kind"):
        not_null_operations.append(migrator.add_not_null(service_table, "kind"))

    if _column_is_nullable(service_table, "lifecycle"):
        not_null_operations.append(migrator.add_not_null(service_table, "lifecycle"))

    if not_null_operations:
        migrate(*not_null_operations)

    _create_index(service_table, "idx_service_uid_unique", ["uid"], unique=True)
    _create_index(service_table, "idx_service_kind_lifecycle", ["kind", "lifecycle"])

    dependency_operations = []

    if not _column_exists(dependency_table, "correlation_enabled"):
        dependency_operations.append(migrator.add_column(dependency_table, "correlation_enabled", BooleanField(null=True)))

    if not _column_exists(dependency_table, "propagation_delay_seconds"):
        dependency_operations.append(migrator.add_column(dependency_table, "propagation_delay_seconds", IntegerField(null=True)))

    if not _column_exists(dependency_table, "metadata"):
        dependency_operations.append(migrator.add_column(dependency_table, "metadata", TextField(null=True)))

    if dependency_operations:
        migrate(*dependency_operations)

    ServiceDependency.update(correlation_enabled=True).where(ServiceDependency.correlation_enabled.is_null()).execute()
    ServiceDependency.update(propagation_delay_seconds=300).where(ServiceDependency.propagation_delay_seconds.is_null()).execute()
    ServiceDependency.update(metadata={}).where(ServiceDependency.metadata.is_null()).execute()

    dependency_not_null_operations = []

    if _column_is_nullable(dependency_table, "correlation_enabled"):
        dependency_not_null_operations.append(migrator.add_not_null(dependency_table, "correlation_enabled"))

    if _column_is_nullable(dependency_table, "propagation_delay_seconds"):
        dependency_not_null_operations.append(migrator.add_not_null(dependency_table, "propagation_delay_seconds"))

    if _column_is_nullable(dependency_table, "metadata"):
        dependency_not_null_operations.append(migrator.add_not_null(dependency_table, "metadata"))

    if dependency_not_null_operations:
        migrate(*dependency_not_null_operations)

    _create_index(dependency_table, "idx_service_dependency_correlation", ["service_id", "correlation_enabled", "enabled"])

    db.create_tables([ServiceEvent], safe=True)


def downgrade():
    """Remove the Services v3 foundation."""

    service_table = Service._meta.table_name
    dependency_table = ServiceDependency._meta.table_name

    db.drop_tables([ServiceEvent], safe=True)

    dependency_index = _quote_identifier("idx_service_dependency_correlation")
    service_uid_index = _quote_identifier("idx_service_uid_unique")
    service_kind_index = _quote_identifier("idx_service_kind_lifecycle")

    if _index_exists(dependency_table, "idx_service_dependency_correlation"):
        db.execute_sql(f"DROP INDEX {dependency_index}" if not _is_mysql() else f"DROP INDEX {dependency_index} ON {_quote_identifier(dependency_table)}")

    dependency_operations = []

    if _column_exists(dependency_table, "metadata"):
        dependency_operations.append(migrator.drop_column(dependency_table, "metadata"))

    if _column_exists(dependency_table, "propagation_delay_seconds"):
        dependency_operations.append(migrator.drop_column(dependency_table, "propagation_delay_seconds"))

    if _column_exists(dependency_table, "correlation_enabled"):
        dependency_operations.append(migrator.drop_column(dependency_table, "correlation_enabled"))

    if dependency_operations:
        migrate(*dependency_operations)

    if _index_exists(service_table, "idx_service_kind_lifecycle"):
        db.execute_sql(f"DROP INDEX {service_kind_index}" if not _is_mysql() else f"DROP INDEX {service_kind_index} ON {_quote_identifier(service_table)}")

    if _index_exists(service_table, "idx_service_uid_unique"):
        db.execute_sql(f"DROP INDEX {service_uid_index}" if not _is_mysql() else f"DROP INDEX {service_uid_index} ON {_quote_identifier(service_table)}")

    service_operations = []

    if _column_exists(service_table, "lifecycle"):
        service_operations.append(migrator.drop_column(service_table, "lifecycle"))

    if _column_exists(service_table, "kind"):
        service_operations.append(migrator.drop_column(service_table, "kind"))

    if _column_exists(service_table, "uid"):
        service_operations.append(migrator.drop_column(service_table, "uid"))

    if service_operations:
        migrate(*service_operations)
