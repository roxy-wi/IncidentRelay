"""Reuse lookup SQL, never lookup results.

Lazy foreign-key access is a significant source of identical SELECT compilation
in Peewee. Keep its model hydration and parameter conversion, while compiling
the scalar primary-key statement only once per model/database/column layout.
"""
from functools import lru_cache

from peewee import Field, Value


_PARAMETER = object()


def _identity(value):
    return value


@lru_cache(maxsize=256)
def _lookup_template(model, database, layout):
    # layout is part of the key so migrations/bind contexts cannot reuse SQL
    # for a different table, schema, primary key, dialect, or column layout.
    if any(type(field).__sql__ is not Field.__sql__ for field in model._meta.sorted_fields):
        return None
    placeholder = Value(_PARAMETER, converter=_identity, unpack=False)
    query = model.select().where(model._meta.primary_key == placeholder)
    sql, constants = query.bind(database).limit(1).offset(0).sql()
    return sql, tuple(constants)


def get_by_primary_key(model, value, database):
    metadata = model._meta
    layout = (
        metadata.table_name, metadata.schema, metadata.primary_key.name,
        database.param, database.quote,
        tuple((field.name, field.column_name, type(field).__sql__) for field in metadata.sorted_fields),
    )
    template = _lookup_template(model, database, layout)
    if template is None:
        return model.select().where(metadata.primary_key == value).get()
    sql, constants = template
    parameter = metadata.primary_key.db_value(value)
    params = tuple(parameter if item is _PARAMETER else item for item in constants)
    return model.raw(sql, *params).bind(database).get()
