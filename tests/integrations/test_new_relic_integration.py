from copy import deepcopy
from pathlib import Path

from app.api.openapi.endpoints.integrations import paths as integration_paths
from app.api.openapi.endpoints.routes import SOURCE_SCHEMA_WITH_SENTRY
from app.api.schemas.routes import RouteCreateSchema
from app.modules.db.models import Alert, AlertGroup
from app.services.integrations.auth import hash_token
from app.services.integrations.normalizers.new_relic import normalize_new_relic
from tests.factories import create_group, create_route, create_team


def new_relic_payload(**overrides):
    payload = {
        "issue_id": "issue-abc-123",
        "title": "API latency is high",
        "message": "p95 latency exceeded 2 seconds",
        "state": "ACTIVATED",
        "status": "CREATED",
        "priority": "CRITICAL",
        "issue_url": "https://one.newrelic.com/redirects/issue/issue-abc-123",
        "condition_name": "API latency",
        "policy_name": "Production API",
        "entity_guid": "MTIzfEFQTXxBUFBMSUNBVElPTnwx",
        "entity_name": "checkout-api",
        "entity_type": "APPLICATION",
        "labels": {
            "environment": "production",
            "service": "checkout",
            "team": "sre",
        },
    }
    payload.update(overrides)
    return payload


def test_normalize_new_relic_workflow_payload():
    alert = normalize_new_relic(new_relic_payload())[0]

    assert alert["source"] == "new_relic"
    assert alert["team_slug"] == "sre"
    assert alert["status"] == "firing"
    assert alert["severity"] == "critical"
    assert alert["title"] == "API latency is high"
    assert alert["message"] == "p95 latency exceeded 2 seconds"
    assert alert["external_id"] == "issue-abc-123"
    assert alert["dedup_key"] == "issue-abc-123"
    assert alert["labels"]["new_relic_issue_id"] == "issue-abc-123"
    assert alert["labels"]["new_relic_condition"] == "API latency"
    assert alert["labels"]["new_relic_entity_name"] == "checkout-api"
    assert alert["labels"]["environment"] == "production"
    assert alert["labels"]["event_link"].endswith("issue/issue-abc-123")


def test_new_relic_closed_issue_uses_same_dedup_key():
    firing = normalize_new_relic(new_relic_payload())[0]
    closed = normalize_new_relic(
        new_relic_payload(
            state="CLOSED",
            status="CLOSED",
        )
    )[0]

    assert firing["status"] == "firing"
    assert closed["status"] == "resolved"
    assert firing["dedup_key"] == closed["dedup_key"]


def test_new_relic_native_camel_case_payload_is_supported():
    payload = {
        "issueId": "issue-native-1",
        "issueTitle": "Database connections exhausted",
        "issuePageUrl": "https://one.newrelic.com/redirects/issue/issue-native-1",
        "priority": "HIGH",
        "state": "ACTIVATED",
        "status": "CREATED",
        "accumulations": {
            "conditionName": ["DB connection pool"],
            "policyName": ["Production DB"],
            "targetName": ["postgres-primary"],
            "rawTag": {
                "environment": ["production"],
                "team": ["database"],
                "service": ["postgres"],
            },
        },
        "entitiesData": {
            "entities": [
                {
                    "id": "entity-guid-1",
                    "name": "postgres-primary",
                }
            ],
            "types": ["HOST"],
        },
    }

    alert = normalize_new_relic(payload)[0]

    assert alert["dedup_key"] == "issue-native-1"
    assert alert["severity"] == "high"
    assert alert["team_slug"] == "database"
    assert alert["labels"]["new_relic_condition"] == "DB connection pool"
    assert alert["labels"]["new_relic_policy"] == "Production DB"
    assert alert["labels"]["new_relic_entity_guid"] == "entity-guid-1"
    assert alert["labels"]["service"] == "postgres"


def test_new_relic_issue_closed_at_marks_event_resolved():
    payload = new_relic_payload(
        state="ACTIVATED",
        status="UPDATED",
        issueClosedAt="2026-08-24T05:00:00Z",
    )

    assert normalize_new_relic(payload)[0]["status"] == "resolved"


