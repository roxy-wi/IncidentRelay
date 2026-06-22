from copy import deepcopy

from app.api.schemas.routes import RouteCreateSchema
from app.services.integrations.auth import hash_token
from app.services.integrations.normalizers.grafana import normalize_grafana
from tests.factories import create_group, create_route, create_team
from app.modules.db.models import (
    Alert,
    AlertGroup,
    AlertExplainStep,
    AlertExplainTrace,
)


def grafana_payload():
    return {
        "receiver": "incidentrelay",
        "status": "firing",
        "orgId": 1,
        "groupKey": "{}:{alertname=\"DiskFull\"}",
        "groupLabels": {
            "alertname": "DiskFull",
        },
        "commonLabels": {
            "team": "sre",
            "environment": "production",
        },
        "commonAnnotations": {
            "runbook_url": "https://example.com/runbooks/disk",
        },
        "externalURL": "https://grafana.example.com/",
        "title": "[FIRING:1] DiskFull",
        "state": "alerting",
        "message": "Grafana notification",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "DiskFull",
                    "severity": "critical",
                    "instance": "host1",
                    "grafana_folder": "Infrastructure",
                    "__alert_rule_uid__": "disk-full-rule",
                },
                "annotations": {
                    "summary": "Disk is full",
                    "description": "/var is 95% full",
                },
                "startsAt": "2026-06-21T10:00:00Z",
                "endsAt": "0001-01-01T00:00:00Z",
                "generatorURL": (
                    "https://grafana.example.com/alerting/"
                    "grafana/disk-full-rule/view"
                ),
                "fingerprint": "grafana-disk-full-host1",
                "silenceURL": (
                    "https://grafana.example.com/alerting/silence/new"
                ),
                "dashboardURL": (
                    "https://grafana.example.com/d/system-overview"
                ),
                "panelURL": (
                    "https://grafana.example.com/d/system-overview"
                    "?viewPanel=12"
                ),
                "values": {
                    "A": 95,
                },
                "valueString": "[ var='A' value=95 ]",
            }
        ],
    }


def test_normalize_grafana_alert():
    alerts = normalize_grafana(grafana_payload())

    assert len(alerts) == 1

    alert = alerts[0]

    assert alert["source"] == "grafana"
    assert alert["team_slug"] == "sre"
    assert alert["status"] == "firing"
    assert alert["severity"] == "critical"
    assert alert["title"] == "Disk is full"
    assert alert["message"] == "/var is 95% full"
    assert alert["external_id"] == "grafana-disk-full-host1"
    assert alert["dedup_key"] == "grafana-disk-full-host1"

    assert alert["labels"]["environment"] == "production"
    assert alert["labels"]["instance"] == "host1"
    assert alert["labels"]["grafana_org_id"] == "1"
    assert alert["labels"]["grafana_receiver"] == "incidentrelay"

    assert alert["labels"]["event_link"] == (
        "https://grafana.example.com/d/system-overview"
    )
    assert alert["labels"]["dashboard_url"] == (
        "https://grafana.example.com/d/system-overview"
    )
    assert alert["labels"]["panel_url"].endswith("?viewPanel=12")

    assert alert["annotations"]["runbook_url"] == (
        "https://example.com/runbooks/disk"
    )

    assert len(alert["payload"]["alerts"]) == 1
    assert alert["payload"]["orgId"] == 1


def test_grafana_alert_status_overrides_group_status():
    payload = grafana_payload()
    payload["status"] = "firing"
    payload["alerts"][0]["status"] = "resolved"

    alert = normalize_grafana(payload)[0]

    assert alert["status"] == "resolved"


def test_grafana_fallback_dedup_key_is_stable():
    payload = grafana_payload()
    payload["alerts"][0]["fingerprint"] = None

    first = normalize_grafana(deepcopy(payload))[0]
    second = normalize_grafana(deepcopy(payload))[0]

    assert first["dedup_key"] == second["dedup_key"]
    assert first["external_id"] == "disk-full-rule"


