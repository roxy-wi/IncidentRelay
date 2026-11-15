from pathlib import Path

from peewee import DatabaseProxy, MySQLDatabase, PostgresqlDatabase, SqliteDatabase
from playhouse.pool import PooledPostgresqlDatabase
from psycopg2 import Error as PostgreSQLError
from psycopg2.extensions import (
    TRANSACTION_STATUS_ACTIVE, TRANSACTION_STATUS_IDLE, TRANSACTION_STATUS_UNKNOWN,
)

from app.settings import Config


database_proxy = DatabaseProxy()


class SafePooledPostgresqlDatabase(PooledPostgresqlDatabase):
    """Return only idle, usable sessions to the process-local pool."""

    def _can_reuse(self, connection):
        try:
            status = connection.get_transaction_status()
            if status in (TRANSACTION_STATUS_UNKNOWN, TRANSACTION_STATUS_ACTIVE):
                connection.close()
                return False
            if status != TRANSACTION_STATUS_IDLE:
                # Peewee uses driver autocommit. An explicit SQL BEGIN can
                # therefore need SQL ROLLBACK rather than driver rollback/reset.
                with connection.cursor() as cursor:
                    cursor.execute("ROLLBACK")
            return not connection.closed
        except PostgreSQLError:
            connection.close()
            return False


def ensure_sqlite_directory(database_name):
    """
    Create parent directory for SQLite database files.
    """
    if database_name in ("", ":memory:"):
        return

    database_path = Path(database_name)

    if database_path.parent == Path("."):
        return

    database_path.parent.mkdir(parents=True, exist_ok=True)


def create_database():
    """
    Create a database instance for the configured backend.
    """

    if Config.DB_TYPE == "sqlite":
        ensure_sqlite_directory(Config.DB_NAME)

        return SqliteDatabase(
            Config.DB_NAME,
            pragmas={
                "journal_mode": "wal",
                "cache_size": -1024 * 64,
                "foreign_keys": 1,
            },
        )

    if Config.DB_TYPE == "mysql":
        return MySQLDatabase(
            Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            host=Config.DB_HOST,
            port=Config.DB_PORT or 3306,
            charset="utf8mb4",
        )

    if Config.DB_TYPE == "postgresql":
        database_class = PostgresqlDatabase
        pool_options = {}
        if Config.DB_POOL_ENABLED:
            if min(Config.DB_POOL_MAX_CONNECTIONS, Config.DB_POOL_STALE_SECONDS,
                   Config.DB_POOL_WAIT_SECONDS) < 1:
                raise RuntimeError("PostgreSQL pool limits must be positive")
            database_class = SafePooledPostgresqlDatabase
            pool_options = {
                "max_connections": Config.DB_POOL_MAX_CONNECTIONS,
                "stale_timeout": Config.DB_POOL_STALE_SECONDS,
                "timeout": Config.DB_POOL_WAIT_SECONDS,
            }
        return database_class(
            Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            host=Config.DB_HOST,
            port=Config.DB_PORT or 5432,
            **pool_options,
        )

    raise RuntimeError(f"Unsupported DB_TYPE: {Config.DB_TYPE}")


def init_database():
    """
    Initialize the database proxy.
    """
    if database_proxy.obj is not None:
        return database_proxy.obj

    db = create_database()
    database_proxy.initialize(db)
    return db
