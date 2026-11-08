"""Exercise the native Cloud Monitoring webhook through Flask and the database."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.api.openapi.spec import build_openapi_spec
from app.modules.db.models import Alert, AlertGroup, ClosedGoogleMonitoringIncident
from app.services.integrations.auth import hash_token
from app.services.orchestration.simulator import normalize_simulation_payload
from tests.factories import create_group, create_route, create_team


SOURCE = "google_cloud_monitoring"
PATH = "/api/integrations/google-cloud-monitoring"
AUTH = ("incidentrelay", "test-route-token")


def envelope(state="open", **fields):
    """Build a native notification; no credentials travel in its body."""
    return {
        "version": "1.2",
        "incident": {
            "state": state,
            "scoping_project_id": "project-a",
            "incident_id": "0.example",
            **fields,
        },
    }


@pytest.fixture
def route(db):
    return create_route(
        create_team(create_group()),
        source=SOURCE,
        token_hash=hash_token(AUTH[1]),
        group_by=["gcp_project_id", "gcp_incident_id"],
    )


def test_new_route_accepts_its_generated_token(client, admin_headers):
    team = create_team(create_group())
    response = client.post(
        "/api/routes",
        headers=admin_headers,
        json={"team_id": team.id, "name": "Google Monitoring", "source": SOURCE},
    )
    assert response.status_code == 201
    created = response.get_json()
    accepted = client.post(
        PATH,
        auth=("incidentrelay", created["intake_token"]),
        json=envelope(),
    )
    assert accepted.status_code == 200
    assert accepted.json[0]["route_id"] == created["id"]


def test_renotify_updates_alert_and_close_is_terminal(client, route):
    def send(state, **fields):
        return client.post(PATH, auth=AUTH, json=envelope(state, **fields))

    url = "https://console.cloud.google.com/monitoring/alerting/incidents/0.example"
    opened = send("open", policy_name="High CPU", severity="Error", url=url)
    assert opened.status_code == 200
    alert = Alert.get_by_id(opened.json[0]["alert_id"])
    assert (alert.route_id, alert.title, alert.severity) == (
        route.id,
        "High CPU",
        "high",
    )
    assert alert.labels["event_link"] == url
    updated = send(
        "open",
        renotify=True,
        summary="CPU still high",
        condition_name="CPU > 90%",
        resource={"type": "gce_instance"},
        resource_display_name="worker-01",
    )
    assert updated.status_code == 200
    assert updated.json[0]["alert_id"] == alert.id
    alert = Alert.get_by_id(alert.id)
    assert alert.message == "CPU still high"
    assert alert.labels["gcp_resource_type"] == "gce_instance"
    assert alert.labels["gcp_resource_name"] == "worker-01"
    assert alert.labels["gcp_condition"] == "CPU > 90%"
    closed = send("closed")
    assert closed.status_code == 200
    assert closed.json[0]["alert_id"] == alert.id
    for state in ("closed", "open"):
        ignored = send(state)
        assert ignored.status_code == 202
        assert ignored.json[0]["outcome"] == "ignored"
    assert [item.status for item in Alert.select()] == ["resolved"]
    assert [item.status for item in AlertGroup.select()] == ["resolved"]
    assert ClosedGoogleMonitoringIncident.select().count() == 1


def test_close_first_and_identity_isolation(client, route):
    assert client.post(PATH, auth=AUTH, json=envelope("closed")).status_code == 202
    assert client.post(PATH, auth=AUTH, json=envelope()).status_code == 202
    assert not Alert.select().exists()
    assert not AlertGroup.select().exists()

    second = create_route(
        route.team,
        source=SOURCE,
        token_hash=hash_token("second-route"),
    )
    assert (
        client.post(
            PATH,
            auth=("incidentrelay", "second-route"),
            json=envelope(),
        ).status_code
        == 200
    )
    assert (
        client.post(
            PATH,
            auth=AUTH,
            json=envelope(scoping_project_id="project-b"),
        ).status_code
        == 200
    )
    assert {(a.route_id, a.labels["gcp_project_id"]) for a in Alert.select()} == {
        (second.id, "project-a"),
        (route.id, "project-b"),
    }


@pytest.mark.parametrize("auth", [None, ("other", AUTH[1]), ("incidentrelay", "wrong")])
def test_challenge_and_route_boundaries(client, route, auth):
    response = client.post(PATH, auth=auth, json=envelope())
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Basic ")
    assert not Alert.select().exists()


def test_requires_enabled_matching_route(client, route):
    route.source = "webhook"
    route.save()
    response = client.post(PATH, auth=AUTH, json=envelope())
    assert response.status_code == 400
    assert response.json["error"] == "route_source_mismatch"
    route.enabled = False
    route.save()
    assert client.post(PATH, auth=AUTH, json=envelope()).status_code == 401
    assert not ClosedGoogleMonitoringIncident.select().exists()
    assert not Alert.select().exists()


@pytest.mark.parametrize(
    "body",
    [
        {"version": "1.2"},
        {"version": "2", "incident": envelope()["incident"]},
        envelope("unknown"),
        envelope(incident_id=" "),
        envelope(scoping_project_id=None),
    ],
)
def test_invalid_payload_has_no_side_effects(client, route, body):
    response = client.post(PATH, json=body, auth=AUTH)
    assert response.status_code == 400
    assert not Alert.select().exists()
    assert not ClosedGoogleMonitoringIncident.select().exists()


def test_failed_close_can_be_retried(client, route, monkeypatch):
    assert client.post(PATH, auth=AUTH, json=envelope()).status_code == 200
    with monkeypatch.context() as patch:

        def fail_write(**fields):
            raise RuntimeError("simulated storage failure")

        patch.setattr(ClosedGoogleMonitoringIncident, "create", fail_write)
        assert client.post(PATH, auth=AUTH, json=envelope("closed")).status_code == 500
    assert Alert.get().status == "firing"
    assert not ClosedGoogleMonitoringIncident.select().exists()
    assert client.post(PATH, auth=AUTH, json=envelope("closed")).status_code == 200
    assert Alert.get().status == "resolved"


@pytest.mark.parametrize("first,second", [("open", "open"), ("closed", "open")])
def test_concurrent_deliveries(app, route, first, second):
    start = Barrier(2)

    def deliver(state):
        with app.test_client() as client:
            start.wait(timeout=10)
            return client.post(PATH, auth=AUTH, json=envelope(state)).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [pool.submit(deliver, state) for state in (first, second)]
        assert all(call.result(timeout=15) in (200, 202) for call in calls)
    if first == "open":
        assert [a.status for a in Alert.select()] == ["firing"]
        assert AlertGroup.select().count() == 1
    else:
        assert not Alert.select().where(Alert.status != "resolved").exists()
        assert ClosedGoogleMonitoringIncident.select().count() == 1


def test_simulation_and_openapi_describe_native_payload():
    source, simulated, count = normalize_simulation_payload(
        source=SOURCE,
        payload=envelope(url="javascript:alert(1)", severity="no severity"),
    )
    assert (source, count, simulated["severity"]) == (SOURCE, 1, "info")
    assert "event_link" not in simulated["labels"]
    assert not Alert.select().exists()
    op = build_openapi_spec()["paths"][PATH]["post"]
    assert op["security"] == [{"basicRouteAuth": []}]
    assert "WWW-Authenticate" in op["responses"]["401"]["headers"]
