import pytest

from app.db import database_proxy


@pytest.mark.postgresql
def test_tests_are_really_using_postgresql():
    database = database_proxy.obj

    assert "postgres" in database.__class__.__name__.lower()


@pytest.mark.postgresql
def test_postgresql_connection_executes_query():
    database = database_proxy.obj

    cursor = database.execute_sql(
        "SELECT current_database(), version()"
    )
    database_name, version = cursor.fetchone()

    assert database_name == "incidentrelay_test"
    assert "PostgreSQL" in version