def test_grafana_endpoint_requires_token(client):
    response = client.post(
        "/api/integrations/grafana",
        json=grafana_payload(),
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "Route intake token is required"


def test_grafana_endpoint_accepts_route_token(
    client,
    monkeypatch,
    db,
):
    raw_token = "grafana-route-token"

    group = create_group(slug="platform")
    team = create_team(group, slug="sre")

    create_route(
        team,
        source="grafana",
        token_hash=hash_token(raw_token),
    )

    calls = []

    def fake_process_incoming_alerts(alerts):
        calls.append(alerts)
        return {"ok": True, "count": len(alerts)}, 200

    monkeypatch.setattr(
        "app.views.integrations_view.process_incoming_alerts",
        fake_process_incoming_alerts,
    )

    response = client.post(
        "/api/integrations/grafana",
        headers={
            "Authorization": f"Bearer {raw_token}",
        },
        json=grafana_payload(),
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "count": 1,
    }

    assert calls[0][0]["source"] == "grafana"
    assert calls[0][0]["title"] == "Disk is full"


def test_grafana_endpoint_rejects_empty_alert_list(
    client,
    db,
):
    raw_token = "grafana-route-token"

    group = create_group(slug="platform")
    team = create_team(group, slug="sre")

    create_route(
        team,
        source="grafana",
        token_hash=hash_token(raw_token),
    )

    payload = grafana_payload()
    payload["alerts"] = []

    response = client.post(
        "/api/integrations/grafana",
        headers={
            "Authorization": f"Bearer {raw_token}",
        },
        json=payload,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"


def test_route_schema_accepts_grafana_and_librenms():
    grafana = RouteCreateSchema(
        team_id=1,
        name="Grafana route",
        source="grafana",
    )
    librenms = RouteCreateSchema(
        team_id=1,
        name="LibreNMS route",
        source="librenms",
    )

    assert grafana.source == "grafana"
    assert librenms.source == "librenms"


def test_grafana_endpoint_creates_alert_and_group(
    client,
    db,
):
    raw_token = "grafana-real-ingest-token"

    group = create_group(slug="platform")
    team = create_team(group, slug="sre")
    route = create_route(
        team,
        source="grafana",
        token_hash=hash_token(raw_token),
        group_by=[
            "alertname",
            "instance",
        ],
    )

    response = client.post(
        "/api/integrations/grafana",
        headers={
            "Authorization": f"Bearer {raw_token}",
        },
        json=grafana_payload(),
    )

    assert response.status_code == 200

    body = response.get_json()

    assert isinstance(body, list)
    assert len(body) == 1

    result = body[0]

    assert result["created"] is True
    assert result["outcome"] == "created"
    assert result["processing_status"] == "completed"
    assert result["status"] == "firing"

    assert result["group_id"]
    assert result["alert_id"]
    assert result["trace_id"]

    assert result["team_id"] == team.id
    assert result["team_slug"] == team.slug
    assert result["route_id"] == route.id
    assert result["routing_error"] is None

    alert_group = AlertGroup.get_by_id(result["group_id"])
    alert = Alert.get_by_id(result["alert_id"])

    assert alert_group.team_id == team.id
    assert alert_group.route_id == route.id
    assert alert_group.source == "grafana"
    assert alert_group.status == "firing"

    assert alert.group_id == alert_group.id
    assert alert.team_id == team.id
    assert alert.route_id == route.id
    assert alert.source == "grafana"
    assert alert.status == "firing"

    assert alert.external_id == "grafana-disk-full-host1"
    assert alert.dedup_key == "grafana-disk-full-host1"
    assert alert.title == "Disk is full"
    assert alert.message == "/var is 95% full"
    assert alert.severity == "critical"

    assert alert.labels["alertname"] == "DiskFull"
    assert alert.labels["instance"] == "host1"
    assert alert.labels["environment"] == "production"
    assert alert.labels["grafana_org_id"] == "1"

    assert alert.payload["orgId"] == 1
    assert len(alert.payload["alerts"]) == 1
    assert (
        alert.payload["alerts"][0]["fingerprint"]
        == "grafana-disk-full-host1"
    )

    trace = AlertExplainTrace.get(
        AlertExplainTrace.trace_id == result["trace_id"]
    )

    assert trace.group_id == alert_group.id
    assert trace.alert_id == alert.id
    assert trace.source == "grafana"
    assert trace.status == "completed"
    assert trace.outcome == "created"


def test_grafana_resolved_payload_updates_existing_alert(
    client,
    db,
):
    raw_token = "grafana-resolve-token"

    group = create_group(slug="platform")
    team = create_team(group, slug="sre")
    create_route(
        team,
        source="grafana",
        token_hash=hash_token(raw_token),
        group_by=[
            "alertname",
            "instance",
        ],
    )

    headers = {
        "Authorization": f"Bearer {raw_token}",
    }

    firing_response = client.post(
        "/api/integrations/grafana",
        headers=headers,
        json=grafana_payload(),
    )

    assert firing_response.status_code == 200

    firing_result = firing_response.get_json()[0]

    resolved_payload = grafana_payload()
    resolved_payload["status"] = "resolved"
    resolved_payload["alerts"][0]["status"] = "resolved"
    resolved_payload["alerts"][0]["endsAt"] = (
        "2026-06-21T10:15:00Z"
    )

    resolved_response = client.post(
        "/api/integrations/grafana",
        headers=headers,
        json=resolved_payload,
    )

    assert resolved_response.status_code == 200

    resolved_result = resolved_response.get_json()[0]

    assert resolved_result["created"] is False
    assert resolved_result["outcome"] == "updated"
    assert resolved_result["processing_status"] == "completed"
    assert resolved_result["status"] == "resolved"
    assert resolved_result["trace_id"]

    assert resolved_result["alert_id"] == firing_result["alert_id"]
    assert resolved_result["group_id"] == firing_result["group_id"]

    alert = Alert.get_by_id(firing_result["alert_id"])
    alert_group = AlertGroup.get_by_id(firing_result["group_id"])

    assert alert.status == "resolved"
    assert alert_group.status == "resolved"

    assert (
        Alert.select()
        .where(
            (Alert.source == "grafana")
            & (
                Alert.dedup_key
                == "grafana-disk-full-host1"
            )
        )
        .count()
        == 1
    )

    trace = AlertExplainTrace.get(
        AlertExplainTrace.trace_id
        == resolved_result["trace_id"]
    )

    assert trace.group_id == alert_group.id
    assert trace.alert_id == alert.id
    assert trace.status == "completed"
    assert trace.outcome == "updated"


def test_grafana_routing_failure_returns_trace_id(
    client,
    db,
):
    raw_token = "grafana-routing-failure-token"

    group = create_group(slug="platform")
    team = create_team(group, slug="sre")

    create_route(
        team,
        source="grafana",
        token_hash=hash_token(raw_token),
        matchers={
            "environment": "staging",
        },
    )

    response = client.post(
        "/api/integrations/grafana",
        headers={
            "Authorization": f"Bearer {raw_token}",
        },
        json=grafana_payload(),
    )

    assert response.status_code == 400

    body = response.get_json()

    assert isinstance(body, list)
    assert len(body) == 1

    result = body[0]

    assert result["created"] is False
    assert result["group_id"] is None
    assert result["alert_id"] is None

    assert result["outcome"] == "routing_failed"
    assert result["processing_status"] == "stopped"
    assert result["reason"] == (
        "Alert did not match any active route."
    )
    assert result["routing_error"] == (
        "Alert did not match any active route."
    )
    assert result["trace_id"]

    assert (
        Alert.select()
        .where(
            (Alert.source == "grafana")
            & (
                Alert.dedup_key
                == "grafana-disk-full-host1"
            )
        )
        .count()
        == 0
    )

    trace = AlertExplainTrace.get(
        AlertExplainTrace.trace_id == result["trace_id"]
    )

    assert trace.source == "grafana"
    assert trace.group_id is None
    assert trace.alert_id is None
    assert trace.status == "stopped"
    assert trace.outcome == "routing_failed"
    assert trace.reason == (
        "Alert did not match any active route."
    )

    steps = list(
        AlertExplainStep.select()
        .where(AlertExplainStep.trace == trace.id)
        .order_by(AlertExplainStep.position.asc())
    )

    route_step = next(
        step
        for step in steps
        if step.code == "route_not_matched"
    )

    assert route_step.stage == "route"
    assert route_step.status == "error"
    assert route_step.data["routing_error"] == (
        "alert does not match route matchers"
    )
