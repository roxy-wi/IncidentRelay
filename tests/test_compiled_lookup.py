import uuid

import pytest
from peewee import AutoField, BooleanField, CompositeKey, DateTimeField, IntegerField, SqliteDatabase, TextField

from app.modules.common import utc_now
from app.modules.db.compiled_lookup import _lookup_template
from app.modules.db.models import BaseModel, Group, JSONTextField, UUIDField
from tests.factories import create_group


def test_compiled_lookup_reuses_sql_but_reads_each_current_row(db, monkeypatch):
    group = create_group()
    _lookup_template.cache_clear()
    expected_sql, expected_params = Group.select().where(Group.id == group.id).limit(1).offset(0).sql()
    calls = []
    execute = db.execute_sql

    def record(sql, params=None, *args, **kwargs):
        if sql.startswith("SELECT"):
            calls.append((sql, tuple(params or ())))
        return execute(sql, params, *args, **kwargs)

    monkeypatch.setattr(db, "execute_sql", record)
    assert Group.get_by_id(group.id).active
    Group.update(active=False, name="Updated").where(Group.id == group.id).execute()
    current = Group.get_by_id(group.id)
    assert (current.active, current.name) == (False, "Updated")
    assert not current._dirty
    assert calls == [(expected_sql, tuple(expected_params))] * 2
    assert _lookup_template.cache_info().misses == 1
    assert _lookup_template.cache_info().hits == 1


def test_missing_primary_key_preserves_model_exception(db):
    with pytest.raises(Group.DoesNotExist):
        Group.get_by_id(2_000_000_000)


def test_container_key_keeps_peewee_expression_semantics(db):
    class Record(BaseModel):
        id = TextField(primary_key=True)

        class Meta:
            database = db
            table_name = "compiled_text_key"

    try:
        Record.create_table()
        Record.create(id="abc")
        assert Record.get_by_id("abc").id == "abc"
        assert Record.get_by_id(["abc"]).id == "abc"
    finally:
        Record.drop_table(safe=True)


def test_compound_filters_are_not_bypassed_by_cached_primary_key(db):
    group = create_group()
    Group.get_by_id(group.id)
    with pytest.raises(Group.DoesNotExist):
        Group.get(Group.id == group.id, Group.active == False)  # noqa: E712
    with pytest.raises(Group.DoesNotExist):
        Group.get(Group.id == group.id, active=False)


def test_custom_select_filters_are_preserved(db):
    class ActiveRecord(BaseModel):
        id = AutoField()
        active = BooleanField(default=True)

        @classmethod
        def select(cls, *fields):
            return super().select(*fields).where(cls.active == True)  # noqa: E712

        class Meta:
            database = db
            table_name = "compiled_active_record"

    try:
        db.create_tables([ActiveRecord])
        hidden = ActiveRecord.create(active=False)
        with pytest.raises(ActiveRecord.DoesNotExist):
            ActiveRecord.get_by_id(hidden.id)
        visible = ActiveRecord.create(active=True)
        assert ActiveRecord.get_by_id(visible.id).id == visible.id
    finally:
        ActiveRecord.drop_table(safe=True)


def test_lookup_preserves_uuid_json_boolean_and_datetime_conversions(db):
    class Record(BaseModel):
        id = UUIDField(primary_key=True)
        data = JSONTextField()
        enabled = BooleanField()
        at = DateTimeField()

        class Meta:
            database = db
            table_name = "compiled_typed_record"

    key = uuid.uuid4()
    now = utc_now()
    try:
        db.create_tables([Record])
        Record.create(id=key, data={"nested": [1, True, "x"]}, enabled=False, at=now)
        row = Record.get_by_id(key)
        assert row.id == key
        assert row.data == {"nested": [1, True, "x"]}
        assert row.enabled is False
        assert row.at == now
    finally:
        Record.drop_table(safe=True)


def test_bound_database_and_table_layout_do_not_reuse_wrong_template(db):
    class Record(BaseModel):
        id = AutoField()
        value = TextField()

        class Meta:
            database = db
            table_name = "compiled_bound_record"

    databases = [SqliteDatabase(":memory:"), SqliteDatabase(":memory:")]
    try:
        for index, database in enumerate(databases):
            with database.bind_ctx([Record]):
                Record.create_table()
                Record.create(id=1, value=str(index))
                assert Record.get_by_id(1).value == str(index)
                Record._meta.set_table_name("compiled_second_record")
                Record.create_table()
                Record.create(id=1, value="new-table")
                assert Record.get_by_id(1).value == "new-table"
                Record._meta.set_table_name("compiled_bound_record")
    finally:
        for database in databases:
            database.close()


def test_composite_primary_key_retains_standard_lookup(db):
    class Pair(BaseModel):
        first = IntegerField()
        second = IntegerField()

        class Meta:
            database = db
            primary_key = CompositeKey("first", "second")
            table_name = "compiled_pair"

    try:
        Pair.create_table()
        Pair.create(first=1, second=2)
        assert Pair.get_by_id((1, 2)).second == 2
    finally:
        Pair.drop_table(safe=True)
