from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.api.openapi.endpoints.integrations import paths as integration_paths
from app.api.openapi.endpoints.routes import SOURCE_SCHEMA_WITH_SENTRY
from app.api.schemas.integrations import UptimeKumaWebhookSchema
from app.api.schemas.routes import RouteCreateSchema
from app.modules.db.models import Alert, AlertGroup
from app.services.integrations.auth import hash_token
from app.services.integrations.normalizers.uptime_kuma import (
    normalize_uptime_kuma,
    normalize_uptime_kuma_severity,
    normalize_uptime_kuma_state,
    normalize_uptime_kuma_status,
    normalize_uptime_kuma_tags,
)
from tests.factories import create_group, create_route, create_team


def uptime_kuma_payload(status=0, **overrides):
    payload = {
        "heartbeat": {
            "monitorID": 42,
            "status": status,
            "time": "2026-07-27 12:10:00.000",
            "msg": "Request timeout after 48000ms",
            "ping": None,
            "duration": 48,
        },
        "monitor": {
            "id": 42,
            "name": "Payments API",
            "type": "http",
            "url": "https://payments.example.com/health",
            "tags": [
                {"name": "team", "value": "sre"},
                {"name": "service", "value": "payments"},
                {"name": "environment", "value": "production"},
                {"name": "severity", "value": "critical"},
            ],
        },
        "msg": "[Payments API] [DOWN] Request timeout",
    }
    payload.update(overrides)
    return payload


def test_normalize_uptime_kuma_down_notification():
    alert = normalize_uptime_kuma(uptime_kuma_payload())[0]

    assert alert["source"] == "uptime_kuma"
    assert alert["status"] == "firing"
    assert alert["title"] == "Payments API"
    assert alert["message"] == "Request timeout after 48000ms"
    assert alert["severity"] == "critical"
    assert alert["team_slug"] == "sre"
    assert alert["external_id"] == "42"
    assert alert["dedup_key"] == "uptime-kuma:42"

    assert alert["labels"]["uptime_kuma_monitor_id"] == "42"
    assert alert["labels"]["uptime_kuma_status"] == "down"
    assert alert["labels"]["uptime_kuma_status_code"] == "0"
    assert alert["labels"]["uptime_kuma_monitor_type"] == "http"
    assert alert["labels"]["uptime_kuma_target"].endswith("/health")
    assert alert["labels"]["service"] == "payments"
    assert alert["labels"]["environment"] == "production"
    assert alert["labels"]["uptime_kuma_tag_service"] == "payments"
    assert alert["labels"]["event_link"].endswith("/health")


def test_uptime_kuma_status_mapping():
    assert normalize_uptime_kuma_state(0) == "firing"
    assert normalize_uptime_kuma_state(1) == "resolved"
    assert normalize_uptime_kuma_state(2) == "pending"
    assert normalize_uptime_kuma_state(3) == "maintenance"
    assert normalize_uptime_kuma_state(99) == "unknown"

    assert normalize_uptime_kuma_status(0) == "firing"
    assert normalize_uptime_kuma_status(1) == "resolved"
    assert normalize_uptime_kuma_status(2) == "firing"
    assert normalize_uptime_kuma_status(3) == "resolved"


@pytest.mark.parametrize(
    ("raw_status", "expected_lifecycle", "expected_label"),
    [
        (0, "firing", "down"),
        (1, "resolved", "up"),
        (2, "firing", "pending"),
        (3, "resolved", "maintenance"),
    ],
)
def test_normalize_uptime_kuma_lifecycle_states(
    raw_status,
    expected_lifecycle,
    expected_label,
):
    alert = normalize_uptime_kuma(
        uptime_kuma_payload(status=raw_status)
    )[0]

    assert alert["status"] == expected_lifecycle
    assert alert["labels"]["uptime_kuma_status"] == expected_label


def test_uptime_kuma_recovery_uses_same_dedup_key():
    firing = normalize_uptime_kuma(uptime_kuma_payload(status=0))[0]
    recovery_payload = uptime_kuma_payload(status=1)
    recovery_payload["heartbeat"]["msg"] = "200 - OK"
    recovery_payload["msg"] = "[Payments API] [UP] 200 - OK"
    recovered = normalize_uptime_kuma(recovery_payload)[0]

    assert firing["status"] == "firing"
    assert recovered["status"] == "resolved"
    assert firing["dedup_key"] == recovered["dedup_key"]


def test_uptime_kuma_status_zero_is_not_treated_as_missing():
    payload = uptime_kuma_payload(status=0)
    payload["status"] = 1

    alert = normalize_uptime_kuma(payload)[0]

    assert alert["status"] == "firing"
    assert alert["labels"]["uptime_kuma_status_code"] == "0"


def test_uptime_kuma_priority_tags_map_to_supported_severity():
    assert normalize_uptime_kuma_severity("P1") == "critical"
    assert normalize_uptime_kuma_severity("P2") == "high"
    assert normalize_uptime_kuma_severity("P3") == "medium"
    assert normalize_uptime_kuma_severity("P4") == "warning"
    assert normalize_uptime_kuma_severity("P5") == "info"


def test_uptime_kuma_tags_create_prefixed_and_routing_labels():
    labels = normalize_uptime_kuma_tags([
        {"name": "team", "value": "database"},
        {"name": "tier", "value": "critical"},
        "region=eu-west",
        "synthetic",
    ])

    assert labels["team"] == "database"
    assert labels["uptime_kuma_tag_team"] == "database"
    assert labels["uptime_kuma_tag_tier"] == "critical"
    assert labels["region"] == "eu-west"
    assert labels["uptime_kuma_tag_synthetic"] == "true"


