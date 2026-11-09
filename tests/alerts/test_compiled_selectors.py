import pytest
from peewee import AutoField, BooleanField, TextField

from app.modules.db import alerts_repo, compiled_select
from app.modules.db.models import Alert, AlertGroup, BaseModel
from tests.factories import create_group, create_route, create_team


@pytest.mark.parametrize("entity", ["alert", "group"])
def test_compiled_selector_executes_identical_sql_and_parameters(db, monkeypatch, entity):
    team = create_team(create_group())
    route = create_route(team)
    if entity == "alert":
        factory, model = alerts_repo._existing_alert_query, Alert
        bindings = {"source": (Alert.source, "test"), "dedup_key": (Alert.dedup_key, "key"),
                    "route": (Alert.route, route.id)}
    else:
        factory, model = alerts_repo._open_group_query, AlertGroup
        bindings = {"source": (AlertGroup.source, "test"),
                    "group_key_hash": (AlertGroup.group_key_hash, alerts_repo.hash_group_key("key")),
                    "team": (AlertGroup.team, team.id), "route": (AlertGroup.route, route.id)}
    calls = []
    execute = db.execute_sql

    def capture(sql, params=None, *args, **kwargs):
        calls.append((sql, tuple(params or ())))
        return execute(sql, params, *args, **kwargs)

    monkeypatch.setattr(db, "execute_sql", capture)
    assert compiled_select.ordinary_first(model, factory, bindings) is None
    expected = calls.pop()
    assert compiled_select.first(model, factory, bindings) is None
    assert calls == [expected]


def test_cached_dedup_lookup_keeps_route_scope_and_sees_resolves(db):
    team = create_team(create_group())
    first_route, other_route = create_route(team), create_route(team)
    first_group = alerts_repo.create_alert_group(team=team, route=first_route, source="test", group_key="first", title="First")
    other_group = alerts_repo.create_alert_group(team=team, route=other_route, source="test", group_key="other", title="Other")
    first = Alert.create(group=first_group, source="test", dedup_key="same-key", group_key="first", title="First", route=first_route)
    other = Alert.create(group=other_group, source="test", dedup_key="same-key", group_key="other", title="Other", route=other_route)
    for _ in range(2):
        assert alerts_repo.find_existing_alert("test", "same-key", route_id=first_route.id).id == first.id
        assert alerts_repo.find_existing_alert("test", "same-key", route_id=other_route.id).id == other.id
    first.status = "resolved"
    first.save(only=[Alert.status])
    assert alerts_repo.find_existing_alert("test", "same-key", route_id=first_route.id) is None
    assert alerts_repo.find_existing_alert("test", "same-key").id == other.id


def test_cached_group_lookup_binds_each_identity_and_excludes_terminal_groups(db):
    team = create_team(create_group())
    route = create_route(team)
    first = alerts_repo.create_alert_group(team=team, route=route, source="test", title="Test", group_key="first")
    second = alerts_repo.create_alert_group(team=team, route=route, source="test", title="Test", group_key="second")
    for group in (first, second, first):
        assert alerts_repo.find_open_alert_group("test", group.group_key, team.id, route.id).id == group.id
    second.status = "merged"
    second.save(only=[AlertGroup.status])
    assert alerts_repo.find_open_alert_group("test", "second", team.id, route.id) is None
    assert alerts_repo.find_open_alert_group("test", "first", team.id + 100, route.id) is None


def test_null_selector_inputs_retain_original_expression_semantics(db):
    assert alerts_repo.find_existing_alert(None, None) is None
    assert alerts_repo.find_open_alert_group(None, None) is None


def test_custom_select_security_filter_is_not_bypassed(db):
    class Record(BaseModel):
        id = AutoField()
        name = TextField()
        visible = BooleanField(default=False)

        @classmethod
        def select(cls, *fields):
            return super().select(*fields).where(cls.visible == True)  # noqa: E712

        class Meta:
            database = db
            table_name = "compiled_selector_filtered"

    def query(parameters):
        return Record.select().where(Record.name == parameters["name"])

    try:
        Record.create_table()
        row = Record.create(name="hidden")
        bindings = {"name": (Record.name, "hidden")}
        assert compiled_select.first(Record, query, bindings) is None
        row.visible = True
        row.save()
        assert compiled_select.first(Record, query, bindings).id == row.id
    finally:
        Record.drop_table(safe=True)
