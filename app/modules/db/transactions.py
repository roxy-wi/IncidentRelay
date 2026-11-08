"""Common write transactions and row locks for SQLite and PostgreSQL."""

from peewee import SqliteDatabase

from app.db import database_proxy as db


def write_transaction():
    """Reserve SQLite writes before any reads; use a regular transaction otherwise."""
    database = getattr(db, "obj", db)
    if isinstance(database, SqliteDatabase):
        return db.atomic("IMMEDIATE")
    return db.atomic()


def lock_row(query):
    """Lock a row on PostgreSQL; callers reserve SQLite writes up front."""
    if not db.in_transaction():
        raise RuntimeError("A row lock requires a transaction")
    if not isinstance(db.obj, SqliteDatabase):
        query = query.for_update()
    return query.first()
