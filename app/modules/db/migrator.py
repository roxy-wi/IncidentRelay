from playhouse.migrate import MySQLMigrator, PostgresqlMigrator, SqliteMigrator
from peewee import MySQLDatabase, PostgresqlDatabase, SqliteDatabase


def get_migrator(db):
    """
    Return a Peewee migrator for the configured database backend.
    """

    if isinstance(db, SqliteDatabase):
        return SqliteMigrator(db)

    if isinstance(db, MySQLDatabase):
        return MySQLMigrator(db)

    if isinstance(db, PostgresqlDatabase):
        return PostgresqlMigrator(db)

    raise RuntimeError(f"Unsupported database type for migrations: {type(db)}")
