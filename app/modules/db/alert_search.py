"""Portable SQL predicates for free text and exact alert-label searches."""

import json
import re

from peewee import Case, MySQLDatabase, PostgresqlDatabase, SqliteDatabase, Value, fn

from app.db import database_proxy


LABEL_QUERY = re.compile(r"^([\w][\w./:-]*)\s*=(.*)$", re.DOTALL)


def parse_label_search(search):
    """Recognize one key=value condition, optionally with a JSON-quoted value."""
    match = LABEL_QUERY.fullmatch(str(search or "").strip())
    if not match:
        return None
    key, value = match.groups()
    value = value.strip()
    if value.startswith('"'):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError("Label search requires a complete double-quoted JSON string after =") from error
    return key, value


def json_text_contains(field, search):
    """Search stored JSON text without JSON-encoding the SQL LIKE parameter."""
    # Match quotes/backslashes as stored by JSONTextField. COALESCE leaves the
    # column as text and prevents Peewee from applying the field's JSON converter
    # to the LIKE pattern, including patterns with escaped wildcard characters.
    text = json.dumps(search, ensure_ascii=False)[1:-1]
    return fn.COALESCE(field, "").contains(text)


def label_equals(field, key, value):
    """Compare a top-level scalar label exactly, with case-sensitive text values."""
    database = database_proxy.obj
    expected = Value(value, converter=False)
    path = Value("$." + json.dumps(key, ensure_ascii=False), converter=False)
    if isinstance(database, SqliteDatabase):
        kind = fn.json_type(field, path)
        extracted = fn.json_extract(field, path)
        text = Case(kind, (("true", "true"), ("false", "false")), extracted.cast("TEXT"))
        return kind.in_(["text", "integer", "real", "true", "false"]) & (text.collate("BINARY") == expected)
    if isinstance(database, PostgresqlDatabase):
        document = field.cast("jsonb")
        name = Value(key, converter=False)
        extracted = fn.jsonb_extract_path(document, name)
        text = fn.jsonb_extract_path_text(document, name)
        return (
            (fn.jsonb_typeof(document) == "object")
            & fn.jsonb_typeof(extracted).in_(["string", "number", "boolean"])
            & (text.collate('"C"') == expected)
        )
    if isinstance(database, MySQLDatabase):
        extracted = fn.JSON_EXTRACT(field, path)
        return (
            fn.JSON_TYPE(extracted).in_(["STRING", "INTEGER", "DOUBLE", "BOOLEAN"])
            & (fn.JSON_UNQUOTE(extracted).cast("BINARY") == expected)
        )
    raise RuntimeError("Unsupported database backend for alert label search")
