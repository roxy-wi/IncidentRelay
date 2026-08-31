from app.api.schemas.routes import RouteCreateSchema
from app.modules.db.models import Alert, AlertGroup
from app.services.integrations.auth import hash_token
from app.services.integrations.normalizers.nagios import normalize_nagios
from tests.factories import create_group, create_route, create_team


def service_payload(**overrides):
    payload = {
        "notification_type": "PROBLEM",
        "host_name": "db01",
        "host_alias": "Primary DB",
        "host_address": "10.10.20.15",
        "host_state": "UP",
        "service_description": "Disk Usage",
        "service_state": "CRITICAL",
        "service_output": "/var is 96% full",
        "state_type": "HARD",
    }
    payload.update(overrides)
    return payload


def test_normalize_nagios_service_problem():
    alert = normalize_nagios(service_payload())[0]

    assert alert["source"] == "nagios"
    assert alert["status"] == "firing"
    assert alert["severity"] == "critical"
    assert alert["lifecycle_action"] == "trigger"
    assert alert["title"] == "CRITICAL: Disk Usage on db01"
    assert alert["message"] == "/var is 96% full"
    assert alert["dedup_key"] == "nagios:service:db01:Disk Usage"
    assert alert["labels"]["nagios_host"] == "db01"
    assert alert["labels"]["nagios_service"] == "Disk Usage"
    assert alert["labels"]["nagios_object_type"] == "service"


def test_nagios_recovery_uses_same_dedup_key():
    problem = normalize_nagios(service_payload())[0]
    recovery = normalize_nagios(service_payload(
        notification_type="RECOVERY",
        service_state="OK",
        service_output="/var is healthy",
    ))[0]

    assert recovery["status"] == "resolved"
    assert recovery["lifecycle_action"] == "resolve"
    assert recovery["dedup_key"] == problem["dedup_key"]


def test_normalize_nagios_host_down():
    alert = normalize_nagios({
        "NOTIFICATIONTYPE": "PROBLEM",
        "HOSTNAME": "edge01",
        "HOSTSTATE": "DOWN",
        "HOSTOUTPUT": "CRITICAL - host unreachable",
    })[0]

    assert alert["status"] == "firing"
    assert alert["severity"] == "critical"
    assert alert["dedup_key"] == "nagios:host:edge01"
    assert alert["labels"]["nagios_object_type"] == "host"


def test_nagios_acknowledgement_is_lifecycle_action():
    alert = normalize_nagios(service_payload(
        notification_type="ACKNOWLEDGEMENT",
    ))[0]

    assert alert["lifecycle_action"] == "acknowledge"


def test_nagios_downtime_notification_is_ignored():
    alert = normalize_nagios(service_payload(
        notification_type="DOWNTIMESTART",
    ))[0]

    assert alert["lifecycle_action"] == "ignore"


def test_route_schema_accepts_nagios():
    route = RouteCreateSchema(
        team_id=1,
        name="Nagios production",
        source="nagios",
    )
    assert route.source == "nagios"


def test_nagios_endpoint_requires_token(client):
    response = client.post(
        "/api/integrations/nagios",
        json=service_payload(),
    )
    assert response.status_code == 401
    assert response.get_json()["error"] == "Route intake token is required"


def test_nagios_endpoint_rejects_token_from_another_source(client, db):
    raw_token = "not-a-nagios-token"
    group = create_group(slug="platform")
    team = create_team(group, slug="sre")
    create_route(team, source="grafana", token_hash=hash_token(raw_token))

    response = client.post(
        "/api/integrations/nagios",
        headers={"Authorization": f"Bearer {raw_token}"},
        json=service_payload(),
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "route_source_mismatch"


def test_nagios_problem_and_recovery_update_existing_alert(client, db):
    raw_token = "nagios-route-token"
    group = create_group(slug="platform")
    team = create_team(group, slug="sre")
    route = create_route(
        team,
        source="nagios",
        token_hash=hash_token(raw_token),
        group_by=["nagios_host", "nagios_service"],
    )
    headers = {"Authorization": f"Bearer {raw_token}"}

    problem_response = client.post(
        "/api/integrations/nagios",
        headers=headers,
        json=service_payload(),
    )
    assert problem_response.status_code == 200
    problem = problem_response.get_json()[0]
    assert problem["created"] is True

    recovery_response = client.post(
        "/api/integrations/nagios",
        headers=headers,
        json=service_payload(notification_type="RECOVERY", service_state="OK"),
    )
    assert recovery_response.status_code == 200
    recovery = recovery_response.get_json()[0]
    assert recovery["created"] is False
    assert recovery["status"] == "resolved"
    assert recovery["alert_id"] == problem["alert_id"]

    alert = Alert.get_by_id(problem["alert_id"])
    alert_group = AlertGroup.get_by_id(problem["group_id"])
    assert alert.source == "nagios"
    assert alert.status == "resolved"
    assert alert.route_id == route.id
    assert alert_group.status == "resolved"


def test_nagios_acknowledgement_acks_existing_group(client, db):
    raw_token = "nagios-ack-route-token"
    group = create_group(slug="platform")
    team = create_team(group, slug="sre")
    create_route(
        team,
        source="nagios",
        token_hash=hash_token(raw_token),
        group_by=["nagios_host", "nagios_service"],
    )
    headers = {"Authorization": f"Bearer {raw_token}"}

    created = client.post(
        "/api/integrations/nagios",
        headers=headers,
        json=service_payload(),
    ).get_json()[0]

    response = client.post(
        "/api/integrations/nagios",
        headers=headers,
        json=service_payload(notification_type="ACKNOWLEDGEMENT"),
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "acknowledged"
    assert AlertGroup.get_by_id(created["group_id"]).status == "acknowledged"
