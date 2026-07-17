from copy import deepcopy

from app.api.schemas.routes import RouteCreateSchema
from app.modules.db.models import Alert, AlertGroup
from app.services.integrations.auth import hash_token
from app.services.integrations.normalizers.datadog import normalize_datadog
from tests.factories import create_group, create_route, create_team


def datadog_payload(**overrides):
    payload = {
        "alert_title": "[Triggered] API latency is high",
        "text_only_msg": "p95 latency exceeded 2 seconds",
        "alert_id": "1234",
        "alert_cycle_key": "cycle-1234-prod-api",
        "aggreg_key": "monitor-1234-prod-api",
        "alert_transition": "Triggered",
        "alert_type": "error",
        "alert_priority": "P1",
        "alert_scope": "env:prod,service:api,host:api-01",
        "alert_metric": "trace.http.request.duration",
        "event_type": "query_alert_monitor",
        "event_id": "98765",
        "hostname": "api-01",
        "link": "https://app.datadoghq.com/monitors/1234",
        "tags": "env:prod,service:api,team:sre,monitor",
    }
    payload.update(overrides)
    return payload


def test_normalize_datadog_trigger():
    alert = normalize_datadog(datadog_payload())[0]

    assert alert["source"] == "datadog"
    assert alert["team_slug"] == "sre"
    assert alert["status"] == "firing"
    assert alert["severity"] == "critical"
    assert alert["title"] == "[Triggered] API latency is high"
    assert alert["message"] == "p95 latency exceeded 2 seconds"
    assert alert["external_id"] == "cycle-1234-prod-api"
    assert alert["dedup_key"] == "cycle-1234-prod-api"

    assert alert["labels"]["env"] == "prod"
    assert alert["labels"]["service"] == "api"
    assert alert["labels"]["team"] == "sre"
    assert alert["labels"]["monitor"] == "true"
    assert alert["labels"]["datadog_alert_id"] == "1234"
    assert alert["labels"]["datadog_scope"] == (
        "env:prod,service:api,host:api-01"
    )
    assert alert["labels"]["event_link"].endswith("/monitors/1234")


def test_datadog_recovery_uses_same_dedup_key():
    firing = normalize_datadog(datadog_payload())[0]
    recovered_payload = datadog_payload(
        alert_title="[Recovered] API latency is high",
        alert_transition="Recovered",
        alert_type="success",
    )
    recovered = normalize_datadog(recovered_payload)[0]

    assert firing["status"] == "firing"
    assert recovered["status"] == "resolved"
    assert firing["dedup_key"] == recovered["dedup_key"]


def test_datadog_accepts_uppercase_variable_names():
    payload = {
        "ALERT_TITLE": "[Triggered] Host down",
        "TEXT_ONLY_MSG": "Host is unreachable",
        "ALERT_ID": "44",
        "ALERT_CYCLE_KEY": "cycle-host-44",
        "ALERT_TRANSITION": "Re-Triggered",
        "ALERT_TYPE": "warning",
        "ALERT_SCOPE": "env:prod,host:web-01",
        "HOSTNAME": "web-01",
        "LINK": "https://app.datadoghq.com/monitors/44",
        "TAGS": ["team:ops", "service:web"],
    }

    alert = normalize_datadog(payload)[0]

    assert alert["dedup_key"] == "cycle-host-44"
    assert alert["status"] == "firing"
    assert alert["severity"] == "warning"
    assert alert["team_slug"] == "ops"
    assert alert["labels"]["service"] == "web"


def test_datadog_fallback_dedup_key_is_stable():
    payload = datadog_payload(
        alert_cycle_key=None,
        aggreg_key=None,
    )

    first = normalize_datadog(deepcopy(payload))[0]
    second = normalize_datadog(deepcopy(payload))[0]

    assert first["dedup_key"] == second["dedup_key"]


def test_route_schema_accepts_datadog():
    route = RouteCreateSchema(
        team_id=1,
        name="Datadog production monitors",
        source="datadog",
    )

    assert route.source == "datadog"


def test_datadog_endpoint_requires_token(client):
    response = client.post(
        "/api/integrations/datadog",
        json=datadog_payload(),
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "Route intake token is required"


def test_datadog_endpoint_rejects_token_from_another_source(client, db):
    raw_token = "not-a-datadog-route-token"
    group = create_group(slug="platform")
    team = create_team(group, slug="sre")
    create_route(
        team,
        source="grafana",
        token_hash=hash_token(raw_token),
    )

    response = client.post(
        "/api/integrations/datadog",
        headers={"Authorization": f"Bearer {raw_token}"},
        json=datadog_payload(),
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "route_source_mismatch"


def test_datadog_trigger_and_recovery_update_existing_alert(client, db):
    raw_token = "datadog-route-token"
    group = create_group(slug="platform")
    team = create_team(group, slug="sre")
    route = create_route(
        team,
        source="datadog",
        token_hash=hash_token(raw_token),
        group_by=["datadog_alert_id", "datadog_scope"],
    )
    headers = {"Authorization": f"Bearer {raw_token}"}

    firing_response = client.post(
        "/api/integrations/datadog",
        headers=headers,
        json=datadog_payload(),
    )

    assert firing_response.status_code == 200
    firing_result = firing_response.get_json()[0]
    assert firing_result["created"] is True
    assert firing_result["status"] == "firing"

    recovery_response = client.post(
        "/api/integrations/datadog",
        headers=headers,
        json=datadog_payload(
            alert_title="[Recovered] API latency is high",
            alert_transition="Recovered",
            alert_type="success",
        ),
    )

    assert recovery_response.status_code == 200
    recovery_result = recovery_response.get_json()[0]
    assert recovery_result["created"] is False
    assert recovery_result["status"] == "resolved"
    assert recovery_result["alert_id"] == firing_result["alert_id"]
    assert recovery_result["group_id"] == firing_result["group_id"]

    alert = Alert.get_by_id(firing_result["alert_id"])
    alert_group = AlertGroup.get_by_id(firing_result["group_id"])

    assert alert.source == "datadog"
    assert alert.status == "resolved"
    assert alert.dedup_key == "cycle-1234-prod-api"
    assert alert.route_id == route.id
    assert alert_group.status == "resolved"
