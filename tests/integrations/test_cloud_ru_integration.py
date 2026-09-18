import pytest

from app.api.schemas.routes import RouteCreateSchema
from app.modules.db.models import Alert, AlertGroup
from app.services.integrations.cloud_ru_smn import (
    CloudRuSmnError,
    build_cloud_ru_smn_signing_string,
    validate_cloud_ru_signing_cert_url,
)
from app.services.integrations.normalizers.cloud_ru import normalize_cloud_ru
from tests.factories import create_group, create_route, create_team


TOPIC_URN = "urn:smn:ru-moscow-1:project-123:incidentrelay"


def cloud_ru_envelope(*, alarm_status="alarm", alarm_level=2, alarm_id="alarm-123"):
    return {
        "type": "Notification",
        "message_id": "smn-message-1",
        "topic_urn": TOPIC_URN,
        "subject": "[Major Alarm] Cloud Eye notification",
        "message": {
            "message_type": "alarm",
            "alarm_id": alarm_id,
            "alarm_name": "checkout-api-cpu",
            "alarm_status": alarm_status,
            "alarm_level": alarm_level,
            "namespace": "SYS.ECS",
            "metric_name": "cpu_util",
            "dimension": "instance_id:instance-123",
            "alarm_description": "CPU usage crossed the configured threshold",
        },
        "timestamp": "2026-09-17T10:00:00Z",
        "signature_version": "v1",
        "signature": "c2lnbmF0dXJl",
        "signing_cert_url": "https://smn.ru-moscow-1.hc.cloud.ru/SMN_ru-moscow-1_test.pem",
    }


def test_normalize_cloud_ru_cloud_eye_alarm():
    alert = normalize_cloud_ru(cloud_ru_envelope())[0]

    assert alert["source"] == "cloud_ru"
    assert alert["status"] == "firing"
    assert alert["severity"] == "high"
    assert alert["dedup_key"] == "alarm-123"
    assert alert["title"] == "checkout-api-cpu"
    assert alert["labels"]["cloud_ru_alarm_id"] == "alarm-123"
    assert alert["labels"]["cloud_ru_namespace"] == "SYS.ECS"
    assert alert["labels"]["cloud_ru_metric_name"] == "cpu_util"
    assert alert["labels"]["cloud_ru_dimension_instance_id"] == "instance-123"


def test_cloud_ru_resolved_uses_same_dedup_key():
    firing = normalize_cloud_ru(cloud_ru_envelope(alarm_status="alarm"))[0]
    resolved = normalize_cloud_ru(cloud_ru_envelope(alarm_status="ok"))[0]

    assert firing["status"] == "firing"
    assert resolved["status"] == "resolved"
    assert firing["dedup_key"] == resolved["dedup_key"]


def test_route_schema_requires_cloud_ru_topic_urn():
    with pytest.raises(ValueError, match="Topic URN"):
        RouteCreateSchema(team_id=1, name="Cloud.ru alerts", source="cloud_ru")

    route = RouteCreateSchema(
        team_id=1,
        name="Cloud.ru alerts",
        source="cloud_ru",
        integration_config={"cloud_ru": {"topic_urn": TOPIC_URN}},
    )
    assert route.source == "cloud_ru"


def test_cloud_ru_signing_string_matches_documented_v1_order():
    envelope = cloud_ru_envelope()
    envelope["message"] = '{"alarm_id":"alarm-123"}'

    signing = build_cloud_ru_smn_signing_string(envelope)

    assert signing.startswith('message\n{"alarm_id":"alarm-123"}\nmessage_id\n')
    assert signing.endswith(f"topic_urn\n{TOPIC_URN}\ntype\nNotification\n")


def test_cloud_ru_certificate_url_rejects_non_cloud_ru_host():
    with pytest.raises(CloudRuSmnError, match="host is not allowed"):
        validate_cloud_ru_signing_cert_url("https://127.0.0.1/cert.pem")


def test_cloud_ru_webhook_firing_and_resolved_update_same_alert(client, db, monkeypatch):
    group = create_group(slug="platform")
    team = create_team(group, slug="sre")
    route = create_route(
        team,
        source="cloud_ru",
        integration_config={"cloud_ru": {"topic_urn": TOPIC_URN}},
    )

    monkeypatch.setattr(
        "app.views.integrations_view.validate_cloud_ru_smn_message",
        lambda envelope, expected_topic_urn: True,
    )

    headers = {
        "X-SMN-MESSAGE-TYPE": "Notification",
        "X-SMN-MESSAGE-ID": "smn-message-1",
        "X-SMN-TOPIC-URN": TOPIC_URN,
    }

    response = client.post(
        f"/api/integrations/cloud-ru/{route.id}",
        headers=headers,
        json=cloud_ru_envelope(alarm_status="alarm"),
    )
    assert response.status_code in {200, 202}

    response = client.post(
        f"/api/integrations/cloud-ru/{route.id}",
        headers=headers,
        json=cloud_ru_envelope(alarm_status="ok"),
    )
    assert response.status_code in {200, 202}

    alerts = list(Alert.select().where(Alert.source == "cloud_ru"))
    assert len(alerts) == 1
    assert alerts[0].status == "resolved"

    groups = list(AlertGroup.select().where(AlertGroup.route == route.id))
    assert len(groups) == 1
    assert groups[0].status == "resolved"


def test_cloud_ru_webhook_rejects_header_mismatch(client, db, monkeypatch):
    group = create_group(slug="platform")
    team = create_team(group, slug="sre")
    route = create_route(
        team,
        source="cloud_ru",
        integration_config={"cloud_ru": {"topic_urn": TOPIC_URN}},
    )

    monkeypatch.setattr(
        "app.views.integrations_view.validate_cloud_ru_smn_message",
        lambda envelope, expected_topic_urn: True,
    )

    response = client.post(
        f"/api/integrations/cloud-ru/{route.id}",
        headers={"X-SMN-TOPIC-URN": "urn:smn:wrong"},
        json=cloud_ru_envelope(),
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "cloud_ru_smn_header_mismatch"
