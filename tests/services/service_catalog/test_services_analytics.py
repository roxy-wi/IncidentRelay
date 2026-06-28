from app.login import create_access_token
from app.modules.db import services_repo
from tests.factories import (
    create_service,
    create_group,
    create_team,
    unique,
    create_impact_alert_group,
    create_service_alert,
    create_route,
    create_service_dependency,
)


def make_headers(user):
    token, _ = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


def create_test_service(team, *, name, enabled=True):
    return services_repo.create_service({
        "team": team.id,
        "slug": unique("service"),
        "name": name,
        "description": "",
        "service_type": "application",
        "environment": "prod",
        "criticality": "medium",
        "tier": "backend",
        "status": "operational",
        "status_source": "manual",
        "status_message": "",
        "default_rotation": None,
        "default_escalation_policy": None,
        "labels": {},
        "tags": [],
        "metadata": {},
        "enabled": enabled,
        "public": False,
        "public_name": "",
        "public_description": "",
        "public_order": 0,
    })


def test_service_analytics_does_not_include_disabled_service(client, admin_headers):
    group = create_group()
    team = create_team(group)

    active = create_service(
        team,
        slug=unique("active-api"),
        name="Active API",
    )

    disabled = create_service(
        team,
        slug=unique("disabled-api"),
        name="Disabled API",
    )
    disabled.enabled = False
    disabled.status = "disabled"
    disabled.save()

    response = client.get(
        f"/api/services/analytics?team_id={team.id}",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    data = response.get_json()

    assert data["version"] == 2

    service_ids = {
        item["service_id"]
        for item in data["items"]
    }

    assert active.id in service_ids
    assert disabled.id not in service_ids


def test_service_analytics_does_not_include_deleted_service(client, admin_headers):
    group = create_group()
    team = create_team(group)

    active = create_service(
        team,
        slug=unique("active-api"),
        name="Active API",
    )

    deleted = create_service(
        team,
        slug=unique("deleted-api"),
        name="Deleted API",
    )
    deleted.deleted = True
    deleted.save()

    response = client.get(
        f"/api/services/analytics?team_id={team.id}",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    data = response.get_json()

    assert data["version"] == 2

    service_ids = {
        item["service_id"]
        for item in data["items"]
    }

    assert active.id in service_ids
    assert deleted.id not in service_ids


def test_service_analytics_returns_404_for_disabled_service_filter(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)

    disabled = create_service(
        team,
        slug=unique("disabled-api"),
        name="Disabled API",
    )
    disabled.enabled = False
    disabled.status = "disabled"
    disabled.save()

    response = client.get(
        f"/api/services/analytics?service_id={disabled.id}",
        headers=admin_headers,
    )

    assert response.status_code == 404


def test_service_analytics_v2_rejects_invalid_days(client, admin_headers):
    response = client.get(
        "/api/services/analytics?days=9999",
        headers=admin_headers,
    )

    assert response.status_code == 400

    data = response.get_json()

    assert data["error"] == "validation_error"
    assert data["message"] == "Request validation failed"
    assert any(
        detail.get("field") == "days"
        for detail in data.get("details", [])
    )


def test_service_analytics_v2_rejects_invalid_sort(client, admin_headers):
    response = client.get(
        "/api/services/analytics?sort=created_at",
        headers=admin_headers,
    )

    assert response.status_code == 400

    data = response.get_json()

    assert data["error"] == "validation_error"
    assert data["message"] == "Request validation failed"
    assert any(
        detail.get("field") == "sort"
        for detail in data.get("details", [])
    )


def find_analytics_item(payload, service):
    for item in payload["items"]:
        if item["service_id"] == service.id:
            return item

    raise AssertionError(
        "Analytics item for service {0} was not found in payload: {1}".format(
            service.slug,
            payload,
        )
    )


def test_service_analytics_v2_returns_grouped_raw_and_impact_metrics(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)

    database = create_service(
        team,
        slug=unique("postgresql-prod"),
        name="PostgreSQL Prod",
        criticality="critical",
        tier="tier_1",
    )
    billing = create_service(
        team,
        slug=unique("billing-api"),
        name="Billing API",
        criticality="critical",
        tier="tier_1",
    )
    route = create_route(team, service=billing)

    create_service_dependency(
        service=billing,
        depends_on_service=database,
        dependency_type="hard",
        criticality="required",
    )

    create_impact_alert_group(
        team=team,
        service=billing,
        route=route,
        status="firing",
        severity="critical",
        alertname="BillingApiDown",
        summary="Billing API is down",
    )

    create_impact_alert_group(
        team=team,
        service=billing,
        route=route,
        status="acknowledged",
        severity="warning",
        alertname="BillingApiSlow",
        summary="Billing API is slow",
    )

    create_impact_alert_group(
        team=team,
        service=billing,
        route=route,
        status="resolved",
        severity="info",
        alertname="BillingApiResolved",
        summary="Billing API recovered",
    )

    create_impact_alert_group(
        team=team,
        service=database,
        status="firing",
        severity="critical",
        alertname="PostgreSQLDown",
        summary="PostgreSQL is down",
    )

    create_service_alert(
        team=team,
        route=route,
        service=billing,
        fingerprint=unique("billing-api-raw-1"),
        status="firing",
        severity="critical",
        alertname="BillingApiDown",
        summary="Billing API is down",
    )
    create_service_alert(
        team=team,
        route=route,
        service=billing,
        fingerprint=unique("billing-api-raw-2"),
        status="firing",
        severity="critical",
        alertname="BillingApiDown",
        summary="Billing API is still down",
    )
    create_service_alert(
        team=team,
        route=route,
        service=billing,
        fingerprint=unique("billing-api-raw-3"),
        status="acknowledged",
        severity="warning",
        alertname="BillingApiSlow",
        summary="Billing API is slow",
    )

    response = client.get(
        f"/api/services/analytics?team_id={team.id}&days=30"
        "&include_series=true"
        "&include_noise=true"
        "&include_response=true"
        "&include_maintenance=true"
        "&include_impact=true"
        "&include_operational=true"
        "&sort=open_alert_groups"
        "&order=desc",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()

    assert payload["version"] == 2
    assert payload["window"]["days"] == 30
    assert "items" in payload
    assert "summary" in payload
    assert "series" in payload
    assert "filters" in payload

    billing_item = find_analytics_item(payload, billing)

    assert billing_item["service_id"] == billing.id
    assert billing_item["service_slug"] == billing.slug
    assert billing_item["service_name"] == "Billing API"

    assert billing_item["alert_groups"]["total"] == 3
    assert billing_item["alert_groups"]["open"] == 2
    assert billing_item["alert_groups"]["firing"] == 1
    assert billing_item["alert_groups"]["acknowledged"] == 1
    assert billing_item["alert_groups"]["resolved"] == 1
    assert billing_item["alert_groups"]["critical_open"] == 1
    assert billing_item["alert_groups"]["by_status"]["firing"] == 1
    assert billing_item["alert_groups"]["by_status"]["acknowledged"] == 1
    assert billing_item["alert_groups"]["by_status"]["resolved"] == 1
    assert billing_item["alert_groups"]["by_severity"]["critical"] == 1

    assert billing_item["noise"]["raw_alerts"] == 3
    assert billing_item["noise"]["alert_groups"] == 3
    assert billing_item["noise"]["dedup_ratio"] == 1
    assert billing_item["noise"]["top_alertnames"][0]["alertname"] == "BillingApiDown"
    assert billing_item["noise"]["top_alertnames"][0]["count"] == 2

    assert billing_item["impact"]["effective_status"] == "major_outage"
    assert billing_item["impact"]["primary_reason"] in {
        "alert_group",
        "upstream_dependency",
    }
    assert billing_item["impact"]["blast_radius"]["transitive_downstream"] >= 0

    assert payload["summary"]["services"] >= 2
    assert payload["summary"]["open_alert_groups"] >= 3
    assert payload["summary"]["critical_open_alert_groups"] >= 2
    assert payload["summary"]["raw_alerts"] >= 3

    assert payload["series"]["alert_groups_by_day"]
    assert payload["series"]["raw_alerts_by_day"]


def test_service_analytics_v2_can_disable_noise_metrics(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(
        team,
        slug=unique("billing-api"),
        name="Billing API",
    )
    route = create_route(team, service=service)

    create_impact_alert_group(
        team=team,
        service=service,
        route=route,
        status="firing",
        severity="critical",
        alertname="BillingApiDown",
        summary="Billing API is down",
    )

    create_service_alert(
        team=team,
        route=route,
        service=service,
        fingerprint=unique("billing-api-raw"),
        status="firing",
        severity="critical",
        alertname="BillingApiDown",
        summary="Billing API is down",
    )

    response = client.get(
        f"/api/services/analytics?team_id={team.id}&include_noise=false",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()
    item = find_analytics_item(payload, service)

    assert item["alert_groups"]["total"] == 1
    assert item["noise"]["raw_alerts"] == 0
    assert item["noise"]["alert_groups"] == 0
    assert item["noise"]["dedup_ratio"] == 0
    assert item["noise"]["top_alertnames"] == []


def test_service_analytics_v2_can_disable_impact_widget(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(
        team,
        slug=unique("billing-api"),
        name="Billing API",
        status="operational",
    )

    response = client.get(
        f"/api/services/analytics?team_id={team.id}&include_impact=false",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()
    item = find_analytics_item(payload, service)

    assert item["impact"]["effective_status"] == "operational"
    assert item["impact"]["primary_reason"] is None
    assert item["impact"]["upstream_issues_count"] == 0
    assert item["impact"]["root_causes"] == 0
    assert item["impact"]["blast_radius"]["transitive_downstream"] == 0


def test_service_analytics_v2_can_disable_series(client, admin_headers):
    group = create_group()
    team = create_team(group)

    service = create_service(
        team,
        slug=unique("billing-api"),
        name="Billing API",
    )
    route = create_route(team, service=service)

    create_impact_alert_group(
        team=team,
        service=service,
        route=route,
        status="firing",
        severity="critical",
        alertname="BillingApiDown",
        summary="Billing API is down",
    )

    create_service_alert(
        team=team,
        route=route,
        service=service,
        fingerprint=unique("billing-api-raw"),
        status="firing",
        severity="critical",
        alertname="BillingApiDown",
        summary="Billing API is down",
    )

    response = client.get(
        f"/api/services/analytics?team_id={team.id}&include_series=false",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    data = response.get_json()

    assert data["version"] == 2
    assert data["series"]["alert_groups_by_day"] == []
    assert data["series"]["raw_alerts_by_day"] == []
    assert data["series"]["impact_by_day"] == []


def test_service_analytics_v2_can_exclude_operational_services(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)

    healthy = create_service(
        team,
        slug=unique("healthy-api"),
        name="Healthy API",
        status="operational",
    )
    noisy = create_service(
        team,
        slug=unique("noisy-api"),
        name="Noisy API",
        status="operational",
    )

    create_impact_alert_group(
        team=team,
        service=noisy,
        status="firing",
        severity="critical",
        alertname="NoisyApiDown",
        summary="Noisy API is down",
    )

    response = client.get(
        f"/api/services/analytics?team_id={team.id}&include_operational=false",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    data = response.get_json()

    assert data["version"] == 2

    service_ids = {
        item["service_id"]
        for item in data["items"]
    }

    assert noisy.id in service_ids
    assert healthy.id not in service_ids


def test_service_analytics_v2_service_filter_keeps_impact_graph(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)

    database = create_service(
        team,
        slug=unique("postgresql-prod"),
        name="PostgreSQL Prod",
        criticality="critical",
        tier="tier_1",
    )
    billing = create_service(
        team,
        slug=unique("billing-api"),
        name="Billing API",
        criticality="critical",
        tier="tier_1",
    )

    create_service_dependency(
        service=billing,
        depends_on_service=database,
        dependency_type="hard",
        criticality="required",
    )

    create_impact_alert_group(
        team=team,
        service=database,
        status="firing",
        severity="critical",
        alertname="PostgreSQLDown",
        summary="PostgreSQL is down",
    )

    response = client.get(
        f"/api/services/analytics?service_id={billing.id}&include_impact=true",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    data = response.get_json()

    assert data["version"] == 2
    assert len(data["items"]) == 1

    item = data["items"][0]

    assert item["service_id"] == billing.id
    assert item["impact"]["effective_status"] == "major_outage"
    assert item["impact"]["primary_reason"] == "upstream_dependency"
    assert item["impact"]["upstream_issues_count"] == 1


def test_service_analytics_v2_hides_disabled_services_by_default(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)

    active = create_service(
        team,
        slug=unique("active-api"),
        name="Active API",
    )
    disabled = create_service(
        team,
        slug=unique("disabled-api"),
        name="Disabled API",
    )
    disabled.enabled = False
    disabled.status = "disabled"
    disabled.save()

    response = client.get(
        f"/api/services/analytics?team_id={team.id}",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    data = response.get_json()

    service_ids = {
        item["service_id"]
        for item in data["items"]
    }

    assert active.id in service_ids
    assert disabled.id not in service_ids


def test_service_analytics_v2_can_include_disabled_services(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)

    disabled = create_service(
        team,
        slug=unique("disabled-api"),
        name="Disabled API",
    )
    disabled.enabled = False
    disabled.status = "disabled"
    disabled.save()

    response = client.get(
        f"/api/services/analytics?team_id={team.id}&include_disabled=true",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    data = response.get_json()

    item = find_analytics_item(data, disabled)

    assert item["service_id"] == disabled.id
    assert item["enabled"] is False
    assert item["impact"]["effective_status"] == "disabled"


def test_service_analytics_v2_sorts_by_raw_alerts(client, admin_headers):
    group = create_group()
    team = create_team(group)

    noisy = create_service(
        team,
        slug=unique("noisy-api"),
        name="Noisy API",
    )
    quiet = create_service(
        team,
        slug=unique("quiet-api"),
        name="Quiet API",
    )

    noisy_route = create_route(team, service=noisy)
    quiet_route = create_route(team, service=quiet)

    create_service_alert(
        team=team,
        route=noisy_route,
        service=noisy,
        fingerprint=unique("noisy-raw-1"),
        status="firing",
        severity="warning",
        alertname="NoisyApiWarning",
        summary="Noisy API warning",
    )
    create_service_alert(
        team=team,
        route=noisy_route,
        service=noisy,
        fingerprint=unique("noisy-raw-2"),
        status="firing",
        severity="warning",
        alertname="NoisyApiWarning",
        summary="Noisy API warning again",
    )
    create_service_alert(
        team=team,
        route=noisy_route,
        service=noisy,
        fingerprint=unique("noisy-raw-3"),
        status="firing",
        severity="warning",
        alertname="NoisyApiWarning",
        summary="Noisy API warning again",
    )

    create_service_alert(
        team=team,
        route=quiet_route,
        service=quiet,
        fingerprint=unique("quiet-raw-1"),
        status="firing",
        severity="info",
        alertname="QuietApiInfo",
        summary="Quiet API info",
    )

    response = client.get(
        f"/api/services/analytics?team_id={team.id}"
        "&sort=raw_alerts"
        "&order=desc"
        "&include_noise=true",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    data = response.get_json()

    assert data["version"] == 2
    assert len(data["items"]) >= 2

    assert data["items"][0]["service_id"] == noisy.id
    assert data["items"][0]["noise"]["raw_alerts"] == 3

    quiet_item = find_analytics_item(data, quiet)

    assert quiet_item["noise"]["raw_alerts"] == 1


def test_service_analytics_v2_counts_alert_groups_by_service(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)

    service = create_service(
        team,
        slug=unique("billing-api"),
        name="Billing API",
    )

    create_impact_alert_group(
        team=team,
        service=service,
        status="firing",
        severity="critical",
        alertname="BillingApiDown",
        summary="Billing API is down",
    )

    response = client.get(
        f"/api/services/analytics?team_id={team.id}",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    data = response.get_json()

    assert data["version"] == 2
    assert len(data["items"]) == 1

    item = data["items"][0]

    assert item["service_id"] == service.id
    assert item["alert_groups"]["total"] == 1
    assert item["alert_groups"]["open"] == 1
    assert item["alert_groups"]["firing"] == 1
    assert item["alert_groups"]["critical_open"] == 1


def test_service_analytics_can_filter_disabled_service_when_included(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)

    disabled = create_service(
        team,
        slug=unique("disabled-api"),
        name="Disabled API",
    )
    disabled.enabled = False
    disabled.status = "disabled"
    disabled.save()

    response = client.get(
        f"/api/services/analytics?service_id={disabled.id}&include_disabled=true",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    data = response.get_json()

    assert data["version"] == 2
    assert len(data["items"]) == 1
    assert data["items"][0]["service_id"] == disabled.id
    assert data["items"][0]["enabled"] is False
    assert data["items"][0]["impact"]["effective_status"] == "disabled"


def test_service_analytics_v2_uses_alert_group_count_for_raw_alert_fallback(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)

    service = create_service(
        team,
        slug=unique("billing-api"),
        name="Billing API",
    )

    alert_group = create_impact_alert_group(
        team=team,
        service=service,
        status="firing",
        severity="critical",
        alertname="BillingApiDown",
        summary="Billing API is down",
    )
    alert_group.alert_count = 7
    alert_group.save()

    response = client.get(
        f"/api/services/analytics?team_id={team.id}&include_noise=true&include_series=true",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    data = response.get_json()
    item = find_analytics_item(data, service)

    assert item["noise"]["raw_alerts"] == 7
    assert item["noise"]["alert_groups"] == 1
    assert item["noise"]["dedup_ratio"] == 7

    raw_series_total = sum(
        row["raw_alerts"]
        for row in data["series"]["raw_alerts_by_day"]
    )

    assert raw_series_total == 7
