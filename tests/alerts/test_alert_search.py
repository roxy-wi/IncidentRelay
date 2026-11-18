"""Search labels without losing exactness, pagination or authorization scope."""

import json
from types import SimpleNamespace

import pytest
from peewee import MySQLDatabase, PostgresqlDatabase, SqliteDatabase

from app.login import create_access_token
from app.modules.db import alert_search
from app.modules.db.models import Alert, AlertGroup
from tests.factories import add_user_to_team, create_group, create_team, create_user, unique


def make_group(team=None, **fields):
    """Keep searchable labels out of titles and grouping keys."""
    key = unique("search-group")
    return AlertGroup.create(
        team=team or create_team(create_group()), source="webhook",
        group_key=key, group_key_hash=key, title="Monitoring signal", **fields,
    )


def add_alert(group, **fields):
    """Create a child without copying its labels into the group snapshot."""
    return Alert.create(
        group=group, team=group.team, source="webhook", dedup_key=unique("search-child"),
        group_key=group.group_key, title="Child signal", **fields,
    )


def search(client, headers, term, **filters):
    response = client.get("/api/alert-groups", headers=headers, query_string={"search": term, **filters})
    assert response.status_code == 200, response.json
    return response.json


@pytest.mark.parametrize("field", ["common_labels", "label_values", "payload_summary", "labels", "payload"])
@pytest.mark.parametrize("value", ["rack7", "NET_GOBGPD_GROUP", "100% busy", 'rack "seven"', r"C:\rack7", "Москва"])
def test_free_text_finds_json_values(client, admin_headers, field, value):
    group = make_group()
    if field in {"labels", "payload"}:
        add_alert(group, **{field: {"location": value}})
    else:
        stored = [value, "elsewhere"] if field == "label_values" else value
        AlertGroup.update({getattr(AlertGroup, field): {"location": stored}}).where(AlertGroup.id == group.id).execute()
    assert [item["id"] for item in search(client, admin_headers, value)["items"]] == [group.id]


@pytest.mark.parametrize("location", ["common", "child"])
@pytest.mark.parametrize(("key", "value", "term"), [
    ("rack", "rack7", "rack=rack7"),
    ("rack", "rack7", "  rack = rack7  "),
    ("team", "Platform Ops", 'team="Platform Ops"'),
    ("team", "Platform Ops", "team=Platform Ops"),
    ("rack", "", 'rack=""'),
    ("rack", "", "rack="),
    ("rack", " padded ", 'rack=" padded "'),
    ("app.kubernetes.io/name", "api=primary", "app.kubernetes.io/name=api=primary"),
    ("rack", "100%_ready", "rack=100%_ready"),
    ("rack", 'a"b\\c', 'rack=' + json.dumps('a"b\\c')),
    ("rack", "Москва", "rack=Москва"),
    ("rack", "x' OR 1=1 --", 'rack="x\' OR 1=1 --"'),
    ("priority", 2, "priority=2"),
    ("priority", "2", "priority=2"),
    ("rack", "null", "rack=null"),
    ("enabled", True, "enabled=true"),
    ("enabled", False, "enabled=false"),
])
def test_label_equals_matches_complete_scalar_value(client, admin_headers, location, key, value, term):
    group = make_group(common_labels={key: value} if location == "common" else {})
    if location == "child":
        add_alert(group, labels={key: value})
    other = make_group(common_labels={"another": value, key: "prefix" + str(value) + "suffix"})
    add_alert(other, labels={key: {"nested": value}}, message=term)
    assert [item["id"] for item in search(client, admin_headers, term)["items"]] == [group.id]


@pytest.mark.parametrize("term", ["rack=rack7", "rack=RACK7", "rack=", "rack=null", "rack=1", "rack=true"])
def test_label_equals_does_not_match_missing_null_nested_or_other_fields(client, admin_headers, term):
    for labels in (None, {}, {"rack": None}, {"nested": {"rack": "rack7"}}, {"rack": ["rack7"]}):
        group = make_group(common_labels=labels, payload_summary={"rack": term.split("=", 1)[1]})
        add_alert(group, labels=labels, message=term)
        AlertGroup.update(group_key=term, title=term).where(AlertGroup.id == group.id).execute()
    assert search(client, admin_headers, term)["pagination"]["total_items"] == 0


