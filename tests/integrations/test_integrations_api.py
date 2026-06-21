from app.services.integrations.auth import hash_token
from tests.factories import create_group, create_route, create_team


def alertmanager_payload():
    return {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "DiskFull",
                    "severity": "critical",
                    "instance": "host1",
                },
                "annotations": {
                    "summary": "Disk is full",
                    "description": "/var is 95% full",
                },
                "fingerprint": "disk-full-host1-var",
                "startsAt": "2026-05-18T10:00:00Z",
            }
        ],
    }


def test_alertmanager_endpoint_requires_token(client):
    response = client.post("/api/integrations/alertmanager", json=alertmanager_payload())

    assert response.status_code == 401
    assert response.is_json


def test_alertmanager_endpoint_accepts_valid_route_token(client, monkeypatch, db):
    raw_token = "test-route-token"
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    create_route(team, source="alertmanager", token_hash=hash_token(raw_token))

    calls = []

    def fake_process_incoming_alerts(alerts):
        calls.append(alerts)
        return {"ok": True, "count": len(alerts)}, 200

    monkeypatch.setattr(
        "app.views.integrations_view.process_incoming_alerts",
        fake_process_incoming_alerts,
    )

    response = client.post(
        "/api/integrations/alertmanager",
        headers={"Authorization": f"Bearer {raw_token}"},
        json=alertmanager_payload(),
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "count": 1}
    assert calls[0][0]["source"] == "alertmanager"
    assert calls[0][0]["title"] == "Disk is full"


def test_webhook_endpoint_rejects_invalid_payload_with_valid_route_token(client, db):
    raw_token = "test-route-token"
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    create_route(team, source="webhook", token_hash=hash_token(raw_token))

    response = client.post(
        "/api/integrations/webhook",
        headers={"Authorization": f"Bearer {raw_token}"},
        json={"message": "missing required title"},
    )

    assert response.status_code == 400
    assert response.is_json
    assert response.get_json()["error"] == "validation_error"


def librenms_payload(**overrides):
    payload = {
        "id": "12345",
        "uid": "lnms-alert-12345",
        "state": "1",
        "severity": "critical",
        "title": "Device down",
        "message": "Device router1 is unreachable",
        "hostname": "router1",
        "device_id": "77",
        "ip": "10.0.0.1",
        "os": "ios",
        "type": "network",
        "hardware": "Cisco IOS",
        "version": "17.9",
        "location": "DC1",
        "rule": "Device down",
        "timestamp": "2026-06-17 10:00:00",
        "team": "sre",
        "librenms_url": "https://librenms.example.com",
        "labels": {
            "environment": "prod",
        },
    }
    payload.update(overrides)
    return payload


def test_librenms_endpoint_accepts_valid_route_token(client, monkeypatch, db):
    raw_token = "test-route-token"

    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    create_route(
        team,
        source="librenms",
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
        "/api/integrations/librenms",
        headers={"Authorization": f"Bearer {raw_token}"},
        json=librenms_payload(),
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "count": 1}

    alert = calls[0][0]

    assert alert["source"] == "librenms"
    assert alert["team_slug"] == "sre"
    assert alert["external_id"] == "lnms-alert-12345"
    assert alert["title"] == "Device down"
    assert alert["message"] == "Device router1 is unreachable"
    assert alert["severity"] == "critical"
    assert alert["status"] == "firing"
    assert alert["labels"]["hostname"] == "router1"
    assert alert["labels"]["device_id"] == "77"
    assert alert["labels"]["event_link"] == (
        "https://librenms.example.com/device/device=router1/"
    )


def test_librenms_recovery_is_normalized_as_resolved(client, monkeypatch, db):
    raw_token = "test-route-token"

    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    create_route(
        team,
        source="librenms",
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
        "/api/integrations/librenms",
        headers={"Authorization": f"Bearer {raw_token}"},
        json=librenms_payload(state="0"),
    )

    assert response.status_code == 200

    alert = calls[0][0]

    assert alert["source"] == "librenms"
    assert alert["status"] == "resolved"
    assert alert["dedup_key"]


