import pytest
from datetime import datetime

from pydantic import ValidationError

from app.login import create_access_token
from tests.factories import create_user, unique
from app.api.schemas.services import (
    ServiceCreateSchema,
    ServiceDependencyCreateSchema,
    ServiceMatchRuleCreateSchema,
)
from app.modules.db.models import (
    AlertGroup,
    ServiceDependency,
    ServiceLink,
    ServiceMatchRule,
    ServiceRunbook,
)
from tests.factories import (
    create_group,
    create_route,
    create_service,
    create_team,
    create_impact_alert_group,
    create_service_dependency,
)


def service_payload(team, **overrides):
    payload = {
        "team_id": team.id,
        "slug": "rabbitmq-cloud",
        "name": "RabbitMQ Cloud",
        "description": "Shared RabbitMQ cluster",
        "service_type": "queue",
        "environment": "production",
        "criticality": "critical",
        "tier": "tier_1",
        "status": "operational",
        "status_source": "manual",
        "labels": {"system": "messaging"},
        "tags": ["rabbitmq", "production"],
        "metadata": {},
        "enabled": True,
        "public": False,
        "public_order": 100,
    }
    payload.update(overrides)
    return payload


def test_service_schema_accepts_valid_payload():
    group = create_group()
    team = create_team(group)

    schema = ServiceCreateSchema(**service_payload(team))

    assert schema.team_id == team.id
    assert schema.slug == "rabbitmq-cloud"
    assert schema.service_type == "queue"
    assert schema.environment == "production"
    assert schema.criticality == "critical"
    assert schema.tier == "tier_1"
    assert schema.status == "operational"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("slug", "RabbitMQ Cloud"),
        ("service_type", "unknown-type"),
        ("environment", "prod"),
        ("criticality", "blocker"),
        ("tier", "tier_0"),
        ("status", "broken"),
        ("status_source", "operator"),
    ],
)
def test_service_schema_rejects_invalid_enums_and_slug(field, value):
    group = create_group()
    team = create_team(group)
    payload = service_payload(team, **{field: value})

    with pytest.raises(ValidationError):
        ServiceCreateSchema(**payload)


def test_service_match_rule_schema_requires_matchers():
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    with pytest.raises(ValidationError):
        ServiceMatchRuleCreateSchema(
            team_id=team.id,
            service_id=service.id,
            name="Empty match rule",
            matchers={},
        )


def test_service_match_rule_schema_accepts_label_regex_matcher():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    route = create_route(team)

    schema = ServiceMatchRuleCreateSchema(
        team_id=team.id,
        route_id=route.id,
        service_id=service.id,
        name="RabbitMQ Cloud labels",
        position=10,
        enabled=True,
        matchers={
            "labels": {
                "job": "RabbitMQ",
                "rabbitmq": {
                    "op": "regex",
                    "value": "^rabbitmq-cloud$",
                },
            }
        },
    )

    assert schema.team_id == team.id
    assert schema.route_id == route.id
    assert schema.service_id == service.id
    assert schema.matchers["labels"]["job"] == "RabbitMQ"


def test_service_dependency_schema_rejects_self_dependency():
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    with pytest.raises(ValidationError):
        ServiceDependencyCreateSchema(
            service_id=service.id,
            depends_on_service_id=service.id,
            dependency_type="hard",
            criticality="required",
        )


def test_create_and_list_services_api(client, admin_headers):
    group = create_group()
    team = create_team(group)

    response = client.post(
        "/api/services",
        json=service_payload(team),
        headers=admin_headers,
    )

    assert response.status_code == 201
    data = response.get_json()
    assert data["id"]
    assert data["team_id"] == team.id
    assert data["slug"] == "rabbitmq-cloud"
    assert data["name"] == "RabbitMQ Cloud"
    assert data["service_type"] == "queue"
    assert data["criticality"] == "critical"

    response = client.get(
        f"/api/services?team_id={team.id}",
        headers=admin_headers,
    )

    assert response.status_code == 200
    items = response.get_json()
    assert any(item["slug"] == "rabbitmq-cloud" for item in items)


