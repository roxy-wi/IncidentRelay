"""Compiled SQL for ordinary saves on explicitly opted-in alert models.

The ORM still owns models, converters, defaults, hooks, and transactions. Only
stable scalar INSERT/UPDATE statement construction is reused. Expressions and
nonstandard models take Peewee's normal path.
"""
from functools import lru_cache

from peewee import AutoField, Field, ForeignKeyField, Model, MySQLDatabase, Node, PostgresqlDatabase, SqliteDatabase, Value


NOT_SUPPORTED = object()


class _Parameter:
    def __init__(self, name):
        self.name = name


def _identity(value):
    return value


def _standard_field(field):
    field_type = type(field)
    ordinary = field_type.__module__ == "peewee" or (
        field_type.__module__ == "app.modules.db.models" and field_type.__name__ == "JSONTextField"
    )
    if isinstance(field, ForeignKeyField):
        ordinary = ordinary and type(field.rel_field).__module__ == "peewee"
    return ordinary and field_type.__sql__ is Field.__sql__


@lru_cache(maxsize=256)
def _save_template(model, database, insert, names, layout):
    values = {model._meta.fields[name]: Value(_Parameter(name), converter=_identity, unpack=False) for name in names}
    if insert:
        query = model.insert(values)
    else:
        query = model.update(values).where(
            model._meta.primary_key == Value(_Parameter(model._meta.primary_key.name), converter=_identity, unpack=False)
        )
    sql, recipe = query.bind(database).sql()
    return sql, tuple(recipe)


def save(instance, force_insert=False, only=None):
    model = type(instance)
    metadata = instance._meta
    primary = metadata.primary_key
    database = getattr(metadata.database, "obj", metadata.database)
    if (not metadata.auto_increment or not isinstance(primary, AutoField)
        or type(primary).__module__ != "peewee"
        or not isinstance(database, (SqliteDatabase, PostgresqlDatabase, MySQLDatabase))
        or getattr(model.insert, "__func__", None) is not Model.insert.__func__
        or getattr(model.update, "__func__", None) is not Model.update.__func__
        or (metadata.schema is not None and not isinstance(metadata.schema, str))):
        return NOT_SUPPORTED

    if only is not None:
        data = instance._prune_fields(instance.__data__, only)
    elif metadata.only_save_dirty and not force_insert:
        data = instance._prune_fields(instance.__data__, instance.dirty_fields)
    else:
        data = instance.__data__.copy()
    # Leave empty/no-op/error cases and unsaved relation handling to Peewee.
    if not data:
        return NOT_SUPPORTED
    for field in metadata.refs:
        if field.name in data and data[field.name] is None and instance.__rel__.get(field.name) is not None:
            return NOT_SUPPORTED
    primary_value = instance._pk
    if isinstance(primary_value, (Node, list, tuple, dict, set, frozenset, range)):
        return NOT_SUPPORTED
    insert = force_insert or primary_value is None
    if primary_value is None or not insert:
        data.pop(primary.name, None)
    if not data or any(name not in metadata.fields for name in data):
        return NOT_SUPPORTED
    # An INSERT compiler can evaluate omitted Python defaults. Such a query
    # must not freeze callable defaults into its cached parameter recipe.
    if insert and any(field.name not in data for field in metadata.defaults):
        return NOT_SUPPORTED
    fields = tuple(field for field in metadata.sorted_fields if field.name in data)
    if any(not _standard_field(field) or isinstance(data[field.name], Node) for field in fields):
        return NOT_SUPPORTED

    converted = {field.name: field.db_value(data[field.name]) for field in fields}
    if not insert:
        converted[primary.name] = primary.db_value(primary_value)
    layout = (metadata.table_name, metadata.schema, primary.name, primary.column_name,
              database.param, database.quote, database.returning_clause,
              tuple((field.name, field.column_name) for field in fields))
    sql, recipe = _save_template(model, database, insert, tuple(field.name for field in fields), layout)
    params = tuple(converted[item.name] if isinstance(item, _Parameter) else item for item in recipe)
    cursor = database.execute_sql(sql, params)
    try:
        if insert:
            if database.returning_clause:
                row = cursor.fetchone()
                new_primary = row[0] if row else None
            else:
                new_primary = cursor.lastrowid
            if new_primary is not None:
                instance._pk = new_primary
                instance._dirty.discard(primary.name)
            rows = 1
        else:
            rows = database.rows_affected(cursor)
    finally:
        cursor.close()
    instance._dirty -= set(data)
    return rows
