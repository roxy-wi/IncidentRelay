"""OpenSearch Alerting and Kibana Alerting intake regression coverage."""

from copy import deepcopy

import pytest

from app.api.openapi.spec import build_openapi_spec
from app.api.openapi.endpoints.routes import SOURCE_SCHEMA_WITH_SENTRY
from app.api.schemas.integrations import KibanaWebhookSchema, OpenSearchWebhookSchema
from app.api.schemas.routes import RouteCreateSchema
from app.modules.db.models import Alert, AlertGroup
from app.services.integrations.auth import hash_token
from app.services.integrations.normalizers.kibana import normalize_kibana
from app.services.integrations.normalizers.opensearch import normalize_opensearch
from app.services.integrations.normalizers.registry import normalize_for_source
from tests.factories import create_group, create_route, create_team


def opensearch_payload(**overrides):
    data = {
        "monitor_id": "monitor-prod-1",
        "trigger_id": "trigger-errors",
        "monitor_name": "API error rate",
        "trigger_name": "5xx threshold",
        "alert_id": "record-123",
        "severity": "2",
        "status": "ACTIVE",
        "message": "API errors exceed threshold",
        "monitor_url": "https://search.example/_dashboards/app/alerting#/monitors/monitor-prod-1",
        "labels": {"team": "sre", "environment": "production"},
    }
    data.update(overrides)
    return data


def kibana_payload(**overrides):
    data = {
        "rule_id": "rule-api-errors",
        "alert_id": "api-01",
        "space_id": "default",
        "rule_name": "HTTP 5xx",
        "status": "active",
        "severity": "critical",
        "message": "5xx rate exceeded 5%",
        "rule_url": "https://kibana.example/app/management/insightsAndAlerting/triggersActions/rule/rule-api-errors",
        "labels": {"team": "sre", "service": "api"},
    }
    data.update(overrides)
    return data


def test_normalize_opensearch_query_monitor_and_recovery():
    firing = normalize_opensearch(opensearch_payload())[0]
    recovered = normalize_opensearch(opensearch_payload(
        status="COMPLETED", severity="5", message="Recovered", alert_id="record-456",
    ))[0]

    assert firing["source"] == "opensearch"
    assert firing["team_slug"] == "sre"
    assert firing["severity"] == "high"
    assert firing["status"] == "firing"
    assert firing["labels"]["opensearch_trigger_id"] == "trigger-errors"
    assert firing["labels"]["event_link"].startswith("https://")
    assert recovered["status"] == "resolved"
    assert firing["dedup_key"] == recovered["dedup_key"]


def test_opensearch_bucket_keys_differentiate_signal_and_route_scopes():
    one = normalize_opensearch(opensearch_payload(bucket_key="api-01"), route_id=1)[0]
    other_bucket = normalize_opensearch(opensearch_payload(bucket_key="api-02"), route_id=1)[0]
    other_route = normalize_opensearch(opensearch_payload(bucket_key="api-01"), route_id=2)[0]
    same = normalize_opensearch(opensearch_payload(bucket_key="api-01"), route_id=1)[0]
    assert len({one["dedup_key"], other_bucket["dedup_key"], other_route["dedup_key"]}) == 3
    assert one["dedup_key"] == same["dedup_key"]


def test_opensearch_bucket_key_array_is_stable():
    one = normalize_opensearch(opensearch_payload(
        bucket_keys=["region:west", "service:api"]
    ))[0]
    two = normalize_opensearch(opensearch_payload(
        bucket_keys=["region:west", "service:api"], status="COMPLETED"
    ))[0]
    distinct = normalize_opensearch(opensearch_payload(
        bucket_keys=["region:west", "service:worker"]
    ))[0]
    assert one["dedup_key"] == two["dedup_key"]
    assert one["dedup_key"] != distinct["dedup_key"]


def test_opensearch_nested_ctx_monitor_trigger_supported():
    raw = {
        "ctx": {
            "monitor": {"id": "m1", "name": "Monitor"},
            "trigger": {"id": "t1", "severity": "1"},
            "alert": {"state": "ACKNOWLEDGED"},
        }
    }
    normalized = normalize_opensearch(raw)[0]
    assert normalized["status"] == "firing"  # ACK != recovery
    assert normalized["severity"] == "critical"
    assert normalized["labels"]["opensearch_monitor_id"] == "m1"