def test_new_relic_fallback_dedup_key_is_stable():
    payload = new_relic_payload(
        issue_id=None,
        entity_guid=None,
    )

    first = normalize_new_relic(deepcopy(payload))[0]
    second = normalize_new_relic(deepcopy(payload))[0]

    assert first["dedup_key"] == second["dedup_key"]


def test_route_schema_accepts_new_relic():
    route = RouteCreateSchema(
        team_id=1,
        name="New Relic production alerts",
        source="new_relic",
    )

    assert route.source == "new_relic"


def test_new_relic_endpoint_requires_token(client):
    response = client.post(
        "/api/integrations/new-relic",
        json=new_relic_payload(),
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "Route intake token is required"


def test_new_relic_endpoint_rejects_token_from_another_source(client, db):
    raw_token = "not-a-new-relic-token"
    group = create_group(slug="platform")
    team = create_team(group, slug="sre")
    create_route(
        team,
        source="grafana",
        token_hash=hash_token(raw_token),
    )

    response = client.post(
        "/api/integrations/new-relic",
        headers={"Authorization": f"Bearer {raw_token}"},
        json=new_relic_payload(),
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "route_source_mismatch"


def test_new_relic_open_and_close_update_existing_alert(client, db):
    raw_token = "new-relic-route-token"
    group = create_group(slug="platform")
    team = create_team(group, slug="sre")
    route = create_route(
        team,
        source="new_relic",
        token_hash=hash_token(raw_token),
        group_by=["new_relic_issue_id"],
    )
    headers = {"Authorization": f"Bearer {raw_token}"}

    firing_response = client.post(
        "/api/integrations/new-relic",
        headers=headers,
        json=new_relic_payload(),
    )

    assert firing_response.status_code == 200
    firing_result = firing_response.get_json()[0]
    assert firing_result["created"] is True
    assert firing_result["status"] == "firing"

    resolved_response = client.post(
        "/api/integrations/new-relic",
        headers=headers,
        json=new_relic_payload(
            state="CLOSED",
            status="CLOSED",
        ),
    )

    assert resolved_response.status_code == 200
    resolved_result = resolved_response.get_json()[0]
    assert resolved_result["created"] is False
    assert resolved_result["status"] == "resolved"
    assert resolved_result["alert_id"] == firing_result["alert_id"]
    assert resolved_result["group_id"] == firing_result["group_id"]

    alert = Alert.get_by_id(firing_result["alert_id"])
    alert_group = AlertGroup.get_by_id(firing_result["group_id"])

    assert alert.source == "new_relic"
    assert alert.status == "resolved"
    assert alert.dedup_key == "issue-abc-123"
    assert alert.route_id == route.id
    assert alert_group.status == "resolved"


def test_route_openapi_lists_new_relic_source():
    assert "new_relic" in SOURCE_SCHEMA_WITH_SENTRY["enum"]


def test_new_relic_openapi_path_documents_workflow_payload():
    spec = integration_paths()
    operation = spec["/api/integrations/new-relic"]["post"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]

    assert operation["operationId"] == "receiveNewRelicAlerts"
    assert operation["security"] == [{"bearerAuth": []}]
    assert {"issue_id", "title", "state", "status", "priority"}.issubset(
        schema["properties"]
    )


def test_new_relic_ui_and_documentation_are_registered():
    root = Path(__file__).resolve().parents[2]
    routes_template = (root / "app/templates/pages/routes.html").read_text()
    routes_js = (root / "app/static/js/pages/routes.js").read_text()
    guide = (root / "docs/integrations/new-relic.md").read_text()
    docs_index = (root / "docs/integrations/index.md").read_text()
    mkdocs = (root / "docs/mkdocs.yml").read_text()

    assert 'value="new_relic"' in routes_template
    assert 'source === "new_relic"' in routes_js
    assert "/api/integrations/new-relic" in routes_js
    assert "# New Relic integration" in guide
    assert "issueId" in guide
    assert "[New Relic](new-relic.md)" in docs_index
    assert "New Relic: integrations/new-relic.md" in mkdocs
