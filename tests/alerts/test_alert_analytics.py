from datetime import timedelta

from app.modules.common import utc_now
from app.modules.db.models import Alert, AlertGroup
from tests.factories import (
    create_group,
    create_route,
    create_service,
    create_team,
    unique,
)


def _analytics_group(
    *,
    team,
    route,
    service,
    alertname,
    status,
    first_seen_at,
    acknowledged_at=None,
    resolved_at=None,
    occurrences=1,
    maintenance_suppressed=False,
):
    group_key = unique("analytics-group")
    group = AlertGroup.create(
        team=team,
        route=route,
        service=service,
        source="pytest",
        group_key_hash=group_key,
        group_key=group_key,
        title=alertname,
        message=alertname + " test",
        severity="critical",
        common_labels={"alertname": alertname, "severity": "critical"},
        label_values={},
        payload_summary={"alertname": alertname},
        status=status,
        acknowledged_at=acknowledged_at,
        resolved_at=resolved_at,
        first_seen_at=first_seen_at,
        last_seen_at=resolved_at or acknowledged_at or first_seen_at,
        alert_count=occurrences,
        firing_count=occurrences if status == "firing" else 0,
        acknowledged_count=occurrences if status == "acknowledged" else 0,
        resolved_count=occurrences if status == "resolved" else 0,
        maintenance_suppressed=maintenance_suppressed,
    )

    for index in range(occurrences):
        alert_seen_at = first_seen_at + timedelta(minutes=index)
        Alert.create(
            team=team,
            route=route,
            service=service,
            group=group,
            source="pytest",
            external_id=unique("analytics-external"),
            dedup_key=unique("analytics-dedup"),
            group_key=group_key,
            title=alertname,
            message=alertname + " child",
            severity="critical",
            labels={"alertname": alertname, "severity": "critical"},
            payload={},
            status="resolved" if status == "resolved" else "firing",
            first_seen_at=alert_seen_at,
            last_seen_at=resolved_at or acknowledged_at or alert_seen_at,
            resolved_at=resolved_at if status == "resolved" else None,
        )

    return group


def test_alert_analytics_returns_noise_lifecycle_and_attention_metrics(
    client,
    admin_headers,
    db,
):
    now = utc_now().replace(microsecond=0)
    group = create_group()
    team = create_team(group)
    service = create_service(team, name="Billing API")
    route = create_route(team, service=service)

    acknowledged = _analytics_group(
        team=team,
        route=route,
        service=service,
        alertname="DiskFull",
        status="acknowledged",
        first_seen_at=now - timedelta(hours=4),
        acknowledged_at=now - timedelta(hours=3),
        occurrences=2,
    )
    resolved_without_ack = _analytics_group(
        team=team,
        route=route,
        service=service,
        alertname="CpuHigh",
        status="resolved",
        first_seen_at=now - timedelta(hours=3),
        resolved_at=now - timedelta(hours=1),
    )
    suppressed = _analytics_group(
        team=team,
        route=route,
        service=service,
        alertname="MaintenanceNoise",
        status="firing",
        first_seen_at=now - timedelta(hours=2),
        maintenance_suppressed=True,
    )
    stale = _analytics_group(
        team=team,
        route=route,
        service=service,
        alertname="ForgottenAlert",
        status="firing",
        first_seen_at=now - timedelta(days=40),
    )

    response = client.get(
        f"/api/alert-groups/analytics?team_id={team.id}&days=7&limit=10",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()

    assert payload["version"] == 1
    assert payload["window"]["days"] == 7

    summary = payload["summary"]
    assert summary["alert_groups"] == 3
    assert summary["occurrences"] == 4
    assert summary["open_now"] == 3
    assert summary["unacknowledged"] == 1
    assert summary["ack_rate"] == 0.5
    assert summary["resolved_without_ack"] == 1
    assert summary["mtta_seconds_p50"] == 3600
    assert summary["mtta_seconds_p95"] == 3600
    assert summary["mttr_seconds_p50"] == 7200
    assert summary["mttr_seconds_p95"] == 7200

    top_noisy = payload["top_noisy"][0]
    assert top_noisy["alertname"] == "DiskFull"
    assert top_noisy["occurrences"] == 2
    assert top_noisy["groups"] == 1
    assert top_noisy["dedup_ratio"] == 2
    assert top_noisy["open"] == 1
    assert top_noisy["ack_rate"] == 1.0

    assert payload["oldest_unresolved"][0]["id"] == stale.id
    assert suppressed.id not in {
        row["id"]
        for row in payload["oldest_unresolved"]
    }

    assert [
        row["id"]
        for row in payload["attention"]["unacknowledged"]
    ] == [stale.id]
    assert [
        row["id"]
        for row in payload["attention"]["resolved_without_ack"]
    ] == [resolved_without_ack.id]

    resolved_health = payload["attention"]["resolved_without_ack_by_alert"]
    assert resolved_health == [{
        "alertname": "CpuHigh",
        "resolved_groups": 1,
        "resolved_without_ack": 1,
        "rate": 1.0,
        "median_lifetime_seconds": 7200,
    }]

    lifecycle = payload["series"]["lifecycle_by_day"]
    assert sum(row["created"] for row in lifecycle) == 3
    assert sum(row["acknowledged"] for row in lifecycle) == 1
    assert sum(row["resolved"] for row in lifecycle) == 1

    assert acknowledged.id != stale.id


def test_alert_analytics_aggregates_resolved_without_ack_by_alertname(
    client,
    admin_headers,
    db,
):
    now = utc_now().replace(microsecond=0)
    group = create_group()
    team = create_team(group)
    service = create_service(team, name="Payments API")
    route = create_route(team, service=service)

    _analytics_group(
        team=team,
        route=route,
        service=service,
        alertname="QueueBacklog",
        status="resolved",
        first_seen_at=now - timedelta(hours=4),
        resolved_at=now - timedelta(hours=2),
    )
    _analytics_group(
        team=team,
        route=route,
        service=service,
        alertname="QueueBacklog",
        status="resolved",
        first_seen_at=now - timedelta(hours=3),
        acknowledged_at=now - timedelta(hours=2, minutes=30),
        resolved_at=now - timedelta(hours=1),
    )

    response = client.get(
        f"/api/alert-groups/analytics?team_id={team.id}&days=7&limit=10",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()
    rows = response.get_json()["attention"]["resolved_without_ack_by_alert"]

    assert rows == [{
        "alertname": "QueueBacklog",
        "resolved_groups": 2,
        "resolved_without_ack": 1,
        "rate": 0.5,
        "median_lifetime_seconds": 7200,
    }]


def test_alert_analytics_rejects_invalid_window(client, admin_headers, db):
    response = client.get(
        "/api/alert-groups/analytics?days=366",
        headers=admin_headers,
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["error"] == "validation_error"
    assert any(detail.get("field") == "days" for detail in payload.get("details", []))