def test_label_equals_is_case_sensitive_and_treats_dotted_keys_literally(client, admin_headers):
    match = make_group(common_labels={"rack.zone": "West"})
    make_group(common_labels={"rack.zone": "west"})
    make_group(common_labels={"Rack.zone": "West"})
    make_group(common_labels={"rack": {"zone": "West"}})
    assert [item["id"] for item in search(client, admin_headers, "rack.zone=West")["items"]] == [match.id]


@pytest.mark.parametrize("term", ['rack="unfinished', 'rack="bad\\q"', 'rack="value" extra'])
def test_invalid_quoted_label_search_is_a_validation_error(client, admin_headers, term):
    response = client.get("/api/alert-groups", headers=admin_headers, query_string={"search": term})
    assert response.status_code == 400
    assert "search" in str(response.json)


@pytest.mark.parametrize("term", ["query=value", "rack7"])
def test_label_search_keeps_pagination_filters_and_access_boundaries(client, term):
    tenant = create_group()
    team = create_team(tenant)
    user = create_user(group=tenant, group_role="viewer")
    add_user_to_team(team, user, "viewer")
    headers = {"Authorization": "Bearer " + create_access_token(user)[0]}
    visible = []
    for _ in range(3):
        group = make_group(team, common_labels={"query": "value", "rack": "rack7"})
        for _ in range(2):
            add_alert(group, labels={"query": "value", "rack": "rack7"})
        visible.append(group.id)
    make_group(team, status="resolved", common_labels={"query": "value", "rack": "rack7"})
    make_group(common_labels={"query": "value", "rack": "rack7"})
    data = search(client, headers, term, status="firing", page=2, page_size=1, sort="id", order="asc")
    assert [item["id"] for item in data["items"]] == [visible[1]]
    assert data["pagination"]["total_items"] == 3
    assert data["pagination"]["total_pages"] == 3


def test_plain_text_with_an_equals_sign_keeps_literal_search(client, admin_headers):
    group = make_group(message="Request https://example.test/?code=failed")
    assert [item["id"] for item in search(client, admin_headers, "https://example.test/?code=failed")["items"]] == [group.id]


@pytest.mark.parametrize("value", ["100% busy", "rack_7", r"rack\7"])
def test_free_text_treats_sql_wildcards_as_literals(client, admin_headers, value):
    match = make_group(common_labels={"rack": value})
    make_group(common_labels={"rack": "1000 busy rackX7 rack7"})
    assert [item["id"] for item in search(client, admin_headers, value)["items"]] == [match.id]


def test_label_filter_matches_varying_child_values_without_duplicate_groups(client, admin_headers):
    group = make_group(common_labels={}, label_values={"rack": ["east", "west"]})
    for value in ("east", "west", "west"):
        add_alert(group, labels={"rack": value})
    for value in ("east", "west"):
        data = search(client, admin_headers, "rack=" + value)
        assert [item["id"] for item in data["items"]] == [group.id]
        assert data["pagination"]["total_items"] == 1


def test_numeric_label_key_does_not_index_a_json_array(client, admin_headers):
    match = make_group(common_labels={"0": "rack7"})
    make_group(common_labels=["rack7"])
    assert [item["id"] for item in search(client, admin_headers, "0=rack7")["items"]] == [match.id]


@pytest.mark.parametrize(("backend", "function"), [
    (SqliteDatabase, "json_extract"),
    (PostgresqlDatabase, "jsonb_extract_path_text"),
    (MySQLDatabase, "JSON_UNQUOTE"),
])
def test_label_sql_binds_parameters_on_every_supported_backend(monkeypatch, backend, function):
    database = backend("unused")
    monkeypatch.setattr(alert_search, "database_proxy", SimpleNamespace(obj=database))
    key, value = "app.kubernetes.io/name", 'a"b\\c%_\' --'
    query = Alert.select(Alert.id).where(
        alert_search.label_equals(Alert.labels, key, value)
        | alert_search.json_text_contains(Alert.payload, "rack7")
    ).bind(database)
    sql, parameters = query.sql()
    assert function in sql
    assert key not in sql and value not in sql
    assert value in parameters
    assert "%rack7%" in parameters
    assert '"%rack7%"' not in parameters
