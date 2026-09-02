import base64

from app.api.openapi.endpoints.integrations import paths as integration_paths
from app.api.openapi.endpoints.routes import SOURCE_SCHEMA_WITH_SENTRY
from app.api.openapi.spec import build_openapi_spec
from app.services.integrations.auth import hash_token
from tests.factories import create_group, create_route, create_team


def _azure_payload():
    return {
        "schemaId": "azureMonitorCommonAlertSchema",
        "data": {
            "essentials": {
                "alertId": "/subscriptions/test/providers/Microsoft.AlertsManagement/alerts/basic-auth-1",
                "alertRule": "Basic auth test",
                "severity": "Sev2",
                "signalType": "Metric",
                "monitorCondition": "Fired",
                "monitoringService": "Platform",
            },
            "customProperties": {"team": "sre"},
        },
    }


def _basic_header(username, password):
    raw = f"{username}:{password}".encode("utf-8")
    value = base64.b64encode(raw).decode("ascii")
    return {"Authorization": f"Basic {value}"}


def test_azure_monitor_endpoint_accepts_basic_route_auth(client, db):
    raw_token = "azure-monitor-basic-token"
    group = create_group(slug="platform")
    team = create_team(group, slug="sre")
    create_route(
        team,
        source="azure_monitor",
        token_hash=hash_token(raw_token),
    )

    response = client.post(
        "/api/integrations/azure-monitor",
        headers=_basic_header("incidentrelay", raw_token),
        json=_azure_payload(),
    )

    assert response.status_code == 200
    assert response.get_json()[0]["status"] == "firing"


def test_azure_monitor_endpoint_rejects_wrong_basic_username(client, db):
    raw_token = "azure-monitor-basic-token"
    group = create_group(slug="platform")
    team = create_team(group, slug="sre")
    create_route(
        team,
        source="azure_monitor",
        token_hash=hash_token(raw_token),
    )

    response = client.post(
        "/api/integrations/azure-monitor",
        headers=_basic_header("wrong-user", raw_token),
        json=_azure_payload(),
    )

    assert response.status_code == 401


def test_route_openapi_lists_azure_monitor_source():
    assert "azure_monitor" in SOURCE_SCHEMA_WITH_SENTRY["enum"]


def test_azure_monitor_openapi_documents_common_schema_and_basic_auth():
    spec = integration_paths()
    operation = spec["/api/integrations/azure-monitor"]["post"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]

    assert operation["operationId"] == "receiveAzureMonitorAlerts"
    assert {"bearerAuth": []} in operation["security"]
    assert {"basicRouteAuth": []} in operation["security"]
    assert schema["properties"]["schemaId"]["enum"] == [
        "azureMonitorCommonAlertSchema"
    ]

    full_spec = build_openapi_spec()
    basic = full_spec["components"]["securitySchemes"]["basicRouteAuth"]
    assert basic["type"] == "http"
    assert basic["scheme"] == "basic"
