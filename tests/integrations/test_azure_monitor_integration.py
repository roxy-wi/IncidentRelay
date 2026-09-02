from copy import deepcopy

from app.api.schemas.routes import RouteCreateSchema
from app.modules.db.models import Alert, AlertGroup
from app.services.integrations.auth import hash_token
from app.services.integrations.normalizers.azure_monitor import (
    normalize_azure_monitor,
)
from tests.factories import create_group, create_route, create_team


def azure_monitor_payload(**essential_overrides):
    essentials = {
        "alertId": (
            "/subscriptions/sub-123/"
            "providers/Microsoft.AlertsManagement/"
            "alerts/alert-instance-123"
        ),
        "alertRule": "Checkout API latency",
        "alertRuleId": (
            "/subscriptions/sub-123/"
            "resourceGroups/production/"
            "providers/microsoft.insights/"
            "metricAlerts/checkout-latency"
        ),
        "severity": "Sev1",
        "signalType": "Metric",
        "monitorCondition": "Fired",
        "monitoringService": "Platform",
        "alertTargetIDs": [
            (
                "/subscriptions/sub-123/"
                "resourceGroups/production/"
                "providers/Microsoft.Compute/"
                "virtualMachines/checkout-01"
            )
        ],
        "configurationItems": ["checkout-01"],
        "originAlertId": "origin-alert-123",
        "firedDateTime": "2026-09-01T08:00:00Z",
        "description": "p95 latency exceeded 2 seconds",
        "targetResourceGroup": "production",
        "targetResourceType": "Microsoft.Compute/virtualMachines",
        "investigationLink": (
            "https://portal.azure.com/#view/"
            "Microsoft_Azure_Monitoring/AlertDetails"
        ),
    }
    essentials.update(essential_overrides)

    return {
        "schemaId": "azureMonitorCommonAlertSchema",
        "data": {
            "essentials": essentials,
            "alertContext": {
                "conditionType": (
                    "SingleResourceMultipleMetricCriteria"
                ),
            },
            "customProperties": {
                "team": "sre",
                "service": "checkout",
                "environment": "production",
            },
        },
    }


def test_normalize_azure_monitor_common_schema():
    alert = normalize_azure_monitor(
        azure_monitor_payload()
    )[0]

    assert alert["source"] == "azure_monitor"
    assert alert["team_slug"] == "sre"
    assert alert["status"] == "firing"
    assert alert["severity"] == "high"
    assert alert["title"] == "Checkout API latency"
    assert alert["message"] == "p95 latency exceeded 2 seconds"
    assert alert["external_id"].endswith(
        "/alerts/alert-instance-123"
    )
    assert alert["dedup_key"].endswith(
        "/alerts/alert-instance-123"
    )
    assert alert["labels"]["team"] == "sre"
    assert alert["labels"]["service"] == "checkout"
    assert alert["labels"]["environment"] == "production"
    assert (
        alert["labels"]["azure_alert_rule"]
        == "Checkout API latency"
    )
    assert (
        alert["labels"]["azure_monitor_condition"]
        == "Fired"
    )
    assert (
        alert["labels"]["azure_subscription_id"]
        == "sub-123"
    )
    assert (
        alert["labels"]["azure_configuration_item"]
        == "checkout-01"
    )
    assert (
        alert["labels"]["event_link"]
        == (
            "https://portal.azure.com/#view/"
            "Microsoft_Azure_Monitoring/AlertDetails"
        )
    )


def test_azure_monitor_severity_mapping():
    expected = {
        "Sev0": "critical",
        "Sev1": "high",
        "Sev2": "medium",
        "Sev3": "warning",
        "Sev4": "info",
    }

    for azure_severity, incidentrelay_severity in expected.items():
        alert = normalize_azure_monitor(
            azure_monitor_payload(severity=azure_severity)
        )[0]

        assert alert["severity"] == incidentrelay_severity


def test_azure_monitor_resolved_uses_same_dedup_key():
    firing = normalize_azure_monitor(
        azure_monitor_payload()
    )[0]
    resolved = normalize_azure_monitor(
        azure_monitor_payload(
            monitorCondition="Resolved",
            resolvedDateTime="2026-09-01T08:10:00Z",
        )
    )[0]

    assert firing["status"] == "firing"
    assert resolved["status"] == "resolved"
    assert firing["dedup_key"] == resolved["dedup_key"]


def test_azure_monitor_fallback_dedup_key_is_stable():
    payload = azure_monitor_payload(
        alertId=None,
        originAlertId=None,
    )

    first = normalize_azure_monitor(deepcopy(payload))[0]
    second = normalize_azure_monitor(deepcopy(payload))[0]

    assert first["dedup_key"] == second["dedup_key"]


def test_route_schema_accepts_azure_monitor():
    route = RouteCreateSchema(
        team_id=1,
        name="Azure production alerts",
        source="azure_monitor",
    )

    assert route.source == "azure_monitor"


def test_azure_monitor_endpoint_requires_token(client):
    response = client.post(
        "/api/integrations/azure-monitor",
        json=azure_monitor_payload(),
    )

    assert response.status_code == 401
    assert (
        response.get_json()["error"]
        == "Route intake token is required"
    )


def test_azure_monitor_rejects_token_from_other_source(
    client,
    db,
):
    raw_token = "not-an-azure-monitor-token"
    group = create_group(slug="platform")
    team = create_team(group, slug="sre")

    create_route(
        team,
        source="grafana",
        token_hash=hash_token(raw_token),
    )

    response = client.post(
        "/api/integrations/azure-monitor",
        headers={"Authorization": f"Bearer {raw_token}"},
        json=azure_monitor_payload(),
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "route_source_mismatch"


def test_azure_monitor_rejects_legacy_schema(
    client,
    db,
):
    raw_token = "azure-monitor-token"
    group = create_group(slug="platform")
    team = create_team(group, slug="sre")

    create_route(
        team,
        source="azure_monitor",
        token_hash=hash_token(raw_token),
    )

    payload = azure_monitor_payload()
    payload["schemaId"] = "AzureMonitorMetricAlert"

    response = client.post(
        "/api/integrations/azure-monitor",
        headers={"Authorization": f"Bearer {raw_token}"},
        json=payload,
    )

    assert response.status_code == 400


def test_azure_monitor_fired_and_resolved_update_existing_alert(
    client,
    db,
):
    raw_token = "azure-monitor-route-token"
    group = create_group(slug="platform")
    team = create_team(group, slug="sre")

    route = create_route(
        team,
        source="azure_monitor",
        token_hash=hash_token(raw_token),
        group_by=["azure_alert_id"],
    )

    headers = {
        "Authorization": f"Bearer {raw_token}",
    }

    firing_response = client.post(
        "/api/integrations/azure-monitor",
        headers=headers,
        json=azure_monitor_payload(),
    )

    assert firing_response.status_code == 200

    firing_result = firing_response.get_json()[0]

    assert firing_result["created"] is True
    assert firing_result["status"] == "firing"

    resolved_response = client.post(
        "/api/integrations/azure-monitor",
        headers=headers,
        json=azure_monitor_payload(
            monitorCondition="Resolved",
            resolvedDateTime="2026-09-01T08:10:00Z",
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

    assert alert.source == "azure_monitor"
    assert alert.status == "resolved"
    assert alert.route_id == route.id
    assert alert_group.status == "resolved"