def test_uptime_kuma_fallback_dedup_key_is_stable():
    payload = uptime_kuma_payload()
    payload["monitor"].pop("id")
    payload["heartbeat"].pop("monitorID")

    first = normalize_uptime_kuma(deepcopy(payload))[0]
    second = normalize_uptime_kuma(deepcopy(payload))[0]

    assert first["external_id"] is None
    assert first["dedup_key"] == second["dedup_key"]


def test_uptime_kuma_test_notification_is_accepted_as_info():
    event = normalize_uptime_kuma({"msg": "Testing webhook"})[0]

    assert event["status"] == "firing"
    assert event["severity"] == "info"
    assert event["title"] == "Uptime Kuma notification"
    assert event["message"] == "Testing webhook"


def test_uptime_kuma_schema_accepts_standard_and_test_payloads():
    standard = UptimeKumaWebhookSchema(**uptime_kuma_payload())
    test = UptimeKumaWebhookSchema(msg="Testing webhook")

    assert standard.heartbeat["status"] == 0
    assert test.msg == "Testing webhook"


def test_uptime_kuma_schema_rejects_empty_payload():
    with pytest.raises(ValidationError):
        UptimeKumaWebhookSchema()


def test_route_schema_accepts_uptime_kuma():
    route = RouteCreateSchema(
        team_id=1,
        name="Uptime Kuma production",
        source="uptime_kuma",
    )

    assert route.source == "uptime_kuma"


def test_uptime_kuma_endpoint_requires_token(client):
    response = client.post(
        "/api/integrations/uptime-kuma",
        json=uptime_kuma_payload(),
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "Route intake token is required"


def test_uptime_kuma_endpoint_rejects_token_from_another_source(client, db):
    raw_token = "not-an-uptime-kuma-route-token"
    group = create_group(slug="platform")
    team = create_team(group, slug="sre")
    create_route(
        team,
        source="grafana",
        token_hash=hash_token(raw_token),
    )

    response = client.post(
        "/api/integrations/uptime-kuma",
        headers={"Authorization": f"Bearer {raw_token}"},
        json=uptime_kuma_payload(),
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "route_source_mismatch"


def test_uptime_kuma_down_and_up_update_existing_alert(client, db):
    raw_token = "uptime-kuma-route-token"
    group = create_group(slug="platform")
    team = create_team(group, slug="sre")
    route = create_route(
        team,
        source="uptime_kuma",
        token_hash=hash_token(raw_token),
        group_by=["uptime_kuma_monitor_id"],
    )
    headers = {"Authorization": f"Bearer {raw_token}"}

    firing_response = client.post(
        "/api/integrations/uptime-kuma",
        headers=headers,
        json=uptime_kuma_payload(status=0),
    )

    assert firing_response.status_code == 200
    firing_result = firing_response.get_json()[0]
    assert firing_result["created"] is True
    assert firing_result["status"] == "firing"

    recovery_payload = uptime_kuma_payload(status=1)
    recovery_payload["heartbeat"]["msg"] = "200 - OK"
    recovery_payload["msg"] = "[Payments API] [UP] 200 - OK"
    recovery_response = client.post(
        "/api/integrations/uptime-kuma",
        headers=headers,
        json=recovery_payload,
    )

    assert recovery_response.status_code == 200
    recovery_result = recovery_response.get_json()[0]
    assert recovery_result["created"] is False
    assert recovery_result["status"] == "resolved"
    assert recovery_result["alert_id"] == firing_result["alert_id"]
    assert recovery_result["group_id"] == firing_result["group_id"]

    alert = Alert.get_by_id(firing_result["alert_id"])
    alert_group = AlertGroup.get_by_id(firing_result["group_id"])

    assert alert.source == "uptime_kuma"
    assert alert.status == "resolved"
    assert alert.dedup_key == "uptime-kuma:42"
    assert alert.route_id == route.id
    assert alert_group.status == "resolved"


def test_route_openapi_lists_uptime_kuma_source():
    assert "uptime_kuma" in SOURCE_SCHEMA_WITH_SENTRY["enum"]


def test_uptime_kuma_openapi_path_documents_standard_payload():
    spec = integration_paths()
    operation = spec["/api/integrations/uptime-kuma"]["post"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]

    assert operation["operationId"] == "receiveUptimeKumaNotification"
    assert operation["security"] == [{"bearerAuth": []}]
    assert {"heartbeat", "monitor", "msg"}.issubset(schema["properties"])


def test_uptime_kuma_ui_and_documentation_are_registered():
    root = Path(__file__).resolve().parents[2]
    routes_template = (root / "app/templates/pages/routes.html").read_text()
    routes_js = (root / "app/static/js/pages/routes.js").read_text()
    guide = (root / "docs/integrations/uptime-kuma.md").read_text()
    docs_index = (root / "docs/integrations/index.md").read_text()
    mkdocs = (root / "docs/mkdocs.yml").read_text()

    assert 'value="uptime_kuma"' in routes_template
    assert 'source === "uptime_kuma"' in routes_js
    assert "/api/integrations/uptime-kuma" in routes_js
    assert "# Uptime Kuma integration" in guide
    assert "## Lifecycle mapping" in guide
    assert "## Use with Event Orchestration" in guide
    assert "[Uptime Kuma](uptime-kuma.md)" in docs_index
    assert "Uptime Kuma: integrations/uptime-kuma.md" in mkdocs