def test_opensearch_only_http_source_links_are_exposed():
    event = normalize_opensearch(opensearch_payload(monitor_url="javascript:alert(1)"))[0]
    assert "event_link" not in event["labels"]


def test_normalize_kibana_trigger_recovery_and_flapping_flag():
    firing = normalize_kibana(kibana_payload(flapping="true"))[0]
    recovered = normalize_kibana(kibana_payload(
        status="recovered", message="Service recovered", rule_name="New title", flapping=False,
    ))[0]

    assert firing["status"] == "firing"
    assert recovered["status"] == "resolved"
    assert firing["dedup_key"] == recovered["dedup_key"]
    assert firing["labels"]["kibana_flapping"] == "true"
    assert recovered["labels"]["kibana_flapping"] == "false"
    assert firing["team_slug"] == "sre"
    assert firing["external_id"] == "api-01"


def test_kibana_rule_and_space_prevent_identity_collisions():
    base = normalize_kibana(kibana_payload(), route_id=9)[0]
    other_rule = normalize_kibana(kibana_payload(rule_id="another-rule"), route_id=9)[0]
    other_space = normalize_kibana(kibana_payload(space_id="security"), route_id=9)[0]
    other_route = normalize_kibana(kibana_payload(), route_id=10)[0]
    assert len({x["dedup_key"] for x in (base, other_rule, other_space, other_route)}) == 4


def test_kibana_nested_rule_alert_action_group_supported():
    event = normalize_kibana({
        "rule": {"id": "r123", "name": "Rule", "spaceId": "ops"},
        "alert": {"id": "a456", "actionGroup": "recovered"},
        "labels": {"environment": "production", "host": {"name": "api"}},
    })[0]
    assert event["status"] == "resolved"
    assert event["labels"]["kibana_space_id"] == "ops"
    assert event["labels"]["host"] == '{"name": "api"}'


def test_recovery_never_inferred_from_missing_webhooks():
    assert normalize_opensearch(opensearch_payload(status=None))[0]["status"] == "firing"
    assert normalize_kibana(kibana_payload(status=None))[0]["status"] == "firing"


@pytest.mark.parametrize("schema,body", [
    (OpenSearchWebhookSchema, {"monitor_id": "m1"}),
    (OpenSearchWebhookSchema, {"monitor_id": "", "trigger_id": "t1"}),
    (KibanaWebhookSchema, {"rule_id": "r1"}),
    (KibanaWebhookSchema, {"rule_id": "r1", "alert_id": ""}),
])
def test_schema_requires_stable_ids(schema, body):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        schema.model_validate(body)


def test_schema_accepts_nested_ids_and_extra_fields():
    opensearch = OpenSearchWebhookSchema.model_validate({
        "monitor": {"id": 12}, "trigger": {"id": 5}, "status": "active",
    })
    kibana = KibanaWebhookSchema.model_validate({
        "rule": {"id": "rule-1"}, "alert": {"id": "instance-1"}, "reason": "CPU",
    })
    assert opensearch.ctx == {}
    assert kibana.model_dump()["reason"] == "CPU"


def test_routes_schema_and_openapi_include_both_integrations():
    spec = build_openapi_spec()
    route_sources = SOURCE_SCHEMA_WITH_SENTRY["enum"]
    for source in ("opensearch", "kibana"):
        assert RouteCreateSchema(team_id=1, name="Search alert", source=source).source == source
        assert source in route_sources
        assert f"/api/integrations/{source}" in spec["paths"]
        operation = spec["paths"][f"/api/integrations/{source}"]["post"]
        assert operation["security"] == [{"bearerAuth": []}]


def _route_with_token(source, token, *, group=None):
    group = group or create_group()
    team = create_team(group)
    return create_route(
        team,
        source=source,
        token_hash=hash_token(token),
        group_by=(
            ["opensearch_monitor_id", "opensearch_trigger_id", "opensearch_bucket_key"]
            if source == "opensearch" else ["kibana_rule_id", "kibana_alert_id"]
        ),
    )


