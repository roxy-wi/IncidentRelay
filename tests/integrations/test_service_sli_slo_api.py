from app.modules.db.models import ServiceEvent, ServiceSloMeasurement
from tests.factories import create_group, create_service, create_team


def _sli_payload(**overrides):
    payload = {
        "slug": "critical-ack-latency",
        "name": "Critical alert acknowledgement latency",
        "description": "Ack latency for critical alert groups.",
        "sli_type": "alert_ack_latency",
        "source": "incidentrelay_alert_groups",
        "configuration": {},
        "severity": "critical",
        "priority": None,
        "enabled": True,
    }
    payload.update(overrides)
    return payload


def _slo_payload(sli_id, **overrides):
    payload = {
        "sli_id": sli_id,
        "name": "95% critical alerts acknowledged within 15 minutes",
        "description": "Critical alert acknowledgement target.",
        "comparison": "percent_good_gte",
        "target_percent_basis_points": 9500,
        "threshold_seconds": 900,
        "threshold_count": None,
        "window_days": 30,
        "exclude_maintenance": True,
        "include_open_alerts": True,
        "enabled": True,
    }
    payload.update(overrides)
    return payload


def test_service_sli_slo_crud_details_analytics_and_timeline(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    response = client.post(
        f"/api/services/{service.id}/slis",
        headers=admin_headers,
        json=_sli_payload(),
    )

    assert response.status_code == 201
    sli = response.get_json()
    assert sli["service_id"] == service.id
    assert sli["sli_type"] == "alert_ack_latency"
    assert sli["severity"] == "critical"

    response = client.post(
        f"/api/services/{service.id}/slos",
        headers=admin_headers,
        json=_slo_payload(sli["id"]),
    )

    assert response.status_code == 201
    slo = response.get_json()
    assert slo["service_id"] == service.id
    assert slo["sli_id"] == sli["id"]
    assert slo["evaluation"]["status"] == "no_data"
    assert ServiceSloMeasurement.select().where(ServiceSloMeasurement.slo == slo["id"]).count() == 1

    response = client.get(
        f"/api/services/{service.id}/slis",
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.get_json()] == [sli["id"]]

    response = client.get(
        f"/api/services/{service.id}/slos",
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.get_json()] == [slo["id"]]

    response = client.get(
        f"/api/services/{service.id}/details",
        headers=admin_headers,
    )
    assert response.status_code == 200
    details = response.get_json()
    assert details["summary"]["slis"] == 1
    assert details["summary"]["slos"] == 1
    assert details["sli_slo"]["slis"][0]["id"] == sli["id"]
    assert details["sli_slo"]["slos"][0]["id"] == slo["id"]

    response = client.get(
        f"/api/services/sli-slo?service_id={service.id}",
        headers=admin_headers,
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert [item["id"] for item in payload["slis"]] == [sli["id"]]
    assert [item["id"] for item in payload["slos"]] == [slo["id"]]

    response = client.get(
        f"/api/services/sli-slo/analytics?service_id={service.id}",
        headers=admin_headers,
    )
    assert response.status_code == 200
    analytics = response.get_json()
    assert analytics["summary"]["total"] == 1
    assert analytics["summary"]["no_data"] == 1
    assert analytics["items"][0]["slo_id"] == slo["id"]

    event_types = [event.event_type for event in ServiceEvent.select().where(ServiceEvent.service == service.id)]
    assert "service_sli.created" in event_types
    assert "service_slo.created" in event_types


def test_create_slo_rejects_sli_from_another_service(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    other_service = create_service(team)

    response = client.post(
        f"/api/services/{other_service.id}/slis",
        headers=admin_headers,
        json=_sli_payload(slug="other-ack-latency"),
    )
    assert response.status_code == 201
    other_sli = response.get_json()

    response = client.post(
        f"/api/services/{service.id}/slos",
        headers=admin_headers,
        json=_slo_payload(other_sli["id"]),
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "service_sli_mismatch"


def test_incident_count_slo_shape_is_validated(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    response = client.post(
        f"/api/services/{service.id}/slis",
        headers=admin_headers,
        json=_sli_payload(
            slug="critical-incident-count",
            name="Critical incident count",
            sli_type="incident_count",
        ),
    )
    assert response.status_code == 201
    sli = response.get_json()

    response = client.post(
        f"/api/services/{service.id}/slos",
        headers=admin_headers,
        json=_slo_payload(sli["id"]),
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["error"] == "service_slo_invalid"
    assert "Incident count SLOs must use value_lte" in payload["message"]


def _create_sli_for_api_test(client, admin_headers, service, **overrides):
    response = client.post(
        f"/api/services/{service.id}/slis",
        headers=admin_headers,
        json=_sli_payload(**overrides),
    )

    assert response.status_code == 201, response.get_json()
    return response.get_json()


def _create_slo_for_api_test(client, admin_headers, service, sli_id, **overrides):
    response = client.post(
        f"/api/services/{service.id}/slos",
        headers=admin_headers,
        json=_slo_payload(sli_id, **overrides),
    )

    assert response.status_code == 201, response.get_json()
    return response.get_json()


def test_sli_scope_normalization_for_impact_and_latency(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    availability_sli = _create_sli_for_api_test(
        client,
        admin_headers,
        service,
        slug="availability",
        name="Availability",
        sli_type="incident_availability",
        configuration={},
        severity="critical",
        priority=None,
    )

    assert availability_sli["configuration"]["priority_scope"] == ["p1", "p2"]
    assert availability_sli["severity"] is None
    assert availability_sli["priority"] is None

    latency_sli = _create_sli_for_api_test(
        client,
        admin_headers,
        service,
        slug="critical-p1-p2-ack",
        name="Critical P1/P2 ack",
        sli_type="alert_ack_latency",
        configuration={"priority_scope": ["P1", "p2", "p2"]},
        severity="critical",
        priority=None,
    )

    assert latency_sli["configuration"]["priority_scope"] == ["p1", "p2"]
    assert latency_sli["severity"] == "critical"
    assert latency_sli["priority"] is None


def test_create_sli_rejects_invalid_priority_scope(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    response = client.post(
        f"/api/services/{service.id}/slis",
        headers=admin_headers,
        json=_sli_payload(
            slug="invalid-priority-scope",
            name="Invalid priority scope",
            sli_type="alert_ack_latency",
            configuration={"priority_scope": ["p1", "p9"]},
        ),
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["error"] == "validation_error"
    assert "priority_scope values must be one of p1, p2, p3, p4" in str(payload)


def test_slo_validation_covers_latency_availability_and_default_incident_count_comparison(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    ack_sli = _create_sli_for_api_test(
        client,
        admin_headers,
        service,
        slug="ack-validation",
        name="Ack validation",
        sli_type="alert_ack_latency",
    )

    response = client.post(
        f"/api/services/{service.id}/slos",
        headers=admin_headers,
        json=_slo_payload(
            ack_sli["id"],
            name="Ack without threshold",
            threshold_seconds=None,
        ),
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["error"] == "service_slo_invalid"
    assert "Latency SLOs require threshold_seconds" in payload["message"]

    availability_sli = _create_sli_for_api_test(
        client,
        admin_headers,
        service,
        slug="availability-validation",
        name="Availability validation",
        sli_type="incident_availability",
    )

    response = client.post(
        f"/api/services/{service.id}/slos",
        headers=admin_headers,
        json=_slo_payload(
            availability_sli["id"],
            name="Availability without target",
            target_percent_basis_points=None,
            threshold_seconds=None,
        ),
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["error"] == "service_slo_invalid"
    assert "Availability SLOs require target_percent_basis_points" in payload["message"]

    count_sli = _create_sli_for_api_test(
        client,
        admin_headers,
        service,
        slug="count-validation",
        name="Count validation",
        sli_type="incident_count",
    )

    count_payload = _slo_payload(
        count_sli["id"],
        name="Max incidents",
        target_percent_basis_points=None,
        threshold_seconds=None,
        threshold_count=1,
    )
    count_payload.pop("comparison")

    response = client.post(
        f"/api/services/{service.id}/slos",
        headers=admin_headers,
        json=count_payload,
    )

    assert response.status_code == 201
    slo = response.get_json()
    assert slo["comparison"] == "value_lte"
    assert slo["threshold_count"] == 1


def test_sli_slo_analytics_include_disabled_filter(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    sli = _create_sli_for_api_test(
        client,
        admin_headers,
        service,
        slug="analytics-ack",
        name="Analytics ack",
        sli_type="alert_ack_latency",
    )

    active_slo = _create_slo_for_api_test(
        client,
        admin_headers,
        service,
        sli["id"],
        name="Active ack target",
    )
    disabled_slo = _create_slo_for_api_test(
        client,
        admin_headers,
        service,
        sli["id"],
        name="Disabled ack target",
        enabled=False,
    )

    response = client.get(
        f"/api/services/sli-slo/analytics?service_id={service.id}&include_disabled=0",
        headers=admin_headers,
    )

    assert response.status_code == 200
    analytics = response.get_json()
    visible_ids = {item["slo_id"] for item in analytics["items"]}
    assert visible_ids == {active_slo["id"]}
    assert disabled_slo["id"] not in visible_ids
    assert analytics["summary"]["total"] == 1
    assert analytics["summary"]["disabled"] == 0

    response = client.get(
        f"/api/services/sli-slo/analytics?service_id={service.id}&include_disabled=1",
        headers=admin_headers,
    )

    assert response.status_code == 200
    analytics = response.get_json()
    visible_ids = {item["slo_id"] for item in analytics["items"]}
    assert visible_ids == {active_slo["id"], disabled_slo["id"]}
    assert analytics["summary"]["total"] == 2
    assert analytics["summary"]["disabled"] == 1