def test_librenms_endpoint_rejects_empty_payload_with_valid_route_token(
    client,
    db,
):
    raw_token = "test-route-token"

    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    create_route(
        team,
        source="librenms",
        token_hash=hash_token(raw_token),
    )

    response = client.post(
        "/api/integrations/librenms",
        headers={"Authorization": f"Bearer {raw_token}"},
        json={},
    )

    assert response.status_code == 400
    assert response.is_json
    assert response.get_json()["error"] == "validation_error"


def test_librenms_endpoint_requires_token(client):
    response = client.post(
        "/api/integrations/librenms",
        json=librenms_payload(),
    )

    assert response.status_code == 401
    assert response.is_json
    assert response.get_json()["error"] == "Route intake token is required"


def test_librenms_firing_and_recovery_use_same_dedup_key(
    client,
    monkeypatch,
    db,
):
    raw_token = "test-route-token"

    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    create_route(
        team,
        source="librenms",
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

    firing_response = client.post(
        "/api/integrations/librenms",
        headers={"Authorization": f"Bearer {raw_token}"},
        json=librenms_payload(state="1"),
    )
    assert firing_response.status_code == 200

    recovery_response = client.post(
        "/api/integrations/librenms",
        headers={"Authorization": f"Bearer {raw_token}"},
        json=librenms_payload(
            state="0",
            severity="ok",
            message="Device router1 recovered",
        ),
    )
    assert recovery_response.status_code == 200

    firing_alert = calls[0][0]
    recovery_alert = calls[1][0]

    assert firing_alert["status"] == "firing"
    assert recovery_alert["status"] == "resolved"
    assert firing_alert["external_id"] == recovery_alert["external_id"]
    assert firing_alert["dedup_key"] == recovery_alert["dedup_key"]


def test_librenms_endpoint_accepts_payload_with_labels_only(
    client,
    monkeypatch,
    db,
):
    raw_token = "test-route-token"

    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    create_route(
        team,
        source="librenms",
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
        "/api/integrations/librenms",
        headers={"Authorization": f"Bearer {raw_token}"},
        json={
            "labels": {
                "alertname": "LibreNMS custom alert",
                "hostname": "router1",
                "severity": "warning",
                "team": "sre",
            }
        },
    )

    assert response.status_code == 200, response.get_json()

    alert = calls[0][0]

    assert alert["source"] == "librenms"
    assert alert["team_slug"] == "sre"
    assert alert["title"] == "LibreNMS custom alert"
    assert alert["severity"] == "warning"
    assert alert["status"] == "firing"
    assert alert["labels"]["hostname"] == "router1"


def test_librenms_endpoint_uses_explicit_fingerprint_as_dedup_key(
    client,
    monkeypatch,
    db,
):
    raw_token = "test-route-token"

    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    create_route(
        team,
        source="librenms",
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
        "/api/integrations/librenms",
        headers={"Authorization": f"Bearer {raw_token}"},
        json=librenms_payload(
            fingerprint="librenms-router1-device-down",
        ),
    )

    assert response.status_code == 200, response.get_json()

    alert = calls[0][0]

    assert alert["dedup_key"] == "librenms-router1-device-down"


def test_librenms_endpoint_prefers_explicit_event_link(
    client,
    monkeypatch,
    db,
):
    raw_token = "test-route-token"

    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    create_route(
        team,
        source="librenms",
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
        "/api/integrations/librenms",
        headers={"Authorization": f"Bearer {raw_token}"},
        json=librenms_payload(
            event_link="https://librenms.example.com/alerts/12345",
            librenms_url="https://librenms.example.com",
        ),
    )

    assert response.status_code == 200, response.get_json()

    alert = calls[0][0]

    assert alert["labels"]["event_link"] == (
        "https://librenms.example.com/alerts/12345"
    )
