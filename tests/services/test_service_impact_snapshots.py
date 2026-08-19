from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.modules.db.models import ServiceImpactSnapshot, ServiceImpactSnapshotItem
from app.services.service_catalog import impact_snapshots
from tests.factories import (
    create_group,
    create_impact_alert_group,
    create_service,
    create_service_dependency,
    create_team,
)
from app.modules.common import utc_now


@pytest.fixture(autouse=True)
def clean_impact_snapshots(db):
    ServiceImpactSnapshotItem.delete().execute()
    ServiceImpactSnapshot.delete().execute()
    yield
    ServiceImpactSnapshotItem.delete().execute()
    ServiceImpactSnapshot.delete().execute()


def _impact_query(**overrides):
    values = {
        "team_id": None,
        "service_id": None,
        "include_disabled": False,
        "include_operational": True,
        "include_explanation": True,
        "include_root_causes": True,
        "include_blast_radius": True,
        "include_paths": True,
        "max_depth": 5,
        "limit": 100,
        "sort": "effective_status",
        "order": "desc",
        "bucket": "day",
        "days": 30,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _create_cloud_catalog():
    group = create_group(name="Operations", slug="ops")
    team = create_team(group, name="Cloud OPS", slug="cloud")
    postgres = create_service(
        team,
        name="Cloud Postgres",
        slug="cloud-pgsql",
        service_type="database",
        criticality="critical",
        tier="tier_1",
        status="major_outage",
    )
    api = create_service(
        team,
        name="Cloud API",
        slug="cloud-api",
        service_type="api",
        criticality="high",
        tier="tier_2",
        status="operational",
    )
    create_service_dependency(
        service=api,
        depends_on_service=postgres,
        dependency_type="hard",
        criticality="required",
    )
    create_impact_alert_group(
        team=team,
        service=postgres,
        status="firing",
        severity="critical",
        alertname="PostgresDown",
        summary="Postgres is unavailable",
    )
    return SimpleNamespace(group=group, team=team, postgres=postgres, api=api)


def _create_snapshot(*, team, captured_at, services_count=1, affected_services=1, **fields):
    values = {
        "team": team,
        "source": "scheduler",
        "captured_at": captured_at,
        "services_count": services_count,
        "affected_services": affected_services,
        "summary": {},
        "filters": {},
        "payload": {},
    }
    values.update(fields)
    return ServiceImpactSnapshot.create(**values)


def _create_snapshot_item(snapshot, service, *, effective_status, primary_reason, **fields):
    values = {
        "snapshot": snapshot,
        "group": service.group,
        "team": service.team,
        "service": service,
        "captured_at": snapshot.captured_at,
        "service_slug": service.slug,
        "service_name": service.name,
        "team_slug": service.team.slug,
        "team_name": service.team.name,
        "effective_status": effective_status,
        "primary_reason": primary_reason,
    }
    values.update(fields)
    return ServiceImpactSnapshotItem.create(**values)


def test_capture_service_impact_snapshot_uses_current_impact_data(db):
    catalog = _create_cloud_catalog()

    snapshot = impact_snapshots.capture_service_impact_snapshot(
        _impact_query(team_id=catalog.team.id),
        team_ids=[catalog.team.id],
        source="manual",
    )

    assert snapshot["source"] == "manual"
    assert snapshot["scope"] == "team"
    assert snapshot["team_id"] == catalog.team.id
    assert snapshot["services_count"] == 2
    assert snapshot["affected_services"] == 2
    assert snapshot["major_outage_services"] == 2
    assert snapshot["own_status_impacted_services"] == 1
    assert snapshot["dependency_impacted_services"] == 1
    assert snapshot["open_alert_groups_total"] == 1
    assert snapshot["critical_open_alert_groups_total"] == 1
    assert len(snapshot["items"]) == 2

    api_item = ServiceImpactSnapshotItem.get(
        ServiceImpactSnapshotItem.service == catalog.api.id
    )
    assert api_item.effective_status == "major_outage"
    assert api_item.primary_reason == "upstream_dependency"
    assert api_item.upstream_issues_count == 1
    assert api_item.root_causes[0]["service_id"] == catalog.postgres.id
    assert api_item.payload["service_slug"] == "cloud-api"


def test_list_service_impact_snapshots_filters_by_readable_items(db):
    catalog = _create_cloud_catalog()

    other_group = create_group(name="Other", slug="other")
    other_team = create_team(other_group, name="Other Team", slug="other-team")
    other_service = create_service(other_team, name="Other API", slug="other-api")

    visible_snapshot = _create_snapshot(
        team=catalog.team,
        captured_at=utc_now(),
    )
    _create_snapshot_item(
        visible_snapshot,
        catalog.api,
        effective_status="major_outage",
        primary_reason="upstream_dependency",
    )

    hidden_snapshot = _create_snapshot(
        team=other_team,
        captured_at=utc_now(),
    )
    _create_snapshot_item(
        hidden_snapshot,
        other_service,
        effective_status="degraded",
        primary_reason="own_status",
    )

    result = impact_snapshots.list_service_impact_snapshots(
        _impact_query(days=7, limit=50),
        team_ids=[catalog.team.id],
    )

    assert [item["id"] for item in result["items"]] == [visible_snapshot.id]


def test_build_service_impact_history_aggregates_snapshots_and_top_services(db):
    catalog = _create_cloud_catalog()
    first_captured_at = utc_now() - timedelta(hours=2)
    second_captured_at = utc_now() - timedelta(hours=1)

    first = _create_snapshot(
        team=catalog.team,
        captured_at=first_captured_at,
        services_count=2,
        affected_services=1,
        dependency_impacted_services=1,
        open_alert_groups_total=1,
        summary={
            "by_effective_status": {"major_outage": 1, "operational": 1},
            "by_primary_reason": {"upstream_dependency": 1},
        },
    )
    second = _create_snapshot(
        team=catalog.team,
        captured_at=second_captured_at,
        services_count=2,
        affected_services=2,
        critical_services=1,
        major_outage_services=1,
        own_status_impacted_services=1,
        dependency_impacted_services=1,
        open_alert_groups_total=3,
        summary={
            "by_effective_status": {"major_outage": 1, "degraded": 1},
            "by_primary_reason": {"own_status": 1, "upstream_dependency": 1},
        },
    )

    _create_snapshot_item(
        first,
        catalog.api,
        effective_status="major_outage",
        primary_reason="upstream_dependency",
        open_alert_groups=1,
    )
    _create_snapshot_item(
        second,
        catalog.api,
        effective_status="degraded",
        primary_reason="upstream_dependency",
        open_alert_groups=1,
        upstream_issues_count=1,
    )
    _create_snapshot_item(
        second,
        catalog.postgres,
        effective_status="major_outage",
        primary_reason="own_status",
        open_alert_groups=2,
        critical_open_alert_groups=1,
    )

    result = impact_snapshots.build_service_impact_history(
        _impact_query(days=7, bucket="hour", limit=10),
        team_ids=[catalog.team.id],
    )

    assert result["summary"]["snapshots"] == 2
    assert result["summary"]["latest_affected_services"] == 2
    assert result["summary"]["max_affected_services"] == 2
    assert len(result["series"]["impact_by_bucket"]) == 2
    assert result["series"]["impact_by_bucket"][-1]["affected_max"] == 2
    assert result["series"]["reason_by_bucket"][-1]["own_status"] == 1
    assert result["top_services"][0]["service_id"] == catalog.api.id
    assert result["top_services"][0]["affected_samples"] == 2
    assert result["latest_snapshot"]["id"] == second.id


def test_cleanup_service_impact_snapshots_deletes_old_rows(db):
    catalog = _create_cloud_catalog()

    old_snapshot = _create_snapshot(
        team=catalog.team,
        captured_at=utc_now() - timedelta(days=40),
    )
    _create_snapshot_item(
        old_snapshot,
        catalog.api,
        effective_status="degraded",
        primary_reason="upstream_dependency",
    )

    fresh_snapshot = _create_snapshot(
        team=catalog.team,
        captured_at=utc_now(),
        affected_services=0,
    )
    _create_snapshot_item(
        fresh_snapshot,
        catalog.postgres,
        effective_status="operational",
        primary_reason="none",
    )

    deleted = impact_snapshots.cleanup_service_impact_snapshots(retention_days=30)

    assert deleted == 1
    assert ServiceImpactSnapshot.select().where(ServiceImpactSnapshot.id == old_snapshot.id).count() == 0
    assert ServiceImpactSnapshotItem.select().where(ServiceImpactSnapshotItem.snapshot == old_snapshot).count() == 0
    assert ServiceImpactSnapshot.select().where(ServiceImpactSnapshot.id == fresh_snapshot.id).count() == 1


def test_create_service_impact_snapshot_api_returns_created_snapshot(
    client,
    auth_headers,
    db,
):
    catalog = _create_cloud_catalog()

    response = client.post(
        "/api/services/impact/snapshots",
        json={"team_id": catalog.team.id, "include_operational": True},
        headers=auth_headers,
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["source"] == "manual"
    assert payload["scope"] == "team"
    assert payload["team_id"] == catalog.team.id
    assert payload["services_count"] == 2
    assert payload["affected_services"] == 2
    assert len(payload["items"]) == 2
