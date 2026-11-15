import pytest
from peewee import PostgresqlDatabase
from playhouse.pool import PooledPostgresqlDatabase

from app.db import create_database
from app.settings import Config


def test_postgresql_pool_is_bounded_and_configurable(monkeypatch):
    monkeypatch.setattr(Config, "DB_TYPE", "postgresql")
    database = create_database()
    assert isinstance(database, PooledPostgresqlDatabase)
    assert database._max_connections == Config.DB_POOL_MAX_CONNECTIONS
    assert database._stale_timeout == Config.DB_POOL_STALE_SECONDS
    assert database._wait_timeout == Config.DB_POOL_WAIT_SECONDS


def test_pool_can_be_disabled(monkeypatch):
    monkeypatch.setattr(Config, "DB_TYPE", "postgresql")
    monkeypatch.setattr(Config, "DB_POOL_ENABLED", False)
    assert type(create_database()) is PostgresqlDatabase


@pytest.mark.parametrize("option", ["DB_POOL_MAX_CONNECTIONS", "DB_POOL_STALE_SECONDS", "DB_POOL_WAIT_SECONDS"])
def test_pool_rejects_unbounded_or_nonpositive_limits(monkeypatch, option):
    monkeypatch.setattr(Config, "DB_TYPE", "postgresql")
    monkeypatch.setattr(Config, option, 0)
    with pytest.raises(RuntimeError, match="positive"):
        create_database()