@pytest.mark.parametrize("source,payload", [
    ("opensearch", opensearch_payload), ("kibana", kibana_payload),
])
def test_endpoints_require_route_token(client, source, payload):
    res = client.post(f"/api/integrations/{source}", json=payload())
    assert res.status_code == 401
    assert res.get_json()["error"] == "Route intake token is required"


@pytest.mark.parametrize("source,other,payload", [
    ("opensearch", "kibana", opensearch_payload),
    ("kibana", "opensearch", kibana_payload),
])
def test_endpoints_reject_token_for_other_source(client, db, source, other, payload):
    token = f"wrong-source-{source}"
    _route_with_token(other, token)
    res = client.post(
        f"/api/integrations/{source}",
        headers={"Authorization": f"Bearer {token}"}, json=payload(),
    )
    assert res.status_code == 400
    assert res.get_json()["error"] == "route_source_mismatch"


@pytest.mark.parametrize("source,payload", [
    ("opensearch", opensearch_payload), ("kibana", kibana_payload),
])
def test_endpoints_reject_incomplete_identity(client, db, source, payload):
    token = f"schema-{source}"
    _route_with_token(source, token)
    data = payload()
    data.pop("monitor_id" if source == "opensearch" else "alert_id")
    res = client.post(
        f"/api/integrations/{source}",
        headers={"Authorization": f"Bearer {token}"}, json=data,
    )
    assert res.status_code == 400


@pytest.mark.parametrize("source,payload,active,resolved", [
    ("opensearch", opensearch_payload, "ACTIVE", "COMPLETED"),
    ("kibana", kibana_payload, "active", "recovered"),
])
def test_firing_update_recovery_lifecycle(client, db, source, payload, active, resolved):
    token = f"lifecycle-{source}"
    route = _route_with_token(source, token)
    headers = {"Authorization": f"Bearer {token}"}
    endpoint = f"/api/integrations/{source}"

    first = client.post(endpoint, headers=headers, json=payload(status=active))
    assert first.status_code == 200
    created = first.get_json()[0]
    assert created["created"] is True

    updated = client.post(endpoint, headers=headers, json=payload(status=active, message="Updated text"))
    assert updated.status_code == 200
    same = updated.get_json()[0]
    assert same["group_id"] == created["group_id"]
    assert same["alert_id"] == created["alert_id"]

    finished = client.post(endpoint, headers=headers, json=payload(status=resolved))
    assert finished.status_code == 200
    closed = finished.get_json()[0]
    assert closed["group_id"] == created["group_id"]
    assert closed["alert_id"] == created["alert_id"]
    assert Alert.get_by_id(closed["alert_id"]).status == "resolved"
    assert AlertGroup.get_by_id(closed["group_id"]).status == "resolved"
    assert Alert.get_by_id(closed["alert_id"]).route_id == route.id

    again = client.post(endpoint, headers=headers, json=payload(status=active))
    assert again.status_code == 200
    restarted = again.get_json()[0]
    assert restarted["group_id"] != created["group_id"]
    assert restarted["alert_id"] != created["alert_id"]
    assert Alert.get_by_id(created["alert_id"]).status == "resolved"


def test_route_tokens_isolate_same_provider_identity(client, db):
    group = create_group()
    routes = [
        _route_with_token("kibana", f"kibana-token-{i}", group=group)
        for i in (1, 2)
    ]
    results = []
    for i, _route in enumerate(routes, 1):
        response = client.post(
            "/api/integrations/kibana",
            json=kibana_payload(),
            headers={"Authorization": f"Bearer kibana-token-{i}"},
        )
        assert response.status_code == 200
        results.append(response.get_json()[0]["group_id"])
    assert len(set(results)) == 2


def test_registry_simulator_normalization_does_not_mutate_payload():
    for source, data in (
        ("opensearch", opensearch_payload()),
        ("kibana", kibana_payload()),
    ):
        original = deepcopy(data)
        one = normalize_for_source(source, data, copy_payload=True)
        assert one[0]["source"] == source
        assert data == original
        assert one[0]["dedup_key"] == normalize_for_source(source, data, copy_payload=True)[0]["dedup_key"]
