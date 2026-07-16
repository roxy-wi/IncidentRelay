from app.modules.db.models import Alert, AlertGroup
from app.services.integrations.auth import hash_token
from app.services.integrations.normalizers.webhook import normalize_webhook
from tests.factories import create_group, create_route, create_team


def pagerduty_trigger(routing_key, **overrides):
    payload = {
        "routing_key": routing_key,
        "event_action": "trigger",
        "dedup_key": "database-prod-01",
        "payload": {
            "summary": "Production database is unavailable",
            "source": "db-prod-01",
            "severity": "error",
            "component": "postgresql",
            "group": "production",
            "class": "database",
            "custom_details": {
                "team": "sre",
                "host": "db-prod-01",
                "replicas": ["db-prod-02", "db-prod-03"],
                "message": "Connection checks are failing",
            },
        },
        "links": [
            {
                "href": "https://monitoring.example.com/incidents/db-prod-01",
                "text": "Open monitoring",
            }
        ],
        "client": "Example Monitor",
        "client_url": "https://monitoring.example.com",
    }
    payload.update(overrides)
    return payload


def test_normalize_webhook_accepts_pagerduty_events_api_v2():
    alert = normalize_webhook(pagerduty_trigger("secret-route-token"))[0]

    assert alert["source"] == "webhook"
    assert alert["integration_format"] == "pagerduty_events_api_v2"
    assert alert["lifecycle_action"] == "trigger"
    assert alert["status"] == "firing"
    assert alert["dedup_key"] == "database-prod-01"
    assert alert["external_id"] == "database-prod-01"
    assert alert["title"] == "Production database is unavailable"
    assert alert["message"] == "Connection checks are failing"
    assert alert["severity"] == "critical"
    assert alert["team_slug"] == "sre"
    assert alert["labels"]["source"] == "db-prod-01"
    assert alert["labels"]["component"] == "postgresql"
    assert alert["labels"]["group"] == "production"
    assert alert["labels"]["class"] == "database"
    assert alert["labels"]["host"] == "db-prod-01"
    assert alert["labels"]["replicas"] == '["db-prod-02", "db-prod-03"]'
    assert alert["labels"]["event_link"] == (
        "https://monitoring.example.com/incidents/db-prod-01"
    )
    assert alert["payload"]["routing_key"] == "[REDACTED]"


def test_pagerduty_trigger_acknowledge_and_resolve_use_webhook_route(client, db):
    raw_token = "pagerduty-compatible-routing-key"
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    route = create_route(
        team,
        source="webhook",
        token_hash=hash_token(raw_token),
    )

    trigger_response = client.post(
        "/api/integrations/webhook",
        json=pagerduty_trigger(raw_token),
    )

    assert trigger_response.status_code == 202
    assert trigger_response.get_json() == {
        "status": "success",
        "message": "Event processed",
        "dedup_key": "database-prod-01",
    }

    alert = Alert.get(Alert.dedup_key == "database-prod-01")
    incident = AlertGroup.get_by_id(alert.group_id)

    assert alert.route_id == route.id
    assert alert.source == "webhook"
    assert alert.status == "firing"
    assert alert.payload["routing_key"] == "[REDACTED]"
    assert incident.status == "firing"

    acknowledge_response = client.post(
        "/api/integrations/webhook",
        json={
            "routing_key": raw_token,
            "event_action": "acknowledge",
            "dedup_key": "database-prod-01",
        },
    )

    assert acknowledge_response.status_code == 202
    incident = AlertGroup.get_by_id(incident.id)
    assert incident.status == "acknowledged"

    resolve_response = client.post(
        "/api/integrations/webhook",
        json={
            "routing_key": raw_token,
            "event_action": "resolve",
            "dedup_key": "database-prod-01",
        },
    )

    assert resolve_response.status_code == 202
    incident = AlertGroup.get_by_id(incident.id)
    alert = Alert.get_by_id(alert.id)
    assert incident.status == "resolved"
    assert alert.status == "resolved"


def test_pagerduty_unknown_follow_up_is_successful_noop(client, db):
    raw_token = "pagerduty-compatible-routing-key"
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    create_route(
        team,
        source="webhook",
        token_hash=hash_token(raw_token),
    )

    response = client.post(
        "/api/integrations/webhook",
        json={
            "routing_key": raw_token,
            "event_action": "resolve",
            "dedup_key": "unknown-dedup-key",
        },
    )

    assert response.status_code == 202
    assert response.get_json()["dedup_key"] == "unknown-dedup-key"


def test_pagerduty_routing_key_must_belong_to_webhook_route(client, db):
    raw_token = "alertmanager-route-token"
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    create_route(
        team,
        source="alertmanager",
        token_hash=hash_token(raw_token),
    )

    response = client.post(
        "/api/integrations/webhook",
        json=pagerduty_trigger(raw_token),
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "route_source_mismatch"


def test_pagerduty_payload_requires_valid_routing_key(client):
    response = client.post(
        "/api/integrations/webhook",
        json=pagerduty_trigger("invalid-routing-key"),
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "Route intake token is required"


def test_pagerduty_acknowledge_requires_dedup_key(client, db):
    raw_token = "pagerduty-compatible-routing-key"
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    create_route(
        team,
        source="webhook",
        token_hash=hash_token(raw_token),
    )

    response = client.post(
        "/api/integrations/webhook",
        json={
            "routing_key": raw_token,
            "event_action": "acknowledge",
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"
