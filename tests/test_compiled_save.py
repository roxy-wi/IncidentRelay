from datetime import datetime
from itertools import count

import pytest
from peewee import AutoField, BooleanField, DateTimeField, ForeignKeyField, IntegrityError, IntegerField, Model, SQL, TextField

from app.modules.db.compiled_save import _save_template
from app.modules.db.models import BaseModel, JSONTextField


@pytest.fixture
def record(db):
    class Record(BaseModel):
        _compiled_write_sql = True
        id = AutoField()
        name = TextField(unique=True)
        count = IntegerField(default=0)
        enabled = BooleanField(default=True)
        data = JSONTextField(default=dict)
        at = DateTimeField(default=lambda: datetime(2026, 1, 1))
        server_value = IntegerField(null=True, constraints=[SQL("DEFAULT 42")])

        class Meta:
            database = db
            table_name = "compiled_save_record"

    Record.create_table()
    try:
        yield Record
    finally:
        Record.drop_table(safe=True)


def test_create_uses_same_sql_and_parameters_as_peewee(db, record, monkeypatch):
    row = record(name="first", data={"nested": [True, 3]})
    expected_sql, expected_params = record.insert(**row.__data__).sql()
    calls = []
    execute = db.execute_sql

    def capture(sql, params=None, *args, **kwargs):
        calls.append((sql, tuple(params or ())))
        return execute(sql, params, *args, **kwargs)

    monkeypatch.setattr(db, "execute_sql", capture)
    assert row.save(force_insert=True) == 1
    assert calls == [(expected_sql, tuple(expected_params))]
    assert row.id is not None
    assert not row._dirty
    fetched = record.get_by_id(row.id)
    assert fetched.data == {"nested": [True, 3]}
    assert fetched.enabled is True
    assert fetched.at == datetime(2026, 1, 1)
    assert fetched.server_value == 42


def test_partial_update_matches_peewee_and_preserves_unsaved_dirty_fields(db, record, monkeypatch):
    row = record.create(name="first")
    row.name = "second"
    row.count = 9
    expected_sql, expected_params = record.update(name="second").where(record.id == row.id).sql()
    calls = []
    execute = db.execute_sql

    def capture(sql, params=None, *args, **kwargs):
        calls.append((sql, tuple(params or ())))
        return execute(sql, params, *args, **kwargs)

    monkeypatch.setattr(db, "execute_sql", capture)
    assert row.save(only=[record.name]) == 1
    assert calls == [(expected_sql, tuple(expected_params))]
    assert row._dirty == {"count"}
    fetched = record.get_by_id(row.id)
    assert (fetched.name, fetched.count) == ("second", 0)


def test_compiled_save_reuses_template_but_binds_each_rows_values(db, record):
    _save_template.cache_clear()
    first = record.create(name="first", data={"value": 1})
    second = record.create(name="second", data={"value": 2})
    assert _save_template.cache_info().misses == 1
    assert _save_template.cache_info().hits == 1
    assert first.id != second.id
    assert record.get_by_id(first.id).data == {"value": 1}
    assert record.get_by_id(second.id).data == {"value": 2}


def test_explicit_primary_key_and_force_insert_preserve_identity(db, record):
    row = record.create(id=100, name="explicit")
    assert row.id == 100
    assert not row._dirty
    row.name = "updated"
    assert row.save() == 1
    assert record.get_by_id(100).name == "updated"


def test_sql_expression_updates_keep_original_peewee_path(db, record):
    row = record.create(name="counter", count=3)
    row.count = record.count + 1
    assert row.save(only=[record.count]) == 1
    assert record.get_by_id(row.id).count == 4


def test_unique_constraint_exception_and_transaction_rollback_are_preserved(db, record):
    row = record.create(name="unique")
    with pytest.raises(IntegrityError):
        with db.atomic():
            record.create(name="unique")
    assert record.select().count() == 1
    with pytest.raises(RuntimeError):
        with db.atomic():
            row.name = "rolled-back"
            row.save(only=[record.name])
            raise RuntimeError("rollback")
    assert record.get_by_id(row.id).name == "unique"


def test_missing_python_defaults_are_not_frozen_in_cached_insert(db):
    values = count(1)

    class Record(BaseModel):
        _compiled_write_sql = True
        id = AutoField()
        number = IntegerField(default=lambda: next(values))
        name = TextField()

        class Meta:
            database = db
            table_name = "compiled_missing_defaults"

    try:
        Record.create_table()
        first = Record(__no_default__=True, name="first")
        second = Record(__no_default__=True, name="second")
        first.save(force_insert=True)
        second.save(force_insert=True)
        assert Record.get_by_id(first.id).number == 1
        assert Record.get_by_id(second.id).number == 2
    finally:
        Record.drop_table(safe=True)


def test_custom_save_hook_is_not_bypassed(db):
    hooks = []

    class Record(BaseModel):
        _compiled_write_sql = True
        id = AutoField()
        name = TextField()

        def save(self, *args, **kwargs):
            hooks.append(self.name)
            return super().save(*args, **kwargs)

        class Meta:
            database = db
            table_name = "compiled_save_hook"

    try:
        Record.create_table()
        _save_template.cache_clear()
        row = Record.create(name="hooked")
        assert hooks == ["hooked"]
        assert _save_template.cache_info().misses == 0
        assert Record.get_by_id(row.id).name == "hooked"
    finally:
        Record.drop_table(safe=True)


def test_only_save_dirty_and_missing_updates_keep_return_values(db, record):
    row = record.create(name="dirty")
    original = record._meta.only_save_dirty
    try:
        record._meta.only_save_dirty = True
        assert row.save() is False
        row.name = "changed"
        assert row.save() == 1
        row.id = 999999
        row.name = "absent"
        assert row.save() == 0
    finally:
        record._meta.only_save_dirty = original


def test_standard_and_compiled_saves_produce_same_rows(db, record):
    ordinary = record(name="ordinary", data={"a": [1, 2]})
    optimized = record(name="optimized", data={"a": [1, 2]})
    Model.save(ordinary, force_insert=True)
    optimized.save(force_insert=True)
    left = record.get_by_id(ordinary.id).__data__.copy()
    right = record.get_by_id(optimized.id).__data__.copy()
    for data in (left, right):
        data.pop("id")
        data.pop("name")
    assert left == right


def test_foreign_key_instances_and_reassignment_preserve_identity(db, record):
    class Child(BaseModel):
        _compiled_write_sql = True
        id = AutoField()
        parent = ForeignKeyField(record)

        class Meta:
            database = db
            table_name = "compiled_save_child"

    try:
        Child.create_table()
        first = record.create(name="first")
        second = record.create(name="second")
        child = Child.create(parent=first)
        assert child.parent is first
        assert Child.get_by_id(child.id).parent_id == first.id
        child.parent = second
        assert child.save(only=[Child.parent]) == 1
        assert child.parent is second
        assert Child.get_by_id(child.id).parent_id == second.id
    finally:
        Child.drop_table(safe=True)


def test_changed_table_layout_does_not_reuse_cached_write_sql(db, record):
    original = record._meta.table_name
    first = record.create(name="first-table")
    try:
        record._meta.set_table_name("compiled_save_other_table")
        record.create_table()
        second = record.create(name="other-table")
        second.name = "updated-other"
        second.save(only=[record.name])
        assert record.get_by_id(second.id).name == "updated-other"
    finally:
        record.drop_table(safe=True)
        record._meta.set_table_name(original)
    assert record.get_by_id(first.id).name == "first-table"
