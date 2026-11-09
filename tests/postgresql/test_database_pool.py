from concurrent.futures import ThreadPoolExecutor

import pytest
from peewee import ProgrammingError
from playhouse.pool import MaxConnectionsExceeded, PooledPostgresqlDatabase

pytestmark = pytest.mark.postgresql


def pooled(db):
    if not isinstance(db, PooledPostgresqlDatabase):
        pytest.skip("requires pooled PostgreSQL")
    return db


def test_requests_can_reuse_the_same_postgresql_backend(db):
    database = pooled(db)
    backend = database.connection().get_backend_pid()
    database.close()
    database.connect()
    assert database.connection().get_backend_pid() == backend


def test_a_broken_idle_connection_is_replaced(db):
    database = pooled(db)
    backend = database.connection().get_backend_pid()
    database.connection().close()
    database.close()
    database.connect()
    assert database.connection().get_backend_pid() != backend
    assert database.execute_sql("SELECT 1").fetchone() == (1,)


def test_an_aborted_transaction_does_not_poison_the_next_checkout(db):
    database = pooled(db)
    database.execute_sql("BEGIN")
    with pytest.raises(ProgrammingError):
        database.execute_sql("SELECT * FROM deliberately_missing_pool_test_table")
    database.close()
    database.connect()
    assert database.execute_sql("SELECT 1").fetchone() == (1,)


def test_an_uncommitted_request_is_rolled_back_on_return(db):
    from app.modules.db.models import Group
    database = pooled(db)
    database.execute_sql("BEGIN")
    Group.create(slug="pool-uncommitted", name="Must be rolled back")
    database.close()
    database.connect()
    assert not Group.select().where(Group.slug == "pool-uncommitted").exists()


def test_pool_exhaustion_has_a_bounded_wait(db):
    database = pooled(db)
    pool = PooledPostgresqlDatabase(database.database, max_connections=1, timeout=0.1,
                                    stale_timeout=300, **database.connect_params)

    def acquire_second():
        with pytest.raises(MaxConnectionsExceeded):
            pool.connect()

    try:
        with pool.connection_context():
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(acquire_second).result(timeout=5)
    finally:
        pool.close_all()
