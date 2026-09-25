import pytest
from peewee import TextField

from app.migrations.introspection import get_columns, get_indexes
from app.modules.db.models import Alert, AlertGroup


TEXT_COLUMNS = (
    (AlertGroup, "title"),
    (Alert, "title"),
    (Alert, "external_id"),
    (Alert, "group_key"),
)


def _database_column(db, model, field_name):
    table_name = model._meta.table_name
    column_name = model._meta.fields[field_name].column_name
    return next(
        column
        for column in get_columns(db, table_name)
        if column.name == column_name
    )


def test_external_alert_text_fields_are_unbounded_in_models():
    for model, field_name in TEXT_COLUMNS:
        assert isinstance(model._meta.fields[field_name], TextField)

    assert Alert._meta.fields["group_key"].index is False
    assert (("group_key", "status"), False) not in Alert._meta.indexes


def test_postgresql_external_alert_columns_are_text(db):
    if "postgres" not in db.__class__.__name__.lower():
        pytest.skip("PostgreSQL-specific column type assertion")

    for model, field_name in TEXT_COLUMNS:
        column = _database_column(db, model, field_name)
        assert "text" in str(column.data_type).lower()


def test_alert_group_key_has_no_btree_index(db):
    indexed_column_sets = {
        tuple(index.columns)
        for index in get_indexes(db, Alert._meta.table_name)
    }

    assert ("group_key",) not in indexed_column_sets
    assert ("group_key", "status") not in indexed_column_sets
