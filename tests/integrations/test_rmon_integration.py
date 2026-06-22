from app.api.schemas.routes import RouteCreateSchema
from app.services.integrations.auth import hash_token
from app.services.integrations.normalizers.rmon import (
    normalize_rmon,
)
from tests.factories import (
    create_group,
    create_route,
    create_team,
)
from app.modules.db.models import (
    Alert,
    AlertExplainStep,
    AlertExplainTrace,
    AlertGroup,
)


def rmon_payload():
    return {
        "title": "[RMON] critical: HTTP check failed",
        "message": "critical: HTTP check failed",
        "severity": "critical",
        "status": "firing",
        "fingerprint": "42 7",
        "rmon_name": "rmon-production",
        "multi_check_id": 42,
        "state_id": 7,
        "check_name": "Public API",
        "check_type": "http",
        "target": "https://api.example.com/health",
        "agent": "eu-west-agent",
        "region": "eu-west",
        "country": "DE",
        "runbook_url": (
            "https://example.com/runbooks/public-api"
        ),
        "labels": {
            "team": "sre",
            "environment": "production",
        },
    }


def test_normalize_rmon_alert():
    alerts = normalize_rmon(rmon_payload())

    assert len(alerts) == 1

    alert = alerts[0]

    assert alert["source"] == "rmon"
    assert alert["team_slug"] == "sre"
    assert alert["status"] == "firing"
    assert alert["severity"] == "critical"

    assert alert["external_id"] == "42"
    assert alert["dedup_key"] == "42 7"

    assert alert["title"] == (
        "[RMON] critical: HTTP check failed"
    )
    assert alert["message"] == (
        "critical: HTTP check failed"
    )

    assert alert["labels"]["rmon_name"] == (
        "rmon-production"
    )
    assert alert["labels"]["rmon_check_id"] == "42"
    assert alert["labels"]["rmon_state_id"] == "7"
    assert alert["labels"]["rmon_check_name"] == (
        "Public API"
    )
    assert alert["labels"]["rmon_check_type"] == "http"
    assert alert["labels"]["target"] == (
        "https://api.example.com/health"
    )
    assert alert["labels"]["environment"] == "production"

    assert alert["labels"]["event_link"] == (
        "https://example.com/runbooks/public-api"
    )


def test_normalize_rmon_resolved_alert():
    payload = rmon_payload()
    payload["status"] = "resolved"
    payload["severity"] = "info"

    alert = normalize_rmon(payload)[0]

    assert alert["status"] == "resolved"


def test_normalize_rmon_ignores_empty_test_fingerprint():
    payload = rmon_payload()
    payload["fingerprint"] = "None None"
    payload["multi_check_id"] = None
    payload["state_id"] = None

    alert = normalize_rmon(payload)[0]

    assert alert["dedup_key"] != "None None"
    assert len(alert["dedup_key"]) == 64


