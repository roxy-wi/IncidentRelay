"""Bounded SQL-template reuse for explicit, scalar repository query shapes.

Only SQL is cached. Each invocation binds fresh values and reads fresh rows.
Factories must select a single model and vary their shape only by parameter
names; they must not read mutable configuration or request state.
"""
from functools import lru_cache

from peewee import Field, Model, PostgresqlDatabase, SqliteDatabase, Value


class _Parameter:
    def __init__(self, name):
        self.name = name


def _identity(value):
    return value


@lru_cache(maxsize=256)
def _template(model, database, factory, names, layout):
    parameters = {name: Value(_Parameter(name), converter=_identity, unpack=False) for name in names}
    sql, recipe = factory(parameters).bind(database).limit(1).sql()
    return sql, tuple(recipe)


def ordinary_first(model, factory, bindings):
    return factory({name: value for name, (field, value) in bindings.items()}).first()


def first(model, factory, bindings):
    metadata = model._meta
    database = getattr(metadata.database, "obj", metadata.database)
    if (not isinstance(database, (SqliteDatabase, PostgresqlDatabase))
        or getattr(model.select, "__func__", None) is not Model.select.__func__
        or (metadata.schema is not None and not isinstance(metadata.schema, str))
        or any(type(field).__sql__ is not Field.__sql__ for field in metadata.sorted_fields)
        or any(type(field).__module__ != "peewee" or not isinstance(value, (str, int))
               for field, value in bindings.values())):
        return ordinary_first(model, factory, bindings)
    layout = (metadata.table_name, metadata.schema, database.param, database.quote,
              tuple((field.name, field.column_name) for field in metadata.sorted_fields))
    sql, recipe = _template(model, database, factory, tuple(bindings), layout)
    values = {name: field.db_value(value) for name, (field, value) in bindings.items()}
    parameters = tuple(values[item.name] if isinstance(item, _Parameter) else item for item in recipe)
    rows = model.raw(sql, *parameters).bind(database).execute()
    try:
        return rows[0]
    except IndexError:
        return None