def test_get_update_and_delete_service_api(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(team, slug="billing-api", name="Billing API")

    response = client.get(
        f"/api/services/{service.id}",
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["slug"] == "billing-api"

    response = client.put(
        f"/api/services/{service.id}",
        json=service_payload(
            team,
            slug="billing-api",
            name="Billing API",
            status="degraded",
            status_message="High latency",
            criticality="high",
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "degraded"
    assert data["status_message"] == "High latency"
    assert data["criticality"] == "high"

    response = client.delete(
        f"/api/services/{service.id}",
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["deleted"] is True

    response = client.get(
        f"/api/services/{service.id}",
        headers=admin_headers,
    )

    assert response.status_code == 404


def test_service_slug_must_be_unique_inside_team(client, admin_headers):
    group = create_group()
    team = create_team(group)

    first = client.post(
        "/api/services",
        json=service_payload(team, slug="rabbitmq-cloud"),
        headers=admin_headers,
    )
    assert first.status_code == 201

    duplicate = client.post(
        "/api/services",
        json=service_payload(team, slug="rabbitmq-cloud"),
        headers=admin_headers,
    )
    assert duplicate.status_code == 409


def test_create_and_list_service_match_rules_api(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    route = create_route(team)

    response = client.post(
        f"/api/services/{service.id}/match-rules",
        json={
            "team_id": team.id,
            "route_id": route.id,
            "service_id": service.id,
            "name": "RabbitMQ Cloud labels",
            "position": 10,
            "enabled": True,
            "matchers": {
                "labels": {
                    "job": "RabbitMQ",
                    "rabbitmq": {
                        "op": "regex",
                        "value": "^rabbitmq-cloud$",
                    },
                }
            },
        },
        headers=admin_headers,
    )

    assert response.status_code == 201
    data = response.get_json()
    assert data["id"]
    assert data["team_id"] == team.id
    assert data["service_id"] == service.id
    assert data["route_id"] == route.id
    assert data["matchers"]["labels"]["job"] == "RabbitMQ"

    response = client.get(
        f"/api/services/match-rules?service_id={service.id}",
        headers=admin_headers,
    )

    assert response.status_code == 200
    items = response.get_json()
    assert len(items) == 1
    assert items[0]["name"] == "RabbitMQ Cloud labels"


def test_update_and_delete_service_match_rule_api(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    rule = ServiceMatchRule.create(
        team=team,
        service=service,
        name="Old rule",
        position=10,
        enabled=True,
        matchers={"labels": {"job": "old"}},
    )

    response = client.put(
        f"/api/services/match-rules/{rule.id}",
        json={
            "team_id": team.id,
            "service_id": service.id,
            "name": "New rule",
            "position": 20,
            "enabled": False,
            "matchers": {"labels": {"job": "new"}},
        },
        headers=admin_headers,
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["name"] == "New rule"
    assert data["position"] == 20
    assert data["enabled"] is False

    response = client.delete(
        f"/api/services/match-rules/{rule.id}",
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["deleted"] is True


def test_create_list_update_delete_service_links_api(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    response = client.post(
        f"/api/services/{service.id}/links",
        json={
            "link_type": "dashboard",
            "label": "Grafana",
            "url": "https://grafana.example.com/d/rabbitmq-cloud",
            "priority": 10,
            "enabled": True,
        },
        headers=admin_headers,
    )

    assert response.status_code == 201
    link = response.get_json()
    assert link["label"] == "Grafana"
    assert link["link_type"] == "dashboard"
    assert link["service_id"] == service.id
    assert link["service_name"] == service.name
    assert link["service_slug"] == service.slug
    assert link["team_id"] == team.id
    assert link["team_name"] == team.name
    assert link["team_slug"] == team.slug

    response = client.get(
        f"/api/services/{service.id}/links",
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert len(response.get_json()) == 1

    response = client.put(
        f"/api/services/links/{link['id']}",
        json={
            "link_type": "logs",
            "label": "Loki",
            "url": "https://logs.example.com",
            "priority": 20,
            "enabled": False,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["link_type"] == "logs"

    response = client.delete(
        f"/api/services/links/{link['id']}",
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["deleted"] is True


def test_create_list_update_delete_service_runbooks_api(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    response = client.post(
        f"/api/services/{service.id}/runbooks",
        json={
            "title": "RabbitMQ cluster partition",
            "url": "https://docs.example.com/runbooks/rabbitmq/cluster-partition",
            "severity": "critical",
            "priority": 10,
            "enabled": True,
            "matchers": {
                "labels": {
                    "alertname": "RabbitMQClusterPartition",
                }
            },
        },
        headers=admin_headers,
    )

    assert response.status_code == 201
    runbook = response.get_json()
    assert runbook["title"] == "RabbitMQ cluster partition"
    assert runbook["severity"] == "critical"

    response = client.get(
        f"/api/services/{service.id}/runbooks",
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert len(response.get_json()) == 1

    response = client.put(
        f"/api/services/runbooks/{runbook['id']}",
        json={
            "title": "Updated runbook",
            "url": "https://docs.example.com/runbooks/rabbitmq/updated",
            "severity": "warning",
            "priority": 20,
            "enabled": False,
            "matchers": {},
        },
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["title"] == "Updated runbook"

    response = client.delete(
        f"/api/services/runbooks/{runbook['id']}",
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["deleted"] is True


def test_create_list_update_delete_service_dependencies_api(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(team, slug="billing-api", name="Billing API")
    upstream = create_service(team, slug="postgresql-prod", name="PostgreSQL Prod")

    response = client.post(
        f"/api/services/{service.id}/dependencies",
        json={
            "depends_on_service_id": upstream.id,
            "dependency_type": "hard",
            "criticality": "required",
            "description": "Billing API stores data in PostgreSQL",
            "enabled": True,
        },
        headers=admin_headers,
    )

    assert response.status_code == 201
    dependency = response.get_json()
    assert dependency["depends_on_service_id"] == upstream.id
    assert dependency["dependency_type"] == "hard"
    assert dependency["criticality"] == "required"

    response = client.get(
        f"/api/services/{service.id}/dependencies",
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert len(response.get_json()) == 1

    response = client.put(
        f"/api/services/dependencies/{dependency['id']}",
        json={
            "depends_on_service_id": upstream.id,
            "dependency_type": "soft",
            "criticality": "important",
            "enabled": False,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["dependency_type"] == "soft"

    response = client.delete(
        f"/api/services/dependencies/{dependency['id']}",
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["deleted"] is True


def test_service_aggregate_links_runbooks_and_dependencies_api(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(team, slug="rabbitmq-cloud", name="RabbitMQ Cloud")
    upstream = create_service(team, slug="network-prod", name="Network Prod")

    ServiceLink.create(
        service=service,
        link_type="dashboard",
        label="Grafana",
        url="https://grafana.example.com",
        priority=10,
        enabled=True,
    )
    ServiceRunbook.create(
        service=service,
        title="RabbitMQ runbook",
        url="https://docs.example.com/runbooks/rabbitmq",
        priority=10,
        enabled=True,
        matchers={},
    )
    ServiceDependency.create(
        service=service,
        depends_on_service=upstream,
        dependency_type="hard",
        criticality="required",
        enabled=True,
    )

    response = client.get(
        f"/api/services/links?service_id={service.id}",
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert len(response.get_json()) == 1

    response = client.get(
        f"/api/services/runbooks?service_id={service.id}",
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert len(response.get_json()) == 1

    response = client.get(
        f"/api/services/dependencies?service_id={service.id}",
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert len(response.get_json()) == 1


def create_service_alert_group(
    *,
    team,
    route,
    service,
    fingerprint="service-alert-group",
    status="firing",
    severity="critical",
    alertname="ServiceAlert",
    summary="Service alert",
):
    now = datetime.utcnow()

    labels = {
        "alertname": alertname,
        "severity": severity,
        "service": service.slug,
    }

    return AlertGroup.create(
        team=team,
        route=route,
        service=service,
        source="pytest",
        group_key_hash=fingerprint,
        group_key=fingerprint,
        title=alertname,
        message=summary,
        severity=severity,
        common_labels=labels,
        label_values=labels,
        payload_summary={
            "summary": summary,
            "alertname": alertname,
            "severity": severity,
        },
        status=status,
        first_seen_at=now,
        last_seen_at=now,
        alert_count=1,
        firing_count=1 if status == "firing" else 0,
        acknowledged_count=1 if status == "acknowledged" else 0,
        resolved_count=1 if status == "resolved" else 0,
        silenced_count=1 if status == "silenced" else 0,
    )


def test_service_details_returns_aggregated_context(client, admin_headers):
    group = create_group()
    team = create_team(group)

    service = create_service(
        team,
        slug="billing-api",
        name="Billing API",
        status="degraded",
        criticality="critical",
        environment="production",
    )
    upstream = create_service(
        team,
        slug="postgresql-prod",
        name="PostgreSQL Prod",
    )
    downstream = create_service(
        team,
        slug="frontend-web",
        name="Frontend Web",
    )
    route = create_route(team, service=service)

    ServiceLink.create(
        service=service,
        link_type="dashboard",
        label="Grafana",
        url="https://grafana.example.com/d/billing-api",
        priority=10,
        enabled=True,
    )

    ServiceRunbook.create(
        service=service,
        title="Billing API runbook",
        url="https://docs.example.com/runbooks/billing-api",
        priority=10,
        enabled=True,
        matchers={},
    )

    ServiceDependency.create(
        service=service,
        depends_on_service=upstream,
        dependency_type="hard",
        criticality="required",
        enabled=True,
    )

    ServiceDependency.create(
        service=downstream,
        depends_on_service=service,
        dependency_type="soft",
        criticality="important",
        enabled=True,
    )

    create_service_alert_group(
        team=team,
        route=route,
        service=service,
        fingerprint="billing-api-critical-details",
        status="firing",
        severity="critical",
        alertname="BillingApiDown",
        summary="Billing API is down",
    )

    response = client.get(
        f"/api/services/{service.id}/details?days=30",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    data = response.get_json()

    assert data["service"]["id"] == service.id
    assert data["service"]["slug"] == "billing-api"

    assert data["summary"]["links"] == 1
    assert data["summary"]["runbooks"] == 1
    assert data["summary"]["upstream_dependencies"] == 1
    assert data["summary"]["downstream_dependencies"] == 1

    assert data["summary"]["alerts"]["total"] == 1
    assert data["summary"]["alerts"]["recent"] == 1
    assert data["summary"]["alerts"]["open"] == 1
    assert data["summary"]["alerts"]["firing"] == 1
    assert data["summary"]["alerts"]["critical_open"] == 1

    assert data["summary"]["alerts"]["by_status"]["firing"] == 1
    assert data["summary"]["alerts"]["by_status"]["acknowledged"] == 0
    assert data["summary"]["alerts"]["by_status"]["resolved"] == 0

    assert data["summary"]["alerts"]["by_severity"]["critical"] == 1
    assert data["summary"]["alerts"]["by_severity"]["high"] == 0
    assert data["summary"]["alerts"]["by_severity"]["warning"] == 0
    assert data["summary"]["alerts"]["by_severity"]["info"] == 0

    assert len(data["links"]) == 1
    assert data["links"][0]["label"] == "Grafana"
    assert data["links"][0]["link_type"] == "dashboard"

    assert len(data["runbooks"]) == 1
    assert data["runbooks"][0]["title"] == "Billing API runbook"

    assert len(data["dependencies"]["upstream"]) == 1
    assert data["dependencies"]["upstream"][0]["service_id"] == service.id
    assert data["dependencies"]["upstream"][0]["depends_on_service_id"] == upstream.id

    assert len(data["dependencies"]["downstream"]) == 1
    assert data["dependencies"]["downstream"][0]["service_id"] == downstream.id
    assert data["dependencies"]["downstream"][0]["depends_on_service_id"] == service.id

    assert data["analytics"]["version"] == 1
    assert data["analytics"]["window"]["days"] == 30
    assert data["analytics"]["widgets"]["alert_volume"]["total"] == 1
    assert data["analytics"]["widgets"]["alert_volume"]["recent"] == 1
    assert data["analytics"]["widgets"]["alert_volume"]["open"] == 1
    assert data["analytics"]["widgets"]["alert_volume"]["critical_open"] == 1
    assert data["analytics"]["breakdowns"]["alerts_by_status"]["firing"] == 1
    assert data["analytics"]["breakdowns"]["alerts_by_severity"]["critical"] == 1


def make_headers(user):
    token, _ = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


def test_service_details_requires_team_read(client, db):
    private_group = create_group(slug=unique("private-group"))
    private_team = create_team(
        group=private_group,
        slug=unique("private-team"),
        name="Private Team",
    )
    service = create_service(
        private_team,
        slug=unique("private-service"),
        name="Private Service",
    )

    other_group = create_group(slug=unique("other-group"))
    other_user = create_user(
        username=unique("service-reader"),
        group=other_group,
    )

    response = client.get(
        f"/api/services/{service.id}/details",
        headers=make_headers(other_user),
    )

    assert response.status_code in {403, 404}


def test_service_details_clamps_analytics_days(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(team, slug="billing-api", name="Billing API")

    response = client.get(
        f"/api/services/{service.id}/details?days=9999",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    data = response.get_json()

    assert data["analytics"]["version"] == 1
    assert data["analytics"]["window"]["days"] == 365
    assert data["summary"]["alerts"]["window_days"] == 365


def test_service_impact_rejects_invalid_max_depth(client, admin_headers):
    response = client.get(
        "/api/services/impact?max_depth=999",
        headers=admin_headers,
    )

    assert response.status_code == 400

    data = response.get_json()

    assert data["error"] == "validation_error"
    assert data["message"] == "Request validation failed"
    assert any(
        detail["field"] == "max_depth"
        for detail in data["details"]
    )


def test_service_impact_rejects_invalid_sort(client, admin_headers):
    response = client.get(
        "/api/services/impact?sort=created_at",
        headers=admin_headers,
    )

    assert response.status_code == 400

    data = response.get_json()

    assert data["error"] == "validation_error"
    assert any(
        detail["field"] == "sort"
        for detail in data["details"]
    )


def test_service_impact_accepts_valid_query(client, admin_headers):
    group = create_group()
    team = create_team(group)
    create_service(
        team,
        slug=unique("billing-api"),
        name="Billing API",
    )

    response = client.get(
        "/api/services/impact"
        "?team_id={team_id}"
        "&include_disabled=false"
        "&include_operational=true"
        "&include_explanation=true"
        "&include_root_causes=true"
        "&include_blast_radius=true"
        "&include_paths=true"
        "&max_depth=5"
        "&limit=100"
        "&sort=effective_status"
        "&order=desc".format(team_id=team.id),
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()


def find_impact_item(payload, service):
    for item in payload["items"]:
        if item["service_id"] == service.id:
            return item

    raise AssertionError(
        "Impact item for service {0} was not found in payload: {1}".format(
            service.slug,
            payload,
        )
    )


def impact_path_slugs(path):
    return [node["service_slug"] for node in path]


def test_service_impact_v2_propagates_direct_upstream_critical_alert(
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
        f"/api/services/impact?team_id={team.id}&include_operational=true",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()
    billing_item = find_impact_item(payload, billing)
    database_item = find_impact_item(payload, database)

    assert payload["version"] == 2

    assert database_item["effective_status"] == "major_outage"
    assert database_item["primary_reason"] == "alert_group"
    assert database_item["open_alert_groups"] == 1
    assert database_item["critical_open_alert_groups"] == 1

    assert billing_item["effective_status"] == "major_outage"
    assert billing_item["dependency_impact_status"] == "major_outage"
    assert billing_item["primary_reason"] == "upstream_dependency"
    assert billing_item["upstream_issues_count"] == 1

    assert billing_item["root_causes"]
    assert billing_item["root_causes"][0]["service_id"] == database.id
    assert billing_item["root_causes"][0]["reason"] == "alert_group"
    assert billing_item["root_causes"][0]["effective_status"] == "major_outage"

    assert billing_item["explanation"]["primary_reason"] == "upstream_dependency"
    assert billing_item["explanation"]["primary_source_service_id"] == database.id
    assert billing_item["explanation"]["paths"]

    first_path = billing_item["explanation"]["paths"][0]
    assert impact_path_slugs(first_path) == [billing.slug, database.slug]


def test_service_impact_v2_builds_transitive_root_cause_path(
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
    frontend = create_service(
        team,
        slug=unique("frontend-web"),
        name="Frontend Web",
        criticality="high",
        tier="tier_1",
    )

    create_service_dependency(
        service=billing,
        depends_on_service=database,
        dependency_type="hard",
        criticality="required",
    )
    create_service_dependency(
        service=frontend,
        depends_on_service=billing,
        dependency_type="soft",
        criticality="important",
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
        f"/api/services/impact?team_id={team.id}&include_operational=true&max_depth=5",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()
    frontend_item = find_impact_item(payload, frontend)

    assert frontend_item["primary_reason"] == "upstream_dependency"
    assert frontend_item["effective_status"] == "partial_outage"
    assert frontend_item["dependency_impact_status"] == "partial_outage"
    assert frontend_item["upstream_issues_count"] == 1

    assert frontend_item["root_causes"]
    assert frontend_item["root_causes"][0]["service_id"] == database.id
    assert frontend_item["root_causes"][0]["effective_status"] == "major_outage"

    assert frontend_item["explanation"]["paths"]
    first_path = frontend_item["explanation"]["paths"][0]

    assert impact_path_slugs(first_path) == [
        frontend.slug,
        billing.slug,
        database.slug,
    ]

    assert first_path[1]["dependency_type"] == "soft"
    assert first_path[1]["dependency_criticality"] == "important"
    assert first_path[2]["dependency_type"] == "hard"
    assert first_path[2]["dependency_criticality"] == "required"


def test_service_impact_v2_calculates_blast_radius(
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
    frontend = create_service(
        team,
        slug=unique("frontend-web"),
        name="Frontend Web",
        criticality="high",
        tier="tier_1",
    )

    create_service_dependency(
        service=billing,
        depends_on_service=database,
        dependency_type="hard",
        criticality="required",
    )
    create_service_dependency(
        service=frontend,
        depends_on_service=billing,
        dependency_type="soft",
        criticality="important",
    )

    response = client.get(
        f"/api/services/impact?team_id={team.id}&include_operational=true&max_depth=5",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()
    database_item = find_impact_item(payload, database)

    blast_radius = database_item["blast_radius"]

    assert blast_radius["direct_downstream"] == 1
    assert blast_radius["transitive_downstream"] == 2
    assert blast_radius["critical_downstream"] == 2
    assert blast_radius["tier_1_downstream"] == 2
    assert blast_radius["affected_downstream"] == 2
    assert blast_radius["cycle_detected"] is False
    assert blast_radius["depth_limited"] is False

    paths = [
        impact_path_slugs(path)
        for path in blast_radius["paths"]
    ]

    assert [database.slug, billing.slug] in paths
    assert [database.slug, billing.slug, frontend.slug] in paths



def test_service_impact_v2_detects_dependency_cycles(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)

    service_a = create_service(
        team,
        slug=unique("service-a"),
        name="Service A",
    )
    service_b = create_service(
        team,
        slug=unique("service-b"),
        name="Service B",
    )

    create_service_dependency(
        service=service_a,
        depends_on_service=service_b,
        dependency_type="hard",
        criticality="required",
    )
    create_service_dependency(
        service=service_b,
        depends_on_service=service_a,
        dependency_type="hard",
        criticality="required",
    )

    create_impact_alert_group(
        team=team,
        service=service_b,
        status="firing",
        severity="critical",
        alertname="ServiceBDown",
        summary="Service B is down",
    )

    response = client.get(
        f"/api/services/impact?team_id={team.id}&include_operational=true&max_depth=5",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()
    service_a_item = find_impact_item(payload, service_a)
    service_b_item = find_impact_item(payload, service_b)

    assert service_a_item["cycle_detected"] is True
    assert service_b_item["cycle_detected"] is True
    assert payload["summary"]["cycle_detected"] >= 1

    assert service_a_item["explanation"]["paths"]


def test_service_impact_v2_marks_depth_limited_paths(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)

    database = create_service(
        team,
        slug=unique("postgresql-prod"),
        name="PostgreSQL Prod",
    )
    billing = create_service(
        team,
        slug=unique("billing-api"),
        name="Billing API",
    )
    frontend = create_service(
        team,
        slug=unique("frontend-web"),
        name="Frontend Web",
    )

    create_service_dependency(
        service=billing,
        depends_on_service=database,
        dependency_type="hard",
        criticality="required",
    )
    create_service_dependency(
        service=frontend,
        depends_on_service=billing,
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
        f"/api/services/impact?team_id={team.id}&include_operational=true&max_depth=1",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()
    frontend_item = find_impact_item(payload, frontend)

    assert frontend_item["depth_limited"] is True
    assert payload["summary"]["depth_limited"] >= 1


def test_service_impact_v2_optional_dependency_downgrades_major_to_degraded(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)

    external_api = create_service(
        team,
        slug=unique("external-api"),
        name="External API",
    )
    billing = create_service(
        team,
        slug=unique("billing-api"),
        name="Billing API",
    )

    create_service_dependency(
        service=billing,
        depends_on_service=external_api,
        dependency_type="external",
        criticality="optional",
    )

    create_impact_alert_group(
        team=team,
        service=external_api,
        status="firing",
        severity="critical",
        alertname="ExternalApiDown",
        summary="External API is down",
    )

    response = client.get(
        f"/api/services/impact?team_id={team.id}&include_operational=true",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()
    billing_item = find_impact_item(payload, billing)

    assert billing_item["primary_reason"] == "upstream_dependency"
    assert billing_item["dependency_impact_status"] == "degraded"
    assert billing_item["effective_status"] == "degraded"
    assert billing_item["root_causes"][0]["effective_status"] == "major_outage"


def test_service_impact_v2_soft_dependency_reduces_major_outage(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)

    database = create_service(
        team,
        slug=unique("postgresql-prod"),
        name="PostgreSQL Prod",
    )
    billing = create_service(
        team,
        slug=unique("billing-api"),
        name="Billing API",
    )

    create_service_dependency(
        service=billing,
        depends_on_service=database,
        dependency_type="soft",
        criticality="important",
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
        f"/api/services/impact?team_id={team.id}&include_operational=true",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()
    billing_item = find_impact_item(payload, billing)

    assert billing_item["primary_reason"] == "upstream_dependency"
    assert billing_item["dependency_impact_status"] == "partial_outage"
    assert billing_item["effective_status"] == "partial_outage"
    assert billing_item["root_causes"][0]["effective_status"] == "major_outage"


def test_service_impact_v2_ignores_disabled_upstream_service(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)

    database = create_service(
        team,
        slug=unique("postgresql-prod"),
        name="PostgreSQL Prod",
    )
    database.enabled = False
    database.save()

    billing = create_service(
        team,
        slug=unique("billing-api"),
        name="Billing API",
    )

    create_service_dependency(
        service=billing,
        depends_on_service=database,
        dependency_type="hard",
        criticality="required",
    )

    response = client.get(
        f"/api/services/impact?team_id={team.id}&include_operational=true",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()
    billing_item = find_impact_item(payload, billing)

    assert billing_item["effective_status"] == "operational"
    assert billing_item["dependency_impact_status"] == "operational"
    assert billing_item["primary_reason"] == "none"
    assert billing_item["upstream_issues_count"] == 0


def test_service_impact_v2_ignores_disabled_dependency(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)

    database = create_service(
        team,
        slug=unique("postgresql-prod"),
        name="PostgreSQL Prod",
    )
    billing = create_service(
        team,
        slug=unique("billing-api"),
        name="Billing API",
    )

    create_service_dependency(
        service=billing,
        depends_on_service=database,
        dependency_type="hard",
        criticality="required",
        enabled=False,
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
        f"/api/services/impact?team_id={team.id}&include_operational=true",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()
    billing_item = find_impact_item(payload, billing)
    database_item = find_impact_item(payload, database)

    assert database_item["effective_status"] == "major_outage"

    assert billing_item["effective_status"] == "operational"
    assert billing_item["dependency_impact_status"] == "operational"
    assert billing_item["primary_reason"] == "none"
    assert billing_item["upstream_issues_count"] == 0
    assert billing_item["root_causes"] == []


def test_service_impact_v2_ignores_silenced_alert_groups(
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
        status="silenced",
        severity="critical",
        alertname="BillingApiSilenced",
        summary="Silenced alert should not affect impact",
    )

    response = client.get(
        f"/api/services/impact?team_id={team.id}&include_operational=true",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()
    item = find_impact_item(payload, service)

    assert item["effective_status"] == "operational"
    assert item["primary_reason"] == "none"
    assert item["open_alert_groups"] == 0
    assert item["critical_open_alert_groups"] == 0


def test_service_impact_v2_ignores_resolved_alert_groups(
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
        status="resolved",
        severity="critical",
        alertname="BillingApiResolved",
        summary="Resolved alert should not affect impact",
    )

    response = client.get(
        f"/api/services/impact?team_id={team.id}&include_operational=true",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()
    item = find_impact_item(payload, service)

    assert item["effective_status"] == "operational"
    assert item["primary_reason"] == "none"
    assert item["open_alert_groups"] == 0
    assert item["critical_open_alert_groups"] == 0


def test_service_details_includes_impact_v2_block(client, admin_headers):
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
        f"/api/services/{billing.id}/details?days=30",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    data = response.get_json()
    impact = data["impact"]

    assert impact["service_id"] == billing.id
    assert impact["effective_status"] == "major_outage"
    assert impact["primary_reason"] == "upstream_dependency"
    assert impact["upstream_issues_count"] == 1

    assert impact["root_causes"]
    assert impact["root_causes"][0]["service_id"] == database.id
    assert impact["root_causes"][0]["effective_status"] == "major_outage"

    assert impact["explanation"]["primary_reason"] == "upstream_dependency"
    assert impact["explanation"]["primary_source_service_id"] == database.id
    assert impact["explanation"]["paths"]

    assert impact["blast_radius"]["direct_downstream"] == 0
    assert impact["blast_radius"]["transitive_downstream"] == 0

    assert data["analytics"]["widgets"]["impact"]["effective_status"] == "major_outage"
    assert data["analytics"]["widgets"]["impact"]["primary_reason"] == "upstream_dependency"