def test_rmon_endpoint_requires_token(client):
    response = client.post(
        "/api/integrations/rmon",
        json=rmon_payload(),
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == (
        "Route intake token is required"
    )


def test_rmon_endpoint_accepts_route_token(
    client,
    monkeypatch,
    db,
):
    raw_token = "rmon-route-token"

    group = create_group(slug="platform")
    team = create_team(group, slug="sre")

    create_route(
        team,
        source="rmon",
        token_hash=hash_token(raw_token),
    )

    calls = []

    def fake_process_incoming_alerts(alerts):
        calls.append(alerts)

        return {
            "ok": True,
            "count": len(alerts),
        }, 200

    monkeypatch.setattr(
        "app.views.integrations_view."
        "process_incoming_alerts",
        fake_process_incoming_alerts,
    )

    response = client.post(
        "/api/integrations/rmon",
        headers={
            "Authorization": f"Bearer {raw_token}",
        },
        json=rmon_payload(),
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "count": 1,
    }

    alert = calls[0][0]

    assert alert["source"] == "rmon"
    assert alert["dedup_key"] == "42 7"
    assert alert["labels"]["rmon_check_id"] == "42"


def test_route_schema_accepts_rmon():
    route = RouteCreateSchema(
        team_id=1,
        name="RMON route",
        source="rmon",
    )

    assert route.source == "rmon"


def test_rmon_endpoint_creates_alert_and_group(
    client,
    db,
):
    raw_token = "rmon-real-ingest-token"

    group = create_group(slug="platform")
    team = create_team(group, slug="sre")
    route = create_route(
        team,
        source="rmon",
        token_hash=hash_token(raw_token),
        group_by=[
            "rmon_check_id",
            "rmon_check_type",
        ],
    )

    response = client.post(
        "/api/integrations/rmon",
        headers={
            "Authorization": f"Bearer {raw_token}",
        },
        json=rmon_payload(),
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

    assert result["alert_id"]
    assert result["group_id"]
    assert result["trace_id"]

    assert result["team_id"] == team.id
    assert result["team_slug"] == team.slug
    assert result["route_id"] == route.id
    assert result["routing_error"] is None

    alert = Alert.get_by_id(result["alert_id"])
    alert_group = AlertGroup.get_by_id(result["group_id"])

    assert alert.group_id == alert_group.id
    assert alert.team_id == team.id
    assert alert.route_id == route.id
    assert alert.source == "rmon"
    assert alert.status == "firing"

    assert alert.external_id == "42"
    assert alert.dedup_key == "42 7"
    assert alert.severity == "critical"

    assert alert.title == (
        "[RMON] critical: HTTP check failed"
    )
    assert alert.message == (
        "critical: HTTP check failed"
    )

    assert alert.labels["rmon_check_id"] == "42"
    assert alert.labels["rmon_state_id"] == "7"
    assert alert.labels["rmon_check_name"] == "Public API"
    assert alert.labels["rmon_check_type"] == "http"
    assert alert.labels["environment"] == "production"

    assert alert.payload["multi_check_id"] == 42
    assert alert.payload["state_id"] == 7
    assert alert.payload["check_type"] == "http"
    assert "token" not in alert.payload

    assert alert_group.team_id == team.id
    assert alert_group.route_id == route.id
    assert alert_group.source == "rmon"
    assert alert_group.status == "firing"

    trace = AlertExplainTrace.get(
        AlertExplainTrace.trace_id == result["trace_id"]
    )

    assert trace.alert_id == alert.id
    assert trace.group_id == alert_group.id
    assert trace.source == "rmon"
    assert trace.status == "completed"
    assert trace.outcome == "created"


def test_rmon_resolved_payload_updates_existing_alert(
    client,
    db,
):
    raw_token = "rmon-resolve-token"

    group = create_group(slug="platform")
    team = create_team(group, slug="sre")

    create_route(
        team,
        source="rmon",
        token_hash=hash_token(raw_token),
        group_by=[
            "rmon_check_id",
            "rmon_check_type",
        ],
    )

    headers = {
        "Authorization": f"Bearer {raw_token}",
    }

    firing_response = client.post(
        "/api/integrations/rmon",
        headers=headers,
        json=rmon_payload(),
    )

    assert firing_response.status_code == 200

    firing_result = firing_response.get_json()[0]

    resolved_payload = rmon_payload()
    resolved_payload["status"] = "resolved"
    resolved_payload["severity"] = "info"
    resolved_payload["message"] = (
        "info: HTTP check recovered"
    )

    resolved_response = client.post(
        "/api/integrations/rmon",
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

    assert (
        resolved_result["alert_id"]
        == firing_result["alert_id"]
    )
    assert (
        resolved_result["group_id"]
        == firing_result["group_id"]
    )

    alert = Alert.get_by_id(firing_result["alert_id"])
    alert_group = AlertGroup.get_by_id(
        firing_result["group_id"]
    )

    assert alert.status == "resolved"
    assert alert_group.status == "resolved"

    assert (
        Alert.select()
        .where(
            (Alert.source == "rmon")
            & (Alert.dedup_key == "42 7")
        )
        .count()
        == 1
    )

    trace = AlertExplainTrace.get(
        AlertExplainTrace.trace_id
        == resolved_result["trace_id"]
    )

    assert trace.alert_id == alert.id
    assert trace.group_id == alert_group.id
    assert trace.status == "completed"
    assert trace.outcome == "updated"


def test_rmon_routing_failure_returns_trace_id(
    client,
    db,
):
    raw_token = "rmon-routing-failure-token"

    group = create_group(slug="platform")
    team = create_team(group, slug="sre")

    create_route(
        team,
        source="rmon",
        token_hash=hash_token(raw_token),
        matchers={
            "environment": "staging",
        },
    )

    response = client.post(
        "/api/integrations/rmon",
        headers={
            "Authorization": f"Bearer {raw_token}",
        },
        json=rmon_payload(),
    )

    assert response.status_code == 400

    body = response.get_json()

    assert isinstance(body, list)
    assert len(body) == 1

    result = body[0]

    assert result["created"] is False
    assert result["alert_id"] is None
    assert result["group_id"] is None

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
            (Alert.source == "rmon")
            & (Alert.dedup_key == "42 7")
        )
        .count()
        == 0
    )

    trace = AlertExplainTrace.get(
        AlertExplainTrace.trace_id == result["trace_id"]
    )

    assert trace.source == "rmon"
    assert trace.alert_id is None
    assert trace.group_id is None
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


def test_rmon_different_check_ids_create_different_alerts(
    client,
    db,
):
    raw_token = "rmon-multiple-checks-token"

    group = create_group(slug="platform")
    team = create_team(group, slug="sre")

    create_route(
        team,
        source="rmon",
        token_hash=hash_token(raw_token),
    )

    headers = {
        "Authorization": f"Bearer {raw_token}",
    }

    first_payload = rmon_payload()

    second_payload = rmon_payload()
    second_payload["multi_check_id"] = 43
    second_payload["state_id"] = 8
    second_payload["fingerprint"] = "43 8"
    second_payload["check_name"] = "Private API"
    second_payload["target"] = (
        "https://internal.example.com/health"
    )

    first_response = client.post(
        "/api/integrations/rmon",
        headers=headers,
        json=first_payload,
    )
    second_response = client.post(
        "/api/integrations/rmon",
        headers=headers,
        json=second_payload,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    first_result = first_response.get_json()[0]
    second_result = second_response.get_json()[0]

    assert first_result["alert_id"] != second_result["alert_id"]

    assert (
        Alert.select()
        .where(Alert.source == "rmon")
        .count()
        == 2
    )
